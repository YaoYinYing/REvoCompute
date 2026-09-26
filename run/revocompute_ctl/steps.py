# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Step registry and the restart walk.

Every restart is an ordered sequence of named steps.  The walker times each
step, honors --dry-run, and runs each completed step's cleanup in reverse on
failure.  The stop step is always last — the registry refuses a sequence
that does not end with it.  The deploy stamp is written by the finalizer
after the walk, so it can carry the real step timings.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from revocompute_ctl.compose import compose_args, run_cmd
from revocompute_ctl.readiness import invalidate_deployment_attestations
from revocompute_ctl.registry import (
    RuntimeFamily,
    build_slurm_images,
    deployment_plugin_root,
    migrate_legacy_sif_evidence,
    validate_plugin_policies,
    runner_enabled,
    validate_compose_model,
    validate_prepared_images,
    validate_runtime_files,
    validate_slurm_images,
)
from revocompute_ctl.storage import (
    prepare_auth_storage,
    prepare_result_storage,
    require_production_identity,
    resolve_runner_identity,
    validate_auth_database_storage,
    validate_auth_storage,
    validate_result_storage,
)


def materialize_runner_families(state) -> None:
    """Atomically replace the server instance's enabled Runner snapshot."""
    from revocompute_ctl import SERVER_ROOT
    from revocompute.plugins import PluginManager

    source_root = state.get("RUNNER_SOURCE_ROOT") or os.path.join(str(SERVER_ROOT), "docker", "runners")
    target_root = os.path.join(state.server_dir(), "docker", "runners")
    staging_root = f"{target_root}.next"
    previous_root = f"{target_root}.previous"
    if not os.path.isdir(source_root):
        raise FileNotFoundError(f"Runtime runner directory is missing: {source_root}")
    enabled = {value for value in state.get("ENABLED_TASKRUNNERS").split(",") if value}
    manifests = PluginManager().discover(source_root)
    os.makedirs(os.path.dirname(target_root), exist_ok=True)
    for transient_root in (staging_root, previous_root):
        if os.path.exists(transient_root):
            shutil.rmtree(transient_root)
    os.makedirs(staging_root)
    common_source = os.path.join(source_root, "common")
    common_target = os.path.join(staging_root, "common")
    if not os.path.isdir(common_source):
        raise FileNotFoundError(f"Shared runner build inputs are missing: {common_source}")
    shutil.copytree(common_source, common_target)
    for manifest in manifests:
        if enabled and manifest.id not in enabled:
            continue
        destination = os.path.join(staging_root, manifest.path.name)
        shutil.copytree(manifest.path, destination)
    had_previous = os.path.exists(target_root)
    try:
        if had_previous:
            os.rename(target_root, previous_root)
        os.rename(staging_root, target_root)
    except BaseException:
        if had_previous and os.path.exists(previous_root) and not os.path.exists(target_root):
            os.rename(previous_root, target_root)
        raise
    finally:
        if os.path.exists(staging_root):
            shutil.rmtree(staging_root)
    if os.path.exists(previous_root):
        shutil.rmtree(previous_root)


def enabled_tool_families(state) -> tuple[str, ...]:
    return tuple(sorted({value.strip() for value in state.get("ENABLED_TOOL_FAMILIES").split(",") if value.strip()}))


def materialize_tool_families(state) -> None:
    """Atomically install only explicitly enabled Tool plugin trees."""
    from revocompute_ctl import SERVER_ROOT

    source_root = Path(state.get("TOOL_SOURCE_ROOT") or SERVER_ROOT / "docker" / "tools").resolve()
    target_root = Path(state.server_dir()) / "docker" / "tools"
    staging_root = target_root.with_name(f"{target_root.name}.next")
    previous_root = target_root.with_name(f"{target_root.name}.previous")
    if not source_root.is_dir():
        raise FileNotFoundError(f"Tool source directory is missing: {source_root}")
    for transient in (staging_root, previous_root):
        if transient.exists():
            shutil.rmtree(transient)
    staging_root.mkdir(parents=True)
    for family in enabled_tool_families(state):
        source = source_root / family
        if not (source / "plugin.yaml").is_file():
            raise FileNotFoundError(f"Enabled Tool family is missing: {family}")
        shutil.copytree(source, staging_root / family)
    target_root.parent.mkdir(parents=True, exist_ok=True)
    if target_root.exists():
        os.rename(target_root, previous_root)
    try:
        os.rename(staging_root, target_root)
    except BaseException:
        if previous_root.exists() and not target_root.exists():
            os.rename(previous_root, target_root)
        raise
    finally:
        if staging_root.exists():
            shutil.rmtree(staging_root)
    if previous_root.exists():
        shutil.rmtree(previous_root)


def tool_runtime_specs(state) -> list[tuple[str, Path, Path]]:
    """Return enabled family, definition, and deployed image paths."""
    tools_root = Path(state.server_dir()) / "docker" / "tools"
    image_root = Path(state.get("TOOL_IMAGE_DIR") or Path(state.server_dir()).parent / "images" / "tools")
    specs: list[tuple[str, Path, Path]] = []
    for family in enabled_tool_families(state):
        family_root = (tools_root / family).resolve()
        manifest = yaml.safe_load((family_root / "plugin.yaml").read_text(encoding="utf-8")) or {}
        runtime = manifest.get("runtime") if isinstance(manifest, dict) else None
        if not isinstance(runtime, dict):
            raise ValueError(f"Tool family {family!r} has no runtime contract")
        definition = (family_root / str(runtime.get("definition", ""))).resolve()
        image_name = Path(str(runtime.get("image", "")))
        if (
            not definition.is_file()
            or not definition.is_relative_to(family_root)
            or image_name.is_absolute()
            or len(image_name.parts) != 1
        ):
            raise ValueError(f"Tool family {family!r} has an invalid runtime artifact contract")
        specs.append((family, definition, image_root / image_name))
    return specs


def validate_tool_images(state) -> None:
    missing = [f"{family}: {image}" for family, _definition, image in tool_runtime_specs(state) if not image.is_file()]
    if missing:
        raise FileNotFoundError("Enabled Tool runtime image(s) are missing: " + ", ".join(missing))


def build_tool_images(state) -> None:
    """Build each enabled Tool SIF to a staging path, then atomically promote it."""
    for family, definition, image in tool_runtime_specs(state):
        image.parent.mkdir(parents=True, exist_ok=True)
        staged = image.with_suffix(f"{image.suffix}.next")
        print(f"[TOOLS] Building exact runtime: {family} ({image})...")
        run_cmd(
            ["apptainer", "build", "--force", str(staged), definition.name],
            env=state.exported(),
            cwd=definition.parent,
        )
        os.replace(staged, image)


def active_tool_call_count(state) -> int:
    database = Path(state.get("DB_PATH") or Path(state.server_dir()) / "revocompute.sqlite3")
    if not database.is_file():
        return 0
    try:
        with sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=5) as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM tool_calls WHERE status IN ('queued', 'preparing', 'running')"
            ).fetchone()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            return 0
        raise
    return int(row[0]) if row else 0


def drain_tool_calls(
    state,
    *,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Wait a bounded interval for outstanding Tool calls during maintenance."""
    configured = state.get("TOOL_DRAIN_TIMEOUT_SECONDS")
    timeout = int(configured) if configured else int(state.get("TOOL_CALL_TIMEOUT_SECONDS") or 300) + 10
    deadline = clock() + timeout
    announced = False
    while (active := active_tool_call_count(state)) > 0:
        if not announced:
            print(f"Waiting for {active} outstanding Tool call(s) to drain...")
            announced = True
        remaining = deadline - clock()
        if remaining <= 0:
            raise RuntimeError(f"Timed out with {active} outstanding Tool call(s); deployment was not stopped")
        sleep(min(1.0, remaining))

# The resource-policy audit argv, kept as one literal so the static test
# assertion stays a one-liner.  No --no-build: `docker compose run` rejects
# it (the worker image already exists — the prepared preflight proves that
# first), and the image check precedes this call.
RESOURCE_AUDIT_CMD = "run --rm --no-deps --entrypoint python worker -m revocompute.resource_audit"


@dataclass
class Step:
    name: str
    run: Callable[[], object]
    cleanup: Callable[[], None] | None = None


@dataclass
class RestartPlan:
    """The walk plus the post-walk finalizer (stamp + maintenance cleanup)."""

    steps: list[Step]
    finalize: Callable[[dict[str, float]], None]
    report_lines: list[str] = field(default_factory=list)


@dataclass
class RestartFlags:
    mode: str = "dev"
    build_sif: bool = False
    use_proxy: str = ""
    use_proxy_from_env: bool = False
    dry_run: bool = False
    keep_gateway: bool = False
    server_only: bool = False
    runner: str | None = None
    task: str | None = None
    collection: str = "smoke"
    all_runners: bool = False
    as_json: bool = False


class StepRegistry:
    """Named step sequences; enforces the stop-last invariant."""

    def __init__(self) -> None:
        self._sequences: dict[str, list[Step]] = {}

    def add(self, name: str, steps: list[Step]) -> None:
        if not steps or steps[-1].name != "stop":
            raise ValueError(f"registry sequence {name!r} must end with the stop step")
        self._sequences[name] = steps

    def get(self, name: str) -> list[Step]:
        return list(self._sequences[name])


def run_walk(steps: list[Step], dry_run: bool = False) -> dict[str, float]:
    """Execute the walk; on failure, run completed steps' cleanups in
    reverse.  Returns step timings."""
    timings: dict[str, float] = {}
    completed: list[Step] = []
    for step in steps:
        if dry_run:
            print(f"  [dry-run] {step.name}")
            continue
        start = time.monotonic()
        try:
            step.run()
        except BaseException:
            for done in reversed(completed):
                if done.cleanup is not None:
                    done.cleanup()
            raise
        timings[step.name] = time.monotonic() - start
        completed.append(step)
    return timings


# -- prepared-mode preflight -------------------------------------------------


def validate_resource_policies(state, compose_cmd: tuple[str, ...]) -> None:
    print("Validating resolved task resource policies with the prepared worker image...")
    run_cmd(
        [*compose_cmd, *compose_args(state), "--env-file", state.env_file, *RESOURCE_AUDIT_CMD.split()],
        env=state.exported(),
    )


def _prepared_preflight(
    state, compose_cmd: tuple[str, ...], families: list[RuntimeFamily], dry_run: bool = False
) -> None:
    """Everything a prepared restart validates before stopping the healthy
    stack. --dry-run skips the mkdir-ing storage prep (it must write nothing)."""
    plugin_root = deployment_plugin_root(state)
    validate_plugin_policies(plugin_root, os.path.join(state.config_dir(), "access_policies"))
    validate_prepared_images(state, families)
    validate_auth_storage(state)
    uid, gid = resolve_runner_identity(state)
    if not dry_run:
        prepare_auth_storage(state, uid, gid)
        prepare_result_storage(state, uid, gid)
    validate_compose_model(state, compose_cmd)
    if not dry_run:  # the audit launches a throwaway worker container
        validate_resource_policies(state, compose_cmd)


# -- subcommand sequences ----------------------------------------------------


def require_env_file(state, dry_run: bool = False) -> None:
    if not os.path.isfile(state.env_file):
        print(
            f"Expected {state.env_file} to exist. Run: REVODESIGN_SERVER_ENV={state.env_file} "
            "bash run/restart.sh setup",
            file=sys.stderr,
        )
        raise SystemExit(1)
    state.ensure_redis_password(write=not dry_run)
    state.ensure_auth_secret_key(write=not dry_run)


# Values compose interpolates directly into a command line.  They must be
# positive integers: a free-form string such as "2 --pool=solo" would be
# split into extra argv words by the shell inside the container.
_COMMAND_LINE_COUNTS = ("WORKER_CONCURRENCY", "GUNICORN_WORKERS", "GUNICORN_TIMEOUT")


def validate_required_settings(state) -> None:
    # The shell validated in a subshell with SERVER_DIR/ADMIN_USERS unset —
    # only the env file counts, never the outer process environment.
    missing = [name for name in ("SERVER_DIR", "ADMIN_USERS") if not state.values.get(name, "").strip()]
    if missing:
        print(f"Missing required setting(s) in {state.env_file}: {' '.join(missing)}", file=sys.stderr)
        raise SystemExit(1)
    invalid = [
        f"{name}={state.get(name)}"
        for name in _COMMAND_LINE_COUNTS
        if (raw := state.get(name).strip()) and not (raw.isdecimal() and int(raw) > 0)
    ]
    if invalid:
        print(
            f"Setting(s) in {state.env_file} must be positive integers: {' '.join(invalid)}",
            file=sys.stderr,
        )
        raise SystemExit(1)


def cmd_setup(state) -> None:
    from revocompute_ctl import ENV_EXAMPLE_FILE
    if not os.path.isfile(state.env_file):
        if not ENV_EXAMPLE_FILE.is_file():
            print(f"Missing {ENV_EXAMPLE_FILE}; cannot initialize {state.env_file}.", file=sys.stderr)
            raise SystemExit(1)
        destination = Path(state.env_file)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ENV_EXAMPLE_FILE, destination)
        # The tracked .env.example is 0644 and ensure_redis_password appends the
        # generated REDIS_PASSWORD below, so tighten before writing any secret.
        os.chmod(destination, 0o600)
        print(f"Created {state.env_file} from {ENV_EXAMPLE_FILE} (mode 0600).")
    state.ensure_redis_password()
    state.ensure_auth_secret_key()
    if state.server_dir():
        materialize_runner_families(state)
        materialize_tool_families(state)
    print(f"Setup completed. Using env file: {state.env_file}")
    print(f"Review {state.env_file} before starting services.")


def cmd_down(state, compose_cmd: tuple[str, ...], *, keep_gateway: bool = False) -> None:
    from revocompute_ctl.maintenance import begin_maintenance, end_maintenance, sentinel_path
    from revocompute_ctl.sweep import pre_stop_sweep_slurm

    require_env_file(state)
    resolve_runner_identity(state)
    enabled_maintenance = keep_gateway and not os.path.isfile(sentinel_path(state))
    if enabled_maintenance:
        begin_maintenance(state)
    try:
        if enabled_tool_families(state):
            # A Tool call may legitimately run up to its configured timeout, so
            # drain whenever the Tool worker is about to stop.  `keep_gateway`
            # only controls the maintenance-page behavior.
            drain_tool_calls(state)
        pre_stop_sweep_slurm(state, compose_cmd)
    except BaseException:
        if enabled_maintenance:
            end_maintenance(state)
        raise
    print("Stopping services via docker compose...")
    services = ["redis", "web", "maintenance", "worker", "tool-worker"]
    if keep_gateway:
        print("Refreshing gateway and keeping it running to serve the maintenance page.")
        run_cmd(
            [
                *compose_cmd,
                *compose_args(state),
                "--env-file",
                state.env_file,
                "up",
                "-d",
                "--no-deps",
                "--force-recreate",
                "gateway",
            ],
            env=state.exported(),
        )
        run_cmd(
            [*compose_cmd, *compose_args(state), "--env-file", state.env_file, "stop", *services],
            env=state.exported(),
        )
        return
    run_cmd(
        [*compose_cmd, *compose_args(state), "--env-file", state.env_file, "down"],
        env=state.exported(),
    )


def cmd_reload(state, compose_cmd: tuple[str, ...]) -> None:
    require_env_file(state)
    print("Sending HUP to Gunicorn...")
    run_cmd(
        [
            *compose_cmd,
            *compose_args(state),
            "--env-file",
            state.env_file,
            "exec",
            "web",
            "pkill",
            "-HUP",
            "gunicorn",
        ],
        env=state.exported(),
    )


def cmd_up(
    state, compose_cmd: tuple[str, ...], extra: list[str] | None = None, *, prevalidated: bool = False
) -> None:
    from revocompute_ctl.admin import prepare_admin_bootstrap, print_admin_logins

    require_env_file(state)
    validate_required_settings(state)
    if not prevalidated:
        families = validate_runtime_files(state)
        if state.use_slurm():
            validate_slurm_images(state, families)
        validate_auth_storage(state)
    prepare_admin_bootstrap(state)
    # Print the generated credential before anything that can exit: the web
    # container creates the account with this password as soon as it starts, and
    # this run holds the only copy.  A validator that fails after `up` would
    # otherwise strand an account whose password was never shown, with no second
    # chance (`prepare_admin_bootstrap` no-ops once the database has users).
    print_admin_logins(state)
    uid, gid = resolve_runner_identity(state)
    prepare_auth_storage(state, uid, gid)
    prepare_result_storage(state, uid, gid)
    print("Starting services via docker compose...")
    run_cmd(
        [
            *compose_cmd,
            *compose_args(state),
            "--env-file",
            state.env_file,
            "up",
            *(extra or []),
            "-d",
            "redis",
            "web",
            "gateway",
            "maintenance",
            "worker",
            "tool-worker",
        ],
        env=state.exported(),
    )
    validate_result_storage(state, compose_cmd)
    validate_auth_database_storage(state, compose_cmd)


def wait_for_services(state, compose_cmd: tuple[str, ...]) -> None:
    expected = {"redis", "web", "gateway", "maintenance", "worker", "tool-worker"}
    for _attempt in range(30):
        running = run_cmd(
            [
                *compose_cmd,
                *compose_args(state),
                "--env-file",
                state.env_file,
                "ps",
                "--status",
                "running",
                "--services",
            ],
            env=state.exported(),
            check=False,
            capture=True,
        ).stdout.split()
        if expected <= set(running):
            print("All prepared deployment services are running.")
            return
        time.sleep(2)
    print("Prepared deployment readiness failed; not all required services are running.", file=sys.stderr)
    raise SystemExit(1)


def pull_production_images(state, compose_cmd: tuple[str, ...], families) -> None:
    del families
    print("Pulling configured production images...")
    run_cmd(
        [*compose_cmd, *compose_args(state), "--env-file", state.env_file, "pull", "web", "gateway"],
        env=state.exported(),
    )


def slurm_block(state, families, build_sif: bool) -> None:
    print("[SLURM] SLURM+Apptainer runner enabled.")
    if build_sif:
        build_slurm_images(state, families)
        validate_slurm_images(state, families)


def finish_restart(state) -> None:
    """The completion banner printed after every successful restart."""
    print("Deployment completed.")
    print(f"Nginx gateway is now running at http://0.0.0.0:{state.get('PORT') or '8080'}/compute/dashboard")
    if state.use_slurm():
        print("[SLURM] SLURM runner is enabled. Configure per-task SLURM settings at /compute/configuration")


# -- the restart walk --------------------------------------------------------


def build_restart_plan(state, compose_cmd: tuple[str, ...], flags: RestartFlags) -> RestartPlan:
    """Assemble the restart walk for the selected mode."""
    from revocompute_ctl import promotion
    from revocompute_ctl.admin import prepare_admin_bootstrap
    from revocompute_ctl.build import cmd_build
    from revocompute_ctl.maintenance import begin_maintenance, end_maintenance
    from revocompute_ctl.stamp import backup_config, stamp_payload, write_stamp

    require_env_file(state, dry_run=flags.dry_run)
    validate_required_settings(state)
    if flags.mode == "prod":
        require_production_identity(state)
    else:
        # Service-context filesystem operations need the resolved numeric
        # identity even when the deployment file specifies names only.
        resolve_runner_identity(state)
    if flags.build_sif and (state.use_slurm() or enabled_tool_families(state)) and not shutil.which("apptainer"):
        print("Apptainer not found on PATH; refusing to stop the current deployment.", file=sys.stderr)
        raise SystemExit(1)
    families: list[RuntimeFamily] = []
    selected_families: list[RuntimeFamily] = []
    images: dict[str, str] = {}
    baseline: dict[str, dict[str, str]] = {}
    backup_path_holder: list[str] = [""]
    promoted_sifs: set[str] = set()

    def load_revision(*, materialize: bool, dry_run: bool = False) -> None:
        """Load one candidate revision without ever rewriting a running instance."""
        if materialize:
            materialize_runner_families(state)
            materialize_tool_families(state)
        loaded = validate_runtime_files(state)
        families[:] = loaded
        if state.use_slurm() and not dry_run:
            migrate_legacy_sif_evidence(state, loaded)
        prepare_admin_bootstrap(state)
        if state.use_slurm() and not flags.build_sif:
            validate_slurm_images(state, loaded)
        if not flags.build_sif:
            validate_tool_images(state)
        if flags.mode == "prepared":
            _prepared_preflight(state, compose_cmd, loaded, dry_run=dry_run)
        selected_families[:] = [family for family in loaded if runner_enabled(state, family.name)]
        images.clear()
        images.update(promotion.taggable_images(state, selected_families))
        baseline.clear()
        baseline.update(promotion.capture_baseline_digests(state, images))

    def activate_revision() -> None:
        if state.use_slurm():
            invalidate_deployment_attestations(state)
        load_revision(materialize=True)

    def stop_current_instance() -> None:
        try:
            cmd_down(state, compose_cmd, keep_gateway=flags.keep_gateway)
        except BaseException:
            if flags.keep_gateway:
                end_maintenance(state)
            raise

    if flags.dry_run:
        load_revision(materialize=False, dry_run=True)

    def changed_now() -> set[str]:
        """Per-family change set computed at the moment it is needed: after
        build/pull for the dry-run prediction, after up for the stamp."""
        return promotion.changed_image_names(state, images, baseline)

    def stale_sifs_now() -> set[str]:
        """SIF staging set: missing or image-stale families (computed at
        build time — the image may be promoted in an earlier restart)."""
        from revocompute_ctl.registry import sif_stale

        stale: set[str] = set()
        for family in selected_families:
            print(f"[SLURM] Checking SIF digest: {family.name} ({family.slurm_image})...")
            if sif_stale(state, family):
                stale.add(family.name)
        return stale

    def final_changed() -> set[str]:
        """Post-up truth: baseline digest vs. the digest now under latest."""
        return promoted_sifs | {
            name
            for name, entry in baseline.items()
            if promotion.image_id(state, f"{images[name]}:latest") != entry.get("latest", "")
        }

    steps: list[Step] = []
    if flags.keep_gateway:
        steps.append(Step("maintenance", lambda: begin_maintenance(state)))
    steps.extend(
        [
            Step("stop", stop_current_instance),
            Step(
                "backup-config",
                lambda: backup_path_holder.__setitem__(
                    0, backup_config(state) if flags.mode != "dev" or state.values.get("CONFIG_DIR") else ""
                ),
            ),
            Step("activate-revision", activate_revision),
            Step("capture-baselines", lambda: None),
        ]
    )

    if flags.mode == "dev":
        steps.append(
            Step(
                "build",
                lambda: cmd_build(
                    state, compose_cmd, flags.use_proxy_from_env, flags.use_proxy, materialize=False
                ),
            )
        )
    elif flags.mode == "prod":
        steps.append(Step("pull", lambda: pull_production_images(state, compose_cmd, families)))
    else:
        steps.append(Step("activate", lambda: print("Activating validated prepared images without builds or pulls.")))
    if state.use_slurm():
        steps.append(Step("build-sif", lambda: slurm_block(state, families, flags.build_sif)))
    if enabled_tool_families(state) and flags.build_sif:
        steps.append(Step("build-tool-sif", lambda: build_tool_images(state)))

    def promote_sifs() -> None:
        promoted_sifs.update(
            family.name for family in selected_families if os.path.isfile(f"{family.slurm_image}.next")
        )
        promotion.promote_sifs(state, selected_families)

    if state.use_slurm():
        steps.append(Step("promote-sifs", promote_sifs))
    steps.append(
        Step(
            "up",
            lambda: cmd_up(
                state, compose_cmd, extra=["--no-build"], prevalidated=flags.mode == "prepared"
            ),
        )
    )
    if flags.keep_gateway:
        steps.append(
            Step(
                "refresh-gateway",
                lambda: run_cmd(
                    [
                        *compose_cmd,
                        *compose_args(state),
                        "--env-file",
                        state.env_file,
                        "restart",
                        "gateway",
                    ],
                    env=state.exported(),
                ),
            )
        )
    if flags.mode == "prepared":
        steps.append(Step("readiness", lambda: wait_for_services(state, compose_cmd)))
    steps.append(Step("prune", lambda: promotion.prune_dangling(state)))

    def finalize(timings: dict[str, float]) -> None:
        try:
            if state.use_slurm():
                from revocompute_ctl.readiness import write_submission_attestation

                write_submission_attestation(state, selected_families)
            changed = final_changed()
            # Production-like deployments retain an audit stamp. Local dev
            # with the checkout-config fallback stays stamp-free.
            if flags.mode != "dev" or state.values.get("CONFIG_DIR"):
                write_stamp(
                    state,
                    stamp_payload(
                        state,
                        mode=flags.mode,
                        timings=timings,
                        changed=sorted(changed),
                        unchanged=sorted(set(images) - changed),
                        images=images,
                        baseline=baseline,
                        families=families,
                        backup_path=backup_path_holder[0],
                    ),
                )
        except BaseException:
            if state.use_slurm():
                try:
                    invalidate_deployment_attestations(state)
                except BaseException:
                    pass
            raise
        finally:
            if flags.keep_gateway:
                try:
                    end_maintenance(state)
                except BaseException:
                    if state.use_slurm():
                        try:
                            invalidate_deployment_attestations(state)
                        except BaseException:
                            pass
                    raise
        finish_restart(state)

    report_lines = []
    if flags.dry_run:
        predicted = changed_now()
        sif_predict = stale_sifs_now() if state.use_slurm() else set()
        report_lines = [
            "Planned restart walk:",
            *(f"  {step.name}" for step in steps),
            "  stamp",
            f"Image changes: changed={', '.join(sorted(predicted)) or '-'}, "
            f"unchanged={', '.join(sorted(set(images) - predicted)) or '-'}",
            f"SIF changes: changed={', '.join(sorted(sif_predict)) or '-'}",
        ]
    return RestartPlan(steps, finalize, report_lines)
