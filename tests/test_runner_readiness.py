# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
import shutil
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / "run"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from revocompute.doctor import Diagnostic, DoctorReport  # noqa: E402
from revocompute.live_tests import atomic_write_json, sha256_file  # noqa: E402
from revocompute_ctl.readiness import (  # noqa: E402
    RunnerReadinessStatus,
    format_readiness_json,
    format_readiness_text,
    run_runner_status,
    resolve_runner_readiness,
)
from revocompute_ctl.registry import RuntimeFamily  # noqa: E402
from revocompute_ctl.registry import RegistryError  # noqa: E402
from revocompute_ctl.registry import _build_provenance, load_plugin_families  # noqa: E402
from revocompute_ctl.live_test import load_validation_identity  # noqa: E402


class _State:
    def __init__(self, root: Path):
        self.root = root

    def server_dir(self) -> str:
        return str(self.root / "server")

    def exported(self) -> dict[str, str]:
        return {}

    def get(self, key: str) -> str:
        return str(self.root / "runners") if key == "RUNNER_SOURCE_ROOT" else ""


@pytest.fixture
def evidence(tmp_path: Path, monkeypatch):
    family_root = tmp_path / "runners" / "demo"
    family_root.mkdir(parents=True)
    family = RuntimeFamily(
        "demo",
        "1",
        "demo.def",
        "demo.sif",
        str(tmp_path / "images" / "demo.sif"),
        root=family_root,
    )
    active = Path(family.slurm_image)
    active.parent.mkdir()
    active.write_bytes(b"active-sif")
    current = {
        "build_provenance_digest": "sha256:build-current",
        "apptainer_version": "apptainer version 1.4.5",
    }
    plan = SimpleNamespace(
        digest="sha256:test-current",
        select=lambda collection: (SimpleNamespace(id="minimal"),) if collection == "smoke" else (),
    )
    monkeypatch.setattr("revocompute_ctl.readiness.diagnose", lambda *_args, **_kwargs: DoctorReport(()))
    monkeypatch.setattr("revocompute_ctl.readiness._build_provenance", lambda *_args: current)
    monkeypatch.setattr("revocompute_ctl.readiness.sif_stale", lambda *_args: False)
    monkeypatch.setattr(
        "revocompute_ctl.readiness.load_validation_identity",
        lambda *_args: (plan, "sha256:config-current"),
    )
    return _State(tmp_path), family, active


def _write_receipt(family: RuntimeFamily, active: Path, **updates) -> Path:
    receipt = {
        "runner_family": family.name,
        "passed": True,
        "ended_at": "2026-09-05T12:00:00+00:00",
        "sif_sha256": sha256_file(active),
        "build_provenance_digest": "sha256:build-current",
        "test_definition_digest": "sha256:test-current",
        "configuration_digest": "sha256:config-current",
        "cases": [{"case_id": "minimal", "passed": True}],
    }
    receipt.update(updates)
    path = active.parent / "receipts" / f"{family.name}.json"
    atomic_write_json(path, receipt)
    return path


def test_doctor_failure_is_not_configured_and_takes_precedence(evidence, monkeypatch):
    state, family, active = evidence
    _write_receipt(family, active)
    diagnostic = Diagnostic("E3002", "error", "schema", "secret-free contract error", family.name)
    monkeypatch.setattr(
        "revocompute_ctl.readiness.diagnose", lambda *_args, **_kwargs: DoctorReport((diagnostic,))
    )
    monkeypatch.setattr(
        "revocompute_ctl.readiness.sif_stale",
        lambda *_args: (_ for _ in ()).throw(AssertionError("artifact should not be inspected")),
    )

    result = resolve_runner_readiness(state, family)

    assert result.status is RunnerReadinessStatus.NOT_CONFIGURED
    assert result.reason_code == "DOCTOR_FAILED"
    assert result.doctor_diagnostics[0].code == "E3002"
    assert "secret-free contract error" in result.message


def test_missing_active_sif_is_not_built(evidence):
    state, family, active = evidence
    active.unlink()

    result = resolve_runner_readiness(state, family)

    assert result.status is RunnerReadinessStatus.NOT_BUILT
    assert result.reason_code == "SIF_MISSING"
    assert not result.sif_exists


def test_stale_build_takes_precedence_over_receipt(evidence, monkeypatch):
    state, family, active = evidence
    _write_receipt(family, active)
    monkeypatch.setattr("revocompute_ctl.readiness.sif_stale", lambda *_args: True)

    result = resolve_runner_readiness(state, family)

    assert result.status is RunnerReadinessStatus.BUILD_STALE
    assert result.reason_code == "BUILD_PROVENANCE_STALE"
    assert result.receipt_exists is False


def test_current_build_without_receipt_is_not_validated(evidence):
    state, family, _active = evidence

    result = resolve_runner_readiness(state, family)

    assert result.status is RunnerReadinessStatus.NOT_VALIDATED
    assert result.reason_code == "RECEIPT_MISSING"


@pytest.mark.parametrize(
    "updates",
    [
        {"sif_sha256": "sha256:wrong-sif"},
        {"configuration_digest": "sha256:changed-task-or-runtime"},
        {"test_definition_digest": "sha256:changed-test"},
        {"cases": []},
    ],
)
def test_wrong_artifact_contract_or_coverage_makes_validation_stale(evidence, updates):
    state, family, active = evidence
    _write_receipt(family, active, **updates)

    result = resolve_runner_readiness(state, family)

    assert result.status is RunnerReadinessStatus.VALIDATION_STALE
    assert result.reason_code == "RECEIPT_STALE"
    assert result.build_provenance_current is True


def test_current_evidence_is_ready_and_serializes_stably(evidence):
    state, family, active = evidence
    _write_receipt(family, active)

    result = resolve_runner_readiness(state, family)
    payload = json.loads(format_readiness_json([result]))

    assert result.status is RunnerReadinessStatus.READY
    assert result.ready
    assert result.required_smoke_cases == ("minimal",)
    assert result.passed_smoke_cases == ("minimal",)
    assert payload == {"runners": [result.as_dict()]}
    assert "READY" in format_readiness_text([result], detailed=True)


def test_status_output_does_not_include_environment_secrets(evidence, monkeypatch):
    state, family, active = evidence
    state.exported = lambda: {"API_TOKEN": "never-print-this"}
    _write_receipt(family, active, unexpected_secret="never-print-this")

    result = resolve_runner_readiness(state, family)
    rendered = format_readiness_json([result]) + format_readiness_text([result], detailed=True)

    assert "never-print-this" not in rendered


def test_candidate_does_not_determine_active_readiness(evidence):
    state, family, active = evidence
    active.unlink()
    Path(f"{family.slurm_image}.next").write_bytes(b"validated-candidate")

    result = resolve_runner_readiness(state, family)

    assert result.status is RunnerReadinessStatus.NOT_BUILT


def test_runner_status_all_lists_enabled_families_and_json(evidence, monkeypatch, capsys):
    state, family, active = evidence
    _write_receipt(family, active)
    disabled = RuntimeFamily("disabled", "1", "disabled.def", "disabled.sif", "disabled.sif")
    state.get = lambda key: "demo" if key == "ENABLED_TASKRUNNERS" else ""
    monkeypatch.setattr("revocompute_ctl.readiness.load_instance_families", lambda _state: [family, disabled])

    results = run_runner_status(state, runner=None, all_runners=True, as_json=True)
    payload = json.loads(capsys.readouterr().out)

    assert [item.runner_family for item in results] == ["demo"]
    assert [item["runner_family"] for item in payload["runners"]] == ["demo"]


def test_runner_status_unknown_or_disabled_fails_cleanly(evidence, monkeypatch):
    state, family, _active = evidence
    state.get = lambda key: "other" if key == "ENABLED_TASKRUNNERS" else ""
    monkeypatch.setattr("revocompute_ctl.readiness.load_instance_families", lambda _state: [family])

    with pytest.raises(RegistryError, match="Unknown or disabled Runner Family"):
        run_runner_status(state, runner="demo", all_runners=False, as_json=False)


def test_runner_status_all_accepts_zero_family_instance(evidence, monkeypatch, capsys):
    state, _family, _active = evidence
    monkeypatch.setattr("revocompute_ctl.readiness.load_instance_families", lambda _state: [])

    assert run_runner_status(state, runner=None, all_runners=True, as_json=True) == []
    assert json.loads(capsys.readouterr().out) == {"runners": []}


def test_real_identity_keeps_build_and_validation_freshness_separate(tmp_path):
    repo = tmp_path / "repo"
    runners = repo / "docker" / "runners"
    shutil.copytree(ROOT / "docker" / "runners" / "alphafold3", runners / "alphafold3")
    shutil.copytree(ROOT / "docker" / "runners" / "common", runners / "common")
    fixture = repo / "tests" / "data" / "json" / "alphafold3_tiny.json"
    fixture.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "tests" / "data" / "json" / "alphafold3_tiny.json", fixture)

    original = load_plugin_families(runners)[0]
    image = tmp_path / "images" / "alphafold3_v1.sif"
    image.parent.mkdir()
    image.write_bytes(b"exact-active-sif")
    family = replace(original, slurm_image=str(image))
    state = _State(tmp_path)
    provenance = _build_provenance(state, family)
    atomic_write_json(
        image.parent / "digest" / "image-sif.json",
        {family.name: {**provenance, "sif_sha256": sha256_file(image)}},
    )
    plan, config_digest = load_validation_identity(family)
    atomic_write_json(
        image.parent / "receipts" / "alphafold3.json",
        {
            "runner_family": family.name,
            "passed": True,
            "ended_at": "2026-09-05T12:00:00+00:00",
            "sif_sha256": sha256_file(image),
            "build_provenance_digest": provenance["build_provenance_digest"],
            "test_definition_digest": plan.digest,
            "configuration_digest": config_digest,
            "cases": [{"case_id": "minimal-alphafold3", "passed": True}],
        },
    )

    assert resolve_runner_readiness(state, family).status is RunnerReadinessStatus.READY

    task = family.root / "tasks" / "predict" / "task.yaml"
    original_task = task.read_text(encoding="utf-8")
    task.write_text(original_task.replace("summary: AlphaFold 3", "summary: Changed AlphaFold 3"), encoding="utf-8")
    task_changed = resolve_runner_readiness(state, family)
    assert task_changed.status is RunnerReadinessStatus.VALIDATION_STALE
    assert task_changed.build_provenance_current

    task.write_text(original_task, encoding="utf-8")
    test_plan = family.root / "test.yaml"
    test_plan.write_text(test_plan.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    test_changed = resolve_runner_readiness(state, family)
    assert test_changed.status is RunnerReadinessStatus.VALIDATION_STALE
    assert test_changed.build_provenance_current

    run_script = family.root / "run.sh"
    run_script.write_text(run_script.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert resolve_runner_readiness(state, family).status is RunnerReadinessStatus.BUILD_STALE
