# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Playwright route ownership for the frontend fixture harness.

The router serves the real built frontend bundle and fulfills every API request
from the mounted scenario. It replaces per-test ``page.route`` sprawl with one
dispatch table plus a semantic request log, so a browser test states what it
drives and what it observed rather than how each endpoint is faked.

The mocked boundary is the HTTP API projection. Production frontend code, the
strict CSP, and same-origin behavior stay exactly as they are in production. A
request the scenario does not declare fails the test instead of silently
returning an empty body.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from . import builders
from .models import DEFAULT_ORIGIN, DEFAULT_TASK_ID
from .scenarios import RunnerScenario

_HTML_HEADERS = {
    "Content-Type": "text/html; charset=utf-8",
    "Content-Security-Policy": (
        "default-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; script-src 'self'; "
        "img-src 'self' data: blob:; worker-src 'self' blob:"
    ),
    "Referrer-Policy": "no-referrer",
}

# Static bundle paths and public fixtures the shell loads without an API call.
_STATIC_PREFIX = "/static/app/"
_PUBLIC_FIXTURES = ("/logo.svg", "/logo.ico", "/skills.md")

# The profile fields PUT /compute/api/auth/me owns. Everything else in the body
# (notably a password change) is handled separately and never persisted here.
_PROFILE_FIELDS = frozenset({"full_name", "affiliation", "position", "pi_name"})

_APP_PAGE = re.compile(
    r"/(?:api-docs|runners|runners/[^/]+|compute/terms"
    r"|compute/(?:login|register|reset_password|user_verify|profile|user_control|configuration|logs"
    r"|create_task|dashboard|results/[0-9a-fA-F]{32}))"
)


@dataclass(frozen=True, slots=True)
class RequestRecord:
    """One captured browser request, including its multipart body."""

    method: str
    url: str
    path: str
    query: str
    body: bytes

    def form_fields(self) -> dict[str, str]:
        """Return the flat multipart fields of a form post."""
        fields: dict[str, list[str]] = {}
        for name, _, value in self.multipart_parts():
            fields.setdefault(name, []).append(value.decode("utf-8", errors="replace"))
        return {name: values[0] for name, values in fields.items()}

    def multipart_parts(self) -> list[tuple[str, str, bytes]]:
        """Return ``(name, filename, body)`` for every multipart part."""
        from email.parser import BytesParser
        from email.policy import HTTP

        header = f"Content-Type: multipart/form-data; boundary={self._boundary()}\nMIME-Version: 1.0\n\n"
        message = BytesParser(policy=HTTP).parsebytes(header.encode() + self.body)
        parts: list[tuple[str, str, bytes]] = []
        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition") or ""
            filename = part.get_filename() or ""
            parts.append((str(name), str(filename), part.get_payload(decode=True) or b""))
        return parts

    def uploaded_files(self) -> list[tuple[str, str, bytes]]:
        """Return only the file parts, as ``(field, filename, body)``."""
        return [(name, filename, body) for name, filename, body in self.multipart_parts() if filename]

    def _boundary(self) -> str:
        first = self.body.split(b"\r\n", 1)[0]
        return first.decode("ascii", errors="replace").removeprefix("--").strip()

    def json_body(self) -> Any:
        return json.loads(self.body.decode("utf-8")) if self.body else None

    def workspace_capabilities(self) -> dict[str, Any]:
        """Return the version-2 workspace document's capability values."""
        raw = self.form_fields().get("workspace")
        if not raw:
            return {}
        document = json.loads(raw)
        return document.get("capabilities", {}) if isinstance(document, dict) else {}


class RequestCapture:
    """Semantic queries over the requests the browser actually made.

    Helpers assert *what* was requested. A new endpoint gets a helper here
    rather than an open-coded substring scan in a test.
    """

    def __init__(self, records: list[RequestRecord]) -> None:
        self._records = records

    def urls(self) -> tuple[str, ...]:
        return tuple(record.url for record in self._records)

    def matching(self, path: str) -> tuple[RequestRecord, ...]:
        return tuple(record for record in self._records if record.path == path)

    def _prefix(self, prefix: str) -> tuple[RequestRecord, ...]:
        return tuple(record for record in self._records if record.path.startswith(prefix))

    def preflight(self, task_type: str | None = None) -> tuple[RequestRecord, ...]:
        records = self._prefix("/compute/api/preflight/")
        if task_type is None:
            return records
        return tuple(record for record in records if record.path.endswith(f"/{task_type}"))

    def submit(self) -> tuple[RequestRecord, ...]:
        return self.matching("/compute/api/post")

    def task_list(self) -> tuple[RequestRecord, ...]:
        return self.matching("/compute/api/tasks")

    def status_polls(self, task_id: str = DEFAULT_TASK_ID) -> tuple[RequestRecord, ...]:
        return self.matching(f"/compute/api/running/{task_id}")

    def result_manifest(self, task_id: str = DEFAULT_TASK_ID) -> tuple[RequestRecord, ...]:
        return self.matching(f"/compute/api/results/{task_id}")

    def access_request(self) -> tuple[RequestRecord, ...]:
        return self.matching("/compute/api/access/requests")

    def detail(self, name: str | None = None) -> tuple[RequestRecord, ...]:
        records = self._prefix("/compute/api/types/")
        if name is None:
            return records
        return tuple(record for record in records if record.path == f"/compute/api/types/{name}")

    def navigation(self) -> tuple[RequestRecord, ...]:
        """Requests for application pages rather than API or static assets."""
        return tuple(
            record
            for record in self._records
            if not record.path.startswith("/compute/api/") and not record.path.startswith(_STATIC_PREFIX)
        )


@dataclass
class _ScenarioState:
    """Mutable bookkeeping that is *not* scenario identity.

    An access request, an API key, or a profile edit changes observable state
    for the rest of one test, but each is driven by an explicit user action
    rather than by elapsed time, so it stays deterministic.
    """

    api_key_active: bool = False
    profile: dict[str, Any] = field(default_factory=dict)
    polls: dict[str, int] = field(default_factory=dict)
    access_requests: int = 0
    access_requests_pending: bool = True

    def next_poll(self, task_id: str) -> int:
        index = self.polls.get(task_id, 0)
        self.polls[task_id] = index + 1
        return index


class UnexpectedRequest(AssertionError):
    """Raised when the browser requests an endpoint the scenario does not declare."""


class FrontendFixtureRouter:
    """Serve the production frontend bundle against one scenario's fixtures."""

    def __init__(self, page: Any, scenario: RunnerScenario, *, origin: str = DEFAULT_ORIGIN) -> None:
        self.page = page
        self.scenario = scenario
        self.origin = origin
        self._records: list[RequestRecord] = []
        self._unexpected: list[RequestRecord] = []
        self._state = _ScenarioState()
        self._dist: Any = None
        self._html = ""

    # -- installation -------------------------------------------------------

    def install(self) -> FrontendFixtureRouter:
        from browser_frontend_assets import result_dist

        self._dist = result_dist()
        manifest = json.loads((self._dist / ".vite" / "manifest.json").read_text(encoding="utf-8"))["index.html"]
        styles = "".join(f'<link rel="stylesheet" href="/static/app/{name}">' for name in manifest.get("css", []))
        self._html = (
            '<!doctype html><html lang="en"><head><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta name="referrer" content="no-referrer">'
            f'{styles}<script type="module" src="/static/app/{manifest["file"]}"></script>'
            '</head><body><div id="app"></div></body></html>'
        )
        self.page.add_init_script(
            "window.__cspViolations = [];"
            "document.addEventListener('securitypolicyviolation',"
            " event => window.__cspViolations.push(event.violatedDirective + ':' + event.blockedURI));"
        )
        self.page.on("request", self._capture)
        self.page.route(f"{self.origin}/**", self._dispatch)
        return self

    # -- observation --------------------------------------------------------

    @property
    def requests(self) -> RequestCapture:
        return RequestCapture(self._records)

    def _capture(self, request: Any) -> None:
        parsed = urlparse(request.url)
        self._records.append(
            RequestRecord(
                method=request.method,
                url=request.url,
                path=parsed.path,
                query=parsed.query,
                body=request.post_data_buffer or b"",
            )
        )

    # -- dispatch -----------------------------------------------------------

    def _dispatch(self, route: Any) -> None:
        parsed = urlparse(route.request.url)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path.startswith(_STATIC_PREFIX) or path in _PUBLIC_FIXTURES:
            return self._static(route, path)
        if path == "/openapi.json":
            return route.fulfill(json=builders.openapi_spec())
        handler = self._api_handler(path)
        if handler is not None:
            return handler(route, query)
        if route.request.method == "GET" and (path == "/" or _APP_PAGE.fullmatch(path)):
            return route.fulfill(headers=_HTML_HEADERS, body=self._html)
        request = route.request
        self._unexpected.append(
            RequestRecord(
                method=request.method,
                url=request.url,
                path=path,
                query=parsed.query,
                body=request.post_data_buffer or b"",
            )
        )
        route.fulfill(status=500, content_type="application/json", body=json.dumps({"error": f"Unexpected request: {path}"}))
        raise UnexpectedRequest(f"Unexpected request: {request.method} {path}")

    def _static(self, route: Any, path: str) -> None:
        body = self.scenario.static_assets().get(path.lstrip("/"))
        if body is not None:
            content_type = "text/javascript" if path.endswith(".js") else "text/css" if path.endswith(".css") else "text/plain"
            return route.fulfill(status=200, content_type=content_type, body=body)
        if path == "/skills.md":
            return route.fulfill(status=200, content_type="text/markdown", body="# REvoCompute agent guide\n")
        if not path.startswith(_STATIC_PREFIX):
            return route.fulfill(status=404, body="not found")
        relative = path[len(_STATIC_PREFIX) :]
        route.fulfill(path=self._dist / relative)

    # -- API endpoints ------------------------------------------------------

    def _api_handler(self, path: str):
        """Return the handler for one API path, or None when it is undeclared."""
        for pattern, handler in _API_ROUTES:
            match = pattern.fullmatch(path)
            if match is not None:
                return lambda route, query, handler=handler, groups=match.groupdict(): handler(self, route, query, **groups)
        return None

    # -- auth and profile ---------------------------------------------------

    def _auth_me(self, route: Any, query: Any) -> None:
        if self.scenario.session.role in {"anonymous", "expired"}:
            return route.fulfill(status=401, json={"error": "Authentication required"})
        if route.request.method == "PUT":
            payload = _json_object(route.request.post_data) or {}
            if {"current_password", "new_password"} & set(payload):
                if self.scenario.reject_password_update:
                    return route.fulfill(status=400, json={"error": "Current password is incorrect"})
                return route.fulfill(json={"message": "Password updated"})
            # Only the profile fields the endpoint owns are persisted; a
            # credential must never round-trip into the CurrentUser projection.
            self._state.profile.update(
                {key: value for key, value in payload.items() if key in _PROFILE_FIELDS}
            )
            return route.fulfill(json={"message": "Profile updated"})
        return route.fulfill(json={**self.scenario.session.as_user_payload(), **self._state.profile})

    def _auth_api_key(self, route: Any, query: Any) -> None:
        if route.request.method == "GET":
            return route.fulfill(json={"has_api_key": self._state.api_key_active})
        if route.request.method == "POST":
            self._state.api_key_active = True
            return route.fulfill(status=201, json={"api_key": "rvk_test_secret_once", "message": "API key generated."})
        self._state.api_key_active = False
        return route.fulfill(json={"message": "API key revoked."})

    def _auth_token(self, route: Any, query: Any) -> None:
        if self.scenario.session.role in {"anonymous", "expired"}:
            return route.fulfill(status=401, json={"error": "Authentication required"})
        return route.fulfill(json={"token": "ephemeral"})

    def _auth_login(self, route: Any, query: Any) -> None:
        payload = _json_object(route.request.post_data) or {}
        if self.scenario.session.role == "expired":
            return route.fulfill(status=401, json={"error": "Invalid credentials"})
        return route.fulfill(json={"token": "signed-in", "username": payload.get("username", "tester")})

    def _auth_logout(self, route: Any, query: Any) -> None:
        return route.fulfill(json={"message": "Signed out."})

    def _auth_register(self, route: Any, query: Any) -> None:
        payload = _json_object(route.request.post_data) or {}
        return route.fulfill(
            status=201,
            json={
                "message": "Check your email, then wait for administrator approval.",
                "username": payload.get("username", "newresearcher"),
                "email_sent": True,
            },
        )

    def _legal_terms(self, route: Any, query: Any) -> None:
        markdown = (
            "# Terms of Service\n\n"
            + "\n\n".join(f"## Policy {index}\n\nPolicy detail {index}." for index in range(1, 16))
            + "\n\n## Restricted Runner access {#restricted-runner-access}\n\nAccess decisions are server-owned."
        )
        return route.fulfill(json={"document": "terms", "version": "sha256:" + "b" * 64, "markdown": markdown})

    # -- Runner discovery ---------------------------------------------------

    def _runner_detail(self, route: Any, query: Any, name: str = "", **_: str) -> None:
        definition = self.scenario.runner_or_none(name)
        if definition is None:
            return route.fulfill(status=404, json={"error": f"Unknown task type: {name!r}"})
        return route.fulfill(json=builders.build_detail(definition))

    def _parameter_schema(self, route: Any, query: Any, name: str = "", **_: str) -> None:
        definition = self.scenario.runner_or_none(name)
        if definition is None:
            return route.fulfill(status=404, json={"error": f"Unknown task type: {name!r}"})
        return route.fulfill(json=builders.build_parameter_schema(definition))

    def _workspace_normalize(self, route: Any, query: Any, name: str = "", **_: str) -> None:
        payload = _json_object(route.request.post_data) or {}
        definition = self.scenario.runner_or_none(name)
        if definition is None:
            return route.fulfill(status=404, json={"error": f"Unknown task type: {name!r}"})
        known = {capability.id for step in definition.workspace_steps for capability in step.capabilities}
        if str(payload.get("capability_id") or "") not in known:
            return route.fulfill(status=400, json={"error": "Unknown normalizable workspace capability"})
        return route.fulfill(json={"value": payload.get("value")})

    # -- submission and lifecycle ------------------------------------------

    def _preflight(self, route: Any, query: Any, name: str = "", **_: str) -> None:
        definition = self.scenario.runner_or_none(name)
        if definition is None:
            return route.fulfill(status=404, json={"error": f"Unknown task type: {name!r}"})
        payload, status = self.scenario.preflight_response(definition)
        return route.fulfill(status=status, json=payload)

    def _submit(self, route: Any, query: Any) -> None:
        definition = self.scenario.runner_or_none(self.scenario.task_type)
        if definition is None:
            return route.fulfill(status=400, json={"error": f"Unknown task type: {self.scenario.task_type}"})
        self._state.polls.setdefault(self.scenario.task_id, 0)
        payload, status = builders.build_submit(self.scenario.task_id, definition, status=self.scenario.submit_status())
        route.fulfill(status=status, headers={"Location": payload["status_url"]}, json=payload)

    def _task_list(self, route: Any, query: Any) -> None:
        return route.fulfill(json={"tasks": self.scenario.summary_payloads()})

    def _status(self, route: Any, query: Any, task_id: str = "", **_: str) -> None:
        definition = self.scenario.runner_for_task(task_id)
        if definition is None:
            return route.fulfill(status=404, json={"status": "not_found", "md5sum": task_id})
        poll_index = self._state.next_poll(task_id)
        payload, terminal, _ = self.scenario.task_status_payload(task_id, poll_index)
        return route.fulfill(status=200 if terminal else 202, json=payload)

    # -- results ------------------------------------------------------------

    def _result_manifest(self, route: Any, query: Any, task_id: str = "", **_: str) -> None:
        manifest = self.scenario.result_for(task_id)
        if manifest is None:
            return route.fulfill(status=404, json={"status": "not_found", "md5sum": task_id})
        return route.fulfill(json=manifest)

    def _result_artifact(self, route: Any, query: Any, path: str = "", task_id: str = "", **_: str) -> None:
        body = self.scenario.artifact_body(task_id, unquote(path))
        if body is None:
            return route.fulfill(status=404, json={"error": "Artifact not found"})
        content, content_type = body
        return route.fulfill(status=200, content_type=content_type, body=content)

    def _result_table(self, route: Any, query: Any, path: str = "", task_id: str = "", **_: str) -> None:
        page = self.scenario.table_page(task_id, unquote(path))
        if page is None:
            return route.fulfill(status=404, json={"error": "Table not found"})
        return route.fulfill(json=page)

    def _result_projection(self, route: Any, query: Any, path: str = "", task_id: str = "", **_: str) -> None:
        projection = self.scenario.projection(task_id, unquote(path), kind=query.get("kind", ["numeric"])[0])
        if projection is None:
            return route.fulfill(status=404, json={"error": "Projection not found"})
        return route.fulfill(json=projection)

    def _result_logical_file(self, route: Any, query: Any, task_id: str = "", file_id: str = "", **_: str) -> None:
        index = int((query.get("index", ["0"]) or ["0"])[0])
        # The real endpoint resolves a logical file to its underlying artifact
        # path and serves those bytes, not the LogicalResultFile object.
        body = self.scenario.logical_file_artifact(task_id, file_id, index)
        if body is None:
            return route.fulfill(status=404, json={"error": "Result file not found"})
        content, content_type = body
        return route.fulfill(status=200, content_type=content_type, body=content)

    def _storyboard_asset(self, route: Any, query: Any, task_id: str = "", asset: str = "", **_: str) -> None:
        body = self.scenario.storyboard_module(task_id, asset)
        if body is None:
            return route.fulfill(status=404, json={"error": "Storyboard asset not found"})
        return route.fulfill(content_type="text/javascript", body=body)

    def _archive_action(self, route: Any, query: Any, task_id: str = "", **_: str) -> None:
        return route.fulfill(json=self.scenario.archive_response(task_id))

    # -- access -------------------------------------------------------------

    def _access_policies(self, route: Any, query: Any) -> None:
        policies = [builders.runner_access_payload(access) for access in self.scenario.policy_states()]
        return route.fulfill(json={"policies": policies})

    def _access_request(self, route: Any, query: Any) -> None:
        self._state.access_requests += 1
        return route.fulfill(
            status=201,
            json={"policy_id": self.scenario.access_policy_id, "requests": [{"entitlement": "academic-models", "status": "pending"}]},
        )

    # -- mutating task actions ---------------------------------------------

    def _delete_batch(self, route: Any, query: Any) -> None:
        payload = _json_object(route.request.post_data) or {}
        return route.fulfill(json={"deleted": list(payload.get("md5sums", []))})

    def _delete_task(self, route: Any, query: Any, task_id: str = "", **_: str) -> None:
        if self.scenario.session.role in {"anonymous", "expired"}:
            return route.fulfill(status=401, json={"error": "Authentication required"})
        return route.fulfill(json={"status": "deleted", "md5sum": task_id})

    def _cancel_task(self, route: Any, query: Any, task_id: str = "", **_: str) -> None:
        return route.fulfill(json={"status": "cancelled", "md5sum": task_id})


# Dispatch table: first match wins. Handlers receive the router plus the URL
# captures, so a parameterized route needs no per-test closure.
_API_ROUTES: tuple[tuple[re.Pattern[str], Any], ...] = (
    (re.compile(r"/compute/api/auth/me"), FrontendFixtureRouter._auth_me),
    (re.compile(r"/compute/api/auth/me/api-key"), FrontendFixtureRouter._auth_api_key),
    (re.compile(r"/compute/api/auth/token"), FrontendFixtureRouter._auth_token),
    (re.compile(r"/compute/api/auth/login"), FrontendFixtureRouter._auth_login),
    (re.compile(r"/compute/api/auth/logout"), FrontendFixtureRouter._auth_logout),
    (re.compile(r"/compute/api/auth/register"), FrontendFixtureRouter._auth_register),
    (re.compile(r"/compute/api/legal/terms"), FrontendFixtureRouter._legal_terms),
    (re.compile(r"/compute/api/infrastructure"), lambda self, route, query: route.fulfill(json=builders.build_infrastructure(self.scenario.readiness()))),
    (re.compile(r"/compute/api/types"), lambda self, route, query: route.fulfill(json=self.scenario.catalog())),
    (re.compile(r"/compute/api/types/(?P<name>[^/]+)/workspace/normalize"), FrontendFixtureRouter._workspace_normalize),
    (re.compile(r"/compute/api/types/(?P<name>[^/]+)"), FrontendFixtureRouter._runner_detail),
    (re.compile(r"/compute/api/task-parameters/(?P<name>[^/]+)"), FrontendFixtureRouter._parameter_schema),
    (re.compile(r"/compute/api/preflight/(?P<name>[^/]+)"), FrontendFixtureRouter._preflight),
    (re.compile(r"/compute/api/post"), FrontendFixtureRouter._submit),
    (re.compile(r"/compute/api/tasks"), FrontendFixtureRouter._task_list),
    (re.compile(r"/compute/api/running/(?P<task_id>[0-9a-fA-F]+)"), FrontendFixtureRouter._status),
    (re.compile(r"/compute/api/results/(?P<task_id>[0-9a-fA-F]+)/archive"), FrontendFixtureRouter._archive_action),
    (re.compile(r"/compute/api/results/(?P<task_id>[0-9a-fA-F]+)/tables/(?P<path>.+)"), FrontendFixtureRouter._result_table),
    (re.compile(r"/compute/api/results/(?P<task_id>[0-9a-fA-F]+)/ndarrays/(?P<path>.+)"), FrontendFixtureRouter._result_projection),
    (re.compile(r"/compute/api/results/(?P<task_id>[0-9a-fA-F]+)/files/(?P<file_id>[^/]+)"), FrontendFixtureRouter._result_logical_file),
    (re.compile(r"/compute/api/results/(?P<task_id>[0-9a-fA-F]+)/artifacts/(?P<path>.+)"), FrontendFixtureRouter._result_artifact),
    (re.compile(r"/compute/api/results/(?P<task_id>[0-9a-fA-F]+)/storyboard/(?P<asset>.+)"), FrontendFixtureRouter._storyboard_asset),
    (re.compile(r"/compute/api/results/(?P<task_id>[0-9a-fA-F]+)"), FrontendFixtureRouter._result_manifest),
    (re.compile(r"/compute/api/access/requests"), FrontendFixtureRouter._access_request),
    (re.compile(r"/compute/api/access"), FrontendFixtureRouter._access_policies),
    (re.compile(r"/compute/api/delete/(?P<task_id>[0-9a-fA-F]+)"), FrontendFixtureRouter._delete_task),
    (re.compile(r"/compute/api/delete"), FrontendFixtureRouter._delete_batch),
    (re.compile(r"/compute/api/cancel/(?P<task_id>[0-9a-fA-F]+)"), FrontendFixtureRouter._cancel_task),
)


# ---------------------------------------------------------------------------
# Convenience mounting
# ---------------------------------------------------------------------------


def mount_scenario(page: Any, scenario: RunnerScenario, *, origin: str = DEFAULT_ORIGIN) -> FrontendFixtureRouter:
    """Serve the built frontend bundle against one scenario's fixtures.

    Returns the installed router, whose ``requests`` capture answers what the
    browser actually asked for.
    """
    return FrontendFixtureRouter(page, scenario, origin=origin).install()


def _json_object(body: str | None) -> dict[str, Any] | None:
    if not body:
        return None
    try:
        value = json.loads(body)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None
