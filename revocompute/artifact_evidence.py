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
    "runtime_bundle_sha256",
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


def receipt_digests(family, sif_sha256: str) -> tuple[Path, ...]:
    """Every receipt path recorded for exactly this artifact digest."""
    match = _SHA256_RE.fullmatch(sif_sha256)
    if match is None:
        return ()
    root = Path(family.slurm_image).parent / "evidence" / family.name
    try:
        return tuple(sorted(root.glob(f"{match.group(1)}.*.receipt.json")))
    except OSError:
        return ()


def read_receipt_for_digest(
    family, sif_sha256: str, receipt_identity: Mapping[str, Any]
) -> Mapping[str, Any] | None:
    """Read the receipt written for exactly this digest and identity, without hashing."""
    try:
        value = json.loads(
            evidence_path(family, sif_sha256, "receipt", receipt_identity=receipt_identity).read_text(
                encoding="utf-8"
            )
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(value, Mapping) or value.get("runner_family") != family.name:
        return None
    return value


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


def staged_identity_path(family) -> Path:
    """The path-bound identity of the staged candidate beside its artifact."""
    return Path(f"{family.slurm_image}.next.build.json")


def _staged_stat_identity(family) -> list[int] | None:
    """The staged file's stat identity, captured while its bytes are known.

    ``None`` when nothing is staged: a live test that passed still writes its
    receipt, and losing the candidate must not turn that run into an exception.
    A record without a stat identity describes no file, so readers fail closed.
    """
    try:
        stat = Path(f"{family.slurm_image}.next").stat()
    except OSError:
        return None
    return [stat.st_size, stat.st_mtime_ns, stat.st_ino]


def write_staged_identity(family, sif_sha256: str, build_provenance_digest: str) -> None:
    """Record the digest of the file staged at ``<sif>.next``.

    Build evidence is content-addressed, so same-provenance siblings leave
    several records and none of them says which artifact is staged.  This
    sidecar is the one path-bound record; it is removed on promotion.  It also
    carries the staged file's stat identity, so a reader can tell that the
    recorded bytes are no longer the staged bytes without hashing the artifact.
    """
    atomic_write_json(
        staged_identity_path(family),
        {
            "runner_family": family.name,
            "sif_sha256": sif_sha256,
            "build_provenance_digest": build_provenance_digest,
            "staged_stat_identity": _staged_stat_identity(family),
        },
    )


def read_staged_digest(family) -> str | None:
    """The digest the staged-identity record names, whatever its provenance.

    Provenance must not gate this read: the record exists to bind *bytes* to the
    staged path, and a record naming another provenance still names a digest.
    Gating on provenance here made readiness report "unrecorded" for a record
    the activation path accepts -- the same disagreement, one field over.
    """
    try:
        value = json.loads(staged_identity_path(family).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, Mapping) or value.get("runner_family") != family.name:
        return None
    candidate = value.get("sif_sha256")
    return candidate if isinstance(candidate, str) else None


def staged_identity_describes(family, sif_sha256: str) -> bool:
    """Whether the staged-identity record describes exactly the staged bytes.

    A candidate rewritten after the record was written still has a receipt for
    the bytes it replaced, so readiness and activation both need this check:
    promotion refuses bytes the record does not describe, and readiness stops
    recommending a promotion the deployment-host step would refuse.  The stat
    identity is the cheap half of the contract; activation additionally hashes
    the candidate and binds its receipt, which is the stronger half.

    shortcut: a rewrite preserving size, mtime and inode is invisible to this
    check, so readiness reports the recorded identity rather than the bytes on
    disk. Activation additionally hashes the candidate and re-checks the file it
    replaced, which catches any swap that changes the stat identity; a swap that
    preserves all three inside the activation window remains undetected. Upgrade
    to a measured activation anchor when that must close too.
    """
    try:
        value = json.loads(staged_identity_path(family).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(value, Mapping) or value.get("runner_family") != family.name:
        return False
    if value.get("sif_sha256") != sif_sha256:
        return False
    try:
        return _staged_stat_identity(family) == [int(item) for item in value["staged_stat_identity"]]
    except (KeyError, TypeError, ValueError, OSError):
        return False


def remove_staged_identity(family) -> None:
    try:
        staged_identity_path(family).unlink()
    except FileNotFoundError:
        pass


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


