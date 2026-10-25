# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The Fleet's Active image is an identity, never an existence bit.

A SIF file can be present while the server cannot establish which artifact it
is (a failed doctor check, a build whose provenance no longer matches).  The
Fleet must report that as Unknown rather than deriving an active image from
``sif_exists``.  The projection is exercised over a representative large fleet
so one evidence variant cannot hide behind another row.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from revocompute.admission import RunnerReadinessStatus
from revocompute import runner_admin_view
from revocompute.runner_admin_view import active_image_view, fleet_view
from revocompute.runner_host import ServerHostPaths
from revocompute.runner_readiness import RunnerReadiness

FLEET_SIZE = 32


def _readiness(
    family: str,
    *,
    status: RunnerReadinessStatus,
    reason_code: str,
    sif_exists: bool,
    sif_sha256: str | None,
) -> RunnerReadiness:
    return RunnerReadiness(
        runner_family=family,
        status=status,
        reason_code=reason_code,
        message=reason_code,
        doctor_ok=status is not RunnerReadinessStatus.NOT_CONFIGURED,
        sif_path=f"/images/{family}.sif",
        sif_exists=sif_exists,
        sif_sha256=sif_sha256,
        build_provenance_current=status is RunnerReadinessStatus.READY,
        build_provenance_digest="sha256:build" if sif_sha256 else None,
        runtime_bundle_sha256=None,
        receipt_exists=sif_sha256 is not None,
        receipt_valid=status is RunnerReadinessStatus.READY,
        receipt_tested_at="2026-01-01T00:00:00Z" if status is RunnerReadinessStatus.READY else None,
        receipt_sif_sha256=sif_sha256,
    )


#: The few lifecycle variants a representative deployment actually shows.  The
#: same variant repeats across families, so the fixture tests the ceiling of
#: evidence shapes rather than thirty bespoke rows.
_VARIANTS = (
    _readiness(
        "family_ready",
        status=RunnerReadinessStatus.READY,
        reason_code="READY",
        sif_exists=True,
        sif_sha256="sha256:" + "a" * 64,
    ),
    _readiness(
        "family_unvalidated",
        status=RunnerReadinessStatus.NOT_VALIDATED,
        reason_code="RECEIPT_MISSING",
        sif_exists=True,
        sif_sha256="sha256:" + "b" * 64,
    ),
    _readiness(
        "family_stale",
        status=RunnerReadinessStatus.VALIDATION_STALE,
        reason_code="RECEIPT_STALE",
        sif_exists=True,
        sif_sha256="sha256:" + "c" * 64,
    ),
    _readiness(
        "family_not_built",
        status=RunnerReadinessStatus.NOT_BUILT,
        reason_code="SIF_MISSING",
        sif_exists=False,
        sif_sha256=None,
    ),
    _readiness(
        "family_unknown_image",
        status=RunnerReadinessStatus.NOT_CONFIGURED,
        reason_code="DOCTOR_FAILED",
        sif_exists=True,
        sif_sha256=None,
    ),
)


def _plugin_tree(root: Path, families: list[str]) -> Path:
    """Materialize a deployable family per name, as the real discovery path reads it."""
    runner_root = root / "runners"
    for name in families:
        family = runner_root / name
        family.mkdir(parents=True)
        family.joinpath("plugin.yaml").write_text(
            "api_version: 1\n"
            f"id: {name}\n"
            "version: '1'\n"
            "runtime:\n"
            f"  image_artifact: {name}.sif\n"
            f"  definition: {name}.def\n"
            "  entrypoint: [bash, run.sh]\n",
            encoding="utf-8",
        )
    return runner_root


def _state(root: Path, runner_root: Path) -> ServerHostPaths:
    return ServerHostPaths(
        server=str(root / "server"),
        config=str(root / "config"),
        root=str(root),
        settings={"RUNNER_SOURCE_ROOT": str(runner_root)},
    )


def _rename(row: RunnerReadiness, name: str) -> RunnerReadiness:
    """Rebind a scripted variant to the family the register is evaluating."""
    return replace(row, runner_family=name)


@pytest.mark.parametrize(
    ("sif_exists", "sif_sha256", "state", "reason"),
    [
        (False, None, "MISSING", "SIF_MISSING"),
        (True, None, "UNKNOWN", "ACTIVE_IMAGE_IDENTITY_UNKNOWN"),
        (True, "sha256:" + "d" * 64, "ACTIVE", None),
    ],
)
def test_active_image_never_infers_identity_from_presence(sif_exists, sif_sha256, state, reason):
    row = _readiness(
        "demo",
        status=RunnerReadinessStatus.NOT_CONFIGURED,
        reason_code="CONFIGURATION_INVALID",
        sif_exists=sif_exists,
        sif_sha256=sif_sha256,
    )

    expected = {"state": state, "sha256": sif_sha256 if state == "ACTIVE" else None, "reason_code": reason}
    assert active_image_view(row) == expected


def test_fleet_projects_a_32_family_register_with_independent_evidence(tmp_path, monkeypatch):
    names = [f"family_{index:02d}" for index in range(FLEET_SIZE)]
    runner_root = _plugin_tree(tmp_path, names)
    state = _state(tmp_path, runner_root)

    scripted = {name: _VARIANTS[index % len(_VARIANTS)] for index, name in enumerate(names)}
    monkeypatch.setattr(
        runner_admin_view,
        "resolve_runner_readiness",
        lambda _state, family: _rename(scripted[family.name], family.name),
    )

    rows = fleet_view(
        state,
        infrastructure={
            "status": "READY",
            "summary": {"scheduler": {"capacity": "AVAILABLE"}, "gpu": {"capacity": "AVAILABLE"}},
        },
        database=None,
        user_id=None,
    )

    assert [row["runner_family"] for row in rows] == names
    assert len(rows) == FLEET_SIZE
    for index, row in enumerate(rows):
        variant = _VARIANTS[index % len(_VARIANTS)]
        assert row["readiness"]["status"] == variant.status.value
        assert row["readiness"]["reason_code"] == variant.reason_code
        assert row["readiness"]["active_image"] == active_image_view(variant)
        # Capacity and access stay siblings of readiness on every row.
        assert row["capacity"] == {"available": True, "reason": "scheduler_available"}
        assert row["access"] == {"restricted": False, "granted": True, "policy_id": None}

    images = [row["readiness"]["active_image"]["state"] for row in rows]
    assert {"ACTIVE", "MISSING", "UNKNOWN"} <= set(images)
