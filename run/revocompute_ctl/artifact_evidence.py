# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Content-addressed build and live-test evidence for Runner SIFs."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from revocompute.live_tests import atomic_write_json, canonical_digest, sha256_file

_SHA256_RE = re.compile(r"sha256:([0-9a-f]{64})\Z")


_RECEIPT_IDENTITY_FIELDS = (
    "build_provenance_digest",
    "test_definition_digest",
    "configuration_digest",
    "execution_uid",
    "execution_gid",
    "scheduler_user",
)


def _receipt_identity(value: Mapping[str, Any]) -> str:
    return canonical_digest({field: value.get(field) for field in _RECEIPT_IDENTITY_FIELDS}).removeprefix("sha256:")


def evidence_path(
    family, sif_sha256: str, kind: str, *, receipt_identity: Mapping[str, Any] | None = None
) -> Path:
    match = _SHA256_RE.fullmatch(sif_sha256)
    if match is None or kind not in {"build", "receipt"}:
        raise ValueError("invalid Runner artifact evidence identity")
    suffix = f".{_receipt_identity(receipt_identity)}" if kind == "receipt" and receipt_identity is not None else ""
    return Path(family.slurm_image).parent / "evidence" / family.name / f"{match.group(1)}{suffix}.{kind}.json"


def read_artifact_evidence(
    family,
    artifact: str | Path,
    kind: str,
    *,
    receipt_identity: Mapping[str, Any] | None = None,
) -> tuple[str, Mapping[str, Any] | None]:
    sif_sha256 = sha256_file(artifact)
    try:
        if kind == "receipt" and receipt_identity is None:
            digest = sif_sha256.removeprefix("sha256:")
            matches = sorted(evidence_path(family, sif_sha256, kind).parent.glob(f"{digest}.*.receipt.json"))
            if len(matches) != 1:
                return sif_sha256, None
            path = matches[0]
        else:
            path = evidence_path(family, sif_sha256, kind, receipt_identity=receipt_identity)
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return sif_sha256, None
    if not isinstance(value, Mapping):
        return sif_sha256, None
    if value.get("runner_family") != family.name:
        return sif_sha256, None
    return sif_sha256, value


def read_evidence_for_digest(
    family, sif_sha256: str, kind: str, *, receipt_identity: Mapping[str, Any] | None = None
) -> Mapping[str, Any] | None:
    """Read evidence for a previously recorded digest without reading the SIF."""
    try:
        path = evidence_path(family, sif_sha256, kind, receipt_identity=receipt_identity)
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(value, Mapping) or value.get("runner_family") != family.name:
        return None
    return value


def read_build_evidence_for_provenance(family, build_provenance_digest: str) -> Mapping[str, Any] | None:
    """Read build evidence by declared-input provenance without hashing the SIF."""
    root = Path(family.slurm_image).parent / "evidence" / family.name
    try:
        paths = sorted(root.glob("*.build.json"))
    except OSError:
        return None
    for path in paths:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (
            isinstance(value, Mapping)
            and value.get("runner_family") == family.name
            and value.get("build_provenance_digest") == build_provenance_digest
        ):
            return value
    return None


def read_receipt_for_identity(family, receipt_identity: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Read a receipt by build and validation identity without hashing the SIF."""
    root = Path(family.slurm_image).parent / "evidence" / family.name
    for path in sorted(root.glob("*.receipt.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(value, Mapping) or value.get("runner_family") != family.name:
            continue
        if all(value.get(field) == receipt_identity.get(field) for field in _RECEIPT_IDENTITY_FIELDS):
            return value
    return None


def receipt_exists_for_provenance(family, build_provenance_digest: str) -> bool:
    root = Path(family.slurm_image).parent / "evidence" / family.name
    for path in root.glob("*.receipt.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (
            isinstance(value, Mapping)
            and value.get("runner_family") == family.name
            and value.get("build_provenance_digest") == build_provenance_digest
        ):
            return True
    return False


def write_artifact_evidence(family, sif_sha256: str, kind: str, value: Mapping[str, Any]) -> Path:
    path = evidence_path(
        family, sif_sha256, kind, receipt_identity=value if kind == "receipt" else None
    )
    payload = {**value, "runner_family": family.name, "sif_sha256": sif_sha256}
    if kind == "receipt":
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = None
        if (
            isinstance(previous, Mapping)
            and previous.get("runner_family") == family.name
            and previous.get("sif_sha256") == sif_sha256
        ):
            previous_cases = previous.get("cases") if isinstance(previous.get("cases"), list) else ()
            current_cases = payload.get("cases") if isinstance(payload.get("cases"), list) else ()
            cases = {
                case["case_id"]: case
                for case in previous_cases
                if isinstance(case, Mapping) and case.get("passed") is True and "case_id" in case
            }
            cases.update(
                (case["case_id"], case)
                for case in current_cases
                if isinstance(case, Mapping) and case.get("passed") is True and "case_id" in case
            )
            payload["cases"] = [cases[case_id] for case_id in sorted(cases)]
    atomic_write_json(path, payload)
    return path


def artifact_receipt_exists(family, sif_sha256: str) -> bool:
    digest = sif_sha256.removeprefix("sha256:")
    return any(evidence_path(family, sif_sha256, "receipt").parent.glob(f"{digest}.*.receipt.json"))
