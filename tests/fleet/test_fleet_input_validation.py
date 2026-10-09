# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations
import gzip
import io
import json
import random
from dataclasses import replace
from pathlib import Path
import pytest
import conftest
from conftest import _load_fleet_module, _test_client_auth
from revocompute.input_validators import MAX_CIF_ATOMS
from revocompute.input_validators import (
    MAX_CIF_RECORD_LENGTH,
    MAX_FASTA_RECORD_LENGTH,
    MAX_FASTA_SEQUENCES,
    MAX_FASTA_TOTAL_RESIDUES,
    MAX_JSON_DEPTH,
    MAX_JSON_NODES,
    MAX_PDB_LINES,
    MAX_PDB_RECORD_LENGTH,
    supported_input_formats,
    validate_a3m,
    validate_fasta,
    validate_input_file,
    validate_json,
    validate_logical_input,
    validate_mmcif,
    validate_pdb,
)
from revocompute.task_types import TaskInputRole, discover_plugins, list_types
ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = ROOT


def test_every_production_task_format_has_a_core_security_validator():
    # Discovery is what populates the contributions registry the task list reads;
    # without it this test only passes when another test happened to run first.
    discover_plugins(str(REPO_ROOT / "docker" / "runners"))
    declared = {format_name for task_type in list_types() for role in task_type.inputs for format_name in role.formats}

    assert declared <= supported_input_formats()
