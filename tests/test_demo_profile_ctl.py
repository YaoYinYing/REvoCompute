# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The demo deployment profile installs curated replay content and no executor."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import revocompute_ctl
import revocompute_ctl.steps as steps_module
from demo_replay_fixtures import CAPTURED_ARTIFACT, SYNTHETIC_TASK_TYPE, write_synthetic_replay_bundle
from revocompute_ctl.__main__ import detect_executor
from revocompute_ctl.env import EnvState
from revocompute_ctl.steps import materialize_demo_replays, validate_deployment_files

REPO_ROOT = Path(__file__).resolve().parents[1]


def _state(tmp_path: Path, **overrides: str) -> EnvState:
    values = {
        "SERVER_DIR": str(tmp_path / "server"),
        "REVOCOMPUTE_DEMO_MODE": "true",
        "REVOCOMPUTE_JOB_EXECUTOR": "demo",
        "ENABLED_TASKRUNNERS": "",
        **overrides,
    }
    return EnvState(str(tmp_path / "demo.env"), values=values)


@pytest.fixture(autouse=True)
def _clear_profile_env(monkeypatch):
    for name in ("REVOCOMPUTE_DEMO_MODE", "REVOCOMPUTE_JOB_EXECUTOR", "ENABLED_TASKRUNNERS", "USE_SLURM"):
        monkeypatch.delenv(name, raising=False)


def test_demo_profile_never_selects_the_slurm_model(tmp_path):
    state = _state(tmp_path)
    assert state.demo_mode() is True
    assert state.use_slurm() is False


def test_demo_profile_does_not_layer_the_slurm_compose_overlay(tmp_path):
    """The executor refusal must reach the rendered Compose model, not just a flag.

    ``docker-compose.slurm.yml`` overrides ``worker`` and ``tool-worker``; a demo
    stack that layered it would still start executor-shaped services. The Slurm
    profile is asserted beside it so the demo assertion cannot pass vacuously.
    """
    slurm_overlay = str(revocompute_ctl.COMPOSE_SLURM_FILE)
    assert slurm_overlay not in _state(tmp_path).compose_args()
    slurm_state = _state(
        tmp_path,
        REVOCOMPUTE_DEMO_MODE="false",
        REVOCOMPUTE_JOB_EXECUTOR="slurm",
        USE_SLURM="1",
    )
    assert slurm_overlay in slurm_state.compose_args()


def test_demo_setup_never_materializes_runtime_bundles(tmp_path, monkeypatch):
    """A demo deployment pins no Runner code, so it must not snapshot bundles.

    The Runtime Bundle store exists to pin the code an executing Task will run;
    running the materializer in demo mode would silently create that executor
    state. The non-demo control proves the spy observes a real call.
    """
    calls: list[object] = []
    # An empty materialized runner tree is a valid zero-family snapshot, so
    # validation never falls back to the production checkout.
    (tmp_path / "server" / "docker" / "runners").mkdir(parents=True)
    for name in ("materialize_runner_families", "materialize_tool_families", "materialize_demo_replays"):
        monkeypatch.setattr(steps_module, name, lambda _state: None)
    monkeypatch.setattr(steps_module, "load_plugin_families", lambda _root: [])
    monkeypatch.setattr(
        steps_module,
        "materialize_runner_bundles",
        lambda _state, families: calls.append(families) or {},
    )
    demo = _state(tmp_path, REDIS_PASSWORD="x", AUTH_SECRET_KEY="y")
    steps_module.cmd_setup(demo)
    assert calls == []
    slurm = _state(
        tmp_path,
        REVOCOMPUTE_DEMO_MODE="false",
        REVOCOMPUTE_JOB_EXECUTOR="slurm",
        USE_SLURM="1",
        RUNTIME_BUNDLE_DIR=str(tmp_path / "runtime-bundles"),
        REDIS_PASSWORD="x",
        AUTH_SECRET_KEY="y",
    )
    steps_module.cmd_setup(slurm)
    assert calls == [[]]


def test_demo_requires_the_demo_executor(tmp_path):
    assert detect_executor(_state(tmp_path)) == (False, "demo profile")
    with pytest.raises(SystemExit):
        detect_executor(_state(tmp_path, REVOCOMPUTE_JOB_EXECUTOR="slurm"))
    with pytest.raises(SystemExit):
        detect_executor(EnvState(str(tmp_path / "x.env"), values={"REVOCOMPUTE_JOB_EXECUTOR": "demo"}))


def test_materialize_demo_replays_installs_the_curated_corpus(tmp_path):
    from revocompute.demo import load_demo_replays

    state = _state(tmp_path)
    materialize_demo_replays(state)
    root = tmp_path / "server" / "demo" / "replays"
    tracked = json.loads((REPO_ROOT / "demo" / "replays" / "index.json").read_text(encoding="utf-8"))
    index = json.loads((root / "index.json").read_text(encoding="utf-8"))
    # The tracked index is authoritative: materialization resolves each source
    # into a deployment-local bundle without changing the corpus it declares.
    assert index["version"] == tracked["version"]
    assert [entry["id"] for entry in index["scenarios"]] == [entry["id"] for entry in tracked["scenarios"]]
    assert all("source" not in entry and entry["bundle"] for entry in index["scenarios"])
    loaded = load_demo_replays(root)
    assert set(loaded) == {entry["id"] for entry in index["scenarios"]}
    # Each scenario's provenance is classified from its own captured mode, and
    # the curated corpus exercises both recorded and labeled-synthetic results.
    expected_kind = {"reproduced_real_result": "recorded_verified", "synthetic": "synthetic"}
    for scenario_id, scenario in loaded.items():
        document = json.loads((root / f"{scenario_id}.json").read_text(encoding="utf-8"))
        capture = (document.get("provenance") or {}).get("capture") or {}
        assert scenario.provenance == expected_kind.get(capture.get("mode"), "recorded_legacy")
    assert {"recorded_verified", "synthetic"} <= {scenario.provenance for scenario in loaded.values()}


def test_demo_validation_does_not_require_a_runner_runtime(tmp_path):
    state = _state(tmp_path)
    materialize_demo_replays(state)
    target = tmp_path / "server" / "docker" / "runners"
    shutil.copytree(REPO_ROOT / "tests" / "fixtures" / "runners", target)
    families = validate_deployment_files(state)
    assert families, "the canonical manifests still validate without a SIF or Apptainer contract"


def _crafted_corpus(tmp_path: Path, *, relative_source: str, scenario_id: str = "crafted") -> Path:
    root = tmp_path / "crafted"
    (root / "tests" / "data").mkdir(parents=True)
    write_synthetic_replay_bundle(root / "tests" / "data" / "bundle.json")
    replay_root = root / "demo" / "replays"
    replay_root.mkdir(parents=True)
    (replay_root / "index.json").write_text(
        json.dumps(
            {
                "version": 1,
                "scenarios": [
                    {
                        "id": scenario_id, "title": "crafted", "summary": "",
                        "task_type": SYNTHETIC_TASK_TYPE, "source": relative_source,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return root


def test_demo_replay_source_outside_the_curated_corpus_is_refused(tmp_path, monkeypatch):
    crafted = _crafted_corpus(tmp_path, relative_source="../outside.json")
    monkeypatch.setattr(revocompute_ctl, "SERVER_ROOT", crafted)
    staging = tmp_path / "server" / "demo" / "replays.next"
    with pytest.raises(SystemExit, match="outside the curated corpus"):
        materialize_demo_replays(_state(tmp_path))
    assert not staging.exists(), "a refused materialization must leave no staged tree behind"


@pytest.mark.parametrize("scenario_id", ["../escaped", "nested/escaped"])
def test_a_replay_id_that_cannot_be_a_bundle_name_is_refused_before_copying(
    tmp_path, monkeypatch, scenario_id
):
    """The id names the installed bundle, so it is validated before any path join.

    An escaping id would copy outside the demo state and then fail the loader; a
    slash id would raise an uncaught ``FileNotFoundError``. Both must fail closed
    with the loader's own refusal and leave nothing staged.
    """
    crafted = _crafted_corpus(
        tmp_path, relative_source="tests/data/bundle.json", scenario_id=scenario_id
    )
    monkeypatch.setattr(revocompute_ctl, "SERVER_ROOT", crafted)
    staging = tmp_path / "server" / "demo" / "replays.next"
    target = tmp_path / "server" / "demo" / "replays"
    with pytest.raises(SystemExit, match="invalid replay scenario id"):
        materialize_demo_replays(_state(tmp_path))
    assert not staging.exists()
    assert not target.exists()
    assert not list(tmp_path.rglob("escaped*"))


def test_demo_replay_source_must_be_a_checked_in_bundle(tmp_path, monkeypatch):
    crafted = _crafted_corpus(tmp_path, relative_source="tests/data/bundle.json")
    bundle_path = crafted / "tests" / "data" / "bundle.json"
    document = json.loads(bundle_path.read_text(encoding="utf-8"))
    document["payloads"][CAPTURED_ARTIFACT]["payload"] = "tampered"
    bundle_path.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setattr(revocompute_ctl, "SERVER_ROOT", crafted)
    with pytest.raises(SystemExit):
        materialize_demo_replays(_state(tmp_path))
