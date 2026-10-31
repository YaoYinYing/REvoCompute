# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Fleet browser acceptance for the canonical parameter area of a Task.

Two shipped Runners declare parameters but, in their ``task.yaml``, a workspace
whose only capabilities are ``files`` and ``review``: AlphaFold 3 (the reported
case, whose eight parameters were reachable only from the Runner detail) and
OpenDDE (fifteen). The generic browser suite drives synthetic fixtures, so the
server-owned projection those two depend on - the canonical parameter capability
the workspace projection injects, the schema the parameters endpoint serves, and
the submission boundary that accepts the echoed capability id - can only be
exercised against the installed fleet.

This file loads the real TaskTypes through the production discovery path, serves
their own projected bytes to the built frontend, and drives the Create Task
workbench: every declared parameter renders as an editable control, a changed
value is the one the browser posts, and the real preflight endpoint accepts that
submission and echoes it back in ``normalized_params``. Nothing here executes a
Runner, needs a GPU, or makes a scientific claim.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from playwright.sync_api import Page, expect
import pytest

from browser_frontend_assets import result_dist
from conftest import _load_fleet_module, _test_client_auth

pytestmark = pytest.mark.browser

ORIGIN = "https://revocompute.example"
CSP = (
    "default-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; "
    "script-src 'self'; img-src 'self' data: blob:; worker-src 'self' blob:; connect-src 'self' blob:"
)
ROOT = Path(__file__).resolve().parents[3]

# The two shipped parameter-bearing workspaces that declare no parameter area of
# their own, with the input each one needs and the parameter this run edits.
# ``num_steps`` (OpenDDE) and ``num_recycles`` (AlphaFold 3) are integers with no
# enum, so the edit is an ordinary field edit rather than a choice.
CASES = (
    {
        "task_type": "alphafold3",
        "entitlement": "alphafold3_noncommercial",
        "filename": "alphafold3_tiny.json",
        "edit": ("num_recycles", "12"),
    },
    {
        "task_type": "opendde",
        "entitlement": None,
        "filename": "opendde_tiny.json",
        "edit": ("num_steps", "250"),
    },
)


def _install_app(page: Page) -> None:
    """Serve the built frontend bundle for the Create Task workbench."""
    dist = result_dist()
    entry = json.loads((dist / ".vite" / "manifest.json").read_text(encoding="utf-8"))["index.html"]
    styles = "".join(f'<link rel="stylesheet" href="/static/app/{name}">' for name in entry.get("css", []))
    html = (
        '<!doctype html><html lang="en"><head><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="referrer" content="no-referrer">'
        f'{styles}<script type="module" src="/static/app/{entry["file"]}"></script>'
        '</head><body><div id="app"></div></body></html>'
    )
    headers = {
        "Content-Type": "text/html; charset=utf-8",
        "Content-Security-Policy": CSP,
        "Referrer-Policy": "no-referrer",
    }
    page.route(f"{ORIGIN}/compute/create_task**", lambda route: route.fulfill(headers=headers, body=html))
    page.route(f"{ORIGIN}/compute/login**", lambda route: route.fulfill(headers=headers, body=html))

    def static(route):
        relative = route.request.url.split("/static/app/", 1)[1].split("?", 1)[0]
        route.fulfill(path=dist / relative)

    page.route(f"{ORIGIN}/static/app/**", static)
    page.route(f"{ORIGIN}/compute/api/auth/me", lambda route: route.fulfill(json={"id": 1, "username": "tester", "role": "user"}))
    page.route(f"{ORIGIN}/compute/api/auth/token", lambda route: route.fulfill(json={"token": "ephemeral"}))
    page.route(f"{ORIGIN}/compute/api/system/notices", lambda route: route.fulfill(json={"notices": []}))


def _prepare_backend(monkeypatch, tmp_path, *, entitlement: str | None):
    """Load the installed fleet with the GPU admission the real boundary needs."""
    from types import SimpleNamespace

    from revocompute.admission import AdmissionEvidence

    module = _load_fleet_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    module.app.config["manage_db"].resource_set("slurm_enabled", "true")
    route = module.app.view_functions["upload_file"]
    while hasattr(route, "__wrapped__"):
        route = route.__wrapped__
    # Runner availability evidence is a separate concern; this test is about the
    # parameter contract, so the Runner is simply available.
    monkeypatch.setattr(
        "revocompute.admission.resolve_submission_readiness",
        lambda *_args, **_kwargs: AdmissionEvidence(
            {
                "runner_family": "demo_runner",
                "status": "READY",
                "ready": True,
                "reason_code": "READY",
                "message": "ready",
                "next_action": "none",
            }
        ),
    )
    module.app.config["infrastructure_readiness"] = SimpleNamespace(
        report=lambda: {
            "status": "READY",
            "stale": False,
            "summary": {"scheduler": {"capacity": "AVAILABLE"}, "gpu": {"capacity": "AVAILABLE"}},
        },
        admission_block=lambda **kwargs: None,
    )
    user_db = module.app.config["user_db"]
    client = module.app.test_client()
    auth_headers = _test_client_auth(module)
    user = user_db.get_user_by_username("tester")
    user_db.update_user(user["id"], allow_gpu_use=True)
    if entitlement is not None:
        # ``granted_by`` is a user id (the operator who would approve the
        # request); the test user records its own grant, as the access-route
        # tests do.
        user_db.grant_entitlement(user["id"], entitlement, granted_by=user["id"], basis="other")
    return module, client, auth_headers


def _multipart_field(body: bytes, name: str) -> str | None:
    """Return one flat multipart field's value from a captured request body."""
    match = re.search(rf'name="{re.escape(name)}"\r\n\r\n(.*?)\r\n--', body.decode("utf-8", errors="replace"), flags=re.DOTALL)
    return match.group(1) if match else None


def _workspace_capability(body: bytes, capability_id: str) -> object:
    document = json.loads(_multipart_field(body, "workspace") or "{}")
    return document.get("capabilities", {}).get(capability_id)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["task_type"])
def test_a_parameter_less_workspace_renders_and_submits_every_declared_parameter(
    page: Page, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, case: dict
) -> None:
    """The injected canonical area is what the workbench edits and submits."""
    _install_app(page)
    module, client, auth_headers = _prepare_backend(monkeypatch, tmp_path, entitlement=case["entitlement"])
    task_type = case["task_type"]

    detail_response = client.get(f"/compute/api/types/{task_type}", headers=auth_headers)
    assert detail_response.status_code == 200, detail_response.get_data(as_text=True)
    detail = detail_response.get_json()
    parameters_response = client.get(detail["parameters_url"], headers=auth_headers)
    assert parameters_response.status_code == 200
    declared = parameters_response.get_json()["properties"]
    assert declared, f"{task_type} declares no parameters to expose"

    # The workspace the manifest declares owns no parameter area; the projection
    # supplies the canonical one in the terminal step ahead of `review`.
    owners = [
        capability
        for step in detail["input_workspace"]["steps"]
        for capability in step["capabilities"]
        if capability["plugin"] == "parameters"
    ]
    assert len(owners) == 1, f"{task_type} must project exactly one parameter area"
    assert detail["input_workspace"]["steps"][-1]["capabilities"][-1]["plugin"] == "review"
    assert detail["input_workspace"]["plugins"] == []

    # The catalog and detail bytes are the ones the signed-in user receives, so a
    # restricted Runner's access state carries the grant the test recorded rather
    # than the anonymous projection.
    catalog_response = client.get("/compute/api/types", headers=auth_headers)
    page.route(f"{ORIGIN}/compute/api/types", lambda route: route.fulfill(json=catalog_response.get_json()))
    page.route(f"{ORIGIN}/compute/api/types/{task_type}", lambda route: route.fulfill(json=detail))
    page.route(f"{ORIGIN}{detail['parameters_url']}", lambda route: route.fulfill(json=parameters_response.get_json()))

    captured: list[tuple[bytes, str]] = []

    def preflight(route) -> None:
        """Forward the browser's own multipart body to the real endpoint."""
        body = route.request.post_data_buffer or b""
        content_type = route.request.headers.get("content-type", "")
        captured.append((body, content_type))
        response = client.post(
            f"/compute/api/preflight/{task_type}",
            headers={**auth_headers, "Content-Type": content_type},
            data=body,
        )
        route.fulfill(status=response.status_code, content_type="application/json", body=response.get_data())

    page.route(f"{ORIGIN}/compute/api/preflight/{task_type}", preflight)
    # Submission is exercised elsewhere; the flow stops on a server error so the
    # workbench stays mounted for the post-preflight assertions.
    page.route(f"{ORIGIN}/compute/api/post", lambda route: route.fulfill(status=500, json={"error": "not exercised"}))

    page.goto(f"{ORIGIN}/compute/create_task?task_type={task_type}")
    expect(page.locator(".ct-workbench")).to_be_visible()

    # Every declared, user-editable parameter is a control the user can edit -
    # nothing the owning task.yaml publishes is left behind on the detail page.
    for name in declared:
        expect(page.locator(f'[data-ct-parameter="{name}"]')).to_have_count(1)

    # A declared calendar-date format is the browser's own date control, holding
    # the declared default, rather than a bare text field.
    date_field = page.locator('[data-ct-parameter="max_template_date"]')
    if task_type == "alphafold3":
        expect(date_field).to_have_attribute("type", "date")
        expect(date_field).to_have_value(declared["max_template_date"]["default"])

    page.locator('input[type="file"]').first.set_input_files(
        {"name": case["filename"], "mimeType": "application/json",
         "buffer": (ROOT / "tests" / "data" / "json" / case["filename"]).read_bytes()}
    )
    name, value = case["edit"]
    page.locator(f'[data-ct-parameter="{name}"]').fill(value)
    expect(page.locator(".ct-validation-row.error")).to_have_count(0)

    page.get_by_role("button", name="Run task", exact=True).click()
    expect(page.locator(".ct-status")).to_contain_text("Submission failed")
    body, content_type = captured[0]
    # The edited value is the one the browser posts, under the server's own flat
    # `params[...]` field name.
    assert _multipart_field(body, f"params[{name}]") == value
    # The workspace echoes the capability the projection published - the id the
    # submission boundary served is the id it accepts back - and carries the
    # parameter values the workbench collected under it.
    echoed = _workspace_capability(body, owners[0]["id"])
    assert isinstance(echoed, dict) and echoed[name] == value, echoed
    # ...and the real endpoint accepted that exact browser body and resolved the
    # edited value back into the normalized parameter contract.
    response = client.post(
        f"/compute/api/preflight/{task_type}",
        headers={**auth_headers, "Content-Type": content_type},
        data=body,
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    payload = response.get_json()
    assert payload["valid"] is True, payload
    assert payload["normalized_params"][name] == int(value)
    assert payload["contract"] == {"status": "passed"}
    assert module.task_store.list_tasks() == []
