# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The runtime-image pin contract: submission, observation, completion, recovery.

The gate proves the Slurm wrapper observed the pinned bytes immediately before
it invoked Apptainer.  It does not prove Apptainer opened those bytes: a
promotion rename can still land in the window between the hash and exec.  These
tests drive the real resolver, the real wrapper, the real receipt parser and the
real guarded COMPLETED transition; none of them inspects rendered script text.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import _load_pssm_module, _test_client_auth
from revocompute import runtime_image, stage_state, task_types, task_runtime
from revocompute.db import TaskDatabase
from revocompute.job import JobState
from revocompute.job.runners.slurm_runner import SlurmJob
from revocompute.resource_policy import ResolvedResources
from revocompute.serialization import sha256_file
from revocompute.task_types import RunnerConfig, RuntimeFamily, TaskInputRole, TaskType, WorkflowStage

_IMAGE_SHA_A = "sha256:" + "a" * 64
_IMAGE_SHA_B = "sha256:" + "b" * 64


@pytest.fixture(autouse=True)
def _restore_task_type_registry():
    """Undo this module's narrowed discovery for whatever runs next.

    Loading the submission app with ``ENABLED_TASKRUNNERS=cpu_runner`` installs
    a process-wide registry snapshot that would otherwise survive the test and
    make later suites fail to resolve their own synthetic families.
    """
    previous = task_types._active()
    yield
    task_types._install_snapshot(previous)


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _family(name: str, image: Path) -> SimpleNamespace:
    return SimpleNamespace(name=name, slurm_image=str(image))


def _write_receipt(image: Path, digest: str, *, family: str) -> None:
    evidence = image.parent / "evidence" / family
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / f"{digest.removeprefix('sha256:')}.fixture.receipt.json").write_text(
        json.dumps({"runner_family": family, "sif_sha256": digest}), encoding="utf-8"
    )


def _task_type(family: str, image: Path) -> TaskType:
    return TaskType(
        name=family,
        display_name=family,
        runtime=RuntimeFamily(
            name=family,
            entrypoint=("bash", "/app/run.sh"),
            definition=f"{family}.def",
            slurm_image=str(image),
            image_artifact=image.name,
        ),
        inputs=(
            TaskInputRole(
                name="sequence",
                title="Sequence",
                type="protein_sequence",
                formats=("fasta",),
                minimum=1,
                maximum=1,
            ),
        ),
        stage_markers={"execute": "Execute"},
    )


def _job(
    tmp_path: Path,
    *,
    family: str = "cpu_runner",
    image_name: str = "cpu_runner.sif",
    pin: str | None,
    sif_bytes: bytes = b"pinned-image",
    pins: dict[str, str] | None = None,
    stage_name: str | None = None,
    attempt: int = 1,
    task_id: str = "a" * 32,
    task_store: TaskDatabase | None = None,
) -> SlurmJob:
    inputs = tmp_path / "ws" / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    input_path = inputs / "input.fasta"
    input_path.write_text(">test\nACDE\n", encoding="utf-8")
    image = tmp_path / "images" / image_name
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(sif_bytes)
    recorded = dict(pins or {})
    if pin is not None:
        recorded[family] = pin
    (inputs / "task.json").write_text(json.dumps({"runtime_images": recorded}), encoding="utf-8")
    entities = [
        {"type": "workspace", "workspace_root": str(tmp_path / "ws"), "workspace_key": "k"},
        {
            "type": "file",
            "value": "input.fasta",
            "snapshot_path": str(input_path),
            "snapshot_root": str(inputs),
            "hash": hashlib.sha256(input_path.read_bytes()).hexdigest(),
            "mounted": "/workspace/inputs/input.fasta",
        },
    ]
    return SlurmJob(
        task_id,
        _task_type(family, image),
        RunnerConfig(),
        entities,
        str(tmp_path / "out"),
        username="alice",
        stage_name=stage_name or family,
        stage_attempt=attempt,
        task_store=task_store,
    )


def _run_wrapper(tmp_path: Path, job: SlurmJob, *, job_id: str = "4217", script: str | None = None):
    job._prepare_scratch_dir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    apptainer = bin_dir / "apptainer"
    started = tmp_path / f"command-started-{uuid.uuid4().hex}"
    apptainer.write_text(
        '#!/bin/bash\n: > "${COMMAND_STARTED:?}"\n', encoding="utf-8"
    )
    apptainer.chmod(0o700)
    environment = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "SLURM_JOB_ID": job_id,
        "SLURM_CPUS_PER_TASK": "1",
        "SLURM_NTASKS": "1",
        "COMMAND_STARTED": str(started),
    }
    result = subprocess.run(
        ["bash"],
        input=script if script is not None else job._render_wrapper(),
        text=True,
        capture_output=True,
        env=environment,
        check=False,
        timeout=30,
    )
    job._job_id = job_id
    return result, started


def _db(tmp_path: Path, task_id: str = "a" * 32) -> TaskDatabase:
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    database.upsert_task(
        task_id,
        filename="input.fasta",
        file_path="/tmp/input.fasta",
        uploaded_at=time.time(),
        status="running",
        is_binary=0,
        task_type="cpu_runner",
        storage_key="key",
        submitted_by_user_id=0,
    )
    return database


# -- acceptance gate: admission -------------------------------------------------


class _AvailableInfrastructure:
    def report(self) -> dict:
        return {
            "status": "READY",
            "stale": False,
            "summary": {"scheduler": {"capacity": "AVAILABLE"}, "gpu": {"capacity": "AVAILABLE"}},
        }

    def admission_block(self, **_kwargs):
        return None


def _submission_setup(monkeypatch, tmp_path, *, image: bool, receipt: bool, receipt_family: str | None = None):
    images = tmp_path / "images"
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={
            "RUNNER_UID": "1234",
            "RUNNER_GID": "5678",
            "ENABLED_TASKRUNNERS": "cpu_runner",
            "REVOCOMPUTE_IMAGE_DIR": str(images),
        },
    )
    module.app.config["manage_db"].resource_set("slurm_enabled", "true")
    module.app.config["infrastructure_readiness"] = _AvailableInfrastructure()
    monkeypatch.setattr(module.run_compute_task, "apply_async", lambda *_a, **_k: SimpleNamespace(id="q"))
    readiness = Path(module.CONFIG.server_dir) / "readiness"
    readiness.mkdir(parents=True, exist_ok=True)
    (readiness / "cpu_runner.json").write_text(
        json.dumps(
            {
                "runner_family": "cpu_runner",
                "status": "READY",
                "ready": True,
                "reason_code": "READY",
                "message": "ready",
                "next_action": "none",
            }
        ),
        encoding="utf-8",
    )
    family = module.task_runtime._get_family("cpu_runner")[0]
    path = Path(family.slurm_image)
    if image:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"submission-image")
    if image and receipt:
        _write_receipt(path, sha256_file(path), family=receipt_family or family.name)
    return module, family


def _post(module):
    client = module.app.test_client()
    return client.post(
        "/compute/api/post",
        headers=_test_client_auth(module),
        data={
            "task_type": "cpu_runner",
            "file": (io.BytesIO(b">test\nACDE\n"), "upload.fasta"),
            "input_roles": "sequence",
        },
        content_type="multipart/form-data",
    )


def test_submission_without_a_resolvable_pin_fails_closed_before_side_effects(monkeypatch, tmp_path):
    module, _family_row = _submission_setup(monkeypatch, tmp_path, image=False, receipt=False)

    response = _post(module)

    assert response.status_code == 503, response.get_data(as_text=True)
    assert response.get_json()["reason"] == "RUNTIME_IMAGE_UNPINNED"
    assert module.task_store.list_tasks() == []


def test_submission_without_an_exact_digest_receipt_fails_closed(monkeypatch, tmp_path):
    module, _family_row = _submission_setup(monkeypatch, tmp_path, image=True, receipt=False)

    response = _post(module)

    assert response.status_code == 503, response.get_data(as_text=True)
    assert response.get_json()["reason"] == "RUNTIME_IMAGE_UNPINNED"
    assert module.task_store.list_tasks() == []


def test_a_receipt_for_another_family_cannot_pin_this_family(monkeypatch, tmp_path):
    module, _family_row = _submission_setup(
        monkeypatch, tmp_path, image=True, receipt=True, receipt_family="another_runner"
    )

    response = _post(module)

    assert response.status_code == 503, response.get_data(as_text=True)
    assert "live-test receipt" in response.get_json()["message"]
    assert module.task_store.list_tasks() == []


def test_an_admitted_submission_pins_the_immutable_snapshot_and_the_row(monkeypatch, tmp_path):
    module, family = _submission_setup(monkeypatch, tmp_path, image=True, receipt=True)
    expected = sha256_file(Path(family.slurm_image))

    response = _post(module)

    assert response.status_code in (202, 302), response.get_data(as_text=True)
    task_id = (
        response.get_json()["task_id"]
        if response.is_json
        else response.headers["Location"].rsplit("/", 1)[-1]
    )
    task = module.task_store.get_task(task_id)
    manifest = json.loads(
        (Path(module.app.config["storage_resolver"].get_input_root(task)) / "inputs" / "task.json").read_text()
    )
    assert manifest["runtime_images"] == {"cpu_runner": expected}
    assert json.loads(task["input_form"])["runtime_images"] == {"cpu_runner": expected}


# -- acceptance gate: promotion between submission and launch -------------------


def test_promotion_to_new_bytes_before_launch_refuses_and_never_runs_them(tmp_path):
    image = tmp_path / "images" / "cpu_runner.sif"
    pinned = _digest(b"submission-image")
    job = _job(tmp_path, pin=pinned, sif_bytes=b"submission-image")
    script = job._render_wrapper()
    assert job.runtime_image_observation() is None

    # Promotion renames a different SIF onto the active path after the pin was
    # taken and before the wrapper runs.
    image.write_bytes(b"promoted-image")

    result, started = _run_wrapper(tmp_path, job, script=script)

    assert result.returncode != 0
    assert not started.exists(), "Apptainer must not run bytes the pin does not name"
    assert job.runtime_image_observation() is None
    receipt = Path(job.runtime_image_receipt_path).read_text(encoding="utf-8")
    assert f"expected_sha256={pinned}" in receipt
    assert f"observed_sha256={_digest(b'promoted-image')}" in receipt


def test_attempt_creation_never_writes_a_runtime_image_identity(tmp_path):
    database = _db(tmp_path)
    try:
        database.begin_stage_attempt(task_id="a" * 32, stage_index=0, stage_name="cpu_runner")
        assert database.list_stage_runs("a" * 32)[0]["runtime_image_sha256"] is None
    finally:
        database.engine.dispose()


def test_expected_and_observed_mismatch_never_completes(tmp_path):
    database = _db(tmp_path)
    try:
        attempt = database.begin_stage_attempt(task_id="a" * 32, stage_index=0, stage_name="cpu_runner")["attempt"]
        assert not database.finish_stage_attempt(
            task_id="a" * 32,
            stage_name="cpu_runner",
            attempt=attempt,
            status=stage_state.COMPLETED,
            reason_code=stage_state.Reason.COMPLETED,
            expected_runtime_image=_IMAGE_SHA_A,
            observed_runtime_image=_IMAGE_SHA_B,
        )
        assert database.list_stage_runs("a" * 32)[0]["status"] == stage_state.QUEUED
        assert database.finish_stage_attempt(
            task_id="a" * 32,
            stage_name="cpu_runner",
            attempt=attempt,
            status=stage_state.COMPLETED,
            reason_code=stage_state.Reason.COMPLETED,
            expected_runtime_image=_IMAGE_SHA_A,
            observed_runtime_image=_IMAGE_SHA_A,
        )
        run = database.list_stage_runs("a" * 32)[0]
        assert run["runtime_image_sha256"] == _IMAGE_SHA_A
    finally:
        database.engine.dispose()


# -- acceptance gate: receipt presence and integrity ----------------------------


def test_missing_or_corrupted_schema_two_receipt_never_completes(tmp_path):
    job = _job(tmp_path, pin=_digest(b"pinned-image"))
    result, _started = _run_wrapper(tmp_path, job)
    assert result.returncode == 0, result.stderr
    assert job.runtime_image_observation() is not None

    receipt = Path(job.runtime_image_receipt_path)
    receipt.unlink()
    assert job.runtime_image_observation() is None

    receipt.write_text("schema_version=2\ntask_id=a\n", encoding="utf-8")
    assert job.runtime_image_observation() is None

    receipt.write_text(
        "schema_version=2\n"
        f"task_id={job.task_id}\nstage=cpu_runner\nattempt=1\nfamily=cpu_runner\n"
        "slurm_job_id=4217\nexpected_sha256=not-a-digest\n"
        "observed_sha256=not-a-digest\nobserved_at=1\n",
        encoding="utf-8",
    )
    assert job.runtime_image_observation() is None


def test_schema_one_adoption_leaves_the_image_observation_available(tmp_path):
    job = _job(tmp_path, pin=_digest(b"pinned-image"))
    result, _started = _run_wrapper(tmp_path, job)
    assert result.returncode == 0, result.stderr
    # The wrapper wrote the schema-1 allocation receipt at start and the schema-2
    # image observation immediately before exec.
    assert job.read_allocation_receipt() is not None
    observation = job.runtime_image_observation()
    assert observation is not None

    # ``_notify_dispatched`` adopts and deletes the schema-1 receipt before the
    # scientific launch; the image observation must survive that deletion.
    job.discard_allocation_receipt()

    assert job.read_allocation_receipt() is None
    assert job.runtime_image_observation() == observation


# -- acceptance gate: attribution -----------------------------------------------


def test_wrong_job_id_or_attempt_in_the_receipt_is_rejected(tmp_path):
    job = _job(tmp_path, pin=_digest(b"pinned-image"), attempt=1)
    result, _started = _run_wrapper(tmp_path, job, job_id="4217")
    assert result.returncode == 0, result.stderr
    assert job.runtime_image_observation() is not None

    job._job_id = "9999"
    assert job.runtime_image_observation() is None
    job._job_id = "4217"

    # Copy the valid receipt to the path a different attempt would read; its
    # bound attempt still makes it that attempt's evidence, not attempt 2's.
    receipt = Path(job.runtime_image_receipt_path)
    new_path = receipt.with_name(receipt.name.replace("-1.receipt", "-2.receipt"))
    new_path.write_text(receipt.read_text(encoding="utf-8"), encoding="utf-8")
    job._stage_attempt = 2
    assert job.runtime_image_observation() is None


# -- acceptance gate: worker death and recovery ---------------------------------


def test_worker_death_before_observation_cannot_complete_but_recovery_settles(tmp_path):
    database = _db(tmp_path)
    try:
        attempt = database.begin_stage_attempt(task_id="a" * 32, stage_index=0, stage_name="cpu_runner")["attempt"]
        assert not database.finish_stage_attempt(
            task_id="a" * 32,
            stage_name="cpu_runner",
            attempt=attempt,
            status=stage_state.COMPLETED,
            reason_code=stage_state.Reason.COMPLETED,
            expected_runtime_image=_IMAGE_SHA_A,
            observed_runtime_image=None,
        )
        assert database.list_stage_runs("a" * 32)[0]["status"] == stage_state.QUEUED
        assert database.finish_active_stage_runs(
            "a" * 32, status=stage_state.INTERRUPTED, reason_code=stage_state.Reason.WORKER_LOST
        ) == 1
        assert database.list_stage_runs("a" * 32)[0]["status"] == stage_state.INTERRUPTED
        # A resumed execution opens a fresh attempt and still needs an
        # observation of its own; the interrupted attempt's absence is not one.
        resumed = database.begin_stage_attempt(task_id="a" * 32, stage_index=0, stage_name="cpu_runner")
        assert resumed["attempt"] == 2
        assert not database.finish_stage_attempt(
            task_id="a" * 32,
            stage_name="cpu_runner",
            attempt=2,
            status=stage_state.COMPLETED,
            reason_code=stage_state.Reason.COMPLETED,
            expected_runtime_image=_IMAGE_SHA_A,
            observed_runtime_image=None,
        )
    finally:
        database.engine.dispose()


def test_an_observation_written_before_worker_death_survives_for_recovery(tmp_path):
    job = _job(tmp_path, pin=_digest(b"pinned-image"))
    result, _started = _run_wrapper(tmp_path, job)
    assert result.returncode == 0, result.stderr
    # The worker died before settling; a fresh reader of the same attempt still
    # finds the durable observation and it still binds this attempt.
    fresh = _job(tmp_path, pin=_digest(b"pinned-image"))
    fresh._job_id = "4217"
    assert fresh.runtime_image_observation() is not None
    observation = fresh.runtime_image_observation()
    # A stale observation from another pin is not this attempt's evidence.
    stale = _job(tmp_path, pin=_IMAGE_SHA_A)
    stale._job_id = "4217"
    assert stale.runtime_image_observation() is None
    assert observation.observed == _digest(b"pinned-image")


# -- acceptance gate: resumed workflow is not current ---------------------------


def _workflow_type(family: str) -> TaskType:
    stage = WorkflowStage(family, "Only stage", False, (), ("execute",))
    return TaskType(
        name=family,
        display_name=family,
        runtime=RuntimeFamily(
            name=family, entrypoint=("bash", "run.sh"), definition="x.def", slurm_image="x.sif"
        ),
        inputs=(),
        stage_markers={"execute": "Execute"},
        workflow=(stage,),
    )


@pytest.mark.parametrize("observed", [None, _IMAGE_SHA_B])
def test_a_completed_row_without_an_equal_observation_is_not_current(tmp_path, observed):
    database = _db(tmp_path)
    try:
        task_id = "a" * 32
        database.update_task(
            task_id, input_form=json.dumps({"runtime_images": {"cpu_runner": _IMAGE_SHA_A}})
        )
        attempt = database.begin_stage_attempt(
            task_id=task_id, stage_index=0, stage_name="cpu_runner"
        )["attempt"]
        with database.engine.begin() as connection:
            connection.exec_driver_sql(
                "UPDATE stage_runs SET status='COMPLETED', runtime_image_sha256=? "
                "WHERE task_id=? AND stage_name='cpu_runner' AND attempt=?",
                (observed, task_id, attempt),
            )
        recorded = database.list_stage_runs(task_id)[0]
        tt = _workflow_type("cpu_runner")
        items = [{"name": "cpu_runner", "status": stage_state.COMPLETED}]
        task_runtime._attach_stage_dependencies(
            database.get_task(task_id), tt, items, {"cpu_runner": recorded}, None
        )
        assert items[0]["dependency"] != "completed"
    finally:
        database.engine.dispose()


def test_a_completed_row_with_the_equal_observation_is_current(tmp_path):
    database = _db(tmp_path)
    try:
        task_id = "a" * 32
        database.update_task(
            task_id, input_form=json.dumps({"runtime_images": {"cpu_runner": _IMAGE_SHA_A}})
        )
        attempt = database.begin_stage_attempt(
            task_id=task_id, stage_index=0, stage_name="cpu_runner"
        )["attempt"]
        with database.engine.begin() as connection:
            connection.exec_driver_sql(
                "UPDATE stage_runs SET status='COMPLETED', runtime_image_sha256=? "
                "WHERE task_id=? AND stage_name='cpu_runner' AND attempt=?",
                (_IMAGE_SHA_A, task_id, attempt),
            )
        recorded = database.list_stage_runs(task_id)[0]
        tt = _workflow_type("cpu_runner")
        items = [{"name": "cpu_runner", "status": stage_state.COMPLETED}]
        task_runtime._attach_stage_dependencies(
            database.get_task(task_id), tt, items, {"cpu_runner": recorded}, None
        )
        assert items[0]["dependency"] == "completed"
    finally:
        database.engine.dispose()


# -- acceptance gate: independent families --------------------------------------


def test_multiple_families_pin_and_observe_independently(tmp_path):
    alpha = tmp_path / "images" / "alpha.sif"
    beta = tmp_path / "images" / "beta.sif"
    alpha.parent.mkdir(parents=True, exist_ok=True)
    alpha.write_bytes(b"alpha-bytes")
    beta.write_bytes(b"beta-bytes")
    alpha_digest, beta_digest = sha256_file(alpha), sha256_file(beta)
    alpha_job = _job(
        tmp_path,
        family="alpha",
        image_name="alpha.sif",
        pin=alpha_digest,
        sif_bytes=b"alpha-bytes",
        pins={"beta": beta_digest},
        stage_name="alpha.stage",
    )
    beta_job = _job(
        tmp_path,
        family="beta",
        image_name="beta.sif",
        pin=beta_digest,
        sif_bytes=b"beta-bytes",
        pins={"alpha": alpha_digest},
        stage_name="beta.stage",
    )

    alpha_result, _ = _run_wrapper(tmp_path, alpha_job)
    beta_result, _ = _run_wrapper(tmp_path, beta_job)

    assert alpha_result.returncode == 0, alpha_result.stderr
    assert beta_result.returncode == 0, beta_result.stderr
    alpha_observation = alpha_job.runtime_image_observation()
    beta_observation = beta_job.runtime_image_observation()
    assert alpha_observation.family == "alpha" and alpha_observation.observed == alpha_digest
    assert beta_observation.family == "beta" and beta_observation.observed == beta_digest

    # A task that pins only the sibling family has no pin for this one: the
    # wrapper fails closed instead of borrowing another family's digest.
    wrong = _job(
        tmp_path,
        family="alpha",
        image_name="alpha.sif",
        pin=None,
        sif_bytes=b"alpha-bytes",
        pins={"beta": beta_digest},
    )
    wrong_result, wrong_started = _run_wrapper(tmp_path, wrong)
    assert wrong_result.returncode != 0
    assert not wrong_started.exists()
    assert wrong.runtime_image_observation() is None


# -- acceptance gate: resolver boundary -----------------------------------------


def test_resolver_binds_the_receipt_to_the_family_and_the_path(tmp_path):
    image = tmp_path / "images" / "cpu_runner.sif"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"sif")
    family = _family("cpu_runner", image)
    digest = sha256_file(image)

    with pytest.raises(runtime_image.RuntimeImageError):
        runtime_image.runtime_image_for_submission(family)

    _write_receipt(image, digest, family="cpu_runner")
    resolved = runtime_image.runtime_image_for_submission(family)
    assert resolved.path == str(image)
    assert resolved.digest == digest

    # The digest is of the bytes at the path, not a name the caller supplied.
    image.write_bytes(b"replaced")
    with pytest.raises(runtime_image.RuntimeImageError):
        runtime_image.runtime_image_for_submission(family)
    replaced = sha256_file(image)
    _write_receipt(image, replaced, family="cpu_runner")
    assert runtime_image.runtime_image_for_submission(family).digest == replaced != digest


def test_the_observation_parser_requires_attribution_and_digests():
    valid = (
        "schema_version=2\n"
        "task_id=t\nstage=s\nattempt=1\nfamily=f\nslurm_job_id=42\n"
        f"expected_sha256={_IMAGE_SHA_A}\nobserved_sha256={_IMAGE_SHA_A}\nobserved_at=1\n"
    )
    observation = runtime_image.parse_runtime_image_receipt(valid)
    assert observation == runtime_image.RuntimeImageObservation(
        task_id="t",
        stage_name="s",
        attempt=1,
        family="f",
        slurm_job_id="42",
        expected=_IMAGE_SHA_A,
        observed=_IMAGE_SHA_A,
    )
    for broken in (
        valid.replace("schema_version=2", "schema_version=1"),
        valid.replace("slurm_job_id=42", "slurm_job_id=not-a-job"),
        valid.replace("attempt=1", "attempt=zero"),
        valid.replace(f"observed_sha256={_IMAGE_SHA_A}", "observed_sha256=nope"),
        valid.replace(f"expected_sha256={_IMAGE_SHA_A}", "expected_sha256="),
    ):
        assert runtime_image.parse_runtime_image_receipt(broken) is None


# -- acceptance gate: attribution beyond job id and attempt ---------------------


def test_an_observation_for_another_stage_is_not_this_attempts_evidence(tmp_path):
    writer = _job(tmp_path, pin=_digest(b"pinned-image"), stage_name="stage_a")
    result, _started = _run_wrapper(tmp_path, writer)
    assert result.returncode == 0, result.stderr
    reader = _job(tmp_path, pin=_digest(b"pinned-image"), stage_name="stage_b")
    reader._job_id = "4217"
    # Same file, so only the attribution comparison can reject it.
    Path(reader.runtime_image_receipt_path).parent.mkdir(parents=True, exist_ok=True)
    Path(reader.runtime_image_receipt_path).write_text(
        Path(writer.runtime_image_receipt_path).read_text(encoding="utf-8"), encoding="utf-8"
    )
    assert reader.runtime_image_observation() is None


def test_an_observation_for_another_family_is_not_this_attempts_evidence(tmp_path):
    digest = _digest(b"pinned-image")
    writer = _job(tmp_path, pin=digest, family="cpu_runner", stage_name="stage_a")
    result, _started = _run_wrapper(tmp_path, writer)
    assert result.returncode == 0, result.stderr
    reader = _job(
        tmp_path,
        pin=digest,
        family="other_runner",
        image_name="other_runner.sif",
        stage_name="stage_a",
    )
    reader._job_id = "4217"
    Path(reader.runtime_image_receipt_path).parent.mkdir(parents=True, exist_ok=True)
    Path(reader.runtime_image_receipt_path).write_text(
        Path(writer.runtime_image_receipt_path).read_text(encoding="utf-8"), encoding="utf-8"
    )
    assert reader.runtime_image_observation() is None


def test_a_task_row_that_disagrees_with_the_snapshot_pin_refuses_launch(tmp_path):
    database = _db(tmp_path)
    try:
        database.update_task("a" * 32, input_form=json.dumps({"runtime_images": {"cpu_runner": _IMAGE_SHA_A}}))
        job = _job(tmp_path, pin=_digest(b"pinned-image"), task_store=database)
        with pytest.raises(RuntimeError):
            job._pinned_runtime_image_digest()
        with pytest.raises(RuntimeError):
            job._render_wrapper()
    finally:
        database.engine.dispose()
