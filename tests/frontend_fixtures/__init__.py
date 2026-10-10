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

from . import builders, results, scenarios
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
    PreflightInput,
    PreflightSpec,
    ReadinessState,
    ResultArtifactSpec,
    ResultFixture,
    RunnerDefinition,
    StoryboardSpec,
    WorkerView,
    WorkflowStage,
    WorkspaceCapability,
    WorkspaceStep,
)
from .provenance import PROVENANCE_SOURCE, ProvenanceError, production_receipt_pointer
from .replay import ReplayBundle
from .replay_bundle import (
    DEFAULT_MAX_BUNDLE_BYTES,
    DEFAULT_MAX_PAYLOAD_BYTES,
    REPLAY_BUNDLE_KIND,
    REPLAY_BUNDLE_VERSION,
    ReplayBundleError,
    bundle_digest,
    capture_replay_bundle,
    load_bundle,
    normalize,
    project_manifest_for_serve,
    required_view_sources,
    write_bundle,
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
    gremlin_lh_runner,
    pssm_gremlin_scenario,
    replay_scenario,
    runner_scenario,
    structure_scenario,
)

# The authentic-scenario inventory: the helpers whose identity or contract is a
# real production Runner, transcribed from that family's ``task.yaml``, rather
# than a synthetic stand-in. Exercising an authentic scenario is a fleet
# boundary activity, so a generic Server/Core test must not reach these helpers.
# ``tools/check_test_boundaries.py`` reads this declaration (a real consumer of
# the fixtures, not a text scan) so the enforcement set cannot drift from the
# helpers it guards: a helper listed here is fleet-only without a second list.
AUTHENTIC_SCENARIOS = frozenset({
    gremlin_lh_runner,
    production_receipt_pointer,
    pssm_gremlin_scenario,
    replay_scenario,
})

__all__ = [
    "ADMIN_AUTH",
    "ANONYMOUS_AUTH",
    "AUTHENTIC_SCENARIOS",
    "CONTROLLED_ACCESS_POLICY",
    "CONTROLLED_RUNNER_NAME",
    "DEFAULT_MAX_BUNDLE_BYTES",
    "DEFAULT_MAX_PAYLOAD_BYTES",
    "DEFAULT_ORIGIN",
    "DEFAULT_TASK_ID",
    "EXPIRED_AUTH",
    "PREFLIGHT_FIXTURES",
    "PROVENANCE_SOURCE",
    "REPLAY_BUNDLE_KIND",
    "REPLAY_BUNDLE_VERSION",
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
    "PreflightInput",
    "PreflightSpec",
    "ProvenanceError",
    "ReadinessState",
    "ReplayBundle",
    "ReplayBundleError",
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
    "WorkspaceStep",
    "build_catalog",
    "build_categorical_projection",
    "build_detail",
    "build_infrastructure",
    "build_matrix_projection",
    "build_parameter_schema",
    "build_preflight",
    "build_result_manifest",
    "build_runner_summary",
    "build_submit",
    "build_table_page",
    "build_task_status",
    "build_task_summary",
    "builders",
    "bundle_digest",
    "capture_replay_bundle",
    "controlled_runner",
    "controlled_scenario",
    "gremlin_lh_runner",
    "load_bundle",
    "mount_scenario",
    "normalize",
    "openapi_spec",
    "preflight_fixture",
    "production_receipt_pointer",
    "project_manifest_for_serve",
    "pssm_gremlin_scenario",
    "replay",
    "replay_bundle",
    "replay_scenario",
    "required_view_sources",
    "result_fixture",
    "results",
    "runner_scenario",
    "scenarios",
    "structure_scenario",
    "validate_manifest",
    "validate_payload",
    "view_entry",
    "write_bundle",
]
