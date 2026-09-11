# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import pickle
import re
import sys
import types
from pathlib import Path

import numpy as np
import pytest
import torch
import yaml

ROOT = Path(__file__).resolve().parents[1]
FAMILY = ROOT / "docker/runners/mu_protein"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_converter():
    package = types.ModuleType("safetensors")
    torch_module = types.ModuleType("safetensors.torch")
    torch_module.save_file = lambda *_: None
    package.torch = torch_module
    previous_package = sys.modules.get("safetensors")
    previous_torch = sys.modules.get("safetensors.torch")
    sys.modules["safetensors"] = package
    sys.modules["safetensors.torch"] = torch_module
    try:
        return _load_module("mu_protein_convert", FAMILY / "convert_checkpoint.py")
    finally:
        if previous_package is None:
            sys.modules.pop("safetensors", None)
        else:
            sys.modules["safetensors"] = previous_package
        if previous_torch is None:
            sys.modules.pop("safetensors.torch", None)
        else:
            sys.modules["safetensors.torch"] = previous_torch


def test_registry_is_exactly_two_immutable_official_figshare_assets() -> None:
    registry = json.loads((FAMILY / "asset-registry.json").read_text(encoding="utf-8"))
    assert registry["upstream_commit"] == "c228769f635e066d592838018b14463720956455"
    assert {item["id"] for item in registry["assets"]} == {"muformer_encoder", "musearch_tem1_muformer"}
    assert {item["figshare_file_id"] for item in registry["assets"]} == {48930421, 58327423}
    assert all(
        item["download_url"] == f"https://ndownloader.figshare.com/files/{item['figshare_file_id']}"
        for item in registry["assets"]
    )
    assert all(item["size"] > 8_000_000_000 and len(item["md5"]) == 32 for item in registry["assets"])
    encoder = next(item for item in registry["assets"] if item["id"] == "muformer_encoder")
    target = next(item for item in registry["assets"] if item["id"] == "musearch_tem1_muformer")
    assert encoder["observed_sha256"] == "6778beb3d4e278dc278666151aa6eb02f800f300573766d853ec0676cc11ce35"
    assert target["observed_sha256"] == "1f8e55dd1aa57df4b427b74137f1f474064a7b548d1f35fb1686cebf9a8e1d8d"


def test_existing_encoder_matches_published_figshare_identity() -> None:
    encoder = Path("/mnt/db/weights/revocompute/mu_protein/uFormer-L-encoder.pt")
    if not encoder.is_file():
        pytest.skip("operator has not provisioned the official encoder")
    assert encoder.stat().st_size == 8_170_009_235
    value = hashlib.md5(usedforsecurity=False)
    with encoder.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            value.update(chunk)
    assert value.hexdigest() == "2f7da1ebbd6ad659f6194dfa2d77dc1b"


def test_existing_target_loads_weights_only_with_exact_minimal_globals() -> None:
    target = Path("/mnt/db/weights/revocompute/mu_protein/muformer-l-BLAT_ECOLX_Ranganathan2015_CFX.pt")
    if not target.is_file():
        pytest.skip("operator has not provisioned the official target checkpoint")
    converter = _load_converter()
    loaded = converter.load_weights_only(target, role="muformer")
    state, metadata = converter.extract({"role": "muformer"}, loaded)
    assert len(state) == 581
    assert sum(value.numel() for value in state.values()) == 681_734_416
    assert metadata == {}
    assert torch.serialization.get_safe_globals() == []


def test_weights_only_load_succeeds_with_namespace_as_only_allowlisted_global(tmp_path: Path) -> None:
    converter = _load_converter()
    checkpoint = tmp_path / "encoder.pt"
    torch.save(
        {
            "args": argparse.Namespace(encoder_embed_dim=8, encoder_layers=1),
            "model": {"encoder.weight": torch.arange(8, dtype=torch.float32)},
            "optimizer_history": [],
        },
        checkpoint,
    )
    loaded = converter.load_weights_only(checkpoint)
    state, metadata = converter.extract({"role": "encoder"}, loaded)
    assert list(state) == ["encoder.weight"]
    assert metadata["model_args"] == {"encoder_embed_dim": 8, "encoder_layers": 1}
    assert torch.serialization.get_safe_globals() == []


def test_weights_only_load_succeeds_for_official_muformer_numpy_metadata(tmp_path: Path) -> None:
    converter = _load_converter()
    checkpoint = tmp_path / "muformer.pt"
    torch.save(
        {
            "model_state_dict": {"weight": torch.arange(8, dtype=torch.float32)},
            "optimizer_state_dict": {"state": {}, "param_groups": []},
            "log_info": {"best_corr": np.float64(0.5)},
        },
        checkpoint,
    )

    with pytest.raises(pickle.UnpicklingError, match="numpy.core.multiarray.scalar"):
        converter.load_weights_only(checkpoint)
    loaded = converter.load_weights_only(checkpoint, role="muformer")
    state, metadata = converter.extract({"role": "muformer"}, loaded)
    assert list(state) == ["weight"]
    assert metadata == {}
    assert torch.serialization.get_safe_globals() == []


def test_extract_breaks_tied_storage_for_real_safetensors(tmp_path: Path) -> None:
    safetensors_torch = pytest.importorskip("safetensors.torch")
    converter = _load_converter()
    shared = torch.arange(8, dtype=torch.float32)
    state, _ = converter.extract(
        {"role": "muformer"},
        {"model_state_dict": {"first": shared, "second": shared}},
    )
    assert state["first"].untyped_storage().data_ptr() != state["second"].untyped_storage().data_ptr()

    output = tmp_path / "tied.safetensors"
    safetensors_torch.save_file(state, output)
    loaded = safetensors_torch.load_file(output)
    assert torch.equal(loaded["first"], shared)
    assert torch.equal(loaded["second"], shared)


def test_conversion_requires_published_md5_and_fetch_receipt_sha256(tmp_path: Path) -> None:
    converter = _load_converter()
    raw = tmp_path / "raw"
    sanitized = tmp_path / "sanitized"
    raw.mkdir()
    checkpoint = raw / "encoder.pt"
    torch.save({"args": argparse.Namespace(dim=2), "model": {"weight": torch.ones(2)}}, checkpoint)
    content = checkpoint.read_bytes()
    record = {
        "id": "muformer_encoder",
        "role": "encoder",
        "filename": checkpoint.name,
        "size": len(content),
        "md5": hashlib.md5(content, usedforsecurity=False).hexdigest(),
        "sanitized_filename": "encoder.safetensors",
    }
    receipt = {"local_sha256": hashlib.sha256(content).hexdigest()}
    (raw / "muformer_encoder.receipt.json").write_text(json.dumps(receipt), encoding="utf-8")

    seen = {}

    def fake_save(state, destination):
        seen.update(state)
        Path(destination).write_bytes(b"safe-tensor-state")

    manifest = converter.convert(record, raw, sanitized, saver=fake_save)
    assert list(seen) == ["weight"]
    assert manifest["allowlisted_globals"] == ["argparse.Namespace"]
    assert manifest["tensor_count"] == 1
    assert manifest["source"]["sha256"] == receipt["local_sha256"]
    assert manifest["sanitized"]["format"] == "safetensors"

    receipt["local_sha256"] = "0" * 64
    (raw / "muformer_encoder.receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(SystemExit, match="Local SHA-256"):
        converter.convert(record, raw, sanitized, saver=fake_save)


def test_converter_rejects_non_tensor_state(tmp_path: Path) -> None:
    converter = _load_converter()
    with pytest.raises(SystemExit, match="only string-to-tensor"):
        converter.extract(
            {"role": "muformer"},
            {"model_state_dict": {"weight": torch.ones(1), "unsafe": "not a tensor"}},
        )


def test_operator_wrapper_enforces_offline_unprivileged_conversion_boundary() -> None:
    wrapper = (FAMILY / "prepare_assets.sh").read_text(encoding="utf-8")
    definition = (FAMILY / "conversion.def").read_text(encoding="utf-8")
    converter = (FAMILY / "convert_checkpoint.py").read_text(encoding="utf-8")
    fetcher = (FAMILY / "fetch_asset.py").read_text(encoding="utf-8")
    assert "--containall --cleanenv --no-home --net --network none --security no-new-privs" in wrapper
    assert ":/input:ro" in wrapper and ":/output:rw" in wrapper
    assert "weights_only=True" in converter and "mmap=True" in converter
    assert "weights_only=False" not in converter
    assert "os.geteuid() == 0" in converter
    assert "url" not in fetcher.split("parser.add_argument", 1)[1].split("args =", 1)[0]
    assert "https://download.pytorch.org/whl/cpu" in definition
    assert "https://pypi.org/simple" in definition
    assert "uv pip sync" in definition and "--require-hashes" in definition
    assert "requirements.lock" in definition
    assert "mirror" not in definition.lower()
    assert "%test" in definition


def test_converter_dependency_lock_is_complete_and_hashed() -> None:
    lock = (FAMILY / "requirements.lock").read_text(encoding="utf-8")
    entries = re.split(r"(?=^[a-z0-9][a-z0-9_.-]*==)", lock, flags=re.MULTILINE)[1:]
    names = {entry.split("==", 1)[0] for entry in entries}
    assert names == {
        "filelock",
        "fsspec",
        "jinja2",
        "markupsafe",
        "mpmath",
        "networkx",
        "numpy",
        "safetensors",
        "sympy",
        "torch",
        "typing-extensions",
    }
    assert all("--hash=sha256:" in entry for entry in entries)
    assert "--python-version 3.11 --python-platform x86_64-manylinux_2_28" in lock


def test_family_is_deliberately_not_registered_until_scientific_validation() -> None:
    assert not (FAMILY / "plugin.yaml").exists()
    assert not (FAMILY / "runner.yaml").exists()
    assert not (FAMILY / "tasks").exists()
    provenance = json.loads((FAMILY / "upstream.json").read_text(encoding="utf-8"))
    assert provenance["runtime_promotion"] == "blocked"
    assert len(provenance["blockers"]) == 2
    evidence = json.loads((FAMILY / "scientific-evidence.json").read_text(encoding="utf-8"))
    assert evidence["upstream_commit"] == provenance["upstream_commit"]
    assert evidence["normalization_dataset"]["git_blob_sha1"] == "38469996154348bdf28e7ddb592d0f2e19576d0e"
    assert (
        evidence["normalization_dataset"]["sha256"]
        == "a8bf4da55487f39dcf41281dddb173942b8e7865255bd8b17fbf57337e55f9d7"
    )
    assert evidence["normalization_dataset"]["sequence_count"] == 104
    assert evidence["reproduction_examples"][0]["published_score_status"] == "ambiguous_range_comment"
    for example in evidence["reproduction_examples"]:
        sequence = example["sequence"]
        assert len(sequence) == example["sequence_length"]
        assert hashlib.sha256(sequence.encode("ascii")).hexdigest() == example["sequence_sha256"]
    policy = yaml.safe_load((FAMILY / "policies/noncommercial.yaml").read_text(encoding="utf-8"))
    assert policy["id"] == "mu_protein_noncommercial"
    assert policy["requestable"] is True
