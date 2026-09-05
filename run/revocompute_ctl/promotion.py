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
    """Atomically activate exact candidates with valid smoke receipts.

    Validate every candidate before replacing any active artifact.  This keeps
    a failed multi-family promotion from leaving a partially updated runtime.
    """
    from revocompute_ctl.live_test import candidate_receipt_valid
    from revocompute_ctl.registry import RegistryError

    candidates: list[tuple[str, str]] = []
    for family in families:
        if not runner_enabled(state, family.name):
            continue
        sif = family.slurm_image
        staged = f"{sif}.next"
        if os.path.isfile(staged):
            if not candidate_receipt_valid(state, family):
                raise RegistryError(f"Staged SIF has no valid exact-hash live-test receipt: {family.name}")
            candidates.append((staged, sif))

    for staged, sif in candidates:
        os.replace(staged, sif)
        if os.path.isfile(f"{staged}.source"):
            os.remove(f"{staged}.source")
        print(f"[SLURM] Promoted staged SIF: {sif}")


def prune_dangling(state) -> None:
    """Remove replaced, now-dangling Docker images and build cache."""
    run_cmd(["docker", "image", "prune", "-f"], env=state.exported(), check=False)
    run_cmd(["docker", "buildx", "prune", "-f"], env=state.exported(), check=False)
