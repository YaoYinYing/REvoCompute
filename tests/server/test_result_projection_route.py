# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""The GET /compute/api/results route projects through the shared projection.

The replay harness reuses ``revocompute.result_projection.project_result_manifest``
for its round trip, so the route and the harness share one projection. These
tests pin the route's behavior against a real finished task: the shared function
produces the served body, and the route owns only authorization (which artifacts
and views a caller may see).
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from conftest import (
    _admin_client_auth,
    _load_pssm_module,
    _relocate_task_artifacts,
    _task_owner,
    _test_client_auth,
)

from revocompute.result_projection import project_result_manifest


def _finished_task_with_result(module, tmp_path) -> tuple[str, Path]:
    """Place a canonical ResultManifest plus artifact bytes at a real task root."""
    result_dir = tmp_path / "result"
    result_dir.mkdir()
    (result_dir / "results").mkdir()
    (result_dir / "results" / "summary.txt").write_text("alignment rows: 12\n", encoding="utf-8")
    (result_dir / "execution").mkdir()
    (result_dir / "execution" / "slurm.stdout").write_text("worker ready\n", encoding="utf-8")
    md5sum = uuid.uuid4().hex
    owner = _task_owner(module, "tester")
    _relocate_task_artifacts(module, md5sum, result_dir, owner)
    root = Path(module.app.config["storage_resolver"].get_task_root({"md5sum": md5sum, **owner}))
    artifacts = [
        {
            "path": "results/summary.txt",
            "size": len(b"alignment rows: 12\n"),
            "sha256": "0" * 63 + "1",
            "media_type": "text/plain",
            "preview": "text",
            "role": "primary",
        },
        {
            "path": "execution/slurm.stdout",
            "size": len(b"worker ready\n"),
            "sha256": "0" * 63 + "2",
            "media_type": "text/plain",
            "preview": "text",
            "role": "diagnostic",
        },
    ]
    manifest = {
        "schema_version": 3,
        "task_id": md5sum,
        "task_type": "gremlin",
        "created_at": "2026-01-01T00:00:00+00:00",
        "status": "finished",
        "terminal": True,
        "error": None,
        "run": {"method": {"id": "gremlin", "name": "GREMLIN"}, "inputs": [], "parameters": []},
        "output_check": {"state": "not_configured", "checks": [], "problems": []},
        "limitations": [],
        "views": [{"id": "logs", "plugin": "evidence-bundle", "role": "primary", "title": "Logs", "sources": {"files": ["results/summary.txt"]}}],
        "artifacts": artifacts,
        "result": {
            "files": {
                "summary": [
                    {
                        "path": "results/summary.txt",
                        "role": "primary",
                        "cardinality": "one",
                        "logical_type": "text",
                        "media_type": "text/plain",
                        "preview": "text",
                        "size": len(b"alignment rows: 12\n"),
                        "sha256": "0" * 63 + "1",
                    }
                ]
            }
        },
        "storyboard": None,
        "outcome": "SUCCESS",
        "total_size": sum(artifact["size"] for artifact in artifacts),
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    module.task_store.upsert_task(
        md5sum,
        filename="input.fasta",
        file_path=str(root / "input.fasta"),
        uploaded_at=1.0,
        started_at=1.0,
        finished_at=2.0,
        walltime=1.0,
        status="finished",
        is_binary=0,
        source_ip="127.0.0.1",
        user_agent="pytest",
        username="tester",
        task_type="gremlin",
        submitted_by_user_id=int(owner["submitted_by_user_id"]),
        storage_key=owner["storage_key"],
    )
    return md5sum, root


def test_result_route_matches_the_shared_projection(monkeypatch, tmp_path) -> None:
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    client = module.app.test_client()
    headers = _test_client_auth(module, username="tester")
    md5sum, root = _finished_task_with_result(module, tmp_path)

    served = client.get(f"/compute/api/results/{md5sum}", headers=headers)
    assert served.status_code == 200
    body = served.get_json()
    # The owner holds full-results access, so the route projects the published
    # manifest unchanged through the shared function.
    published = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    expected = project_result_manifest(
        published,
        task_id=md5sum,
        status="finished",
        terminal=True,
        error=None,
        archive={"ready": False, "request_url": f"/compute/api/results/{md5sum}/archive", "download_url": None},
    )
    assert body == expected
    assert {artifact["path"] for artifact in body["artifacts"]} == {"results/summary.txt", "execution/slurm.stdout"}


def test_result_route_hides_diagnostics_from_a_visibility_only_caller(monkeypatch, tmp_path) -> None:
    """Authorization stays the route's job: a non-owner never reaches the projection."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    client = module.app.test_client()
    md5sum, _ = _finished_task_with_result(module, tmp_path)
    other = _test_client_auth(module, username="someone_else")

    body = client.get(f"/compute/api/results/{md5sum}", headers=other).get_json()
    # The route denies an unowned task exactly like a missing one.
    assert body.get("status") == "not_found"


def test_result_route_projects_capabilities_and_urls_for_the_full_view(monkeypatch, tmp_path) -> None:
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    client = module.app.test_client()
    headers = _admin_client_auth(module)
    md5sum, _ = _finished_task_with_result(module, tmp_path)

    body = client.get(f"/compute/api/results/{md5sum}", headers=headers).get_json()
    summary = next(artifact for artifact in body["artifacts"] if artifact["path"] == "results/summary.txt")
    assert summary["capability"] == "text"
    assert summary["url"] == f"/compute/api/results/{md5sum}/artifacts/results/summary.txt"
    assert body["terminal"] is True
    assert body["status"] == "finished"
    assert body["result"]["files"]["summary"][0]["url"] == f"/compute/api/results/{md5sum}/files/summary?index=0"
    assert "execution/slurm.stdout" in {artifact["path"] for artifact in body["artifacts"]}
