# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Control-plane contracts for the frontend presentation cutover."""

from __future__ import annotations

import hashlib
from pathlib import Path

from conftest import _admin_client_auth, _load_pssm_module, _test_client_auth
from jsonschema import Draft202012Validator
from revocompute.auth import _serializer, send_password_reset_email, send_verification_email


def _install_frontend_entry(module, tmp_path: Path) -> str:
    static_root = tmp_path / "static"
    app_root = static_root / "app"
    app_root.mkdir(parents=True)
    entry = '<!doctype html><html><body><main id="app"></main></body></html>'
    (app_root / "index.html").write_text(entry, encoding="utf-8")
    module.app.static_folder = str(static_root)
    return entry


def _validate_openapi_payload(spec: dict, schema_name: str, payload: object) -> None:
    Draft202012Validator(
        {"$ref": f"#/components/schemas/{schema_name}", "components": spec["components"]},
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    ).validate(payload)


def test_browser_routes_serve_one_inert_entry_with_server_authorization(monkeypatch, tmp_path):
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    entry = _install_frontend_entry(module, tmp_path)
    client = module.app.test_client()

    for path in (
        "/",
        "/api-docs",
        "/compute/login?return_to=https%3A%2F%2Fevil.example",
        "/compute/register",
        "/compute/reset_password",
        "/compute/reset_password?token=domain-state-must-not-be-injected",
        "/compute/user_verify",
        "/compute/user_verify?token=domain-state-must-not-be-injected",
        "/compute/terms",
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert response.get_data(as_text=True) == entry
        assert "domain-state-must-not-be-injected" not in response.get_data(as_text=True)

    user_headers = _test_client_auth(module)
    admin_headers = _admin_client_auth(module)
    assert client.get("/compute/profile").status_code == 401
    assert client.get("/compute/profile", headers=user_headers).get_data(as_text=True) == entry

    for path in ("/compute/user_control", "/compute/configuration", "/compute/logs"):
        assert client.get(path).status_code == 401
        assert client.get(path, headers=user_headers).status_code == 403
        response = client.get(path, headers=admin_headers)
        assert response.status_code == 200
        assert response.get_data(as_text=True) == entry


def test_superseded_browser_assets_are_not_served(monkeypatch, tmp_path):
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    client = module.app.test_client()

    for path in (
        "/static/js/api-docs.js",
        "/static/js/auth-api.js",
        "/static/js/configuration.js",
        "/static/js/error-page.js",
        "/static/js/index-agent-guide.js",
        "/static/js/log-viewer.js",
        "/static/js/login.js",
        "/static/js/profile.js",
        "/static/js/register.js",
        "/static/js/reset-password.js",
        "/static/js/theme-toggle.js",
        "/static/js/theme.js",
        "/static/js/ui.js",
        "/static/js/user-control.js",
        "/static/css/base.css",
        "/static/css/profile.css",
        "/static/css/user-control.css",
        "/compute/logo.svg",
        "/favicon.ico",
    ):
        assert client.get(path).status_code == 404


def test_authenticated_login_redirect_accepts_only_safe_local_return_target(monkeypatch, tmp_path):
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    _install_frontend_entry(module, tmp_path)
    client = module.app.test_client()
    headers = _test_client_auth(module)

    local = client.get(
        "/compute/login?return_to=%2Fcompute%2Fcreate_task%3Ftask_type%3Dgremlin", headers=headers
    )
    assert local.status_code == 302
    assert local.headers["Location"] == "/compute/create_task?task_type=gremlin"

    for unsafe in ("https://evil.example", "//evil.example", "//[", "/\\evil.example", "/%0d%0aLocation:evil"):
        response = client.get("/compute/login", query_string={"return_to": unsafe}, headers=headers)
        assert response.status_code == 302
        assert response.headers["Location"] == "/compute/dashboard"


def test_email_verification_get_is_inert_and_post_owns_mutation(monkeypatch, tmp_path):
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    entry = _install_frontend_entry(module, tmp_path)
    database = module.app.config["user_db"]
    user = database.create_user(username="verifyme", email="verify@test.local", password="pass1234")
    token = _serializer.dumps({"uid": user["id"], "purpose": "verify-email"})
    client = module.app.test_client()

    page = client.get("/compute/user_verify", query_string={"token": token})
    assert page.status_code == 200
    assert page.get_data(as_text=True) == entry
    assert database.get_user(user["id"])["email_verified"] is False

    invalid = client.post("/compute/api/auth/verify-email", json={"token": "invalid"})
    assert invalid.status_code == 400
    assert database.get_user(user["id"])["email_verified"] is False

    verified = client.post("/compute/api/auth/verify-email", json={"token": token})
    assert verified.status_code == 200
    assert verified.json == {
        "email": "verify@test.local",
        "message": "Email address verified.",
        "registration_pending": True,
    }
    assert database.get_user(user["id"])["email_verified"] is True
    assert database.get_user(user["id"])["registration_status"] == "verified"


def test_password_reset_get_is_inert_and_only_api_post_changes_password(monkeypatch, tmp_path):
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    entry = _install_frontend_entry(module, tmp_path)
    database = module.app.config["user_db"]
    user = database.create_user(
        username="resetme",
        email="reset@test.local",
        password="oldpass123",
        registration_status="approved",
        user_status="active",
    )
    database.verify_email(user["id"])
    token = _serializer.dumps(
        {"uid": user["id"], "purpose": "reset-password", "ver": 0, "nonce": "test-nonce"}
    )
    client = module.app.test_client()

    page = client.get("/compute/reset_password", query_string={"token": token})
    assert page.status_code == 200
    assert page.get_data(as_text=True) == entry
    assert client.post("/compute/reset_password", json={"token": token, "password": "newpass456"}).status_code == 405
    assert client.post("/compute/api/auth/login", json={"username": "resetme", "password": "oldpass123"}).status_code == 200

    reset = client.post("/compute/api/auth/reset-password", json={"token": token, "password": "newpass456"})
    assert reset.status_code == 200
    assert reset.json == {"message": "Password updated - you can now log in."}
    assert client.post("/compute/api/auth/login", json={"username": "resetme", "password": "oldpass123"}).status_code == 401
    assert client.post("/compute/api/auth/login", json={"username": "resetme", "password": "newpass456"}).status_code == 200
    assert client.post("/compute/api/auth/reset-password", json={"token": token, "password": "anotherpass"}).status_code == 400


def test_emailed_auth_links_use_configured_origin_and_canonical_token_query(monkeypatch, tmp_path):
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    database = module.app.config["user_db"]
    user = database.create_user(username="mailed", email="mailed@test.local", password="oldpass123")
    sent: list[dict[str, str]] = []

    monkeypatch.setenv("SERVER_BASE_URL", "https://trusted.example")
    monkeypatch.setattr("revocompute.auth._send_email", lambda **message: sent.append(message) or True)

    assert send_verification_email(user) is True
    assert send_password_reset_email(user["email"], database) is True
    assert len(sent) == 2
    for message in sent:
        assert "https://trusted.example/compute/" in message["text"]
        assert "?token=" in message["text"]
        assert "?c=" not in message["text"]


def test_legal_terms_resource_is_bounded_and_comes_from_canonical_markdown(monkeypatch, tmp_path):
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    response = module.app.test_client().get("/compute/api/legal/terms")
    source = (Path(module.__file__).with_name("legal") / "TERMS_OF_SERVICE.md").read_text(encoding="utf-8")

    assert response.status_code == 200
    assert response.json == {
        "document": "terms",
        "version": f"sha256:{hashlib.sha256(source.encode('utf-8')).hexdigest()}",
        "markdown": source,
    }
    assert len(response.data) < 64 * 1024


def test_registration_capability_is_public_and_server_authoritative(monkeypatch, tmp_path):
    disabled = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678", "ENABLE_REGISTER": "false", "SMTP_HOST": "mail"},
    )
    assert disabled.app.test_client().get("/compute/api/auth/registration").json == {
        "enabled": False,
        "email_available": True,
    }

    enabled = _load_pssm_module(
        monkeypatch,
        tmp_path / "enabled",
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678", "ENABLE_REGISTER": "true", "SMTP_HOST": ""},
    )
    assert enabled.app.test_client().get("/compute/api/auth/registration").json == {
        "enabled": True,
        "email_available": False,
    }


def test_frontend_entry_csp_allows_only_local_scripts_styles_and_fonts(monkeypatch, tmp_path):
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    _install_frontend_entry(module, tmp_path)

    csp = module.app.test_client().get("/").headers["Content-Security-Policy"]
    directives = {part.strip().split()[0]: part.strip().split()[1:] for part in csp.split(";") if part.strip()}
    assert directives["script-src"] == ["'self'"]
    assert directives["font-src"] == ["'self'"]
    assert directives["style-src"] == ["'self'", "'unsafe-inline'"]
    assert "'unsafe-eval'" not in csp
    assert "https:" not in csp


def test_openapi_describes_public_auth_and_legal_contracts(monkeypatch, tmp_path):
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    client = module.app.test_client()
    spec = client.get("/openapi.json").get_json()

    expected_methods = {
        "/compute/api/auth/registration": "get",
        "/compute/api/auth/captcha": "get",
        "/compute/api/auth/register": "post",
        "/compute/api/auth/forgot-password": "post",
        "/compute/api/auth/reset-password": "post",
        "/compute/api/auth/resend-verification": "post",
        "/compute/api/auth/verify-email": "post",
        "/compute/api/legal/terms": "get",
    }
    for path, method in expected_methods.items():
        assert method in spec["paths"][path]

    _validate_openapi_payload(
        spec,
        "RegistrationCapability",
        client.get("/compute/api/auth/registration").get_json(),
    )
    _validate_openapi_payload(spec, "LegalDocument", client.get("/compute/api/legal/terms").get_json())
