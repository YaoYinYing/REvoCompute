# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Cross-component acceptance for the canonical CPU-only Example Runner."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess

from conftest import _load_pssm_module, _test_client_auth
from revocompute.job import JobState


ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_FAMILY = ROOT / "docker" / "runners" / "example"


def test_example_runner_submission_worker_output_and_download(monkeypatch, tmp_path: Path) -> None:
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={
            "RUNNER_UID": "1234",
            "RUNNER_GID": "5678",
            "ENABLED_TASKRUNNERS": "example",
        },
    )
    client = module.app.test_client()
    auth_header = _test_client_auth(module)

    class _Queued:
        id = "queued-example-acceptance"

    monkeypatch.setattr(module.run_compute_task, "apply_async", lambda *args, **kwargs: _Queued())
    response = client.post(
        "/compute/api/post",
        headers=auth_header,
        data={
            "task_type": "sequence_statistics",
            "params[mass_precision]": "4",
            "file": (io.BytesIO(b">acceptance\nACDEFG\n"), "acceptance.fasta"),
            "input_roles": "sequence",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 302, response.get_data(as_text=True)[:300]
    task_id = response.headers["Location"].rsplit("/", 1)[-1]
    submitted = module.task_store.get_task(task_id)
    assert submitted is not None
    assert submitted["task_type"] == "sequence_statistics"
    assert submitted["celery_task_id"] == _Queued.id

    def _run_example_locally(*, entities, output_dir, stage_callback=None, **_kwargs):
        file_entities = [entity for entity in entities if entity["type"] == "file"]
        manifest_path = Path(file_entities[0]["snapshot_root"]) / "task.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        snapshots = {
            (entity["role"], entity["relative_path"]): entity["snapshot_path"] for entity in file_entities
        }
        for role, inputs in manifest["inputs"].items():
            for item in inputs:
                item["path"] = snapshots[(role, item["relative_path"])]
        local_manifest = tmp_path / "example-task.json"
        local_manifest.write_text(json.dumps(manifest), encoding="utf-8")
        completed = subprocess.run(
            ["bash", str(EXAMPLE_FAMILY / "run.sh"), "-i", str(local_manifest), "-o", output_dir],
            env={
                **os.environ,
                "TASK_MANIFEST": str(local_manifest),
                "TASK_CONTEXT_SRC": str(ROOT / "docker" / "runners" / "common" / "task_context.sh"),
                "EXAMPLE_ANALYZER": str(EXAMPLE_FAMILY / "analyze.py"),
            },
            text=True,
            capture_output=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        assert "REVODESIGN_STAGE:sequence_statistics" in completed.stdout
        if stage_callback:
            stage_callback("sequence_statistics")
        return JobState.COMPLETED

    monkeypatch.setattr(module.task_runtime, "_run_compute_job", _run_example_locally)
    module.run_compute_task(task_id)

    status = client.get(f"/compute/api/running/{task_id}", headers=auth_header)
    assert status.status_code == 200
    assert status.get_json()["status"] == "finished"

    results = client.get(f"/compute/api/results/{task_id}", headers=auth_header)
    assert results.status_code == 200
    manifest = results.get_json()
    assert manifest["output_check"]["state"] == "passed"
    assert {view["id"] for view in manifest["views"]} == {"sequence_statistics_table", "aggregate_summary"}
    artifact = next(item for item in manifest["artifacts"] if item["path"] == "sequence_statistics.tsv")

    download = client.get(f"{artifact['url']}?download=1", headers=auth_header)
    assert download.status_code == 200
    assert download.headers["Content-Disposition"].startswith("attachment;")
    assert "acceptance\t6\t" in download.get_data(as_text=True)
