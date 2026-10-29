# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""A composed Task is admitted and pinned against every family its graph names."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml
from conftest import _load_pssm_module, _test_client_auth

from revocompute import runtime_bundle

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "runners"
FASTA = ROOT / "tests" / "data" / "fasta" / "Sli_S4.fasta"


def _runner_root(tmp_path: Path, *, foreign_gpu: bool, task_gpus: bool, foreign: str = "cpu_runner") -> Path:
    """A copy of the fixture tree whose calculation runs in ``foreign``."""
    root = tmp_path / "runners"
    shutil.copytree(FIXTURES, root)
    task_yaml = root / "multistage_runner" / "tasks" / "predict" / "task.yaml"
    raw = yaml.safe_load(task_yaml.read_text(encoding="utf-8"))
    raw["workflow"][1]["family"] = foreign
    raw["workflow"][1]["requires_gpu"] = foreign_gpu
    raw["gpus"] = task_gpus
    task_yaml.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return root


def _submit(module, *, allow_gpu: bool):
    client = module.app.test_client()
    headers = _test_client_auth(module)
    user = module.app.config["user_db"].get_user_by_username("tester")
    module.app.config["user_db"].update_user(user["id"], allow_gpu_use=allow_gpu)
    with FASTA.open("rb") as handle:
        return client.post(
            "/compute/api/post",
            headers=headers,
            data={
                "task_type": "multistage_runner",
                "file": (handle, FASTA.name),
                "input_roles": "sequence",
            },
            content_type="multipart/form-data",
        )


def _composed_module(
    monkeypatch, tmp_path: Path, *, foreign_gpu: bool, task_gpus: bool, foreign: str = "cpu_runner"
):
    root = _runner_root(tmp_path, foreign_gpu=foreign_gpu, task_gpus=task_gpus, foreign=foreign)
    return _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={
            "RUNNER_UID": "1234",
            "RUNNER_GID": "5678",
            "ENABLED_TASKRUNNERS": f"multistage_runner,{foreign}",
        },
        runner_root=root,
    )


def _queued(module, monkeypatch) -> None:
    class _Async:
        id = "queued-composed"

    monkeypatch.setattr(module.run_compute_task, "apply_async", lambda *_args, **_kwargs: _Async())


def _task_manifest(module, task_id: str) -> dict:
    task = module.task_store.get_task(task_id)
    root = Path(module.app.config["storage_resolver"].get_input_root(task))
    return json.loads((root / "inputs" / "task.json").read_text(encoding="utf-8"))


def test_composed_submission_freezes_node_families_and_pins_every_bundle(monkeypatch, tmp_path):
    module = _composed_module(monkeypatch, tmp_path, foreign_gpu=True, task_gpus=True)
    _queued(module, monkeypatch)

    response = _submit(module, allow_gpu=True)

    assert response.status_code == 302, response.get_data(as_text=True)[:500]
    task_id = response.headers["Location"].rsplit("/", 1)[-1]
    task = module.task_store.get_task(task_id)
    input_form = json.loads(task["input_form"])
    manifest = _task_manifest(module, task_id)
    detail = module.app.test_client().get("/compute/api/types/multistage_runner").get_json()
    assert detail["execution_graph"] == input_form["execution_graph"]
    nodes = {node["id"]: node["family"] for node in input_form["execution_graph"]["document"]["nodes"]}
    assert nodes == {
        "multistage_runner.features": "multistage_runner",
        "multistage_runner.model": "cpu_runner",
    }
    published = runtime_bundle.load_index(module.CONFIG.runtime_bundle_root)
    expected = {"multistage_runner": published["multistage_runner"], "cpu_runner": published["cpu_runner"]}
    assert input_form["runtime_bundles"] == expected
    assert manifest["runtime_bundles"] == expected
    assert "runtime_bundle_sha256" not in input_form
    assert "runtime_bundle_sha256" not in manifest


def test_unready_referenced_family_refuses_submission_without_a_task_row(monkeypatch, tmp_path):
    module = _composed_module(monkeypatch, tmp_path, foreign_gpu=True, task_gpus=True)
    module.app.config["manage_db"].resource_set("slurm_enabled", "true")
    readiness = Path(module.CONFIG.server_dir) / "readiness"
    readiness.mkdir(parents=True, exist_ok=True)
    (readiness / "multistage_runner.json").write_text(
        json.dumps(
            {
                "runner_family": "multistage_runner",
                "status": "READY",
                "ready": True,
                "reason_code": "READY",
            }
        ),
        encoding="utf-8",
    )
    _queued(module, monkeypatch)
    before = {task["md5sum"] for task in module.task_store.list_tasks()}

    response = _submit(module, allow_gpu=True)

    assert response.status_code == 503, response.get_data(as_text=True)[:500]
    body = response.get_json()
    assert body["runner"] == "cpu_runner"
    assert body["status"] == "NOT_CONFIGURED"
    assert {task["md5sum"] for task in module.task_store.list_tasks()} == before


def test_foreign_family_access_policy_must_admit_the_user_and_is_audited(monkeypatch, tmp_path):
    module = _composed_module(
        monkeypatch, tmp_path, foreign_gpu=True, task_gpus=True, foreign="restricted_runner"
    )
    _queued(module, monkeypatch)
    before = {task["md5sum"] for task in module.task_store.list_tasks()}

    response = _submit(module, allow_gpu=True)

    assert response.status_code == 403, response.get_data(as_text=True)[:500]
    assert {task["md5sum"] for task in module.task_store.list_tasks()} == before
    events = module.app.config["user_db"].list_runner_access_events(
        policy_id="synthetic_noncommercial"
    )
    assert events and events[0]["runtime_family"] == "restricted_runner"
    assert events[0]["outcome"] == "denied"


def test_graph_gpu_stage_refuses_when_credit_is_exhausted(monkeypatch, tmp_path):
    module = _composed_module(monkeypatch, tmp_path, foreign_gpu=True, task_gpus=False)

    def exhausted(_user_id):
        raise module.task_runtime.GPUCreditUnavailableError("compute_exhausted")

    monkeypatch.setattr(module.task_store, "require_compute_entitlement", exhausted)
    _queued(module, monkeypatch)
    before = {task["md5sum"] for task in module.task_store.list_tasks()}

    response = _submit(module, allow_gpu=True)

    assert response.status_code == 403, response.get_data(as_text=True)[:500]
    assert response.get_json()["details"][0]["code"] == "gpu_credit_exhausted"
    assert {task["md5sum"] for task in module.task_store.list_tasks()} == before


def test_graph_gpu_stage_refuses_when_gpu_infrastructure_is_unavailable(monkeypatch, tmp_path):
    module = _composed_module(monkeypatch, tmp_path, foreign_gpu=True, task_gpus=False)
    module.app.config["manage_db"].resource_set("slurm_enabled", "true")
    readiness = Path(module.CONFIG.server_dir) / "readiness"
    readiness.mkdir(parents=True, exist_ok=True)
    for family in ("multistage_runner", "cpu_runner"):
        (readiness / f"{family}.json").write_text(
            json.dumps({"runner_family": family, "status": "READY", "ready": True, "reason_code": "READY"}),
            encoding="utf-8",
        )

    class _GpuUnavailable:
        def report(self):
            return {}

        def admission_block(self, *, requires_gpu, force=False):
            if not requires_gpu:
                return None
            return {"component": "gpu_inventory", "reason_code": "evidence_missing", "stale": True}

    module.app.config["infrastructure_readiness"] = _GpuUnavailable()
    _queued(module, monkeypatch)
    before = {task["md5sum"] for task in module.task_store.list_tasks()}

    response = _submit(module, allow_gpu=True)

    assert response.status_code == 503, response.get_data(as_text=True)[:500]
    assert response.get_json()["details"][0]["code"] == "infrastructure_unavailable"
    assert {task["md5sum"] for task in module.task_store.list_tasks()} == before


def test_graph_gpu_stage_takes_exactly_one_submission_reservation(monkeypatch, tmp_path):
    module = _composed_module(monkeypatch, tmp_path, foreign_gpu=True, task_gpus=False)
    _queued(module, monkeypatch)

    response = _submit(module, allow_gpu=True)

    assert response.status_code == 302, response.get_data(as_text=True)[:500]
    task_id = response.headers["Location"].rsplit("/", 1)[-1]
    holds = [hold for hold in module.task_store.list_live_reservations() if hold["task_id"] == task_id]
    assert len(holds) == 1
    assert holds[0]["state"] == "held"
    assert int(holds[0]["quantity"]) > 0


def test_graph_gpu_stage_requires_entitlement_even_when_the_task_is_cpu(monkeypatch, tmp_path):
    module = _composed_module(monkeypatch, tmp_path, foreign_gpu=True, task_gpus=False)
    _queued(module, monkeypatch)
    before = {task["md5sum"] for task in module.task_store.list_tasks()}

    response = _submit(module, allow_gpu=False)

    assert response.status_code == 403, response.get_data(as_text=True)[:500]
    assert "GPU access required" in response.get_data(as_text=True)
    assert {task["md5sum"] for task in module.task_store.list_tasks()} == before
