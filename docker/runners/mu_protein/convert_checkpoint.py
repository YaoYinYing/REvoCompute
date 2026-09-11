#!/usr/bin/env python3
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import _codecs
import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable

import numpy as np
import torch
from safetensors.torch import save_file

HERE = Path(__file__).resolve().parent
REGISTRY = HERE / "asset-registry.json"
RAW_ROOT = Path("/input")
SANITIZED_ROOT = Path("/output")


def fail(message: str) -> None:
    raise SystemExit(message)


def digest(path: Path, algorithm: str) -> str:
    value = hashlib.md5(usedforsecurity=False) if algorithm == "md5" else hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return {key: json_safe(item) for key, item in value.items()}
    fail(f"Checkpoint metadata contains unsupported type: {type(value).__name__}")


def load_weights_only(path: Path, role: str = "encoder") -> dict:
    torch.serialization.clear_safe_globals()
    safe_globals: list[Any]
    if role == "encoder":
        safe_globals = [argparse.Namespace]
    elif role == "muformer":
        # The official target checkpoint stores NumPy scalar training metrics. These
        # are the only non-PyTorch globals in its statically inspected pickle stream.
        safe_globals = [np.core.multiarray.scalar, np.dtype, type(np.dtype(np.float64)), _codecs.encode]
    else:
        fail(f"Unsupported checkpoint role: {role}")
    torch.serialization.add_safe_globals(safe_globals)
    try:
        value = torch.load(path, map_location="cpu", weights_only=True, mmap=True)
    finally:
        torch.serialization.clear_safe_globals()
    if not isinstance(value, dict):
        fail("Checkpoint root must be a dictionary")
    return value


def extract(record: dict, checkpoint: dict) -> tuple[dict[str, torch.Tensor], dict]:
    state_key = "model" if record["role"] == "encoder" else "model_state_dict"
    state = checkpoint.get(state_key)
    if not isinstance(state, dict) or not state:
        fail(f"Checkpoint has no nonempty {state_key} tensor state")
    if not all(isinstance(key, str) and isinstance(value, torch.Tensor) for key, value in state.items()):
        fail(f"Checkpoint {state_key} must contain only string-to-tensor entries")
    metadata = {}
    if record["role"] == "encoder":
        namespace = checkpoint.get("args")
        if not isinstance(namespace, argparse.Namespace):
            fail("Encoder checkpoint has no argparse.Namespace architecture metadata")
        metadata["model_args"] = json_safe(vars(namespace))
    converted = {}
    storage_ids = set()
    for key, value in state.items():
        tensor = value.detach().cpu().contiguous()
        storage_id = (tensor.untyped_storage().data_ptr(), tensor.untyped_storage().nbytes())
        if storage_id in storage_ids:
            tensor = tensor.clone()
            storage_id = (tensor.untyped_storage().data_ptr(), tensor.untyped_storage().nbytes())
        storage_ids.add(storage_id)
        converted[key] = tensor
    return converted, metadata


def convert(
    record: dict,
    raw_root: Path,
    sanitized_root: Path,
    saver: Callable[[dict[str, torch.Tensor], str], None] = save_file,
) -> dict:
    source = raw_root / record["filename"]
    if not source.is_file() or source.stat().st_size != record["size"]:
        fail(f"Raw checkpoint is missing or has the wrong published size: {source}")
    if digest(source, "md5") != record["md5"]:
        fail(f"Raw checkpoint does not match the published MD5: {source}")
    raw_sha256 = digest(source, "sha256")
    if record.get("observed_sha256") and raw_sha256 != record["observed_sha256"]:
        fail(f"Raw checkpoint does not match the observed SHA-256: {source}")
    receipt_path = raw_root / f"{record['id']}.receipt.json"
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"Missing or invalid fetch receipt for {record['id']}: {exc}")
    if receipt.get("local_sha256") != raw_sha256:
        fail(f"Local SHA-256 does not match the fetch receipt for {record['id']}")

    checkpoint = load_weights_only(source, record["role"])
    state, metadata = extract(record, checkpoint)
    sanitized_root.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{record['id']}.", dir=sanitized_root)
    os.close(descriptor)
    temporary = Path(temporary_name)
    destination = sanitized_root / record["sanitized_filename"]
    try:
        saver(state, str(temporary))
        if not temporary.is_file() or temporary.stat().st_size == 0:
            fail("Safetensors conversion produced an empty file")
        temporary.chmod(0o440)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    manifest = {
        "schema_version": 1,
        "asset_id": record["id"],
        "source": {
            "filename": record["filename"],
            "size": record["size"],
            "md5": record["md5"],
            "sha256": raw_sha256,
        },
        "sanitized": {
            "filename": destination.name,
            "size": destination.stat().st_size,
            "sha256": digest(destination, "sha256"),
            "format": "safetensors",
        },
        "allowlisted_globals": (
            ["argparse.Namespace"]
            if record["role"] == "encoder"
            else [
                "numpy.core.multiarray.scalar",
                "numpy.dtype",
                "numpy.dtypes.Float64DType",
                "_codecs.encode",
            ]
        ),
        "tensor_count": len(state),
        **metadata,
    }
    manifest_path = sanitized_root / f"{record['id']}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest_path.chmod(0o440)
    return manifest


def main() -> None:
    if os.geteuid() == 0:
        fail("Mu-Protein checkpoint conversion must run as an unprivileged user")
    parser = argparse.ArgumentParser(description="Convert one allowlisted Mu-Protein checkpoint to safetensors")
    parser.add_argument("asset_id", choices=("muformer_encoder", "musearch_tem1_muformer"))
    args = parser.parse_args()
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    record = next(item for item in registry["assets"] if item["id"] == args.asset_id)
    convert(record, RAW_ROOT, SANITIZED_ROOT)


if __name__ == "__main__":
    main()
