# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from conftest import _admin_client_auth, _load_pssm_module, _test_client_auth
from revocompute import task_types
from revocompute.task_types import discover_plugins

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "docker/runners/alphafold3/run.sh"


def _preserve_registry():
    class RegistryContext:
        def __enter__(self):
            self.tasks = dict(task_types._registry)
            self.runtimes = dict(task_types._runtime_registry)
            self.categories = dict(task_types._category_registry)
            return self

        def __exit__(self, *_):
            task_types._registry.clear()
            task_types._registry.update(self.tasks)
            task_types._runtime_registry.clear()
            task_types._runtime_registry.update(self.runtimes)
            task_types._category_registry.clear()
            task_types._category_registry.update(self.categories)

    return RegistryContext()


def _load_af3_registry():
    discover_plugins(str(ROOT / "docker/runners"), {"alphafold", "alphafold3"})
    return task_types.get("alphafold3")


def test_alphafold3_registry_is_restricted_staged_and_independent_from_alphafold2():
    with _preserve_registry():
        af3, runner = _load_af3_registry()
        af2, _ = task_types.get("alphafold")

        assert af3.runtime.name == "alphafold3"
        assert af3.runtime.access_policy.id == "alphafold3_noncommercial"
        assert af3.runtime.access_policy.requires == ("alphafold3_noncommercial",)
        assert af3.input_extensions == (".json",)
        assert af3.gpus is True
        assert [(stage.name, stage.requires_gpu) for stage in af3.workflow] == [
            ("alphafold3.features", False),
            ("alphafold3.model", True),
        ]
        assert [stage.runner_args for stage in af3.workflow] == [("-s", "features"), ("-s", "model")]
        assert af2.runtime.name == "alphafold"
        assert af2.runtime.access_policy is None
        assert af2.input_extension == ".fasta"
        assert [mount.mode for mount in runner.mounts] == ["ro", "ro", "ro"]
        assert runner.mounts[0].host_path == "/mnt/db/weights/alphafold3"
        assert runner.mounts[0].container_path == "/mnt/alphafold3/models"


def test_alphafold3_result_workspace_selects_current_upstream_outputs():
    with _preserve_registry():
        af3, _ = _load_af3_registry()
        selectors = {
            selector.value
            for view in af3.result_workspace
            for group in view.sources.values()
            for selector in group
        }
        assert "modeling/*/*_model.cif" in selectors
        assert "modeling/*/*_ranking_scores.csv" in selectors
        assert "modeling/*/*_summary_confidences.json" in selectors
        assert "modeling/*/*_confidences.json" in selectors
        assert "features/*/*_data.json" in selectors


def test_alphafold3_result_workspace_resolves_representative_outputs(monkeypatch, tmp_path):
    files = {
        "modeling/test_job/test_job_model.cif": "data_test_job",
        "modeling/test_job/test_job_ranking_scores.csv": "seed,sample,ranking_score\n1,0,0.9\n",
        "modeling/test_job/test_job_confidences.json": '{"pae": []}',
        "modeling/test_job/test_job_summary_confidences.json": (
            '{"ptm":0.9,"iptm":0.8,"ranking_score":0.9,'
            '"fraction_disordered":0.1,"has_clash":0}'
        ),
        "modeling/test_job/TERMS_OF_USE.md": "terms",
        "features/test_job/test_job_data.json": '{"name":"Test Job"}',
    }
    artifacts = []
    for relative_path, content in files.items():
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        artifacts.append({"path": relative_path, "size": path.stat().st_size, "role": "artifact"})

    module = _load_pssm_module(
        monkeypatch,
        tmp_path / "app",
        {"RUNNER_UID": "1234", "RUNNER_GID": "5678", "ENABLED_TASKRUNNERS": "alphafold3"},
    )
    af3, _ = module.task_runtime._get_task_type("alphafold3")
    views, checks, problems = module.task_runtime._resolve_result_views(af3, artifacts, str(tmp_path))

    assert problems == []
    assert all(check["status"] == "passed" for check in checks)
    by_id = {view["id"]: view for view in views}
    assert by_id["predicted_structures"]["sources"]["candidates"] == [
        "modeling/test_job/test_job_model.cif"
    ]
    assert "features/test_job/test_job_data.json" in by_id["prediction_data"]["sources"]["items"]


def test_alphafold3_runtime_fails_preflight_when_its_policy_is_missing(tmp_path):
    runners = tmp_path / "runners"
    shutil.copytree(ROOT / "docker/runners/alphafold3", runners / "alphafold3")
    (runners / "alphafold3/policies/noncommercial.yaml").unlink()
    with _preserve_registry(), pytest.raises(KeyError, match="alphafold3_noncommercial"):
        discover_plugins(str(runners), {"alphafold3"})


def _write_fake_af3(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
values = {arg.split('=', 1)[0]: arg.split('=', 1)[1] for arg in args if arg.startswith('--') and '=' in arg}
with open(os.environ['AF3_CALL_LOG'], 'a', encoding='utf-8') as handle:
    handle.write(json.dumps(args) + '\\n')
stage = 'features' if '--run_data_pipeline=true' in args else 'model'
if os.environ.get('AF3_FAIL_STAGE') == stage:
    raise SystemExit(9)
out = Path(values['--output_dir']) / 'test_job'
out.mkdir(parents=True)
if stage == 'features':
    (out / 'test_job_data.json').write_text('{\"name\": \"Test Job\"}', encoding='utf-8')
else:
    if not values['--json_path'].endswith('/features/test_job/test_job_data.json'):
        raise SystemExit(8)
    (out / 'test_job_ranking_scores.csv').write_text('seed,sample,ranking_score\\n1,0,0.9\\n', encoding='utf-8')
    (out / 'test_job_confidences.json').write_text('{\"pae\": []}', encoding='utf-8')
    (out / 'test_job_summary_confidences.json').write_text('{\"ptm\": 0.9, \"iptm\": 0.8, \"ranking_score\": 0.9, \"fraction_disordered\": 0.1, \"has_clash\": 0}', encoding='utf-8')
    (out / 'TERMS_OF_USE.md').write_text('terms', encoding='utf-8')
    if os.environ.get('AF3_NO_STRUCTURE') != '1':
        (out / 'test_job_model.cif').write_text('data_test_job', encoding='utf-8')
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _runner_env(tmp_path: Path) -> tuple[dict[str, str], Path, Path]:
    fake = tmp_path / "fake_af3.py"
    _write_fake_af3(fake)
    db_dir = tmp_path / "databases"
    db_dir.mkdir()
    reduced = tmp_path / "reduced_bfd.fasta"
    reduced.write_text(">x\nACDE\n", encoding="utf-8")
    models = tmp_path / "models"
    models.mkdir()
    (models / "af3.bin.zst").write_bytes(b"weights-placeholder")
    user_input = tmp_path / "input.json"
    user_input.write_text('{"name":"Test Job"}', encoding="utf-8")
    manifest = tmp_path / "task.json"
    manifest.write_text(json.dumps({"files": [{"path": str(user_input)}], "params": {}}), encoding="utf-8")
    call_log = tmp_path / "calls.jsonl"
    env = {
        **os.environ,
        "TASK_MANIFEST": str(manifest),
        "TASK_CONTEXT_SRC": str(ROOT / "docker/runners/common/task_context.sh"),
        "ALPHAFOLD3_PYTHON": "python3",
        "ALPHAFOLD3_SCRIPT": str(fake),
        "ALPHAFOLD3_DB_DIR": str(db_dir),
        "ALPHAFOLD3_SMALL_BFD_PATH": str(reduced),
        "ALPHAFOLD3_MODEL_DIR": str(models),
        "AF3_CALL_LOG": str(call_log),
    }
    return env, manifest, call_log


def _run_stage(env: dict[str, str], manifest: Path, output: Path, stage: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(RUNNER), "-i", str(manifest), "-o", str(output), "-s", stage],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_alphafold3_wrapper_composes_stages_and_hands_off_processed_json(tmp_path):
    env, manifest, call_log = _runner_env(tmp_path)
    output = tmp_path / "result"

    features = _run_stage(env, manifest, output, "features")
    assert features.returncode == 0, features.stderr
    assert "REVODESIGN_STAGE:data_pipeline" in features.stdout
    assert not (output / "task_finished").exists()
    model = _run_stage(env, manifest, output, "model")
    assert model.returncode == 0, model.stderr
    assert "REVODESIGN_STAGE:inference" in model.stdout
    assert (output / "task_finished").is_file()

    calls = [json.loads(line) for line in call_log.read_text(encoding="utf-8").splitlines()]
    assert "--run_data_pipeline=true" in calls[0]
    assert "--run_inference=false" in calls[0]
    assert f"--db_dir={env['ALPHAFOLD3_DB_DIR']}" in calls[0]
    assert "--run_data_pipeline=false" in calls[1]
    assert "--run_inference=true" in calls[1]
    assert f"--model_dir={env['ALPHAFOLD3_MODEL_DIR']}" in calls[1]
    assert any(arg.endswith("/features/test_job/test_job_data.json") for arg in calls[1])


@pytest.mark.parametrize(
    ("nproc", "jackhmmer", "nhmmer", "hmmsearch"),
    [(8, 2, 2, 8), (16, 4, 5, 8), (32, 8, 8, 8), (128, 8, 8, 8)],
)
def test_alphafold3_runner_translates_total_cpu_budget(tmp_path, nproc, jackhmmer, nhmmer, hmmsearch):
    env, manifest, call_log = _runner_env(tmp_path)
    env["NPROC"] = str(nproc)
    completed = _run_stage(env, manifest, tmp_path / "result", "features")

    assert completed.returncode == 0, completed.stderr
    args = json.loads(call_log.read_text(encoding="utf-8").splitlines()[0])
    assert f"--jackhmmer_n_cpu={jackhmmer}" in args
    assert f"--nhmmer_n_cpu={nhmmer}" in args
    assert f"--hmmsearch_n_cpu={hmmsearch}" in args
    assert "--jackhmmer_max_parallel_shards=1" in args
    assert "--nhmmer_max_parallel_shards=1" in args


@pytest.mark.parametrize("nproc", ["1", "3", "invalid"])
def test_alphafold3_runner_rejects_insufficient_or_invalid_cpu_budget(tmp_path, nproc):
    env, manifest, call_log = _runner_env(tmp_path)
    env["NPROC"] = nproc
    completed = _run_stage(env, manifest, tmp_path / "result", "features")

    assert completed.returncode != 0
    assert not call_log.exists()
    assert "NPROC" in completed.stderr


def test_alphafold3_wrapper_rejects_missing_or_modified_processed_json(tmp_path):
    env, manifest, call_log = _runner_env(tmp_path)
    output = tmp_path / "result"
    missing = _run_stage(env, manifest, output, "model")
    assert missing.returncode != 0
    assert "processed JSON is missing" in missing.stderr
    assert not call_log.exists()

    assert _run_stage(env, manifest, output, "features").returncode == 0
    processed = output / "features/test_job/test_job_data.json"
    processed.write_text('{"changed":true}', encoding="utf-8")
    modified = _run_stage(env, manifest, output, "model")
    assert modified.returncode != 0
    assert "changed after feature validation" in modified.stderr
    assert len(call_log.read_text(encoding="utf-8").splitlines()) == 1
    assert not (output / "task_finished").exists()


def test_alphafold3_wrapper_propagates_upstream_failure_and_validates_structure(tmp_path):
    env, manifest, _ = _runner_env(tmp_path)
    output = tmp_path / "failed"
    env["AF3_FAIL_STAGE"] = "features"
    failed = _run_stage(env, manifest, output, "features")
    assert failed.returncode == 9
    assert not (output / "task_finished").exists()

    env.pop("AF3_FAIL_STAGE")
    recovered = _run_stage(env, manifest, output, "features")
    assert recovered.returncode == 0, recovered.stderr
    assert (output / ".alphafold3-features-complete").is_file()
    output = tmp_path / "missing-structure"
    assert _run_stage(env, manifest, output, "features").returncode == 0
    env["AF3_NO_STRUCTURE"] = "1"
    model = _run_stage(env, manifest, output, "model")
    assert model.returncode != 0
    assert "no expected mmCIF" in model.stderr
    assert not (output / "task_finished").exists()
    env.pop("AF3_NO_STRUCTURE")
    recovered_model = _run_stage(env, manifest, output, "model")
    assert recovered_model.returncode == 0, recovered_model.stderr
    assert (output / "task_finished").is_file()


def _submit_af3(client, headers):
    document = b'{"name":"Test Job","modelSeeds":[1],"sequences":[],"dialect":"alphafold3","version":1}'
    return client.post(
        "/compute/api/post",
        headers=headers,
        data={"task_type": "alphafold3", "file": (io.BytesIO(document), "input.json")},
        content_type="multipart/form-data",
    )


def test_real_alphafold3_policy_precedes_gpu_and_submission_side_effects(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        {"RUNNER_UID": "1234", "RUNNER_GID": "5678", "ENABLED_TASKRUNNERS": "alphafold3"},
    )
    queued = type("Queued", (), {"id": "af3-access-test"})()
    monkeypatch.setattr(module.run_compute_task, "apply_async", lambda *_args, **_kwargs: queued)
    client = module.app.test_client()
    user_headers = _test_client_auth(module)
    admin_headers = _admin_client_auth(module)
    db = module.app.config["user_db"]
    user = db.get_user_by_username("tester")

    before = module.task_store.list_tasks()
    denied = _submit_af3(client, user_headers)
    assert denied.status_code == 403
    assert denied.get_json()["policy_id"] == "alphafold3_noncommercial"
    assert _submit_af3(client, user_headers).status_code == 403
    assert _submit_af3(client, user_headers).status_code == 403
    cooldown = _submit_af3(client, user_headers)
    assert cooldown.status_code == 429
    assert int(cooldown.headers["Retry-After"]) >= 1
    assert _submit_af3(client, admin_headers).status_code == 403
    assert module.task_store.list_tasks() == before
    assert not any(Path(module.CONFIG.workspace_folder).rglob("*"))

    requested = client.post(
        "/compute/api/access/requests",
        headers=user_headers,
        json={"policy_id": "alphafold3_noncommercial", "reason": "Non-commercial structural research"},
    )
    assert requested.status_code == 201
    request_id = requested.get_json()["requests"][0]["id"]
    approved = client.post(
        f"/compute/api/auth/admin/access/requests/{request_id}/decision",
        headers=admin_headers,
        json={"decision": "approved", "basis": "individually_verified", "note": "Eligibility verified"},
    )
    assert approved.status_code == 200
    assert db.get_access_request(request_id)["status"] == "approved"
    assert _submit_af3(client, user_headers).get_json()["error"].startswith("GPU access required")
    db.update_user(user["id"], allow_gpu_use=True)
    assert _submit_af3(client, user_headers).status_code == 302

    api_headers = {"X-API-Key": db.generate_api_key(user["id"])}
    assert _submit_af3(client, api_headers).status_code == 202
    events = db.list_runner_access_events(policy_id="alphafold3_noncommercial", limit=20)
    assert {event["event_type"] for event in events} >= {
        "runner_access_denied", "runner_access_suspended",
        "runner_access_blocked_by_suspension", "runner_access_allowed",
    }


def test_public_alphafold3_catalog_does_not_expose_mounts_or_entitlements(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        {"RUNNER_UID": "1234", "RUNNER_GID": "5678", "ENABLED_TASKRUNNERS": "alphafold3"},
    )
    payload = module.app.test_client().get("/compute/api/types").get_json()
    af3 = next(task for task in payload["task_types"] if task["name"] == "alphafold3")
    serialized = json.dumps(af3)
    assert af3["access"]["restricted"] is True
    assert af3["access"]["policy_id"] == "alphafold3_noncommercial"
    assert "/mnt/db" not in serialized
    assert "/mnt/alphafold3" not in serialized
    assert "requires" not in af3["access"]
    assert "alphafold3_noncommercial" not in serialized.replace(af3["access"]["policy_id"], "")


def test_alphafold3_policy_document_and_image_pin_are_stable():
    policy = yaml.safe_load((ROOT / "docker/runners/alphafold3/policies/noncommercial.yaml").read_text())
    dockerfile = (ROOT / "docker/runners/alphafold3/Dockerfile").read_text(encoding="utf-8")
    assert policy["requestable"] is True
    assert policy["license"]["url"].endswith("/WEIGHTS_TERMS_OF_USE.md")
    assert "c0f97eda2f1f482fd94d3a38bece18c7069b4a5c" in dockerfile
    assert "main" not in next(line for line in dockerfile.splitlines() if line.startswith("ARG ALPHAFOLD3_REF="))
