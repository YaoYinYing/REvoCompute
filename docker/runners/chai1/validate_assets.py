# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REQUIRED_ASSETS = {
    "models_v2/feature_embedding.pt",
    "models_v2/bond_loss_input_proj.pt",
    "models_v2/token_embedder.pt",
    "models_v2/trunk.pt",
    "models_v2/diffusion_module.pt",
    "models_v2/confidence_head.pt",
    "esm/traced_sdpa_esm2_t36_3B_UR50D_fp16.pt",
    "conformers_v1.apkl",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate(root: Path, manifest: Path) -> None:
    try:
        document = json.loads(manifest.read_text(encoding="utf-8"))
        records = document["assets"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError(f"invalid asset manifest {manifest}: {exc}") from exc
    if not isinstance(records, list):
        raise ValueError("asset manifest 'assets' must be a list")

    by_path = {record.get("path"): record for record in records if isinstance(record, dict)}
    missing = REQUIRED_ASSETS - by_path.keys()
    extra = by_path.keys() - REQUIRED_ASSETS
    if missing:
        raise ValueError(f"asset manifest is missing: {', '.join(sorted(missing))}")
    if extra:
        raise ValueError(f"asset manifest contains unexpected paths: {', '.join(sorted(extra))}")

    resolved_root = root.resolve()
    for relative in sorted(REQUIRED_ASSETS):
        record = by_path[relative]
        asset = (resolved_root / relative).resolve()
        if resolved_root not in asset.parents:
            raise ValueError(f"asset path escapes root: {relative}")
        if not asset.is_file():
            raise ValueError(f"missing Chai-1 asset: {asset}")
        expected_size = record.get("size")
        if not isinstance(expected_size, int) or expected_size <= 0:
            raise ValueError(f"invalid expected size for {relative}")
        if asset.stat().st_size != expected_size:
            raise ValueError(f"size mismatch for {relative}: expected {expected_size}, got {asset.stat().st_size}")
        expected_hash = record.get("sha256")
        if not isinstance(expected_hash, str) or len(expected_hash) != 64:
            raise ValueError(f"SHA-256 is not provisioned for {relative}")
        actual_hash = _sha256(asset)
        if actual_hash != expected_hash.lower():
            raise ValueError(f"SHA-256 mismatch for {relative}: expected {expected_hash}, got {actual_hash}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the immutable Chai-1 asset set")
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()
    try:
        validate(args.root, args.manifest)
    except ValueError as exc:
        print(f"Chai-1 asset verification failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
