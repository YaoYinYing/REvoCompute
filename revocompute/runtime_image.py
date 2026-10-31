# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Pinned runtime images for one execution attempt.

A Task's immutable ``task.json`` records ``runtime_images: {family: digest}``:
the digest of the SIF file the family's executions open.  Submission resolves
it once; the Slurm wrapper re-hashes the file immediately before Apptainer and
records what it observed in a schema-2 receipt.  The store writes the observed
digest only into a guarded COMPLETED transition that also checks it against the
attempt's pin.

The digest is an observation of the bytes at the path this attempt opens, not
an immutable identity: the path may still be a mutable active SIF until a
content-addressed store holds the bytes.  A promotion that renames a new SIF
onto the path between submission and launch therefore fails closed here rather
than silently running bytes no receipt validated.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from revocompute.artifact_evidence import receipt_digests
from revocompute.serialization import sha256_file

SHA256_PREFIXED = re.compile(r"sha256:[0-9a-f]{64}\Z")

_SCHEMA_VERSION = "2"


class RuntimeImageError(ValueError):
    """No runtime image or no live-test evidence for this family."""


@dataclass(frozen=True, slots=True)
class RuntimeImage:
    """The path this attempt opens and the digest observed there at submission."""

    path: str
    digest: str


@dataclass(frozen=True, slots=True)
class RuntimeImageObservation:
    """What the compute-node wrapper measured immediately before Apptainer.

    ``expected`` is the submission pin the wrapper carried; ``observed`` is the
    digest of the file it was about to open.  Both are ``sha256:<hex>``.  The
    record is attributable to one Task, StageAttempt, family and Slurm job, so
    a receipt from another attempt or allocation cannot settle this one.
    """

    task_id: str
    stage_name: str
    attempt: int
    family: str
    slurm_job_id: str
    expected: str
    observed: str


def _has_live_test_receipt(family: Any, digest: str) -> bool:
    """Whether a live-test receipt exists for exactly these bytes and family."""
    for path in receipt_digests(family, digest):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (
            isinstance(value, Mapping)
            and value.get("runner_family") == family.name
            and value.get("sif_sha256") == digest
        ):
            return True
    return False


def runtime_image_for_submission(family: Any, *, require_receipt: bool = True) -> RuntimeImage:
    """Resolve the image path and content digest a new Task must pin.

    This is the only resolver boundary.  It returns the path the attempt will
    open and the content digest at that path now; the wrapper re-hashes the
    same path at launch, so a path replaced in between fails closed.  A later
    content-addressed store replaces this body without changing callers,
    ``task.json`` or ``stage_runs``.

    A production submission requires the live-test receipt for exactly those
    bytes.  The live test itself passes ``require_receipt=False``: it is the
    run that produces that receipt, and it must pin the candidate bytes it is
    about to exercise.
    """
    path = str(getattr(family, "slurm_image", "") or "")
    if not path or not Path(path).is_file():
        raise RuntimeImageError(f"Runner family {family.name!r} has no runtime image at {path or '<unset>'!r}")
    digest = sha256_file(path)
    if require_receipt and not _has_live_test_receipt(family, digest):
        raise RuntimeImageError(
            f"Runner family {family.name!r} has no live-test receipt for runtime image {digest}"
        )
    return RuntimeImage(path=path, digest=digest)


def parse_runtime_image_receipt(text: str) -> RuntimeImageObservation | None:
    """Parse the wrapper's schema-2 image observation.

    Shared by the worker settling the attempt and by nothing else: the file is
    read non-destructively and never deleted, so a crash after the wrapper wrote
    it leaves the observation available to recovery.  Anything truncated,
    unknown-schema, unattributable or malformed is treated as absent.
    """
    fields: dict[str, str] = {}
    for line in text.splitlines():
        key, separator, value = line.partition("=")
        if not separator or key in fields:
            continue
        fields[key] = value.strip()
    if fields.get("schema_version") != _SCHEMA_VERSION:
        return None
    task_id = fields.get("task_id", "")
    stage_name = fields.get("stage", "")
    family = fields.get("family", "")
    slurm_job_id = fields.get("slurm_job_id", "")
    expected = fields.get("expected_sha256", "")
    observed = fields.get("observed_sha256", "")
    if not task_id or not stage_name or not family or not slurm_job_id.isdigit():
        return None
    if SHA256_PREFIXED.fullmatch(expected) is None or SHA256_PREFIXED.fullmatch(observed) is None:
        return None
    try:
        attempt = int(fields.get("attempt", ""))
        observed_at = float(fields.get("observed_at", ""))
    except ValueError:
        return None
    if attempt < 1 or observed_at <= 0:
        return None
    return RuntimeImageObservation(
        task_id=task_id,
        stage_name=stage_name,
        attempt=attempt,
        family=family,
        slurm_job_id=slurm_job_id,
        expected=expected,
        observed=observed,
    )
