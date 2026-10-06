# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The Core-owned admission vocabulary shared by every scientific ingress.

Two things live here, and both exist because the same decision must mean the
same thing on the browser form, the public API, the API-key path, the Tool
call, and the MCP projection of the same workflow:

* the bounded, machine-readable reason codes an admission decision is reported
  with, and the single table mapping each to its preflight phase, and
* the validator-revision identity plus the receipt that binds a validation
  decision to the exact immutable bytes execution later consumes.

This module owns *the reason codes and their phase*, nothing else.  The
operational events a rejection is recorded under are the existing ones in
:mod:`revocompute.operational_events` — ``preflight.security_rejected``,
``preflight.contract_rejected``, ``preflight.admission_denied``, and
``manifest.published`` — and this module only says which of those a code routes
to.  There is no second event family and no duplicate event name here; adding
an event belongs in ``operational_events.EVENT_NAMES``, the module that owns it.

The vocabulary is deliberately data, not prose: callers switch on the code and
never scrape a message.
"""

from __future__ import annotations

import hashlib
import json
import ntpath
import os
import stat as stat_module
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import unquote

from werkzeug.utils import secure_filename

# NAME_MAX is 255 on Linux; leave room for the 21-byte `.tmp_<16 hex>_`
# quarantine prefix plus the role subdirectory.  200 bytes is generous for any
# real input filename and cannot overflow the prefix.
MAX_INPUT_COMPONENT_BYTES = 200
# PATH_MAX is 4096 on Linux and the snapshot root sits well inside it, so 1024
# bytes of joined relative path is both far below the limit and far above any
# real nested upload.
MAX_INPUT_RELATIVE_PATH_BYTES = 1024


class Phase(str, Enum):
    """Which preflight phase an admission decision belongs to."""

    SECURITY = "security"
    CONTRACT = "contract"
    ADMISSION = "admission"


#: Bounded, stable vocabulary.  Renaming one of these is a protocol change:
#: the Web UI, API, MCP projection, operational events, and Admin reports all
#: key off the same string.
#:
#: The phase split is deliberate and load-bearing.  ``SECURITY`` is transport
#: and byte safety — content, paths, names, namespace identity, size — and is
#: what a submission must clear before any compute is contemplated.  ``CONTRACT``
#: is the caller's declared vocabulary not matching the owning ``task.yaml``
#: (role names, cardinality, declared format), which is a request-shape error,
#: not a hostile-bytes finding.
REASON_CODES: dict[Phase, frozenset[str]] = {
    Phase.SECURITY: frozenset(
        {
            "input_path_invalid",
            "input_namespace_collision",
            "input_format_invalid",
            "input_logical_type_invalid",
            "input_file_count_limit",
            "input_file_size_limit",
            "input_total_size_limit",
            "input_snapshot_mismatch",
            "request_size_limit",
            "workspace_json_invalid",
            "validator_resource_limit",
        }
    ),
    Phase.CONTRACT: frozenset(
        {
            "contract_invalid",
            "input_role_binding",
            "input_role_format",
            "input_role_unknown",
            "input_role_cardinality",
        }
    ),
    Phase.ADMISSION: frozenset(
        {
            "admission_denied",
            "admission_limited",
            "admission_unavailable",
            "gpu_credit_exhausted",
            "infrastructure_unavailable",
            "runner_not_ready",
        }
    ),
}


_REQUEST_SIZE_LIMIT = "request_size_limit"

#: Artifact-publication reason codes, carried on the ``manifest.published``
#: event so a downstream consumer reads why a result set was narrowed without
#: scraping the human-readable problems.  Separate from the ingress phases: an
#: artifact is not a submission, so there is no preflight phase to route to.
ARTIFACT_PUBLICATION_REJECTED = "artifact_publication_rejected"
ARTIFACT_CAPACITY_GUARD = "artifact_capacity_guard"

_PHASE_BY_CODE = {
    code: phase.value for phase, codes in REASON_CODES.items() for code in codes
}

#: Which existing ``operational_events`` name each non-success phase is recorded
#: under.  These are the operational_events module's names verbatim — this table
#: only routes a reason code to them; it is not a second event family.
_EVENT_BY_PHASE = {
    Phase.SECURITY.value: "preflight.security_rejected",
    Phase.CONTRACT.value: "preflight.contract_rejected",
    Phase.ADMISSION.value: "preflight.admission_denied",
}


def phase_for_code(code: str, *, http_status: int = 400) -> str:
    """Return the preflight phase for one reason code.

    An unlisted code falls back to the status-derived default the boundary used
    before the vocabulary existed, so a new code can never silently become a
    "security" rejection merely by being added at a call site.
    """
    known = _PHASE_BY_CODE.get(code)
    if known is not None:
        return known
    return Phase.ADMISSION.value if http_status >= 401 else Phase.CONTRACT.value


def event_for_code(code: str, *, http_status: int = 400) -> str:
    """Return the existing operational event name for one admission rejection."""
    return _EVENT_BY_PHASE[phase_for_code(code, http_status=http_status)]


# The validator revision is the identity of the boundary that produced a
# decision, not a hand-maintained version string: it is a content digest of the
# parser and boundary sources, so it moves exactly when the validation behavior
# can move.  A hand-written constant is a second source of truth that drifts.
_BOUNDARY_SOURCES = (
    "input_validators/__init__.py",
    "input_validators/common.py",
    "input_validators/isolated_validation.py",
    "input_validators/isolated_worker.py",
    "input_validators/fasta.py",
    "input_validators/json_file.py",
    "input_validators/mmcif.py",
    "input_validators/pdb.py",
    "input_validators/profiles.py",
    "input_validators/small_molecule.py",
    "input_validators/structured_data.py",
    "ingress_security.py",
)


def validator_revision() -> str:
    """Return the content identity of the Core validation boundary.

    ``sha256:<hex>`` over the byte content of every boundary source.  A
    deployment that cannot read its own sources reports ``sha256:unavailable``
    rather than guessing, so a receipt never claims an identity it cannot back.
    """
    digest = hashlib.sha256()
    try:
        for relative in _BOUNDARY_SOURCES:
            path = Path(__file__).parent / relative
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    except OSError:
        return "sha256:unavailable"
    return f"sha256:{digest.hexdigest()}"


@dataclass(frozen=True, slots=True)
class ValidationReceipt:
    """Durable evidence that one immutable byte stream was admitted.

    The receipt is written into the task snapshot beside the bytes it describes,
    so execution later consumes a manifest that names the digest it validated,
    the format and logical profile it applied, and the boundary that decided.
    """

    sha256: str
    size: int
    format: str
    logical_type: str
    relative_path: str
    role: str
    decision: str = "accepted"
    reason_code: str | None = None

    def as_record(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "reason_code": self.reason_code,
            "sha256": self.sha256,
            "size": self.size,
            "format": self.format,
            "logical_type": self.logical_type,
            "relative_path": self.relative_path,
            "role": self.role,
            "validator_revision": validator_revision(),
        }


def snapshot_mismatch_reason(receipt: Any, physical_path: str) -> str | None:
    """Return a reason code when *physical_path* is not the admitted bytes.

    Checks the digest the receipt recorded, the validator revision that decided,
    and — defensively — that the path is still a private regular file.  Returns
    ``None`` only when the snapshot provably *is* the admitted byte stream under
    the same boundary, which is the sole case where revalidation may be skipped.
    """
    if not isinstance(receipt, dict):
        return "input_snapshot_mismatch"
    recorded = str(receipt.get("sha256") or "")
    revision = str(receipt.get("validator_revision") or "")
    if not recorded or revision != validator_revision():
        return "input_snapshot_mismatch"
    try:
        if os.path.islink(physical_path) or not os.path.isfile(physical_path):
            return "input_snapshot_mismatch"
        info = os.stat(physical_path, follow_symlinks=False)
        if not stat_module.S_ISREG(info.st_mode) or info.st_nlink != 1:
            return "input_snapshot_mismatch"
        digest = hashlib.sha256()
        with open(physical_path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return "input_snapshot_mismatch"
    if digest.hexdigest() != recorded:
        return "input_snapshot_mismatch"
    return None


def canonical_relative_path(raw_path: str) -> tuple[str | None, str | None]:
    """Canonicalize one submitted input path, returning ``(path, reason_code)``.

    Fails closed with a bounded reason code instead of an exception: the caller
    is an ingress handler reporting an admission decision, not a resolver.
    """
    source = unicodedata.normalize("NFKC", str(raw_path or "")).strip()
    if not source or any(ord(character) < 32 or ord(character) == 127 for character in source):
        return None, "input_path_invalid"
    decoded = unquote(source)
    for candidate in (source, decoded):
        slash_normalized = candidate.replace("\\", "/")
        drive, _tail = ntpath.splitdrive(candidate)
        if drive or ntpath.isabs(candidate) or slash_normalized.startswith("/"):
            return None, "input_path_invalid"
        parts = slash_normalized.split("/")
        if not parts or any(part in {"", ".", ".."} or part.startswith(".") for part in parts):
            return None, "input_path_invalid"
    normalized = source.replace("\\", "/")
    raw_parts = normalized.split("/")
    safe_parts = [secure_filename(part) for part in raw_parts]
    if any(not part for part in safe_parts):
        return None, "input_path_invalid"
    # A name this long cannot become a file: quarantine prefixes 21 bytes to the
    # basename (`.tmp_<16 hex>_`), so an unbounded name overflows NAME_MAX and
    # the OSError reaches the client as an unhandled 500.  Reject at the
    # contract boundary with a normal 400 instead.  `secure_filename` only
    # expands names, so measuring the sanitized form is the conservative check.
    if any(len(part.encode("utf-8")) > MAX_INPUT_COMPONENT_BYTES for part in safe_parts):
        return None, "input_path_invalid"
    # Bounding each component is not enough: the snapshot copy joins every one
    # of them under the role directory, so a path with ~20 legal components
    # still overflows PATH_MAX and reaches `_prepare_task_record` as the same
    # unhandled OSError.  Bound the joined path too.
    relative_path = "/".join(safe_parts)
    if len(relative_path.encode("utf-8")) > MAX_INPUT_RELATIVE_PATH_BYTES:
        return None, "input_path_invalid"
    return relative_path, None


T = TypeVar("T")


def collapse_sanitization_collisions(
    items: Iterable[tuple[str, T]],
) -> tuple[list[tuple[str, T]], T | None, bool]:
    """Drop entries whose canonical path duplicates one already admitted.

    ``secure_filename`` is many-to-one: ``a b.pdb`` and ``a_b.pdb`` both become
    ``a_b.pdb``, and a Unicode name folds onto its ASCII lookalike.  Two
    submissions that canonicalize to one path are one namespace entry, so the
    later one is dropped and the collision is reported.  Returns
    ``(kept, first_colliding_item, had_collision)``; the caller decides whether
    a collision is an admission failure for that role.
    """
    seen: set[str] = set()
    kept: list[tuple[str, T]] = []
    first_collision: T | None = None
    collided = False
    for canonical, item in items:
        if canonical in seen:
            collided = True
            if first_collision is None:
                first_collision = item
            continue
        seen.add(canonical)
        kept.append((canonical, item))
    return kept, first_collision, collided


def receipt_identity(receipts: Iterable[dict[str, Any]]) -> str:
    """Return the canonical identity of the admitted snapshot.

    Used where a Task identity must name *what was admitted and by which
    boundary*, so a submission prepared under one validator revision is not
    silently reused as the same Task under another.
    """
    payload = json.dumps(
        sorted(
            (
                {
                    "path": str(receipt.get("relative_path") or ""),
                    "sha256": str(receipt.get("sha256") or ""),
                    "format": str(receipt.get("format") or ""),
                    "logical_type": str(receipt.get("logical_type") or ""),
                    "role": str(receipt.get("role") or ""),
                    "validator_revision": str(receipt.get("validator_revision") or ""),
                }
                for receipt in receipts
            ),
            key=lambda item: (item["role"], item["path"]),
        ),
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
