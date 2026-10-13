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

The executor is therefore available only where the controller itself runs: a
process on the deployment host with the checkout in place.  A containerized web
process is Unavailable *by design* — Compose mounts the deployment data tree
(``SERVER_DIR``), never the host checkout, and the web image ships neither Docker
nor Apptainer, so the controller could not be executed there even if it were
mounted.  Naming a deployment env file inside a container would only make
:func:`availability` claim a capability it cannot exercise.  Host mutations on a
containerized deployment go through the operator CLI (``run/restart.sh``), which
is the break-glass path, and that is the state the Admin surface reports.
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
    """The host controller cannot be resolved, so no mutation is attempted.

    This is the supported degraded mode: the caller must fail closed (never
    fabricate, clear, or rewrite readiness) and report the state to the operator.
    The message names the missing artifact by role -- ``run/restart.sh`` or the
    deployment env file -- never by absolute host path, so it is actionable
    without leaking the deployment layout.
    """


class UnsupportedOperation(OperatorActionError):
    """The action has no stable host command, so it is refused rather than guessed."""


@dataclass(frozen=True, slots=True)
class ExecutorConfig:
    """A resolved, bounded host-controller invocation.

    ``command`` is a fixed argv prefix; the executor appends only table-derived
    arguments.  ``working_directory`` is the bounded cwd and ``env_file`` the
    deployment env file the child is started with; both come from operator
    configuration, never from a request.
    """

    command: tuple[str, ...]
    env_file: str
    working_directory: str
    timeout_seconds: float = 1800.0


@dataclass(frozen=True, slots=True)
class ExecutorAvailability:
    """Whether a host operation can be planned and run, and why not when it cannot.

    ``reason`` is a stable machine code; ``unavailable_reason`` is the operator
    sentence behind it (``None`` when available), so the Admin surface can report
    *why* mutations are disabled instead of a bare "unavailable".
    """

    available: bool
    reason: str
    unavailable_reason: str | None = None


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


def _server_root(host: HostPaths) -> Path:
    """The checkout the deployment controller runs from.

    The deployment env file lives in that checkout (``run/restart.sh`` is its
    sibling) and ``SERVER_DIR`` points at the data tree beside it, so the env
    file's directory is the authoritative answer whenever one is configured and
    the controller is actually there.  A checkout-in-place deployment, whose data
    tree and checkout are the same directory, resolves through ``SERVER_DIR``.
    """
    env_file = os.environ.get("REVODESIGN_SERVER_ENV")
    if env_file:
        checkout = Path(env_file).expanduser().parent
        if (checkout / "run" / "restart.sh").is_file():
            return checkout
    return Path(host.server_root())


def _resolve_env_file(root: Path) -> Path | None:
    """The deployment env file the controller is started with.

    ``REVODESIGN_SERVER_ENV`` is resolved exactly as the controller's own CLI
    resolves it (absolute, or relative to the working directory), so the Web and
    the CLI agree on which deployment they are operating.  Directory traversal
    and a symlinked file are fine: this is a path operator configuration already
    trusts, not a request field.  A path that is absent, is not a regular file,
    or cannot be read is refused rather than followed.
    """
    named = os.environ.get("REVODESIGN_SERVER_ENV")
    candidate = Path(named).expanduser() if named else root / ".env.production"
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    if not candidate.is_file():
        return None
    if not os.access(candidate, os.R_OK):
        return None
    return candidate


def _executor_problem(host: HostPaths) -> str | None:
    """Why host operations cannot be resolved, or ``None`` when they can.

    The reasons are role-specific and secret-free: they name the missing artifact
    by role and the corrective step, never an absolute host path or an env value,
    so the same text can be shown in the Admin surface and pasted into a report.
    """
    root = _server_root(host)
    entrypoint = root / "run" / "restart.sh"
    if not entrypoint.is_file():
        return (
            "The deployment controller (run/restart.sh) is not reachable from this server "
            "process, so host operations are disabled here. Run the action directly with "
            "run/restart.sh on the deployment host; a server process that runs in a container "
            "cannot reach the controller, and that is expected."
        )
    if not _is_relative_to(entrypoint, root):
        return "The deployment controller resolves outside the server root; refusing to run it."
    named = os.environ.get("REVODESIGN_SERVER_ENV")
    if not named and not (root / ".env.production").is_file():
        return (
            "This server process cannot drive the deployment controller: no deployment env "
            "file is visible to it. Host mutations for a containerized server belong to "
            "run/restart.sh on the deployment host; a server process beside the checkout can "
            "set REVODESIGN_SERVER_ENV to the deployment env file (or place .env.production "
            "in the server root) to enable them."
        )
    if _resolve_env_file(root) is None:
        return (
            "The deployment env file named by REVODESIGN_SERVER_ENV is missing or unreadable "
            "from this server process; correct the path or its permissions."
        )
    return None


def resolve_executor(host: HostPaths) -> ExecutorConfig | None:
    """Resolve the bounded host controller, or ``None`` when it is unreachable.

    The controller must be a real file inside the resolved server root and the
    deployment env file must be a readable regular file; a path that does not
    exist, or that points outside the deployment, is treated as unavailable
    rather than followed.
    """
    if _executor_problem(host) is not None:
        return None
    root = _server_root(host)
    entrypoint = root / "run" / "restart.sh"
    env_file = _resolve_env_file(root)
    assert env_file is not None  # guaranteed by _executor_problem
    interpreter = os.environ.get("REVODESIGN_PYTHON") or "python3"
    return ExecutorConfig(
        command=(interpreter, str(entrypoint)),
        env_file=str(env_file),
        working_directory=str(root),
    )


def availability(host: HostPaths) -> ExecutorAvailability:
    """Whether host operations can be attempted, as a capability separate from readiness."""
    problem = _executor_problem(host)
    if problem is not None:
        return ExecutorAvailability(False, "operator_executor_unavailable", problem)
    return ExecutorAvailability(True, "operator_executor_available", None)


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
        raise ExecutorUnavailable(_executor_problem(host) or "Operator executor unavailable")
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
        raise ExecutorUnavailable(
            "The deployment controller's interpreter could not be started; check REVODESIGN_PYTHON."
        ) from exc
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
