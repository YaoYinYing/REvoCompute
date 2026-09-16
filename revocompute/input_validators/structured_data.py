# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Bounded transport validators for structured text and Parquet inputs."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import yaml

from revocompute.input_validators.common import MAX_TEXT_BYTES, _read_text

MAX_STRUCTURED_TEXT_BYTES = 1024 * 1024
MAX_STRUCTURED_NODES = 1_000_000
MAX_STRUCTURED_DEPTH = 50
MAX_DELIMITED_ROWS = 1_000_000
MAX_DELIMITED_RECORD_LENGTH = 1024 * 1024


def _object_graph_stats(root: Any) -> tuple[int, int]:
    nodes = 0
    depth = 0
    seen: set[int] = set()
    stack: list[tuple[Any, int]] = [(root, 1)]
    while stack:
        value, level = stack.pop()
        nodes += 1
        depth = max(depth, level)
        if isinstance(value, dict):
            identity = id(value)
            if identity in seen:
                continue
            seen.add(identity)
            stack.extend((child, level + 1) for child in value.values())
        elif isinstance(value, list):
            identity = id(value)
            if identity in seen:
                continue
            seen.add(identity)
            stack.extend((child, level + 1) for child in value)
    return nodes, depth


def validate_yaml(path: str) -> str | None:
    """Validate bounded, UTF-8 YAML without applying a Runner schema."""
    text, error = _read_text(path, kind="YAML", max_bytes=MAX_STRUCTURED_TEXT_BYTES)
    if error:
        return error
    try:
        if any(isinstance(event, yaml.events.AliasEvent) for event in yaml.parse(text, Loader=yaml.SafeLoader)):
            return "YAML aliases are not supported in scientific input"
        value = yaml.safe_load(text)
    except (yaml.YAMLError, RecursionError):
        return "Uploaded file does not appear to be valid YAML"
    if not isinstance(value, dict):
        return "YAML scientific input must contain a top-level mapping"
    nodes, depth = _object_graph_stats(value)
    if nodes > MAX_STRUCTURED_NODES:
        return f"YAML file contains more than {MAX_STRUCTURED_NODES} values"
    if depth > MAX_STRUCTURED_DEPTH:
        return f"YAML file is nested deeper than {MAX_STRUCTURED_DEPTH} levels"
    return None


def validate_delimited_text(path: str) -> str | None:
    """Validate a bounded UTF-8 CSV/restraints transport without scientific interpretation."""
    text, error = _read_text(path, kind="delimited text", max_bytes=MAX_TEXT_BYTES)
    if error:
        return error
    if text.lstrip().lower().startswith(("<!doctype", "<html", "<script", "<?xml")):
        return "Uploaded delimited-text file appears to contain markup"
    lines = text.splitlines()
    if not any(line.strip() for line in lines):
        return "Uploaded delimited-text file is empty"
    if any(len(line) > MAX_DELIMITED_RECORD_LENGTH for line in lines):
        return f"Delimited-text file contains a record longer than {MAX_DELIMITED_RECORD_LENGTH} characters"
    try:
        for count, _row in enumerate(csv.reader(lines, strict=True), start=1):
            if count > MAX_DELIMITED_ROWS:
                return f"Delimited-text file contains more than {MAX_DELIMITED_ROWS} records"
    except csv.Error:
        return "Uploaded file does not appear to be valid delimited text"
    return None


def validate_parquet(path: str) -> str | None:
    """Check the bounded Parquet envelope without loading third-party parsing code."""
    try:
        source = Path(path)
        size = source.stat().st_size
        if size < 8:
            return "Uploaded file does not appear to be a Parquet file"
        with source.open("rb") as stream:
            first_magic = stream.read(4)
            stream.seek(-4, 2)
            last_magic = stream.read(4)
    except OSError as exc:
        return f"Could not read uploaded Parquet file: {exc}"
    if first_magic != b"PAR1" or last_magic != b"PAR1":
        return "Uploaded file does not appear to be a Parquet file"
    return None
