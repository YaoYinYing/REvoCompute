# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Reusable logical input profiles, separate from file-format parsing."""

from __future__ import annotations

import json
import ntpath
import re
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from revocompute.input_validators.common import (
    MAX_FASTA_RECORD_LENGTH,
    MAX_FASTA_SEQUENCES,
    MAX_FASTA_TOTAL_RESIDUES,
    _read_text,
)

_URL_PATTERN = re.compile(r"[a-z][a-z0-9+.-]*://", re.IGNORECASE)
_FOUNDRY_PATH_KEYS = {"input", "path", "msa_path", "template_path"}


def _load_json_document(path: str) -> tuple[Any | None, str | None]:
    try:
        return json.loads(Path(path).read_bytes().decode("utf-8")), None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        return None, "Uploaded task specification is not valid JSON"


def _walk_json(value: Any):
    stack = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            for key, child in current.items():
                yield str(key), child
                stack.append(child)
        elif isinstance(current, list):
            stack.extend(current)


def _walk_json_values(value: Any):
    stack = [value]
    while stack:
        current = stack.pop()
        yield current
        if isinstance(current, dict):
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)


def _is_nonempty_object_or_object_list(value: Any) -> bool:
    return (isinstance(value, dict) and bool(value)) or (
        isinstance(value, list) and bool(value) and all(isinstance(item, dict) and item for item in value)
    )


def _contains_external_url(value: Any) -> bool:
    return any(isinstance(child, str) and _URL_PATTERN.match(child.strip()) for child in _walk_json_values(value))


def _safe_relative_asset_reference(value: str) -> bool:
    source = unicodedata.normalize("NFKC", value).strip()
    if not source or any(ord(character) < 32 or ord(character) == 127 for character in source):
        return False
    for candidate in (source, unquote(source)):
        drive, _tail = ntpath.splitdrive(candidate)
        normalized = candidate.replace("\\", "/")
        parts = normalized.split("/")
        if drive or ntpath.isabs(candidate) or normalized.startswith("/"):
            return False
        if not parts or any(part in {"", ".", ".."} for part in parts):
            return False
    return not _URL_PATTERN.match(source)


def _validate_alphafold3_specification(value: Any) -> str | None:
    documents = value if isinstance(value, list) else [value]
    if not documents or not all(isinstance(document, dict) and document for document in documents):
        return "AlphaFold 3 JSON must have a non-empty object or object-list top-level shape"
    for key, _child in _walk_json(value):
        if key.casefold().endswith("path"):
            return "AlphaFold 3 JSON contains an external file field; provide content inline"
    if _contains_external_url(value):
        return "AlphaFold 3 JSON must not contain an external URL"
    if isinstance(value, dict) and (
        value.get("dialect") != "alphafold3"
        or not isinstance(value.get("version"), int)
        or isinstance(value.get("version"), bool)
        or value["version"] < 1
    ):
        return "AlphaFold 3 JSON object must declare the alphafold3 dialect and a positive integer version"
    if any(not isinstance(document.get("sequences"), list) or not document["sequences"] for document in documents):
        return "AlphaFold 3 JSON must contain a non-empty sequences list"
    if any(not isinstance(document.get("modelSeeds"), list) or not document["modelSeeds"] for document in documents):
        return "AlphaFold 3 JSON must contain a non-empty modelSeeds list"
    return None


def _validate_opendde_specification(value: Any) -> str | None:
    if not _is_nonempty_object_or_object_list(value):
        return "OpenDDE JSON must have a non-empty object or object-list top-level shape"
    for key, _child in _walk_json(value):
        normalized = key.casefold()
        if normalized.endswith("path") or normalized.endswith("url"):
            return "OpenDDE JSON must not contain external path or URL fields"
    if _contains_external_url(value):
        return "OpenDDE JSON must not contain an external URL"
    return None


def _validate_foundry_specification(value: Any) -> str | None:
    if not _is_nonempty_object_or_object_list(value):
        return "Foundry JSON must have a non-empty object or object-list top-level shape"
    if _contains_external_url(value):
        return "Foundry JSON path fields must name a confined uploaded asset"
    for key, child in _walk_json(value):
        if key.casefold() in _FOUNDRY_PATH_KEYS and (
            not isinstance(child, str) or not _safe_relative_asset_reference(child)
        ):
            return "Foundry JSON path fields must name a confined uploaded asset"
    return None


_SPECIFICATION_VALIDATORS: dict[str, Any] = {
    "alphafold3_specification": _validate_alphafold3_specification,
    "foundry_specification": _validate_foundry_specification,
    "opendde_specification": _validate_opendde_specification,
}

# Boltz reuses two physical formats for one logical contract: a YAML document
# and a header-framed FASTA. The FASTA dialect is its own — `>CHAIN|TYPE[|MSA]`
# with `ccd`/`smiles` entity types — so it cannot share the protein alphabet.
_BOLTZ_FASTA_ENTITY_TYPES = frozenset({"protein", "dna", "rna", "ccd", "smiles"})
_BOLTZ_YAML_ENTITY_TYPES = ("protein", "rna", "dna", "ligand")
_BOLTZ_YAML_EXTENSIONS = ("yml", "yaml")


def _boltz_header_fields(header: str) -> list[str]:
    """Return the pipe-separated fields of a Boltz FASTA header."""
    return [field.strip() for field in header[1:].split("|")]


def _validate_boltz_fasta_specification(text: str) -> str | None:
    records = 0
    total_residues = 0
    seen_chains: set[str] = set()
    for line in text.splitlines():
        if len(line) > MAX_FASTA_RECORD_LENGTH:
            return f"FASTA file contains a record longer than {MAX_FASTA_RECORD_LENGTH} characters"
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(">"):
            records += 1
            if records > MAX_FASTA_SEQUENCES:
                return f"FASTA file contains more than {MAX_FASTA_SEQUENCES} sequences"
            fields = _boltz_header_fields(stripped)
            if len(fields) < 2:
                return "Boltz FASTA header must declare 'CHAIN_ID|ENTITY_TYPE' fields"
            chain_id, entity_type = fields[0], fields[1].lower()
            if not chain_id:
                return "Boltz FASTA header has an empty chain id"
            if chain_id in seen_chains:
                return f"Boltz FASTA header repeats chain id {chain_id!r}"
            seen_chains.add(chain_id)
            if entity_type not in _BOLTZ_FASTA_ENTITY_TYPES:
                return f"Boltz FASTA header has an unsupported entity type {fields[1]!r}"
            if len(fields) > 3:
                return "Boltz FASTA header has more than three fields"
            if len(fields) == 3 and fields[2]:
                if entity_type != "protein":
                    return "Boltz FASTA MSA references are only valid for protein chains"
                if not _safe_relative_asset_reference(fields[2]) and fields[2] != "empty":
                    return "Boltz FASTA MSA reference must be 'empty' or a confined uploaded asset"
            continue
        if not records:
            return "FASTA file must start with a '>' header line"
        # Sequences stay one line per record upstream; whitespace inside a
        # sequence would silently change its length.
        if len(stripped.split()) != 1:
            return "Boltz FASTA sequence line contains whitespace"
        if not stripped:
            return "Boltz FASTA contains an empty sequence"
        total_residues += len(stripped)
        if total_residues > MAX_FASTA_TOTAL_RESIDUES:
            return f"FASTA file contains more than {MAX_FASTA_TOTAL_RESIDUES} residues"
    if not records:
        return "FASTA file must contain a '>' header line"
    return None


def _validate_boltz_yaml_specification(text: str) -> str | None:
    import yaml

    try:
        document = yaml.safe_load(text)
    except (yaml.YAMLError, RecursionError):
        return "Uploaded Boltz specification is not valid YAML"
    if not isinstance(document, dict):
        return "Boltz YAML must contain a top-level mapping"
    sequences = document.get("sequences")
    if not isinstance(sequences, list) or not sequences:
        return "Boltz YAML must contain a non-empty sequences list"
    for item in sequences:
        if not isinstance(item, dict) or not item:
            return "Boltz YAML sequences entries must be non-empty entity mappings"
        declared = _BOLTZ_YAML_ENTITY_TYPES + ("ccd",)
        entity_types = [name for name in item if name in declared]
        if len(entity_types) != 1 or len(item) != 1:
            return "Boltz YAML sequences entries must declare exactly one entity type"
        entity_type = entity_types[0]
        entity = item[entity_type]
        if not isinstance(entity, dict):
            return f"Boltz YAML {entity_type} entry must be a mapping"
        if entity_type in {"protein", "rna", "dna"}:
            if not isinstance(entity.get("sequence"), str) or not entity["sequence"]:
                return f"Boltz YAML {entity_type} entry must declare a non-empty sequence"
        elif not entity.get("ccd") and not entity.get("smiles"):
            return "Boltz ligand entries must declare a ccd code or a smiles string"
        # `msa: empty` and confined relative paths are the two accepted MSA
        # forms; a URL or absolute path is never a legal reference.
        msa = entity.get("msa")
        if msa not in (None, "", "empty"):
            if entity_type != "protein":
                return "Boltz 'msa' is only valid for protein entities"
            if not isinstance(msa, str) or not _safe_relative_asset_reference(msa):
                return "Boltz 'msa' must be 'empty' or a confined uploaded asset"
    if _contains_external_url(document):
        return "Boltz YAML must not contain an external URL"
    return None


def _load_boltz_document(path: str, format_name: str) -> str | None:
    text, error = _read_text(path, kind="Boltz specification")
    if error:
        return error
    if format_name in _BOLTZ_YAML_EXTENSIONS:
        return _validate_boltz_yaml_specification(text)
    if format_name in {"fasta", "fa", "fas"}:
        return _validate_boltz_fasta_specification(text)
    return f"Boltz specifications do not support the {format_name!r} format"


def validate_logical_input(path: str, format_name: str, logical_type: str) -> str | None:
    if logical_type == "protein_structure":
        text, error = _read_text(path, kind="protein structure")
        if error:
            return error
        if format_name in {"pdb", "pdbqt"} and not any(
            line.startswith("ATOM  ") for line in text.splitlines()
        ):
            return "Protein structure contains no protein ATOM records"
        if format_name in {"cif", "mmcif"} and "_atom_site." not in text:
            return "Protein structure contains no atom-site records"
    elif logical_type == "alignment" and format_name in {"a3m", "fa", "faa", "fas", "fasta"}:
        text, error = _read_text(path, kind="alignment")
        if error:
            return error
        sequences = [
            "".join(line for line in record.splitlines()[1:] if line.strip())
            for record in text.split(">")
            if record.strip()
        ]
        widths = {
            len("".join(char for char in sequence if not char.islower() and char not in "."))
            for sequence in sequences
        }
        if len(sequences) < 2 or len(widths) != 1 or 0 in widths:
            return "Alignment must contain at least two equal-length sequences"
    elif format_name == "json":
        # _error is not reachable: the .json extension always runs
        # json_file.validate_json before this logical-type check.
        specification_validator = _SPECIFICATION_VALIDATORS.get(logical_type)
        if specification_validator is not None:
            value, _error = _load_json_document(path)
            return specification_validator(value)
    elif logical_type == "boltz_specification" and format_name in {
        *_BOLTZ_YAML_EXTENSIONS,
        "fasta",
        "fa",
        "fas",
    }:
        error = _load_boltz_document(path, format_name)
        if error:
            return error
    return None
