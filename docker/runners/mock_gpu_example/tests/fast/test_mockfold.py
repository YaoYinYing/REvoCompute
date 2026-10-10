# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The Mock GPU Example Runner proves the persistent/OOM machinery end to end.

These tests exercise the real family entrypoint (`run.sh` over a `task.json`)
and the real shared lifecycle, driving a configurable pseudo-device. They prove
the mechanism the ESMFold2/SimpleFold scientific acceptance depends on — per-item
identity, resume, bounded recovery, provenance, and fail-closed unsafe plans —
without a GPU. They make no scientific claim about any real model.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[5]
FAMILY = ROOT / "docker" / "runners" / "mock_gpu_example"
MOCKFOLD_PATH = FAMILY / "mockfold.py"
SHARED = ROOT / "docker" / "runners" / "common" / "runtime"

sys.path.insert(0, str(SHARED))
SPEC = importlib.util.spec_from_file_location("mockfold", MOCKFOLD_PATH)
assert SPEC and SPEC.loader
mockfold = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mockfold)


# ---------------------------------------------------------------------------
# The deterministic pseudo-model: resource-only recovery must not move a result
# ---------------------------------------------------------------------------


def test_a_resource_only_adjustment_never_changes_the_drawn_coordinates():
    """The comparison contract: resource-only recovery preserves the result.

    ``chunk_size``/``cpu_offload``/``token_budget`` lower the pseudo-device's
    memory demand and nothing else, so the pseudo-model draws byte-identical
    samples. That equivalence is exactly what a persistent-vs-single comparison
    asserts for a real Runner, and this is the CPU-only stand-in for it. A
    ``cache_clear``-only plan is a lever that fictitiously relieves nothing, so
    both demand and bytes are unchanged — which is exactly why the shared
    lifecycle drops it as a no-op before it consumes an attempt.
    """
    baseline = mockfold.draw_samples("h", 4, 7, {})
    baseline_demand = mockfold.memory_demand_mb(40, mockfold.resolve_sample_plan(4, 7, {}), {})
    for adjustments in (
        {"chunk_size": 512},
        {"cpu_offload": True},
        {"token_budget": 256},
        {"chunk_size": 512, "cpu_offload": True, "token_budget": 256},
    ):
        assert mockfold.draw_samples("h", 4, 7, adjustments) == baseline, adjustments
        # ... and the demand really did change, so the case is not vacuous.
        demand = mockfold.memory_demand_mb(40, mockfold.resolve_sample_plan(4, 7, adjustments), adjustments)
        assert demand < baseline_demand, adjustments

    assert mockfold.draw_samples("h", 4, 7, {"cache_clear": True}) == baseline
    assert (
        mockfold.memory_demand_mb(40, mockfold.resolve_sample_plan(4, 7, {"cache_clear": True}), {"cache_clear": True})
        == baseline_demand
    )


def test_scientific_and_backend_adjustments_change_the_coordinates():
    """A grouping or a backend change *is* a scientific-output change.

    ``sample_group_size`` draws the same requested samples under a different
    stream grouping, and ``kernel_backend`` is a numerical-backend change, so
    both move the coordinates. The runner reports them as such rather than as
    neutral resource knobs.
    """
    baseline = mockfold.draw_samples("h", 4, 7, {})
    grouped = mockfold.draw_samples("h", 4, 7, {"sample_group_size": 2})
    backended = mockfold.draw_samples("h", 4, 7, {"kernel_backend": "reference"})

    assert grouped != baseline, "a grouping change must move the samples"
    assert backended != baseline, "a backend change must move the samples"
    # The requested count and seed are untouched: sample j still carries seed+j.
    assert [sample["sample_seed"] for sample in grouped] == [7, 8, 9, 10]
    assert [sample["sample_seed"] for sample in baseline] == [7, 8, 9, 10]


# ---------------------------------------------------------------------------
# End-to-end through the real entrypoint
# ---------------------------------------------------------------------------


def _manifest(tmp_path: Path, records: dict[str, str], *, params: dict | None = None, snapshot: str = "snap-1") -> Path:
    source = tmp_path / "input.fasta"
    source.write_text("".join(f">{name}\n{sequence}\n" for name, sequence in records.items()), encoding="utf-8")
    task = tmp_path / "task.json"
    task.write_text(
        json.dumps(
            {
                "version": 4,
                "task_id": "mock-task",
                "task_type": "mock_folding",
                "inputs": {"sequence": [{"path": str(source), "original_name": "input.fasta", "sha256": snapshot}]},
                "params": params if params is not None else {"num_samples": 4, "seed": 7},
                "execution": {"batch_size": 1, "max_item_attempts": 3, "max_runtime_restarts": 1},
                "resource_adaptation": {
                    "stage": "recover",
                    "fallback_plans": [
                        {"label": "samples_two_at_a_time", "title": "two",
                         "adjustments": {"sample_group_size": 2, "cache_clear": True}},
                        {"label": "samples_one_at_a_time", "title": "one",
                         "adjustments": {"sample_group_size": 1, "cache_clear": True, "chunk_size": 512}},
                    ],
                },
                "resource_guidance": {
                    "plan_order": ["", "samples_two_at_a_time", "samples_one_at_a_time"],
                    "profiles": [],
                },
            }
        ),
        encoding="utf-8",
    )
    return task


def _run(task: Path, output: Path, *, free_vram_mb: int = 8192) -> subprocess.CompletedProcess[str]:
    environment = {
        **os.environ,
        "MOCK_DEVICE_FREE_VRAM_MB": str(free_vram_mb),
        "TASK_MANIFEST": str(task),
        "TASK_CONTEXT_SRC": str(SHARED / "task_context.sh"),
        "MOCKFOLD_FOLDER": str(MOCKFOLD_PATH),
        "MOCKFOLD_SHARED_DIR": str(SHARED),
    }
    return subprocess.run(
        ["bash", str(FAMILY / "run.sh"), "-i", str(task), "-o", str(output)],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def test_reference_runner_commits_one_directory_per_record_and_is_deterministic(tmp_path: Path) -> None:
    """One input -> one result, in input order, with a reproducible artifact."""
    task = _manifest(tmp_path, {"mock_alpha": "ACDEFG", "mock_beta": "MNPQRS", "mock_gamma": "WY"})
    output = tmp_path / "output"

    completed = _run(task, output)

    assert completed.returncode == 0, completed.stderr
    assert "REVODESIGN_TASK_OUTCOME:SUCCESS" in completed.stdout
    manifest = json.loads((output / "work_items.json").read_text(encoding="utf-8"))
    assert manifest["outcome"] == "SUCCESS"
    assert [entry["id"] for entry in manifest["items"]] == ["mock_alpha", "mock_beta", "mock_gamma"]
    assert not (output / ".tmp").exists()
    first = (output / "mock_alpha" / "mock_samples.json").read_bytes()

    # A second, independent run of the same input yields identical bytes.
    output2 = tmp_path / "output2"
    assert _run(task, output2).returncode == 0
    assert (output2 / "mock_alpha" / "mock_samples.json").read_bytes() == first


def test_a_real_oom_walks_the_declared_ladder_and_publishes_its_provenance(tmp_path: Path) -> None:
    """An adaptive-OOM step is auditable per attempt through the result surface.

    With a pseudo-device too small for the default concurrency, every item OOMs
    on the default path and recovers on the first declared fallback. Each item's
    ``work_items.json`` record names the plan, its scientific-impact class, the
    resource-only settings applied, and the effective scientific parameter set —
    and the server projection republishes exactly that class.
    """
    task = _manifest(tmp_path, {"mock_alpha": "ACDEFGHIKLMNPQRSTVWY", "mock_beta": "MNPQRSTVWYACDEFGHIKL"})
    output = tmp_path / "output"

    completed = _run(task, output, free_vram_mb=1600)

    assert completed.returncode == 0, completed.stderr
    manifest = json.loads((output / "work_items.json").read_text(encoding="utf-8"))
    assert manifest["outcome"] == "SUCCESS"
    for entry in manifest["items"]:
        assert entry["status"] == "SUCCEEDED"
        assert entry["attempts"] == 2, entry
        records = entry["recovery"]
        assert [record["plan_label"] for record in records] == ["", "samples_two_at_a_time"]
        # The default path is not a recovery action; the grouping rung is a
        # scientific-output change and is classified as one.
        assert [record["action"] for record in records] == ["", "scientific_output"]
        # Only the resource-only setting is filed under ``resources``; the
        # grouping is disclosed in the effective set instead.
        assert records[1]["resources"] == {"cache_clear": True}
        assert records[0]["effective_parameters"]["sample_groups"] == [4]
        assert records[1]["effective_parameters"]["sample_groups"] == [2, 2]
        # The requested count and seed survive the recovery at every attempt.
        assert records[1]["effective_parameters"]["num_samples"] == 4
        assert records[1]["effective_parameters"]["seed"] == 7
        # The measured OOM row is kept, at the same attempt index.
        oom_rows = [row for row in entry["resource_events"] if row["outcome"] == "oom"]
        assert oom_rows and oom_rows[0]["attempt"] == 1

    # The server publishes the runner's own class, not a re-derivation of it.
    from revocompute.resource_observations import (
        RECOVERY_ACTION_SCIENTIFIC_OUTPUT,
        work_items_projection,
    )

    projection = work_items_projection(str(output))
    assert projection["outcome"] == "SUCCESS"
    for item in projection["work_items"]:
        assert item["recovery_action"] == RECOVERY_ACTION_SCIENTIFIC_OUTPUT
        assert item["recovery"][-1]["effective_parameters"]["sample_groups"] == [2, 2]


def test_resource_only_recovery_preserves_the_unrecovered_result(tmp_path: Path) -> None:
    """A resource-only rung recovers memory and returns the *same* result.

    With a pseudo-device too small for the default path, the item OOMs and
    recovers on a ``cpu_offload`` rung that touches only execution. The committed
    artifact is byte-identical to the same input run without any recovery, which
    is exactly the equivalence a persistent-vs-single comparison asserts.
    """
    task = _manifest(tmp_path, {"mock_alpha": "ACDEFGHIKLMNPQRSTVWY"})
    declaration = json.loads(task.read_text(encoding="utf-8"))
    declaration["resource_adaptation"]["fallback_plans"] = [
        {"label": "offload", "title": "Offload to host", "adjustments": {"cpu_offload": True}}
    ]
    declaration["resource_guidance"]["plan_order"] = ["", "offload"]
    task.write_text(json.dumps(declaration), encoding="utf-8")

    baseline_out = tmp_path / "baseline"
    recovered_out = tmp_path / "recovered"
    assert _run(task, baseline_out, free_vram_mb=8192).returncode == 0
    assert _run(task, recovered_out, free_vram_mb=1500).returncode == 0

    manifest = json.loads((recovered_out / "work_items.json").read_text(encoding="utf-8"))
    entry = manifest["items"][0]
    assert entry["status"] == "SUCCEEDED"
    assert [record["action"] for record in entry["recovery"]] == ["", "resource_only"]
    assert entry["recovery"][1]["resources"] == {"cpu_offload": True}
    assert (recovered_out / "mock_alpha" / "mock_samples.json").read_bytes() == (
        baseline_out / "mock_alpha" / "mock_samples.json"
    ).read_bytes()


def test_the_numerical_backend_rung_is_classified_as_such(tmp_path: Path) -> None:
    """A kernel-backend recovery is a numerical-backend change, never resource_only."""
    task = _manifest(tmp_path, {"mock_alpha": "ACDEFGHIKLMNPQRSTVWY"})
    declaration = json.loads(task.read_text(encoding="utf-8"))
    declaration["resource_adaptation"]["fallback_plans"] = [
        {"label": "reference_kernels", "title": "Reference kernels",
         "adjustments": {"kernel_backend": "reference"}}
    ]
    declaration["resource_guidance"]["plan_order"] = ["", "reference_kernels"]
    task.write_text(json.dumps(declaration), encoding="utf-8")
    output = tmp_path / "output"

    # Free VRAM between the default demand (2256 MiB) and the reference-backend
    # demand (1804 MiB), so the default OOMs and the backend rung fits.
    assert _run(task, output, free_vram_mb=1900).returncode == 0

    manifest = json.loads((output / "work_items.json").read_text(encoding="utf-8"))
    entry = manifest["items"][0]
    assert entry["status"] == "SUCCEEDED"
    assert [record["action"] for record in entry["recovery"]] == ["", "numerical_backend"]
    # A backend key is never filed as a resource-only setting; its divergence is
    # disclosed in the effective set instead.
    assert entry["recovery"][1]["resources"] == {}
    assert entry["recovery"][0]["effective_parameters"]["kernel_backend"] == "triton"
    assert entry["recovery"][1]["effective_parameters"]["kernel_backend"] == "reference"


def test_resume_preserves_item_identity_and_a_changed_snapshot_recomputes(tmp_path: Path) -> None:
    """Restart keeps every committed item; changed input recomputes."""
    task = _manifest(tmp_path, {"mock_alpha": "ACDEFG", "mock_beta": "MNPQRS", "mock_gamma": "WY"})
    output = tmp_path / "output"
    assert _run(task, output).returncode == 0

    marker = output / "mock_alpha" / "mock_samples.json"
    touched = marker.stat().st_mtime_ns
    resumed = _run(task, output)
    assert resumed.returncode == 0
    assert "REVODESIGN_STAGE:model_loading" not in resumed.stdout, "a committed task must not reload"
    assert marker.stat().st_mtime_ns == touched, "a committed item must not be recomputed"
    manifest = json.loads((output / "work_items.json").read_text(encoding="utf-8"))
    assert all(entry["attempts"] == 1 for entry in manifest["items"])

    # Same item names, different immutable input snapshot: every item reruns.
    changed = _manifest(tmp_path, {"mock_alpha": "ACDEFG", "mock_beta": "MNPQRS", "mock_gamma": "WY"}, snapshot="snap-2")
    changed_out = tmp_path / "changed"
    assert _run(changed, changed_out).returncode == 0
    reassembled = json.loads((changed_out / "work_items.json").read_text(encoding="utf-8"))
    assert reassembled["input_snapshot"] == "snap-2"
    assert all(entry["attempts"] == 1 for entry in reassembled["items"])


def test_an_unsafe_plan_is_refused_before_execution(tmp_path: Path) -> None:
    """Automatic recovery fails closed on a plan that names a scientific parameter.

    The server rejects such a declaration, but the runner refuses it on its own
    too: the plan is dropped before the ladder is walked and recorded as refused,
    so it can never mutate the scientific execution.
    """
    task = _manifest(tmp_path, {"mock_alpha": "ACDEFGHIKLMNPQRSTVWY"})
    declaration = json.loads(task.read_text(encoding="utf-8"))
    declaration["resource_adaptation"]["fallback_plans"] = [
        {"label": "cheat", "title": "change the seed", "adjustments": {"seed": 99}}
    ]
    declaration["resource_guidance"]["plan_order"] = ["", "cheat"]
    task.write_text(json.dumps(declaration), encoding="utf-8")
    output = tmp_path / "output"

    completed = _run(task, output, free_vram_mb=1600)

    # The default path OOMs, the only fallback was refused, so the item fails.
    assert completed.returncode != 0
    manifest = json.loads((output / "work_items.json").read_text(encoding="utf-8"))
    entry = manifest["items"][0]
    assert entry["status"] == "FAILED_RESOURCE"
    assert entry["attempts"] == 1
    assert manifest["outcome"] == "FAILED"
    assert manifest["refused_unsafe_plans"] == ["cheat"]
    # Every recorded attempt is the default path, and no item directory exists.
    assert [record["plan_label"] for record in entry["recovery"]] == [""]
    assert not (output / "mock_alpha").exists()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
