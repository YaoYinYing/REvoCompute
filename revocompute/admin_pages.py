# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The closed set of Administration page destinations the server serves.

The frontend shell navigates to these destinations and the server serves each
one as a page.  A destination the navigation links to without a registered page
route is a production 404 — direct navigation and a browser refresh both fail —
so the declaration lives in exactly one server-owned place and is registered
through exactly one view, rather than as four near-identical handlers that can
drift apart.

The authorization boundary is the server's, not the shell's, and it is the same
for every destination: an administrator receives the frontend shell, an
authenticated non-administrator receives the same shell with a 403 status, and an
unauthenticated browser is sent to sign in by ``login_required``.

``frontend/src/app/admin-destinations.ts`` is the frontend half of this
declaration; ``tests/server/test_admin_page_routes.py`` holds the two together.
"""

from __future__ import annotations

from typing import Any, Callable

from flask import Flask, g

from revocompute.auth import login_required

#: Every Administration destination, in navigation order, paired with the
#: endpoint name Flask registers for it.
ADMIN_PAGE_ROUTES: tuple[tuple[str, str], ...] = (
    ("/compute/runner_fleet", "runner_fleet_page"),
    ("/compute/user_control", "user_control_page"),
    ("/compute/logs", "log_viewer_page"),
    ("/compute/configuration", "configuration_page"),
)


def register_admin_pages(app: Flask, serve_entry: Callable[..., Any]) -> None:
    """Register every Administration page route against one shared view.

    ``serve_entry`` is the application's own inert frontend-shell server, passed
    in rather than imported so this module never depends on the routing module
    that calls it.
    """

    @login_required
    def _serve_admin_page():
        if g.current_user.get("role") != "admin":
            return serve_entry(private=True, status=403)
        return serve_entry(private=True)

    for path, endpoint in ADMIN_PAGE_ROUTES:
        app.add_url_rule(path, endpoint=endpoint, view_func=_serve_admin_page, methods=["GET"])
