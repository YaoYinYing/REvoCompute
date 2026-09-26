# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Deterministic, dependency-free protein sequence statistics.

The family runs the shared persistent lifecycle
(``common/persistent_runner.py``), so it also carries the plugin surface that
lifecycle calls: ``initialize_runtime`` once per task, ``run_item`` per work
item, and ``finalize_task`` for the task-level rollup. The science itself is
unchanged and stays usable on its own through ``main``.
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
import os
from pathlib import Path
import platform
import resource
import sys
from typing import Iterable


# Average residue masses in a polypeptide chain, in daltons. Molecular weight
# adds one water molecule for the termini. Ambiguous symbols use constituent
# averages; X uses the unweighted average of the 20 canonical residues.
RESIDUE_MASSES = {
    "A": 71.0788,
    "C": 103.1388,
    "D": 115.0886,
    "E": 129.1155,
    "F": 147.1766,
    "G": 57.0519,
    "H": 137.1411,
    "I": 113.1594,
    "K": 128.1741,
    "L": 113.1594,
    "M": 131.1926,
    "N": 114.1038,
    "P": 97.1167,
    "Q": 128.1307,
    "R": 156.1875,
    "S": 87.0782,
    "T": 101.1051,
    "V": 99.1326,
    "W": 186.2132,
    "Y": 163.1760,
    "U": 150.0388,
    "O": 237.3018,
}
RESIDUE_MASSES["B"] = (RESIDUE_MASSES["D"] + RESIDUE_MASSES["N"]) / 2
RESIDUE_MASSES["Z"] = (RESIDUE_MASSES["E"] + RESIDUE_MASSES["Q"]) / 2
RESIDUE_MASSES["J"] = (RESIDUE_MASSES["I"] + RESIDUE_MASSES["L"]) / 2
RESIDUE_MASSES["X"] = sum(RESIDUE_MASSES[code] for code in "ACDEFGHIKLMNPQRSTVWY") / 20
WATER_MASS = 18.01528


def read_fasta(path: Path) -> list[tuple[str, str]]:
    """Read non-aligned protein FASTA records and return stable record IDs."""
    records: list[tuple[str, str]] = []
    identifier: str | None = None
    sequence: list[str] = []
    seen_ids: set[str] = set()

    def finish_record() -> None:
        if identifier is None:
            return
        joined = "".join(sequence).replace(" ", "").upper()
        if not joined:
            raise ValueError(f"FASTA record {identifier!r} contains no residues")
        unsupported = sorted(set(joined) - set(RESIDUE_MASSES))
        if unsupported:
            symbols = "".join(unsupported)
            raise ValueError(f"FASTA record {identifier!r} contains unsupported residue symbols: {symbols}")
        records.append((identifier, joined))

    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(">"):
            finish_record()
            header = line[1:].strip()
            if not header:
                raise ValueError(f"FASTA header on line {line_number} has no identifier")
            identifier = header.split()[0]
            if identifier in seen_ids:
                raise ValueError(f"FASTA identifier {identifier!r} is duplicated")
            seen_ids.add(identifier)
            sequence = []
        elif identifier is None:
            raise ValueError(f"Sequence data on line {line_number} precedes the first FASTA header")
        else:
            sequence.append("".join(line.split()))
    finish_record()
    if not records:
        raise ValueError("FASTA input contains no records")
    return records


def sequence_statistics(identifier: str, sequence: str, *, mass_precision: int) -> dict[str, object]:
    counts = Counter(sequence)
    composition = {code: counts[code] for code in sorted(counts)}
    molecular_weight = round(WATER_MASS + sum(RESIDUE_MASSES[code] for code in sequence), mass_precision)
    return {
        "sequence_id": identifier,
        "length": len(sequence),
        "molecular_weight_da": molecular_weight,
        "aa_composition": composition,
    }


def write_results(output_dir: Path, statistics: Iterable[dict[str, object]], *, mass_precision: int) -> None:
    rows = list(statistics)
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "sequence_statistics.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("sequence_id", "length", "molecular_weight_da", "aa_composition"),
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            composition = json.dumps(row["aa_composition"], sort_keys=True, separators=(",", ":"))
            writer.writerow({**row, "aa_composition": composition})
    lengths = [int(row["length"]) for row in rows]
    summary = {
        "schema_version": 1,
        "parameters": {"mass_precision": mass_precision},
        "sequence_count": len(rows),
        "total_residues": sum(lengths),
        "minimum_length": min(lengths),
        "maximum_length": max(lengths),
        "sequences": rows,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _residues(summary: dict | None) -> int:
    """Residue total of one committed item summary, or 0 when unreadable."""
    try:
        return int(summary["total_residues"])  # type: ignore[index]
    except (KeyError, TypeError, ValueError):
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Single-FASTA statistics (analyze.py --input ... --output-dir ...)")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--mass-precision", type=int, choices=range(0, 7), default=2)
    args = parser.parse_args(argv)
    records = read_fasta(args.input)
    statistics = [
        sequence_statistics(identifier, sequence, mass_precision=args.mass_precision)
        for identifier, sequence in records
    ]
    write_results(args.output_dir, statistics, mass_precision=args.mass_precision)
    return 0


# ---------------------------------------------------------------------------
# Persistent multi-work-item execution
# ---------------------------------------------------------------------------

# Runner-owned imports live below the analyzer so a missing shared module
# breaks the persistent path with a clear error instead of the unit-test import.
from persistent_runner import (  # noqa: E402
    FAILED_INPUT,
    FAILED_RUNTIME,
    OUTCOME_SUCCESS,
    PARTIAL_SUCCESS,
    SUCCESS,
    WorkItemError,
    execute_task,
)
from work_items import build_config, read_task_manifest, record_problem, sequence_work_items  # noqa: E402

#: The reference runtime is the analyzer's own in-memory tables, so it is
#: loaded once and stands in for a model that would otherwise be reloaded. The
#: fingerprint names the interpreter because the tables are Python data.
RUNTIME_FINGERPRINT = f"analyze-py3-{platform.python_version()}"

#: Per-item supported maximum. The FASTA reader accepts what the transport
#: layer permits; the runner declares what *it* can compute, and a record beyond
#: it fails that item alone with ``FAILED_INPUT``. A model-backed family
#: replaces this with its upstream envelope (SimpleFold supports 1022 residues).
MAX_ITEM_RESIDUES = 4096


class SequenceStatisticsPlugin:
    """The plugin surface ``persistent_runner.execute_task`` calls.

    The example deliberately holds no model. ``initialize_runtime`` builds the
    per-task tables once; ``run_item`` analyzes the one record it was given into
    its private staging directory. A GPU runner replaces those two with the real
    model and reports the framework's own memory statistics from ``run_item``.
    """

    runner = "example"
    runner_version = "1"
    model_revision = "sequence-statistics-v1"
    runtime_fingerprint = RUNTIME_FINGERPRINT

    def __init__(self, params: dict) -> None:
        self.params = dict(params)

    # -- lifecycle ----------------------------------------------------------

    def initialize_runtime(self, execution: dict) -> dict:
        """Build the runtime once per task. It is not rebuilt per item."""
        runtime = {
            "residue_masses": dict(RESIDUE_MASSES),
            "water_mass": WATER_MASS,
            "mass_precision": int(self.params["mass_precision"]),
        }
        # The runtime is ready, so every remaining second is item execution.
        # The shared lifecycle emitted `model_loading` before calling us; this
        # closes that stage and opens the one the task declares for analysis.
        print("REVODESIGN_STAGE:sequence_statistics", flush=True)
        return runtime

    def finalize(self, runtime: dict) -> None:
        runtime.clear()

    def finalize_task(self, output_dir: str, manifest: dict) -> None:
        """Write the task-level rollup over the committed items.

        Every item's numbers come from its committed ``<item>/summary.json``, so
        the rollup counts what was actually accepted, in original input order,
        rather than what this process happened to execute. A committed summary
        this process cannot read — truncated by a crash, written by an older
        schema — is counted as missing rather than taking the whole rollup down
        after every item already succeeded.
        """
        summaries: dict[str, dict] = {}
        for entry in manifest["items"]:
            if entry["status"] != "SUCCEEDED":
                continue
            try:
                with open(os.path.join(output_dir, entry["name"], "summary.json"), encoding="utf-8") as handle:
                    summaries[entry["name"]] = json.load(handle)
            except (OSError, json.JSONDecodeError):
                pass
        rollup = {
            "schema_version": 1,
            "task_id": manifest.get("task_id") or "",
            "sequence_count": len(manifest["items"]),
            "succeeded_count": len(summaries),
            "failed_count": len(manifest["items"]) - len(summaries),
            "total_residues": sum(_residues(summary) for summary in summaries.values()),
            "items": [
                {
                    "sequence_id": entry["id"],
                    "status": entry["status"],
                    "attempts": entry["attempts"],
                    "output_path": entry["output_path"],
                    "total_residues": _residues(summaries.get(entry["name"])),
                }
                for entry in manifest["items"]
            ],
        }
        (Path(output_dir) / "task_summary.json").write_text(
            json.dumps(rollup, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    # -- measurement --------------------------------------------------------

    def device_profile(self, runtime: dict) -> dict:
        """The reference has no accelerator. A GPU runner queries the device here.

        This is the ``DeviceObserver`` half of the measurement contract: the
        facts the server's estimator cannot obtain on its own.
        """
        return {
            "vendor": "cpu",
            "model": platform.machine() or "unknown",
            "compute_capability": "",
            "total_vram_mb": 1,
            "mig_profile": "",
        }

    def runtime_usage(self, runtime: dict) -> tuple[int, int, int]:
        """``(peak, current, reserved)`` MiB, from the process that owns the work."""
        peak_mb = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024)
        return peak_mb, peak_mb, 0

    def available_vram_mb(self, runtime: dict) -> int:
        """No accelerator, so there is no device envelope to plan against."""
        return 0

    # -- one work item ------------------------------------------------------

    def run_item(self, runtime: dict, payload: dict, adjustments: dict, work_dir: str, execution: dict) -> tuple:
        """Analyze one record into its private staging directory.

        Returning a non-success outcome classifies a bounded failure; raising
        :class:`WorkItemError` classifies it explicitly. Either way only this
        item is affected — ``persistent_runner`` fails the item and continues.

        ``adjustments`` are execution-only resource settings. The requested
        science (here, the resolved ``mass_precision``) is read from the
        runtime, never from a fallback plan.
        """
        sequence = str(payload.get("sequence") or "")
        # The analyzer has an average mass for every ambiguous symbol, so its
        # per-item envelope is its own mass table rather than the canonical 20.
        problem = record_problem(sequence, max_length=MAX_ITEM_RESIDUES, alphabet=RESIDUE_MASSES)
        if problem:
            raise WorkItemError(FAILED_INPUT, problem)
        identifier = str(payload.get("id") or "item")
        precision = int(runtime["mass_precision"])
        write_results(
            Path(work_dir),
            [sequence_statistics(identifier, sequence, mass_precision=precision)],
            mass_precision=precision,
        )
        peak_mb, _, _ = self.runtime_usage(runtime)
        return OUTCOME_SUCCESS, peak_mb, 0, peak_mb, ""

    def validate_item(self, work_dir: str, payload: dict, adjustments: dict) -> None:
        """Commit only when both declared artifacts exist and are non-empty."""
        for filename in ("sequence_statistics.tsv", "summary.json"):
            path = os.path.join(work_dir, filename)
            if not os.path.isfile(path) or os.path.getsize(path) == 0:
                raise WorkItemError(FAILED_RUNTIME, f"work item produced no {filename}")


def run_task(task_manifest: Path, output_dir: Path) -> int:
    """Entrypoint for ``run.sh``: one FASTA record, one work item."""
    manifest = read_task_manifest(task_manifest)
    params = dict(manifest.get("params") or {})
    if "mass_precision" not in params:
        print("task.json carries no resolved mass_precision parameter", file=sys.stderr)
        return 2
    items, payload = sequence_work_items(manifest, "sequence")
    config = build_config(manifest, SequenceStatisticsPlugin.runner, items, payload)
    result = execute_task(config, SequenceStatisticsPlugin(params), output_dir=str(output_dir))
    if result["outcome"] in (SUCCESS, PARTIAL_SUCCESS):
        return 0
    print(f"task outcome: {result['outcome']}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    argv = sys.argv[1:]
    if argv and argv[0] == "task":
        raise SystemExit(run_task(Path(argv[1]), Path(argv[2])))
    raise SystemExit(main())
