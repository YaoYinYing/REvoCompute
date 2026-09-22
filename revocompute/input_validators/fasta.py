# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""FASTA / A3M content validators.

``validate_fasta`` and ``validate_a3m`` enforce the strict residue alphabets of
plain protein serialization. Chai-1 reuses FASTA framing for a richer entity
specification (protein, RNA, DNA, ligand SMILES, glycan), whose sequences carry
modification brackets and SMILES punctuation that a protein alphabet rejects.
``validate_chai_entity_fasta`` is that dialect: it checks framing and obvious
malformation and leaves canonical semantic parsing to Chai itself.
"""

from __future__ import annotations

import string

from revocompute.input_validators.common import (
    _A3M_ALPHABET,
    _FASTA_ALPHABET,
    _FASTA_WHITESPACE,
    MAX_FASTA_RECORD_LENGTH,
    MAX_FASTA_SEQUENCES,
    MAX_FASTA_TOTAL_RESIDUES,
    _read_text,
)

_CHAI_ENTITY_TYPES = frozenset({"protein", "ligand", "rna", "dna", "glycan"})
# Upstream accepts RNA/DNA modification blocks and ligand SMILES punctuation.
_CHAI_POLYMER_CHARS = frozenset(string.ascii_letters + string.digits + "()[]")
_CHAI_LIGAND_CHARS = frozenset(string.ascii_letters + string.digits + ".-+=#$%:/\\[]()<>@")
_OPENING, _CLOSING = "([", ")]"


def _chai_modified_polymer(sequence: str) -> str | None:
    """Return an error if a Chai protein/RNA/DNA sequence is malformed.

    Modification blocks are ``(ASP)``/``[NH2]`` style and must be balanced and
    non-empty; bare residues outside blocks must be single letters.
    """
    open_bracket: str | None = None
    block = ""
    for char in sequence:
        if char in _OPENING:
            if open_bracket is not None:
                return "Chai entity FASTA has nested modification brackets"
            open_bracket = char
            block = ""
        elif char in _CLOSING:
            if open_bracket is None:
                return "Chai entity FASTA has an unopened modification bracket"
            if _OPENING.index(open_bracket) != _CLOSING.index(char):
                return "Chai entity FASTA has mismatched modification brackets"
            if len(block) < 2:
                return "Chai entity FASTA has an empty modification block"
            open_bracket = None
        elif open_bracket is not None:
            block += char
        elif not char.isalpha():
            return f"Chai entity FASTA sequence contains invalid character {char!r}"
        if char not in _CHAI_POLYMER_CHARS:
            return f"Chai entity FASTA sequence contains invalid character {char!r}"
    if open_bracket is not None:
        return "Chai entity FASTA has an unclosed modification bracket"
    return None


def _chai_entity_sequence(entity_type: str, sequence: str) -> str | None:
    if entity_type in {"protein", "rna", "dna"}:
        return _chai_modified_polymer(sequence)
    # Ligand SMILES and glycan strings have no residue alphabet; reject only
    # characters no upstream entity type accepts, plus unbalanced brackets.
    if not any(char.isalpha() for char in sequence):
        return f"Chai {entity_type} record must contain at least one letter"
    unbalanced = 0
    for char in sequence:
        if char in _OPENING:
            unbalanced += 1
        elif char in _CLOSING:
            unbalanced -= 1
            if unbalanced < 0:
                return f"Chai {entity_type} record has an unopened bracket"
    if unbalanced:
        return f"Chai {entity_type} record has an unclosed bracket"
    for char in sequence:
        if char not in _CHAI_LIGAND_CHARS:
            return f"Chai {entity_type} record contains invalid character {char!r}"
    return None


def validate_chai_entity_fasta(path: str) -> str | None:
    """Return an error if *path* is not a plausible Chai entity FASTA."""
    text, error = _read_text(path, kind="Chai entity FASTA")
    if error is not None:
        return error
    sequences = 0
    total_residues = 0
    pending_entity_type: str | None = None
    sequence_lines: list[str] = []

    def check_record() -> str | None:
        record = "".join(sequence_lines)
        if not record:
            return "Chai entity FASTA contains an empty record"
        assert pending_entity_type is not None
        return _chai_entity_sequence(pending_entity_type, record)

    for line in text.splitlines():
        if len(line) > MAX_FASTA_RECORD_LENGTH:
            return f"FASTA file contains a record longer than {MAX_FASTA_RECORD_LENGTH} characters"
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(">"):
            if pending_entity_type is not None:
                if error := check_record():
                    return error
                sequence_lines = []
            sequences += 1
            if sequences > MAX_FASTA_SEQUENCES:
                return f"FASTA file contains more than {MAX_FASTA_SEQUENCES} sequences"
            fields = stripped[1:].split("|")
            entity_type = fields[0].strip().lower()
            if entity_type not in _CHAI_ENTITY_TYPES:
                return f"Chai entity FASTA header has an unsupported entity type {fields[0].strip()!r}"
            label = fields[1].strip() if len(fields) == 2 else ""
            if len(fields) > 2 or not label or ("=" in label and label.split("=", 1)[0] != "name"):
                return "Chai entity FASTA header must declare a type and a name label"
            pending_entity_type = entity_type
            continue
        if pending_entity_type is None:
            return "FASTA file must start with a '>' header line"
        sequence_lines.append(stripped)
        total_residues += len(stripped)
        if total_residues > MAX_FASTA_TOTAL_RESIDUES:
            return f"FASTA file contains more than {MAX_FASTA_TOTAL_RESIDUES} residues"
    if pending_entity_type is not None:
        if error := check_record():
            return error
    if not sequences:
        return "FASTA file must contain a '>' header line"
    return None


def validate_fasta(path: str, *, allow_lowercase: bool = False) -> str | None:
    """Return an error message if *path* is not a plausible FASTA/A3M file."""
    text, error = _read_text(path, kind="FASTA")
    if error is not None:
        return error
    alphabet = _A3M_ALPHABET if allow_lowercase else _FASTA_ALPHABET
    sequences = 0
    total_residues = 0
    for line in text.splitlines():
        if len(line) > MAX_FASTA_RECORD_LENGTH:
            return f"FASTA file contains a record longer than {MAX_FASTA_RECORD_LENGTH} characters"
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(">"):
            sequences += 1
            if sequences > MAX_FASTA_SEQUENCES:
                return f"FASTA file contains more than {MAX_FASTA_SEQUENCES} sequences"
            continue
        if not sequences:
            return "FASTA file must start with a '>' header line"
        for char in line:
            if char in alphabet or char in _FASTA_WHITESPACE:
                if char not in _FASTA_WHITESPACE:
                    total_residues += 1
            else:
                return f"FASTA sequence contains invalid character {char!r}"
        if total_residues > MAX_FASTA_TOTAL_RESIDUES:
            return f"FASTA file contains more than {MAX_FASTA_TOTAL_RESIDUES} residues"
    if not sequences:
        return "FASTA file must contain a '>' header line"
    return None


def validate_a3m(path: str) -> str | None:
    """Return an error message if *path* is not a plausible A3M file."""
    return validate_fasta(path, allow_lowercase=True)
