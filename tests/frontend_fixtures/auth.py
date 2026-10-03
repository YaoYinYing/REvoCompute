# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Deterministic authentication projections for browser fixtures.

The harness fakes the *response* to an authentication attempt, not the
authentication itself: a browser fixture proves how the frontend reacts to a
401 or to an administrator's session, while server-side credential handling
stays with the server tests.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

DEFAULT_USERNAME = "tester"
DEFAULT_FULL_NAME = "Test Scientist"


@dataclass(frozen=True, slots=True)
class Session:
    """A deterministic authentication projection.

    ``anonymous`` fails the current-user projection the way a signed-out browser
    does; ``expired`` fails a request from a session that was already
    established, which is what the frontend turns into a return_to redirect.
    """

    role: str = "session"
    username: str = DEFAULT_USERNAME
    full_name: str = DEFAULT_FULL_NAME

    def as_user_payload(self) -> dict[str, str | None]:
        return {
            "username": self.username,
            "email": f"{self.username}@example.org",
            "email_verified": True,
            "role": "admin" if self.role == "admin" else ("guest" if self.role == "guest" else "user"),
            "full_name": self.full_name,
            "affiliation": "Example Institute",
            "position": "research_assistant",
            "pi_name": "Dr Example",
        }

    def with_role(self, role: str) -> Session:
        return replace(self, role=role)

    def with_name(self, username: str, full_name: str) -> Session:
        return replace(self, username=username, full_name=full_name)


ANONYMOUS_AUTH = Session(role="anonymous", username="anonymous", full_name="")
USER_AUTH = Session(role="session")
ADMIN_AUTH = Session(role="admin", username="admin", full_name="Admin Scientist")
EXPIRED_AUTH = Session(role="expired")
