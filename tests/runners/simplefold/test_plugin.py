# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""SimpleFold persistent multi-item plugin contract.

No GPU and no network: ``tests/runners/simplefold/fake_modules`` supplies a
CPU-only ``simplefold`` package that mirrors upstream's call seams, and the
plugin is driven either directly or through the shared ``persistent_runner``
lifecycle. The fake counts model loads, records every stream seed, and can fail
one record or reproduce a deterministic CUDA OOM, so the tests exercise the real
seams rather than a mock of them.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
FAMILY = ROOT / "docker/runners/simplefold"
COMMON = ROOT / "docker/runners/common"
FAKE_MODULES = Path(__file__).resolve().parent / "fake_modules"

DEFAULT_PARAMS = {
    "model": "simplefold_1.6B",
    "num_steps": 2,
    "tau": 0.01,
    "num_samples": 2,
    "predict_plddt": True,
    "output_format": "mmcif",
    "seed": 7,
}
PLANS = {
    "one": {"label": "one", "title": "One at a time", "adjustments": {"sample_group_size": 1}},
    "pair": {"label": "pair", "title": "Two at a time", "adjustments": {"sample_group_size": 2, "cache_clear": True}},
}


@pytest.fixture(scope="module")
def plugin_module():
    """Import ``offline_predict`` against the shared modules and the fake upstream.

    No fake ``torch`` is installed: the plugin treats an absent framework as
    "no device", and installing one process-wide would leak into every later
    test that probes for a real PyTorch.
    """
    for path in (str(COMMON), str(FAMILY), str(FAKE_MODULES)):
        if path not in sys.path:
            sys.path.insert(0, path)
    spec = importlib.util.spec_from_file_location("simplefold_plugin", FAMILY / "offline_predict.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module


@pytest.fixture()
def state(tmp_path, monkeypatch):
    """Per-test fake-module instrumentation state."""
    root = tmp_path / "fake-state"
    root.mkdir()
    monkeypatch.setenv("SIMPLEFOLD_FAKE_STATE", str(root))
    monkeypatch.delenv("SIMPLEFOLD_FAKE_OOM_MULTIPLICITY", raising=False)
    monkeypatch.delenv("SIMPLEFOLD_FAKE_FAIL_RECORDS", raising=False)
    from simplefold import inference

    return root, inference


def _plugin(plugin_module, tmp_path, params=None, plans=None):
    return plugin_module.SimpleFoldPlugin(
        {**DEFAULT_PARAMS, **(params or {})},
        checkpoint_dir=str(tmp_path),
        ccd_path=str(tmp_path / "ccd.pkl"),
        fallback_plans=plans if plans is not None else PLANS,
    )


def _config(items, **overrides):
    config = {
        "task_id": "t1",
        "runner": "simplefold",
        "items": items,
        "execution": {"max_item_attempts": 3},
        "resource_adaptation": {"stage": "recover", "fallback_plans": list(PLANS.values())},
        "resource_guidance": {"plan_order": ["", "one", "pair"]},
    }
    config.update(overrides)
    return config


def _sequence_items(*records):
    return [
        {"id": identifier, "order": index, "length": len(sequence), "sequence": sequence}
        for index, (identifier, sequence) in enumerate(records)
    ]


def _run(plugin_module, config, plugin, output_dir):
    from persistent_runner import execute_task

    return execute_task(config, plugin, output_dir=str(output_dir))


# -- work-item normalization ------------------------------------------------


def test_sequence_work_items_preserve_order_and_identifiers(tmp_path, plugin_module):
    from work_items import sequence_work_items

    fasta = tmp_path / "multi.fa"
    fasta.write_text(">zeta first\nACDEF\n>alpha\nMNPQR\n>zeta second\nSTVWY\n", encoding="utf-8")
    manifest = {
        "task_id": "t1",
        "params": DEFAULT_PARAMS,
        "inputs": {"sequence": [{"path": str(fasta), "original_name": "multi.fa", "sha256": "abc"}]},
    }

    items, payload = sequence_work_items(manifest, "sequence")

    assert [item["id"] for item in items] == ["zeta", "alpha", "zeta"]
    assert [item["order"] for item in items] == [0, 1, 2]
    assert [item["length"] for item in items] == [5, 5, 5]
    assert payload["sequence_count"] == 3
    assert payload["input_sha256"] == "abc"


def test_duplicate_or_unsafe_identifiers_are_rejected_before_any_path_exists(tmp_path, plugin_module):
    from persistent_runner import FatalTaskError, normalize_items

    with pytest.raises(FatalTaskError, match="duplicate work item identifiers"):
        normalize_items(_sequence_items(("a/b", "ACDE"), ("a b", "FGHI")))
    with pytest.raises(FatalTaskError, match="without an identifier"):
        normalize_items([{"id": "ok", "length": 1}, {"id": "   ", "length": 1}])
    # Nothing was created for the rejected items.
    assert list(tmp_path.iterdir()) == []


def test_invalid_record_is_rejected_while_the_rest_still_run(tmp_path, plugin_module, state):
    """A record the researcher cannot sample fails alone, not the whole task."""
    root, _inference = state
    items = _sequence_items(("good", "ACDE"), ("bad", "ACD*"), ("also_good", "FGHI"))
    plugin = _plugin(plugin_module, tmp_path)
    output = tmp_path / "out"

    manifest = _run(plugin_module, _config(items), plugin, output)

    assert manifest["outcome"] == "PARTIAL_SUCCESS"
    states = {entry["id"]: entry["status"] for entry in manifest["items"]}
    assert states["bad"] == "FAILED_INPUT"
    assert states["good"] == states["also_good"] == "SUCCEEDED"
    assert (output / "good" / "predictions_simplefold_1.6B" / "good_sampled_0.cif").is_file()
    assert (output / "also_good" / "run_metadata.json").is_file()
    assert not (output / "bad").exists()


# -- persistent runtime -----------------------------------------------------


def test_runtime_initializes_once_for_a_multi_item_task(tmp_path, plugin_module, state):
    root, inference = state
    items = _sequence_items(("a", "ACDE"), ("b", "FGHI"), ("c", "KLMN"))
    plugin = _plugin(plugin_module, tmp_path)
    output = tmp_path / "out"

    manifest = _run(plugin_module, _config(items), plugin, output)

    assert manifest["outcome"] == "SUCCESS"
    assert inference.fake_loads() == 4, "one folding model, one pLDDT pair, one ESM-2, one utilities set"
    assert len(list(output.glob("*/run_metadata.json"))) == 3


def test_resume_skips_committed_items_without_reloading_the_model(tmp_path, plugin_module, state):
    root, inference = state
    items = _sequence_items(("a", "ACDE"), ("b", "FGHI"))
    plugin = _plugin(plugin_module, tmp_path)
    output = tmp_path / "out"
    manifest = _run(plugin_module, _config(items), plugin, output)
    assert manifest["outcome"] == "SUCCESS"

    loads_before = inference.fake_loads()
    seeds_before = inference.fake_seeds()
    resumed = _run(plugin_module, _config(items), _plugin(plugin_module, tmp_path), output)

    assert resumed["outcome"] == "SUCCESS"
    assert inference.fake_loads() == loads_before, "a fully committed task must not reload the runtime"
    assert inference.fake_seeds() == seeds_before, "committed items must not be recomputed"


def test_each_item_commits_its_own_directory_and_staging_is_never_a_result(tmp_path, plugin_module, state):
    root, _inference = state
    items = _sequence_items(("a", "ACDE"), ("b", "FGHI"))
    plugin = _plugin(plugin_module, tmp_path)
    output = tmp_path / "out"

    manifest = _run(plugin_module, _config(items), plugin, output)

    assert manifest["outcome"] == "SUCCESS"
    for name in ("a", "b"):
        assert (output / name).is_dir()
        assert not (output / ".tmp").exists()
    assert not any((output / ".tmp").glob("*"))


# -- failure semantics ------------------------------------------------------


def test_a_failed_item_yields_partial_success_while_the_rest_complete(tmp_path, plugin_module, state, monkeypatch):
    monkeypatch.setenv("SIMPLEFOLD_FAKE_FAIL_RECORDS", "b")
    items = _sequence_items(("a", "ACDE"), ("b", "FGHI"), ("c", "KLMN"))
    plugin = _plugin(plugin_module, tmp_path)
    output = tmp_path / "out"

    manifest = _run(plugin_module, _config(items), plugin, output)

    assert manifest["outcome"] == "PARTIAL_SUCCESS"
    assert [entry["status"] for entry in manifest["items"]] == ["SUCCEEDED", "FAILED_RESOURCE", "SUCCEEDED"]
    assert not (output / "b").exists()
    assert (output / "c" / "run_metadata.json").is_file()


# -- OOM recovery -----------------------------------------------------------


def test_oom_retries_with_the_declared_fallback_preserving_samples_and_seed(
    tmp_path, plugin_module, state, monkeypatch
):
    # The requested four samples are one draw upstream; the declared pair plan
    # draws them as 2+2 and still produces all four.
    monkeypatch.setenv("SIMPLEFOLD_FAKE_OOM_MULTIPLICITY", "3")
    items = _sequence_items(("a", "ACDE"),)
    plugin = _plugin(plugin_module, tmp_path, {"num_samples": 4, "seed": 7})
    output = tmp_path / "out"
    config = _config(items, resource_guidance={"plan_order": ["", "pair", "one"]})

    manifest = _run(plugin_module, config, plugin, output)

    assert manifest["outcome"] == "SUCCESS"
    entry = manifest["items"][0]
    assert entry["attempts"] == 2
    assert [event["plan_label"] for event in entry["resource_events"]] == ["", "pair"]
    assert entry["resource_events"][0]["outcome"] == "oom"

    metadata = json.loads((output / "a" / "run_metadata.json").read_text(encoding="utf-8"))
    assert metadata["parameters"]["num_samples"] == 4, "the requested sample count must not change"
    assert metadata["parameters"]["seed"] == 7
    assert metadata["effective"]["seed"] == 7, "the item's seed must not change"
    assert metadata["effective"]["sample_group_size"] == 2
    assert metadata["effective"]["sample_groups"] == [2, 2]
    assert metadata["effective"]["sample_seeds"] == [7, 7, 8, 8]
    assert metadata["effective"]["plan_label"] == "pair"
    assert "2+2" in metadata["effective"]["plan_title"]
    assert "unchanged" in metadata["effective"]["plan_title"]
    assert len(metadata["structures"]) == 4
    assert len(metadata["confidence"]) == 4


def test_all_requested_samples_are_streamed_in_the_default_single_draw(plugin_module):
    """Default path: one multiplicity-N draw, one stream for all samples."""
    plan = plugin_module.resolve_sample_plan(3, 0, 7, None, None)
    assert plan["sample_groups"] == [3]
    assert plan["group_seeds"] == [7]
    assert plan["sample_seeds"] == [7, 7, 7]
    assert plan["label"] == "" and plan["title"] == ""


def test_retry_budget_is_finite_and_the_item_fails_as_a_resource_failure(tmp_path, plugin_module, state, monkeypatch):
    monkeypatch.setenv("SIMPLEFOLD_FAKE_OOM_MULTIPLICITY", "1")
    items = _sequence_items(("a", "ACDE"), ("b", "FGHI"))
    plugin = _plugin(plugin_module, tmp_path, {"num_samples": 2})
    output = tmp_path / "out"

    manifest = _run(plugin_module, _config(items, execution={"max_item_attempts": 3}), plugin, output)

    assert manifest["outcome"] == "FAILED"
    assert {entry["status"] for entry in manifest["items"]} == {"FAILED_RESOURCE"}
    assert all(entry["attempts"] == 3 for entry in manifest["items"])
    assert not (output / "a").exists() and not (output / "b").exists()


def test_unrecoverable_cuda_faults_propagate_instead_of_being_retried(tmp_path, plugin_module, state, monkeypatch):
    from simplefold import inference

    items = _sequence_items(("a", "ACDE"),)

    def explode(*args, **kwargs):
        raise RuntimeError("CUDA error: an illegal memory access was encountered")

    monkeypatch.setattr(inference, "generate_structure", explode)
    plugin = _plugin(plugin_module, tmp_path)
    output = tmp_path / "out"

    manifest = _run(plugin_module, _config(items), plugin, output)

    assert manifest["outcome"] == "FAILED"
    assert manifest["items"][0]["status"] == "FAILED_RUNTIME"
    assert "illegal memory access" in (manifest["items"][0]["error"] or "")


# -- declared adaptation plans ----------------------------------------------


def test_a_plan_naming_a_scientific_parameter_is_rejected_at_load(tmp_path, plugin_module):
    with pytest.raises(ValueError, match="non-resource parameter"):
        plugin_module.declared_plans(
            {"fallback_plans": [{"label": "cheat", "title": "Fewer samples", "adjustments": {"num_samples": 1}}]}
        )
    with pytest.raises(ValueError, match="non-resource parameter"):
        plugin_module.declared_plans(
            {"fallback_plans": [{"label": "seed", "title": "Different seed", "adjustments": {"seed": 1}}]}
        )
    with pytest.raises(ValueError, match="unknown fields"):
        plugin_module.declared_plans({"fallback_plans": [{"label": "x", "adjustments": {}, "stage": "recover"}]})
    with pytest.raises(ValueError, match="unique and non-empty"):
        plugin_module.declared_plans(
            {
                "fallback_plans": [
                    {"label": "same", "adjustments": {"sample_group_size": 1}},
                    {"label": "same", "adjustments": {"sample_group_size": 2}},
                ]
            }
        )
    assert plugin_module.declared_plans({"fallback_plans": list(PLANS.values())}).keys() == {"one", "pair"}


def test_sample_plan_splits_the_requested_samples_without_changing_the_count(plugin_module):
    default = plugin_module.resolve_sample_plan(5, 2, 42, None, None)
    assert default["sample_groups"] == [5]
    assert default["sample_group_size"] == 5
    assert default["item_seed"] == 44
    assert default["group_seeds"] == [44]
    assert default["sample_seeds"] == [44, 44, 44, 44, 44]

    split = plugin_module.resolve_sample_plan(5, 2, 42, PLANS["pair"]["adjustments"], PLANS["pair"])
    assert split["sample_groups"] == [2, 2, 1]
    assert split["group_seeds"] == [44, 45, 46]
    assert split["sample_seeds"] == [44, 44, 45, 45, 46]
    assert sum(split["sample_groups"]) == 5
    assert split["cache_clear"] is True
    assert split["label"] == "pair"
    assert "2+2+1" in split["title"]
    assert plugin_module.resolve_sample_plan(3, 0, 1, {"group_size": 1}, PLANS["one"])["sample_groups"] == [1, 1, 1]


def test_a_recognized_execution_key_this_plugin_cannot_realize_is_reported(plugin_module):
    """A resource key is not silently reinterpreted as an implemented one."""
    plan = {"label": "offload", "title": "Offload to CPU", "adjustments": {"cpu_offload": True}}
    plans = plugin_module.declared_plans({"fallback_plans": [plan]})
    assert plans["offload"]["adjustments"] == {"cpu_offload": True}

    effective = plugin_module.resolve_sample_plan(4, 0, 7, plan["adjustments"], plans["offload"])
    assert effective["sample_group_size"] == 4, "cpu_offload must not change how many samples are drawn together"
    assert effective["unapplied"] == {"cpu_offload": True}
    assert effective["sample_seeds"] == [7, 7, 7, 7]
