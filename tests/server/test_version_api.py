# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The authenticated version API and page boundary.

Ordinary signed-in users read the same non-sensitive projection as
administrators; anonymous and invalid credentials get the existing generic API
response and HTML navigation is redirected to sign-in with its deep link
preserved. The response is private and uncached, satisfies the published
OpenAPI contract, and never leaks a host path or credential.
"""

from __future__ import annotations

from conftest import _admin_client_auth, _load_pssm_module, _test_client_auth
from revocompute.contracts import validate_openapi_payload

BUILD_ENV = (
    "REVOCOMPUTE_BUILD_GIT_SHA",
    "REVOCOMPUTE_BUILD_TIME",
    "REVOCOMPUTE_BUILD_ID",
    "REVOCOMPUTE_RELEASE_CHANNEL",
    "REVOCOMPUTE_BASE_VERSION",
)
SHA = "a" * 40


def _module(monkeypatch, tmp_path):
    for name in BUILD_ENV:
        monkeypatch.delenv(name, raising=False)
    return _load_pssm_module(
        monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"}
    )


def _frontend_entry(module, tmp_path) -> str:
    static_root = tmp_path / "static"
    app_root = static_root / "app"
    app_root.mkdir(parents=True)
    entry = '<!doctype html><html><body><main id="app"></main></body></html>'
    (app_root / "index.html").write_text(entry, encoding="utf-8")
    module.app.static_folder = str(static_root)
    return entry


def test_anonymous_api_request_gets_the_generic_json_rejection(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    response = module.app.test_client().get("/compute/api/version")

    assert response.status_code == 401
    assert response.is_json
    assert response.get_json()["error"] == "Authentication required"
    assert "base_version" not in response.get_json()
    assert "Location" not in response.headers


def test_anonymous_html_navigation_redirects_with_the_deep_link(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    _frontend_entry(module, tmp_path)
    response = module.app.test_client().get(
        "/compute/version", headers={"Accept": "text/html"}
    )

    assert response.status_code == 302
    location = response.headers["Location"]
    assert location.startswith("/compute/login?")
    assert "return_to=/compute/version" in location


def test_an_invalid_bearer_credential_is_rejected(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    response = module.app.test_client().get(
        "/compute/api/version", headers={"Authorization": "Bearer not-a-valid-token"}
    )

    assert response.status_code == 401
    assert response.is_json
    assert "base_version" not in response.get_json()


def test_ordinary_users_and_administrators_read_the_same_projection(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    monkeypatch.setenv("REVOCOMPUTE_BUILD_GIT_SHA", SHA)
    monkeypatch.setenv("REVOCOMPUTE_BUILD_TIME", "2026-11-12T10:20:30Z")
    client = module.app.test_client()
    user = client.get("/compute/api/version", headers=_test_client_auth(module))
    admin = client.get("/compute/api/version", headers=_admin_client_auth(module))

    assert user.status_code == admin.status_code == 200
    assert user.get_json() == admin.get_json()
    assert "role" not in user.get_json()


def test_the_version_response_is_private_uncached_and_contract_valid(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    monkeypatch.setenv("REVOCOMPUTE_BUILD_GIT_SHA", SHA)
    monkeypatch.setenv("REVOCOMPUTE_BUILD_TIME", "2026-11-12T10:20:30Z")
    monkeypatch.setenv("REVOCOMPUTE_BUILD_ID", f"{SHA[:7]}-20261112T102030Z")
    response = module.app.test_client().get(
        "/compute/api/version", headers=_test_client_auth(module)
    )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    payload = response.get_json()
    validate_openapi_payload("VersionInfo", payload)

    identity_text = repr({key: value for key, value in payload.items() if key != "changelog"})
    assert "/home/" not in identity_text
    assert "/app/" not in identity_text
    assert "password" not in identity_text.lower()
    assert "secret" not in identity_text.lower()
    assert "authorization" not in identity_text.lower()


def test_a_verified_build_reports_the_display_version_and_full_revision(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    monkeypatch.setenv("REVOCOMPUTE_BUILD_GIT_SHA", SHA)
    payload = module.app.test_client().get(
        "/compute/api/version", headers=_test_client_auth(module)
    ).get_json()

    assert payload["base_version"] == "0.1.0"
    assert payload["app_version"] == "0.1.0+aaaaaaa"
    assert payload["git_sha"] == SHA
    assert payload["revision_status"] == "verified"
    assert payload["release_channel"] == "development"


def test_an_unknown_revision_is_reported_honestly(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    payload = module.app.test_client().get(
        "/compute/api/version", headers=_test_client_auth(module)
    ).get_json()

    assert payload["git_sha"] is None
    assert payload["revision_status"] == "unknown"
    assert payload["app_version"] == "0.1.0+unknown"
    assert payload["built_at"] is None


def test_an_invalid_build_sha_is_not_fabricated_into_a_revision(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    monkeypatch.setenv("REVOCOMPUTE_BUILD_GIT_SHA", "2890609")
    payload = module.app.test_client().get(
        "/compute/api/version", headers=_test_client_auth(module)
    ).get_json()

    assert payload["git_sha"] is None
    assert payload["revision_status"] == "unknown"


def test_a_release_channel_uses_the_base_version_without_a_build_suffix(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    monkeypatch.setenv("REVOCOMPUTE_BUILD_GIT_SHA", SHA)
    monkeypatch.setenv("REVOCOMPUTE_RELEASE_CHANNEL", "release")
    payload = module.app.test_client().get(
        "/compute/api/version", headers=_test_client_auth(module)
    ).get_json()

    assert payload["app_version"] == payload["base_version"] == "0.1.0"
    assert payload["release_channel"] == "release"


def test_the_changelog_is_structured_plain_text_and_bounded(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    payload = module.app.test_client().get(
        "/compute/api/version", headers=_test_client_auth(module)
    ).get_json()
    changelog = payload["changelog"]

    validate_openapi_payload("VersionInfo", payload)
    assert len(changelog["source_sha256"]) == 64
    assert changelog["truncated"] is False
    assert any(section["kind"] == "unreleased" for section in changelog["sections"])
    total = 0
    for section in changelog["sections"]:
        assert section["kind"] in {"unreleased", "development-snapshot", "release"}
        if section["date"] is not None:
            assert len(section["date"]) == 10
        for category in section["categories"]:
            for item in category["items"]:
                assert "<" not in item["text"]
                assert "](http" not in item["text"]
                assert len(item["text"]) <= 500
                assert item["depth"] in {0, 1}
                total += 1
    assert len(changelog["sections"]) <= 50
    assert total <= 1000


def test_build_id_is_null_without_a_verified_revision(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    monkeypatch.setenv("REVOCOMPUTE_BUILD_ID", "untrusted-without-a-commit")
    payload = module.app.test_client().get(
        "/compute/api/version", headers=_test_client_auth(module)
    ).get_json()

    assert payload["git_sha"] is None
    assert payload["build_id"] is None


def test_the_builder_base_version_wins_over_source_and_metadata(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    monkeypatch.setenv("REVOCOMPUTE_BASE_VERSION", "9.9.9")
    payload = module.app.test_client().get(
        "/compute/api/version", headers=_test_client_auth(module)
    ).get_json()

    assert payload["base_version"] == "9.9.9"
    assert payload["app_version"] == "9.9.9+unknown"


def test_a_missing_changelog_is_a_bounded_empty_payload(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    import revocompute.version_info as version_information

    monkeypatch.setattr(
        version_information, "_changelog_candidates", lambda: (tmp_path / "absent-CHANGELOG.md",)
    )
    response = module.app.test_client().get(
        "/compute/api/version", headers=_test_client_auth(module)
    )

    assert response.status_code == 200
    assert response.get_json()["changelog"] == {
        "source_sha256": None,
        "truncated": False,
        "sections": [],
    }


def test_the_version_page_serves_the_shell_at_the_signed_in_boundary(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    entry = _frontend_entry(module, tmp_path)
    client = module.app.test_client()

    anonymous = client.get("/compute/version", headers={"Accept": "application/json"})
    assert anonymous.status_code == 401
    assert "base_version" not in anonymous.get_data(as_text=True)

    for headers in (_test_client_auth(module), _admin_client_auth(module)):
        response = client.get("/compute/version", headers=headers)
        assert response.status_code == 200
        assert response.get_data(as_text=True) == entry
        assert response.headers["Cache-Control"] == "private, no-store"


def test_a_path_like_build_identifier_is_not_served(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    monkeypatch.setenv("REVOCOMPUTE_BUILD_GIT_SHA", SHA)
    monkeypatch.setenv("REVOCOMPUTE_BUILD_ID", "/var/run/registry/secret")
    payload = module.app.test_client().get(
        "/compute/api/version", headers=_test_client_auth(module)
    ).get_json()

    assert payload["git_sha"] == SHA
    assert payload["build_id"] is None
