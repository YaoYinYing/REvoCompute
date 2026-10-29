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
from revocompute.storage import RESERVED_RESULT_ROOT_FILES

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


_MOL1_ENTITY_TYPES = frozenset({"proteinChain", "dnaSequence", "rnaSequence", "ligand", "ion"})
_MOL1_ENTITY_KEYS = {
    "proteinChain": frozenset(
        {"sequence", "count", "id", "modifications", "pairedMsaPath", "unpairedMsaPath", "templatesPath"}
    ),
    "dnaSequence": frozenset({"sequence", "count", "id", "modifications"}),
    "rnaSequence": frozenset({"sequence", "count", "id", "modifications", "unpairedMsaPath"}),
    "ligand": frozenset({"ligand", "count", "id"}),
    "ion": frozenset({"ion", "count", "id"}),
}
_MOL1_SEQUENCE_ALPHABETS = {
    "proteinChain": frozenset("ACDEFGHIKLMNPQRSTVWYX"),
    "dnaSequence": frozenset("ACGTNXIU"),
    "rnaSequence": frozenset("ACGUNXI"),
}
# modelSeeds and assembly_id are accepted by upstream tooling but not by this
# Task's contract: seeds belong to the sample_seeds parameter, and assembly
# extension belongs to the JSON converter, not prediction.
_MOL1_JOB_KEYS = frozenset({"name", "sequences", "covalent_bonds"})
_MOL1_BOND_KEYS = frozenset(
    {"entity1", "entity2", "copy1", "copy2", "position1", "position2", "atom1", "atom2"}
)
_MOL1_JOB_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_MOL1_CHAIN_ID = re.compile(r"[A-Za-z0-9]{1,4}")
_MOL1_MODIFICATION_CODE = re.compile(r"CCD_[A-Za-z0-9]+")
_MOL1_LIGAND_CCD = re.compile(r"CCD_[A-Za-z0-9_]+")
_MOL1_ION_CODE = re.compile(r"[A-Za-z0-9]{1,8}")
_MOL1_TEMPLATE_EXTENSIONS = (".a3m", ".json")
_MOL1_MSA_EXTENSIONS = (".a3m",)
_MOL1_LIGAND_FILE_EXTENSIONS = (".pdb", ".sdf", ".mol2")
_MOL1_MAX_JOBS = 32
_MOL1_MAX_ENTITIES = 256
_MOL1_MAX_COPY_COUNT = 1024
_MOL1_MAX_POLYMER_RESIDUES = 20_000
_MOL1_MAX_BONDS = 1024
_MOL1_MAX_LIGAND_LENGTH = 10_000


def _mol1_int(value: Any) -> int | None:
    """A true integer: upstream adds and ranges over `count` and modification positions."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _mol1_bond_int(value: Any) -> int | None:
    """Bond fields: upstream calls ``int()`` on these and its docs show strings."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _mol1_asset_reference(value: Any, extensions: tuple[str, ...]) -> str | None:
    """Return an error unless *value* is a confined uploaded-asset reference.

    Upstream matches these suffixes case-sensitively, so the reference must
    carry the canonical lowercase extension.
    """
    if not isinstance(value, str) or not _safe_relative_asset_reference(value):
        return "must be a confined uploaded asset name"
    if not value.endswith(extensions):
        return f"must name one of: {', '.join(extensions)}"
    return None


def _mol1_modifications(
    entity_type: str, modifications: Any, sequence_length: int
) -> str | None:
    if modifications is None:
        return None
    if not isinstance(modifications, list):
        return "modifications must be a list"
    code_key, position_key = (
        ("ptmType", "ptmPosition") if entity_type == "proteinChain" else ("modificationType", "basePosition")
    )
    seen_positions: set[int] = set()
    for modification in modifications:
        if not isinstance(modification, dict) or set(modification) != {code_key, position_key}:
            return f"each modification must declare exactly '{code_key}' and '{position_key}'"
        if not isinstance(modification[code_key], str) or not _MOL1_MODIFICATION_CODE.fullmatch(
            modification[code_key]
        ):
            return f"'{code_key}' must be one CCD code"
        position = _mol1_int(modification[position_key])
        if position is None or not 1 <= position <= sequence_length:
            return f"'{position_key}' must be a residue position in the sequence"
        if position in seen_positions:
            return "modifications must not repeat a residue position"
        seen_positions.add(position)
    return None


def _mol1_entity_positions(entity_type: str, entity: dict[str, Any]) -> int:
    """Number of bond-addressable positions in one entity."""
    if entity_type in _MOL1_SEQUENCE_ALPHABETS:
        return len(entity.get("sequence") or "")
    if entity_type == "ligand" and isinstance(entity.get("ligand"), str):
        value = entity["ligand"]
        if value.startswith("CCD_"):
            return len(value.split("_")) - 1
    return 1


def _validate_mol1_specification(value: Any) -> str | None:
    """Validate Mol-1's AlphaFold-Server-like job list without scientific preparation.

    The upstream CLI accepts a top-level list of jobs. Path fields may name only
    confined uploaded assets, because a missing path makes upstream silently
    search the public ColabFold service instead.
    """
    if not isinstance(value, list) or not value:
        return "Mol-1 JSON must be a non-empty top-level list of jobs"
    if len(value) > _MOL1_MAX_JOBS:
        return f"Mol-1 JSON contains more than {_MOL1_MAX_JOBS} jobs"
    if _contains_external_url(value):
        return "Mol-1 JSON must not contain an external URL"
    names: set[str] = set()
    total_residues = 0
    for job_index, job in enumerate(value):
        label = f"Mol-1 job {job_index + 1}"
        if not isinstance(job, dict):
            return f"{label} must be an object"
        if set(job) - _MOL1_JOB_KEYS:
            return f"{label} contains an unsupported field"
        name = job.get("name")
        if not isinstance(name, str) or not _MOL1_JOB_NAME.fullmatch(name):
            return f"{label} needs a name of letters, digits, '.', '_' or '-'"
        # Upstream makes each job a directory under the result root.  A name the
        # Server writes there as a file would become that file's directory and
        # break publication after inference; the shared set is Server-owned.
        if name in RESERVED_RESULT_ROOT_FILES:
            return f"{label} name {name!r} collides with a Server-owned result file"
        if name in names:
            return f"Mol-1 job names must be unique: {name!r}"
        names.add(name)
        chain_ids: set[str] = set()
        sequences = job.get("sequences")
        if not isinstance(sequences, list) or not sequences or len(sequences) > _MOL1_MAX_ENTITIES:
            return f"{label} needs a non-empty sequences list of at most {_MOL1_MAX_ENTITIES} entities"
        entity_counts: list[int] = []
        entity_positions: list[int] = []
        for entity_index, entry in enumerate(sequences):
            entity_label = f"{label} sequence {entity_index + 1}"
            if not isinstance(entry, dict) or len(entry) != 1:
                return f"{entity_label} must declare exactly one entity type"
            entity_type, entity = next(iter(entry.items()))
            if entity_type not in _MOL1_ENTITY_TYPES:
                return f"{entity_label} has an unsupported entity type {entity_type!r}"
            if not isinstance(entity, dict) or set(entity) - _MOL1_ENTITY_KEYS[entity_type]:
                return f"{entity_label} contains an unsupported field"
            count = _mol1_int(entity.get("count"))
            if count is None or not 1 <= count <= _MOL1_MAX_COPY_COUNT:
                return f"{entity_label} needs a positive integer count"
            entity_counts.append(count)
            ids = entity.get("id")
            if ids is not None:
                if (
                    not isinstance(ids, list)
                    or len(ids) != count
                    or not all(isinstance(item, str) and _MOL1_CHAIN_ID.fullmatch(item) for item in ids)
                ):
                    return f"{entity_label} id must list one short chain id per copy"
                if len(set(ids)) != len(ids) or chain_ids & set(ids):
                    return f"{entity_label} chain ids must be unique across the job"
                chain_ids.update(ids)
            if entity_type in _MOL1_SEQUENCE_ALPHABETS:
                sequence = entity.get("sequence")
                if not isinstance(sequence, str) or not sequence:
                    return f"{entity_label} needs a non-empty sequence"
                if len(sequence) > _MOL1_MAX_POLYMER_RESIDUES:
                    return f"{entity_label} sequence exceeds {_MOL1_MAX_POLYMER_RESIDUES} residues"
                invalid = sorted(set(sequence) - _MOL1_SEQUENCE_ALPHABETS[entity_type])
                if invalid:
                    return f"{entity_label} sequence contains unsupported residues: {''.join(invalid)}"
                total_residues += len(sequence) * count
                error = _mol1_modifications(entity_type, entity.get("modifications"), len(sequence))
                if error:
                    return f"{entity_label} {error}"
                for field, extensions in (
                    ("pairedMsaPath", _MOL1_MSA_EXTENSIONS),
                    ("unpairedMsaPath", _MOL1_MSA_EXTENSIONS),
                    ("templatesPath", _MOL1_TEMPLATE_EXTENSIONS),
                ):
                    if field in entity:
                        error = _mol1_asset_reference(entity[field], extensions)
                        if error:
                            return f"{entity_label} {field} {error}"
            elif entity_type == "ligand":
                ligand = entity.get("ligand")
                if not isinstance(ligand, str) or not ligand or len(ligand) > _MOL1_MAX_LIGAND_LENGTH:
                    return f"{entity_label} needs a non-empty ligand description"
                if ligand.startswith("CCD_"):
                    if not _MOL1_LIGAND_CCD.fullmatch(ligand):
                        return f"{entity_label} ligand CCD codes are malformed"
                elif ligand.startswith("FILE_"):
                    error = _mol1_asset_reference(ligand[len("FILE_") :], _MOL1_LIGAND_FILE_EXTENSIONS)
                    if error:
                        return f"{entity_label} ligand FILE_ reference {error}"
                elif "://" in ligand:
                    return f"{entity_label} ligand must be a CCD code, SMILES, or uploaded FILE_ asset"
            else:
                ion = entity.get("ion")
                if not isinstance(ion, str) or not _MOL1_ION_CODE.fullmatch(ion):
                    return f"{entity_label} needs a CCD ion code"
            entity_positions.append(_mol1_entity_positions(entity_type, entity))
        if total_residues > _MOL1_MAX_POLYMER_RESIDUES:
            return f"Mol-1 JSON exceeds {_MOL1_MAX_POLYMER_RESIDUES} total polymer residues"
        bonds = job.get("covalent_bonds")
        if bonds is not None:
            if not isinstance(bonds, list) or len(bonds) > _MOL1_MAX_BONDS:
                return f"{label} covalent_bonds must be a list of at most {_MOL1_MAX_BONDS} bonds"
            for bond_index, bond in enumerate(bonds):
                bond_label = f"{label} covalent_bonds {bond_index + 1}"
                if not isinstance(bond, dict) or set(bond) - _MOL1_BOND_KEYS:
                    return f"{bond_label} contains an unsupported field"
                entity_numbers: list[int] = []
                for suffix in ("1", "2"):
                    entity_number = _mol1_bond_int(bond.get(f"entity{suffix}"))
                    if entity_number is None or not 1 <= entity_number <= len(sequences):
                        return f"{bond_label} entity{suffix} must name an entity in the job"
                    entity_numbers.append(entity_number)
                    position = _mol1_bond_int(bond.get(f"position{suffix}"))
                    if position is None or not 1 <= position <= entity_positions[entity_number - 1]:
                        return f"{bond_label} position{suffix} is outside its entity"
                    atom = bond.get(f"atom{suffix}")
                    if not isinstance(atom, str) or not atom or len(atom) > 32:
                        return f"{bond_label} atom{suffix} must name an atom"
                has_copy1, has_copy2 = "copy1" in bond, "copy2" in bond
                if has_copy1 != has_copy2:
                    return f"{bond_label} must declare copy1 and copy2 together"
                if has_copy1:
                    for suffix in ("1", "2"):
                        entity_number = _mol1_bond_int(bond[f"entity{suffix}"])
                        copy = _mol1_bond_int(bond[f"copy{suffix}"])
                        if copy is None or not 1 <= copy <= entity_counts[entity_number - 1]:
                            return f"{bond_label} copy{suffix} is outside its entity"
                elif entity_counts[entity_numbers[0] - 1] != entity_counts[entity_numbers[1] - 1]:
                    return f"{bond_label} must declare copy1 and copy2 when the entity counts differ"
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
    "mol1_specification": _validate_mol1_specification,
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


def _load_boltz_document(path: str) -> str | None:
    text, error = _read_text(path, kind="Boltz specification")
    if error:
        return error
    return _validate_boltz_yaml_specification(text)


def validate_boltz_fasta_specification(path: str) -> str | None:
    """Physical-format dialect for the header-framed Boltz FASTA.

    Registered in ``_DIALECTS`` so it *replaces* the strict protein
    ``validate_fasta`` for this logical type. Boltz reuses FASTA framing for
    ``ccd`` and ``smiles`` entities whose payloads are not protein residues,
    so running the protein alphabet first would reject legal input.
    """
    text, error = _read_text(path, kind="Boltz specification")
    if error:
        return error
    return _validate_boltz_fasta_specification(text)


def validate_logical_input(path: str, format_name: str, logical_type: str) -> str | None:
    if logical_type == "protein_structure":
        text, error = _read_text(path, kind="protein structure")
        if error:
            return error
        if format_name in {"pdb", "ent", "pdbqt"} and not any(
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
    elif logical_type == "boltz_specification" and format_name in _BOLTZ_YAML_EXTENSIONS:
        # The FASTA dialect is selected by ``_DIALECTS`` in the physical pass,
        # so only the YAML serialization reaches this branch.
        error = _load_boltz_document(path)
        if error:
            return error
    return None
