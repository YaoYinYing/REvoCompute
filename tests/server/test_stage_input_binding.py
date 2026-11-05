# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""A produced artifact reaches a consumer as a verified, bound stage input."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import time

import pytest

from revocompute import stage_state
from revocompute import task_runtime
from revocompute.db import TaskDatabase
from revocompute.execution_graph import GraphValidationError, compile_graph, execution_graph_payload
from revocompute.job import STAGE_INPUTS_CONTAINER_DIR, STAGE_INPUTS_DOCUMENT_NAME
from revocompute.resource_policy import ResolvedResources
from revocompute.task_types import ExecutionMode, RuntimeFamily, StagePortSpec, TaskType, WorkflowStage

_IMAGE = "sha256:" + "a" * 64


def _policy() -> ResolvedResources:
    return ResolvedResources(
        cpus=4,
        memory="8G",
        max_runtime_seconds=3600,
        partition="cpu",
        gres=None,
        nodes=1,
        ntasks=1,
        qos=None,
        account=None,
        constraint=None,
        exclusive=False,
        requires_gpu=False,
        sources={},
    )


def _task_type(producer_path: str = "features/*.dat", *, optional: bool = False) -> TaskType:
    runtime = RuntimeFamily("stage_input_runner", ("bash", "run.sh"), "runner.def", "image.sif")
    producer = WorkflowStage(
        "stage_input_runner.features", "Features", False, ("-s", "features"), ("msa",),
        outputs=(StagePortSpec("features", "features", path=producer_path, required=not optional),),
    )
    consumer = WorkflowStage(
        "stage_input_runner.model", "Model", False, ("-s", "model"), ("model",),
        inputs=(StagePortSpec("features", "features", source="stage_input_runner.features:features", required=not optional),),
    )
    return TaskType(
        "stage_input_runner",
        "Staged synthetic calculation",
        runtime,
        (),
        stage_markers={"msa": "MSA", "model": "Model"},
        workflow=(consumer, producer),
    )


def _workspace(tmp_path) -> list[dict]:
    return [{"type": "workspace", "workspace_root": str(tmp_path / "workspace"), "workspace_key": "owner-key"}]


def _prepare(
    tmp_path, monkeypatch, *, producer_path: str = "features/*.dat", optional: bool = False
) -> tuple[TaskDatabase, str, TaskType, Path]:
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    monkeypatch.setattr(task_runtime, "task_store", database)
    task_type = _task_type(producer_path, optional=optional)
    monkeypatch.setattr(task_runtime, "_get_task_type", lambda name: (task_type, None))
    monkeypatch.setattr(task_runtime, "_get_family", lambda name: (task_type.runtime, None))
    task_id = "c" * 32
    database.upsert_task(
        task_id,
        filename="input.fasta",
        file_path="/tmp/input.fasta",
        uploaded_at=time.time(),
        status="queued",
        is_binary=0,
        task_type=task_type.name,
        storage_key="owner-key",
        submitted_by_user_id=0,
    )
    graph = compile_graph(task_type)
    database.update_task(
        task_id,
        input_form=json.dumps({
            "execution_graph": {"ir_version": graph.ir_version, "digest": graph.digest, "document": graph.document},
        }),
    )
    output = tmp_path / "output"
    output.mkdir()
    return database, task_id, task_type, output


def _run(database, task_id, task_type, output, entities) -> str:
    return task_runtime._run_compute_workflow(
        task_id,
        database.get_task(task_id),
        task_type,
        entities,
        str(output),
        {stage.name: _policy() for stage in task_type.workflow},
        lambda _stage: None,
    )


class _Job:
    """A scheduler-free stand-in that publishes the producer's declared output."""

    def __init__(self, stage_tt, output: Path):
        self.stage_tt = stage_tt
        self.output = output

    def submit(self) -> str:
        return "42"

    def poll(self):
        if self.stage_tt.name.endswith("features"):
            (self.output / "features").mkdir(exist_ok=True)
            (self.output / "features" / "2KL8.dat").write_text("features", encoding="utf-8")
        return task_runtime.JobState.COMPLETED

    def runtime_image_observation(self):
        from types import SimpleNamespace

        return SimpleNamespace(expected=_IMAGE, observed=_IMAGE)


def test_the_consumer_reads_a_verified_copy_named_by_a_server_document(tmp_path, monkeypatch):
    database, task_id, task_type, output = _prepare(tmp_path, monkeypatch)
    staged: dict[str, str | None] = {}

    def _create_job(_task_id, stage_tt, _runner, _entities, _output, stage_callback=None, **kwargs):
        staged[stage_tt.name] = kwargs.get("stage_inputs_dir")
        return _Job(stage_tt, output)

    monkeypatch.setattr(task_runtime, "_create_job", _create_job)

    result = _run(database, task_id, task_type, output, _workspace(tmp_path))

    assert result == task_runtime.JobState.COMPLETED
    # A stage whose inputs are all graph-role uploads stages nothing.
    assert staged["stage_input_runner-features"] is None
    directory = Path(staged["stage_input_runner-model"])
    assert directory == tmp_path / "workspace" / "stage_inputs" / "stage_input_runner.model"
    document = json.loads((directory / STAGE_INPUTS_DOCUMENT_NAME).read_text(encoding="utf-8"))
    assert document["version"] == 1
    assert document["stage"] == "stage_input_runner.model"
    assert document["inputs"] == {
        "features": {
            "path": f"{STAGE_INPUTS_CONTAINER_DIR}/features/2KL8.dat",
            "files": [
                {
                    "path": f"{STAGE_INPUTS_CONTAINER_DIR}/features/2KL8.dat",
                    "source_path": "features/2KL8.dat",
                    "sha256": hashlib.sha256(b"features").hexdigest(),
                    "size": 8,
                }
            ],
            "producer": "stage_input_runner.features",
            "producer_attempt": 1,
        }
    }
    # The bytes the consumer is handed are the copy, not the shared output tree,
    # so the consumer's own outputs can never rewrite its input.
    assert (directory / "features" / "2KL8.dat").read_text(encoding="utf-8") == "features"


def test_the_consumer_stages_from_the_attempt_completed_in_this_execution(tmp_path, monkeypatch):
    """A COMPLETED row from an earlier execution is recomputed, not reused."""
    database, task_id, task_type, output = _prepare(tmp_path, monkeypatch)
    (output / "features").mkdir()
    (output / "features" / "2KL8.dat").write_text("stale", encoding="utf-8")
    index = next(i for i, stage in enumerate(task_type.workflow) if stage.name == "stage_input_runner.features")
    attempt = database.begin_stage_attempt(
        task_id=task_id, stage_index=index, stage_name="stage_input_runner.features"
    )
    identity = task_runtime._stage_output_identity(str(output), task_type.workflow[1].outputs)
    assert identity is not None
    assert database.finish_stage_attempt(
        task_id=task_id,
        stage_name="stage_input_runner.features",
        attempt=attempt["attempt"],
        status=stage_state.COMPLETED,
        reason_code="completed",
        output_identity=identity,
        expected_runtime_image=_IMAGE,
        observed_runtime_image=_IMAGE,
    )

    staged: dict[str, str | None] = {}

    def _create_job(_task_id, stage_tt, _runner, _entities, _output, stage_callback=None, **kwargs):
        staged[stage_tt.name] = kwargs.get("stage_inputs_dir")
        return _Job(stage_tt, output)

    monkeypatch.setattr(task_runtime, "_create_job", _create_job)

    result = _run(database, task_id, task_type, output, _workspace(tmp_path))

    assert result == task_runtime.JobState.COMPLETED
    directory = Path(staged["stage_input_runner-model"])
    document = json.loads((directory / STAGE_INPUTS_DOCUMENT_NAME).read_text(encoding="utf-8"))
    entry = document["inputs"]["features"]
    # The consumer's document names the attempt this execution completed, and
    # the bytes are that attempt's, not the earlier row's.
    assert entry["producer_attempt"] == 2
    assert entry["files"][0]["sha256"] == hashlib.sha256(b"features").hexdigest()
    assert (directory / "features" / "2KL8.dat").read_text(encoding="utf-8") == "features"
    assert [
        (run["attempt"], run["status"])
        for run in database.list_stage_runs(task_id)
        if run["stage_name"] == "stage_input_runner.features"
    ] == [(1, "COMPLETED"), (2, "COMPLETED")]


def test_a_consumer_without_an_execution_workspace_is_refused_before_any_allocation(tmp_path, monkeypatch):
    database, task_id, task_type, output = _prepare(tmp_path, monkeypatch)
    created: list[str] = []

    def _create_job(_task_id, stage_tt, _runner, _entities, _output, stage_callback=None, **kwargs):
        created.append(stage_tt.name)
        return _Job(stage_tt, output)

    monkeypatch.setattr(task_runtime, "_create_job", _create_job)

    result = _run(database, task_id, task_type, output, [])

    assert result == task_runtime.JobState.FAILED
    # The producer still ran; only the consumer, which has nowhere to be handed
    # its verified artifact, was refused.
    assert created == ["stage_input_runner-features"]
    diagnostics = database.get_task_diagnostics(task_id) or {}
    assert diagnostics.get("reason_code") == "stage_input_unavailable"
    assert diagnostics.get("stage_id") == "stage_input_runner.model"


def _producer_run(
    tmp_path, monkeypatch, files: dict[str, str], *, producer_path: str = "features/*.dat", optional: bool = False
) -> tuple[str, str, dict, dict]:
    database, task_id, task_type, output = _prepare(
        tmp_path, monkeypatch, producer_path=producer_path, optional=optional
    )
    for relative, content in files.items():
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    graph = compile_graph(task_type)
    identity = task_runtime._stage_output_identity(str(output), task_type.workflow[1].outputs)
    assert identity is not None
    latest = {"stage_input_runner.features": {"status": stage_state.COMPLETED, "output_identity": identity, "attempt": 1}}
    nodes = {node.id: node for node in graph.nodes}
    return str(output), task_id, nodes, latest


def test_reuse_port_files_match_the_declared_glob_not_an_empty_static_prefix():
    port = StagePortSpec("features", "features", path="*/features.pkl")
    identity = {
        "files": [
            {"path": "job/features.pkl", "size": 1, "sha256": "a" * 64},
            {"path": "other.log", "size": 1, "sha256": "b" * 64},
            {"path": "job/unrelated.pkl", "size": 1, "sha256": "c" * 64},
        ]
    }

    assert task_runtime._reuse_port_files(identity, port) == [
        {"path": "job/features.pkl", "size": 1, "sha256": "a" * 64},
    ]


def test_a_multi_file_producer_port_is_staged_as_a_role_directory(tmp_path, monkeypatch):
    output, _task_id, nodes, latest = _producer_run(
        tmp_path, monkeypatch, {"features/a.dat": "a", "features/b.dat": "b"}
    )
    node = nodes["stage_input_runner.model"]
    stage_inputs = tmp_path / "workspace" / "stage_inputs" / node.id

    assert task_runtime._materialize_stage_inputs(str(stage_inputs), output, node, nodes, latest) is None

    document = json.loads((stage_inputs / STAGE_INPUTS_DOCUMENT_NAME).read_text(encoding="utf-8"))
    entry = document["inputs"]["features"]
    # The port's static prefix is the role directory, so a role that is a set of
    # files names that directory rather than inventing a single-file identity.
    assert entry["path"] == f"{STAGE_INPUTS_CONTAINER_DIR}/features"
    assert [item["source_path"] for item in entry["files"]] == ["features/a.dat", "features/b.dat"]
    assert sorted(path.name for path in (stage_inputs / "features").iterdir()) == ["a.dat", "b.dat"]


def test_a_recorded_digest_that_no_longer_matches_the_bytes_is_refused(tmp_path, monkeypatch):
    output, _task_id, nodes, latest = _producer_run(tmp_path, monkeypatch, {"features/2KL8.dat": "features"})
    stale = json.loads(latest["stage_input_runner.features"]["output_identity"])
    stale["files"][0]["sha256"] = "0" * 64
    latest["stage_input_runner.features"]["output_identity"] = json.dumps(stale)
    node = nodes["stage_input_runner.model"]
    stage_inputs = tmp_path / "workspace" / "stage_inputs" / node.id

    refusal = task_runtime._materialize_stage_inputs(str(stage_inputs), output, node, nodes, latest)

    assert refusal == "stage_input_invalid"
    assert not (stage_inputs / STAGE_INPUTS_DOCUMENT_NAME).exists()


def test_an_upstream_stage_that_never_completed_stages_nothing(tmp_path, monkeypatch):
    output, _task_id, nodes, _latest = _producer_run(tmp_path, monkeypatch, {"features/2KL8.dat": "features"})
    node = nodes["stage_input_runner.model"]
    stage_inputs = tmp_path / "workspace" / "stage_inputs" / node.id

    assert task_runtime._materialize_stage_inputs(str(stage_inputs), output, node, nodes, {}) == (
        "stage_input_unavailable"
    )
    assert not (stage_inputs / STAGE_INPUTS_DOCUMENT_NAME).exists()


def test_a_nested_producer_port_keeps_its_layout_below_the_static_prefix(tmp_path, monkeypatch):
    output, _task_id, nodes, latest = _producer_run(
        tmp_path,
        monkeypatch,
        {"features/1abc/a_data.json": "a", "features/1abc/b_data.json": "b"},
        producer_path="features/*/*_data.json",
    )
    node = nodes["stage_input_runner.model"]
    stage_inputs = tmp_path / "workspace" / "stage_inputs" / node.id

    assert task_runtime._materialize_stage_inputs(str(stage_inputs), output, node, nodes, latest) is None

    document = json.loads((stage_inputs / STAGE_INPUTS_DOCUMENT_NAME).read_text(encoding="utf-8"))
    entry = document["inputs"]["features"]
    assert entry["path"] == f"{STAGE_INPUTS_CONTAINER_DIR}/features"
    assert [item["path"] for item in entry["files"]] == [
        f"{STAGE_INPUTS_CONTAINER_DIR}/features/1abc/a_data.json",
        f"{STAGE_INPUTS_CONTAINER_DIR}/features/1abc/b_data.json",
    ]
    assert (stage_inputs / "features" / "1abc" / "b_data.json").read_text(encoding="utf-8") == "b"


def test_an_optional_port_that_published_nothing_leaves_its_role_undeclared(tmp_path, monkeypatch):
    output, _task_id, nodes, latest = _producer_run(
        tmp_path, monkeypatch, {"unrelated/notes.txt": "x"}, optional=True
    )
    node = nodes["stage_input_runner.model"]
    stage_inputs = tmp_path / "workspace" / "stage_inputs" / node.id

    assert task_runtime._materialize_stage_inputs(str(stage_inputs), output, node, nodes, latest) is None

    document = json.loads((stage_inputs / STAGE_INPUTS_DOCUMENT_NAME).read_text(encoding="utf-8"))
    # An optional producer port with no matches is an absent role, not an empty
    # one: the consumer's own declaration says the role may be missing.
    assert document["inputs"] == {}
    assert not (stage_inputs / "features").exists()


def _reuse_task_type() -> TaskType:
    """The same two-stage shape with a manifest-declared model-only mode."""
    base = _task_type()
    mode = ExecutionMode(
        "model_only", "Model from prepared features", ("stage_input_runner.model",), "full",
        {"stage_input_runner.model.features": {
            "role": "prepared_features", "type": "features", "inputs": ["sequence"],
        }},
    )
    return replace(base, execution_modes=(ExecutionMode("full", "Full", tuple(s.name for s in base.workflow)), mode))


def _source_artifact(database, task_id, task_type, output: Path, content: str = "features") -> dict:
    """A finished source Task whose features stage published one verified file."""
    (output / "features").mkdir(parents=True, exist_ok=True)
    (output / "features" / "2KL8.dat").write_text(content, encoding="utf-8")
    index = next(i for i, stage in enumerate(task_type.workflow) if stage.name == "stage_input_runner.features")
    attempt = database.begin_stage_attempt(
        task_id=task_id, stage_index=index, stage_name="stage_input_runner.features"
    )
    identity = task_runtime._stage_output_identity(str(output), task_type.workflow[1].outputs)
    assert identity is not None
    assert database.finish_stage_attempt(
        task_id=task_id, stage_name="stage_input_runner.features", attempt=attempt["attempt"],
        status=stage_state.COMPLETED, reason_code="completed", output_identity=identity,
        expected_runtime_image=_IMAGE, observed_runtime_image=_IMAGE,
    )
    files = json.loads(identity)["files"]
    return {
        "source_task": task_id, "stage": "stage_input_runner.features", "port": "features",
        "digest": task_runtime._reuse_artifact_digest(files),
    }


def _reuse_source_task(tmp_path, monkeypatch, *, owner: int = 0, status: str = "finished"):
    task_type = _reuse_task_type()
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    monkeypatch.setattr(task_runtime, "task_store", database)
    monkeypatch.setattr(task_runtime, "_get_task_type", lambda name: (task_type, None))
    monkeypatch.setattr(task_runtime, "_get_family", lambda name: (task_type.runtime, None))
    source_id = "d" * 32
    sequence = b">source\nACDE\n"
    database.upsert_task(
        source_id, filename="source.fasta", file_path="/tmp/source.fasta", uploaded_at=time.time(),
        status="running", is_binary=0, task_type=task_type.name,
        storage_key="owner-key", submitted_by_user_id=owner,
        input_form=json.dumps({"entities": [{
            "type": "file", "role": "sequence", "relative_path": "source.fasta",
            "hash": hashlib.sha256(sequence).hexdigest(), "size": len(sequence),
        }]}),
    )
    output = tmp_path / "source-output"
    output.mkdir()
    reference = _source_artifact(database, source_id, task_type, output)
    database.update_task(source_id, status=status)
    return database, task_type, source_id, output, reference


def test_a_recorded_file_the_tree_no_longer_holds_refuses_the_whole_artifact(tmp_path, monkeypatch):
    output, _task_id, nodes, latest = _producer_run(
        tmp_path, monkeypatch, {"features/a.dat": "a", "features/b.dat": "b"}
    )
    (Path(output) / "features" / "b.dat").unlink()
    node = nodes["stage_input_runner.model"]
    stage_inputs = tmp_path / "workspace" / "stage_inputs" / node.id

    refusal = task_runtime._materialize_stage_inputs(str(stage_inputs), output, node, nodes, latest)

    # The identity names two files and only one is still published, so this
    # attempt's tree is not the artifact the producer settled.
    assert refusal == "stage_input_invalid"
    assert not (stage_inputs / STAGE_INPUTS_DOCUMENT_NAME).exists()


def test_a_valid_reuse_reference_is_frozen_and_changes_task_identity(tmp_path, monkeypatch):
    database, task_type, source_id, _output, reference = _reuse_source_task(tmp_path, monkeypatch)
    resolved = task_runtime.resolve_reuse_source(reference, user_id=0, expected_type="features")
    assert resolved["source_task"] == source_id
    assert resolved["artifact_digest"] == reference["digest"]
    assert resolved["source_inputs"] == {"sequence": task_runtime.role_input_digest([
        {"sha256": hashlib.sha256(b">source\nACDE\n").hexdigest(), "size": 13},
    ])}
    frozen = execution_graph_payload(task_type, "model_only", {"prepared_features": {
        "source_task": resolved["source_task"], "stage": resolved["stage"], "port": resolved["port"],
        "artifact_digest": resolved["artifact_digest"], "type": resolved["type"],
        "source_inputs": resolved["source_inputs"],
    }})
    assert frozen["document"]["reuse_inputs"]["prepared_features"]["source"]["source_task"] == source_id
    other = dict(reference, digest="1" * 64)
    assert frozen["digest"] != execution_graph_payload(task_type, "model_only", {"prepared_features": {
        "source_task": "e" * 32, "stage": resolved["stage"], "port": resolved["port"],
        "artifact_digest": other["digest"], "type": resolved["type"],
        "source_inputs": resolved["source_inputs"],
    }})["digest"]
    # The same artifact prepared from a different input identity is a different
    # scientific request, so the binding changes the frozen digest too.
    assert frozen["digest"] != execution_graph_payload(task_type, "model_only", {"prepared_features": {
        "source_task": resolved["source_task"], "stage": resolved["stage"], "port": resolved["port"],
        "artifact_digest": resolved["artifact_digest"], "type": resolved["type"],
        "source_inputs": {"sequence": "0" * 64},
    }})["digest"]


def test_reuse_refuses_not_owned_not_completed_and_wrong_identity(tmp_path, monkeypatch):
    database, _task_type_value, _source_id, _output, reference = _reuse_source_task(tmp_path, monkeypatch, owner=7)
    with pytest.raises(task_runtime.ReuseReferenceError, match="another caller") as exc:
        task_runtime.resolve_reuse_source(reference, user_id=0, expected_type="features")
    assert exc.value.reason == "reuse_source_not_owned"

    database, _task_type_value, _source_id, _output, reference = _reuse_source_task(
        tmp_path / "incomplete", monkeypatch, status="running"
    )
    with pytest.raises(task_runtime.ReuseReferenceError, match="has not completed"):
        task_runtime.resolve_reuse_source(reference, user_id=0, expected_type="features")


def test_reuse_refuses_wrong_stage_port_type_and_digest(tmp_path, monkeypatch):
    database, _task_type_value, _source_id, _output, reference = _reuse_source_task(tmp_path, monkeypatch)
    for change, reason in (
        ({"stage": "stage_input_runner.model"}, "reuse_port_unknown"),
        ({"port": "missing"}, "reuse_port_unknown"),
        ({"digest": "0" * 64}, "reuse_digest_mismatch"),
    ):
        with pytest.raises(task_runtime.ReuseReferenceError) as exc:
            task_runtime.resolve_reuse_source({**reference, **change}, user_id=0, expected_type="features")
        assert exc.value.reason == reason
    with pytest.raises(task_runtime.ReuseReferenceError) as exc:
        task_runtime.resolve_reuse_source(reference, user_id=0, expected_type="other")
    assert exc.value.reason == "reuse_type_mismatch"


def test_reuse_refuses_a_superseded_completed_attempt(tmp_path, monkeypatch):
    database, task_type, source_id, output, reference = _reuse_source_task(tmp_path, monkeypatch, status="running")
    index = next(i for i, stage in enumerate(task_type.workflow) if stage.name == "stage_input_runner.features")
    attempt = database.begin_stage_attempt(
        task_id=source_id, stage_index=index, stage_name="stage_input_runner.features"
    )
    database.finish_stage_attempt(
        task_id=source_id, stage_name="stage_input_runner.features", attempt=attempt["attempt"],
        status=stage_state.FAILED, reason_code="allocation_failed",
    )
    database.update_task(source_id, status="finished")
    with pytest.raises(task_runtime.ReuseReferenceError) as exc:
        task_runtime.resolve_reuse_source(reference, user_id=0, expected_type="features")
    assert exc.value.reason == "reuse_stage_not_completed"


def test_model_only_dispatch_materializes_the_source_and_opens_no_producer_attempt(tmp_path, monkeypatch):
    database, task_type, source_id, source_output, reference = _reuse_source_task(tmp_path, monkeypatch)
    frozen_ref = {
        "source_task": source_id, "stage": reference["stage"], "port": reference["port"],
        "artifact_digest": reference["digest"], "type": "features",
        "source_inputs": task_runtime._source_input_identity(database.get_task(source_id)),
    }
    graph = compile_graph(task_type, "model_only", {"prepared_features": frozen_ref})
    consumer_id = "f" * 32
    database.upsert_task(
        consumer_id, filename="input.fasta", file_path="/tmp/input.fasta", uploaded_at=time.time(),
        status="queued", is_binary=0, task_type=task_type.name,
        storage_key="owner-key", submitted_by_user_id=0,
    )
    database.update_task(consumer_id, input_form=json.dumps({
        "execution_graph": {"ir_version": graph.ir_version, "digest": graph.digest, "document": graph.document},
    }))
    monkeypatch.setattr(task_runtime, "_storage", lambda: SimpleNamespace(
        get_output_root=lambda task: str(source_output) if str(task.get("md5sum")) == source_id
        else str(tmp_path / "consumer-output")
    ))
    staged: dict[str, str | None] = {}

    def _create_job(_task_id, stage_tt, _runner, _entities, _output, stage_callback=None, **kwargs):
        staged[stage_tt.name] = kwargs.get("stage_inputs_dir")
        return _Job(stage_tt, tmp_path / "consumer-output")

    monkeypatch.setattr(task_runtime, "_create_job", _create_job)
    output = tmp_path / "consumer-output"
    output.mkdir()
    result = _run(database, consumer_id, task_type, output, _workspace(tmp_path))

    assert result == task_runtime.JobState.COMPLETED
    assert staged == {
        "stage_input_runner-model": str(tmp_path / "workspace" / "stage_inputs" / "stage_input_runner.model")
    }
    document = json.loads((Path(staged["stage_input_runner-model"]) / STAGE_INPUTS_DOCUMENT_NAME).read_text())
    entry = document["inputs"]["features"]
    assert entry["source_task"] == source_id
    assert entry["source_stage"] == "stage_input_runner.features"
    assert entry["files"][0]["sha256"] == hashlib.sha256(b"features").hexdigest()
    # Reuse is a provenance edge, never a second producer execution.
    assert [run["stage_name"] for run in database.list_stage_runs(consumer_id)] == ["stage_input_runner.model"]


@pytest.mark.parametrize(
    ("break_source", "reason"),
    [
        ("changed", "stage_input_invalid"),
        ("deleted", "stage_input_invalid"),
        ("foreign", "stage_input_invalid"),
        ("removed", "stage_input_unavailable"),
        ("input_changed", "stage_input_invalid"),
    ],
)
def test_model_only_dispatch_refuses_a_broken_source_before_any_attempt(
    tmp_path, monkeypatch, break_source, reason
):
    database, task_type, source_id, source_output, reference = _reuse_source_task(
        tmp_path, monkeypatch, owner=0 if break_source != "foreign" else 7
    )
    frozen_source_inputs = task_runtime._source_input_identity(database.get_task(source_id))
    if break_source == "changed":
        (source_output / "features" / "2KL8.dat").write_text("changed", encoding="utf-8")
    if break_source == "deleted":
        import shutil
        shutil.rmtree(source_output)
    if break_source == "removed":
        database.delete_task(source_id)
    if break_source == "input_changed":
        database.update_task(source_id, input_form=json.dumps({"entities": [{
            "type": "file", "role": "sequence", "relative_path": "source.fasta",
            "hash": "0" * 64, "size": 13,
        }]}))
    frozen_ref = {
        "source_task": source_id, "stage": reference["stage"], "port": reference["port"],
        "artifact_digest": reference["digest"], "type": "features",
        "source_inputs": frozen_source_inputs,
    }
    graph = compile_graph(task_type, "model_only", {"prepared_features": frozen_ref})
    consumer_id = "a" * 32
    database.upsert_task(
        consumer_id, filename="input.fasta", file_path="/tmp/input.fasta", uploaded_at=time.time(),
        status="queued", is_binary=0, task_type=task_type.name,
        storage_key="owner-key", submitted_by_user_id=0,
    )
    database.update_task(consumer_id, input_form=json.dumps({
        "execution_graph": {"ir_version": graph.ir_version, "digest": graph.digest, "document": graph.document},
    }))
    monkeypatch.setattr(task_runtime, "_storage", lambda: SimpleNamespace(
        get_output_root=lambda task: str(source_output)
    ))
    created: list[str] = []

    def _create_job(_task_id, stage_tt, _runner, _entities, _output, stage_callback=None, **kwargs):
        created.append(stage_tt.name)
        return _Job(stage_tt, tmp_path / "consumer-output")

    monkeypatch.setattr(task_runtime, "_create_job", _create_job)
    output = tmp_path / "consumer-output"
    output.mkdir()
    result = _run(database, consumer_id, task_type, output, _workspace(tmp_path))

    assert result == task_runtime.JobState.FAILED
    assert created == []
    assert database.list_stage_runs(consumer_id) == []
    assert (database.get_task_diagnostics(consumer_id) or {}).get("reason_code") == reason


def test_a_declared_reuse_role_without_a_reference_is_refused():
    task_type = _reuse_task_type()
    with pytest.raises(GraphValidationError, match="reuse references"):
        compile_graph(task_type, "model_only")
    with pytest.raises(GraphValidationError, match="reuse references"):
        compile_graph(task_type, "model_only", {"prepared_features": {}, "extra": {}})
