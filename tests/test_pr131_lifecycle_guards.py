# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Mutation-sensitive guards for the environment/execution separation.

These tests fail if a guard is removed: overlay-only edits must not rebuild a
SIF or activate unvalidated code, an environment edit must invalidate the old
receipt, activation must be receipt-gated, an overlay entrypoint must resolve
inside the mounted bundle, and a composed acceptance must bind the exact
candidates it ran.  Every fixture is a temporary runner tree.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "run"))

from revocompute import runtime_bundle as rb  # noqa: E402
from revocompute import runner_live_test  # noqa: E402
from revocompute.artifact_evidence import write_artifact_evidence  # noqa: E402
from revocompute.doctor import diagnose  # noqa: E402
from revocompute.live_tests import receipt_matches, sha256_file  # noqa: E402
from revocompute.runner_bundles import materialize_runner_bundles  # noqa: E402
from revocompute.runner_live_test import (  # noqa: E402
    TaskResourceSnapshot,
    ValidationIdentity,
    _composed_artifacts,
    _composed_for,
    _verify_composed_artifacts,
)
from revocompute.runner_readiness import (  # noqa: E402
    RunnerReadinessStatus,
    format_readiness_text,
    resolve_runner_readiness,
)
from revocompute.runner_registry import (  # noqa: E402
    RegistryError,
    RuntimeFamily,
    _build_provenance,
    load_plugin_families,
    sif_stale,
)


class _State:
    def __init__(self, root: Path, values: dict[str, str] | None = None):
        self.root = root
        self._values = values or {}

    def server_dir(self) -> str:
        return str(self.root / "server")

    def get(self, key: str) -> str:
        return self._values.get(key, "")

    def exported(self) -> dict[str, str]:
        return {}


def _deployment(tmp_path: Path, name: str = "demo") -> tuple[_State, RuntimeFamily]:
    root = tmp_path / "runners" / name
    root.mkdir(parents=True)
    (root / f"{name}.def").write_text("Bootstrap: docker\nFrom: scratch\n", encoding="utf-8")
    run_script = root / "run.sh"
    run_script.write_text("#!/bin/sh\necho one\n", encoding="utf-8")
    run_script.chmod(0o755)
    state = _State(
        tmp_path,
        {
            "RUNTIME_BUNDLE_DIR": str(tmp_path / "runtime-bundles"),
            "REVODESIGN_APPTAINER_VERSION": "apptainer version 1.4.0",
        },
    )
    family = RuntimeFamily(
        name,
        "1",
        f"{name}.def",
        f"{name}.sif",
        str(tmp_path / "images" / f"{name}.sif"),
        root=root,
        runtime_overlay=(f"{name}/run.sh",),
    )
    return state, family


def _sif(family: RuntimeFamily, contents: bytes = b"sif-bytes") -> Path:
    path = Path(family.slurm_image)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(contents)
    return path


def _publish(state: _State, family: RuntimeFamily) -> str:
    digest, _ = rb.materialize(family.root.parent, family.runtime_overlay, str(state.get("RUNTIME_BUNDLE_DIR")))
    rb.write_index(str(state.get("RUNTIME_BUNDLE_DIR")), {family.name: digest})
    return digest


def test_overlay_only_edit_reuses_the_sif_and_does_not_activate_untested_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, family = _deployment(tmp_path)
    store = str(state.get("RUNTIME_BUNDLE_DIR"))
    active = _publish(state, family)
    sif = _sif(family)
    sif_before = sif.read_bytes()
    provenance_before = _build_provenance(state, family)["build_provenance_digest"]
    commands: list[list[str]] = []
    monkeypatch.setattr(
        "revocompute.runner_registry.run_cmd", lambda argv, **_kwargs: commands.append(list(argv))
    )
    # This edited source has no receipt, so restart activation must refuse it.
    monkeypatch.setattr(runner_live_test, "receipt_valid_for_bundle", lambda *_a, **_k: False)

    (family.root / "run.sh").write_text("#!/bin/sh\necho two\n", encoding="utf-8")
    candidate = materialize_runner_bundles(state, [family])["demo"]

    assert candidate != active
    # Same environment identity and same SIF bytes: no rebuild was requested.
    assert _build_provenance(state, family)["build_provenance_digest"] == provenance_before
    assert sif.read_bytes() == sif_before
    assert not any("build" in command[:3] for command in commands)
    # The snapshot exists for validation but is not what a new submission pins.
    assert rb.resolve_pinned(store, candidate) is not None
    assert rb.load_index(store) == {"demo": active}
    assert rb.resolve_for_submission(store, rb.load_index(store), "demo", declares_overlay=True) == active


def test_environment_only_edit_changes_the_build_identity_and_old_receipt_cannot_authorize(
    tmp_path: Path,
) -> None:
    state, family = _deployment(tmp_path)
    bundle = _publish(state, family)
    sif = _sif(family)
    before = _build_provenance(state, family)
    write_artifact_evidence(family, sha256_file(sif), "build", before)
    assert sif_stale(state, family, str(sif)) is False

    (family.root / "demo.def").write_text(
        "Bootstrap: docker\nFrom: scratch\n# new environment lock\n", encoding="utf-8"
    )
    after = _build_provenance(state, family)

    assert after["build_provenance_digest"] != before["build_provenance_digest"]
    assert sif_stale(state, family, str(sif)) is True
    # The overlay did not move, so the Runtime Bundle identity is unchanged.
    assert rb.overlay_digest(family.root.parent, family.runtime_overlay) == bundle
    old_receipt = {
        "receipt_contract_version": 2,
        "passed": True,
        "sif_sha256": sha256_file(sif),
        "build_provenance_digest": before["build_provenance_digest"],
        "test_definition_digest": "test",
        "configuration_digest": "config",
        "cases": [{"case_id": "minimal", "passed": True}],
    }
    assert not receipt_matches(
        old_receipt,
        sif_sha256=sha256_file(sif),
        build_provenance_digest=after["build_provenance_digest"],
        test_definition_digest="test",
        configuration_digest="config",
        required_case_ids={"minimal"},
        runtime_bundle_sha256=bundle,
    )


def _readiness_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A synthetic family whose build and live-test evidence are current."""
    state, family = _deployment(tmp_path)
    active = _publish(state, family)
    sif = _sif(family)
    plan = SimpleNamespace(
        digest="test",
        select=lambda collection, **_kwargs: (SimpleNamespace(id="minimal"),) if collection == "smoke" else (),
        omitted=(),
    )
    monkeypatch.setattr(
        "revocompute.runner_readiness.diagnose",
        lambda *_a, **_k: SimpleNamespace(ok=True, diagnostics=()),
    )
    monkeypatch.setattr(
        "revocompute.runner_readiness._build_provenance",
        lambda *_a: {"build_provenance_digest": "build", "apptainer_version": "1.4"},
    )
    monkeypatch.setattr("revocompute.runner_readiness.sif_stale", lambda *_a: False)
    monkeypatch.setattr(
        "revocompute.runner_readiness.load_validation_identity",
        lambda *_a, **_k: ValidationIdentity(plan, "config", (TaskResourceSnapshot("predict", None, ()),)),
    )
    write_artifact_evidence(family, sha256_file(sif), "build", {"build_provenance_digest": "build"})
    write_artifact_evidence(
        family,
        sha256_file(sif),
        "receipt",
        {
            "receipt_contract_version": 2,
            "runner_family": family.name,
            "passed": True,
            "sif_sha256": sha256_file(sif),
            "build_provenance_digest": "build",
            "test_definition_digest": "test",
            "configuration_digest": "config",
            "runtime_bundle_sha256": active,
            "cases": [{"case_id": "minimal", "passed": True}],
            "ended_at": "2026-10-31T00:00:00+00:00",
        },
    )
    return state, family, sif, active


def test_no_change_is_idempotent_and_keeps_the_prior_ready_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, family, _sif_path, active = _readiness_evidence(tmp_path, monkeypatch)
    assert resolve_runner_readiness(state, family).status is RunnerReadinessStatus.READY

    def unexpected(*_args, **_kwargs):
        raise AssertionError("an unchanged digest needs no receipt validation")

    monkeypatch.setattr(runner_live_test, "receipt_valid_for_bundle", unexpected)
    materialize_runner_bundles(state, [family])

    assert rb.load_index(str(state.get("RUNTIME_BUNDLE_DIR"))) == {"demo": active}
    assert resolve_runner_readiness(state, family).status is RunnerReadinessStatus.READY


def test_overlay_source_edit_reads_stale_before_activation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, family, sif, active = _readiness_evidence(tmp_path, monkeypatch)
    sif_sha = sha256_file(sif)

    (family.root / "run.sh").write_text("#!/bin/sh\necho edited\n", encoding="utf-8")
    source = rb.overlay_digest(family.root.parent, family.runtime_overlay)

    result = resolve_runner_readiness(state, family)

    assert result.status is RunnerReadinessStatus.VALIDATION_STALE
    assert result.reason_code == "RUNTIME_BUNDLE_CHANGED"
    assert result.next_action == "live-test"
    assert result.build_provenance_current is True
    assert result.sif_sha256 == sif_sha
    assert result.runtime_bundle_sha256 == source != active
    assert "Runtime bundle: STALE" in format_readiness_text([result], detailed=True)

    # An unpublished binding fails closed the same way: no source-digest fallback.
    rb.write_index(str(state.get("RUNTIME_BUNDLE_DIR")), {})
    unpublished = resolve_runner_readiness(state, family)
    assert unpublished.status is RunnerReadinessStatus.VALIDATION_STALE
    assert unpublished.reason_code == "RUNTIME_BUNDLE_CHANGED"


def test_activation_publishes_only_the_receipt_validated_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, family = _deployment(tmp_path)
    store = str(state.get("RUNTIME_BUNDLE_DIR"))
    active = _publish(state, family)
    (family.root / "run.sh").write_text("#!/bin/sh\necho two\n", encoding="utf-8")

    monkeypatch.setattr(runner_live_test, "receipt_valid_for_bundle", lambda *_a, **_k: False)
    candidate = materialize_runner_bundles(state, [family])["demo"]
    assert candidate != active
    assert rb.load_index(store) == {"demo": active}

    seen: list[tuple[str, str]] = []

    def _accept(_state, selected, digest, **_kwargs):
        seen.append((selected.name, digest))
        return True

    monkeypatch.setattr(runner_live_test, "receipt_valid_for_bundle", _accept)
    materialize_runner_bundles(state, [family])

    assert seen == [("demo", candidate)]
    assert rb.load_index(store) == {"demo": candidate}


def test_a_failed_live_test_leaves_the_prior_index_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, family = _deployment(tmp_path)
    store = str(state.get("RUNTIME_BUNDLE_DIR"))
    active = _publish(state, family)
    (family.root / "run.sh").write_text("#!/bin/sh\necho broken\n", encoding="utf-8")
    monkeypatch.setattr(runner_live_test, "load_plugin_families", lambda _root: [family])
    monkeypatch.setattr(runner_live_test, "prepare_live_test_server_image", lambda *_a: None)
    monkeypatch.setattr(
        runner_live_test.RunnerLiveTestWorker, "run", lambda *_a, **_k: SimpleNamespace(passed=False)
    )

    assert (
        runner_live_test.run_live_tests(
            state, runner="demo", task=None, collection="smoke", all_runners=False
        )
        is False
    )
    assert rb.load_index(store) == {"demo": active}


def test_entrypoint_declared_in_the_overlay_must_use_the_mounted_bundle(tmp_path: Path) -> None:
    runners = tmp_path / "runners"
    family = runners / "demo"
    family.mkdir(parents=True)
    (family / "run.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (family / "demo.def").write_text("Bootstrap: docker\nFrom: scratch\n", encoding="utf-8")
    manifest = {
        "api_version": 1,
        "id": "demo",
        "version": "1",
        "runtime": {
            "image_artifact": "demo.sif",
            "definition": "demo.def",
            "entrypoint": ["bash", "/app/revocompute/demo/run.sh"],
            "runtime_overlay": ["demo/run.sh"],
        },
    }
    (family / "plugin.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")

    with pytest.raises(RegistryError):
        load_plugin_families(runners)
    assert any(
        diagnostic.code == "E2005" and "must resolve under" in diagnostic.message
        for diagnostic in diagnose(runners, repo_root=ROOT).diagnostics
    )

    manifest["runtime"]["entrypoint"] = ["bash", "/opt/revocompute/runtime/demo/run.sh"]
    (family / "plugin.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    assert load_plugin_families(runners)[0].entrypoint[-1] == "/opt/revocompute/runtime/demo/run.sh"


def test_an_unmigrated_family_entrypoint_is_not_globally_rejected(tmp_path: Path) -> None:
    runners = tmp_path / "runners"
    common = runners / "common" / "runtime"
    common.mkdir(parents=True)
    (common / "task_context.sh").write_text("shared\n", encoding="utf-8")
    family = runners / "legacy"
    family.mkdir(parents=True)
    (family / "run.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (family / "legacy.def").write_text("Bootstrap: docker\nFrom: scratch\n", encoding="utf-8")
    manifest = {
        "api_version": 1,
        "id": "legacy",
        "version": "1",
        "runtime": {
            "image_artifact": "legacy.sif",
            "definition": "legacy.def",
            "entrypoint": ["bash", "/app/revocompute/run.sh"],
            "runtime_overlay": ["common/runtime/task_context.sh"],
        },
    }
    (family / "plugin.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")

    assert load_plugin_families(runners)[0].entrypoint[-1] == "/app/revocompute/run.sh"


def _composed_tree(tmp_path: Path) -> tuple[RuntimeFamily, RuntimeFamily]:
    runners = tmp_path / "runners"
    owner_root = runners / "composed_runner"
    (owner_root / "tasks" / "compose").mkdir(parents=True)
    (owner_root / "plugin.yaml").write_text(
        yaml.safe_dump(
            {
                "api_version": 1,
                "id": "composed_runner",
                "version": "1",
                "runtime": {"image_artifact": "composed_runner.sif", "definition": "composed_runner.def"},
                "tasks": ["tasks/compose/task.yaml"],
            }
        ),
        encoding="utf-8",
    )
    (owner_root / "tasks" / "compose" / "task.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "composed_task",
                "display_name": "Composed",
                "category": "analysis",
                "inputs": {
                    "sequence": {
                        "title": "Sequence",
                        "type": "protein_sequence",
                        "formats": ["fasta"],
                        "cardinality": {"min": 1, "max": 1},
                    }
                },
                "workflow": [
                    {"name": "prepare", "runner_args": ["-s", "prepare"]},
                    {"name": "calculate", "family": "companion_runner", "runner_args": ["-s", "run"]},
                ],
            }
        ),
        encoding="utf-8",
    )
    companion_root = runners / "companion_runner"
    companion_root.mkdir()
    (companion_root / "plugin.yaml").write_text(
        yaml.safe_dump(
            {
                "api_version": 1,
                "id": "companion_runner",
                "version": "1",
                "runtime": {"image_artifact": "companion_runner.sif", "definition": "companion_runner.def"},
                "tasks": [],
            }
        ),
        encoding="utf-8",
    )
    owner = RuntimeFamily(
        "composed_runner",
        "1",
        "composed_runner.def",
        "composed_runner.sif",
        str(tmp_path / "images" / "composed_runner.sif"),
        root=owner_root,
    )
    companion = RuntimeFamily(
        "companion_runner",
        "1",
        "companion_runner.def",
        "companion_runner.sif",
        str(tmp_path / "images" / "companion_runner.sif"),
        root=companion_root,
        runtime_overlay=("companion_runner/run.sh",),
    )
    return owner, companion


def test_composed_acceptance_binds_the_selected_companion_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, companion = _composed_tree(tmp_path)
    owner_artifact = Path(owner.slurm_image)
    owner_artifact.parent.mkdir(parents=True, exist_ok=True)
    owner_artifact.write_bytes(b"owner")
    companion_candidate = Path(f"{companion.slurm_image}.next")
    companion_candidate.parent.mkdir(parents=True, exist_ok=True)
    companion_candidate.write_bytes(b"companion candidate")
    write_artifact_evidence(
        companion, sha256_file(companion_candidate), "build", {"build_provenance_digest": "build-b"}
    )
    families = {owner.name: owner, companion.name: companion}
    monkeypatch.setattr(
        "revocompute.runner_live_test._build_provenance", lambda *_a: {"build_provenance_digest": "build-b"}
    )
    monkeypatch.setattr("revocompute.runner_readiness.bundle_digest", lambda *_a: "sha256:published")
    state = _State(tmp_path)
    candidate = "sha256:candidate-bundle"

    records = _composed_artifacts(
        state, owner, families, {"composed_task"}, candidate_bundles={companion.name: candidate}
    )

    assert records[0]["runtime_bundle_sha256"] == candidate
    _verify_composed_artifacts(state, records, families, candidate_bundles={companion.name: candidate})
    with pytest.raises(
        runner_live_test.LiveTestConfigurationError, match="changed after its identity was recorded"
    ):
        _verify_composed_artifacts(
            state, records, families, candidate_bundles={companion.name: "sha256:other"}
        )

    # A companion not selected in this pass keeps the published digest.
    unselected = _composed_artifacts(state, owner, families, {"composed_task"})
    assert unselected[0]["runtime_bundle_sha256"] == "sha256:published"


def test_composed_submission_refuses_a_missing_companion_record(tmp_path: Path) -> None:
    owner, companion = _composed_tree(tmp_path)
    families = {owner.name: owner, companion.name: companion}

    with pytest.raises(runner_live_test.LiveTestConfigurationError, match="no recorded artifact"):
        _composed_for(owner, "composed_task", [], families)


def test_a_task_pinned_to_a_refuses_when_a_is_gone_after_b_activation(tmp_path: Path) -> None:
    state, family = _deployment(tmp_path)
    store = str(state.get("RUNTIME_BUNDLE_DIR"))
    digest_a = materialize_runner_bundles(state, [family], activate=False)["demo"]
    rb.write_index(store, {"demo": digest_a})
    (family.root / "run.sh").write_text("#!/bin/sh\necho two\n", encoding="utf-8")
    digest_b = materialize_runner_bundles(state, [family], activate=False)["demo"]
    rb.write_index(store, {"demo": digest_b})
    assert digest_b != digest_a

    assert (
        rb.resolve_for_submission(store, rb.load_index(store), "demo", declares_overlay=True, digest=digest_a)
        == digest_a
    )
    rb._remove_tree(rb.bundle_directory(store, digest_a))

    with pytest.raises(rb.RuntimeBundleError, match="unavailable"):
        rb.resolve_for_submission(store, rb.load_index(store), "demo", declares_overlay=True, digest=digest_a)
    assert (
        rb.resolve_for_submission(store, rb.load_index(store), "demo", declares_overlay=True, digest=digest_b)
        == digest_b
    )
