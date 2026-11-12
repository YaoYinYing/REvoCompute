# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import gzip
import hashlib
import io
import json
import shutil
import struct
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import yaml
from conftest import _anchor_result_publication, _load_pssm_module, _test_client_auth

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "tests" / "data" / "mdconvert"


def _app(monkeypatch, tmp_path, extra_env=None, tools_dir=None):
    images = tmp_path / "tool-images"
    images.mkdir()
    (images / "mdconvert.sif").write_bytes(b"fixture-sif")
    environment = {
        "RUNNER_UID": "1234",
        "RUNNER_GID": "5678",
        "ENABLED_TOOL_FAMILIES": "mdconvert",
        "TOOL_IMAGE_DIR": str(images),
        "TOOL_REQUEST_MAX_BYTES": "108000000",
        "TOOL_STORAGE_MAX_BYTES": "268435456",
    }
    if tools_dir is not None:
        environment["TOOLS_DIR"] = str(tools_dir)
    environment.update(extra_env or {})
    return _load_pssm_module(monkeypatch, tmp_path, environment)


def _md_tools(tmp_path: Path, limits: dict) -> Path:
    root = tmp_path / "custom-tools"
    shutil.copytree(REPO_ROOT / "docker" / "tools" / "mdconvert", root / "mdconvert")
    manifest_path = root / "mdconvert" / "tools" / "md_trajectory_convert" / "tool.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["limits"] = limits
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    return root


def _submit(client, headers, *, topology: bytes = None, trajectory: bytes = None, **fields):
    topology = topology if topology is not None else (FIXTURES / "tiny.gro").read_bytes()
    trajectory = trajectory if trajectory is not None else (FIXTURES / "tiny.xtc").read_bytes()
    data = {
        "parameters": "{}",
        "file_roles": ["topology", "trajectory"],
        "files": [(io.BytesIO(topology), "tiny.gro"), (io.BytesIO(trajectory), "tiny.xtc")],
    }
    data.update(fields)
    return client.post("/compute/api/tools/md_trajectory_convert/call", headers=headers, data=data)


def test_mdconvert_contract_projects_roles_formats_and_limits(monkeypatch, tmp_path):
    module = _app(monkeypatch, tmp_path)
    client = module.app.test_client()
    headers = _test_client_auth(module)

    detail = client.get("/compute/api/tools/md_trajectory_convert", headers=headers)
    assert detail.status_code == 200
    payload = detail.get_json()

    assert payload["available"] is True
    assert [role["id"] for role in payload["inputs"]] == ["topology", "trajectory"]
    assert payload["inputs"][0]["formats"] == ["gro"]
    assert payload["inputs"][1]["formats"] == ["xtc"]
    assert payload["inputs"][1]["cardinality"] == {"min": 1, "max": 1}
    assert [role["id"] for role in payload["outputs"]] == ["reference", "snapshots", "manifest"]
    assert payload["outputs"][1]["cardinality"] == {"min": 0, "max": 50}
    assert payload["limits"] == {
        "request_bytes": 108_000_000,
        "input_bytes": {"topology": 8_000_000, "trajectory": 100_000_000},
    }
    parameters = client.get("/compute/api/tool-parameters/md_trajectory_convert", headers=headers).get_json()
    assert parameters["properties"]["output_adapter"]["enum"] == ["caver_pdb_snapshots"]
    assert parameters["properties"]["pbc_treatment"]["enum"] == ["none"]
    assert parameters["properties"]["frame_indices"]["maxItems"] == 51


def test_ordinary_inputs_are_admitted_and_queued(monkeypatch, tmp_path):
    module = _app(monkeypatch, tmp_path)
    queued = []
    monkeypatch.setattr(
        module.celery,
        "send_task",
        lambda *args, **kwargs: queued.append((args, kwargs)) or SimpleNamespace(id="md-call"),
    )
    client = module.app.test_client()
    headers = _test_client_auth(module)

    response = _submit(
        client,
        headers,
        parameters='{"frame_indices":[0,2],"reference_frame":2}',
    )

    assert response.status_code == 202, response.get_json()
    record = module.tool_calls.get(response.get_json()["tool_call_id"])
    manifest = json.loads(record["input_manifest_json"])
    assert {role: [item["format"] for item in values] for role, values in manifest["inputs"].items()} == {
        "topology": ["gro"],
        "trajectory": ["xtc"],
    }
    assert queued and queued[0][1]["queue"] == "tools"


def test_trajectory_over_one_hundred_million_decoded_bytes_is_refused(monkeypatch, tmp_path):
    module = _app(monkeypatch, tmp_path)
    queued = []
    monkeypatch.setattr(module.celery, "send_task", lambda *args, **kwargs: queued.append(args))
    client = module.app.test_client()
    headers = _test_client_auth(module)
    oversized = tmp_path / "oversized.xtc"
    with oversized.open("wb") as stream:
        stream.write(struct.pack(">i", 1995))
        stream.seek(100_000_000)
        stream.write(b"x")
    assert oversized.stat().st_size == 100_000_001
    with oversized.open("rb") as stream:
        response = client.post(
            "/compute/api/tools/md_trajectory_convert/call",
            headers=headers,
            data={
                "parameters": "{}",
                "file_roles": ["topology", "trajectory"],
                "files": [
                    (io.BytesIO((FIXTURES / "tiny.gro").read_bytes()), "tiny.gro"),
                    (stream, "oversized.xtc"),
                ],
            },
        )

    assert response.status_code == 400, response.get_json()
    assert response.get_json()["code"] == "input_file_size_limit"
    assert queued == []
    assert module.tool_calls.total_accounted_bytes() == 0


def test_compressed_trajectory_cannot_expand_past_the_cap(monkeypatch, tmp_path):
    module = _app(monkeypatch, tmp_path)
    monkeypatch.setattr(module.celery, "send_task", lambda *args, **kwargs: SimpleNamespace(id="never"))
    client = module.app.test_client()
    headers = _test_client_auth(module)

    response = _submit(
        client,
        headers,
        trajectory=gzip.compress(b"\0" * 2_000_000, mtime=0),
        file_encodings=["identity", "gzip"],
    )

    assert response.status_code == 400, response.get_json()
    assert response.get_json()["code"] in {"input_encoding_limit", "input_file_size_limit"}


def test_core_validators_refuse_malformed_or_unsupported_formats(monkeypatch, tmp_path):
    module = _app(monkeypatch, tmp_path)
    monkeypatch.setattr(module.celery, "send_task", lambda *args, **kwargs: SimpleNamespace(id="never"))
    client = module.app.test_client()
    headers = _test_client_auth(module)

    malformed = _submit(client, headers, topology=b"not a topology\n")
    assert malformed.status_code == 400, malformed.get_json()
    assert malformed.get_json()["error_class"] == "invalid_input"

    bad_trajectory = _submit(
        client,
        headers,
        trajectory=(FIXTURES / "bad_magic.xtc").read_bytes(),
    )
    assert bad_trajectory.status_code == 400, bad_trajectory.get_json()
    assert bad_trajectory.get_json()["error_class"] == "invalid_input"

    unsupported = client.post(
        "/compute/api/tools/md_trajectory_convert/call",
        headers=headers,
        data={
            "parameters": "{}",
            "file_roles": ["topology", "trajectory"],
            "files": [
                (io.BytesIO((FIXTURES / "tiny.gro").read_bytes()), "tiny.gro"),
                (io.BytesIO(b"x" * 100), "trajectory.nc"),
            ],
        },
    )
    assert unsupported.status_code == 400, unsupported.get_json()
    assert unsupported.get_json()["error_class"] == "invalid_input"


def test_topology_and_total_caps_are_separate_from_the_trajectory_cap(monkeypatch, tmp_path):
    tools = _md_tools(tmp_path, {"request_bytes": 1000, "input_bytes": {"topology": 300, "trajectory": 800}})
    module = _app(
        monkeypatch,
        tmp_path,
        {"TOOL_REQUEST_MAX_BYTES": "1000", "TOOL_STORAGE_MAX_BYTES": "4096", "TOOL_OUTPUT_MAX_BYTES": "1024"},
        tools_dir=tools,
    )
    monkeypatch.setattr(module.celery, "send_task", lambda *args, **kwargs: SimpleNamespace(id="never"))
    client = module.app.test_client()
    headers = _test_client_auth(module)

    # The 245-byte topology is inside its 300-byte cap; a 700-byte trajectory
    # is inside its 800-byte cap; together they cross the 1000-byte shared
    # budget while neither per-role cap is exceeded.
    trajectory = (FIXTURES / "tiny.xtc").read_bytes().ljust(800, b"\0")
    total = _submit(client, headers, trajectory=trajectory)
    assert total.status_code == 400, total.get_json()
    assert total.get_json()["code"] == "input_total_size_limit"

    topology = _submit(
        client,
        headers,
        topology=b"x" * 301,
        trajectory=(FIXTURES / "tiny.xtc").read_bytes(),
    )
    assert topology.status_code == 400, topology.get_json()
    assert topology.get_json()["code"] == "input_file_size_limit"


def _artifact_task(module, name: str, content: bytes) -> str:
    owner = module.app.config["user_db"].get_user_by_username("owner")
    source_id = uuid.uuid4().hex
    source = {"md5sum": source_id, "storage_key": owner["storage_key"]}
    root = Path(module.app.config["storage_resolver"].get_task_root(source))
    root.mkdir(parents=True)
    artifact = root / name
    artifact.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    (root / "manifest.json").write_text(
        json.dumps({"artifacts": [{"path": name, "sha256": digest, "size": len(content)}]}),
        encoding="utf-8",
    )
    module.task_store.upsert_task(
        source_id,
        filename=name,
        file_path=str(artifact),
        uploaded_at=time.time(),
        finished_at=time.time(),
        status="finished",
        is_binary=0,
        username="owner",
        submitted_by_user_id=owner["id"],
        storage_key=owner["storage_key"],
        task_type="cpu_runner",
    )
    _anchor_result_publication(module, source_id)
    return source_id


def test_artifact_reference_bytes_are_charged_to_the_same_budget(monkeypatch, tmp_path):
    tools = _md_tools(tmp_path, {"request_bytes": 500, "input_bytes": {"trajectory": 500}})
    module = _app(
        monkeypatch,
        tmp_path,
        {"TOOL_REQUEST_MAX_BYTES": "500", "TOOL_STORAGE_MAX_BYTES": "4096", "TOOL_OUTPUT_MAX_BYTES": "1024"},
        tools_dir=tools,
    )
    monkeypatch.setattr(module.celery, "send_task", lambda *args, **kwargs: SimpleNamespace(id="never"))
    client = module.app.test_client()
    headers = _test_client_auth(module, "owner")

    # A Task-artifact reference larger than the per-role budget must be refused
    # by the same decoded accounting as an upload.
    source_id = _artifact_task(module, "oversized.xtc", b"x" * 600)
    response = client.post(
        "/compute/api/tools/md_trajectory_convert/call",
        headers=headers,
        data={
            "parameters": "{}",
            "file_roles": ["topology"],
            "files": [(io.BytesIO((FIXTURES / "tiny.gro").read_bytes()), "tiny.gro")],
            "artifact_references": f"@{source_id}/oversized.xtc",
            "artifact_roles": "trajectory",
        },
    )

    assert response.status_code == 400, response.get_json()
    assert response.get_json()["code"] == "input_file_size_limit"
