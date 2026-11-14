# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Durable Task lifecycle vocabulary shared by Core, the store, and the API.

``tasks.status`` is the only authority for what may still happen to a Task.
This module names that vocabulary once: the states, the groups every consumer
actually means, the legal transitions between them, and the disposal lanes a
retiring Task follows.  Nothing else may spell a Task status literal.

Two axes share the column, deliberately:

*execution* — ``pending`` -> ``queued`` -> ``running`` -> ``finished`` /
``failed``, with ``cancelled`` reachable from any live state; and
*disposal* — the ``deleting:*`` claim, then either a user deletion
(``deleted:*``) or retention cleanup (``cleaned:*``).  Disposal is entered only
from a settled outcome or a live state the user abandons, so a Task that is
still running is never silently retired.

Recovery returns a ``queued`` or ``running`` Task to ``pending`` and a start
observation may then move it straight back to ``running``.  Those two edges are
listed because they are part of the machine, not accidents: the StageRun record,
not the Task status, decides whether an attempt is still owned.

A ``failed`` Task may be promoted to ``finished`` by the recovery that
republishes a result the run produced but could not publish.  ``finished`` and
``cancelled`` never move back.

The ``deleted:finshed`` spelling is a durable wire value that predates this
module and is kept: existing rows and API consumers spell it that way.
"""

from __future__ import annotations

from typing import Any, NamedTuple

PENDING = "pending"
QUEUED = "queued"
RUNNING = "running"
FINISHED = "finished"
FAILED = "failed"
CANCELLED = "cancelled"
DELETING_FINISHED = "deleting:finished"
DELETING_CANCELLED = "deleting:cancel"
CLEANED_FINISHED = "cleaned:finished"
CLEANED_CANCELLED = "cleaned:cancel"
#: Stored spelling, kept for the rows and clients already using it.
DELETED_FINISHED = "deleted:finshed"
DELETED_CANCELLED = "deleted:cancel"

STATUSES = (
    PENDING,
    QUEUED,
    RUNNING,
    FINISHED,
    FAILED,
    CANCELLED,
    DELETING_FINISHED,
    DELETING_CANCELLED,
    CLEANED_FINISHED,
    CLEANED_CANCELLED,
    DELETED_FINISHED,
    DELETED_CANCELLED,
)

#: The Task is live and may still be cancelled.
ACTIVE = frozenset({PENDING, QUEUED, RUNNING})
#: A dispatch is expected to own a scheduler allocation.
EXECUTING = frozenset({QUEUED, RUNNING})
#: The execution outcome has been decided.  A ``finished`` or ``cancelled``
#: outcome is final; a ``failed`` one may still be promoted to ``finished`` by
#: the same recovery that republishes its result.
OUTCOMES = frozenset({FINISHED, FAILED, CANCELLED})
#: A retire operation owns the Task and is deleting its artifacts.
DISPOSAL_CLAIMS = frozenset({DELETING_FINISHED, DELETING_CANCELLED})
#: Explicit user deletion completed; the row is kept for audit but hidden.
USER_DELETED = frozenset({DELETED_FINISHED, DELETED_CANCELLED})
#: Retention cleanup completed; the row is kept for audit but hidden.
RETENTION_CLEANED = frozenset({CLEANED_FINISHED, CLEANED_CANCELLED})
#: Artifacts are gone, whatever removed them.
DISPOSED = USER_DELETED | RETENTION_CLEANED
#: The run is no longer executing; only disposal, and the recovery that
#: republishes and promotes a failed run, may follow (Admin report view).
SETTLED = OUTCOMES | DISPOSAL_CLAIMS | DISPOSED
#: No field write may target the row, yet a cleanup completion still may.
#: ``finished`` and ``failed`` are deliberately absent: they are settled, but a
#: resubmission of a handle-less ``failed`` Task may retry it.
LOCKED = frozenset({CANCELLED}) | DISPOSAL_CLAIMS | DISPOSED
#: Client pollers stop here.  A ``deleting:*`` claim is not complete: its purge
#: is still in flight.
POLLING_COMPLETE = OUTCOMES | DISPOSED
#: History listings never publish a retired row.
HISTORY_HIDDEN = DISPOSED
#: Result publication and finalization refuse to write over these: a cancel, a
#: deletion, or a retention claim owns the Task's result tree.  ``finished`` and
#: ``failed`` are absent on purpose — a recovery may still republish.
RESULT_WRITES_REFUSED = frozenset({CANCELLED}) | DISPOSAL_CLAIMS | DISPOSED
#: A Task in one of these states may have a published result to read.
PUBLISHED_RESULTS = frozenset({FINISHED, FAILED})
#: The History "needs attention" filter.
ATTENTION = frozenset({FAILED, CANCELLED})

#: The legal execution/disposal transitions.  A same-status write is a field
#: update, not a transition, and is admitted separately by ``accepted_from``.
#:
#: ``failed -> pending`` is the retry of a Task that recorded no allocation: a
#: resubmission of the identical content may re-prepare it.  A failure that
#: still owns a scheduler handle is refused as reserved before reaching here.
#: ``failed -> finished`` is the republication recovery: the run completed but
#: could not publish its result, so the authority that republishes promotes the
#: Task rather than leaving a successful run recorded as a failure.
TRANSITIONS: dict[str, frozenset[str]] = {
    PENDING: frozenset({QUEUED, RUNNING, FAILED, CANCELLED, DELETING_CANCELLED}),
    QUEUED: frozenset({PENDING, RUNNING, FINISHED, FAILED, CANCELLED, DELETING_CANCELLED}),
    RUNNING: frozenset({PENDING, FINISHED, FAILED, CANCELLED, DELETING_CANCELLED}),
    FINISHED: frozenset({DELETING_FINISHED}),
    FAILED: frozenset({PENDING, FINISHED, DELETING_CANCELLED}),
    CANCELLED: frozenset({DELETING_CANCELLED}),
    DELETING_FINISHED: frozenset({CLEANED_FINISHED, DELETED_FINISHED}),
    DELETING_CANCELLED: frozenset({CLEANED_CANCELLED, DELETED_CANCELLED}),
    CLEANED_FINISHED: frozenset(),
    CLEANED_CANCELLED: frozenset(),
    DELETED_FINISHED: frozenset(),
    DELETED_CANCELLED: frozenset(),
}


class Disposal(NamedTuple):
    """The three durable states one dispose operation passes through."""

    claim: str
    cleaned: str
    deleted: str


#: Two lanes, not four: a Task that reached ``finished`` retires through the
#: success lane, every other status through the cancel-history lane.  The lane is
#: a property of the outcome the Task had, never of who requested the retire.
_SUCCESS_LANE = Disposal(DELETING_FINISHED, CLEANED_FINISHED, DELETED_FINISHED)
_OTHER_LANE = Disposal(DELETING_CANCELLED, CLEANED_CANCELLED, DELETED_CANCELLED)
_LANES = (_SUCCESS_LANE, _OTHER_LANE)


def normalize(value: Any) -> str:
    """A status as stored and compared: trimmed and lower-cased."""
    return str(value or "").strip().lower()


def is_active(value: Any) -> bool:
    """The Task is live and may still be cancelled."""
    return normalize(value) in ACTIVE


def artifacts_removed(value: Any) -> bool:
    """The Task's artifacts are gone, whether a user or retention removed them."""
    return normalize(value) in DISPOSED


def artifacts_unavailable(value: Any) -> bool:
    """Artifacts are gone or a retire owns them; neither may be served."""
    return normalize(value) in DISPOSED | DISPOSAL_CLAIMS


def predecessors(status: str) -> frozenset[str]:
    """Every status that may legally move to *status* (excluding itself)."""
    if status not in TRANSITIONS:
        raise ValueError(f"Unknown Task status {status!r}")
    return frozenset(source for source, targets in TRANSITIONS.items() if status in targets)


def accepted_from(status: str) -> frozenset[str]:
    """Every status a guarded write to *status* may observe.

    A live or settled row may be rewritten in its current status: that is an
    ordinary field update, not a transition, and ``update_task`` uses this set
    as its compare-and-set predicate.  A :data:`LOCKED` row may not: it is
    owned by a cancel, deletion, or retire, and only its one disposal edge may
    follow.
    """
    sources = predecessors(status)
    if status not in LOCKED:
        sources = sources | {status}
    return sources


def disposal(status: Any) -> Disposal | None:
    """The dispose lane for *status*, or ``None`` when it is already decided.

    ``None`` covers two different situations the caller must tell apart with
    :data:`DISPOSAL_CLAIMS` and :data:`DISPOSED`: a retire already owns the row
    (resume it), or the artifacts are already gone (nothing to do).
    """
    status = normalize(status)
    if status == FINISHED:
        return _SUCCESS_LANE
    if status in ACTIVE or status in OUTCOMES:
        return _OTHER_LANE
    return None


def cleanup_completion(claim: Any) -> str | None:
    """The retention status a cleanup claim settles to, or ``None``."""
    claim = normalize(claim)
    for lane in _LANES:
        if claim == lane.claim:
            return lane.cleaned
    return None


def cleanup_termination(claim: Any) -> str | None:
    """The user-deletion status a cleanup claim settles to, or ``None``."""
    claim = normalize(claim)
    for lane in _LANES:
        if claim == lane.claim:
            return lane.deleted
    return None
