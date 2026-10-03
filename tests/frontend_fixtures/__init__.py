# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Deterministic canonical API fixtures for the production frontend.

The harness serves the real built frontend bundle against fixture responses that
use the server's own projection vocabulary, so Runner-facing frontend behavior
can be exercised without a Runner image, GPU, scheduler, or network.

What a fixture test proves: *given this canonical API contract, the frontend
renders and behaves correctly*. What it never proves: that a Runner executes, or
that a scientific output is valid. Runner live acceptance and scientific
validation stay with real execution and real receipts.
"""

from __future__ import annotations

from . import admin, builders, results, scenarios  # noqa: F401  module handles for tests
from .admin import (
    build_access_policy_summary,
    build_access_request,
    build_admin_configuration,
    build_admin_user,
    build_admin_user_list,
    build_gpu_credit,
    build_log_archives,
    build_user_entitlements,
    build_user_metrics,
)
from .auth import ADMIN_AUTH, ANONYMOUS_AUTH, EXPIRED_AUTH, USER_AUTH, Session
from .builders import (
    PREFLIGHT_FIXTURES,
    build_catalog,
    build_categorical_projection,
    build_detail,
    build_infrastructure,
    build_matrix_projection,
    build_parameter_schema,
    build_preflight,
    build_result_manifest,
    build_runner_summary,
    build_submit,
    build_table_page,
    build_task_status,
    build_task_summary,
    openapi_spec,
    preflight_fixture,
    validate_payload,
    view_entry,
)
from .models import (
    DEFAULT_ORIGIN,
    DEFAULT_TASK_ID,
    AccessState,
    ArchiveSpec,
    Citation,
    InputRole,
    LifecycleSpec,
    OutputCheckSpec,
    ParameterSpec,
    PreflightAdmission,
    PreflightSpec,
    ReadinessState,
    ResultArtifactSpec,
    ResultFixture,
    RunnerDefinition,
    StoryboardSpec,
    WorkerView,
    WorkflowStage,
    WorkspaceCapability,
    WorkspacePluginAsset,
    WorkspaceStep,
)
from .results import RESULT_FIXTURES, result_fixture, validate_manifest
from .router import (
    FrontendFixtureRouter,
    RequestCapture,
    RequestRecord,
    UnexpectedRequest,
    mount_scenario,
)
from .scenarios import (
    CONTROLLED_ACCESS_POLICY,
    CONTROLLED_RUNNER_NAME,
    SEQUENCE_ROLE,
    RunnerScenario,
    controlled_runner,
    controlled_scenario,
    pssm_gremlin_scenario,
    runner_scenario,
    structure_scenario,
)

__all__ = [
    "ADMIN_AUTH",
    "ANONYMOUS_AUTH",
    "CONTROLLED_ACCESS_POLICY",
    "CONTROLLED_RUNNER_NAME",
    "DEFAULT_ORIGIN",
    "DEFAULT_TASK_ID",
    "EXPIRED_AUTH",
    "PREFLIGHT_FIXTURES",
    "RESULT_FIXTURES",
    "SEQUENCE_ROLE",
    "USER_AUTH",
    "AccessState",
    "ArchiveSpec",
    "Citation",
    "FrontendFixtureRouter",
    "InputRole",
    "LifecycleSpec",
    "OutputCheckSpec",
    "ParameterSpec",
    "PreflightAdmission",
    "PreflightSpec",
    "ReadinessState",
    "RequestCapture",
    "RequestRecord",
    "ResultArtifactSpec",
    "ResultFixture",
    "RunnerDefinition",
    "RunnerScenario",
    "Session",
    "StoryboardSpec",
    "UnexpectedRequest",
    "WorkerView",
    "WorkflowStage",
    "WorkspaceCapability",
    "WorkspacePluginAsset",
    "WorkspaceStep",
    "admin",
    "build_access_policy_summary",
    "build_access_request",
    "build_admin_configuration",
    "build_admin_user",
    "build_admin_user_list",
    "build_catalog",
    "build_categorical_projection",
    "build_detail",
    "build_gpu_credit",
    "build_infrastructure",
    "build_log_archives",
    "build_matrix_projection",
    "build_parameter_schema",
    "build_preflight",
    "build_result_manifest",
    "build_runner_summary",
    "build_submit",
    "build_table_page",
    "build_task_status",
    "build_task_summary",
    "build_user_entitlements",
    "build_user_metrics",
    "builders",
    "controlled_runner",
    "controlled_scenario",
    "mount_scenario",
    "openapi_spec",
    "preflight_fixture",
    "pssm_gremlin_scenario",
    "result_fixture",
    "results",
    "runner_scenario",
    "scenarios",
    "structure_scenario",
    "validate_manifest",
    "validate_payload",
    "view_entry",
]
