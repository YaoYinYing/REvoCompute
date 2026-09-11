#!/usr/bin/env python3
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

SHA256_RE = re.compile(r"[0-9a-f]{64}")


def fail(message: str) -> None:
    raise SystemExit(message)


def load_json(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"Invalid {label}: {exc}")
    if not isinstance(value, dict):
        fail(f"Invalid {label}: expected an object")
    return value


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset-id", required=True, choices=("rfd3", "rfd3na", "rf3"))
    parser.add_argument("--asset-root", required=True, type=Path)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--operator-manifest", required=True, type=Path)
    args = parser.parse_args()

    registry = {item["id"]: item for item in load_json(args.registry, "checkpoint registry").get("assets", [])}
    records = {
        item.get("id"): item
        for item in load_json(args.operator_manifest, "operator asset manifest").get("assets", [])
        if isinstance(item, dict)
    }
    expected = registry[args.asset_id]
    record = records.get(args.asset_id)
    if record is None:
        fail(f"Operator asset manifest has no verified record for {args.asset_id}")
    if record.get("filename") != expected["filename"]:
        fail(f"Unexpected filename for {args.asset_id} in operator asset manifest")
    checksum = record.get("sha256")
    size = record.get("size")
    if not isinstance(checksum, str) or not SHA256_RE.fullmatch(checksum):
        fail(f"Operator asset manifest has no valid SHA-256 for {args.asset_id}")
    if not isinstance(size, int) or size <= 0:
        fail(f"Operator asset manifest has no valid size for {args.asset_id}")
    checkpoint = args.asset_root / expected["filename"]
    if not checkpoint.is_file() or checkpoint.stat().st_size != size:
        fail(f"Foundry checkpoint is missing or has the wrong size: {checkpoint}")
    if digest(checkpoint) != checksum:
        fail(f"Foundry checkpoint SHA-256 mismatch: {checkpoint}")
    print(checkpoint)


if __name__ == "__main__":
    main()
