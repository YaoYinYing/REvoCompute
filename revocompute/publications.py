# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Read-only operator view of result-publication states.

The publication anchor lives in server-owned state, so "is this result still the
one Core published?" is answerable without trusting the result tree.  This
command classifies every terminal task with that same reader and reports the
quarantined ones with their reason -- the operator-facing half of the rollout
rule for results that predate the anchor.

It reports; it never publishes.  A quarantined result is re-published the
ordinary way, by running the task again.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass

from revocompute.config import ComputeConfig
from revocompute.db import TaskDatabase
from revocompute.storage import PUBLICATION_AVAILABLE, PUBLICATION_QUARANTINE_STATES, StorageResolver

#: Publication states of a terminal task, in reporting order.  A state is either
#: available or quarantined; the two sets partition every reported row.
_TERMINAL_RESULT_STATUSES = {"finished", "failed"}


@dataclass(frozen=True, slots=True)
class PublicationEntry:
    task_id: str
    task_type: str
    status: str
    publication: str
    quarantined: bool


def collect_publications(task_store: TaskDatabase, storage: StorageResolver) -> list[PublicationEntry]:
    """Classify every terminal task's result through the canonical reader."""
    entries: list[PublicationEntry] = []
    for task in task_store.list_tasks():
        status = str(task.get("status") or "").strip().lower()
        if status not in _TERMINAL_RESULT_STATUSES:
            continue
        state = storage.publication_state(task)
        entries.append(
            PublicationEntry(
                task_id=str(task.get("md5sum") or ""),
                task_type=str(task.get("task_type") or ""),
                status=status,
                publication=state,
                quarantined=state in PUBLICATION_QUARANTINE_STATES,
            )
        )
    entries.sort(key=lambda entry: (not entry.quarantined, entry.task_id))
    return entries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="revocompute-publications")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--quarantined", action="store_true", help="report quarantined results only")
    args = parser.parse_args(argv)
    config = ComputeConfig.from_env()
    task_store = TaskDatabase(config.db_path)
    try:
        entries = collect_publications(
            task_store, StorageResolver(config.results_folder, config.workspace_folder, task_store)
        )
    finally:
        task_store.engine.dispose()
    reported = [entry for entry in entries if entry.quarantined] if args.quarantined else entries
    if args.as_json:
        print(json.dumps({"publications": [asdict(entry) for entry in reported]}, indent=2, sort_keys=True))
        return 0
    if not reported:
        print("No result publications are quarantined." if args.quarantined else "No terminal task results found.")
        return 0
    available = sum(1 for entry in entries if entry.publication == PUBLICATION_AVAILABLE)
    for entry in reported:
        print(f"{entry.task_id}: {entry.publication} status={entry.status} task_type={entry.task_type}")
    if not args.quarantined:
        print(f"\n{len(entries)} terminal result(s): {available} available, {len(entries) - available} quarantined.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
