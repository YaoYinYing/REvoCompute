# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Tests for the revocompute_ctl deployment control module."""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

SERVER_DIR = Path(__file__).resolve().parents[1]
RUN_DIR = SERVER_DIR / "run"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from conftest import REPO_DIR, _load_pssm_module, _test_client_auth  # noqa: E402
from revocompute_ctl import SERVER_ROOT  # noqa: E402
from revocompute_ctl import __main__ as main_mod  # noqa: E402
from revocompute_ctl import admin as admin_mod  # noqa: E402
from revocompute_ctl import maintenance as maintenance_mod  # noqa: E402
from revocompute_ctl import promotion  # noqa: E402
from revocompute_ctl import registry as registry_mod  # noqa: E402
from revocompute_ctl import stamp as stamp_mod  # noqa: E402
from revocompute_ctl import steps as steps_mod  # noqa: E402
from revocompute_ctl import sweep as sweep_mod  # noqa: E402
from revocompute_ctl.env import EnvState, parse_env_file  # noqa: E402
from revocompute_ctl.registry import (
    RegistryError,
    RuntimeFamily,
    _docker_tag,
    build_slurm_images,
    load_plugin_families,
)  # noqa: E402
from revocompute_ctl.steps import Step, StepRegistry, run_walk  # noqa: E402

RUNNER_IMAGE = "revodesign-revocompute-runner"


def test_controller_root_is_repository_root():
    assert SERVER_ROOT == Path(REPO_DIR)


def test_plugin_runtime_declares_direct_sif_contract():
    families = {family.name: family for family in load_plugin_families(SERVER_ROOT / "docker" / "runners")}
    assert families["alphafold3"].definition == "alphafold3.def"
    assert families["alphafold3"].image_artifact == "alphafold3_v1.sif"
    assert families["alphafold3"].build_inputs

_DOCKER_SHIM = textwrap.dedent(
    """\
    #!/usr/bin/env bash
    printf "%s\\n" "$*" >> "${SHIM_LOG}"
    if [[ "$1" == "compose" && "$*" == *" ps --status running --services"* ]]; then
      printf "redis\\nweb\\ngateway\\nmaintenance\\nworker\\n"
      exit 0
    fi
    if [[ "$1" == "image" && "$2" == "inspect" && "$3" == "--format" ]]; then
      if [[ "$4" == "{{.Created}}" ]]; then
        printf '%s\\n' "${SHIM_CREATED:-2020-01-01T00:00:00Z}"
      else
        img="${@: -1}"
        grep -F "${img}=" "${SHIM_IDS}" 2>/dev/null | head -1 | cut -d= -f2- || true
      fi
      exit 0
    fi
    if [[ "$1" == "run" ]]; then
      declare -a subs=()
      prev=""
      for arg in "$@"; do
        if [[ "$prev" == "-v" ]]; then
          subs+=("-e" "s|${arg#*:}|${arg%%:*}|g")
        fi
        prev="$arg"
      done
      script="${@: -1}"
      transformed="$script"
      for ((i=0; i<${#subs[@]}; i+=2)); do
        transformed="$(printf '%s' "$transformed" | sed "${subs[$i]}" "${subs[$((i+1))]}")"
      done
      sh -c "$transformed"
      exit $?
    fi
    if [[ "$1" == "build" && "${DOCKER_BUILD_FAIL:-0}" == "1" ]]; then exit 1; fi
    exit 0
    """
)

_APPTAINER_SHIM = textwrap.dedent(
    """\
    #!/usr/bin/env bash
    printf "%s\\n" "$*" >> "${SHIM_LOG}"
    if [[ "${APPTAINER_FAIL:-0}" == "1" ]]; then exit 1; fi
    touch "${3}"
    """
)


def _write_shims(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    docker = bin_dir / "docker"
    docker.write_text(_DOCKER_SHIM, encoding="utf-8")
    docker.chmod(0o755)
    apptainer = bin_dir / "apptainer"
    apptainer.write_text(_APPTAINER_SHIM, encoding="utf-8")
    apptainer.chmod(0o755)
    return bin_dir


def _shimmed_state(monkeypatch, tmp_path: Path, bin_dir: Path, ids: dict[str, str], **values) -> tuple[EnvState, Path]:
    ids_file = tmp_path / "ids.txt"
    ids_file.write_text("".join(f"{key}={value}\n" for key, value in ids.items()), encoding="utf-8")
    monkeypatch.setenv("SHIM_IDS", str(ids_file))
    log = tmp_path / "docker.log"
    monkeypatch.setenv("SHIM_LOG", str(log))
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    state = EnvState(str(tmp_path / "fake.env"), values=dict(values))
    return state, log


def _docker_config_dir(tmp_path: Path) -> Path:
    """Return deployment-owned policy configuration for the SLURM controller."""
    source_root = SERVER_DIR / "config"
    config_dir = tmp_path / "docker-config"
    shutil.copytree(source_root / "access_policies", config_dir / "access_policies")
    return config_dir


def _deploy_env(tmp_path: Path, config_dir: Path | None = None) -> tuple[Path, Path, Path]:
    """SERVER_DIR + AUTH_DIR + env file, the harness shape."""
    if config_dir is None:
        config_dir = _docker_config_dir(tmp_path)
    task_dir = tmp_path / "tasks"
    auth_dir = tmp_path / "auth"
    log_dir = tmp_path / "logs"
    for path in (task_dir, auth_dir, log_dir):
        path.mkdir(parents=True, exist_ok=True)
    os.chmod(auth_dir, 0o777)
    results_dir = task_dir / "results"
    results_dir.mkdir(exist_ok=True)
    os.chmod(results_dir, 0o777)
    lines = [
        f"SERVER_DIR={task_dir}",
        f"AUTH_DIR={auth_dir}",
        f"LOG_DIR={log_dir}",
        "ADMIN_USERS=admin",
        "RUNNER_UID=1000",
        "RUNNER_GID=1000",
        "RUNNER_USERNAME=revodesign",
        "RUNNER_GROUP=revodesign",
        "SERVER_IMAGE=example/revodesign-server:latest",
    ]
    lines.append(f"CONFIG_DIR={config_dir}")
    runner_source = tmp_path / "runner-source"
    from test_process_isolation import _make_runner_source
    lines.append(f"RUNNER_SOURCE_ROOT={_make_runner_source(runner_source, executor='slurm')}")
    env_file = tmp_path / "server.env"
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return task_dir, auth_dir, env_file


def _run_cli(
    monkeypatch, tmp_path: Path, env_file: Path, bin_dir: Path, *args: str
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update({"REVODESIGN_SERVER_ENV": str(env_file), "PATH": f"{bin_dir}:{env['PATH']}"})
    return subprocess.run(
        ["bash", str(Path(REPO_DIR) / "run" / "restart.sh"), *args],
        cwd=REPO_DIR,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )


# -- registry invariant -------------------------------------------------------


def _access_policy_config(tmp_path: Path, policy_text: str | None, *, reference: str = "restricted_runner") -> Path:
    config_dir = tmp_path / "policy-config"
    config_dir.mkdir()
    runner = config_dir / "runners" / "restricted"
    runner.mkdir(parents=True)
    (runner / "plugin.yaml").write_text(
        yaml.safe_dump({
            "id": "restricted", "version": "1",
            "runtime": {
                "definition": "restricted.def",
                "image_artifact": "restricted.sif",
                "access_policy": reference,
            },
        }),
        encoding="utf-8",
    )
    (runner / "restricted.def").write_text("Bootstrap: docker\nFrom: alpine:3.20\n", encoding="utf-8")
    (config_dir / "access_policies").mkdir(exist_ok=True)
    if policy_text is not None:
        policy_dir = config_dir / "access_policies"
        (policy_dir / "restricted.yaml").write_text(policy_text, encoding="utf-8")
    return config_dir


def _valid_policy_text(**updates) -> str:
    policy = {
        "id": "restricted_runner",
        "label": "Restricted Runner",
        "description": "Operator approval is required.",
        "requires": ["academic_access"],
        "match": "all",
        "requestable": True,
    }
    policy.update(updates)
    return yaml.safe_dump(policy)


def test_prepared_preflight_accepts_valid_access_policy(monkeypatch, tmp_path):
    config_dir = _access_policy_config(tmp_path, _valid_policy_text())
    state = EnvState(str(tmp_path / "server.env"), values={
        "CONFIG_DIR": str(config_dir), "RUNNER_SOURCE_ROOT": str(config_dir / "runners"),
        "SERVER_DIR": str(tmp_path / "server"), "AUTH_DIR": str(tmp_path / "auth"),
    })
    monkeypatch.setattr(steps_mod, "validate_runtime_files", lambda *_args: [])
    monkeypatch.setattr(steps_mod, "validate_prepared_images", lambda *_args: None)
    monkeypatch.setattr(steps_mod, "validate_auth_storage", lambda *_args: None)
    monkeypatch.setattr(steps_mod, "resolve_runner_identity", lambda *_args: (1000, 1000))
    monkeypatch.setattr(steps_mod, "validate_compose_model", lambda *_args: None)

    steps_mod._prepared_preflight(state, ("docker", "compose"), dry_run=True)


@pytest.mark.parametrize(
    ("policy_text", "reference", "message"),
    [
        (None, "missing_policy", "Unknown access policy"),
        ("id: [unterminated\n", "restricted_runner", "Invalid Runner access policy configuration"),
        (_valid_policy_text(unexpected=True), "restricted_runner", "unknown keys"),
        (_valid_policy_text(requires=["Invalid entitlement"]), "restricted_runner", "entitlement identifiers"),
    ],
)
def test_prepared_preflight_rejects_invalid_access_contract_before_artifact_checks(
    monkeypatch, tmp_path, policy_text, reference, message
):
    config_dir = _access_policy_config(tmp_path, policy_text, reference=reference)
    state = EnvState(str(tmp_path / "server.env"), values={
        "CONFIG_DIR": str(config_dir), "RUNNER_SOURCE_ROOT": str(config_dir / "runners"),
        "SERVER_DIR": str(tmp_path / "server"), "AUTH_DIR": str(tmp_path / "auth"),
    })
    checked_artifacts = False

    def artifact_check(*_args):
        nonlocal checked_artifacts
        checked_artifacts = True

    monkeypatch.setattr(steps_mod, "validate_prepared_images", artifact_check)
    monkeypatch.setattr(steps_mod, "validate_auth_storage", lambda *_args: None)
    monkeypatch.setattr(steps_mod, "resolve_runner_identity", lambda *_args: (1000, 1000))
    monkeypatch.setattr(steps_mod, "validate_compose_model", lambda *_args: None)
    with pytest.raises(RegistryError):
        steps_mod._prepared_preflight(state, ("docker", "compose"), dry_run=True)
    assert not checked_artifacts


def test_config_contract_digest_changes_when_only_access_policy_changes(tmp_path):
    config_dir = _access_policy_config(tmp_path, _valid_policy_text())
    registry_digest = stamp_mod.registry_sha256(str(config_dir))
    initial = stamp_mod.config_contract_sha256(str(config_dir))
    policy_file = config_dir / "access_policies" / "restricted.yaml"
    policy_file.write_text(_valid_policy_text(requires=["institutional_access"]), encoding="utf-8")

    assert stamp_mod.registry_sha256(str(config_dir)) == registry_digest
    assert stamp_mod.config_contract_sha256(str(config_dir)) != initial


def test_step_registry_requires_stop_last():
    registry = StepRegistry()
    with pytest.raises(ValueError, match="stop"):
        registry.add("x", [Step("a", lambda: None)])
    registry.add("x", [Step("a", lambda: None), Step("stop", lambda: None)])
    assert [step.name for step in registry.get("x")] == ["a", "stop"]


def test_slurm_sweep_only_cancels_persisted_deployment_job_ids(monkeypatch, tmp_path):
    state = EnvState(str(tmp_path / "server.env"), values={"USE_SLURM": "1"})
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout="101\n202\n")

    monkeypatch.setattr(sweep_mod, "run_cmd", fake_run)
    sweep_mod.pre_stop_sweep_slurm(state, ("docker", "compose"))

    first_argv, first_kwargs = calls[0]
    assert "squeue" not in first_argv
    assert first_argv[-2:] == ["python3", "-"]
    assert "slurm_job_id" in first_kwargs["stdin"]
    assert "pending" not in sweep_mod.SWEEP_SOURCE
    assert "_record_failure" in sweep_mod.SWEEP_SOURCE
    assert calls[1][0][-3:] == ["scancel", "101", "202"]


def test_walk_runs_completed_cleanups_in_reverse_on_failure():
    events: list[str] = []

    def fail() -> None:
        events.append("run:b")
        raise RuntimeError("boom")

    walk = [
        Step("a", lambda: events.append("run:a"), cleanup=lambda: events.append("cleanup:a")),
        Step("b", fail, cleanup=lambda: events.append("cleanup:b")),
    ]
    with pytest.raises(RuntimeError):
        run_walk(walk)
    assert events == ["run:a", "run:b", "cleanup:a"]  # b's own cleanup is caller's job


# -- env parsing --------------------------------------------------------------


def test_env_file_parsing_and_redis_password_round_trip(tmp_path):
    env_file = tmp_path / "server.env"
    env_file.write_text("# comment\nexport A=1\nB=\"two\"\nC='three'\n", encoding="utf-8")
    assert parse_env_file(env_file) == {"A": "1", "B": "two", "C": "three"}

    env_file.write_text("REDIS_URL=redis://redis:6379/0\nBROKER_URL=redis://127.0.0.1:6380/0\n", encoding="utf-8")
    password = EnvState(str(env_file)).ensure_redis_password()
    assert len(password) == 48
    text = env_file.read_text(encoding="utf-8")
    assert f"REDIS_URL=redis://:{password}@redis:6379/0" in text
    assert f"BROKER_URL=redis://:{password}@127.0.0.1:6380/0" in text
    # A second process reuses the persisted secret instead of regenerating.
    assert EnvState(str(env_file)).ensure_redis_password() == password


def test_explicit_missing_env_file_fails_before_registry_fallback(monkeypatch, tmp_path):
    missing = tmp_path / "missing.env"
    result = _run_cli(monkeypatch, tmp_path, missing, _write_shims(tmp_path), "restart", "--build-sif")

    assert result.returncode == 1
    assert result.stderr.splitlines()[-1] == f"Explicit env file does not exist: {missing}"


def test_prepare_builds_only_selected_runner(monkeypatch, tmp_path):
    _task_dir, _auth_dir, env_file = _deploy_env(tmp_path)
    bin_dir = _write_shims(tmp_path)
    monkeypatch.setenv("SHIM_LOG", str(tmp_path / "docker.log"))
    result = _run_cli(
        monkeypatch, tmp_path, env_file, bin_dir, "prepare", "--build-sif", "--enabled-runners=freebindcraft"
    )

    assert result.returncode == 0, result.stderr
    commands = (tmp_path / "docker.log").read_text(encoding="utf-8")
    assert "freebindcraft.sif.next.build" in commands
    assert "freebindcraft/freebindcraft.def" in commands
    assert "build web worker" not in commands


def test_prepare_fails_when_selected_runner_build_fails(monkeypatch, tmp_path):
    _task_dir, _auth_dir, env_file = _deploy_env(tmp_path)
    bin_dir = _write_shims(tmp_path)
    monkeypatch.setenv("APPTAINER_FAIL", "1")
    result = _run_cli(
        monkeypatch, tmp_path, env_file, bin_dir, "prepare", "--build-sif", "--enabled-runners=freebindcraft"
    )

    assert result.returncode == 1
    assert "Direct SIF build failed for freebindcraft" in result.stderr


def test_prepare_rejects_unknown_runner(monkeypatch, tmp_path):
    _task_dir, _auth_dir, env_file = _deploy_env(tmp_path)
    result = _run_cli(monkeypatch, tmp_path, env_file, _write_shims(tmp_path), "prepare", "--enabled-runners=typo")

    assert result.returncode == 1
    assert "Unknown runner selection: typo" in result.stderr


def test_build_server_only_skips_runner_images(monkeypatch, tmp_path):
    _task_dir, _auth_dir, env_file = _deploy_env(tmp_path)
    bin_dir = _write_shims(tmp_path)
    monkeypatch.setenv("SHIM_IDS", str(tmp_path / "ids.txt"))
    monkeypatch.setenv("SHIM_LOG", str(tmp_path / "docker.log"))
    result = _run_cli(monkeypatch, tmp_path, env_file, bin_dir, "build", "--server-only")

    assert result.returncode == 0, result.stderr
    commands = (tmp_path / "docker.log").read_text(encoding="utf-8").splitlines()
    assert any(command.endswith("build web worker") for command in commands)
    assert not any(command.startswith("build ") for command in commands)


def test_restart_rejects_unknown_runner(monkeypatch, tmp_path):
    _task_dir, _auth_dir, env_file = _deploy_env(tmp_path)
    result = _run_cli(monkeypatch, tmp_path, env_file, _write_shims(tmp_path), "restart", "--enabled-runners=typo")

    assert result.returncode == 1
    assert "Unknown runner selection: typo" in result.stderr


def test_env_state_precedence_runtime_over_file_over_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNNER_UID", "999")
    state = EnvState(str(tmp_path / "fake.env"), values={"RUNNER_UID": "888", "APPTAINER_CACHEDIR": "/custom/cache"})
    assert state.get("RUNNER_UID") == "888"  # file beats environment
    assert state.exported()["APPTAINER_CACHEDIR"] == "/custom/cache"
    state.runtime["RUNNER_UID"] = "777"  # the shell's later export wins
    assert state.get("RUNNER_UID") == "777"


@pytest.mark.parametrize("subcommand", ["down", "restart"])
def test_keep_gateway_flag(subcommand):
    parsed, _reset_username, flags = main_mod.parse_args([subcommand, "--keep-gateway"])
    assert parsed == subcommand
    assert flags.keep_gateway


def test_live_test_scope_arguments_are_command_specific():
    parsed, _username, flags = main_mod.parse_args(["live-test", "--runner", "gremlin", "--collection", "smoke"])
    assert parsed == "live-test"
    assert flags.runner == "gremlin"
    assert flags.collection == "smoke"
    with pytest.raises(SystemExit):
        main_mod.parse_args(["build", "--runner", "gremlin"])


def test_runner_status_scope_and_json_arguments_are_command_specific():
    parsed, _username, flags = main_mod.parse_args(["runner-status", "--runner", "gremlin", "--json"])
    assert parsed == "runner-status"
    assert flags.runner == "gremlin"
    assert flags.as_json
    with pytest.raises(SystemExit):
        main_mod.parse_args(["runner-status", "--task", "pssm_gremlin"])


def test_down_keep_gateway_leaves_gateway_serving_maintenance(monkeypatch, tmp_path):
    bin_dir = _write_shims(tmp_path)
    task_dir, _auth_dir, env_file = _deploy_env(tmp_path)
    monkeypatch.setenv("SHIM_IDS", str(tmp_path / "ids.txt"))
    monkeypatch.setenv("SHIM_LOG", str(tmp_path / "docker.log"))

    result = _run_cli(monkeypatch, tmp_path, env_file, bin_dir, "down", "--keep-gateway")

    assert result.returncode == 0, result.stderr
    assert (task_dir / ".maintenance").is_file()
    commands = (tmp_path / "docker.log").read_text(encoding="utf-8").splitlines()
    assert any("up -d --no-deps --force-recreate gateway" in command for command in commands)
    assert any(command.endswith("stop redis web maintenance worker") for command in commands)
    compose_commands = [command.split() for command in commands if "--env-file" in command.split()]
    assert all(tokens[tokens.index("--env-file") + 2] != "down" for tokens in compose_commands)


def test_deployment_lock_rejects_concurrent_control(tmp_path):
    first = main_mod.acquire_deployment_lock(str(tmp_path / "server.env"))
    try:
        with pytest.raises(SystemExit):
            main_mod.acquire_deployment_lock(str(tmp_path / "server.env"))
    finally:
        first.close()


def test_keep_gateway_restarts_it_after_web_recreation(monkeypatch, tmp_path):
    bin_dir = _write_shims(tmp_path)
    _task_dir, _auth_dir, env_file = _deploy_env(tmp_path)
    monkeypatch.setenv("SHIM_IDS", str(tmp_path / "ids.txt"))
    monkeypatch.setenv("SHIM_LOG", str(tmp_path / "docker.log"))

    result = _run_cli(monkeypatch, tmp_path, env_file, bin_dir, "restart", "--keep-gateway")

    assert result.returncode == 0, result.stderr
    commands = (tmp_path / "docker.log").read_text(encoding="utf-8").splitlines()
    up = next(i for i, command in enumerate(commands) if "up --no-build -d redis web gateway" in command)
    refresh = next(i for i, command in enumerate(commands) if command.endswith("restart gateway"))
    assert up < refresh


# -- direct SIF images --------------------------------------------------------


def _direct_family(tmp_path: Path) -> RuntimeFamily:
    root = tmp_path / "runners" / "demo"
    root.mkdir(parents=True)
    (root / "demo.def").write_text("Bootstrap: docker\nFrom: python:3.12-slim\n", encoding="utf-8")
    (root / "run.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    return RuntimeFamily(
        name="demo",
        version="1",
        definition="demo.def",
        image_artifact="demo.sif",
        slurm_image=str(tmp_path / "sifs" / "demo.sif"),
        build_inputs=("demo/run.sh",),
        root=root,
    )


def test_sif_staging_builds_directly_and_skips_matching_provenance(tmp_path, monkeypatch):
    family = _direct_family(tmp_path)
    Path(family.slurm_image).parent.mkdir()
    state, log = _shimmed_state(monkeypatch, tmp_path, _write_shims(tmp_path), {})

    assert build_slurm_images(state, [family]) == 1
    staged = Path(f"{family.slurm_image}.next")
    assert staged.is_file()
    manifest = yaml.safe_load((staged.parent / "digest/image-sif.json").read_text(encoding="utf-8"))["demo"]
    assert manifest["definition_sha256"].startswith("sha256:")
    assert manifest["build_inputs"][0]["path"] == "demo/run.sh"
    assert "docker_image_id" not in manifest
    assert build_slurm_images(state, [family]) == 0
    assert len([line for line in log.read_text().splitlines() if line.startswith("build ")]) == 1

    (family.root / "run.sh").write_text("#!/bin/sh\necho changed\n", encoding="utf-8")
    assert build_slurm_images(state, [family]) == 1


def test_failed_direct_build_leaves_no_candidate(tmp_path, monkeypatch):
    family = _direct_family(tmp_path)
    Path(family.slurm_image).parent.mkdir()
    bin_dir = _write_shims(tmp_path)
    monkeypatch.setenv("APPTAINER_FAIL", "1")
    state, _log = _shimmed_state(monkeypatch, tmp_path, bin_dir, {})

    with pytest.raises(RegistryError):
        build_slurm_images(state, [family], fail_on_error=True)
    assert not Path(f"{family.slurm_image}.next").exists()
    assert not Path(f"{family.slurm_image}.next.build").exists()


def test_prepared_candidate_requires_exact_live_receipt(tmp_path, monkeypatch):
    family = _direct_family(tmp_path)
    Path(family.slurm_image).parent.mkdir()
    state, _log = _shimmed_state(monkeypatch, tmp_path, _write_shims(tmp_path), {}, USE_SLURM="1")
    build_slurm_images(state, [family])
    monkeypatch.setattr("revocompute_ctl.live_test.candidate_receipt_valid", lambda *_args: False)

    with pytest.raises(RegistryError, match="receipt"):
        registry_mod.validate_prepared_images(state, [family])


def test_prepared_active_sif_requires_exact_live_receipt(tmp_path, monkeypatch):
    family = _direct_family(tmp_path)
    Path(family.slurm_image).parent.mkdir()
    state, _log = _shimmed_state(monkeypatch, tmp_path, _write_shims(tmp_path), {}, USE_SLURM="1")
    build_slurm_images(state, [family])
    os.replace(f"{family.slurm_image}.next", family.slurm_image)
    monkeypatch.setattr("revocompute_ctl.live_test.active_receipt_valid", lambda *_args: False)

    with pytest.raises(RegistryError, match="receipt"):
        registry_mod.validate_prepared_images(state, [family])


def test_sif_promotion_is_receipt_gated_and_preserves_active(tmp_path, monkeypatch):
    family = _direct_family(tmp_path)
    active = Path(family.slurm_image)
    active.parent.mkdir()
    active.write_bytes(b"active")
    candidate = Path(f"{family.slurm_image}.next")
    candidate.write_bytes(b"candidate")
    state = EnvState(str(tmp_path / "server.env"), values={"ENABLED_TASKRUNNERS": "demo"})
    monkeypatch.setattr("revocompute_ctl.live_test.candidate_receipt_valid", lambda *_args: False)

    with pytest.raises(RegistryError, match="receipt"):
        promotion.promote_sifs(state, [family])
    assert active.read_bytes() == b"active"
    assert candidate.read_bytes() == b"candidate"

    monkeypatch.setattr("revocompute_ctl.live_test.candidate_receipt_valid", lambda *_args: True)
    promotion.promote_sifs(state, [family])
    assert active.read_bytes() == b"candidate"
    assert not candidate.exists()


def test_sif_promotion_validates_all_candidates_before_activation(tmp_path, monkeypatch):
    first = _direct_family(tmp_path / "first")
    second = _direct_family(tmp_path / "second")
    for family, active_data, candidate_data in ((first, b"active-1", b"candidate-1"), (second, b"active-2", b"candidate-2")):
        active = Path(family.slurm_image)
        active.parent.mkdir(parents=True)
        active.write_bytes(active_data)
        Path(f"{family.slurm_image}.next").write_bytes(candidate_data)
    state = EnvState(str(tmp_path / "server.env"), values={"ENABLED_TASKRUNNERS": "demo"})
    valid_results = iter((True, False))
    monkeypatch.setattr("revocompute_ctl.live_test.candidate_receipt_valid", lambda *_args: next(valid_results))

    with pytest.raises(RegistryError, match="demo"):
        promotion.promote_sifs(state, [first, second])
    assert Path(first.slurm_image).read_bytes() == b"active-1"
    assert Path(f"{first.slurm_image}.next").read_bytes() == b"candidate-1"
    assert Path(second.slurm_image).read_bytes() == b"active-2"
    assert Path(f"{second.slurm_image}.next").read_bytes() == b"candidate-2"


def test_taggable_images_contains_only_server_image(tmp_path):
    family = _direct_family(tmp_path)
    state = EnvState(str(tmp_path / "server.env"), values={"SERVER_IMAGE": "registry.example/team/server"})
    assert promotion.taggable_images(state, [family]) == {"server": "registry.example/team/server"}


def test_docker_tag_distinguishes_registry_port_from_image_tag():
    assert _docker_tag("registry.example:5000/team/runner") == "registry.example:5000/team/runner:latest"
    assert _docker_tag("registry.example:5000/team/runner:v2") == "registry.example:5000/team/runner:v2"
    assert _docker_tag("registry.example:5000/team/runner@sha256:abc") == "registry.example:5000/team/runner@sha256:abc"


# -- stamp / backup / maintenance round-trips through the container transport


def test_stamp_round_trip_and_config_backup(tmp_path, monkeypatch):
    bin_dir = _write_shims(tmp_path)
    task_dir, _auth_dir, _env = _deploy_env(tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "operator.yaml").write_text("site: test\n", encoding="utf-8")
    state, _log = _shimmed_state(
        monkeypatch, tmp_path, bin_dir, {}, SERVER_DIR=str(task_dir), CONFIG_DIR=str(config_dir)
    )

    backup = stamp_mod.backup_config(state)
    assert (Path(backup) / "operator.yaml").is_file()

    stamp_mod.write_stamp(state, {"commit": "abc", "mode": "prepared"})
    stamp_path = config_dir / ".deploy-stamp"
    assert stamp_path.is_file()
    assert yaml.safe_load(stamp_path.read_text(encoding="utf-8")) == {"commit": "abc", "mode": "prepared"}

    # The payload's git reads must find the checkout (glued `-C/path` broke
    # this on the live drill) and record a real commit.
    payload = stamp_mod.stamp_payload(
        state,
        mode="prepared",
        timings={},
        changed=[],
        unchanged=[],
        images={},
        baseline={},
        families=[],
        backup_path="",
    )
    assert payload["commit"]
    assert isinstance(payload["dirty"], bool)
    assert payload["config_contract_sha256"] == stamp_mod.config_contract_sha256(str(config_dir))


def test_maintenance_sentinel_lifecycle(tmp_path, monkeypatch):
    bin_dir = _write_shims(tmp_path)
    task_dir, _auth_dir, _env = _deploy_env(tmp_path)
    state, _log = _shimmed_state(monkeypatch, tmp_path, bin_dir, {}, SERVER_DIR=str(task_dir))
    maintenance_mod.begin_maintenance(state)
    assert (task_dir / ".maintenance").is_file()
    maintenance_mod.end_maintenance(state)
    assert not (task_dir / ".maintenance").exists()


def test_admin_bootstrap_checks_container_when_host_cannot_read_database(tmp_path, monkeypatch):
    state = EnvState(
        str(tmp_path / "server.env"),
        values={"AUTH_DIR": str(tmp_path), "ADMIN_USERS": "admin"},
    )
    monkeypatch.setattr(admin_mod, "_needs_admin_bootstrap", lambda *_args: None)
    calls = []
    monkeypatch.setattr(
        admin_mod,
        "container_fs",
        lambda state, script, mounts, **kwargs: calls.append((script, mounts, kwargs))
        or subprocess.CompletedProcess(script, 0, "1\n"),
    )

    admin_mod.prepare_admin_bootstrap(state)

    assert state.get("ADMIN_BOOTSTRAP_CREDENTIALS").startswith("admin\t")
    assert calls[0][0] == "python -"
    assert calls[0][1] == [(str(tmp_path), "/auth")]


@pytest.mark.parametrize("failure_step", ["up", "readiness"])
def test_failed_activation_keeps_maintenance(monkeypatch, tmp_path, failure_step):
    events = []
    state = EnvState(str(tmp_path / "server.env"), values={"SERVER_DIR": str(tmp_path), "ADMIN_USERS": "admin"})

    def fail_at(phase):
        if failure_step == phase:
            raise RuntimeError(f"{phase} failed")

    monkeypatch.setattr(steps_mod, "require_env_file", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(steps_mod, "validate_required_settings", lambda *_args: None)
    monkeypatch.setattr(steps_mod, "validate_runtime_files", lambda *_args: [])
    monkeypatch.setattr(steps_mod, "resolve_runner_identity", lambda *_args: (1000, 1000))
    monkeypatch.setattr(steps_mod, "_prepared_preflight", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(steps_mod, "cmd_down", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(steps_mod, "cmd_up", lambda *_args, **_kwargs: fail_at("up"))
    monkeypatch.setattr(steps_mod, "wait_for_services", lambda *_args: fail_at("readiness"))
    monkeypatch.setattr(steps_mod, "run_cmd", lambda *args, **kwargs: subprocess.CompletedProcess(args, 0))
    monkeypatch.setattr(admin_mod, "prepare_admin_bootstrap", lambda *_args: None)
    monkeypatch.setattr(maintenance_mod, "begin_maintenance", lambda *_args: events.append("begin"))
    monkeypatch.setattr(maintenance_mod, "end_maintenance", lambda *_args: events.append("end"))
    monkeypatch.setattr(promotion, "taggable_images", lambda *_args: {})
    monkeypatch.setattr(promotion, "capture_baseline_digests", lambda *_args: {})
    monkeypatch.setattr(promotion, "prune_dangling", lambda *_args: None)
    monkeypatch.setattr(stamp_mod, "backup_config", lambda *_args: "")

    plan = steps_mod.build_restart_plan(
        state,
        ("docker", "compose"),
        steps_mod.RestartFlags(mode="prepared", keep_gateway=True),
    )
    with pytest.raises(RuntimeError, match=failure_step):
        run_walk(plan.steps)

    assert events == ["begin"]


# -- proxy broadcasting -------------------------------------------------------


def test_proxy_broadcasts_to_subprocess_env_without_leaking_output(tmp_path, monkeypatch):
    """--use-proxy must reach every subprocess environment (the shell's
    global export) while the URL never appears in the ctl's own output."""
    proxy_url = "http://test-user:test-password@proxy.invalid:8080"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    env_dumper = bin_dir / "docker"
    env_dumper.write_text(
        '#!/usr/bin/env bash\nprintf "%s\\n" "HTTP_PROXY=${HTTP_PROXY}" "HTTPS_PROXY=${HTTPS_PROXY}" '
        '"NO_PROXY=${NO_PROXY}" >> "${SHIM_LOG}"\nif [[ "$*" == *" ps --status running --services"* ]]; then '
        'printf "redis\\nweb\\ngateway\\nmaintenance\\nworker\\n"; fi\n',
        encoding="utf-8",
    )
    env_dumper.chmod(0o755)
    task_dir, _auth_dir, env_file = _deploy_env(tmp_path)
    monkeypatch.setenv("SHIM_LOG", str(tmp_path / "docker.log"))
    monkeypatch.delenv("NO_PROXY", raising=False)  # the shell default must apply
    result = _run_cli(monkeypatch, tmp_path, env_file, bin_dir, "build", f"--use-proxy={proxy_url}")

    assert result.returncode == 0, result.stderr
    assert proxy_url not in result.stdout
    assert proxy_url not in result.stderr
    broadcast = (tmp_path / "docker.log").read_text(encoding="utf-8")
    assert f"HTTP_PROXY={proxy_url}" in broadcast
    assert f"HTTPS_PROXY={proxy_url}" in broadcast
    assert "NO_PROXY=localhost,127.0.0.1,.local" in broadcast


# -- dry-run ------------------------------------------------------------------


def test_dry_run_predicts_and_writes_nothing(tmp_path, monkeypatch):
    bin_dir = _write_shims(tmp_path)
    task_dir, _auth_dir, env_file = _deploy_env(tmp_path)
    monkeypatch.setenv("SHIM_IDS", str(tmp_path / "ids.txt"))
    monkeypatch.setenv("SHIM_LOG", str(tmp_path / "docker.log"))
    result = _run_cli(monkeypatch, tmp_path, env_file, bin_dir, "restart", "--dry-run")

    assert result.returncode == 0, result.stderr
    assert "Planned restart walk:" in result.stdout
    assert "Image changes:" in result.stdout
    commands = (tmp_path / "docker.log").read_text(encoding="utf-8").splitlines()
    assert all("version" in command or "image inspect" in command for command in commands)
    assert not (task_dir / "backups").exists()
    assert not (task_dir / ".maintenance").exists()
    assert not (SERVER_DIR / "config" / ".deploy-stamp").exists()


# -- route gate ---------------------------------------------------------------


def test_upload_gate_returns_503_under_maintenance_sentinel(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    client = module.app.test_client()
    auth_header = _test_client_auth(module)

    def payload():
        # werkzeug closes the file object while building the body — one per request.
        return {"file": (io.BytesIO(b">seq\nACDEFGHIK"), "t.fasta"), "task_type": "gremlin"}

    sentinel = Path(module.CONFIG.server_dir) / ".maintenance"
    sentinel.write_text("deployment maintenance\n", encoding="utf-8")
    blocked = client.post("/compute/api/post", headers=auth_header, data=payload())
    assert blocked.status_code == 503
    assert b"submissions are paused" in blocked.data

    sentinel.unlink()
    allowed = client.post("/compute/api/post", headers=auth_header, data=payload())
    # Without the sentinel the request proceeds past the gate (the downstream
    # failure mode in a unit-test env is irrelevant here).
    assert b"submissions are paused" not in allowed.data
