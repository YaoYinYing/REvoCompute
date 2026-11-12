# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Query vocabulary and signed cursors for authorized Task history.

The HTTP handler owns authentication; this module owns the bounded request
vocabulary, the strict UTC date parsing, and the opaque cursor.  Cursors are
signed with the same deployment secret as session tokens but a distinct salt,
so a session token can never be replayed as a cursor or vice versa.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from revocompute.auth import _SECRET_KEY

DEFAULT_PAGE_SIZE = 30
MAX_PAGE_SIZE = 100
CURSOR_MAX_AGE_SECONDS = 3600
MAX_QUERY_LENGTH = 200
MAX_FILTER_LENGTH = 100
MAX_STATUS_LENGTH = 50

_SORTS = {"submitted", "finished"}
_DATE_ONLY = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_TASK_ID = re.compile(r"[0-9a-f]{32}\Z")

_cursor_serializer = URLSafeTimedSerializer(_SECRET_KEY, salt="revocompute-task-history-cursor")


class HistoryQueryError(ValueError):
    """A request parameter the History API refuses, with its HTTP status."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class HistoryQuery:
    """The effective, normalized filters of one history request."""

    q: str | None
    task_type: str | None
    status: str | None
    owner: str | None
    submitted_from: float | None
    submitted_to: float | None
    finished_from: float | None
    finished_to: float | None
    sort: str
    limit: int
    cursor: str | None

    def projection(self) -> dict[str, Any]:
        """Echo the authoritative effective query, without the opaque cursor."""
        return {
            "q": self.q,
            "task_type": self.task_type,
            "status": self.status,
            "owner": self.owner,
            "submitted_from": _iso_utc(self.submitted_from),
            "submitted_to": _iso_utc(self.submitted_to),
            "finished_from": _iso_utc(self.finished_from),
            "finished_to": _iso_utc(self.finished_to),
            "sort": self.sort,
            "limit": self.limit,
        }


@dataclass(frozen=True)
class CursorState:
    """The decoded position and traversal anchor of a continuation page."""

    timestamp: float | None
    task_id: str
    anchor: float


def parse_history_query(args: Mapping[str, str], *, is_admin: bool) -> HistoryQuery:
    """Normalize and validate the Task history query string.

    Invalid page sizes are normalized rather than rejected.  An owner filter is
    administrator-only and is refused before any query runs, so an ordinary
    caller cannot probe owner identities; dates and over-long strings are
    refused with a bounded error message.
    """
    owner = _bounded(args.get("owner"), "owner", MAX_FILTER_LENGTH)
    if owner and not is_admin:
        raise HistoryQueryError("The owner filter is administrator-only", status=403)
    sort = (args.get("sort") or "submitted").strip().lower()
    if sort not in _SORTS:
        raise HistoryQueryError("sort must be 'submitted' or 'finished'")
    raw_cursor = (args.get("cursor") or "").strip() or None
    if raw_cursor is not None and len(raw_cursor) > 512:
        raise HistoryQueryError("cursor is too long")
    return HistoryQuery(
        q=_bounded(args.get("q"), "q", MAX_QUERY_LENGTH),
        task_type=_bounded(args.get("task_type"), "task_type", MAX_FILTER_LENGTH),
        status=_bounded(args.get("status"), "status", MAX_STATUS_LENGTH),
        owner=owner,
        submitted_from=_date_bound(args.get("submitted_from"), "submitted_from"),
        submitted_to=_date_bound(args.get("submitted_to"), "submitted_to", end_of_day=True),
        finished_from=_date_bound(args.get("finished_from"), "finished_from"),
        finished_to=_date_bound(args.get("finished_to"), "finished_to", end_of_day=True),
        sort=sort,
        limit=_page_size(args.get("limit")),
        cursor=raw_cursor,
    )


def filter_fingerprint(query: HistoryQuery) -> str:
    """A stable digest of every effective filter a cursor is bound to."""
    payload = {
        "q": query.q,
        "task_type": query.task_type,
        "status": query.status,
        "owner": query.owner,
        "submitted_from": query.submitted_from,
        "submitted_to": query.submitted_to,
        "finished_from": query.finished_from,
        "finished_to": query.finished_to,
        "sort": query.sort,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def encode_cursor(
    *, timestamp: float | None, task_id: str, fingerprint: str, scope: str, sort: str, anchor: float
) -> str:
    """Sign the continuation position and the traversal's as-of anchor."""
    return _cursor_serializer.dumps(
        {
            "v": 1,
            "ts": timestamp,
            "id": task_id,
            "fp": fingerprint,
            "scope": scope,
            "sort": sort,
            "anchor": anchor,
        }
    )


def decode_cursor(token: str, *, fingerprint: str, scope: str, sort: str) -> CursorState | None:
    """Return the position only when the cursor is this caller's, unexpired and unchanged.

    A ``None`` answer tells the handler to restart from page one: malformed,
    expired, replayed under different filters, or minted for a different user or
    sort.  Nothing in a rejected cursor is trusted.
    """
    try:
        payload = _cursor_serializer.loads(token, max_age=CURSOR_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(payload, dict) or payload.get("v") != 1:
        return None
    if payload.get("fp") != fingerprint or payload.get("scope") != scope or payload.get("sort") != sort:
        return None
    task_id = payload.get("id")
    timestamp = payload.get("ts")
    anchor = payload.get("anchor")
    if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
        return None
    if timestamp is not None and (isinstance(timestamp, bool) or not isinstance(timestamp, (int, float))):
        return None
    if isinstance(anchor, bool) or not isinstance(anchor, (int, float)):
        return None
    return CursorState(timestamp=None if timestamp is None else float(timestamp), task_id=task_id, anchor=float(anchor))


def _page_size(raw: str | None) -> int:
    if raw is None or not raw.strip():
        return DEFAULT_PAGE_SIZE
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_PAGE_SIZE
    if value <= 0:
        return DEFAULT_PAGE_SIZE
    return min(value, MAX_PAGE_SIZE)


def _bounded(raw: str | None, name: str, maximum: int) -> str | None:
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    if len(value) > maximum:
        raise HistoryQueryError(f"{name} is longer than {maximum} characters")
    return value


def _date_bound(raw: str | None, name: str, *, end_of_day: bool = False) -> float | None:
    """Parse one strict ISO 8601 UTC bound as a POSIX timestamp.

    A bare ``YYYY-MM-DD`` names a whole UTC day: ``_from`` starts at 00:00 and
    ``_to`` ends at the final microsecond.  A full timestamp must carry an
    explicit offset; a naive local time is refused rather than guessed.
    """
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    try:
        if _DATE_ONLY.fullmatch(value):
            day = date.fromisoformat(value)
            parsed = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
            if end_of_day:
                parsed += timedelta(days=1) - timedelta(microseconds=1)
        else:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("naive timestamp")
    except ValueError as exc:
        raise HistoryQueryError(f"{name} must be an ISO 8601 UTC date or offset timestamp") from exc
    return parsed.astimezone(timezone.utc).timestamp()


def _iso_utc(timestamp: float | None) -> str | None:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
