# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Direct browser navigation to every Administration page on the real server.

The frontend fixture harness answers page requests with its own HTML document, so
it cannot answer whether a production page route exists.  This contract asks the
question the harness cannot: it serves the *real* application over HTTP with the
*real* built frontend bundle, hands each Administration URL to Chrome, and
asserts what the real server answered — the shell for an administrator, the
sign-in boundary for an anonymous visitor, and the 403 shell for a signed-in
non-administrator.

``tests/server/test_admin_page_routes.py`` owns the parity contract between the
shell's declared Administration destinations and the registered Flask routes.
This file owns the browser behavior; it fails the day a destination the
navigation links to stops being served, or stops rendering the shell.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import Page, expect
import pytest

from conftest import _load_pssm_module
from browser_frontend_assets import result_dist
from revocompute.admin_pages import ADMIN_PAGE_ROUTES
from revocompute.auth import generate_token

pytestmark = pytest.mark.browser


class _WsgiHandler(BaseHTTPRequestHandler):
    """A minimal WSGI transport for one Flask application.

    The browser has to reach the application over real HTTP — a page route is a
    document the browser loads, and the authentication boundary is a cookie the
    transport carries — so the requests are served by the application's own WSGI
    callable rather than by its test client.
    """

    application = None

    def do_GET(self) -> None:  # noqa: N802 - http.server's own spelling
        self._serve("GET")

    def do_POST(self) -> None:  # noqa: N802 - http.server's own spelling
        self._serve("POST")

    def _serve(self, method: str) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        parsed = urlsplit(self.path)
        environ = {
            "REQUEST_METHOD": method,
            "SCRIPT_NAME": "",
            "PATH_INFO": parsed.path,
            "QUERY_STRING": parsed.query,
            "SERVER_NAME": "127.0.0.1",
            "SERVER_PORT": str(self.server.server_address[1]),
            "SERVER_PROTOCOL": "HTTP/1.1",
            "REMOTE_ADDR": "127.0.0.1",
            "CONTENT_TYPE": self.headers.get("Content-Type") or "",
            "CONTENT_LENGTH": str(length),
            "wsgi.version": (1, 0),
            "wsgi.url_scheme": "http",
            "wsgi.input": BytesIO(body),
            "wsgi.errors": BytesIO(),
            "wsgi.multithread": True,
            "wsgi.multiprocess": False,
            "wsgi.run_once": False,
            "HTTP_HOST": self.headers.get("Host") or "127.0.0.1",
        }
        for header, value in self.headers.items():
            key = header.upper().replace("-", "_")
            if key in {"CONTENT_TYPE", "CONTENT_LENGTH"}:
                continue
            environ[f"HTTP_{key}"] = value
        status_holder: dict[str, str] = {}
        payload: list[bytes] = []

        def start_response(status: str, headers: list[tuple[str, str]], _exc_info=None) -> None:
            status_holder["status"] = status
            status_holder["headers"] = json.dumps(headers)

        for chunk in self.application(environ, start_response):
            payload.append(chunk)
        self.send_response(int(status_holder["status"].split()[0]))
        for name, value in json.loads(status_holder["headers"]):
            self.send_header(name, value)
        self.send_header("Content-Length", str(sum(len(chunk) for chunk in payload)))
        self.end_headers()
        for chunk in payload:
            self.wfile.write(chunk)

    def log_message(self, *args: object) -> None:  # keep the test log quiet
        return


def _serve_application(module) -> tuple[ThreadingHTTPServer, str]:
    _WsgiHandler.application = module.app
    server = ThreadingHTTPServer(("127.0.0.1", 0), _WsgiHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def _cookie_for(module, username: str, password: str) -> dict[str, str]:
    """Sign in through the real login API and take the session cookie value."""
    response = module.app.test_client().post(
        "/compute/api/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    for header in response.headers.getlist("Set-Cookie"):
        if header.startswith("auth_token="):
            return {"name": "auth_token", "value": header.split(";", 1)[0].split("=", 1)[1]}
    raise AssertionError("login did not issue an auth_token cookie")


def _admin_credentials(module) -> tuple[str, str]:
    db = module.app.config["user_db"]
    user = db.create_user(
        username="page-route-admin",
        email="page-route-admin@test.local",
        password="admin-password",
        role="admin",
        registration_status="approved",
        user_status="active",
    )
    db.verify_email(user["id"])
    return "page-route-admin", "admin-password"


def _install_frontend_bundle(module, tmp_path: Path) -> None:
    static_root = tmp_path / "static"
    static_root.mkdir()
    (static_root / "app").symlink_to(result_dist(), target_is_directory=True)
    module.app.static_folder = str(static_root)


def test_administration_pages_answer_real_browser_navigation(monkeypatch, tmp_path, page: Page) -> None:
    module = _load_pssm_module(
        monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"}
    )
    _install_frontend_bundle(module, tmp_path)
    username, password = _admin_credentials(module)
    admin_cookie = _cookie_for(module, username, password)
    # A signed-in ordinary user, established through the same real login path.
    user_db = module.app.config["user_db"]
    ordinary = user_db.create_user(
        username="page-route-user",
        email="page-route-user@test.local",
        password="user-password",
        registration_status="approved",
        user_status="active",
    )
    user_db.verify_email(ordinary["id"])
    user_cookie = _cookie_for(module, "page-route-user", "user-password")

    server, origin = _serve_application(module)
    try:
        for path, _ in ADMIN_PAGE_ROUTES:
            # Anonymous: the server's own login redirect is the boundary, and the
            # browser lands on the sign-in page carrying the destination back.
            page.context.clear_cookies()
            response = page.goto(f"{origin}{path}")
            assert response is not None and response.status == 200
            assert response.url.startswith(f"{origin}/compute/login?return_to="), response.url
            assert urlsplit(response.url).query == f"return_to={path}"
            expect(page.get_by_role("button", name="Sign in", exact=True)).to_be_visible()

            # Signed-in non-administrator: the server answers the shell with 403,
            # and the frontend renders its own access-denied state.
            page.context.clear_cookies()
            page.context.add_cookies([{**user_cookie, "url": origin}])
            response = page.goto(f"{origin}{path}")
            assert response is not None and response.status == 403, f"{path} must 403 a non-administrator"
            expect(page.locator(".route-error")).to_contain_text("403")

            # Administrator: the page route serves the shell and renders the view.
            page.context.clear_cookies()
            page.context.add_cookies([{**admin_cookie, "url": origin}])
            response = page.goto(f"{origin}{path}")
            assert response is not None and response.status == 200, f"{path} must serve an administrator"
            expect(page.locator(".app-shell")).to_be_visible()
            expect(page.locator("[data-nav-group='admin'] a[aria-current='page']")).to_have_attribute(
                "href", path
            )
    finally:
        server.shutdown()
        server.server_close()


def test_runner_fleet_direct_refresh_renders_the_fleet_view(monkeypatch, tmp_path, page: Page) -> None:
    """The reported regression: a direct load and refresh of the fleet page."""
    module = _load_pssm_module(
        monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"}
    )
    _install_frontend_bundle(module, tmp_path)
    username, password = _admin_credentials(module)
    page.context.add_cookies([{**_cookie_for(module, username, password), "url": "http://127.0.0.1"}])

    server, origin = _serve_application(module)
    try:
        for _ in range(2):
            response = page.goto(f"{origin}/compute/runner_fleet")
            assert response is not None and response.status == 200
            expect(page.get_by_role("heading", name="Runner fleet", level=1)).to_be_visible()
    finally:
        server.shutdown()
        server.server_close()
