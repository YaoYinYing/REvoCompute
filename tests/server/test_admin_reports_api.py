# Copyright © 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The authorization and bounding boundary around the Admin read model.

``revocompute.admin_reports`` owns no route: an Admin HTTP handler authorizes the
caller, parses a bounded request, and calls the facade.  These cases pin that
boundary against the real Flask application — anonymous, non-admin, and admin,
and the fact that an over-large or malformed request is refused rather than
served unbounded.
"""

from __future__ import annotations

import io
import json
from types import SimpleNamespace

from conftest import _admin_client_auth, _load_pssm_module, _test_client_auth
from jsonschema import Draft202012Validator

REPORT_PATHS = (
    "/compute/api/auth/admin/reports/tasks",
    "/compute/api/auth/admin/reports/resources",
    "/compute/api/auth/admin/reports/integrity",
    "/compute/api/auth/admin/reports/activity",
)


def _assert_matches_openapi(spec, schema_name, payload):
    """The published contract must accept the body the handler actually served.

    The generated TypeScript types are lenient about pre-existing differences, so
    they cannot catch a schema that rejects every real response.  Validating the
    served body against the server's own component is what keeps the single
    server-owned contract true of what goes on the wire.
    """
    validator = Draft202012Validator(
        {"$ref": f"#/components/schemas/{schema_name}", "components": spec["components"]}
    )
    errors = list(validator.iter_errors(payload))
    assert not errors, [error.message for error in errors]


def _module(monkeypatch, tmp_path):
    return _load_pssm_module(
        monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"}
    )


def test_every_admin_report_path_requires_an_administrator(monkeypatch, tmp_path):
    """Anonymous is authenticated-for, a non-admin is refused, an admin reads.

    The read model exposes every subject's position and the deployment's drift, so
    the boundary is the same one every other Admin read uses rather than a second
    authorization story.
    """
    module = _module(monkeypatch, tmp_path)
    client = module.app.test_client()
    regular = _test_client_auth(module)
    admin = _admin_client_auth(module)

    for path in REPORT_PATHS:
        assert client.get(path).status_code == 401, path
        assert client.get(path, headers=regular).status_code == 403, path
        assert client.get(path, headers=admin).status_code == 200, path


def test_an_over_large_report_limit_is_clamped_to_the_ceiling_and_labelled(monkeypatch, tmp_path):
    """A page size above the ceiling is clamped, and the response says so.

    Clamping rather than refusing matters because a client asking for more than
    the deployment serves has made no error an operator must act on — but the page
    must not read as the whole fleet, so the ceiling is reported beside it.  A
    value that is not a page size at all is a real mistake and is refused.
    """
    module = _module(monkeypatch, tmp_path)
    client = module.app.test_client()
    admin = _admin_client_auth(module)

    oversized = client.get(f"{REPORT_PATHS[0]}?limit=100000", headers=admin)
    assert oversized.status_code == 200
    window = oversized.get_json()["window"]
    assert window["limit"] == window["limit_ceiling"] == oversized.get_json()["limit_ceiling"] == 200

    accepted = client.get(f"{REPORT_PATHS[0]}?limit=25", headers=admin)
    assert accepted.status_code == 200
    assert accepted.get_json()["window"]["limit"] == 25

    not_a_number = client.get(f"{REPORT_PATHS[0]}?limit=all", headers=admin)
    assert not_a_number.status_code == 400
    assert "limit" in not_a_number.get_json()["error"]

    # ``str.isdigit()`` accepts digits outside ASCII that ``int()`` rejects: the
    # page-size contract must answer those with its own bounded refusal rather
    # than letting the conversion raise.
    for raw in ("²", "①", "٥", "0" * 4000):
        lookalike = client.get(f"{REPORT_PATHS[0]}?limit={raw}", headers=admin)
        assert lookalike.status_code in (400, 200), raw
        if lookalike.status_code == 400:
            assert "limit" in lookalike.get_json()["error"], raw


def test_a_malformed_report_filter_is_refused_with_a_bounded_error(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    client = module.app.test_client()
    admin = _admin_client_auth(module)

    bad_subject = client.get(f"{REPORT_PATHS[1]}?subject=not-a-user", headers=admin)
    assert bad_subject.status_code == 400

    bad_since = client.get(f"{REPORT_PATHS[3]}?since=whenever", headers=admin)
    assert bad_since.status_code == 400

    # A non-finite timestamp cannot be serialized as standard JSON, so a body that
    # carried it would be a 200 no client could parse.
    for raw in ("NaN", "Infinity", "1e400"):
        nonfinite = client.get(f"{REPORT_PATHS[3]}?since={raw}", headers=admin)
        assert nonfinite.status_code == 400, raw


def test_a_non_admin_cannot_read_another_subjects_canonical_projection(monkeypatch, tmp_path):
    """The facts the read model composes are admin-only on the wire."""
    module = _module(monkeypatch, tmp_path)
    client = module.app.test_client()
    regular = _test_client_auth(module)
    admin = _admin_client_auth(module)
    target = module.app.config["user_db"].get_user_by_username("tester")
    path = f"/compute/api/auth/admin/users/{target['id']}/resource-entitlement"

    assert client.get(path).status_code in (401, 403)
    assert client.get(path, headers=regular).status_code in (401, 403)
    assert client.get(path, headers=admin).status_code == 200


def test_the_task_report_reads_the_recorded_decision_rather_than_a_recomputation(monkeypatch, tmp_path):
    """The Admin report and the submission agree about one Task's class.

    The Task is submitted through the real HTTP path, then read back through the
    Admin report.  The class the report names is the class the submission
    recorded, which is the property an operator relies on when asking why a Task
    is on a queue.
    """
    module = _module(monkeypatch, tmp_path)
    monkeypatch.setattr(
        module.run_compute_task,
        "apply_async",
        lambda *args, **kwargs: SimpleNamespace(id="celery-dispatch-id"),
    )
    client = module.app.test_client()
    admin = _admin_client_auth(module)

    submitted = client.post(
        "/compute/api/post",
        headers=_test_client_auth(module),
        data={
            "task_type": "cpu_runner",
            "files": (io.BytesIO(b">sequence\nACDEFGHIK\n"), "sequence.fasta"),
            "input_roles": "sequence",
        },
        content_type="multipart/form-data",
    )
    assert submitted.status_code in {200, 201, 202, 302}, submitted.get_data(as_text=True)

    recorded = json.loads(module.task_store.list_tasks()[0]["input_form"])["placement_decision"]
    report = client.get(REPORT_PATHS[0], headers=admin).get_json()
    entry = next(item for item in report["tasks"] if item["task_id"] == module.task_store.list_tasks()[0]["md5sum"])

    assert entry["placement"]["state"] == "recorded"
    assert entry["placement"]["reason_code"] == recorded["reason_code"]
    execution = recorded["execution_class"]
    expected_id = (
        f"{execution['state']}|{execution['partition'] or 'scheduler-default'}|"
        + (f"{execution['device_class'] or 'untyped'}x{execution['device_count']}" if execution["state"] == "accelerator" else "none")
    )
    assert entry["placement"]["execution_class_id"] == expected_id
    assert entry["placement"]["policy_revision"] == recorded["policy_revision"]


def test_every_report_body_matches_the_server_owned_schema(monkeypatch, tmp_path):
    """Each report the server serves validates against its own published schema.

    The Admin read model is projected through the API, and the API's single source
    of truth for a response shape is ``openapi.json`` — which the frontend also
    generates its types from.  A schema that rejects the body the handler actually
    serves is a contract defect whether or not a lenient type generator hides it,
    so the served bodies are validated against the components verbatim, in both
    the deployment-scope and subject-scope shapes the resource report can take.
    """
    module = _module(monkeypatch, tmp_path)
    client = module.app.test_client()
    admin = _admin_client_auth(module)
    spec = client.get("/openapi.json").get_json()

    roll = client.get(REPORT_PATHS[1], headers=admin).get_json()
    _assert_matches_openapi(spec, "AdminResourceReport", roll)
    assert roll["scope"] == "deployment"

    subject = client.get(f"{REPORT_PATHS[1]}?subject=1", headers=admin).get_json()
    _assert_matches_openapi(spec, "AdminResourceReport", subject)
    assert subject["scope"] == "subject"

    for path, schema in (
        (REPORT_PATHS[0], "AdminTaskReport"),
        (REPORT_PATHS[2], "AdminIntegrityReport"),
        (REPORT_PATHS[3], "AdminActivityReport"),
    ):
        _assert_matches_openapi(spec, schema, client.get(path, headers=admin).get_json())
