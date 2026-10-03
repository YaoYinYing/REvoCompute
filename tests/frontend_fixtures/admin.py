# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Deterministic payloads for the profile, credit, and administration surfaces.

These projections are outside the Runner workflow: account identity, GPU credit
ledger state, access policy administration, runtime configuration, and log
archives. They exist so a browser test can drive those views against canonical
response shapes without a populated deployment.
"""

from __future__ import annotations

from typing import Any

from .auth import ADMIN_AUTH, USER_AUTH, Session
from .builders import validate_payload
from .models import RunnerDefinition


def build_gpu_credit(user_id: int = 2, adjustment: int = 600) -> dict[str, Any]:
    payload = {
        "user_id": user_id,
        "period": "2026-09",
        "credit_unit_gpu_seconds": 60,
        "monthly_grant_gpu_seconds": 7200,
        "usage_gpu_seconds": 1800,
        "adjustment_gpu_seconds": adjustment,
        "remaining_gpu_seconds": 6000 + adjustment,
        "monthly_grant_credits": 120,
        "usage_credits": 30,
        "adjustment_credits": adjustment / 60,
        "remaining_credits": 100 + adjustment / 60,
        "allow_gpu_use": True,
        "history": [
            {
                "id": 1,
                "period": "2026-09",
                "kind": "monthly_grant",
                "gpu_seconds": 7200,
                "reason": "Monthly allocation",
                "created_at": 1790636400,
            }
        ],
    }
    validate_payload("GPUCreditSummary", payload)
    return payload


def build_user_metrics(window: str = "30d") -> dict[str, Any]:
    days = {"7d": 7, "30d": 30, "90d": 90, "quarter": 92}.get(window, 30)
    payload = {
        "window": window,
        "days": days,
        "period": "2026-09-29",
        "tasks_submitted": 5,
        "tasks_completed": 4,
        "tasks_failed": 1,
        "success_rate": 0.8,
        "cpu_tasks": 3,
        "gpu_tasks": 2,
        "gpu_minutes": 30,
        "total_runtime_seconds": 480,
        "median_runtime_seconds": 75,
        "distribution": [{"task_type": "sequence_demo", "label": "Sequence demo", "gpu": False, "tasks": 5}],
        "activity": [{"period": "2026-09-28", "count": 2}, {"period": "2026-09-29", "count": 3}],
    }
    validate_payload("UserMetrics", payload)
    return payload


def build_admin_user(user_id: int, session: Session, *, allow_gpu_use: bool = True) -> dict[str, Any]:
    payload = {
        "id": user_id,
        **session.as_user_payload(),
        "allow_gpu_use": allow_gpu_use,
        "registration_status": "approved",
        "user_status": "active",
        "created_at": 1790636400,
        "approved_by": 1,
        "approved_at": 1790636500,
        "registration_ip": "192.0.2.10",
        "registration_country": "TEST",
        "gpu_credit": build_gpu_credit(user_id),
    }
    validate_payload("AdminUser", payload)
    return payload


def build_admin_user_list(admin: Session) -> dict[str, Any]:
    """The administrator roster: the acting administrator plus one ordinary user.

    The list projection is what the User control table renders, so it carries
    both roles rather than only the caller's own identity.
    """
    admin_session = admin if admin.role == "admin" else ADMIN_AUTH
    payload = {"users": [build_admin_user(1, admin_session), build_admin_user(2, USER_AUTH)]}
    validate_payload("AdminUserList", payload)
    return payload


def build_access_policy_summary(policy_id: str = "academic-only", **overrides: object) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "policy_id": policy_id,
        "label": "Academic models",
        "description": "Eligibility required.",
        "requires": ["academic-models"],
        "notice": None,
        "license": None,
        "authorized_users": 1,
        "pending_requests": 1,
        "suspended_users": 0,
        **overrides,
    }
    validate_payload("AccessPolicySummary", payload)
    return payload


def build_access_request(request_id: int = 7, user_id: int = 2) -> dict[str, Any]:
    return {
        "id": request_id,
        "user_id": user_id,
        "username": "tester",
        "full_name": "Test Scientist",
        "email": "tester@example.org",
        "affiliation": "Example Institute",
        "entitlement": "academic-models",
        "reason": "Non-commercial protein design.",
        "status": "pending",
        "created_at": 1790636400,
    }


def build_user_entitlements(policy_id: str = "academic-only") -> dict[str, Any]:
    payload = {
        "grants": [
            {
                "id": 5,
                "user_id": 2,
                "entitlement": "academic-models",
                "basis": "institutional_collaborator",
                "expires_at": None,
                "revoked_at": None,
                "created_at": 1790636400,
                "note": "Affiliation verified",
            }
        ],
        "policies": [
            {"policy_id": policy_id, "label": "Academic models", "granted": True, "request_status": "approved"},
        ],
    }
    validate_payload("UserEntitlements", payload)
    return payload


def build_admin_configuration(definition: RunnerDefinition) -> dict[str, Any]:
    parameters = len(definition.parameters)
    payload = {
        "task_types": [
            {
                "tool": definition.name,
                "display_name": definition.display_name,
                "enabled": True,
                "requires_gpu": definition.gpus,
                "runtime_family": definition.runtime_family,
                "is_workflow_stage": False,
                "category": definition.category,
                "inputs": [
                    {"id": role.id, "title": role.title, "formats": list(role.formats)} for role in definition.inputs
                ],
                "parameter_count": parameters,
                "stage_count": len(definition.workflow),
                "effective_resources": {"cpus": 2, "memory": "4G"},
            }
        ],
        "resources": {"cpus": 2, "memory": "4G", "max_runtime_seconds": 3600, "slurm_partition": "cpu"},
        "ignored_resource_keys": [],
        "slurm": {"enabled": True, "allowed_queues": ["cpu", "gpu"]},
    }
    validate_payload("AdminConfiguration", payload)
    return payload


def build_log_archives() -> dict[str, Any]:
    payload = {
        "logs": [
            {
                "id": "server",
                "filename": "server.log",
                "archives": [{"filename": "server.log.1", "size": 2048, "modified_at": 1790636400}],
            }
        ]
    }
    validate_payload("LogArchiveList", payload)
    return payload


__all__ = [
    "build_access_policy_summary",
    "build_access_request",
    "build_admin_configuration",
    "build_admin_user",
    "build_admin_user_list",
    "build_gpu_credit",
    "build_log_archives",
    "build_user_entitlements",
    "build_user_metrics",
]
