# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Contract guarantees of the frontend fixture harness itself.

The harness is the only artifact here that can drift from production: the
frontend bundle, the API projection, and the schemas are all real. These tests
assert the guarantees a browser test relies on — canonical vocabulary, schema
validity, deterministic lifecycle, and readable request capture — so a fixture
failure names the harness rather than the browser under test.
"""

from __future__ import annotations

from frontend_fixtures import (
    ADMIN_AUTH,
    ANONYMOUS_AUTH,
    EXPIRED_AUTH,
    AccessState,
    PREFLIGHT_FIXTURES,
    RESULT_FIXTURES,
    USER_AUTH,
    RequestCapture,
    RequestRecord,
    build_catalog,
    build_detail,
    build_infrastructure,
    build_parameter_schema,
    build_runner_summary,
    build_task_status,
    build_task_summary,
    builders,
    controlled_runner,
    controlled_scenario,
    openapi_spec,
    pssm_gremlin_scenario,
    result_fixture,
    structure_scenario,
    validate_manifest,
    validate_payload,
)
from revocompute.db import TaskDatabase

OPENAPI = openapi_spec()
VIEW_PLUGINS = set(OPENAPI["components"]["schemas"]["ResultView"]["properties"]["plugin"]["enum"])
ARTIFACT_ROLES = set(OPENAPI["components"]["schemas"]["Artifact"]["properties"]["role"]["enum"])
ARTIFACT_CAPABILITIES = set(OPENAPI["components"]["schemas"]["Artifact"]["properties"]["capability"]["enum"])


def _result_manifests():
    """Return ``(name, canonical manifest)`` for every registered fixture."""
    return [(name, builders.build_result_manifest(result_fixture(name))) for name in sorted(RESULT_FIXTURES)]


def test_every_result_fixture_matches_the_canonical_manifest_schema() -> None:
    names = [name for name, _ in _result_manifests()]
    assert names == sorted(RESULT_FIXTURES)  # every registered fixture is exercised
    for name, manifest in _result_manifests():
        validate_manifest(manifest)
        assert manifest["schema_version"] == 3, name


def test_result_fixtures_use_only_declared_view_and_artifact_vocabulary() -> None:
    for name, manifest in _result_manifests():
        for view in manifest["views"]:
            assert view["plugin"] in VIEW_PLUGINS, (name, view["plugin"])
            assert view["role"] in {"primary", "evidence"}, name
        for artifact in manifest["artifacts"]:
            assert artifact["role"] in ARTIFACT_ROLES, (name, artifact["role"])
            assert artifact["capability"] in ARTIFACT_CAPABILITIES, (name, artifact["capability"])


def test_result_fixtures_cover_each_frontend_rendering_class() -> None:
    required = {
        "minimal_success",
        "text_log",
        "table",
        "matrix",
        "alignment",
        "structure",
        "multi_structure",
        "trajectory",
        "metric_series",
        "large_download_only",
        "nested_tree",
        "partial",
        "failed_diagnostics",
        "archive_pending",
        "archive_ready",
    }
    assert required <= set(RESULT_FIXTURES)


def test_partial_and_failed_fixtures_report_their_own_outcome() -> None:
    partial = builders.build_result_manifest(result_fixture("partial"))
    assert partial["status"] == "finished"
    assert partial["outcome"] == "PARTIAL_SUCCESS"
    assert partial["progress"]["completed_items"] == 1
    assert partial["progress"]["failed_items"] == 1

    failed = builders.build_result_manifest(result_fixture("failed_diagnostics"))
    assert failed["status"] == "failed"
    assert failed["outcome"] == "FAILED"
    assert failed["output_check"]["state"] == "not_assessed"
    assert failed["error"]


def test_catalog_detail_and_parameter_payloads_match_their_schemas() -> None:
    definition = controlled_runner()
    validate_payload("TaskTypeSummary", build_runner_summary(definition))
    validate_payload("TaskCatalog", build_catalog([definition]))
    validate_payload("TaskTypeDetail", build_detail(definition))
    validate_payload("TaskParameterSchema", build_parameter_schema(definition))


def test_scenario_catalog_keeps_runner_order_and_category_projection() -> None:
    extras = [controlled_runner(name=f"method_{index}", display_name=f"Method {index}") for index in range(3)]
    scenario = controlled_scenario().with_catalog(extras)
    catalog = scenario.catalog()
    assert [task["name"] for task in catalog["task_types"]] == ["sequence_demo", "method_0", "method_1", "method_2"]
    assert catalog["categories"] == [{"name": "evolution", "label": "Evolution"}]
    assert scenario.runner_or_none("missing") is None


def test_infrastructure_payload_reports_capacity_per_resource_group() -> None:
    scenario = controlled_scenario().with_readiness("DEGRADED", scheduler_capacity="BUSY", gpu_capacity="UNKNOWN")
    payload = build_infrastructure(scenario.readiness())
    assert payload["status"] == "DEGRADED"
    assert payload["summary"]["scheduler"]["capacity"] == "BUSY"
    assert payload["summary"]["gpu"]["capacity"] == "UNKNOWN"


def test_preflight_fixtures_use_only_supported_response_codes() -> None:
    expected = {
        "valid": 200,
        "warning": 200,
        "capacity_busy": 200,
        "invalid_security": 400,
        "invalid_contract": 400,
        "access_denied": 403,
        "gpu_credit_exhausted": 403,
        "runner_not_ready": 503,
        "infrastructure_not_ready": 503,
    }
    assert set(PREFLIGHT_FIXTURES) == set(expected)
    scenario = controlled_scenario()
    for name, status in expected.items():
        payload, code = scenario.with_preflight(name).preflight_response(scenario.runner)
        assert code == status, name
        assert payload["valid"] == (status == 200), name
        assert payload["admission"]["allowed"] == (status == 200), name
        assert bool(payload["errors"]) == (status != 200), name
        assert bool(payload["warnings"]) == (name in {"warning", "capacity_busy"}), name


def test_lifecycle_advances_by_poll_count_and_stops_at_the_last_state() -> None:
    scenario = controlled_scenario().with_lifecycle("queued", "running", "finished")
    states = [scenario.task_status_payload("0123456789abcdef0123456789abcdef", index)[2] for index in range(5)]
    assert states == ["queued", "running", "finished", "finished", "finished"]
    assert [TaskDatabase.STOP_POLLING_STATUSES.__contains__(state) for state in states] == [False, False, True, True, True]


def test_result_is_available_only_once_the_lifecycle_reaches_a_terminal_state() -> None:
    task_id = "0123456789abcdef0123456789abcdef"
    scenario = controlled_scenario().with_lifecycle("queued", "running", "finished").with_result("text_log")
    assert scenario.result_available_at(0, task_id) is False
    assert scenario.result_available_at(1, task_id) is False
    assert scenario.result_available_at(2, task_id) is True
    assert scenario.result_for("ffffffffffffffffffffffffffffffff") is None

    without_result = controlled_scenario().with_lifecycle("finished")
    assert without_result.result_manifest() is None
    assert without_result.summary_payloads()[0]["result"]["available"] is False


def test_task_status_and_summary_payloads_match_their_schemas() -> None:
    task_id = "0123456789abcdef0123456789abcdef"
    scenario = controlled_scenario()
    validate_payload("TaskStatus", build_task_status(task_id, scenario.runner, "running"))
    for status in ("queued", "running", "finished", "failed", "cancelled"):
        validate_payload("TaskSummary", build_task_summary(task_id, scenario.runner, status=status, result_available=False))


def test_access_scenarios_project_the_canonical_runner_access_shape() -> None:
    states = {
        "open": AccessState.open(),
        "requestable": AccessState.requestable_policy(),
        "pending": AccessState.pending_policy(),
        "granted": AccessState.granted_policy(),
        "denied": AccessState.denied_policy(),
    }
    for name, access in states.items():
        validate_payload("TaskCatalogAccess", builders.catalog_access_payload(access))
        validate_payload("RunnerAccess", builders.runner_access_payload(access))
        if access.restricted:
            assert builders.runner_access_payload(access)["request_status"] in {None, "pending", "approved", "rejected"}, name
    assert builders.runner_access_payload(AccessState.open()) == {"restricted": False}


def test_authentication_projections_satisfy_the_current_user_schema() -> None:
    for session in (USER_AUTH, ADMIN_AUTH):
        validate_payload("CurrentUser", session.as_user_payload())
        assert session.as_user_payload()["role"] in {"user", "admin"}
    assert ANONYMOUS_AUTH.role in {"anonymous", "expired"}
    assert EXPIRED_AUTH.role == "expired"


def test_reference_scenarios_project_real_runner_vocabulary() -> None:
    gremlin = pssm_gremlin_scenario()
    validate_payload("TaskTypeDetail", gremlin.detail())
    gremlin_manifest = gremlin.result_manifest()
    assert gremlin_manifest is not None
    assert {view["id"] for view in gremlin_manifest["views"]} >= {"apc_couplings", "ranked_pairs", "filtered_alignment"}

    fold = structure_scenario()
    validate_payload("TaskTypeDetail", fold.detail())
    assert fold.detail()["gpus"] is True
    assert [stage["requires_gpu"] for stage in fold.detail()["workflow"]] == [False, True, True]
    assert fold.result_manifest() is not None


def test_request_capture_answers_semantic_questions_about_a_form_post() -> None:
    body = (
        b"--X\r\nContent-Disposition: form-data; name=\"task_type\"\r\n\r\nsequence_demo\r\n"
        b"--X\r\nContent-Disposition: form-data; name=\"workspace\"\r\n\r\n"
        b'{"version": 2, "capabilities": {"design_regions": {"mode": "binder"}}}\r\n'
        b"--X\r\nContent-Disposition: form-data; name=\"files\"; filename=\"sample.fasta\"\r\n"
        b"Content-Type: text/plain\r\n\r\n>sample\nACDEFG\n\r\n--X--\r\n"
    )
    capture = RequestCapture(
        [
            RequestRecord("POST", "https://example.test/compute/api/preflight/sequence_demo", "/compute/api/preflight/sequence_demo", "", body),
            RequestRecord("POST", "https://example.test/compute/api/post", "/compute/api/post", "", body),
            RequestRecord("GET", "https://example.test/compute/api/running/abc", "/compute/api/running/abc", "", b""),
        ]
    )
    submitted = capture.submit()[0]
    assert submitted.form_fields()["task_type"] == "sequence_demo"
    assert submitted.workspace_capabilities() == {"design_regions": {"mode": "binder"}}
    assert submitted.uploaded_files()[0][1] == "sample.fasta"
    assert len(capture.preflight("sequence_demo")) == 1
    assert len(capture.preflight("other")) == 0
    assert len(capture.status_polls("abc")) == 1
    assert capture.result_manifest("abc") == ()
    assert not capture.navigation()
