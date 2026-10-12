# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The closed set of Account page destinations the server serves.

The shell links to each of the user's own Account sections directly, and the
server serves each one as a page. A section the navigation reaches without a
registered page route is a production 404 — direct navigation and a browser
refresh both fail — so the declaration lives in exactly one server-owned place
and is registered through exactly one view, rather than as near-identical
handlers that can drift apart.

``frontend/src/app/router.ts`` is the frontend half of this declaration;
``tests/server/test_account_page_routes.py`` holds the two together.

The authorization boundary is the Account's own, not the shell's: the sections
serve the same frontend shell as ``/compute/profile`` and require a signed-in
user (``login_required``), exactly as the Account root does.
"""

from __future__ import annotations

from typing import Any, Callable

from flask import Flask

from revocompute.auth import login_required

#: The Account sections that are not the Account root. ``/compute/profile`` stays
#: the first section's page; every other section has its own address so it can be
#: linked, bookmarked, refreshed and shared on its own.
ACCOUNT_SECTION_SLUGS: tuple[str, ...] = (
    "security",
    "api-key",
    "runner-access",
    "gpu-credits",
    "metrics",
)


def register_account_pages(app: Flask, serve_entry: Callable[..., Any]) -> None:
    """Register every Account section route against one shared view.

    ``serve_entry`` is the application's own inert frontend-shell server, passed
    in rather than imported so this module never depends on the routing module
    that calls it.
    """

    @login_required
    def _serve_account_page():
        return serve_entry(private=True)

    for slug in ACCOUNT_SECTION_SLUGS:
        app.add_url_rule(
            f"/compute/account/{slug}",
            endpoint=f"account_{slug.replace('-', '_')}_page",
            view_func=_serve_account_page,
            methods=["GET"],
        )
