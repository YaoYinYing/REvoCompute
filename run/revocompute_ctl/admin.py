# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Admin bootstrap credentials and reset-passwd.

Credentials are generated on the host and handed to the web container
through the environment; plaintext passwords are never printed.
"""

from __future__ import annotations

import os
import secrets
import sqlite3
import sys
import tempfile
from pathlib import Path

from revocompute_ctl.compose import container_fs


_AUTH_DB_EMPTY_CHECK = """\
import sqlite3

with sqlite3.connect("file:/auth/users.sqlite3?mode=ro", uri=True) as conn:
    print(int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0))
"""

_RESET_PASSWORD = """\
import datetime
import os
import secrets
import sqlite3
import sys
import tempfile
from pathlib import Path

from werkzeug.security import generate_password_hash

auth_dir = Path("/auth")
user_db = auth_dir / "users.sqlite3"
backup_root = Path("/srv/backups")
credential_file = None
backup_dir = None
try:
    if not user_db.is_file():
        raise RuntimeError("user database is missing")
    with sqlite3.connect(user_db) as source:
        columns = {row[1] for row in source.execute("PRAGMA table_info(users)")}
        if not {"username", "password_hash"} <= columns:
            raise RuntimeError("users table has an incompatible schema")
        if source.execute("SELECT 1 FROM users WHERE username = ?", (USERNAME,)).fetchone() is None:
            raise RuntimeError("username does not exist")

        password = secrets.token_hex(16)
        handle, credential_name = tempfile.mkstemp(dir=auth_dir, prefix="reset-admin-credentials.")
        credential_file = Path(credential_name)
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(f"{USERNAME}\\t{password}\\n")
        credential_file.chmod(0o600)

        backup_root.mkdir(exist_ok=True)
        stamp = datetime.datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")
        backup_dir = Path(tempfile.mkdtemp(dir=backup_root, prefix=f"auth-pre-reset-passwd-{stamp}-"))
        backup_dir.chmod(0o700)
        backup_db = backup_dir / "users.sqlite3"
        with sqlite3.connect(backup_db) as destination:
            source.backup(destination)
        backup_db.chmod(0o600)

        assignments = "password_hash = ?"
        if "token_version" in columns:
            assignments += ", token_version = token_version + 1"
        if source.execute(
            f"UPDATE users SET {assignments} WHERE username = ?",
            (generate_password_hash(password), USERNAME),
        ).rowcount != 1:
            raise RuntimeError("password reset did not update exactly one user")
except BaseException as exc:
    if credential_file is not None:
        credential_file.unlink(missing_ok=True)
    if backup_dir is not None:
        for path in backup_dir.iterdir():
            path.unlink()
        backup_dir.rmdir()
    print(str(exc), file=sys.stderr)
    raise SystemExit(1) from None

print(f"{backup_dir.name}\\t{credential_file.name}")
"""


def _needs_admin_bootstrap(user_db: str) -> bool | None:
    path = Path(user_db)
    if not path.is_file():
        return True
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            has_users = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'users'").fetchone()
            count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] if has_users else 0
        return count == 0
    except sqlite3.Error:
        return None


def _container_needs_admin_bootstrap(state, auth_dir: str) -> bool:
    result = container_fs(
        state,
        "python -",
        [(auth_dir, "/auth")],
        stdin_data=_AUTH_DB_EMPTY_CHECK,
        check=False,
        capture=True,
    )
    if result.returncode != 0 or result.stdout.strip() not in ("0", "1"):
        print("Cannot inspect the auth database as the web service; refusing to restart.", file=sys.stderr)
        raise SystemExit(1)
    return result.stdout.strip() == "1"


def prepare_admin_bootstrap(state) -> None:
    """Generate ADMIN_BOOTSTRAP_CREDENTIALS for the configured admins when the
    user database has no users yet."""
    if state.get("ADMIN_BOOTSTRAP_CREDENTIALS"):
        return
    auth_dir = state.get("AUTH_DIR") or os.path.join(state.server_root(), "auth-data")
    user_db = os.path.join(auth_dir, "users.sqlite3")
    needs_bootstrap = _needs_admin_bootstrap(user_db)
    if needs_bootstrap is None:
        needs_bootstrap = _container_needs_admin_bootstrap(state, auth_dir)
    if not needs_bootstrap:
        return

    credentials: list[str] = []
    seen: list[str] = []
    for admin_username in state.get_csv("ADMIN_USERS"):
        admin_username = admin_username.strip()
        if not admin_username:
            continue
        if admin_username in seen:
            print(f"ADMIN_USERS must not contain duplicate usernames: {admin_username}", file=sys.stderr)
            raise SystemExit(1)
        seen.append(admin_username)
        admin_pw = secrets.token_hex(16)
        credentials.append(f"{admin_username}\t{admin_pw}\n")
    if not credentials:
        print("ADMIN_USERS must contain at least one username.", file=sys.stderr)
        raise SystemExit(1)
    state.runtime["ADMIN_BOOTSTRAP_CREDENTIALS"] = "".join(credentials)


def print_admin_logins(state) -> None:
    """Persist generated bootstrap credentials to a 0600 file in AUTH_DIR and
    clear them from the environment."""
    credentials = state.get("ADMIN_BOOTSTRAP_CREDENTIALS")
    if not credentials:
        return
    auth_dir = state.get("AUTH_DIR") or os.path.join(state.server_root(), "auth-data")
    os.makedirs(auth_dir, exist_ok=True)
    handle, credential_file = tempfile.mkstemp(dir=auth_dir, prefix="bootstrap-admin-credentials.")
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        stream.write(credentials)
    os.chmod(credential_file, 0o600)
    print(f"Bootstrap admin credentials written to: {credential_file} (mode 0600)")
    state.runtime.pop("ADMIN_BOOTSTRAP_CREDENTIALS", None)


def cmd_reset_passwd(state, username: str) -> None:
    """Rotate one user's password hash, invalidate tokens, back up the auth
    database, and write the new credential to a 0600 file."""
    if not state.get("AUTH_DIR") or not state.server_dir():
        print(f"AUTH_DIR and SERVER_DIR must be set in {state.env_file}.", file=sys.stderr)
        raise SystemExit(1)
    if not username.isprintable() or len(username) > 128:
        print("Username must contain printable characters and be at most 128 characters.", file=sys.stderr)
        raise SystemExit(1)

    result = container_fs(
        state,
        "python -",
        [(state.get("AUTH_DIR"), "/auth"), (state.server_dir(), "/srv")],
        stdin_data=f"USERNAME = {username!r}\n{_RESET_PASSWORD}",
        check=False,
        capture=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "container exited without a diagnostic"
        print(f"Password reset failed: {detail}", file=sys.stderr)
        print("No credential file was retained.", file=sys.stderr)
        raise SystemExit(1)

    try:
        backup_name, credential_name = result.stdout.strip().split("\t", 1)
    except ValueError:
        print("Password reset failed; no credential file was retained.", file=sys.stderr)
        raise SystemExit(1) from None
    backup_db = os.path.join(state.server_dir(), "backups", backup_name, "users.sqlite3")
    credential_file = os.path.join(state.get("AUTH_DIR"), credential_name)
    print(f"Password reset completed for user: {username}")
    print(f"Auth database backup written to: {backup_db} (mode 0600)")
    print(f"New credential written to: {credential_file} (mode 0600)")
