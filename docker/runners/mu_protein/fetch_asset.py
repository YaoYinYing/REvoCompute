#!/usr/bin/env python3
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REGISTRY = HERE / "asset-registry.json"
DEFAULT_RAW_ROOT = Path("/mnt/db/weights/revocompute/mu_protein")


def fail(message: str) -> None:
    raise SystemExit(message)


def load_asset(asset_id: str, registry_path: Path = REGISTRY) -> dict:
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    assets = {item["id"]: item for item in registry["assets"]}
    if asset_id not in assets:
        fail(f"Unknown Mu-Protein asset ID: {asset_id}")
    record = assets[asset_id]
    expected_url = f"https://ndownloader.figshare.com/files/{record['figshare_file_id']}"
    if record["download_url"] != expected_url:
        fail("Asset registry contains a noncanonical Figshare URL")
    return record


def hash_file(path: Path) -> tuple[int, str, str]:
    md5 = hashlib.md5(usedforsecurity=False)
    sha256 = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            size += len(chunk)
            md5.update(chunk)
            sha256.update(chunk)
    return size, md5.hexdigest(), sha256.hexdigest()


def verify(path: Path, record: dict) -> str:
    size, md5, sha256 = hash_file(path)
    if size != record["size"]:
        fail(f"Published size mismatch for {record['id']}: expected {record['size']}, got {size}")
    if md5 != record["md5"]:
        fail(f"Published MD5 mismatch for {record['id']}: expected {record['md5']}, got {md5}")
    if record.get("observed_sha256") and sha256 != record["observed_sha256"]:
        fail(f"Observed SHA-256 mismatch for {record['id']}")
    return sha256


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch one allowlisted Mu-Protein asset from official Figshare")
    parser.add_argument("asset_id", choices=("muformer_encoder", "musearch_tem1_muformer"))
    args = parser.parse_args()
    record = load_asset(args.asset_id)
    raw_root = Path(os.environ.get("MU_PROTEIN_RAW_ROOT", DEFAULT_RAW_ROOT)).resolve()
    raw_root.mkdir(parents=True, exist_ok=True)
    destination = raw_root / record["filename"]
    if destination.exists():
        sha256 = verify(destination, record)
    else:
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{record['id']}.", dir=raw_root)
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            with urllib.request.urlopen(record["download_url"]) as response, temporary.open("wb") as output:
                while chunk := response.read(8 * 1024 * 1024):
                    output.write(chunk)
            sha256 = verify(temporary, record)
            temporary.chmod(0o440)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
    receipt = {
        "asset_id": record["id"],
        "filename": record["filename"],
        "figshare_article": record["figshare_article"],
        "figshare_version": record["figshare_version"],
        "figshare_file_id": record["figshare_file_id"],
        "size": record["size"],
        "published_md5": record["md5"],
        "local_sha256": sha256,
    }
    receipt_path = raw_root / f"{record['id']}.receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    receipt_path.chmod(0o440)
    print(destination)


if __name__ == "__main__":
    main()
