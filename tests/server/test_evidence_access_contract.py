# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The cross-identity read contract for atomically written evidence.

Submission evidence (build records, live-test receipts, the staged identity
sidecar) is written by the deployment operator and read by the web/worker
service account, which is a different identity.  A private-by-default temp file
made those records unreadable to the service while the catalog still reported
the family READY.  These cases pin the explicit permission contract and the
admin-only diagnostic that names an unreadable record without leaking a path.
"""

from __future__ import annotations

import grp
import io
import json
import os
import pwd
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import _admin_client_auth, _load_pssm_module, _test_client_auth
from revocompute.artifact_evidence import (
    EVIDENCE_ACCESS_INVALID,
    EVIDENCE_ACCESS_MISSING,
    EVIDENCE_ACCESS_OK,
    EVIDENCE_ACCESS_UNREADABLE,
    evidence_access_state,
    staged_identity_path,
    write_artifact_evidence,
    write_staged_identity,
)
from revocompute.operator_service import OperatorService
from revocompute.runner_host import ServerHostPaths
from revocompute.runner_readiness import load_instance_families
from revocompute.serialization import atomic_write_json

_SERVICE_UID = 129
_SERVICE_GID = 137


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_default_write_is_private(tmp_path):
    path = tmp_path / "record.json"
    atomic_write_json(path, {"runner_family": "demo"})
    assert _mode(path) == 0o600


def test_shared_read_write_is_group_readable(tmp_path):
    path = tmp_path / "record.json"
    atomic_write_json(path, {"runner_family": "demo"}, shared_read=True)
    assert _mode(path) == 0o640
    assert _mode(path) & stat.S_IRGRP
    assert _mode(path) & 0o007 == 0
    assert json.loads(path.read_text(encoding="utf-8")) == {"runner_family": "demo"}


def _acl_permissions(text: str) -> dict[tuple[str, str], int]:
    """Parse ``getfacl`` output into ``(kind, qualifier) -> permission bits``."""
    entries: dict[tuple[str, str], int] = {}
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        parts = line.split(":")
        if len(parts) != 3:
            continue
        kind, qualifier, perms = parts
        bits = (4 if "r" in perms else 0) | (2 if "w" in perms else 0) | (1 if "x" in perms else 0)
        entries[(kind, qualifier)] = bits
    return entries


def _principal_name(lookup, numeric: int) -> str:
    """The name ``getfacl`` prints, or the numeric qualifier when unregistered."""
    try:
        return lookup(numeric)
    except KeyError:
        return str(numeric)


def _named_entry(entries: dict[tuple[str, str], int], kind: str, numeric: int, name: str) -> int:
    for qualifier in (name, str(numeric)):
        if (key := (kind, qualifier)) in entries:
            return entries[key]
    pytest.fail(f"no named {kind} ACL entry for {name}/{numeric}: {entries!r}")


def test_default_acl_mask_permits_shared_read(tmp_path):
    setfacl = shutil.which("setfacl")
    getfacl = shutil.which("getfacl")
    if not setfacl or not getfacl:
        pytest.skip("setfacl/getfacl are unavailable; ACL effectiveness not exercised")

    directory = tmp_path / "evidence"
    directory.mkdir()
    os.chmod(directory, 0o2770)
    try:
        subprocess.run(
            [
                setfacl,
                "-m", f"d:u:{_SERVICE_UID}:rwx",
                "-m", f"d:g:{_SERVICE_GID}:rwx",
                "-m", "d:m::rwx",
                str(directory),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        pytest.skip(f"filesystem does not support default ACLs: {exc}")

    path = directory / "receipt.json"
    atomic_write_json(path, {"runner_family": "demo"}, shared_read=True)
    assert _mode(path) == 0o640

    result = subprocess.run(
        [getfacl, "--omit-header", "-p", str(path)], check=True, capture_output=True, text=True
    )
    entries = _acl_permissions(result.stdout)
    mask = entries.get(("mask", ""), 0)
    user_entry = _named_entry(
        entries, "user", _SERVICE_UID, _principal_name(lambda uid: pwd.getpwuid(uid).pw_name, _SERVICE_UID)
    )
    group_entry = _named_entry(
        entries, "group", _SERVICE_GID, _principal_name(lambda gid: grp.getgrgid(gid).gr_name, _SERVICE_GID)
    )
    assert mask & 0o4, entries
    assert user_entry & mask & 0o4, entries
    assert group_entry & mask & 0o4, entries


def test_production_evidence_writers_are_group_readable(tmp_path):
    """Deleting a caller's ``shared_read=True`` must fail this test."""
    family = SimpleNamespace(name="demo", slurm_image=str(tmp_path / "images" / "demo.sif"))
    digest = "sha256:" + "a" * 64

    build = write_artifact_evidence(family, digest, "build", {"build_provenance_digest": "prov"})
    assert _mode(build) == 0o640

    receipt = write_artifact_evidence(
        family,
        digest,
        "receipt",
        {
            "runner_family": family.name,
            "sif_sha256": digest,
            "build_provenance_digest": "prov",
            "runtime_bundle_sha256": None,
            "test_definition_digest": "test",
            "configuration_digest": "config",
            "execution_uid": 1,
            "execution_gid": 2,
            "scheduler_user": "revodesign",
            "cases": [],
        },
    )
    assert _mode(receipt) == 0o640

    write_staged_identity(family, digest, "prov")
    assert _mode(staged_identity_path(family)) == 0o640


def test_atomic_replace_is_complete_and_carries_the_new_mode(tmp_path):
    path = tmp_path / "record.json"
    atomic_write_json(path, {"version": 1}, shared_read=True)
    assert _mode(path) == 0o640

    payload = {"version": 2, "body": "x" * 4096}
    atomic_write_json(path, payload)
    assert _mode(path) == 0o600
    assert json.loads(path.read_text(encoding="utf-8")) == payload
    assert list(tmp_path.glob(f".{path.name}.*")) == []

    atomic_write_json(path, {"version": 3}, shared_read=True)
    assert _mode(path) == 0o640
    assert json.loads(path.read_text(encoding="utf-8")) == {"version": 3}
    assert list(tmp_path.glob(f".{path.name}.*")) == []


def test_service_identity_can_open_a_shared_record(tmp_path):
    if os.geteuid() != 0:
        pytest.skip(
            f"requires root to drop to uid {_SERVICE_UID}/gid {_SERVICE_GID}; "
            f"test process runs as uid {os.geteuid()}"
        )
    directory = Path(os.mkdtemp(prefix="evidence-access-", dir="/tmp"))
    directory.chmod(0o755)
    path = directory / "receipt.json"
    atomic_write_json(path, {"runner_family": "demo"}, shared_read=True)
    os.chown(path, -1, _SERVICE_GID)

    def _drop_to_service_identity() -> None:
        os.setgroups([])
        os.setgid(_SERVICE_GID)
        os.setuid(_SERVICE_UID)

    result = subprocess.run(
        [sys.executable, "-I", "-c", "import json,sys; json.load(open(sys.argv[1]))", str(path)],
        preexec_fn=_drop_to_service_identity,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def _host(module) -> ServerHostPaths:
    return ServerHostPaths(
        server=module.CONFIG.server_dir,
        config=str(Path(module.CONFIG.server_dir) / "config"),
        root=str(Path(__file__).resolve().parents[2]),
        settings={
            "RUNNER_SOURCE_ROOT": module.CONFIG.runners_dir,
            "RUNTIME_BUNDLE_DIR": module.CONFIG.runtime_bundle_root,
            "MANAGE_DB_PATH": str(module.CONFIG.manage_db_path),
            "RUNNER_UID": "1234",
            "RUNNER_GID": "5678",
            "RUNNER_USERNAME": "revodesign",
            "RUNNER_GROUP": "revodesign",
        },
    )


def _family_evidence(host: ServerHostPaths, name: str = "cpu_runner") -> tuple[ServerHostPaths, Path]:
    family = next(item for item in load_instance_families(host) if item.name == name)
    return family, Path(family.slurm_image).parent / "evidence" / family.name


def test_evidence_access_states_are_distinct(tmp_path):
    family = SimpleNamespace(name="cpu_runner", slurm_image=str(tmp_path / "images" / "cpu_runner.sif"))
    root = tmp_path / "images" / "evidence" / "cpu_runner"

    assert evidence_access_state(family) == EVIDENCE_ACCESS_MISSING

    root.mkdir(parents=True)
    (root / "a.receipt.json").write_text("not json", encoding="utf-8")
    assert evidence_access_state(family) == EVIDENCE_ACCESS_INVALID

    (root / "a.receipt.json").write_bytes(b"\xff\xfe\x00")
    assert evidence_access_state(family) == EVIDENCE_ACCESS_INVALID

    atomic_write_json(root / "a.receipt.json", {"runner_family": "cpu_runner"})
    assert evidence_access_state(family) == EVIDENCE_ACCESS_OK

    # The staged identity sidecar beside the SIF is evidence too.
    (root / "a.receipt.json").unlink()
    write_staged_identity(family, "sha256:" + "a" * 64, "prov")
    assert evidence_access_state(family) == EVIDENCE_ACCESS_OK
    atomic_write_json(root / "a.receipt.json", {"runner_family": "cpu_runner"})

    (root / "a.receipt.json").chmod(0o000)
    try:
        if os.geteuid() == 0:
            pytest.skip("root ignores permission bits, so unreadable cannot be simulated here")
        assert evidence_access_state(family) == EVIDENCE_ACCESS_UNREADABLE
    finally:
        (root / "a.receipt.json").chmod(0o600)


def test_non_regular_entries_are_ignored(tmp_path):
    family = SimpleNamespace(name="cpu_runner", slurm_image=str(tmp_path / "images" / "cpu_runner.sif"))
    root = tmp_path / "images" / "evidence" / "cpu_runner"
    root.mkdir(parents=True)
    try:
        os.mkfifo(root / "pipe.json")
    except (AttributeError, OSError) as exc:
        pytest.skip(f"FIFO creation is unavailable: {exc}")
    assert evidence_access_state(family) == EVIDENCE_ACCESS_MISSING


def test_admin_diagnostic_names_unreadable_evidence_without_leaking_paths(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"}
    )
    host = _host(module)
    family, root = _family_evidence(host)
    module.app.config["operator_service"] = OperatorService(host, database=module.app.config["user_db"])
    client = module.app.test_client()
    admin = _admin_client_auth(module)
    ordinary = _test_client_auth(module)

    missing = client.get("/compute/api/auth/admin/runners/cpu_runner", headers=admin)
    assert missing.status_code == 200, missing.get_data(as_text=True)
    assert missing.get_json()["readiness"]["evidence"]["access"] == EVIDENCE_ACCESS_MISSING

    root.mkdir(parents=True)
    (root / "a.receipt.json").write_text("not json", encoding="utf-8")
    invalid = client.get("/compute/api/auth/admin/runners/cpu_runner", headers=admin)
    assert invalid.status_code == 200, invalid.get_data(as_text=True)
    assert invalid.get_json()["readiness"]["evidence"]["access"] == EVIDENCE_ACCESS_INVALID

    (root / "a.receipt.json").write_bytes(b"\xff\xfe\x00")
    binary = client.get("/compute/api/auth/admin/runners/cpu_runner", headers=admin)
    assert binary.status_code == 200, binary.get_data(as_text=True)
    assert binary.get_json()["readiness"]["evidence"]["access"] == EVIDENCE_ACCESS_INVALID

    atomic_write_json(root / "a.receipt.json", {"runner_family": family.name})
    (root / "a.receipt.json").chmod(0o000)
    try:
        unreadable = client.get("/compute/api/auth/admin/runners/cpu_runner", headers=admin)
    finally:
        (root / "a.receipt.json").chmod(0o600)
    body = unreadable.get_json()
    if os.geteuid() == 0:
        pytest.skip("root ignores permission bits, so unreadable cannot be simulated here")
    assert body["readiness"]["evidence"]["access"] == EVIDENCE_ACCESS_UNREADABLE
    assert str(root) not in json.dumps(body)

    refused = client.get("/compute/api/auth/admin/runners/cpu_runner", headers=ordinary)
    assert refused.status_code == 403
    assert "unreadable" not in refused.get_data(as_text=True)


def test_public_catalog_and_refusal_payloads_do_not_expose_the_diagnostic(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={
            "RUNNER_UID": "1234",
            "RUNNER_GID": "5678",
            "ENABLED_TASKRUNNERS": "cpu_runner",
        },
    )
    client = module.app.test_client()
    ordinary = _test_client_auth(module)

    catalog = client.get("/compute/api/types", headers=ordinary)
    assert catalog.status_code == 200, catalog.get_data(as_text=True)
    text = catalog.get_data(as_text=True)
    catalog_payload = catalog.get_json()
    for entry in catalog_payload["task_types"]:
        assert "readiness" not in entry
        assert "evidence" not in entry
    assert EVIDENCE_ACCESS_UNREADABLE not in text

    module.app.config["manage_db"].resource_set("slurm_enabled", "true")
    readiness = Path(module.CONFIG.server_dir) / "readiness"
    readiness.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        readiness / "cpu_runner.json",
        {
            "runner_family": "cpu_runner",
            "status": "NOT_VALIDATED",
            "ready": False,
            "reason_code": "RECEIPT_MISSING",
            "message": "Active Runner SIF has no live-test receipt",
            "next_action": "live-test",
        },
    )
    refusal = client.post(
        "/compute/api/post",
        headers=ordinary,
        data={
            "task_type": "cpu_runner",
            "file": (io.BytesIO(b">test\nACDE\n"), "upload.fasta"),
            "input_roles": "sequence",
        },
        content_type="multipart/form-data",
    )
    assert refusal.status_code == 503, refusal.get_data(as_text=True)
    payload = refusal.get_json()
    assert set(payload) == {"error", "runner", "status", "reason", "message", "next_action"}
    assert "evidence" not in refusal.get_data(as_text=True)
    assert EVIDENCE_ACCESS_UNREADABLE not in refusal.get_data(as_text=True)
