# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import sys
import json
from pathlib import Path
from revocompute import resource_observations as ro
from revocompute.db import TaskDatabase
from revocompute.resource_model import FallbackPlan
from revocompute.task_types import ResourceAdaptation
from server.test_resource_adaptation import _observation

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "docker/runners/common/runtime"))

def test_published_guidance_binds_only_the_revision_runtime_and_device_it_names(tmp_path):
    """The server's output and the runner's binder must agree on the identity.

    Two revisions are qualified in one store on the same GPU. The runner's own
    binder, driven with the block the server actually published, must select its
    own revision's threshold and nothing when its revision, runtime, or device
    has no entry — the end-to-end form of the isolation the unit tests assert.
    """
    from persistent_runner import PlanSequence

    store = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    for revision, threshold_vram in (("fast", 2000), ("standard", 4000)):
        for index in range(4):
            store.record_resource_observation(
                _observation(
                    model_revision=revision,
                    task_id=f"{revision}{index:026d}",
                    work_item=f"p{revision}{index}",
                    attempt=1,
                )
            )
        store.record_resource_observation(
            _observation(
                model_revision=revision,
                features={
                    "runner": "gpu_runner",
                    "model_revision": revision,
                    "runtime_fingerprint": "fp-1",
                    "sequence_length": threshold_vram,
                    "sequence_count": 1,
                    "batch_size": 1,
                    "sample_count": 1,
                    "parameters": {},
                },
                # The *default* plan is the one that OOMed, so this profile's
                # evidence is that its default is a known failure above the
                # threshold — the reactive ladder is not what the test exercises.
                task_id=f"{revision}oom",
                work_item=f"p{revision}9",
                attempt=2,
                outcome="oom",
                available_mb=100,
                plan_label="",
            )
        )
    plans = FallbackPlan.parse_all([{"label": "split", "adjustments": {"sample_group_size": 1}}])
    adaptation = ResourceAdaptation(stage="avoid", fallback_plans=plans)
    device = {"model": "A100-PCIE-40GB", "total_vram_mb": 40960}

    guidance = ro.observations_for_guidance("gpu_runner", adaptation, store=store)
    assert [entry["model_revision"] for entry in guidance["profiles"]] == ["fast", "standard"]

    def bind(revision, fingerprint, bound_device=device):
        sequence = PlanSequence(
            adaptation.to_dict(), {**guidance, "plan_order": ["", "split"]}, {"max_item_attempts": 2}
        )
        sequence.bind_identity(revision, fingerprint, bound_device)
        return sequence.plan_for(0, [], scale=2000).label

    assert bind("fast", "fp-1") == "split", "the evidenced default is skipped for its own revision"
    assert bind("standard", "fp-1") == "", "a foreign revision keeps the default path"
    assert bind("fast", "fp-other") == "", "a changed runtime keeps the default path"
    assert bind("fast", "fp-1", {"model": "H100-PCIE-80GB", "total_vram_mb": 81559}) == "", (
        "a different device keeps the default path"
    )


def test_a_sample_grouping_plan_publishes_its_runner_class_across_layers(tmp_path):
    """The class the runner assigns is the class the ResultManifest publishes.

    A ``sample_group_size`` split is a scientific-output change, not a neutral
    resource knob, so the runner classifies it ``scientific_output`` and the
    server must republish exactly that — the runner classification and the
    server projection agree on this key across layers.
    """
    from persistent_runner import classify_adjustments

    runner_class = classify_adjustments({"sample_group_size": 1, "cache_clear": True})
    assert runner_class == "scientific_output"
    assert runner_class == ro.RECOVERY_ACTION_SCIENTIFIC_OUTPUT

    result_dir = tmp_path / "grouping"
    result_dir.mkdir()
    (result_dir / "work_items.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "a",
                        "status": "SUCCEEDED",
                        "recovery": [
                            {"attempt": 1, "plan_label": "", "action": "", "resources": {},
                             "effective_parameters": {"sample_groups": [4]}},
                            {
                                "attempt": 2,
                                "plan_label": "samples_two_at_a_time",
                                "action": runner_class,
                                "resources": {},
                                "effective_parameters": {"sample_groups": [2, 2]},
                            },
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    projection = ro.work_items_projection(str(result_dir))

    item = projection["work_items"][0]
    assert item["recovery_action"] == ro.RECOVERY_ACTION_SCIENTIFIC_OUTPUT
    assert [record["action"] for record in item["recovery"]] == ["", "scientific_output"]
    assert item["recovery"][-1]["effective_parameters"]["sample_groups"] == [2, 2]
