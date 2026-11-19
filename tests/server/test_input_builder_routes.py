# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Application routes for the pinned workbench and the optional Studio gateway."""

from __future__ import annotations

import io
import json

from conftest import _load_pssm_module, _test_client_auth
from revocompute import atomworks


def _bionuta_tree(root):
    (root / "integration" / "input-builder").mkdir(parents=True)
    (root / "index.html").write_text("<html>workbench</html>", encoding="utf-8")
    (root / "integration" / "input-builder" / "index.mjs").write_text("export function mount() {}", encoding="utf-8")
    return root


def test_bionuta_assets_require_login_are_same_origin_and_refuse_traversal(monkeypatch, tmp_path):
    tree = _bionuta_tree(tmp_path / "bionuta")
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"REVOCOMPUTE_BIONUTA_ROOT": str(tree), "RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    client = module.app.test_client()
    auth = _test_client_auth(module)

    assert client.get("/compute/bionuta/index.html").status_code == 401
    served = client.get("/compute/bionuta/index.html", headers=auth)
    assert served.status_code == 200
    assert served.get_data(as_text=True) == "<html>workbench</html>"
    policy = served.headers["Content-Security-Policy"]
    assert "connect-src 'self'" in policy and "frame-ancestors 'self'" in policy
    assert served.headers["Cross-Origin-Resource-Policy"] == "same-origin"
    assert served.headers["X-Content-Type-Options"] == "nosniff"
    adapter = client.get("/compute/bionuta/integration/input-builder/index.mjs", headers=auth)
    assert adapter.status_code == 200
    detail = client.get("/compute/api/types/builder_runner", headers=auth).get_json()
    builder = detail["input_workspace"]["builders"][0]
    assert builder["id"] == "bionuta"
    assert builder["available"] is True
    assert builder["targets"]["alphafold3"] == "json"
    assert builder["adapter_path"] == "/compute/bionuta/integration/input-builder/index.mjs"
    for path in (
        "/compute/bionuta/..%2fserver.py",
        "/compute/bionuta/%2e%2e/server.py",
        "/compute/bionuta/missing.js",
    ):
        assert client.get(path, headers=auth).status_code == 404


def test_atomworks_gateway_scopes_sessions_to_their_owner(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch, tmp_path, extra_env={"REVOCOMPUTE_ATOMWORKS_STUDIO_URL": "http://studio.test", "RUNNER_UID": "1234", "RUNNER_GID": "5678"}
    )
    client = module.app.test_client()
    first = _test_client_auth(module, "first")
    second = _test_client_auth(module, "second")
    calls: list[tuple[str, str]] = []
    sid = "s" * 32

    def fake_forward(base, method, path, **kwargs):
        calls.append((method, path))
        if method == "POST" and path == "/api/sessions":
            return 200, "application/json", json.dumps(
                {"session_id": sid, "editor_path": f"/?session={sid}&embed=1", "structure": {}}
            ).encode(), {}
        if method == "GET" and path == f"/api/sessions/{sid}":
            return 200, "application/json", b'{"ok":true}', {}
        if method == "DELETE":
            return 204, "text/plain", b"", {}
        return 404, "text/plain", b"missing", {}

    monkeypatch.setattr(atomworks, "forward", fake_forward)

    assert client.post("/api/sessions", data={}).status_code == 401
    created = client.post(
        "/api/sessions",
        headers=first,
        data={"file": (io.BytesIO(b"data_1\n#\n"), "start.cif")},
        content_type="multipart/form-data",
    )
    assert created.status_code == 200
    payload = created.get_json()
    assert payload["session_id"] == sid
    assert payload["editor_path"] == f"/compute/atomworks/?session={sid}&embed=1"

    # The owner reads its own session; another signed-in caller sees a missing
    # session and the gateway never forwards the guessed request upstream.
    before = list(calls)
    assert client.get(f"/api/sessions/{sid}", headers=second).status_code == 404
    assert calls == before
    assert client.get(f"/api/sessions/{sid}", headers=first).status_code == 200

    # An unlisted route is not a proxy, even for the owner.
    assert client.get("/api/secret", headers=first).status_code == 404
    assert client.get(f"/api/sessions/{'z' * 32}", headers=first).status_code == 404

    # A cross-site mutation is refused before it reaches the service.
    before = list(calls)
    cross_site = client.post(
        f"/api/sessions/{sid}/export",
        headers={**first, "Origin": "https://evil.invalid", "Sec-Fetch-Site": "cross-site"},
        json={},
    )
    assert cross_site.status_code == 403
    assert calls == before

    assert client.delete(f"/api/sessions/{sid}", headers=first).status_code == 204
    assert client.get(f"/api/sessions/{sid}", headers=first).status_code == 404


def test_atomworks_gateway_is_absent_without_a_configured_service(monkeypatch, tmp_path):
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"REVOCOMPUTE_ATOMWORKS_STUDIO_URL": None, "RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    client = module.app.test_client()
    auth = _test_client_auth(module)
    assert client.get("/api/health", headers=auth).status_code == 404
    assert client.get("/compute/atomworks/", headers=auth).status_code == 404
