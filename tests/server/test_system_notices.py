# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Server-owned system notice projection.

The persistent-notice surface is operator-configured and repository-owned: the
server publishes the deployed ``revocompute/legal/SYSTEM_NOTICES.md`` source and
the frontend renders it as text. These cases pin the projection contract — the
empty state, a real notice, the size bound, and OpenAPI conformance — without
reading the frontend or any Markdown wording.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from conftest import _load_pssm_module


def _module(monkeypatch, tmp_path, notices: str | None = None):
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    if notices is not None:
        # Point the route at a test-owned source instead of editing the shipped file.
        source = tmp_path / "SYSTEM_NOTICES.md"
        source.write_text(notices, encoding="utf-8")
        module.app.view_functions["system_notices"].__globals__["_SYSTEM_NOTICES_SOURCE"] = source
    return module


def test_system_notices_is_anonymous_and_empty_when_nothing_is_configured(monkeypatch, tmp_path):
    # A comment-only source (as the shipped file is) announces nothing.
    module = _module(monkeypatch, tmp_path, "<!-- maintenance notices go here -->\n")
    # No Authorization header: the notice surface is public.
    response = module.app.test_client().get("/compute/api/system/notices")

    assert response.status_code == 200
    assert response.json == {"notices": []}


def test_system_notices_publishes_configured_content_addressed_notice(monkeypatch, tmp_path):
    source = "# Maintenance\n\nStorage maintenance on Saturday 02:00-04:00 UTC.\n"
    module = _module(monkeypatch, tmp_path, source)
    client = module.app.test_client()
    response = client.get("/compute/api/system/notices")
    spec = client.get("/openapi.json").get_json()

    assert response.status_code == 200
    notices = response.json["notices"]
    assert len(notices) == 1
    notice = notices[0]
    assert notice["level"] == "info"
    assert notice["body"] == source
    # Identity is content-derived, so editing the notice yields a new identity and
    # a reader who hid the old text is not silently suppressing the new one.
    assert notice["id"] == f"operator-notice-{hashlib.sha256(source.encode('utf-8')).hexdigest()[:12]}"

    _validate_openapi_payload(spec, "SystemNotices", response.json)


def test_system_notices_beyond_the_size_bound_is_unavailable(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path, "x" * (64 * 1024 + 1))
    response = module.app.test_client().get("/compute/api/system/notices")

    assert response.status_code == 503


def test_system_notices_are_declared_in_the_published_contract(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path, "# Notice\n\nbody\n")
    client = module.app.test_client()
    response = client.get("/compute/api/system/notices")
    spec = client.get("/openapi.json").get_json()

    assert spec["paths"]["/compute/api/system/notices"]["get"]["operationId"] == "getSystemNotices"
    _validate_openapi_payload(spec, "SystemNotices", response.json)


def _validate_openapi_payload(spec, component, payload):
    """Validate a response body against its declared OpenAPI schema component."""
    schema = spec["components"]["schemas"][component]
    assert schema.get("additionalProperties") is False
    for key in schema["required"]:
        assert key in payload, f"{component} response is missing required {key!r}"
    assert set(payload) <= set(schema["properties"])
