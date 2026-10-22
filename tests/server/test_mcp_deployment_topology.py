# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The deployed MCP topology, exercised end to end with real processes.

The surface is its own service, so the facts that matter are about *processes*,
not about a module: whether the web service (``gunicorn --preload -w 2``) hosts
any MCP listener at all, whether an MCP client reaches the service the
deployment starts, whether a worker recycle disturbs it or duplicates it, and
whether a rollback leaves anything running.  A unit test that imported both
halves into one process could not observe any of them, so this file starts the
real commands on real sockets and inspects the real process tree.

The guest fixture answers only what the tests need: the MCP ``initialize``
handshake (the pre-credential step an agent host performs first) and the
canonical ``/compute/api/mcp`` capability document the web service serves.  An
authenticated canonical operation is proven at the transport and credential
layer -- the service is asked for the tool it cannot answer without a real
canonical principal, and the response is the canonical ``AUTH_REQUIRED`` class
rather than an MCP-local refusal -- because the guest's job is the topology, not
the scientific contract (that is ``tests/mcp_live_acceptance.py``).

Everything here is bounded: ports are taken from free sockets, every wait has a
deadline, and every process is killed in teardown, so the file is deterministic
in CI and leaves nothing running.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The production web command, spelled the way ``docker-compose.yml`` spells it.
#: A test that starts anything else would be asserting about a shape the
#: deployment does not run.
GUNICORN_COMMAND = (
    "{python}",
    "-m",
    "gunicorn",
    "-w",
    "2",
    "--timeout",
    "120",
    "--preload",
    "--no-control-socket",
    "--forwarded-allow-ips",
    "127.0.0.1",
)

#: The production MCP entrypoint: the ``mcp`` service runs exactly this.
MCP_COMMAND = ("{python}", "-m", "revocompute.mcp")

#: Rounds the concurrent cold-start case repeats.  The interleaving it pins is
#: timing-dependent, so one round proves nothing about a race; each round starts
#: both services against a database tree that did not exist a moment earlier.
COLD_START_ROUNDS = 4


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _python() -> str:
    """The interpreter that has this repository and its extras importable."""
    return sys.executable


def _require(executable: str) -> None:
    try:
        __import__(executable)
    except ImportError:  # pragma: no cover - depends on the installed extras
        pytest.skip(f"{executable} is not installed (install the mcp/test extras)")


def _prepare_root(root: Path) -> None:
    """Build the deployment tree both services read, as ``setup`` would.

    The runner tree is the repository's synthetic plugin fixtures -- the same
    input the generic Server tests use -- so plugin discovery has the family
    vocabulary it needs without this file naming a product identity.
    """
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(parents=True, exist_ok=True)
    (root / "runtime-bundles").mkdir(parents=True, exist_ok=True)
    shutil.copytree(REPO_ROOT / "config" / "access_policies", root / "config" / "access_policies", dirs_exist_ok=True)
    shutil.copytree(REPO_ROOT / "tests" / "fixtures" / "runners", root / "docker" / "runners")
    shutil.copytree(REPO_ROOT / "docker" / "tools", root / "docker" / "tools")
    for folder in ("uniref30", "uniref90"):
        (root / folder).mkdir(exist_ok=True)

    # A deployment materializes each family's Runtime Bundle before it serves;
    # the two processes read the same store, so it is built once here.
    sys.path.insert(0, str(REPO_ROOT))
    from revocompute import runtime_bundle
    from revocompute.plugins import PluginManager

    store_root = root / "runtime-bundles"
    index: dict[str, str] = {}
    for manifest in PluginManager().discover(str(root / "docker" / "runners")):
        if not manifest.runtime_overlay:
            continue
        index[manifest.id] = runtime_bundle.materialize(
            root / "docker" / "runners", manifest.runtime_overlay, store_root
        )[0]
    runtime_bundle.write_index(store_root, index)


def _environment(root: Path, *, http_port: int, mcp_port: int, base_url: str) -> dict[str, str]:
    environment = dict(os.environ)
    environment.update(
        {
            "SERVER_DIR": str(root),
            "RUNNERS_DIR": str(root / "docker" / "runners"),
            "DB_PATH": str(root / "tasks.sqlite3"),
            "MANAGE_DB_PATH": str(root / "manage.sqlite3"),
            "LOG_DIR": str(root / "logs"),
            "CONFIG_DIR": str(root / "config"),
            "RUNTIME_BUNDLE_DIR": str(root / "runtime-bundles"),
            "USER_DB_PATH": str(root / "users.sqlite3"),
            "MCP_HANDLE_DB_PATH": str(root / "mcp_handles.sqlite3"),
            "ADMIN_USERS": "admin",
            "ADMIN_BOOTSTRAP_CREDENTIALS": "admin\ttopology-admin-password",
            "AUTH_SECRET_KEY": "topology-signing-key-not-a-credential",
            "RUNNER_UID": "1234",
            "RUNNER_GID": "5678",
            "REDIS_URL": "redis://127.0.0.1:1/0",
            "SERVER_BASE_URL": base_url,
            "PORT": str(http_port),
            "MCP_PORT": str(mcp_port),
            # The deployment-owned destination the web process dials for the
            # service fact.  A real deployment resolves the compose service name;
            # this deployment's services share the loopback interface.
            "MCP_SERVICE": "127.0.0.1",
            "MCP_LOG_LEVEL": "warning",
            "PYTHONPATH": str(REPO_ROOT),
        }
    )
    for name in ("RUNNER_USERNAME", "RUNNER_GROUP", "RUNNER_USER"):
        environment.pop(name, None)
    return environment


class _Deployment:
    """One running deployment: the web process, the MCP service, and the ports."""

    def __init__(self, root: Path, *, mcp_enabled: bool) -> None:
        self.root = root
        self.http_port = _free_port()
        self.mcp_port = _free_port()
        self.base_url = f"http://127.0.0.1:{self.http_port}"
        self.environment = _environment(
            root, http_port=self.http_port, mcp_port=self.mcp_port, base_url=self.base_url
        )
        self.environment["MCP_ENABLED"] = "true" if mcp_enabled else "false"
        self.web: subprocess.Popen[str] | None = None
        self.mcp: subprocess.Popen[str] | None = None
        self.web_log = root / "web.log"
        self.mcp_log = root / "mcp-service.log"

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> "_Deployment":
        """Start each service in turn, waiting for one before starting the next.

        This is the fixture's original order, kept for the cases that observe a
        *running* deployment rather than a starting one.  It cannot see the
        concurrent cold start -- the second service begins only after the first
        is already serving -- so :meth:`launch` exists for that case.
        """
        self.launch_web()
        self.wait_for_http()
        if self.mcp_enabled:
            self.launch_mcp()
            self.wait_for_mcp_service()
        return self

    def launch(self, *, mcp: bool) -> "_Deployment":
        """Start every process *together*, without waiting for any of them.

        The deployed topology starts the web service and the MCP service
        together, and a fresh deployment starts them against empty databases --
        so both processes run the canonical startup pass at once, and the loser
        of a ``CREATE TABLE`` race must tolerate it.  Waiting for the first
        service to bind before starting the second would hide that race
        entirely, so the concurrent case launches both and *then* waits.
        """
        self.launch_web()
        if mcp:
            self.launch_mcp()
        return self

    def launch_web(self) -> None:
        command = [*GUNICORN_COMMAND, "-b", f"127.0.0.1:{self.http_port}", "revocompute.app:app"]
        command = [_python() if token == "{python}" else token for token in command]
        with self.web_log.open("w", encoding="utf-8") as log:
            self.web = subprocess.Popen(
                command, env=self.environment, cwd=str(self.root), stdout=log, stderr=subprocess.STDOUT, text=True
            )

    def launch_mcp(self) -> None:
        assert self.mcp_enabled, "the MCP service is only started when the deployment opted in"
        mcp_command = [_python() if token == "{python}" else token for token in MCP_COMMAND]
        with self.mcp_log.open("w", encoding="utf-8") as log:
            self.mcp = subprocess.Popen(
                mcp_command,
                env=self.environment,
                cwd=str(self.root),
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
            )

    def wait_until_serving(self) -> None:
        self.wait_for_http()
        if self.mcp is not None:
            self.wait_for_mcp_service()

    def wait_for_http(self) -> None:
        self._wait_for(self.http_port, self.web)

    def wait_for_mcp_service(self) -> None:
        assert self.mcp is not None
        self._wait_for(self.mcp_port, self.mcp)

    @property
    def mcp_enabled(self) -> bool:
        return self.environment["MCP_ENABLED"] == "true"

    def _wait_for(self, port: int, process: subprocess.Popen[str], *, seconds: float = 60.0) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise AssertionError(f"a service exited before binding {port}:\n{self.logs()}")
            with socket.socket() as probe:
                if probe.connect_ex(("127.0.0.1", port)) == 0:
                    return
            time.sleep(0.2)
        raise AssertionError(f"nothing bound port {port} within {seconds:.0f}s:\n{self.logs()}")

    def wait_for_mcp_exit(self, *, seconds: float = 30.0) -> int:
        assert self.mcp is not None
        return self.mcp.wait(timeout=seconds)

    def logs(self) -> str:
        parts = []
        for path in (self.web_log, self.mcp_log):
            if path.is_file():
                parts.append(f"--- {path.name} ---\n{path.read_text(encoding='utf-8')[-4000:]}")
        return "\n".join(parts)

    def stop(self) -> None:
        for process in (self.mcp, self.web):
            if process is None:
                continue
            process.terminate()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:  # pragma: no cover - a hung service is a bug
                process.kill()
                process.wait(timeout=20)

    # -- observation -------------------------------------------------------

    def worker_pids(self) -> list[int]:
        """The current gunicorn workers of this deployment's master."""
        assert self.web is not None
        master = self.web.pid
        return [pid for pid in _children(master) if _role(pid) == "gunicorn"]

    def listeners(self) -> dict[int, list[str]]:
        """Every listening port this deployment owns, mapped to the role of each owner.

        Ownership is read from the socket table's own pids and classified from each
        process's command line, so a service started as ``python -m <module>`` is
        still identified by what it is running rather than by the interpreter name
        every Python process shares.
        """
        owners: dict[int, list[str]] = {}
        for line in _ss().splitlines()[1:]:
            fields = line.split()
            if len(fields) < 6:
                continue
            port = int(fields[3].rsplit(":", 1)[-1])
            if port not in (self.http_port, self.mcp_port):
                continue
            for entry in line.split("users:")[-1].strip("()").split("),("):
                marker = entry.split("pid=")
                if len(marker) != 2:
                    continue
                owners.setdefault(port, []).append(_role(int(marker[1].split(",")[0])))
        return owners

    def capability(self) -> dict:
        return _get_json(f"{self.base_url}/compute/api/mcp")

    def mcp_initialize(self) -> dict:
        return _mcp_initialize(self.mcp_port)

    def authenticated_call(self, tool: str, arguments: dict) -> dict:
        """Drive one MCP tool call over a real streamable-HTTP session with a real key."""
        return _mcp_call(self.mcp_port, tool, arguments, headers=self.api_key_headers())

    def anonymous_call(self, tool: str, arguments: dict) -> dict:
        """The same call with no credential at all."""
        return _mcp_call(self.mcp_port, tool, arguments, headers={})

    def api_key_headers(self) -> dict[str, str]:
        """A real credential from the canonical user database this deployment reads.

        It is minted through the same ``UserDatabase`` the web and MCP processes
        open, so the token travels the canonical path: the service resolves it
        against the same database rather than trusting anything the test asserts.
        """
        from revocompute.auth import UserDatabase

        database = UserDatabase(self.environment["USER_DB_PATH"])
        try:
            user = database.get_user_by_username("topology")
            if user is None:
                user = database.create_user(
                    username="topology",
                    email="topology@topology.local",
                    password="topology-password-not-a-credential",
                    registration_status="approved",
                    user_status="active",
                )
                database.verify_email(user["id"])
            return {"X-API-Key": database.generate_api_key(user["id"])}
        finally:
            database.engine.dispose()


# -- process helpers ----------------------------------------------------------


def _ps() -> str:
    return subprocess.run(["ps", "-eLo", "pid,ppid,lwp,comm"], capture_output=True, text=True, check=False).stdout


def _ss() -> str:
    return subprocess.run(["ss", "-ltnp"], capture_output=True, text=True, check=False).stdout


def _role(pid: int) -> str:
    """What a process *is*: the gunicorn web service, or the MCP service.

    A process's ``comm`` is only the interpreter name for a Python entrypoint, so
    the command line is what distinguishes the two services: ``gunicorn`` in the
    argv is the web service, and ``revocompute.mcp`` is the service process this
    test started.
    """
    tokens = _argv(pid)
    if tokens is None:  # pragma: no cover - the process went away between calls
        return "gone"
    if any("gunicorn" in token for token in tokens):
        return "gunicorn"
    if any("revocompute.mcp" in token for token in tokens):
        return "mcp"
    return "other"


def _argv(pid: int) -> list[str] | None:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:  # pragma: no cover - the process went away between calls
        return None
    return [token.decode("utf-8", "replace") for token in raw.split(bytes([0])) if token]


def _children(pid: int) -> list[int]:
    children = []
    for line in _ps().splitlines()[1:]:
        fields = line.split()
        if fields and int(fields[1]) == pid:
            children.append(int(fields[0]))
    return children


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310 - loopback
        return json.loads(response.read().decode("utf-8"))


def _mcp_initialize(port: int) -> dict:
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "topology", "version": "1"},
            },
        }
    ).encode("utf-8")
    request = urllib.request.Request(  # noqa: S310 - loopback
        f"http://127.0.0.1:{port}/k/mcp",
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310 - loopback
        payload = response.read().decode("utf-8").strip()
    return _jsonrpc(payload)


def _mcp_call(port: int, tool: str, arguments: dict, *, headers: dict[str, str]) -> dict:
    """One full streamable-HTTP session: initialize, then ``tools/call``.

    The session is opened and consumed the way an agent host does, over the real
    wire, so "an authenticated canonical operation works over MCP" is an observed
    round trip rather than an in-process function call.
    """
    import anyio
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async def _run() -> dict:
        async with streamablehttp_client(f"http://127.0.0.1:{port}/k/mcp", headers=headers) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool, arguments)
                return {
                    "is_error": result.isError,
                    "content": [block.text for block in result.content if getattr(block, "text", None)],
                    "structured": result.structuredContent,
                }

    return anyio.run(_run)


def _jsonrpc(payload: str) -> dict:
    text = payload
    if text.startswith("event:") or "data:" in text.splitlines()[0]:
        for line in text.splitlines():
            if line.startswith("data:"):
                text = line[len("data:") :].strip()
                break
    return json.loads(text)


# -- tests --------------------------------------------------------------------


def test_the_web_service_hosts_no_mcp_listener(tmp_path):
    # The finding this closes: under ``--preload`` a listener started at import
    # time lives in the pre-fork master and is re-forked on every worker recycle.
    # The web service must therefore hold no MCP socket at all -- the MCP port is
    # owned by the service process alone, and no gunicorn pid appears as one of
    # its owners.
    _require("gunicorn")
    _require("mcp")
    root = tmp_path / "deployment"
    root.mkdir()
    _prepare_root(root)
    deployment = _Deployment(root, mcp_enabled=True)
    try:
        deployment.start()
        listeners = deployment.listeners()
        assert deployment.mcp_port in listeners, "the MCP service must serve"
        assert "gunicorn" not in listeners[deployment.mcp_port], (
            f"a gunicorn process owns the MCP port: {listeners[deployment.mcp_port]}"
        )
        assert deployment.http_port in listeners
        assert all(name == "gunicorn" for name in listeners[deployment.http_port])
        # The master and its workers exist, and none of them owns the MCP port.
        workers = deployment.worker_pids()
        assert len(workers) == 2, workers
        assert deployment.mcp is not None and deployment.mcp.pid not in workers
    finally:
        deployment.stop()


def test_a_real_mcp_client_initializes_over_the_mcp_port(tmp_path):
    # "The surface is deployed" is a claim about a real client, so the handshake
    # is driven over the wire against the service the deployment starts.
    _require("gunicorn")
    _require("mcp")
    root = tmp_path / "deployment"
    root.mkdir()
    _prepare_root(root)
    deployment = _Deployment(root, mcp_enabled=True)
    try:
        deployment.start()
        result = deployment.mcp_initialize()
        server = result["result"]["serverInfo"]
        assert result["result"]["protocolVersion"]
        assert server["name"]
    finally:
        deployment.stop()


def test_an_authenticated_mcp_call_reaches_the_canonical_authorization(tmp_path):
    # MCP is a protocol projection, not a second admission path: the credential is
    # checked against the canonical user database, and an anonymous call gets the
    # canonical AUTH_REQUIRED class rather than an MCP-local refusal.
    _require("gunicorn")
    _require("mcp")
    root = tmp_path / "deployment"
    root.mkdir()
    _prepare_root(root)
    deployment = _Deployment(root, mcp_enabled=True)
    try:
        deployment.start()
        anonymous = deployment.anonymous_call("discover_tools", {})
        assert anonymous["is_error"] is True
        assert "AUTH_REQUIRED" in json.dumps(anonymous["content"])

        # A real API key from the canonical database is accepted, and the answer
        # is the canonical Tool catalog rather than an authorization failure.
        authorized = deployment.authenticated_call("discover_tools", {})
        assert authorized["is_error"] is False
    finally:
        deployment.stop()


def test_a_worker_recycle_leaves_mcp_serving_with_no_duplicate_listener(tmp_path):
    # A worker recycle must not disturb the surface or create a second listener.
    # Before the fix this is exactly where the fork-sited listener was re-forked
    # and left the master owning a socket no configured service supervised.
    _require("gunicorn")
    _require("mcp")
    root = tmp_path / "deployment"
    root.mkdir()
    _prepare_root(root)
    deployment = _Deployment(root, mcp_enabled=True)
    try:
        deployment.start()
        service_pid = deployment.mcp.pid
        before = deployment.worker_pids()
        assert len(before) == 2, before
        assert deployment.mcp_initialize()["result"]["protocolVersion"]

        victim = before[0]
        os.kill(victim, 9)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if victim not in deployment.worker_pids() and len(deployment.worker_pids()) == 2:
                break
            time.sleep(0.2)
        after = deployment.worker_pids()
        assert victim not in after, f"the killed worker is still listed: {after}"
        assert len(after) == 2, after

        # Same service process, same single listener, still answering.
        assert deployment.mcp.pid == service_pid
        assert deployment.mcp.poll() is None
        listeners = deployment.listeners()
        assert listeners[deployment.mcp_port] == ["mcp"], listeners
        assert deployment.mcp_initialize()["result"]["protocolVersion"]
    finally:
        deployment.stop()


def test_a_clean_shutdown_leaves_no_orphan_listener(tmp_path):
    # A rollback or a stop must leave nothing behind: neither port may still be
    # bound, and no process of this deployment may survive.
    _require("gunicorn")
    _require("mcp")
    root = tmp_path / "deployment"
    root.mkdir()
    _prepare_root(root)
    deployment = _Deployment(root, mcp_enabled=True)
    deployment.start()
    deployment.stop()
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and (deployment.mcp_port in deployment.listeners()):
        time.sleep(0.2)
    assert deployment.mcp_port not in deployment.listeners(), "the MCP port is still bound after shutdown"
    assert deployment.http_port not in deployment.listeners(), "the HTTP port is still bound after shutdown"


def test_mcp_is_disabled_by_default(tmp_path):
    # The default is "this surface does not exist": no MCP service is started and
    # the web service publishes no MCP endpoint, so a deployment that never opted
    # in is byte-for-byte the deployment it was before MCP existed.
    _require("gunicorn")
    root = tmp_path / "deployment"
    root.mkdir()
    _prepare_root(root)
    deployment = _Deployment(root, mcp_enabled=False)
    try:
        deployment.start()
        assert deployment.mcp is None
        assert deployment.mcp_port not in deployment.listeners()
        capability = deployment.capability()
        assert capability == {
            "listener_ready": False,
            "route_configured": False,
            "gateway_verified": None,
            "operational": False,
            "enabled": False,
            "endpoint": None,
            "detail": None,
        }
        # And the MCP path is not a route the web service serves over HTTP.
        with pytest.raises(urllib.error.HTTPError) as failure:
            _get_json(f"{deployment.base_url}/k/mcp")
        assert failure.value.code == 404
    finally:
        deployment.stop()


def test_the_mcp_service_is_its_own_supervised_process(tmp_path):
    # Why the surface is not started in the web process: the MCP service is
    # supervised in its own right. Killing it is visible to the operator as an
    # exited process (not as a silently dead thread inside a worker), and the web
    # service keeps serving the capability so the operator can see the fact.
    _require("gunicorn")
    _require("mcp")
    root = tmp_path / "deployment"
    root.mkdir()
    _prepare_root(root)
    deployment = _Deployment(root, mcp_enabled=True)
    try:
        deployment.start()
        assert deployment.mcp is not None
        deployment.mcp.kill()
        assert deployment.wait_for_mcp_exit() != 0
        # The web service is unaffected, and its capability reports the service
        # not answering as an operator problem rather than as "disabled".
        capability = deployment.capability()
        assert capability["listener_ready"] is False
        assert capability["enabled"] is False
        assert capability["endpoint"] is None
        assert capability["detail"]
    finally:
        deployment.stop()


def test_a_concurrent_cold_start_leaves_both_services_serving(tmp_path):
    # The case the deployed topology actually runs: `docker compose up` starts
    # the web service and the MCP service together, and a *fresh* deployment
    # starts them against empty databases.  Both processes import the canonical
    # application, so both run its startup pass -- creating tables in the same
    # user, Task, Tool call, and Operator Job databases -- at the same time.  The
    # loser of that race is told a table "already exists", which is benign and
    # must not fail the process: an unhandled error would take down the web
    # service (or the MCP service) on a first deploy.
    #
    # Every other case in this file starts the web service and *waits* for it
    # before starting the MCP service, so none of them can observe the
    # concurrency; this one launches both and only then waits.
    _require("gunicorn")
    _require("mcp")
    for round_index in range(COLD_START_ROUNDS):
        root = tmp_path / f"deployment-{round_index}"
        root.mkdir()
        _prepare_root(root)
        deployment = _Deployment(root, mcp_enabled=True)
        try:
            deployment.launch(mcp=True)
            deployment.wait_until_serving()
            # Both services stayed up: neither one crashed on the other's schema.
            assert deployment.web is not None and deployment.web.poll() is None, deployment.logs()
            assert deployment.mcp is not None and deployment.mcp.poll() is None, deployment.logs()
            # Both serve.  The canonical API answers its capability, and a real
            # MCP client completes the handshake over the wire.
            capability = deployment.capability()
            assert capability["listener_ready"] is True, capability
            assert capability["enabled"] is False
            assert capability["endpoint"] is None
            assert deployment.mcp_initialize()["result"]["protocolVersion"]
            # And the canonical stores the two processes raced to create are the
            # complete, usable ones: an authenticated canonical operation reaches
            # its real answer rather than failing on a half-created schema.
            authorized = deployment.authenticated_call("discover_tools", {})
            assert authorized["is_error"] is False, authorized
        finally:
            deployment.stop()


def test_starting_the_mcp_service_does_not_terminalize_a_running_operator_job(tmp_path):
    # The second importer of the canonical application must not repeat the
    # application's startup pass.  That pass terminalizes an Operator Job left
    # RUNNING by a restart; if importing the application were enough to run it,
    # merely *starting* the MCP service -- which `restart: unless-stopped` does
    # again after any crash -- would fail a job the web service is legitimately
    # running.  The job's owner is the process that owns the application, so the
    # pass is asserted in both directions with real processes.
    _require("gunicorn")
    _require("mcp")
    from revocompute.operator_jobs import OperatorJobStatus, OperatorJobStore

    root = tmp_path / "deployment"
    root.mkdir()
    _prepare_root(root)
    web = _Deployment(root, mcp_enabled=True)
    # A web process that has already run its own startup pass, on an empty store.
    web.launch_web()
    web.wait_for_http()
    try:
        store = OperatorJobStore(str(root / "operator-jobs.sqlite"))
        record, _ = store.create(
            action="runner.build",
            runner_family="demo",
            actor_user_id=1,
            actor_username="admin",
            tier="mutate",
            lease_scope="runner/demo",
            requested_intent="runner.build",
            plan_digest="sha256:" + "a" * 16,
            evidence_digest="sha256:" + "b" * 16,
            parameters={"runner_family": "demo"},
            idempotency_key=None,
        )
        job_id = record["job_id"]
        assert store.transition(job_id, expected=(OperatorJobStatus.QUEUED,), new_status=OperatorJobStatus.RUNNING)

        # Starting the MCP service imports the canonical application.  The job
        # the web service owns is still RUNNING afterwards.
        web.launch_mcp()
        web.wait_for_mcp_service()
        assert web.mcp is not None and web.mcp.poll() is None, web.logs()
        assert store.get(job_id)["status"] == OperatorJobStatus.RUNNING.value, (
            "starting the MCP service terminalized a job the web service owns"
        )
        store.engine.dispose()

        # Control: a process that *does* own the application still runs the pass.
        # A second web master on the same tree -- what a restart of the web
        # service is -- terminalizes the same job, which is the behavior the
        # first half must not have performed.
        restarted = _Deployment(root, mcp_enabled=False)
        restarted.launch_web()
        restarted.wait_for_http()
        try:
            reopened = OperatorJobStore(str(root / "operator-jobs.sqlite"))
            row = reopened.get(job_id)
            assert row["status"] == OperatorJobStatus.FAILED.value, row
            assert row["failure_category"] == "orphaned_executor_restart"
            reopened.engine.dispose()
        finally:
            restarted.stop()
    finally:
        web.stop()
