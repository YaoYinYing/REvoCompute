# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Shared helpers for a persistent multi-work-item Runner entrypoint.

Standard library only — a runner image must not need NumPy or a resource model
to execute work items (see ``persistent_runner``). A family entrypoint uses this
to turn its own named input role into work items and its immutable ``task.json``
into the config ``persistent_runner.execute_task`` consumes::

    manifest = read_task_manifest(args.task_manifest)
    items, payload = sequence_work_items(manifest, "sequence")
    execute_task(build_config(manifest, "simplefold", items, payload),
                 SimpleFoldPlugin(payload["params"]), output_dir=args.output_dir)
"""

from __future__ import annotations

import json
import os
from pathlib import Path

RESIDUE_ALPHABET = frozenset("ACDEFGHIKLMNPQRSTVWYX")


class InputError(ValueError):
    """The task's declared input cannot be turned into work items."""


def read_task_manifest(path: str | os.PathLike) -> dict:
    with open(path, encoding="utf-8") as handle:
        manifest = json.load(handle)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("inputs"), dict):
        raise InputError("Task manifest is not a runner-protocol manifest")
    return manifest


def role_files(manifest: dict, role: str) -> list[dict]:
    files = manifest.get("inputs", {}).get(role)
    if not isinstance(files, list):
        raise InputError(f"Task manifest has no input role {role!r}")
    return files


def role_paths(manifest: dict, role: str) -> list[str]:
    return [str(entry["path"]) for entry in role_files(manifest, role)]


def read_fasta_records(path: str | os.PathLike) -> list[tuple[str, str]]:
    """Read non-aligned protein FASTA records, preserving header order.

    Returns the header's first token as the record identifier and the joined,
    upper-cased sequence. Identifiers are not required to be unique here: the
    caller decides whether a duplicate is fatal, because a duplicate that
    normalizes to the same output directory is.
    """
    records: list[tuple[str, str]] = []
    identifier: str | None = None
    sequence: list[str] = []

    def finish() -> None:
        if identifier is None:
            return
        joined = "".join(sequence).replace(" ", "").upper()
        if not joined:
            raise InputError(f"FASTA record {identifier!r} contains no residues")
        invalid = sorted(set(joined) - RESIDUE_ALPHABET)
        if invalid:
            raise InputError(f"FASTA record {identifier!r} contains unsupported residues: {''.join(invalid)}")
        records.append((identifier, joined))

    for line_number, raw_line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(">"):
            finish()
            header = line[1:].strip()
            if not header:
                raise InputError(f"FASTA header on line {line_number} is empty")
            identifier = header.split()[0]
            sequence = []
        elif identifier is None:
            raise InputError(f"Sequence data on line {line_number} precedes the first FASTA header")
        else:
            sequence.append("".join(line.split()))
    finish()
    if not records:
        raise InputError("FASTA input contains no records")
    return records


def sequence_work_items(manifest: dict, role: str, *, max_length: int, extensions: tuple[str, ...] = ()) -> tuple[list[dict], dict]:
    """Turn one sequence FASTA into work items and a payload of shared facts.

    One FASTA file may carry many sequences: the file's role cardinality is about
    files, while each record is an independently executable work item. The
    ``payload`` carries what every item shares, so a plugin does not re-read the
    manifest.
    """
    files = role_files(manifest, role)
    if len(files) != 1:
        raise InputError(f"Task input role {role!r} must contain exactly one FASTA file")
    entry = files[0]
    path = str(entry["path"])
    if extensions and Path(path).suffix.lower() not in extensions:
        raise InputError(f"Task input role {role!r} must be one of: {', '.join(extensions)}")
    records = read_fasta_records(path)
    items = [
        {"id": identifier, "order": index, "length": len(sequence), "sequence": sequence}
        for index, (identifier, sequence) in enumerate(records)
    ]
    too_long = [item["id"] for item in items if item["length"] > max_length]
    if too_long:
        raise InputError(
            f"Sequence {too_long[0]!r} has {next(item['length'] for item in items if item['id'] == too_long[0])} "
            f"residues; the supported maximum is {max_length}"
        )
    payload = {
        "params": dict(manifest.get("params") or {}),
        "task_id": str(manifest.get("task_id") or ""),
        "task_type": str(manifest.get("task_type") or ""),
        "input_sha256": str(entry.get("sha256") or ""),
        "input_name": str(entry.get("original_name") or Path(path).name),
        "sequence_count": len(items),
    }
    return items, payload


def build_config(
    manifest: dict, runner: str, items: list[dict], payload: dict, *, execution_defaults: dict | None = None
) -> dict:
    """Assemble the ``persistent_runner.execute_task`` config from ``task.json``.

    The server supplies ``execution``, ``execution_queue``,
    ``resource_adaptation``, ``resource_guidance``, and ``observations``; a
    missing block means the runner's conservative default, so an older task
    manifest still runs unchanged.  ``execution_defaults`` fills a key the
    manifest omits with the runner's own conservative value — the runner owns
    how many attempts its declared fallbacks have earned.
    """
    return {
        "task_id": payload.get("task_id") or manifest.get("task_id") or "",
        "runner": runner,
        "items": list(items),
        "execution": {**(execution_defaults or {}), **dict(manifest.get("execution") or {})},
        "execution_queue": dict(manifest.get("execution_queue") or {}),
        "resource_adaptation": dict(manifest.get("resource_adaptation") or {}),
        "resource_guidance": dict(manifest.get("resource_guidance") or {}),
        "observations": list(manifest.get("observations") or []),
    }


def _self_check() -> None:
    import tempfile

    fasta = ">alpha first\nACDE\n>beta\nMXXF\n"
    with tempfile.TemporaryDirectory() as root:
        path = os.path.join(root, "in.fasta")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(fasta)
        manifest = {
            "task_id": "t",
            "task_type": "x",
            "params": {"seed": 1},
            "inputs": {"sequence": [{"path": path, "original_name": "in.fasta"}]},
            "execution": {"batch_size": 1},
        }
        items, payload = sequence_work_items(manifest, "sequence", max_length=10)
        assert [item["id"] for item in items] == ["alpha", "beta"]
        assert [item["length"] for item in items] == [4, 4]
        assert payload["sequence_count"] == 2
        config = build_config(manifest, "fake", items, payload, execution_defaults={"max_item_attempts": 2})
        assert config["execution"] == {"batch_size": 1, "max_item_attempts": 2}
        assert config["resource_adaptation"] == {}
        try:
            sequence_work_items(manifest, "sequence", max_length=3)
        except InputError as error:
            assert "supported maximum is 3" in str(error)
        else:  # pragma: no cover - regression guard
            raise AssertionError("an over-long record must be rejected")


if __name__ == "__main__":  # pragma: no cover - runnable self-check
    _self_check()
    print("work_items self-check passed")
