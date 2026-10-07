# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""SQLAlchemy schema for durable Operator Job records."""

from __future__ import annotations

import sqlalchemy as sa


def operator_jobs_table(metadata: sa.MetaData) -> sa.Table:
    """Declare the Operator Job table on the caller's metadata.

    The caller owns the metadata so each store instance has its own table object
    bound to its own engine, with no shared mutable module-level state.
    """
    return sa.Table(
        "operator_jobs",
        metadata,
        sa.Column("job_id", sa.String(42), primary_key=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("runner_family", sa.String(64), nullable=False),
        sa.Column("actor_user_id", sa.Integer, nullable=False),
        sa.Column("actor_username", sa.String, nullable=False),
        sa.Column("tier", sa.String(16), nullable=False),
        sa.Column("lease_scope", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("stage", sa.String(32), nullable=True),
        sa.Column("requested_intent", sa.Text, nullable=False),
        sa.Column("request_identity", sa.String(80), nullable=False),
        sa.Column("plan_digest", sa.String(80), nullable=False),
        sa.Column("evidence_digest", sa.String(80), nullable=False),
        sa.Column("parameter_json", sa.Text, nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=True),
        sa.Column("result_json", sa.Text, nullable=True),
        sa.Column("effect_json", sa.Text, nullable=True),
        sa.Column("failure_category", sa.String(64), nullable=True),
        sa.Column("log_text", sa.Text, nullable=True),
        sa.Column("created_at", sa.Float, nullable=False),
        sa.Column("started_at", sa.Float, nullable=True),
        sa.Column("finished_at", sa.Float, nullable=True),
        sa.Index("idx_operator_jobs_family_status", "runner_family", "status"),
        sa.Index("idx_operator_jobs_actor", "actor_user_id"),
        sa.Index("idx_operator_jobs_created", "created_at"),
        sa.Index("uq_operator_jobs_idempotency", "actor_user_id", "idempotency_key", unique=True),
    )
