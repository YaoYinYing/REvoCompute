# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Ingest and projection of runner-reported resource observations.

The runner publishes one normalized observation per execution attempt on
stdout; the server stores them and projects two bounded, read-only views back
into the next ``task.json``: the guidance the runner enforces (what the learned
evidence says about this profile) and the observations the server's own
estimator ingests.  Nothing here measures anything — measurement happens in the
runner, where the GPU allocations live.

Durable per-item state is the runner's ``work_items.json``, written atomically
beside the results.  The server reads it live and at finalization; the format
is the frozen interface shared with ``docker/runners/common/persistent_runner``,
which the server must not import (it is runner-tree code).  ``read_work_items``
here is the one server-side reader of that file, so both sides agree on the
name and shape by construction.
"""

from __future__ import annotations

import json
import logging
import os
import stat
from collections.abc import Iterable, Sequence
from typing import Any

from revocompute import resource_model as rm

OBSERVATION_PREFIX = "REVODESIGN_OBSERVATION:"
PROGRESS_PREFIX = "REVODESIGN_PROGRESS:"
TASK_OUTCOME_PREFIX = "REVODESIGN_TASK_OUTCOME:"
WORK_ITEMS_NAME = "work_items.json"

#: Work-item states and task outcomes, as the frozen Runner Protocol defines
#: them.  The server cannot import the runner's module (it lives in the runner
#: tree), so the vocabulary is restated here.  Only ``SUCCEEDED`` and the three
#: failure states are named: anything else — ``PENDING``, ``RUNNING``,
#: ``CANCELLED`` — is unfinished in :func:`derive_outcome`, which is the safe
#: reading of a state the server did not observe happen.
ITEM_SUCCEEDED = "SUCCEEDED"
ITEM_FAILED_STATES = ("FAILED_INPUT", "FAILED_RESOURCE", "FAILED_RUNTIME")
TASK_OUTCOME_SUCCESS = "SUCCESS"
TASK_OUTCOME_PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
TASK_OUTCOME_FAILED = "FAILED"
TASK_OUTCOME_CANCELLED_PARTIAL = "CANCELLED_PARTIAL"
TASK_OUTCOMES = (
    TASK_OUTCOME_SUCCESS,
    TASK_OUTCOME_PARTIAL_SUCCESS,
    TASK_OUTCOME_FAILED,
    TASK_OUTCOME_CANCELLED_PARTIAL,
)

#: Hard bound on one runner-protocol stdout line.  A production observation is a
#: few KiB; anything larger is not one, so the bound rejects a pathological line
#: before ``json.loads`` ever builds a structure from it.
PROTOCOL_LINE_MAX_BYTES = 64 * 1024

#: Bound on the observation projection embedded in one ``task.json``.  The
#: estimator needs a bounded history, not the whole table.
OBSERVATION_LIMIT = 200
#: Bound on the per-item manifest (``work_items.json``) the server will read.
#: A production task's item count is far below this, and an oversized file is
#: refused rather than parsed, so a hostile result tree cannot exhaust memory.
WORK_ITEMS_MAX_BYTES = 8 * 1024 * 1024
#: Bound on the *structure*, not just the bytes: a manifest of nested empty
#: lists is small on disk and still unbounded in items.  A production task's
#: item count is orders of magnitude below this cap.
WORK_ITEMS_MAX_ITEMS = 100_000


def _parse_json_payload(line: str, prefix: str) -> dict[str, Any] | None:
    """Parse the JSON object a protocol line carries, or ``None``.

    Total by construction: ``json.loads`` on untrusted transport can raise
    ``RecursionError`` on a deeply nested payload just as easily as it can raise
    ``ValueError``, and the caller is a poll loop whose cleanup must run.  The
    length bound rejects a pathological line before a structure is built at all.
    """
    position = line.find(prefix)
    if position < 0:
        return None
    payload_text = line[position + len(prefix) :].strip()
    if len(payload_text) > PROTOCOL_LINE_MAX_BYTES:
        logging.warning("Refusing oversized %s line", prefix.rstrip(":"))
        return None
    try:
        payload = json.loads(payload_text)
    except Exception:  # untrusted transport: ValueError, TypeError, RecursionError
        return None
    return payload if isinstance(payload, dict) else None


def parse_observation_line(line: str) -> dict[str, Any] | None:
    """Parse one ``REVODESIGN_OBSERVATION:{json}`` line, or return ``None``.

    Runner output is untrusted transport: a malformed line is dropped, never
    raised, so one bad log line cannot end a running task.
    """
    payload = _parse_json_payload(line, OBSERVATION_PREFIX)
    if payload is None or not payload.get("runner"):
        return None
    return payload


def parse_progress_line(line: str) -> dict[str, Any] | None:
    """Parse one ``REVODESIGN_PROGRESS:{json}`` line, or return ``None``."""
    payload = _parse_json_payload(line, PROGRESS_PREFIX)
    return payload if payload else None


def parse_task_outcome_line(line: str) -> str | None:
    """Parse one ``REVODESIGN_TASK_OUTCOME:<name>`` line, or return ``None``."""
    position = line.find(TASK_OUTCOME_PREFIX)
    if position < 0:
        return None
    outcome = line[position + len(TASK_OUTCOME_PREFIX) :].strip()
    if len(outcome) > 64:
        return None
    return outcome if outcome in TASK_OUTCOMES else None


def derive_outcome(items: Sequence[dict[str, Any]]) -> str:
    """Derive the task outcome from item states (the server's own rule).

    The rule's owner is ``docker/runners/common/persistent_runner.derive_outcome``
    (runner-tree code the server must not import), restated here so the published
    outcome is the server's derivation and not the runner's assertion.
    ``CANCELLED`` and any state the server does not know count as unfinished,
    which is the safe reading: neither a success nor a failure.
    """
    succeeded = sum(1 for item in items if item.get("status") == ITEM_SUCCEEDED)
    failed = sum(1 for item in items if item.get("status") in ITEM_FAILED_STATES)
    not_finished = sum(1 for item in items if item.get("status") not in (ITEM_SUCCEEDED, *ITEM_FAILED_STATES))
    if not_finished:
        return TASK_OUTCOME_CANCELLED_PARTIAL
    if failed == 0:
        return TASK_OUTCOME_SUCCESS
    return TASK_OUTCOME_PARTIAL_SUCCESS if succeeded else TASK_OUTCOME_FAILED


def observe_lines(
    lines: Iterable[str],
    *,
    store: Any,
    task: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Persist every observation line in a captured stdout stream.

    ``store`` is the caller's task store.  It is required rather than imported:
    this module is imported by ``routes`` *before* the task runtime, and
    reaching back for a module global at call time re-enters that import from
    inside a partially initialized application.  ``task`` supplies the durable
    identity a runner's stdout cannot know — the task row's id and its storage
    key, needed to attribute the row to a tenant.  Called for failed jobs too:
    an OOM row is evidence, not noise.
    """
    stored: list[dict[str, Any]] = []
    for line in lines:
        payload = parse_observation_line(line)
        if payload is None:
            continue
        row = {**payload, "_storage_key": (task or {}).get("storage_key") or ""}
        if task is not None:
            row.setdefault("task_id", str(task.get("md5sum") or ""))
        try:
            if store.record_resource_observation(row) is not None:
                stored.append(row)
        except Exception:  # ingestion is bookkeeping; never fail the job for it
            logging.exception("Could not store a resource observation for task %s", (task or {}).get("md5sum"))
    return stored


def observations_for_guidance(
    runner_family: str,
    adaptation: Any,
    *,
    store: Any,
    limit: int = OBSERVATION_LIMIT,
) -> dict[str, Any]:
    """Compute the guidance block ``task.json`` carries for one submission.

    Total and non-raising: a storage failure yields empty guidance, which is
    exactly the observe-stage behaviour, never a refused submission.
    """
    stage = getattr(adaptation, "stage", rm.STAGES[0])
    plans = tuple(getattr(adaptation, "fallback_plans", ()) or ())
    try:
        rows = store.list_resource_observations(runners=(runner_family,), limit=limit)
    except Exception:  # guidance is advisory; the default path must still run
        logging.exception("Could not build resource guidance for runner family %s", runner_family)
        return rm.guidance_for(plans, (), stage=stage)
    observations = []
    for payload in map(_observation_payload, rows):
        if not payload:
            continue
        try:
            observations.append(rm.ResourceObservation.from_dict(payload))
        except Exception:
            # One unreadable row must not silence the whole family's evidence;
            # ingest rejects such a row now, so this only covers history.
            logging.warning("Skipping unreadable resource observation for runner family %s", runner_family)
    return rm.guidance_for(plans, observations, stage=stage)


def _observation_payload(row: dict[str, Any]) -> dict[str, Any] | None:
    """The stored normalized JSON, minus the server-only tenant attribution."""
    payload: Any = None
    raw = row.get("observation_json")
    if isinstance(raw, str) and raw:
        try:
            payload = json.loads(raw)
        except Exception:  # stored bytes are still untrusted; never raise here
            payload = None
    if not isinstance(payload, dict):
        # A row written by a version that stored only the projected columns
        # still describes an observation; publish those columns instead.
        payload = {key: value for key, value in row.items() if key not in {"id", "observation_json"}}
    return {key: value for key, value in payload.items() if not str(key).startswith("_")}


def work_items_path(result_dir: str) -> str:
    return os.path.join(result_dir, WORK_ITEMS_NAME)


def read_work_items(result_dir: str) -> dict[str, Any] | None:
    """Read the runner's per-item state, or ``None`` when it is absent/invalid.

    Atomic publication on the runner side means a reader sees either the
    previous or the next complete file; a missing or half-written file is
    treated as "no per-item detail", never as an error.  The file is read
    without following a symlink: the result tree is runner-writable, and
    following one would let a task project another task's item ids and errors
    into its own dashboard and results manifest.
    """
    path = work_items_path(result_dir)
    try:
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode):
            logging.warning("Refusing non-regular work-item manifest: %s", path)
            return None
        if info.st_size > WORK_ITEMS_MAX_BYTES:
            logging.warning("Refusing oversized work-item manifest: %s", path)
            return None
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:  # OSError plus a deeply nested payload's RecursionError
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        return None
    items = payload["items"][:WORK_ITEMS_MAX_ITEMS]
    if any(not isinstance(entry, dict) for entry in items):
        return None
    return {**payload, "items": items}


def work_items_projection(result_dir: str) -> dict[str, Any] | None:
    """Ordered per-item detail plus progress counts for the result manifest.

    Items keep the runner's original input order (the manifest is written in
    that order), so the published list is directly presentable.
    """
    manifest = read_work_items(result_dir)
    if manifest is None:
        return None
    items = [
        {
            key: entry.get(key)
            for key in ("id", "status", "attempts", "output_path", "error")
        }
        for entry in manifest["items"]
        if entry.get("id")
    ]
    derived = derive_outcome(items)
    reported = manifest.get("outcome")
    if reported is not None and str(reported) != derived:
        logging.warning(
            "Runner reported outcome %r but item states derive %s; publishing the derived outcome",
            reported,
            derived,
        )
    return {
        "outcome": derived,
        "work_items": items,
        "progress": progress_counts(items, current=manifest.get("current_item")),
    }


def progress_counts(items: Sequence[dict[str, Any]], *, current: Any = None) -> dict[str, Any]:
    """Count item states into the progress shape the dashboard renders."""
    counts = {
        "total_items": len(items),
        "completed_items": 0,
        "failed_items": 0,
        "pending_items": 0,
        "running_items": 0,
    }
    for item in items:
        status = str(item.get("status") or "")
        if status == ITEM_SUCCEEDED:
            counts["completed_items"] += 1
        elif status in ITEM_FAILED_STATES:
            counts["failed_items"] += 1
        elif status == "RUNNING":
            counts["running_items"] += 1
        else:
            counts["pending_items"] += 1
    current_item = current or next((item.get("id") for item in items if item.get("status") == "RUNNING"), None)
    counts["current_item"] = current_item
    return counts
