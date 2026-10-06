# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""What the server does and does not publish as a result artifact.

Two runner-owned facts reach the published manifest here: the completion
sentinel is operational state and never an artifact, and a runner may declare
how each of its own files is presented.  Both are asserted through the public
manifest and the real parser, never through repository text.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import stat
import uuid

import pytest
from revocompute.result_storyboard import ResultContractError, declared_file_roles, load_expected_file_tree
from revocompute.task_types import ArtifactSelector, ResultView

from conftest import _load_pssm_module, _upsert_task_for_user


def _finished_task(module, tmp_path, task_type: str = "gremlin") -> str:
    task_id = uuid.uuid4().hex
    result_dir = tmp_path / "result"
    result_dir.mkdir()
    _upsert_task_for_user(
        module,
        task_id,
        filename="input.fasta",
        file_path=result_dir / "input.fasta",
        result_dir=result_dir,
        username="tester",
        task_type=task_type,
    )
    return task_id


def _finalize(module, task_id: str, files: dict[str, str]) -> dict:
    task = module.task_store.get_task(task_id)
    result_dir = Path(module.app.config["storage_resolver"].get_task_root(task))
    for name, content in files.items():
        path = result_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    module.task_runtime._finalize_results_manifest(task, execution_state="completed", finished_at=1_700_000_000)
    with open(result_dir / "manifest.json", encoding="utf-8") as handle:
        return json.load(handle)


def _role_view(role: str, path: str) -> ResultView:
    return ResultView(
        plugin="evidence-bundle",
        id="declared",
        role=role,
        title="Declared",
        description="Synthetic view for a role-precedence test.",
        sources={"items": (ArtifactSelector(value=path, is_glob=False, required=True),)},
    )


def test_success_sentinel_is_not_published(monkeypatch, tmp_path) -> None:
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id = _finished_task(module, tmp_path)
    manifest = _finalize(
        module,
        task_id,
        {
            "log/task_finished": "",
            "pssm_msa/input_ascii_mtx_file": "pssm\n",
            "execution/slurm-123.stdout.log": "ran\n",
        },
    )

    published = {artifact["path"] for artifact in manifest["artifacts"]}
    assert "log/task_finished" not in published
    assert "log/task_finished" not in json.dumps(manifest)
    # The SLURM capture log is a diagnostic the user still needs.
    assert "execution/slurm-123.stdout.log" in published
    # Suppressing the sentinel does not fabricate a passing output check.
    assert isinstance(manifest["output_check"]["state"], str)


def test_other_files_named_task_finished_stay_published(monkeypatch, tmp_path) -> None:
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id = _finished_task(module, tmp_path)
    manifest = _finalize(
        module,
        task_id,
        {
            "task_finished_summary.txt": "a real result\n",
            "nested/task_finished/notes.txt": "a real result\n",
        },
    )

    published = {artifact["path"] for artifact in manifest["artifacts"]}
    assert "task_finished_summary.txt" in published
    assert "nested/task_finished/notes.txt" in published


def test_declared_role_overrides_the_default_classification() -> None:
    import revocompute.task_runtime as task_runtime

    artifacts = [{"path": "notes.txt", "size": 7, "role": "artifact"}]
    task_runtime._resolve_result_views(_type_with(("main", "artifact", "notes.txt")), artifacts, ".", {"notes.txt": "provenance"})
    assert artifacts[0]["role"] == "provenance"


def test_declared_provenance_role_is_not_downgraded_by_view_membership() -> None:
    import revocompute.task_runtime as task_runtime

    artifacts = [{"path": "ranked/rank_0.cif", "size": 10, "role": "provenance"}]
    task_runtime._resolve_result_views(
        _type_with(("main", "evidence", "ranked/rank_0.cif")), artifacts, ".", {"ranked/rank_0.cif": "provenance"}
    )
    assert artifacts[0]["role"] == "provenance"


def test_primary_view_outranks_a_declared_role() -> None:
    import revocompute.task_runtime as task_runtime

    artifacts = [{"path": "summary.json", "size": 10, "role": "artifact"}]
    task_runtime._resolve_result_views(_type_with(("main", "primary", "summary.json")), artifacts, ".", {"summary.json": "diagnostic"})
    assert artifacts[0]["role"] == "primary"


def test_declared_role_parses_from_expected_files(tmp_path) -> None:
    declaration = tmp_path / "expected_files.yaml"
    declaration.write_text(
        "result:\n"
        "  files:\n"
        "    summary:\n"
        "      path: summary.json\n"
        "      required: true\n"
        "      role: diagnostic\n",
        encoding="utf-8",
    )
    assert load_expected_file_tree(declaration)["summary"]["role"] == "diagnostic"



def test_declared_roles_map_exact_paths_and_globs_onto_published_paths() -> None:
    roles = declared_file_roles(
        {
            "structures": {"pattern": "ranked/rank_*.cif", "cardinality": "many", "required": True, "role": "artifact"},
            "metadata": {"path": "run_metadata.json", "cardinality": "one", "required": True, "role": "provenance"},
            "absent": {"path": "not_published.json", "cardinality": "one", "required": False, "role": "diagnostic"},
            "undeclared": {"path": "summary.json", "cardinality": "one", "required": True},
        },
        ["ranked/rank_0.cif", "ranked/rank_1.cif", "run_metadata.json", "summary.json"],
    )
    assert roles == {
        "ranked/rank_0.cif": "artifact",
        "ranked/rank_1.cif": "artifact",
        "run_metadata.json": "provenance",
    }


@pytest.mark.parametrize("role", ["primary", "scientific"])
def test_unsupported_declared_role_is_rejected(tmp_path, role) -> None:
    declaration = tmp_path / "expected_files.yaml"
    declaration.write_text(
        f"result:\n  files:\n    summary:\n      path: summary.json\n      required: true\n      role: {role}\n",
        encoding="utf-8",
    )
    with pytest.raises(ResultContractError, match="role must be one of"):
        load_expected_file_tree(declaration)


def test_empty_declared_role_is_rejected(tmp_path) -> None:
    declaration = tmp_path / "expected_files.yaml"
    declaration.write_text(
        "result:\n  files:\n    summary:\n      path: summary.json\n      required: true\n      role:\n",
        encoding="utf-8",
    )
    with pytest.raises(ResultContractError, match="role must be one of"):
        load_expected_file_tree(declaration)


def test_declared_role_survives_the_published_manifest(monkeypatch, tmp_path) -> None:
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678", "ENABLED_TASKRUNNERS": "chai1"},
    )
    task_id = _finished_task(module, tmp_path, task_type="chai1_predict")
    task = module.task_store.get_task(task_id)
    result_dir = Path(module.app.config["storage_resolver"].get_task_root(task))
    (result_dir / "ranking.json").write_text('{"order": []}\n', encoding="utf-8")
    (result_dir / "run_metadata.json").write_text('{"seed": 0}\n', encoding="utf-8")
    (result_dir / "ranked").mkdir()
    (result_dir / "ranked" / "rank_0.cif").write_text("data_x\n", encoding="utf-8")

    # A runner-owned declaration supplied as a fixture.  ``run_metadata.json``
    # is also a source of a declared non-primary view, so its declaration must
    # outrank that view membership; ``ranking.json`` is not in any view at all.
    monkeypatch.setattr(
        module.task_runtime,
        "expected_file_tree",
        lambda *_args: {
            "structures": {
                "pattern": "ranked/rank_*.cif",
                "cardinality": "many",
                "required": True,
                "type": "structure",
            },
            "metadata": {
                "path": "run_metadata.json",
                "cardinality": "one",
                "required": True,
                "type": "json",
                "role": "diagnostic",
            },
            "ranking": {
                "path": "ranking.json",
                "cardinality": "one",
                "required": True,
                "type": "json",
                "role": "provenance",
            },
        },
    )
    monkeypatch.setattr(module.task_runtime, "storyboard_declaration", lambda *_args: None)

    module.task_runtime._finalize_results_manifest(task, execution_state="completed", finished_at=1_700_000_000)
    with open(result_dir / "manifest.json", encoding="utf-8") as handle:
        manifest = json.load(handle)

    by_path = {artifact["path"]: artifact for artifact in manifest["artifacts"]}
    # The declaration outranks the file's membership in an evidence view.
    assert by_path["run_metadata.json"]["role"] == "diagnostic"
    assert by_path["ranking.json"]["role"] == "provenance"
    # The primary view keeps ownership of its own sources.
    assert by_path["ranked/rank_0.cif"]["role"] == "primary"
    # Nothing but the published artifact schema is serialized.
    assert set(by_path["ranking.json"]) == {
        "path",
        "size",
        "sha256",
        "media_type",
        "preview",
        "capability",
        "role",
    }




def test_declared_role_reaches_an_artifact_that_is_not_a_view_source() -> None:
    """A declaration is not limited to files some view already names."""
    import revocompute.task_runtime as task_runtime

    artifacts = [{"path": "model/metadata.json", "size": 10, "role": "artifact"}]
    task_runtime._resolve_result_views(
        _type_with(("main", "primary", "summary.json")), artifacts, ".", {"model/metadata.json": "provenance"}
    )
    assert artifacts[0]["role"] == "provenance"


def test_declared_evidence_does_not_downgrade_a_diagnostic_artifact() -> None:
    import revocompute.task_runtime as task_runtime

    artifacts = [{"path": "execution/run.log", "size": 10, "role": "diagnostic"}]
    task_runtime._resolve_result_views(None, artifacts, ".", {"execution/run.log": "evidence"})
    assert artifacts[0]["role"] == "diagnostic"


def test_exact_path_declarations_reach_the_published_manifest(monkeypatch, tmp_path) -> None:
    """Every declared role is carried to the published artifact, not only globs."""
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678", "ENABLED_TASKRUNNERS": "chai1"},
    )
    task_id = _finished_task(module, tmp_path, task_type="chai1_predict")
    task = module.task_store.get_task(task_id)
    result_dir = Path(module.app.config["storage_resolver"].get_task_root(task))
    for name in (
        "summary.json",
        "alignment/statistics.json",
        "model/metadata.json",
        "model/training_history.csv",
        "profiles/profile.tsv",
    ):
        path = result_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("value\n", encoding="utf-8")
    (result_dir / "ranked").mkdir()
    (result_dir / "ranked" / "rank_0.cif").write_text("data_x\n", encoding="utf-8")

    # A file-tree fixture built the way a runner writes one: mostly exact
    # ``path:`` declarations, one glob, and one entry with no role at all.
    monkeypatch.setattr(
        module.task_runtime,
        "expected_file_tree",
        lambda *_args: {
            "summary": {"path": "summary.json", "cardinality": "one", "required": True, "role": "provenance"},
            "statistics": {
                "path": "alignment/statistics.json",
                "cardinality": "one",
                "required": True,
                "role": "evidence",
            },
            "metadata": {"path": "model/metadata.json", "cardinality": "one", "required": True, "role": "provenance"},
            "history": {
                "path": "model/training_history.csv",
                "cardinality": "one",
                "required": True,
                "role": "diagnostic",
            },
            "profile": {"path": "profiles/profile.tsv", "cardinality": "one", "required": True, "role": "evidence"},
            "structures": {
                "pattern": "ranked/rank_*.cif",
                "cardinality": "many",
                "required": True,
                "role": "artifact",
            },
        },
    )
    monkeypatch.setattr(module.task_runtime, "storyboard_declaration", lambda *_args: None)

    module.task_runtime._finalize_results_manifest(task, execution_state="completed", finished_at=1_700_000_000)
    with open(result_dir / "manifest.json", encoding="utf-8") as handle:
        manifest = json.load(handle)

    by_path = {artifact["path"]: artifact["role"] for artifact in manifest["artifacts"]}
    assert by_path["summary.json"] == "provenance"
    assert by_path["alignment/statistics.json"] == "evidence"
    assert by_path["model/metadata.json"] == "provenance"
    assert by_path["model/training_history.csv"] == "diagnostic"
    assert by_path["profiles/profile.tsv"] == "evidence"
    # A declared glob reaches the published path too, but the task's primary
    # view still owns its own sources.
    assert by_path["ranked/rank_0.cif"] == "primary"


def _type_with(view: tuple[str, str, str]):
    view_id, role, path = view
    return type("TaskType", (), {"result_workspace": (replace(_role_view(role, path), id=view_id),)})()


# ---------------------------------------------------------------------------
# The Runner output directory is an untrusted filesystem namespace.
# ---------------------------------------------------------------------------


def _finalize_dir(module, task_id: str, build) -> tuple[dict, Path]:
    """Finalize a task whose result tree *build* populates, returning the manifest."""
    task = module.task_store.get_task(task_id)
    result_dir = Path(module.app.config["storage_resolver"].get_task_root(task))
    build(result_dir)
    module.task_runtime._finalize_results_manifest(task, execution_state="completed", finished_at=1_700_000_000)
    with open(result_dir / "manifest.json", encoding="utf-8") as handle:
        return json.load(handle), result_dir


def test_a_symlink_out_of_the_result_root_is_never_published(monkeypatch, tmp_path) -> None:
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id = _finished_task(module, tmp_path)
    outside = tmp_path / "host-secret.txt"
    outside.write_text("host data\n", encoding="utf-8")

    def build(result_dir: Path) -> None:
        (result_dir / "real.txt").write_text("real result\n", encoding="utf-8")
        (result_dir / "escape.txt").symlink_to(outside)
        (result_dir / "linked-dir").symlink_to(tmp_path, target_is_directory=True)

    manifest, _result_dir = _finalize_dir(module, task_id, build)

    published = {artifact["path"]: artifact for artifact in manifest["artifacts"]}
    assert "real.txt" in published
    assert "escape.txt" not in published
    # A symlinked directory is not descended into, so its contents never appear
    # under a fabricated path either.
    assert not any(path.startswith("linked-dir/") for path in published)
    assert manifest["output_check"]["state"] == "failed"
    assert any("escape.txt" in problem for problem in manifest["output_check"]["problems"])


def test_a_second_hardlink_to_published_bytes_is_refused(monkeypatch, tmp_path) -> None:
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id = _finished_task(module, tmp_path)
    outside = tmp_path / "aliased.txt"
    outside.write_text("aliased bytes\n", encoding="utf-8")

    def build(result_dir: Path) -> None:
        (result_dir / "plain.txt").write_text("plain result\n", encoding="utf-8")
        os.link(outside, result_dir / "aliased.txt")

    manifest, _result_dir = _finalize_dir(module, task_id, build)

    published = {artifact["path"] for artifact in manifest["artifacts"]}
    assert "plain.txt" in published
    assert "aliased.txt" not in published
    assert manifest["output_check"]["state"] == "failed"
    assert any("hard link" in problem for problem in manifest["output_check"]["problems"])


@pytest.mark.parametrize("kind", ["fifo", "char"])
def test_special_files_are_refused_not_followed(monkeypatch, tmp_path, kind) -> None:
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id = _finished_task(module, tmp_path)
    name = {"fifo": "pipe.txt", "char": "device.txt"}[kind]

    def build(result_dir: Path) -> None:
        (result_dir / "plain.txt").write_text("plain result\n", encoding="utf-8")
        target = result_dir / name
        if kind == "fifo":
            os.mkfifo(target)
        else:
            # A device node stands in for "any non-regular, non-link entry";
            # creating one needs privilege, so a host that refuses it skips the
            # case rather than asserting a weaker property.
            try:
                os.mknod(target, 0o600 | stat.S_IFBLK, os.makedev(7, 200))
            except (PermissionError, OSError) as exc:
                pytest.skip(f"cannot create a device node here: {exc}")

    manifest, _result_dir = _finalize_dir(module, task_id, build)

    published = {artifact["path"] for artifact in manifest["artifacts"]}
    assert "plain.txt" in published
    assert name not in published
    assert manifest["output_check"]["state"] == "failed"
    assert any(name in problem for problem in manifest["output_check"]["problems"])


def test_an_over_capacity_result_tree_is_bounded_not_published_whole(monkeypatch, tmp_path) -> None:
    """The published namespace is bounded in entry count before it is registered."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id = _finished_task(module, tmp_path)
    monkeypatch.setattr(module.task_runtime, "MAX_PUBLISHED_ARTIFACTS", 4)

    def build(result_dir: Path) -> None:
        for index in range(12):
            (result_dir / f"item_{index:02d}.txt").write_text("data\n", encoding="utf-8")

    manifest, _result_dir = _finalize_dir(module, task_id, build)

    assert len(manifest["artifacts"]) == 4
    assert manifest["output_check"]["state"] == "failed"
    assert any("published artifact limit" in problem for problem in manifest["output_check"]["problems"])


def test_an_over_capacity_byte_total_is_bounded(monkeypatch, tmp_path) -> None:
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id = _finished_task(module, tmp_path)
    monkeypatch.setattr(module.task_runtime, "MAX_PUBLISHED_BYTES", 10)

    def build(result_dir: Path) -> None:
        (result_dir / "big_a.bin").write_bytes(b"a" * 8)
        (result_dir / "big_b.bin").write_bytes(b"b" * 8)

    manifest, _result_dir = _finalize_dir(module, task_id, build)

    assert manifest["total_size"] <= 10
    assert len(manifest["artifacts"]) == 1
    assert manifest["output_check"]["state"] == "failed"
    assert any("published artifact limit" in problem for problem in manifest["output_check"]["problems"])


def test_a_swapped_file_after_the_manifest_is_not_reachable(monkeypatch, tmp_path) -> None:
    """Hash/size evidence describes the bytes registered, and later swaps are detected."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id = _finished_task(module, tmp_path)

    def build(result_dir: Path) -> None:
        (result_dir / "result.txt").write_text("original bytes\n", encoding="utf-8")

    manifest, result_dir = _finalize_dir(module, task_id, build)
    artifact = next(item for item in manifest["artifacts"] if item["path"] == "result.txt")
    assert artifact["sha256"] == hashlib.sha256(b"original bytes\n").hexdigest()

    # The published digest no longer describes the file: the resolver refuses to
    # serve it rather than handing the caller substituted bytes.
    (result_dir / "result.txt").write_text("substituted bytes\n", encoding="utf-8")
    task = module.task_store.get_task(task_id)
    resolved = module.app.config["storage_resolver"].resolve_artifact(task, "result.txt")
    assert resolved is None


def test_a_refused_tree_never_falls_back_to_publishing_it(monkeypatch, tmp_path) -> None:
    """Publication failure must not degrade to 'publish everything'."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id = _finished_task(module, tmp_path)
    outside = tmp_path / "secret.txt"
    outside.write_text("secret\n", encoding="utf-8")

    def build(result_dir: Path) -> None:
        (result_dir / "only.txt").symlink_to(outside)

    manifest, result_dir = _finalize_dir(module, task_id, build)

    published = {artifact["path"] for artifact in manifest["artifacts"]}
    # The server writes its own citations record for a known family; that is a
    # server-owned provenance file, not runner output, and it is the only thing
    # published here.
    assert published <= {"citations.bib"}
    assert manifest["total_size"] == sum(item["size"] for item in manifest["artifacts"])
    # The manifest itself is still the durable record.
    assert (result_dir / "manifest.json").is_file()
    assert manifest["output_check"]["state"] == "failed"
    assert "secret" not in json.dumps(manifest)
