# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Fail-fast validation for the current REvoCompute persistent-state epoch."""

from __future__ import annotations

from collections.abc import Mapping, Set

import sqlalchemy as sa

SCHEMA_EPOCH_ERROR = """REvoCompute persistent state is incompatible with the personal-task ownership/storage schema epoch.

This release intentionally does not migrate old test data. Stop the service,
reset the server user/task databases, workspaces, and results according to the
deployment documentation, then start again. Project-era state is not converted
or reinterpreted as personal task state."""


def require_current_schema(
    connection: sa.Connection,
    required_tables: Mapping[str, Set[str]],
    *,
    database_name: str,
    forbidden_columns: Mapping[str, Set[str]] | None = None,
) -> None:
    """Reject a non-empty partial or obsolete schema before ``create_all`` mutates it."""
    inspector = sa.inspect(connection)
    existing_tables = set(inspector.get_table_names())
    relevant_tables = existing_tables.intersection(required_tables)
    if not relevant_tables:
        return

    problems: list[str] = []
    for table_name, required_columns in required_tables.items():
        if table_name not in existing_tables:
            problems.append(f"missing table {table_name}")
            continue
        existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
        missing_columns = sorted(set(required_columns) - existing_columns)
        if missing_columns:
            problems.append(f"{table_name} missing columns: {', '.join(missing_columns)}")
        obsolete_columns = sorted(existing_columns.intersection((forbidden_columns or {}).get(table_name, set())))
        if obsolete_columns:
            problems.append(f"{table_name} has obsolete columns: {', '.join(obsolete_columns)}")

    for table_name, forbidden in (forbidden_columns or {}).items():
        if table_name in required_tables or table_name not in existing_tables:
            continue
        existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
        obsolete_columns = sorted(existing_columns.intersection(forbidden))
        if obsolete_columns:
            problems.append(f"{table_name} has obsolete columns: {', '.join(obsolete_columns)}")

    if problems:
        detail = "; ".join(problems)
        raise RuntimeError(f"{SCHEMA_EPOCH_ERROR}\n\nIncompatible {database_name}: {detail}")
