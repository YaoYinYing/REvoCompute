# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Deployment image bookkeeping and SIF promotion."""

from __future__ import annotations

import os

from revocompute_ctl.compose import image_id, run_cmd
from revocompute_ctl.registry import RuntimeFamily, _docker_tag, runner_enabled


def taggable_images(state, families: list[RuntimeFamily]) -> dict[str, str]:
    """Name to locally managed server deployment image."""
    del families
    managed: dict[str, str] = {}
    server_image = state.get("SERVER_IMAGE") or "revodesign-revocompute-server"
    if _docker_tag(server_image) != server_image:
        managed["server"] = server_image
    return managed


def capture_baseline_digests(state, images: dict[str, str]) -> dict[str, dict[str, str]]:
    return {name: {"latest": image_id(state, _docker_tag(image))} for name, image in images.items()}


def changed_image_names(state, images: dict[str, str], baseline: dict[str, dict[str, str]]) -> set[str]:
    return {
        name
        for name, image in images.items()
        if image_id(state, _docker_tag(image)) != (baseline.get(name) or {}).get("latest", "")
    }


def promote_sifs(state, families: list[RuntimeFamily]) -> None:
    """Activate immutable candidates with valid smoke receipts as one transaction.

    Every candidate is prevalidated, then old active files are retained until
    all replacements succeed so a failed multi-family activation can roll back.
    """
    from revocompute_ctl.live_test import candidate_receipt_valid
    from revocompute_ctl.registry import RegistryError

    candidates: list[tuple[str, str, tuple[int, int, int]]] = []
    for family in families:
        if not runner_enabled(state, family.name):
            continue
        sif = family.slurm_image
        staged = f"{sif}.next"
        if os.path.isfile(staged):
            stat = os.stat(staged)
            candidate_identity = (stat.st_size, stat.st_mtime_ns, stat.st_ino)
            if not candidate_receipt_valid(state, family):
                raise RegistryError(f"Staged SIF has no valid live-test receipt: {family.name}")
            backup = f"{sif}.promote-backup"
            if os.path.lexists(backup):
                raise RegistryError(f"Stale SIF promotion backup requires operator recovery: {backup}")
            candidates.append((staged, sif, candidate_identity))

    promoted: list[tuple[str, str, str | None]] = []
    try:
        for staged, sif, before in candidates:
            if os.stat(staged).st_mode & 0o222:
                os.chmod(staged, 0o444)
            after = os.stat(staged)
            if before != (after.st_size, after.st_mtime_ns, after.st_ino):
                raise RegistryError(f"Staged SIF changed after validation: {staged}")
            backup = f"{sif}.promote-backup" if os.path.isfile(sif) else None
            if backup:
                os.replace(sif, backup)
            try:
                os.chmod(staged, 0o444)
                os.replace(staged, sif)
            except Exception:
                if backup and os.path.isfile(backup):
                    os.replace(backup, sif)
                raise
            promoted.append((staged, sif, backup))
    except Exception:
        for staged, sif, backup in reversed(promoted):
            if os.path.isfile(sif):
                os.replace(sif, staged)
            if backup and os.path.isfile(backup):
                os.replace(backup, sif)
        raise

    for staged, sif, backup in promoted:
        if backup:
            os.remove(backup)
        if os.path.isfile(f"{staged}.source"):
            os.remove(f"{staged}.source")
        print(f"[SLURM] Promoted staged SIF: {sif}")


def prune_dangling(state) -> None:
    """Remove replaced, now-dangling Docker images and build cache."""
    run_cmd(["docker", "image", "prune", "-f"], env=state.exported(), check=False)
    run_cmd(["docker", "buildx", "prune", "-f"], env=state.exported(), check=False)
