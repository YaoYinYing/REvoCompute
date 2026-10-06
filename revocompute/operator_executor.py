# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The Host Operator Executor boundary: the narrowest way the Web triggers host ops.

Many operator actions are host-level (building a SIF, validating against the
target scheduler) while the web process may itself run inside a container.  The
Web application must never be given a Docker socket, arbitrary host filesystem
access, unrestricted sudo, a generic host shell, or unrestricted Slurm/Apptainer
command construction — so a Web-triggered operation crosses a boundary that only
understands the closed typed action vocabulary.

The boundary is deliberately thin: it reuses the deployment controller the host
already trusts (``run/restart.sh``) as a *local* subprocess with a fixed argv
built from a table, an allowlisted environment, and a bounded working directory.
There is no daemon, no socket, no network surface, and no command text — an
action that has no stable host command is refused rather than approximated.  The
executor also owns the supported degraded mode: when the host controller is not
reachable, mutation actions fail closed and observability is unaffected.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from revocompute.operator_actions import OperatorAction, OperatorActionError, get_action, normalize_parameters
from revocompute.runner_host import HostPaths

#: Environment keys the deployment controller legitimately reads.  Everything
#: else in the ambient environment (tokens, cloud credentials, host secrets) is
#: withheld from the subprocess.
_ENV_ALLOWLIST = (
    "HOME",
    "LANG",
    "LC_ALL",
    "LOGNAME",
    "PATH",
    "REVODESIGN_PYTHON",
    "REVODESIGN_SERVER_ENV",
    "SERVER_DIR",
    "CONFIG_DIR",
    "LOG_DIR",
    "TMPDIR",
    "USER",
)

#: The fixed host command each action maps to.  An action absent here has no
#: stable host command today, so the executor refuses it instead of guessing.
_HOST_COMMAND: dict[str, tuple[str, ...]] = {
    "runner.status": ("runner-status",),
    "runner.live_test": ("live-test",),
}

#: Actions that locate their target with a Runner family argument.
_FAMILY_ARGUMENT: dict[str, tuple[str, ...]] = {
    "runner.status": ("--runner",),
    "runner.live_test": ("--runner",),
}

_MAX_LOG_BYTES = 65536

#: A secret-named assignment printed inline in a subprocess log.
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b([A-Za-z0-9_]*(?:secret|password|passwd|token|credential)[A-Za-z0-9_]*)\s*=\s*([^\s]+)"
)
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class ExecutorUnavailable(RuntimeError):
    """The host controller is not reachable, so a mutation cannot be attempted.

    This is the supported degraded mode: the caller must fail closed (never
    fabricate, clear, or rewrite readiness) and report the state to the operator.
    """


class UnsupportedOperation(OperatorActionError):
    """The action has no stable host command, so it is refused rather than guessed."""


@dataclass(frozen=True, slots=True)
class ExecutorConfig:
    """A resolved, bounded host-controller invocation.

    ``command`` is a fixed argv prefix; the executor appends only table-derived
    arguments.  ``working_directory`` and ``env_file`` are absolute paths bounded
    to the deployment tree.
    """

    command: tuple[str, ...]
    env_file: str
    working_directory: str
    timeout_seconds: float = 1800.0


@dataclass(frozen=True, slots=True)
class ExecutorAvailability:
    available: bool
    reason: str


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """A structured, redacted record of one bounded host operation."""

    action_id: str
    runner_family: str
    argv_shape: tuple[str, ...]
    returncode: int
    log_text: str
    succeeded: bool


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (ValueError, OSError):
        return False
    return True


def resolve_executor(host: HostPaths) -> ExecutorConfig | None:
    """Resolve the bounded host controller, or ``None`` when it is unreachable.

    The command, env file, and working directory must all exist inside the
    deployment tree; a configured path outside it is treated as unavailable
    rather than followed.
    """
    root = Path(host.server_root())
    entrypoint = root / "run" / "restart.sh"
    if not entrypoint.is_file() or not _is_relative_to(entrypoint, root):
        return None
    # The env file may sit inside the checkout or be named explicitly by an
    # operator; either way it must be a real file the controller can read.
    env_file = os.environ.get("REVODESIGN_SERVER_ENV") or str(root / ".env.production")
    if not Path(env_file).is_file():
        return None
    interpreter = os.environ.get("REVODESIGN_PYTHON") or "python3"
    return ExecutorConfig(
        command=(interpreter, str(entrypoint)),
        env_file=str(Path(env_file)),
        working_directory=str(root),
    )


def availability(host: HostPaths) -> ExecutorAvailability:
    """Whether host operations can be attempted, as a capability separate from readiness."""
    config = resolve_executor(host)
    if config is None:
        return ExecutorAvailability(False, "operator_executor_unavailable")
    return ExecutorAvailability(True, "operator_executor_available")


def build_host_argv(config: ExecutorConfig, action_id: str, parameters: Mapping[str, object]) -> tuple[str, ...]:
    """Build the fixed argv for one action.  Never shell-interpreted.

    Only the table-declared subcommand and its bounded ``--runner``/``--collection``
    arguments are appended; the family value is re-validated as an identifier so
    a value that reaches here can never become a second argv word, an option, or
    a path.
    """
    action = get_action(action_id)
    subcommand = _HOST_COMMAND.get(action.id)
    if subcommand is None:
        raise UnsupportedOperation(f"{action.id} has no host command on this deployment")
    normalized = normalize_parameters(action, parameters)
    argv: list[str] = [*config.command, *subcommand]
    for flag in _FAMILY_ARGUMENT.get(action.id, ()):
        family = normalized.get("runner_family")
        if family is None:
            raise UnsupportedOperation(f"{action.id} requires a Runner family")
        argv.extend((flag, str(family)))
    collection = normalized.get("collection")
    if collection is not None:
        argv.extend(("--collection", str(collection)))
    return tuple(argv)


def _child_environment(host: HostPaths, config: ExecutorConfig) -> dict[str, str]:
    """The allowlisted environment the subprocess receives."""
    ambient = host.exported()
    environment = {key: ambient[key] for key in _ENV_ALLOWLIST if key in ambient}
    environment["REVODESIGN_SERVER_ENV"] = config.env_file
    environment.setdefault("HOME", os.path.expanduser("~"))
    environment.setdefault("PATH", os.defpath)
    return environment


def _redact(text: str) -> str:
    """Remove secret-bearing ``key=value`` pairs and control characters.

    A failed build or validation routinely prints its environment, so the
    boundary redacts the value of any secret-named assignment before the log is
    returned, and strips control characters that could forge a log line.
    """
    cleaned = _CONTROL_CHARS.sub("", text or "")
    return _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=[redacted]", cleaned)


def _bound_output(text: str, limit: int = _MAX_LOG_BYTES) -> str:
    """Redact, normalize, and bound a subprocess log before it is returned."""
    cleaned = _redact(text)
    if len(cleaned.encode("utf-8", "replace")) <= limit:
        return cleaned
    encoded = cleaned.encode("utf-8", "replace")[:limit]
    return encoded.decode("utf-8", "ignore") + "\n...[truncated]"


def execute(
    host: HostPaths,
    *,
    action_id: str,
    runner_family: str,
    parameters: Mapping[str, object] | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> ExecutionResult:
    """Run one typed operation against the host controller, bounded and fail-closed.

    The caller must have revalidated its plan and re-resolved ``runner_family``
    from the registry before calling; this boundary never accepts a target it
    cannot name with the closed action vocabulary.  When the host controller is
    unreachable the operation fails closed with :class:`ExecutorUnavailable`
    rather than partially mutating readiness.
    """
    config = resolve_executor(host)
    if config is None:
        raise ExecutorUnavailable("Operator executor unavailable")
    action = get_action(action_id)
    normalized = normalize_parameters(action, {**(parameters or {}), "runner_family": runner_family})
    argv = build_host_argv(config, action_id, normalized)
    spawn = runner or subprocess.run
    try:
        completed = spawn(
            list(argv),
            env=_child_environment(host, config),
            cwd=config.working_directory,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=config.timeout_seconds,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ExecutorUnavailable("Operator executor unavailable") from exc
    except subprocess.TimeoutExpired:
        return ExecutionResult(
            action_id=action.id,
            runner_family=runner_family,
            argv_shape=tuple(argv[: len(config.command) + 1]),
            returncode=124,
            log_text="Operation exceeded its bounded wall-clock limit and was terminated.",
            succeeded=False,
        )
    log_text = _bound_output((completed.stdout or "") + (completed.stderr or ""))
    return ExecutionResult(
        action_id=action.id,
        runner_family=runner_family,
        argv_shape=tuple(argv[: len(config.command) + 1]),
        returncode=int(completed.returncode),
        log_text=log_text,
        succeeded=completed.returncode == 0,
    )


def executable_actions() -> tuple[str, ...]:
    """The actions this boundary can actually run on a host deployment."""
    return tuple(sorted(_HOST_COMMAND))


__all__ = [
    "ExecutionResult",
    "ExecutorAvailability",
    "ExecutorConfig",
    "ExecutorUnavailable",
    "UnsupportedOperation",
    "availability",
    "build_host_argv",
    "executable_actions",
    "execute",
    "resolve_executor",
]
