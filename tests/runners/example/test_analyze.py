# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import csv
import importlib.util
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[3]
ANALYZER_PATH = ROOT / "docker" / "runners" / "example" / "analyze.py"
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


def test_runner_consumes_named_input_and_resolved_parameter(tmp_path: Path) -> None:
    source = tmp_path / "input.fasta"
    source.write_text(">reference\nACDE\n", encoding="utf-8")
    task = tmp_path / "task.json"
    task.write_text(
        json.dumps({"inputs": {"sequence": [{"path": str(source)}]}, "params": {"mass_precision": 4}}),
        encoding="utf-8",
    )
    output = tmp_path / "output"
    family = ROOT / "docker" / "runners" / "example"
    environment = {
        **os.environ,
        "TASK_MANIFEST": str(task),
        "TASK_CONTEXT_SRC": str(ROOT / "docker" / "runners" / "common" / "task_context.sh"),
        "EXAMPLE_ANALYZER": str(family / "analyze.py"),
    }

    completed = subprocess.run(
        ["bash", str(family / "run.sh"), "-i", str(task), "-o", str(output)],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "REVODESIGN_STAGE:sequence_statistics" in completed.stdout
    assert (output / "task_finished").is_file()
    payload = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert payload["parameters"] == {"mass_precision": 4}
