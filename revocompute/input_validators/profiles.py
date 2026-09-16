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

from revocompute.input_validators.common import _read_text

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
    elif format_name == "json" and logical_type in {
        "alphafold3_specification",
        "foundry_specification",
        "opendde_specification",
    }:
        value, error = _load_json_document(path)
        if error:
            return error
        validators = {
            "alphafold3_specification": _validate_alphafold3_specification,
            "foundry_specification": _validate_foundry_specification,
            "opendde_specification": _validate_opendde_specification,
        }
        return validators[logical_type](value)
    return None
