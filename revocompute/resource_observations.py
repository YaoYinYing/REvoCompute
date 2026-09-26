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
from collections.abc import Iterable, Sequence
from typing import Any

from revocompute import resource_model as rm

OBSERVATION_PREFIX = "REVODESIGN_OBSERVATION:"
PROGRESS_PREFIX = "REVODESIGN_PROGRESS:"
TASK_OUTCOME_PREFIX = "REVODESIGN_TASK_OUTCOME:"
WORK_ITEMS_NAME = "work_items.json"

#: Work-item states and task outcomes, as the frozen Runner Protocol defines
#: them.  The server cannot import the runner's module (it lives in the runner
#: tree), so the vocabulary is restated here.  Only the states the server
#: distinguishes are named: ``PENDING``/``RUNNING``/``SUCCEEDED`` and the three
#: failure states.  Anything else — including ``CANCELLED`` — counts as pending,
#: which is the safe reading: neither a success nor a failure.
ITEM_RUNNING = "RUNNING"
ITEM_SUCCEEDED = "SUCCEEDED"
ITEM_FAILED_STATES = ("FAILED_INPUT", "FAILED_RESOURCE", "FAILED_RUNTIME")
TASK_OUTCOMES = ("SUCCESS", "PARTIAL_SUCCESS", "FAILED", "CANCELLED_PARTIAL")

#: Bound on the observation projection embedded in one ``task.json``.  The
#: estimator needs a bounded history, not the whole table; both caps apply so a
#: few enormous rows cannot make the manifest arbitrarily large either.
OBSERVATION_LIMIT = 200
OBSERVATION_BYTES = 256 * 1024
#: Bound on the per-item manifest (``work_items.json``) the server will read.
#: A production task's item count is far below this, and an oversized file is
#: refused rather than parsed, so a hostile result tree cannot exhaust memory.
WORK_ITEMS_MAX_BYTES = 8 * 1024 * 1024


def parse_observation_line(line: str) -> dict[str, Any] | None:
    """Parse one ``REVODESIGN_OBSERVATION:{json}`` line, or return ``None``.

    Runner output is untrusted transport: a malformed line is dropped, never
    raised, so one bad log line cannot end a running task.
    """
    position = line.find(OBSERVATION_PREFIX)
    if position < 0:
        return None
    try:
        payload = json.loads(line[position + len(OBSERVATION_PREFIX) :].strip())
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or not payload.get("runner"):
        return None
    return payload


def parse_progress_line(line: str) -> dict[str, Any] | None:
    """Parse one ``REVODESIGN_PROGRESS:{json}`` line, or return ``None``."""
    position = line.find(PROGRESS_PREFIX)
    if position < 0:
        return None
    try:
        payload = json.loads(line[position + len(PROGRESS_PREFIX) :].strip())
    except (ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) and payload else None


def parse_task_outcome_line(line: str) -> str | None:
    """Parse one ``REVODESIGN_TASK_OUTCOME:<name>`` line, or return ``None``."""
    position = line.find(TASK_OUTCOME_PREFIX)
    if position < 0:
        return None
    outcome = line[position + len(TASK_OUTCOME_PREFIX) :].strip()
    return outcome if outcome in TASK_OUTCOMES else None


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
        observations = [rm.ResourceObservation.from_dict(payload) for payload in map(_observation_payload, rows) if payload]
    except Exception:  # guidance is advisory; the default path must still run
        logging.exception("Could not build resource guidance for runner family %s", runner_family)
        return rm.guidance_for(plans, (), stage=stage)
    return rm.guidance_for(plans, observations, stage=stage)


def observations_for_task(
    runner_family: str,
    *,
    store: Any,
    limit: int = OBSERVATION_LIMIT,
) -> list[dict[str, Any]]:
    """Newest-first bounded observation projection for one runner family."""
    try:
        rows = store.list_resource_observations(runners=(runner_family,), limit=limit)
    except Exception:
        logging.exception("Could not project resource observations for runner family %s", runner_family)
        return []
    bounded: list[dict[str, Any]] = []
    total = 0
    for row in rows:
        payload = _observation_payload(row)
        if payload is None:
            continue
        size = len(json.dumps(payload, sort_keys=True))
        if total + size > OBSERVATION_BYTES:
            break
        total += size
        bounded.append(payload)
    return bounded


def _observation_payload(row: dict[str, Any]) -> dict[str, Any] | None:
    """The stored normalized JSON, minus the server-only tenant attribution."""
    payload: Any = None
    raw = row.get("observation_json")
    if isinstance(raw, str) and raw:
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
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
    treated as "no per-item detail", never as an error.
    """
    path = work_items_path(result_dir)
    try:
        if os.path.getsize(path) > WORK_ITEMS_MAX_BYTES:
            logging.warning("Refusing oversized work-item manifest: %s", path)
            return None
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        return None
    return payload


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
        if isinstance(entry, dict) and entry.get("id")
    ]
    return {
        "outcome": manifest.get("outcome"),
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
        elif status == ITEM_RUNNING:
            counts["running_items"] += 1
        else:
            counts["pending_items"] += 1
    current_item = current or next((item.get("id") for item in items if item.get("status") == ITEM_RUNNING), None)
    counts["current_item"] = current_item
    return counts
