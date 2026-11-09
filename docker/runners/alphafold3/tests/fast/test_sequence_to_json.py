# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
import sys
from pathlib import Path

RUNNER_DIR = Path(__file__).resolve().parents[2]
if str(RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(RUNNER_DIR))

from sequence_to_json import main  # noqa: E402


def _convert(tmp_path: Path, content: str, seed: str = "1") -> tuple[int, Path]:
    source = tmp_path / "query.fasta"
    source.write_text(content, encoding="utf-8")
    output = tmp_path / "nested" / "af3_input.json"
    return main([str(source), str(output), seed]), output


def test_converter_emits_one_protein_chain_with_empty_msas_and_templates(tmp_path):
    code, output = _convert(tmp_path, ">query\nMKT AYI\nAK\n", seed="7")

    assert code == 0
    assert output.read_text(encoding="utf-8").endswith("\n")
    assert json.loads(output.read_text(encoding="utf-8")) == {
        "name": "query",
        "modelSeeds": [7],
        "sequences": [
            {
                "protein": {
                    "id": "A",
                    "sequence": "MKTAYIAK",
                    "unpairedMsa": "",
                    "pairedMsa": "",
                    "templates": [],
                }
            }
        ],
        "dialect": "alphafold3",
        "version": 1,
    }


def test_converter_output_is_byte_identical_across_runs(tmp_path):
    source = tmp_path / "query.fasta"
    source.write_text(">query\nMKTAYIAK\n", encoding="utf-8")
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"

    assert main([str(source), str(first), "3"]) == 0
    assert main([str(source), str(second), "3"]) == 0

    assert first.read_bytes() == second.read_bytes()


def test_converter_rejects_multiple_records(tmp_path):
    code, output = _convert(tmp_path, ">one\nMKT\n>two\nAYI\n")

    assert code != 0
    assert not output.exists()


def test_converter_rejects_an_empty_sequence(tmp_path):
    code, output = _convert(tmp_path, ">empty\n\n")

    assert code != 0
    assert not output.exists()


def test_converter_rejects_input_without_a_record(tmp_path):
    code, output = _convert(tmp_path, "")

    assert code != 0
    assert not output.exists()
