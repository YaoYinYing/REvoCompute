# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
FAMILY = ROOT / "docker/runners/molprobity"


def _load_validate():
    spec = importlib.util.spec_from_file_location("molprobity_validate", FAMILY / "validate.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_summary_reader_uses_the_single_upstream_summary_block() -> None:
    validate = _load_validate()
    payload = {
        "summary_results": {"": {"clashscore": 4.23, "num_clashes": 19}},
        "flat_results": [],
    }
    assert validate._summary(payload, "clashscore2") == {"clashscore": 4.23, "num_clashes": 19}


def test_summary_reader_fails_closed_on_an_empty_report() -> None:
    validate = _load_validate()
    with pytest.raises(SystemExit, match="produced no summary"):
        validate._summary({"summary_results": {}, "flat_results": []}, "ramalyze")


def test_flat_rows_keep_the_upstream_residue_identity_and_analysis() -> None:
    validate = _load_validate()
    payload = {
        "flat_results": [
            {
                "chain_id": "A",
                "resseq": "1002",
                "icode": " ",
                "resname": "PRO",
                "altloc": "",
                "evaluation": "Favored",
                "score": 26.1,
                "chi_angles": [35.9, 322.2, 25.3, None],
                "outlier": False,
            }
        ]
    }
    rows = validate._flat_rows(payload, "rotalyze")
    assert rows[0]["analysis"] == "rotalyze"
    assert rows[0]["chain_id"] == "A"
    assert rows[0]["resseq"] == "1002"
    assert rows[0]["rotamer_name"] == ""
    assert json.loads(rows[0]["chi_angles"])[0] == 35.9
    assert rows[0]["outlier"] is False


def test_declared_residue_columns_match_the_written_table() -> None:
    validate = _load_validate()
    rows = validate._flat_rows({"flat_results": [{"chain_id": "A", "resseq": "1"}]}, "ramalyze")
    header = list(rows[0])
    assert header == list(validate.RESIDUE_FIELDS)


def test_residue_table_is_writable_csv(tmp_path: Path) -> None:
    validate = _load_validate()
    rows = validate._flat_rows({"flat_results": [{"chain_id": "A", "resseq": "1", "resname": "GLY"}]}, "ramalyze")
    with (tmp_path / "validation_residues.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=validate.RESIDUE_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    with (tmp_path / "validation_residues.csv").open(encoding="utf-8", newline="") as handle:
        written = list(csv.DictReader(handle))
    assert written[0]["analysis"] == "ramalyze"
    assert written[0]["resname"] == "GLY"
