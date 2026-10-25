# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Parity between the frontend fixture's demo routes and the real demo Server.

``tests/frontend_fixtures/router.py`` reimplements the demo replay routes and
the demo refusal envelopes so browser tests can drive the built frontend without
a Server. Nothing compared those fixture responses to the Server's, so the two
could drift silently. This test boots the real demo Flask app on a synthetic
replay bundle and requires the fixture's preflight refusal and its replay
catalog and manifest responses to be the Server's own responses.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from conftest import _load_pssm_module, _test_client_auth
from demo_replay_fixtures import CAPTURED_ARTIFACT, SYNTHETIC_TASK_TYPE, TABLE_ARTIFACT, write_synthetic_replay_bundle
from frontend_fixtures import FrontendFixtureRouter, controlled_scenario

IDENTITY = {"RUNNER_UID": "1234", "RUNNER_GID": "5678"}
DEMO_ENV = {**IDENTITY, "REVOCOMPUTE_DEMO_MODE": "true", "REVOCOMPUTE_JOB_EXECUTOR": "demo"}
DEMO_ENVIRONMENT = {
    "version": 1,
    "demo_mode": True,
    "execution": "preview_only",
    "notice": "Demo environment: preview and replay only. Tasks are not executed.",
}
SCENARIO_ID = "recorded-demo"
ORIGIN = "https://revocompute.example"


def _install_demo_replays(tmp_path: Path) -> None:
    """Leave the replay index where ``app`` loads it at import."""
    root = tmp_path / "pssm_env" / "demo" / "replays"
    root.mkdir(parents=True, exist_ok=True)
    write_synthetic_replay_bundle(root / f"{SCENARIO_ID}.json")
    index = {
        "version": 1,
        "scenarios": [
            {
                "id": SCENARIO_ID,
                "title": "Recorded summary",
                "summary": "A recorded result for the demo playground.",
                "task_type": SYNTHETIC_TASK_TYPE,
                "bundle": f"{SCENARIO_ID}.json",
            }
        ],
    }
    (root / "index.json").write_text(json.dumps(index), encoding="utf-8")


class _RecordingRoute:
    """A Playwright route stand-in that records one fulfilled fixture response."""

    class _Request:
        def __init__(self, method: str, url: str) -> None:
            self.method = method
            self.url = url
            self.post_data_buffer = b""

    def __init__(self, url: str, method: str) -> None:
        self.request = self._Request(method, url)
        self.status = 200
        self.payload: Any = None

    def fulfill(self, *, status: int = 200, json: Any = None, **_: Any) -> None:
        self.status = status
        self.payload = json


def _fixture_response(router: FrontendFixtureRouter, path: str, method: str = "GET") -> tuple[int, Any]:
    """Dispatch one request through the fixture's real route table."""
    route = _RecordingRoute(f"{ORIGIN}{path}", method)
    router._dispatch(route)
    return route.status, route.payload


def test_demo_fixture_answers_exactly_what_the_real_demo_server_answers(monkeypatch, tmp_path):
    """The fixture's demo refusal and replay responses are the Server's responses."""
    _install_demo_replays(tmp_path)
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env=DEMO_ENV)
    client = module.app.test_client()
    headers = _test_client_auth(module)

    router = FrontendFixtureRouter(
        None,
        controlled_scenario(),
        environment=DEMO_ENVIRONMENT,
        demo_replays=module.app.config["demo_replays"],
    )
    requests = (
        ("POST", f"/compute/api/preflight/{SYNTHETIC_TASK_TYPE}"),
        ("GET", "/compute/api/demo/replays"),
        ("GET", f"/compute/api/demo/replays/{SCENARIO_ID}"),
        # The strict recorded-byte readers: the fixture must bound and refuse
        # exactly as the demo route does, not page anything it can decode.
        ("GET", f"/compute/api/demo/replays/{SCENARIO_ID}/tables/{TABLE_ARTIFACT}?offset=1&limit=1"),
        ("GET", f"/compute/api/demo/replays/{SCENARIO_ID}/tables/{CAPTURED_ARTIFACT}"),
        ("GET", f"/compute/api/demo/replays/{SCENARIO_ID}/tables/{TABLE_ARTIFACT}?limit=501"),
        ("GET", f"/compute/api/demo/replays/{SCENARIO_ID}/ndarrays/{TABLE_ARTIFACT}?key=score&max_elements=8"),
        ("GET", f"/compute/api/demo/replays/{SCENARIO_ID}/ndarrays/{TABLE_ARTIFACT}?key=score&max_elements=999999999"),
        ("GET", f"/compute/api/demo/replays/{SCENARIO_ID}/ndarrays/{TABLE_ARTIFACT}?key=score"),
    )
    for method, path in requests:
        real = client.open(path, method=method, data={} if method == "POST" else None, headers=headers)
        status, payload = _fixture_response(router, path, method)
        assert (status, payload) == (real.status_code, real.get_json()), path
