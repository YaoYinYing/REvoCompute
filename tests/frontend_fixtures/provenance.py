# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The production-provenance pointer a replay bundle carries.

A replay bundle records where its result came from. The canonical record of a
production submission is the machine-generated API acceptance receipt produced by
the receipt tooling (``revocompute.api_receipt``). This module consumes that
receipt rather than inventing a second provenance format: it projects the
receipt's own machine-readable fields into a compact pointer.

Keep the coupling thin. The receipt schema is owned elsewhere and may still be
changing; this module reads only the few stable fields a bundle cites (the task
identity, the receipt digest, and the deployment identity), and when the receipt
parser is present on the current base it re-verifies the receipt digest so a
tampered receipt is rejected rather than cited.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

PROVENANCE_SOURCE = "production_api_acceptance_receipt"


class ProvenanceError(ValueError):
    """The production provenance a bundle cites could not be read or verified."""


def _load_receipt(source: str | Path | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(source, Mapping):
        return dict(source)
    try:
        with open(source, encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, ValueError) as exc:
        raise ProvenanceError(f"receipt is not readable JSON: {exc}") from exc
    if not isinstance(document, Mapping):
        raise ProvenanceError("receipt document must be a JSON object")
    return dict(document)


def _verified(document: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Re-verify the cited receipt's content digest.

    The receipt parser (``revocompute.api_receipt``) owns the receipt contract
    and is authoritative when it is importable. When it is not yet on this base,
    the digest is recomputed with the project's own canonical content digest over
    the receipt body minus its digest and capture-time fields -- the same
    computation the parser performs -- so the pointer can still prove the bytes
    it cites are the bytes it read. A mismatch raises rather than citing a
    tampered receipt.
    """
    try:
        from revocompute.api_receipt import ApiReceiptError, parse_api_receipt
    except ImportError:
        return document, _digest_matches(document)
    try:
        return parse_api_receipt(document), True
    except ApiReceiptError as exc:
        raise ProvenanceError(f"receipt failed validation: {exc}") from exc


def _digest_matches(document: Mapping[str, Any]) -> bool:
    """Whether the receipt's stored digest recomputes from its own body."""
    from revocompute.live_tests import canonical_digest

    stored = document.get("receipt_digest")
    if not isinstance(stored, str) or not stored:
        raise ProvenanceError("receipt has no receipt_digest")
    body = {key: value for key, value in document.items() if key not in {"receipt_digest", "captured_at"}}
    if stored != canonical_digest(body):
        raise ProvenanceError("receipt_digest does not match the receipt contents")
    return True


def production_receipt_pointer(
    source: str | Path | Mapping[str, Any],
    *,
    task_id: str,
    receipt_path: str | None = None,
) -> dict[str, Any]:
    """Project a production receipt into the pointer one replay bundle cites.

    ``task_id`` is the result the bundle captures; the receipt must be for that
    same task, so a bundle can never cite an unrelated acceptance record.
    """
    document, digest_verified = _verified(_load_receipt(source))
    if str(document.get("task_id") or "").lower() != str(task_id).lower():
        raise ProvenanceError("receipt is not for the captured task")
    deployment = document.get("deployment") if isinstance(document.get("deployment"), Mapping) else {}
    submission = document.get("submission") if isinstance(document.get("submission"), Mapping) else {}
    pointer: dict[str, Any] = {
        "source": PROVENANCE_SOURCE,
        "task_id": str(task_id).lower(),
        "task_type": submission.get("task_type"),
        "receipt_version": document.get("receipt_version"),
        "receipt_digest": document.get("receipt_digest"),
        "receipt_digest_verified": digest_verified,
        "deployment_commit": deployment.get("commit"),
        "deployment_mode": deployment.get("mode"),
        "runtime_sif_sha256": deployment.get("runtime_sif_sha256"),
    }
    if receipt_path is not None:
        pointer["receipt_path"] = receipt_path
    return {key: value for key, value in pointer.items() if value is not None}
