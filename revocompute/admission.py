# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Read-only production admission evidence published by deployment control."""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterable
from enum import Enum
from pathlib import Path
from typing import Any


class RunnerReadinessStatus(str, Enum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    NOT_BUILT = "NOT_BUILT"
    BUILD_STALE = "BUILD_STALE"
    NOT_VALIDATED = "NOT_VALIDATED"
    VALIDATION_STALE = "VALIDATION_STALE"
    READY = "READY"


class AdmissionEvidence:
    __slots__ = ("runner_family", "status", "reason_code", "message", "next_action", "ready", "raw")

    def __init__(self, payload: dict[str, Any]):
        self.raw = payload
        self.runner_family = str(payload.get("runner_family") or "")
        status = payload.get("status") or RunnerReadinessStatus.NOT_CONFIGURED.value
        try:
            self.status = RunnerReadinessStatus(status)
        except (TypeError, ValueError):
            self.status = RunnerReadinessStatus.NOT_CONFIGURED
        self.reason_code = str(payload.get("reason_code") or "RUNNER_UNAVAILABLE")
        self.message = str(payload.get("message") or "Runner readiness evidence is unavailable")
        self.next_action = str(payload.get("next_action") or "doctor")
        self.ready = self.status is RunnerReadinessStatus.READY and payload.get("ready") is True


def resolve_submission_readiness(server_dir: str | Path, runner_name: str) -> AdmissionEvidence:
    """Read the deployment attestation; missing or malformed evidence fails closed."""
    path = Path(server_dir) / "readiness" / f"{runner_name}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("runner_family") != runner_name:
            raise ValueError("invalid runner readiness attestation")
        return AdmissionEvidence(payload)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return AdmissionEvidence({"runner_family": runner_name})


def invalidate_submission_attestations(
    server_dir: str | Path, runner_names: Iterable[str] | None = None
) -> None:
    """Remove all or selected deployment evidence when mutable resource policy changes.

    The readiness directory is owned by the configured service identity. This
    operation therefore runs in the web process under that identity; the
    deployment controller publishes and clears it through the same identity.
    """
    server_root = Path(server_dir)
    if runner_names is not None:
        filenames = []
        for runner_name in set(runner_names):
            if Path(runner_name).name != runner_name:
                raise ValueError(f"invalid runner name: {runner_name!r}")
            filenames.append(f"{runner_name}.json")
        for directory in (server_root / "readiness", server_root / ".readiness-publish"):
            for filename in filenames:
                try:
                    (directory / filename).unlink()
                except FileNotFoundError:
                    continue
        return
    for path in (server_root / "readiness", server_root / ".readiness-publish"):
        try:
            if path.is_symlink() or path.is_file():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
        except FileNotFoundError:
            continue
