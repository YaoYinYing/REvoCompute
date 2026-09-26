# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""ESMFold 2 persistent multi-item plugin contract.

No GPU and no network: ``tests/runners/esmfold2/fake_modules`` supplies a
CPU-only ``esm`` package that mirrors the call seams the plugin binds to, and
the plugin is driven through the shared ``persistent_runner`` lifecycle. The
fake counts model loads and records every ``fold`` call verbatim, so the tests
exercise the real seams — and can assert that the requested science reached the
model unchanged under adaptation — rather than a mock of them.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
FAMILY = ROOT / "docker/runners/esmfold2"
COMMON = ROOT / "docker/runners/common"
FAKE_MODULES = Path(__file__).resolve().parent / "fake_modules"

DEFAULT_PARAMS = {
    "model_variant": "fast",
    "num_loops": 2,
    "num_sampling_steps": 4,
    "num_diffusion_samples": 2,
    "seed": 7,
    "lm_dropout": 0.0,
    "lm_mask_pct": 0.0,
    "msa_max_depth": 1024,
    "msa_column_mask_rate": 0.1,
    "kernel_backend": "cuequivariance",
    "include_embeddings": False,
}
PLANS = {
    "one": {"label": "one", "title": "One at a time", "adjustments": {"sample_group_size": 1}},
    "pair": {"label": "pair", "title": "Two at a time", "adjustments": {"sample_group_size": 2, "cache_clear": True}},
    "reference": {
        "label": "reference",
        "title": "Reference kernels",
        "adjustments": {"kernel_backend": "reference", "cache_clear": True},
    },
}


@pytest.fixture(scope="module")
def plugin_module():
    """Import ``predict`` against the shared modules and the fake upstream."""
    for path in (str(COMMON), str(FAMILY), str(FAKE_MODULES)):
        if path not in sys.path:
            sys.path.insert(0, path)
    spec = importlib.util.spec_from_file_location("esmfold2_plugin", FAMILY / "predict.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module


@pytest.fixture()
def assets(tmp_path, monkeypatch, plugin_module):
    """A stub asset root: the real inventory check hashes ~1.5 GB of weights.

    ``validate_assets`` has its own test; the runtime only needs the paths it
    returns and a readable ``assets.json`` for the provenance record, so this
    narrows the inventory walk instead of faking the asset files.
    """
    root = tmp_path / "assets"
    (root / "esmc-6b").mkdir(parents=True)
    (root / "fast").mkdir()
    (root / "ccd.pkl").write_bytes(b"ccd")
    (root / "assets.json").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(
        plugin_module,
        "validate_assets",
        lambda asset_root, variant: (
            Path(asset_root) / variant,
            Path(asset_root) / "esmc-6b",
            Path(asset_root) / "ccd.pkl",
            {},
        ),
    )
    return root


@pytest.fixture()
def state(tmp_path, monkeypatch):
    """Per-test fake-module instrumentation state.

    The stand-in ``torch`` exists only for the duration of one test: a fake
    module left in ``sys.modules`` makes ``importorskip("torch")`` succeed for
    every other runner's tests, which is import pollution rather than a fixture.
    """
    import esm.models.esmfold2 as fake

    saved = {name: sys.modules.get(name) for name in ("torch", "torch.cuda")}
    fake.install_fake_torch()
    root = tmp_path / "fake-state"
    root.mkdir()
    monkeypatch.setenv("ESMFOLD2_FAKE_STATE", str(root))
    monkeypatch.delenv("ESMFOLD2_FAKE_OOM_AT", raising=False)
    monkeypatch.delenv("ESMFOLD2_FAKE_OOM_ALWAYS", raising=False)
    monkeypatch.delenv("ESMFOLD2_FAKE_FAIL_RECORDS", raising=False)
    yield root, fake
    for name, module in saved.items():
        if module is None:
            sys.modules.pop(name, None)
        else:  # pragma: no cover - a real torch is not installed here
            sys.modules[name] = module


def _manifest(tmp_path, records, params=None, *, plan=None):
    fasta = tmp_path / "input.fasta"
    fasta.write_text("".join(f">{name}\n{sequence}\n" for name, sequence in records), encoding="utf-8")
    manifest = {
        "version": 4,
        "task_id": "t1",
        "task_type": "esmfold2_predict",
        "params": {**DEFAULT_PARAMS, **(params or {})},
        "inputs": {"sequence": [{"path": str(fasta), "original_name": "input.fasta", "sha256": "abc"}], "alignment": []},
        "execution": {"batch_size": 1, "max_item_attempts": 3, "max_runtime_restarts": 1},
        "resource_adaptation": {"stage": "recover", "fallback_plans": list(PLANS.values())},
        "resource_guidance": {"plan_order": ["", "one", "pair", "reference"]},
    }
    if plan is not None:
        manifest["resource_adaptation"] = plan
    return manifest


def _run(plugin_module, manifest, output, *, asset_root, **overrides):
    from persistent_runner import execute_task

    items, payload = plugin_module.plan_task(manifest)
    plugin = plugin_module.ESMFold2Plugin(
        payload["params"],
        asset_root=str(asset_root),
        input_name=payload["input_name"],
        input_sha256=payload["input_sha256"],
        msa_path=payload["msa_path"] or "",
        msa_name=payload["msa_name"] or "",
        msa_sha256=payload["msa_sha256"] or "",
        fallback_plans=plugin_module.declared_plans(manifest.get("resource_adaptation")),
    )
    config = plugin_module.build_config(
        manifest, "esmfold2", items, payload, execution_defaults=manifest.get("execution") or {}
    )
    config.update(overrides)
    return execute_task(config, plugin, output_dir=str(output))


# -- work-item normalization ------------------------------------------------


def test_multi_record_fasta_becomes_one_item_per_record_in_input_order(tmp_path, plugin_module):
    manifest = _manifest(
        tmp_path, [("protein_001", "ACDEF"), ("protein_002", "MNPQRST"), ("protein_003", "VWY")]
    )

    items, payload = plugin_module.plan_task(manifest)

    # `plan_task` returns the work items in manifest order; the lifecycle adds the
    # normalized directory name to each one before it runs.
    assert [item["id"] for item in items] == ["protein_001", "protein_002", "protein_003"]
    assert [item["order"] for item in items] == [0, 1, 2]
    assert [item["length"] for item in items] == [5, 7, 3]
    assert {item["sequence_count"] for item in items} == {1}
    assert payload["sequence_count"] == 3
    assert payload["input_sha256"] == "abc"


@pytest.mark.parametrize(
    ("records", "message"),
    [
        # A header repeated verbatim is caught by the FASTA reader.
        ([("a", "ACDE"), ("a", "FGHI")], "duplicate record id"),
        # Two distinct headers that normalize to one output directory would make
        # one record overwrite the other's committed result, so the lifecycle
        # rejects the task before it creates any item path.
        ([("a/b", "ACDE"), ("a_b", "FGHI")], "duplicate work item identifiers"),
        ([("a.", "ACDE"), ("a", "FGHI")], "duplicate work item identifiers"),
    ],
)
def test_duplicate_identifiers_are_rejected_before_any_path_exists(
    tmp_path, plugin_module, state, assets, records, message
):
    manifest = _manifest(tmp_path, records)
    output = tmp_path / "out"

    with pytest.raises(Exception, match=message):
        _run(plugin_module, manifest, output, asset_root=assets)

    assert not list(output.glob("*/prediction.json"))
    assert not (output / ".tmp").exists(), "no item path may exist for a rejected task"


def test_an_empty_record_is_rejected_before_any_path_exists(tmp_path, plugin_module):
    with pytest.raises(ValueError, match="record 'empty' is empty"):
        plugin_module.plan_task(_manifest(tmp_path, [("empty", "")]))
    assert sorted(path.name for path in tmp_path.iterdir()) == ["input.fasta"]


def test_an_unsafe_identifier_is_normalized_into_one_path_component(tmp_path, plugin_module):
    """A path-like header is normalized into one directory, never used as a path."""
    from persistent_runner import safe_item_name

    items, _payload = plugin_module.plan_task(_manifest(tmp_path, [("../../etc/passwd", "ACDE")]))

    assert items[0]["id"] == "../../etc/passwd", "the user's identifier is preserved as metadata"
    name = safe_item_name(items[0]["id"])
    assert "/" not in name and ".." not in name
    assert name == "etc_passwd"


@pytest.mark.parametrize(
    ("records", "message"),
    [
        ([("bad", "ACDZ")], "unsupported residues: Z"),
        ([("long", "A" * 1025)], "supported maximum is 1024"),
    ],
)
def test_a_record_outside_the_folders_envelope_fails_alone(tmp_path, plugin_module, state, assets, records, message):
    """Planning accepts it; the offending work item is the only one that fails."""
    manifest = _manifest(tmp_path, records + [("good", "ACDE")])
    output = tmp_path / "out"

    result = _run(plugin_module, manifest, output, asset_root=assets)

    assert result["outcome"] == "PARTIAL_SUCCESS"
    states = {entry["id"]: entry["status"] for entry in result["items"]}
    assert states[records[0][0]] == "FAILED_INPUT"
    assert states["good"] == "SUCCEEDED"
    failure = next(entry for entry in result["items"] if entry["id"] == records[0][0])
    assert message in failure["error"]
    assert not (output / records[0][0]).exists()


def test_an_alignment_requires_exactly_one_chain_and_the_standard_variant(tmp_path, plugin_module):
    msa = tmp_path / "input.a3m"
    msa.write_text(">query\nACDE\n>homolog\nAC-E\n", encoding="utf-8")

    multi = _manifest(tmp_path, [("a", "ACDE"), ("b", "FGHI")])
    multi["inputs"]["alignment"] = [{"path": str(msa)}]
    with pytest.raises(ValueError, match="exactly one protein chain"):
        plugin_module.plan_task(multi)

    single = _manifest(tmp_path, [("a", "ACDE")])
    single["inputs"]["alignment"] = [{"path": str(msa)}]
    with pytest.raises(ValueError, match="requires model_variant=standard"):
        plugin_module.plan_task(single)


def test_an_alignment_is_carried_into_the_runtime_and_recorded(tmp_path, plugin_module, state, assets):
    """The A3M is a task-level input: it reaches the one chain and is recorded."""
    _root, fake = state
    msa = tmp_path / "input.a3m"
    msa.write_text(">query\nACDE\n>homolog\nAC-E\n", encoding="utf-8")
    manifest = _manifest(tmp_path, [("a", "ACDE")], {"model_variant": "standard"})
    manifest["inputs"]["alignment"] = [{"path": str(msa)}]
    output = tmp_path / "out"

    result = _run(plugin_module, manifest, output, asset_root=assets)

    assert result["outcome"] == "SUCCESS"
    assert [fold["msa"] for fold in fake.fake_folds()] == [str(msa)]
    record = json.loads((output / "a" / "prediction.json").read_text(encoding="utf-8"))
    assert record["input"]["msa"] == "input.a3m"
    assert record["input"]["msa_sha256"]
    assert record["parameters"]["model_variant"] == "standard"


# -- persistent runtime -----------------------------------------------------


def test_the_runtime_initializes_once_for_a_multi_item_task(tmp_path, plugin_module, state, assets):
    _root, fake = state
    manifest = _manifest(tmp_path, [("a", "ACDE"), ("b", "FGHI"), ("c", "KLMN")])
    output = tmp_path / "out"

    result = _run(plugin_module, manifest, output, asset_root=assets)

    assert result["outcome"] == "SUCCESS"
    assert fake.fake_loads() == 1, "the model must load once per task, not once per item"
    assert len(list(output.glob("*/prediction.json"))) == 3
    assert len(fake.fake_folds()) == 3, "one fold call per item on the default path"


def test_each_item_commits_its_own_directory_and_staging_is_never_a_result(tmp_path, plugin_module, state, assets):
    manifest = _manifest(tmp_path, [("a", "ACDE"), ("b", "FGHI")])
    output = tmp_path / "out"

    result = _run(plugin_module, manifest, output, asset_root=assets)

    assert result["outcome"] == "SUCCESS"
    for name in ("a", "b"):
        assert (output / name / "prediction.json").is_file()
        assert (output / name / "sample_001.cif").is_file()
    assert not (output / ".tmp").exists()


def test_a_staged_but_uncommitted_item_is_never_published(tmp_path, plugin_module, state, assets, monkeypatch):
    _root, fake = state
    manifest = _manifest(tmp_path, [("a", "ACDE")])

    def explode(*args, **kwargs):
        raise RuntimeError("killed mid-item")

    monkeypatch.setattr(fake.ESMFold2InputBuilder, "fold", explode)
    output = tmp_path / "out"

    result = _run(plugin_module, manifest, output, asset_root=assets)

    assert result["outcome"] == "FAILED"
    assert not (output / "a").exists(), "a partial item must never be published"
    # Staging may survive a crash, but it is never a result: nothing was renamed
    # into a final directory, and the manifest says so.
    assert not list((output / ".tmp").glob("*")), "staging must not be left holding artifacts"
    assert result["items"][0]["status"] in {"FAILED_RUNTIME", "FAILED_RESOURCE"}
    assert result["items"][0]["attempts"] == len(PLANS), "the fallbacks are walked, not skipped"


def test_resume_does_not_recompute_or_reload_when_every_item_is_committed(tmp_path, plugin_module, state, assets):
    _root, fake = state
    manifest = _manifest(tmp_path, [("a", "ACDE"), ("b", "FGHI")])
    output = tmp_path / "out"
    assert _run(plugin_module, manifest, output, asset_root=assets)["outcome"] == "SUCCESS"

    loads_before = fake.fake_loads()
    folds_before = len(fake.fake_folds())
    resumed = _run(plugin_module, manifest, output, asset_root=assets)

    assert resumed["outcome"] == "SUCCESS"
    assert fake.fake_loads() == loads_before, "a fully committed task must not reload the runtime"
    assert len(fake.fake_folds()) == folds_before, "committed items must not be recomputed"


def test_resume_recomputes_only_the_items_that_did_not_commit(tmp_path, plugin_module, state, assets, monkeypatch):
    """An interrupted worker resumes the unfinished items and nothing else."""
    _root, fake = state
    manifest = _manifest(tmp_path, [("a", "ACDE"), ("b", "FGHI"), ("c", "KLMN")])
    output = tmp_path / "out"

    original = fake.ESMFold2InputBuilder.fold

    def die_on_b(self, model, prediction_input, **kwargs):
        if prediction_input.sequences[0].id == "b":
            raise KeyboardInterrupt("worker killed")  # a BaseException, as a kill is
        return original(self, model, prediction_input, **kwargs)

    monkeypatch.setattr(fake.ESMFold2InputBuilder, "fold", die_on_b)
    with pytest.raises(KeyboardInterrupt):
        _run(plugin_module, manifest, output, asset_root=assets)

    partial = json.loads((output / "work_items.json").read_text(encoding="utf-8"))
    assert [entry["status"] for entry in partial["items"]] == ["SUCCEEDED", "RUNNING", "PENDING"]
    assert (output / "a" / "prediction.json").is_file(), "the committed item survives the kill"

    monkeypatch.setattr(fake.ESMFold2InputBuilder, "fold", original)
    folds_before = len(fake.fake_folds())
    resumed = _run(plugin_module, manifest, output, asset_root=assets)

    assert resumed["outcome"] == "SUCCESS"
    assert [entry["status"] for entry in resumed["items"]] == ["SUCCEEDED"] * 3
    recomputed = [entry["id"] for entry in fake.fake_folds()[folds_before:]]
    assert set(recomputed) == {"b", "c"}, "a committed item must not be recomputed"
    assert "a" not in recomputed


# -- failure semantics ------------------------------------------------------


def test_a_failed_item_leaves_the_rest_successful_and_derives_partial_success(tmp_path, plugin_module, state, assets, monkeypatch):
    _root, _fake = state
    monkeypatch.setenv("ESMFOLD2_FAKE_FAIL_RECORDS", "b")
    manifest = _manifest(tmp_path, [("a", "ACDE"), ("b", "FGHI"), ("c", "KLMN")])
    output = tmp_path / "out"

    result = _run(plugin_module, manifest, output, asset_root=assets)

    assert result["outcome"] == "PARTIAL_SUCCESS"
    assert [entry["status"] for entry in result["items"]] == ["SUCCEEDED", "FAILED_RESOURCE", "SUCCEEDED"]
    assert not (output / "b").exists()
    assert (output / "c" / "prediction.json").is_file()


# -- OOM recovery -----------------------------------------------------------


def test_oom_retries_with_the_declared_fallback_and_preserves_the_requested_science(
    tmp_path, plugin_module, state, assets, monkeypatch
):
    _root, fake = state
    # The requested four samples are one draw upstream; the declared pair plan
    # draws them as 2+2 and still produces all four.
    monkeypatch.setenv("ESMFOLD2_FAKE_OOM_AT", "1")
    manifest = _manifest(tmp_path, [("a", "ACDEFG")], {"num_diffusion_samples": 4, "seed": 11})
    output = tmp_path / "out"
    manifest["resource_guidance"] = {"plan_order": ["", "pair", "one", "reference"]}

    result = _run(plugin_module, manifest, output, asset_root=assets)

    assert result["outcome"] == "SUCCESS"
    entry = result["items"][0]
    assert entry["attempts"] == 2
    assert [event["plan_label"] for event in entry["resource_events"]] == ["", "pair"]
    assert entry["resource_events"][0]["outcome"] == "oom"
    assert entry["resource_events"][0]["error_class"] == "CUDA_OOM"

    record = json.loads((output / "a" / "prediction.json").read_text(encoding="utf-8"))
    assert record["parameters"]["num_diffusion_samples"] == 4, "the requested sample count must not change"
    assert record["parameters"]["seed"] == 11, "the requested seed must not change"
    assert record["parameters"]["num_loops"] == 2
    assert record["parameters"]["num_sampling_steps"] == 4
    assert [path.name for path in sorted((output / "a").glob("sample_*.cif"))] == [
        f"sample_{index:03d}.cif" for index in range(1, 5)
    ]
    assert record["effective"]["sample_groups"] == [2, 2]
    assert record["effective"]["sample_seeds"] == [11, 11, 12, 12]
    assert record["effective"]["plan_label"] == "pair"
    assert record["effective"]["plan_title"] == "Two at a time (2+2 of 4 requested samples per group)"
    assert record["effective"]["cache_clear"] is True
    assert sum(record["effective"]["sample_groups"]) == 4

    folds = fake.fake_folds()
    assert [fold["num_diffusion_samples"] for fold in folds] == [4, 2, 2], "attempt 0 then the split groups"
    assert [fold["seed"] for fold in folds] == [11, 11, 12]
    assert {fold["num_loops"] for fold in folds} == {2}
    assert {fold["num_sampling_steps"] for fold in folds} == {4}
    assert {fold["include_embeddings"] for fold in folds} == {False}


def test_the_reference_kernel_fallback_switches_the_model_backend(tmp_path, plugin_module, state, assets, monkeypatch):
    _root, fake = state
    monkeypatch.setenv("ESMFOLD2_FAKE_OOM_AT", "1")
    manifest = _manifest(tmp_path, [("a", "ACDEFG")], {"num_diffusion_samples": 1})
    manifest["resource_guidance"] = {"plan_order": ["", "reference"]}
    output = tmp_path / "out"

    result = _run(plugin_module, manifest, output, asset_root=assets)

    assert result["outcome"] == "SUCCESS"
    assert [fold["model_backend"] for fold in fake.fake_folds()] == ["cuequivariance", "reference"], (
        "the fallback must reach the model"
    )
    record = json.loads((output / "a" / "prediction.json").read_text(encoding="utf-8"))
    assert record["effective"]["kernel_backend"] == "reference"
    assert record["parameters"]["kernel_backend"] == "cuequivariance", "the user's choice is unchanged"


def test_an_item_that_ooms_under_every_plan_fails_within_a_finite_budget(tmp_path, plugin_module, state, assets, monkeypatch):
    _root, _fake = state
    monkeypatch.setenv("ESMFOLD2_FAKE_OOM_ALWAYS", "1")
    manifest = _manifest(tmp_path, [("a", "ACDE"), ("b", "FGHI")])
    output = tmp_path / "out"

    result = _run(plugin_module, manifest, output, asset_root=assets)

    assert result["outcome"] == "FAILED"
    assert {entry["status"] for entry in result["items"]} == {"FAILED_RESOURCE"}
    assert all(entry["attempts"] == 3 for entry in result["items"]), "the retry budget must be finite"
    assert not (output / "a").exists() and not (output / "b").exists()


def test_an_unrecoverable_cuda_fault_propagates_and_restarts_the_runtime(tmp_path, plugin_module, state, assets, monkeypatch):
    _root, fake = state
    manifest = _manifest(tmp_path, [("a", "ACDE"), ("b", "FGHI")])

    def explode(self, *args, **kwargs):
        raise RuntimeError("CUDA error: an illegal memory access was encountered")

    monkeypatch.setattr(fake.ESMFold2InputBuilder, "fold", explode)
    output = tmp_path / "out"

    result = _run(plugin_module, manifest, output, asset_root=assets)

    assert result["outcome"] == "FAILED"
    assert {entry["status"] for entry in result["items"]} == {"FAILED_RUNTIME"}
    assert "illegal memory access" in (result["items"][0]["error"] or "")


# -- measurement ------------------------------------------------------------


def test_the_runner_reports_the_device_and_the_model_baseline(tmp_path, plugin_module, state, assets):
    """The server's estimator gets its two inputs from here, not from a guess.

    The baseline is the model's residency right after it reached the device, and
    the device profile names the class the job actually got — never a physical
    GPU id, so equivalent devices share observations.
    """
    manifest = _manifest(tmp_path, [("a", "ACDE")])
    _items, payload = plugin_module.plan_task(manifest)
    plugin = plugin_module.ESMFold2Plugin(
        payload["params"], asset_root=str(assets), input_name="input.fasta", input_sha256="abc"
    )
    execution = dict(manifest["execution"])

    runtime = plugin.initialize_runtime(execution)
    baseline, allocated, reserved = plugin.runtime_usage(runtime)
    profile = plugin.device_profile(runtime)
    free = plugin.available_vram_mb(runtime)

    assert baseline == 2560, "the baseline is measured right after the model is on the device"
    assert allocated == 2048 and reserved == 2560
    assert profile == {
        "vendor": "nvidia",
        "model": "NVIDIA A100-PCIE-40GB",
        "compute_capability": "8.0",
        "total_vram_mb": 40960,
        "mig_profile": "",
    }
    assert free == 30000
    plugin.finalize(runtime)
    assert runtime == {}


def test_the_runtime_fingerprint_changes_with_the_environment_not_a_constant(plugin_module):
    fast = plugin_module.ESMFold2Plugin({"kernel_backend": "cuequivariance", "model_variant": "fast"}, asset_root="/x")
    reference = plugin_module.ESMFold2Plugin({"kernel_backend": "reference", "model_variant": "fast"}, asset_root="/x")
    standard = plugin_module.ESMFold2Plugin({"kernel_backend": "cuequivariance", "model_variant": "standard"}, asset_root="/x")

    assert "torch=" in fast.runtime_fingerprint and "cuda=" in fast.runtime_fingerprint
    assert fast.runtime_fingerprint != reference.runtime_fingerprint
    assert fast.runtime_fingerprint != standard.runtime_fingerprint
    assert fast.runtime_fingerprint == fast.runtime_fingerprint, "the fingerprint must be stable"


# -- declared adaptation plans ----------------------------------------------


def test_a_plan_naming_a_scientific_parameter_or_an_unrealized_key_is_rejected_at_load(plugin_module):
    with pytest.raises(ValueError, match="non-resource parameter"):
        plugin_module.declared_plans(
            {"fallback_plans": [{"label": "cheat", "title": "Fewer samples", "adjustments": {"num_samples": 1}}]}
        )
    with pytest.raises(ValueError, match="non-resource parameter"):
        plugin_module.declared_plans(
            {"fallback_plans": [{"label": "seed", "title": "Different seed", "adjustments": {"seed": 1}}]}
        )
    with pytest.raises(ValueError, match="non-resource parameter"):
        plugin_module.declared_plans(
            {"fallback_plans": [{"label": "model", "title": "Other model", "adjustments": {"model_variant": "standard"}}]}
        )
    # A recognized resource key this runner does not implement is a declaration
    # the implementation cannot honour, so it fails rather than becoming a no-op.
    with pytest.raises(ValueError, match="does not implement"):
        plugin_module.declared_plans(
            {"fallback_plans": [{"label": "offload", "title": "Offload", "adjustments": {"cpu_offload": True}}]}
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
    assert set(plugin_module.declared_plans({"fallback_plans": list(PLANS.values())})) == {"one", "pair", "reference"}


def test_the_sample_plan_splits_the_requested_samples_without_changing_count_or_seed(plugin_module):
    default = plugin_module.resolve_sample_plan(5, 42, None)
    assert default["sample_groups"] == [5]
    assert default["group_seeds"] == [42]
    assert default["sample_seeds"] == [42] * 5
    assert default["seed"] == 42 and default["num_samples"] == 5
    assert default["kernel_backend"] is None and default["cache_clear"] is False

    split = plugin_module.resolve_sample_plan(5, 42, PLANS["pair"]["adjustments"])
    assert split["sample_groups"] == [2, 2, 1]
    assert split["group_seeds"] == [42, 43, 44]
    assert split["sample_seeds"] == [42, 42, 43, 43, 44]
    assert sum(split["sample_groups"]) == 5, "the requested sample count is preserved"
    assert split["num_samples"] == 5 and split["seed"] == 42
    assert split["cache_clear"] is True

    # A plan naming only the backend leaves the default grouping alone.
    backend = plugin_module.resolve_sample_plan(4, 7, PLANS["reference"]["adjustments"])
    assert backend["sample_groups"] == [4]
    assert backend["kernel_backend"] == "reference"
    assert plugin_module.resolve_sample_plan(3, 1, {"sample_group_size": 1})["sample_groups"] == [1, 1, 1]


def test_no_adjustment_key_names_a_scientific_parameter(plugin_module):
    """What the planner may change and what the user asked for are disjoint.

    ``kernel_backend`` is the one exception by construction: it is both a user
    parameter and a resource key, so a fallback may only select a value the task
    schema itself allows — it can never become a channel for a different model.
    """
    scientific = {
        "model_variant",
        "num_loops",
        "num_sampling_steps",
        "num_diffusion_samples",
        "seed",
        "lm_dropout",
        "lm_mask_pct",
        "kernel_backend",
        "include_embeddings",
    }
    assert plugin_module.SUPPORTED_ADJUSTMENTS <= plugin_module.RESOURCE_ADJUSTMENT_KEYS
    assert plugin_module.SUPPORTED_ADJUSTMENTS == {"sample_group_size", "kernel_backend", "cache_clear"}
    # Every supported key except `kernel_backend` is absent from the scientific
    # parameter surface, and `kernel_backend`'s own values are constrained to the
    # ones the task schema allows — so an adaptation can never change the model,
    # the sample count, a sampling parameter, or the seed.
    assert (plugin_module.SUPPORTED_ADJUSTMENTS & scientific) == {"kernel_backend"}
    assert set(plugin_module.KERNEL_BACKENDS) == {"reference", "cuequivariance"}

    # A plan naming the model, the sample count, a sampling parameter, or the
    # seed is rejected at load — the whole scientific parameter surface a task
    # could carry is covered by the same guard. `kernel_backend` is not: it is a
    # resource key, and its values are checked against the schema's own enum.
    for key in sorted(scientific - {"kernel_backend"}):
        with pytest.raises(ValueError, match="non-resource parameter"):
            plugin_module.declared_plans(
                {"fallback_plans": [{"label": "cheat", "title": "x", "adjustments": {key: 1}}]}
            )
    with pytest.raises(ValueError, match="unknown kernel backend"):
        plugin_module.declared_plans(
            {"fallback_plans": [{"label": "cheat", "title": "x", "adjustments": {"kernel_backend": "fast"}}]}
        )
