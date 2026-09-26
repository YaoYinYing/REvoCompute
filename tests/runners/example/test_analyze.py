# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The Example Runner is the reference for the persistent multi-item lifecycle.

These tests exercise the real family entrypoint (`run.sh` over a `task.json`)
and prove the reference behaviour: one committed directory per FASTA record, a
second invocation that recomputes nothing, and a failing record that leaves the
rest successful. The analyzer's own unit tests stay at the top.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = ROOT / "docker" / "runners"
FAMILY = EXAMPLES / "example"
ANALYZER_PATH = FAMILY / "analyze.py"

# In the image the shared modules sit beside the family script; here they live
# in the sibling `common/` directory, so make both importable.
sys.path.insert(0, str(EXAMPLES / "common"))
SPEC = importlib.util.spec_from_file_location("example_analyzer", ANALYZER_PATH)
assert SPEC and SPEC.loader
analyzer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analyzer)


def test_analyzer_writes_deterministic_sequence_statistics(tmp_path: Path) -> None:
    source = tmp_path / "sequences.fasta"
    source.write_text(">alpha description\nACDA\n>beta\nMXX\n", encoding="utf-8")
    output = tmp_path / "output"

    assert analyzer.main(["--input", str(source), "--output-dir", str(output), "--mass-precision", "3"]) == 0

    with (output / "sequence_statistics.tsv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    assert rows[0] == {
        "sequence_id": "alpha",
        "length": "4",
        "molecular_weight_da": "378.4",
        "aa_composition": '{"A":2,"C":1,"D":1}',
    }
    payload = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert payload["parameters"] == {"mass_precision": 3}
    assert payload["sequence_count"] == 2
    assert payload["total_residues"] == 7
    assert payload["sequences"][1]["aa_composition"] == {"M": 1, "X": 2}


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("ACDE\n", "precedes the first FASTA header"),
        (">empty\n", "contains no residues"),
        (">one\nAC-D\n", "unsupported residue symbols"),
        (">same\nACD\n>same another\nEFG\n", "duplicated"),
    ],
)
def test_analyzer_rejects_invalid_scientific_input(tmp_path: Path, content: str, message: str) -> None:
    source = tmp_path / "invalid.fasta"
    source.write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        analyzer.read_fasta(source)


# ---------------------------------------------------------------------------
# Reference persistent-lifecycle behaviour
# ---------------------------------------------------------------------------


def _task_manifest(tmp_path: Path, records: dict[str, str], *, params: dict | None = None) -> Path:
    source = tmp_path / "input.fasta"
    source.write_text("".join(f">{name}\n{sequence}\n" for name, sequence in records.items()), encoding="utf-8")
    task = tmp_path / "task.json"
    task.write_text(
        json.dumps(
            {
                "version": 4,
                "task_id": "example-task",
                "task_type": "sequence_statistics",
                "inputs": {"sequence": [{"path": str(source), "original_name": "input.fasta"}]},
                "params": params if params is not None else {"mass_precision": 4},
            }
        ),
        encoding="utf-8",
    )
    return task


def _run(tmp_path: Path, task: Path, output: Path) -> subprocess.CompletedProcess[str]:
    environment = {
        **os.environ,
        "TASK_MANIFEST": str(task),
        "TASK_CONTEXT_SRC": str(EXAMPLES / "common" / "task_context.sh"),
        "EXAMPLE_ANALYZER": str(ANALYZER_PATH),
        "EXAMPLE_SHARED_DIR": str(EXAMPLES / "common"),
    }
    return subprocess.run(
        ["bash", str(FAMILY / "run.sh"), "-i", str(task), "-o", str(output)],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def test_reference_runner_commits_one_directory_per_record(tmp_path: Path) -> None:
    """The contract test: a named role and server-resolved parameters only.

    Two records in one FASTA file are two work items, each committed into its
    own directory, and the resolved ``mass_precision`` reaches every artifact.
    """
    task = _task_manifest(tmp_path, {"alpha": "ACDE", "beta": "MNPQ"})
    output = tmp_path / "output"

    completed = _run(tmp_path, task, output)

    assert completed.returncode == 0, completed.stderr
    assert "REVODESIGN_STAGE:model_loading" in completed.stdout
    assert "REVODESIGN_TASK_OUTCOME:SUCCESS" in completed.stdout
    for name, length in (("alpha", 4), ("beta", 4)):
        summary = json.loads((output / name / "summary.json").read_text(encoding="utf-8"))
        assert summary["sequence_count"] == 1
        assert summary["total_residues"] == length
        assert summary["sequences"][0]["sequence_id"] == name
        assert summary["parameters"] == {"mass_precision": 4}
        assert (output / name / "sequence_statistics.tsv").is_file()
    # Durable per-item state, in original input order, and the task rollup.
    manifest = json.loads((output / "work_items.json").read_text(encoding="utf-8"))
    assert manifest["outcome"] == "SUCCESS"
    assert [entry["id"] for entry in manifest["items"]] == ["alpha", "beta"]
    assert all(entry["status"] == "SUCCEEDED" for entry in manifest["items"])
    rollup = json.loads((output / "task_summary.json").read_text(encoding="utf-8"))
    assert rollup["sequence_count"] == 2
    assert rollup["total_residues"] == 8
    assert not (output / ".tmp").exists()


def test_second_invocation_does_not_recompute_committed_items(tmp_path: Path) -> None:
    """Resume: committed items are skipped, so a restarted worker finishes fast."""
    task = _task_manifest(tmp_path, {"alpha": "ACDE", "beta": "MNPQ", "gamma": "WY"})
    output = tmp_path / "output"
    assert _run(tmp_path, task, output).returncode == 0

    committed = output / "alpha"
    marker = committed / "sequence_statistics.tsv"
    touched = marker.stat().st_mtime_ns
    resumed = _run(tmp_path, task, output)

    assert resumed.returncode == 0, resumed.stderr
    assert "REVODESIGN_TASK_OUTCOME:SUCCESS" in resumed.stdout
    # Nothing reloaded the runtime and nothing rewrote a committed artifact.
    assert "REVODESIGN_STAGE:model_loading" not in resumed.stdout
    assert marker.stat().st_mtime_ns == touched
    manifest = json.loads((output / "work_items.json").read_text(encoding="utf-8"))
    assert all(entry["attempts"] == 1 for entry in manifest["items"])


def test_failing_record_leaves_the_rest_successful(tmp_path: Path) -> None:
    """Partial success: one over-long record fails alone; the others commit.

    The FASTA framing is valid and the transport layer accepts it, but one
    record exceeds the runner's declared residue envelope, so that single work
    item is ``FAILED_INPUT`` while the task reports ``PARTIAL_SUCCESS``.
    """
    task = _task_manifest(tmp_path, {"alpha": "ACDE", "beta": "A" * 4097, "gamma": "WY"})
    output = tmp_path / "output"

    completed = _run(tmp_path, task, output)

    assert completed.returncode == 0, completed.stderr
    assert "REVODESIGN_TASK_OUTCOME:PARTIAL_SUCCESS" in completed.stdout
    manifest = json.loads((output / "work_items.json").read_text(encoding="utf-8"))
    states = {entry["id"]: entry["status"] for entry in manifest["items"]}
    assert states["beta"] == "FAILED_INPUT"
    assert states["alpha"] == states["gamma"] == "SUCCEEDED"
    assert not (output / "beta").exists()
    assert (output / "gamma" / "summary.json").is_file()
    rollup = json.loads((output / "task_summary.json").read_text(encoding="utf-8"))
    assert rollup["succeeded_count"] == 2
    assert rollup["failed_count"] == 1
