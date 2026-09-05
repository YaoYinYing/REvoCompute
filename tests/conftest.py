# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""pytest configuration and shared helpers for revocompute tests.

Run through the server-owned Makefile::

    make test
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import time
import uuid
from pathlib import Path

import pytest

# ── path setup ────────────────────────────────────────────────────────────────

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))
RUN_DIR = SERVER_DIR / "run"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

# ponytail: slurm_runner calls ComputeConfig.from_env()
# at import time — set minimal defaults so unit tests can import without a full env.
os.environ.setdefault("SERVER_DIR", str(SERVER_DIR))
os.environ.setdefault("RUNNER_UID", "1000")
os.environ.setdefault("RUNNER_GID", "1000")

REPO_DIR = str(Path(__file__).resolve().parents[1])
TEST_ROOT = str(Path(__file__).resolve().parent)

# Fresh application imports below own SQLite engines/connections that are not
# reachable through sys.modules after the import-isolation cleanup.  Keep the
# modules alive until the test finishes, then close their resources explicitly
# so the full suite does not exhaust the process file-descriptor limit.
_LOADED_APP_MODULES: list[object] = []


@pytest.fixture(autouse=True)
def _close_loaded_app_resources():
    start = len(_LOADED_APP_MODULES)
    yield
    for module in reversed(_LOADED_APP_MODULES[start:]):
        user_db = module.app.config.get("user_db")
        if user_db is not None:
            user_db.engine.dispose()
        module.task_store.engine.dispose()
        module.manage_db._conn.close()
        module.task_runtime._manage_db._conn.close()
    del _LOADED_APP_MODULES[start:]


# ── module loader ──────────────────────────────────────────────────────────────


def _load_pssm_module(monkeypatch, tmp_path, extra_env: dict | None = None):
    """Load a fresh copy of ``revocompute.py`` with test-isolated env vars.

    ``revocompute.py`` creates ``app``, ``celery``, ``CONFIG``, and
    ``task_store`` at import time — each test needs its own copy.  We use
    ``spec_from_file_location`` so the module is loaded under a unique name,
    avoiding Python's import cache.

    The ``sys.modules`` dance below patches ``revocompute.app`` so
    ``routes.py``'s ``from revocompute.app import app`` resolves to
    THIS test's module rather than loading a second copy from disk (which
    would register routes on a different Flask ``app``).
    """
    # -- env setup --
    env_root = tmp_path / "pssm_env"
    env_root.mkdir(parents=True, exist_ok=True)
    db_path = env_root / "pssm.sqlite3"
    log_dir = env_root / "logs"
    log_dir.mkdir(exist_ok=True)
    (env_root / "config" / "access_policies").mkdir(parents=True, exist_ok=True)
    shutil.copytree(Path(REPO_DIR) / "config" / "access_policies", env_root / "config" / "access_policies", dirs_exist_ok=True)
    # Production discovery reads the server-instance plugin tree.  Materialize
    # the source runner families for isolated application tests as setup does.
    shutil.copytree(Path(REPO_DIR) / "docker" / "runners", env_root / "docker" / "runners")
    for folder in ("uniref30", "uniref90"):
        (env_root / folder).mkdir(exist_ok=True)

    base_env = {
        "SERVER_DIR": str(env_root),
        "DB_PATH": str(db_path),
        "LOG_DIR": str(log_dir),
        "CONFIG_DIR": str(env_root / "config"),
        "ADMIN_USERS": "admin",
        "ADMIN_BOOTSTRAP_CREDENTIALS": "admin\ttest-admin-password",
    }
    for key, value in base_env.items():
        monkeypatch.setenv(key, value)
    for name in ("RUNNER_UID", "RUNNER_GID", "RUNNER_USERNAME", "RUNNER_GROUP", "RUNNER_USER"):
        monkeypatch.delenv(name, raising=False)
    if extra_env:
        for key, value in extra_env.items():
            if value is None:
                monkeypatch.delenv(key, raising=False)
            else:
                monkeypatch.setenv(key, value)
    # Rate limiting and CAPTCHA use Redis when REDIS_URL is reachable.  Tests
    # must not share counters with a live local Redis — every test hits the
    # app from 127.0.0.1, so the suite would 429 itself across tests.  Point
    # it at a dead port unless a test explicitly overrides REDIS_URL.
    if "REDIS_URL" not in (extra_env or {}):
        monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    # Always clear the cached client — get_redis() caches both live clients
    # and fallback None, and an overridden REDIS_URL must win in this test.
    from revocompute.redis_util import get_redis

    get_redis.cache_clear()

    # -- module load with import isolation --
    module_path = Path(REPO_DIR) / "revocompute" / "app.py"
    module_name = f"revocompute_config_test_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    # Force routes.py to re-import for each test so its @app.route decorators
    # bind to THIS test's app instance.  Popping sys.modules alone is not
    # enough — Python also caches submodules as attributes on the parent pkg.
    # ponytail: three lines, one per cached sub-module that binds app.
    _pg = sys.modules.get("revocompute")
    if _pg is not None:
        _pg.__dict__.pop("routes", None)
        _pg.__dict__.pop("app", None)
        _pg.__dict__.pop("task_runtime", None)
    sys.modules.pop("revocompute.routes", None)
    sys.modules.pop("revocompute.task_runtime", None)
    sys.modules[module_name] = module
    sys.modules["revocompute.app"] = module
    try:
        spec.loader.exec_module(module)  # type: ignore[attr-defined]
        module.run_compute_task = module.task_runtime.run_compute_task
        module._ROOT_MOUNT_DIRECTORY = module.task_runtime._ROOT_MOUNT_DIRECTORY
        _LOADED_APP_MODULES.append(module)
        return module
    finally:
        sys.modules.pop(module_name, None)
        sys.modules.pop("revocompute.app", None)
        sys.modules.pop("revocompute.routes", None)
        sys.modules.pop("revocompute.task_runtime", None)
        if _pg is not None:
            _pg.__dict__.pop("routes", None)
            _pg.__dict__.pop("app", None)
            _pg.__dict__.pop("task_runtime", None)


# ── test client auth helpers ───────────────────────────────────────────────────


def _test_client_auth(module, username: str = "tester", password: str = "password") -> dict[str, str]:
    """Create a test user and return Bearer token headers for Flask test-client tests.

    Unlike :func:`_bearer_headers`, this works without a running HTTP server —
    it creates the user directly in the DB and generates a token locally.
    """
    db = module.app.config["user_db"]
    user = db.get_user_by_username(username)
    if not user:
        user = db.create_user(
            username=username,
            email=f"{username}@test.local",
            password=password,
            user_status="active",
            registration_status="approved",
        )
        db.verify_email(user["id"])
    from revocompute.auth import generate_token

    return {"Authorization": f"Bearer {generate_token(user['id'])}"}


def _admin_client_auth(module, username: str = "sysadmin") -> dict[str, str]:
    """Create an admin user and return Bearer token headers."""
    db = module.app.config["user_db"]
    user = db.get_user_by_username(username)
    if not user:
        user = db.create_user(
            username=username,
            email=f"{username}@test.local",
            password="admin_password",
            role="admin",
            registration_status="approved",
            user_status="active",
        )
        db.verify_email(user["id"])
    from revocompute.auth import generate_token

    return {"Authorization": f"Bearer {generate_token(user['id'])}"}


def _personal_task_scope(module, username: str) -> dict[str, str]:
    """Return a complete fresh-schema Personal scope for a test task."""
    database = module.app.config["user_db"]
    user = database.get_user_by_username(username)
    if user is None:
        user = database.create_user(
            username=username,
            email=f"{username}@test.local",
            password="test_password",
            registration_status="approved",
            user_status="active",
        )
    return {"scope_type": "personal", "scope_id": str(user["id"]), "storage_key": user["storage_key"]}


def _relocate_task_artifacts(module, md5sum: str, source_dir: Path | str, scope: dict[str, str]) -> Path:
    """Place fixture output at the same resolver-owned path production uses."""
    source = Path(source_dir)
    task = {"md5sum": md5sum, **scope}
    resolver = module.app.config["storage_resolver"]
    destination = Path(resolver.get_task_root(task))
    if source.resolve() != destination.resolve():
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.exists():
            shutil.copytree(source, destination, dirs_exist_ok=True)
            if source.is_symlink():
                source.unlink()
            else:
                shutil.rmtree(source)
            source.symlink_to(destination, target_is_directory=True)
        else:
            destination.mkdir(parents=True, exist_ok=True)
    old_archive = Path(module.app.config["RESULTS_FOLDER"]) / f"{md5sum}_results.zip"
    archive = Path(resolver.get_archive_path(task))
    if old_archive.is_file() and old_archive != archive:
        archive.parent.mkdir(parents=True, exist_ok=True)
        old_archive.replace(archive)
    return destination


def _upsert_task_for_user(
    module,
    md5sum: str,
    *,
    filename: str,
    file_path: Path | str,
    result_dir: Path | str,
    username: str,
    status: str = "finished",
    run_stage: str | None = None,
    task_type: str = "gremlin",
) -> None:
    scope = _personal_task_scope(module, username)
    _relocate_task_artifacts(module, md5sum, result_dir, scope)
    module.task_store.upsert_task(
        md5sum,
        filename=filename,
        file_path=str(file_path),
        uploaded_at=time.time(),
        started_at=time.time(),
        finished_at=time.time(),
        walltime=1.0,
        status=status,
        is_binary=0,
        source_ip="127.0.0.1",
        user_agent="pytest",
        username=username,
        task_type=task_type,
        submitted_by_user_id=int(scope["scope_id"]),
        run_stage=run_stage,
        **scope,
    )


def _insert_pending_task(
    module, result_dir: Path, filename: str = "input.fasta", task_type: str = "gremlin"
) -> str:
    result_dir.mkdir(parents=True, exist_ok=True)
    fasta_path = result_dir / filename
    fasta_path.write_text(">test\nACDE\n", encoding="utf-8")
    md5sum = uuid.uuid4().hex
    scope = _personal_task_scope(module, "tester")
    _relocate_task_artifacts(module, md5sum, result_dir, scope)
    module.task_store.upsert_task(
        md5sum,
        filename=filename,
        file_path=str(fasta_path),
        uploaded_at=time.time(),
        status="pending",
        is_binary=0,
        source_ip="127.0.0.1",
        user_agent="pytest",
        username="tester",
        task_type=task_type,
        submitted_by_user_id=int(scope["scope_id"]),
        **scope,
    )
    return md5sum


def _extract_md5(location: str) -> str:
    return location.rstrip("/").rsplit("/", 1)[-1]
