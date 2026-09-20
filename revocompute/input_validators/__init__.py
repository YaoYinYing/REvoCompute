# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Core-owned security validators, one maintained module per format.

The upload path calls :func:`validate_input_file`, which dispatches by file
extension. Each validator is part of reviewed Core code; Runner families
cannot register executable validation hooks inside the trusted preflight
boundary.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass

from revocompute.input_validators import (
    fasta,
    isolated_validation,
    json_file,
    mmcif,
    pdb,
    small_molecule,
    structured_data,
)
from revocompute.input_validators.common import (  # noqa: F401 — re-exported for tests/tools
    CIF_SNIFF_LINES,
    MAX_CIF_ATOMS,
    MAX_CIF_RECORD_LENGTH,
    MAX_FASTA_RECORD_LENGTH,
    MAX_FASTA_SEQUENCES,
    MAX_FASTA_TOTAL_RESIDUES,
    MAX_JSON_BYTES,
    MAX_JSON_DEPTH,
    MAX_JSON_NODES,
    MAX_PDB_LINES,
    MAX_PDB_RECORD_LENGTH,
    PDB_SNIFF_LINES,
    _read_text,
)
from revocompute.input_validators.fasta import (  # noqa: F401 — public API
    validate_a3m,
    validate_chai_entity_fasta,
    validate_fasta,
)
from revocompute.input_validators.json_file import validate_json  # noqa: F401
from revocompute.input_validators.mmcif import validate_mmcif  # noqa: F401
from revocompute.input_validators.pdb import validate_pdb  # noqa: F401
from revocompute.input_validators.profiles import validate_logical_input  # noqa: F401
from revocompute.input_validators.small_molecule import validate_mol2, validate_pdbqt, validate_sdf  # noqa: F401

@dataclass(frozen=True)
class ValidatorSpec:
    function: Callable[[str], str | None]
    isolation: str


# Built-in validators, keyed by lowercase file extension.
_VALIDATORS: dict[str, ValidatorSpec] = {}


def register(kind: str, func: Callable[[str], str | None], *, isolation: str = "safe_inprocess") -> None:
    """Register the built-in validator for one file extension."""
    if isolation not in {"safe_inprocess", "isolated"}:
        raise ValueError(f"Unknown validator isolation class: {isolation}")
    _VALIDATORS[kind] = ValidatorSpec(function=func, isolation=isolation)

def supported_input_formats() -> set[str]:
    """Return format IDs covered by the trusted Core security boundary.

    The upload path fails closed on an unsupported extension, so this is the
    set every task-declared input format must fall inside.
    """
    return {extension.removeprefix(".") for extension in _VALIDATORS}


def validator_isolation(format_name: str) -> str | None:
    """Return the Core parser-isolation class for one format ID."""
    spec = _VALIDATORS.get(f".{format_name.lower().removeprefix('.')}")
    return spec.isolation if spec is not None else None


# Physical-format dialects: one serialization may carry more than one
# scientific dialect. A task role's logical type selects the dialect; the
# plain physical validator stays the default and its alphabet stays strict.
_DIALECTS: dict[tuple[str, str], Callable[[str], str | None]] = {
    ("fasta", "chai_entity_specification"): fasta.validate_chai_entity_fasta,
    ("fa", "chai_entity_specification"): fasta.validate_chai_entity_fasta,
    ("faa", "chai_entity_specification"): fasta.validate_chai_entity_fasta,
}


def validate_input_file(path: str, filename: str, *, logical_type: str | None = None) -> str | None:
    """Dispatch content validation by extension; fail closed when unsupported.

    Pass *logical_type* to select a Core-owned dialect of the same physical
    format; without it the strict default validator for the extension runs.
    """
    kind = os.path.splitext(filename)[1].lower()
    format_name = kind.removeprefix(".")
    if logical_type is not None and (dialect := _DIALECTS.get((format_name, logical_type))) is not None:
        return dialect(path)
    spec = _VALIDATORS.get(kind)
    if spec is None:
        return f"Unsupported input format: {kind or '(none)'}"
    if spec.isolation == "isolated":
        return isolated_validation.validate_in_subprocess(path, format_name)
    return spec.function(path)


register(".fasta", fasta.validate_fasta)
register(".fa", fasta.validate_fasta)
register(".faa", fasta.validate_fasta)
register(".fas", fasta.validate_fasta)
register(".a3m", fasta.validate_a3m)
register(".pdb", pdb.validate_pdb)
register(".cif", mmcif.validate_mmcif)
register(".mmcif", mmcif.validate_mmcif)
register(".json", json_file.validate_json)
register(".sdf", small_molecule.validate_sdf)
register(".mol2", small_molecule.validate_mol2)
register(".pdbqt", small_molecule.validate_pdbqt)
register(".yaml", structured_data.validate_yaml, isolation="isolated")
register(".yml", structured_data.validate_yaml, isolation="isolated")
register(".csv", structured_data.validate_delimited_text)
register(".restraints", structured_data.validate_delimited_text)
register(".pqt", structured_data.validate_parquet)
