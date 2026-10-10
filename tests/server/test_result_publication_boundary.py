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
import shutil
import stat
import uuid
import zipfile

import pytest
from revocompute.result_storyboard import ResultContractError, declared_file_roles, load_expected_file_tree
from revocompute.storage import ResultPublicationError
from revocompute.task_types import ArtifactSelector, ResultView

from conftest import _load_pssm_module, _test_client_auth, _upsert_task_for_user


def _finished_task(module, tmp_path, task_type: str = "cpu_runner") -> str:
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
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678", "ENABLED_TASKRUNNERS": "gpu_runner"},
    )
    task_id = _finished_task(module, tmp_path, task_type="gpu_runner")
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
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678", "ENABLED_TASKRUNNERS": "gpu_runner"},
    )
    task_id = _finished_task(module, tmp_path, task_type="gpu_runner")
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
    monkeypatch.setattr(module.task_runtime, "_published_artifact_limit", lambda: 4)

    def build(result_dir: Path) -> None:
        # Spread across many directories: the guard must stop the walk, not
        # re-trip once per directory.
        for directory in range(12):
            child = result_dir / f"d{directory:02d}"
            child.mkdir()
            (child / "item.txt").write_text("data\n", encoding="utf-8")

    manifest, _result_dir = _finalize_dir(module, task_id, build)

    assert len(manifest["artifacts"]) == 4
    assert sum("capacity limit" in problem for problem in manifest["output_check"]["problems"]) == 1
    assert manifest["output_check"]["state"] == "failed"
    assert any("publication capacity limit" in problem for problem in manifest["output_check"]["problems"])


def test_an_over_capacity_byte_total_is_bounded(monkeypatch, tmp_path) -> None:
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id = _finished_task(module, tmp_path)
    monkeypatch.setattr(module.task_runtime, "_published_byte_limit", lambda: 10)

    def build(result_dir: Path) -> None:
        (result_dir / "big_a.bin").write_bytes(b"a" * 8)
        (result_dir / "big_b.bin").write_bytes(b"b" * 8)

    manifest, _result_dir = _finalize_dir(module, task_id, build)

    assert manifest["total_size"] <= 10
    assert len(manifest["artifacts"]) == 1
    assert manifest["output_check"]["state"] == "failed"
    assert any("publication capacity limit" in problem for problem in manifest["output_check"]["problems"])


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


def test_the_refusal_record_is_bounded_for_a_hostile_tree(monkeypatch, tmp_path) -> None:
    """A tree of refused entries does not grow the manifest one problem per file."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id = _finished_task(module, tmp_path)
    outside = tmp_path / "target.bin"
    outside.write_bytes(b"x")

    def build(result_dir: Path) -> None:
        many = result_dir / "many"
        many.mkdir()
        for index in range(60):
            (many / f"link_{index:02d}.txt").symlink_to(outside)
        (result_dir / "real.txt").write_text("real\n", encoding="utf-8")

    manifest, _result_dir = _finalize_dir(module, task_id, build)

    problems = manifest["output_check"]["problems"]
    # Bounded: a handful of named refusals plus one summary, not 60 entries.
    assert len(problems) <= 30
    assert any("further non-publishable" in problem for problem in problems)
    published = {artifact["path"] for artifact in manifest["artifacts"]}
    assert "real.txt" in published
    assert manifest["output_check"]["state"] == "failed"


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


# ---------------------------------------------------------------------------
# The downloadable ZIP is a publication path, so it consumes the same
# published-artifact identity contract as an ordinary download.  These cases
# replace a finalized artifact out from under the manifest and assert the bytes
# never reach the archive.
# ---------------------------------------------------------------------------


def _archive_manifest(module, task_id: str) -> dict:
    archive_path = Path(module.task_runtime._build_results_archive(module.task_store.get_task(task_id)))
    with zipfile.ZipFile(archive_path) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def _single_artifact_task(module, tmp_path, content: bytes) -> tuple[str, Path, dict]:
    task_id = _finished_task(module, tmp_path)
    manifest, result_dir = _finalize_dir(module, task_id, lambda root: (root / "result.txt").write_bytes(content))
    return task_id, result_dir, manifest


def test_unchanged_published_artifact_archives_with_its_manifest_identity(monkeypatch, tmp_path) -> None:
    """The ordinary case still works and the ZIP entry matches the manifest."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    content = b"score\n1.0\n"
    task_id, _result_dir, manifest = _single_artifact_task(module, tmp_path, content)
    artifact = next(item for item in manifest["artifacts"] if item["path"] == "result.txt")

    entries = _archive_manifest(module, task_id)

    assert entries["result.txt"] == content
    assert artifact["sha256"] == hashlib.sha256(content).hexdigest()
    assert artifact["size"] == len(content)
    assert "manifest.json" in entries


def test_a_regular_file_replaced_after_finalization_fails_the_archive_closed(monkeypatch, tmp_path) -> None:
    """Different regular bytes under the declared name must not be archived."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id, result_dir, _manifest = _single_artifact_task(module, tmp_path, b"original bytes\n")
    result_dir.joinpath("result.txt").write_bytes(b"substituted bytes\n")

    with pytest.raises(FileNotFoundError):
        module.task_runtime._build_results_archive(module.task_store.get_task(task_id))


def test_a_symlink_substitution_after_finalization_cannot_reach_the_archive(monkeypatch, tmp_path) -> None:
    """A post-publication symlink cannot pull target bytes into the ZIP."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id, result_dir, _manifest = _single_artifact_task(module, tmp_path, b"original bytes\n")
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"secret target bytes\n")
    artifact = result_dir / "result.txt"
    artifact.unlink()
    artifact.symlink_to(outside)

    with pytest.raises(FileNotFoundError):
        module.task_runtime._build_results_archive(module.task_store.get_task(task_id))


def test_a_hardlink_substitution_after_finalization_cannot_reach_the_archive(monkeypatch, tmp_path) -> None:
    """A second link defeats the private-link assumption and fails closed."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id, result_dir, _manifest = _single_artifact_task(module, tmp_path, b"original bytes\n")
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"original bytes\n")
    artifact = result_dir / "result.txt"
    artifact.unlink()
    artifact.hardlink_to(outside)

    with pytest.raises(FileNotFoundError):
        module.task_runtime._build_results_archive(module.task_store.get_task(task_id))


def test_a_manifest_path_escaping_the_result_root_fails_closed(monkeypatch, tmp_path) -> None:
    """An entry naming bytes outside the published root is never archived."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id, result_dir, _manifest = _single_artifact_task(module, tmp_path, b"original bytes\n")
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"outside bytes\n")
    (result_dir / "manifest.json").write_text(
        json.dumps({"artifacts": [{"path": "../outside.txt"}]}), encoding="utf-8"
    )

    with pytest.raises(FileNotFoundError):
        module.task_runtime._build_results_archive(module.task_store.get_task(task_id))


def test_the_archive_writes_the_manifest_bytes_it_verified(monkeypatch, tmp_path) -> None:
    """The archived manifest is the exact byte stream that selected the entries.

    A replacement of ``manifest.json`` after the read cannot pair manifest A's
    artifacts with manifest B's bytes: the archive writes the bytes read from the
    verified descriptor, never a later open of the pathname.
    """
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id, result_dir, manifest = _single_artifact_task(module, tmp_path, b"original bytes\n")
    published = (result_dir / "manifest.json").read_bytes()

    entries = _archive_manifest(module, task_id)

    assert entries["manifest.json"] == published
    assert json.loads(entries["manifest.json"])["artifacts"] == manifest["artifacts"]


# ---------------------------------------------------------------------------
# After publication identity has been verified, a consumer must consume the
# verified descriptor, not reopen its pathname.  These drive the public Result
# download endpoint with a file replaced after finalization.
# ---------------------------------------------------------------------------


def _published_task(module, tmp_path, content: bytes) -> tuple[str, Path, dict[str, str]]:
    # The caller identity exists before the task, as it does in production: the
    # test helper only pre-verifies a user it just created, so a task created
    # first would leave the account unverified and the request unauthenticated.
    headers = _test_client_auth(module)
    task_id, result_dir, _manifest = _single_artifact_task(module, tmp_path, content)
    return task_id, result_dir, headers


def test_a_replaced_artifact_cannot_be_served_by_the_result_download(monkeypatch, tmp_path) -> None:
    """The direct download refuses a file whose bytes no longer match the manifest."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id, result_dir, headers = _published_task(module, tmp_path, b"original bytes\n")
    result_dir.joinpath("result.txt").write_bytes(b"substituted bytes\n")

    response = module.app.test_client().get(
        f"/compute/api/results/{task_id}/artifacts/result.txt", headers=headers
    )

    assert response.status_code == 404
    assert b"substituted" not in response.data


def test_an_unchanged_artifact_downloads_its_verified_bytes(monkeypatch, tmp_path) -> None:
    """The ordinary download still returns exactly the published bytes."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    content = b"score\n1.0\n"
    task_id, _result_dir, headers = _published_task(module, tmp_path, content)

    response = module.app.test_client().get(
        f"/compute/api/results/{task_id}/artifacts/result.txt", headers=headers
    )

    assert response.status_code == 200
    assert response.data == content
    assert response.headers["Content-Length"] == str(len(content))


def test_a_single_range_reads_from_the_verified_descriptor(monkeypatch, tmp_path) -> None:
    """A bounded Range is served from the verified descriptor, not a reopen.

    The full-stack smoke asserts this shape, so descriptor-bound delivery must
    keep single-range and unsatisfiable-range semantics.
    """
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    content = b"score\n1.0\n"
    task_id, _result_dir, headers = _published_task(module, tmp_path, content)
    client = module.app.test_client()
    url = f"/compute/api/results/{task_id}/artifacts/result.txt"

    first = client.get(url, headers={**headers, "Range": "bytes=0-0"})
    tail = client.get(url, headers={**headers, "Range": "bytes=-3"})
    unsatisfiable = client.get(url, headers={**headers, "Range": f"bytes={len(content) + 10}-"})

    assert first.status_code == 206
    assert first.data == content[:1]
    assert first.headers["Content-Range"] == f"bytes 0-0/{len(content)}"
    assert first.headers["Content-Length"] == "1"
    assert tail.status_code == 206
    assert tail.data == content[-3:]
    assert unsatisfiable.status_code == 416
    assert unsatisfiable.headers["Content-Range"] == f"bytes */{len(content)}"


def test_the_result_download_never_claims_verified_identity_while_offloading(monkeypatch, tmp_path) -> None:
    """nginx offload is not used where it would reopen the mutable pathname.

    ``RESULT_DOWNLOAD_MODE=nginx`` is accepted for deployment compatibility, but a
    published artifact is delivered from the verified descriptor: an
    ``X-Accel-Redirect`` would hand the bytes to a later pathname open, which
    could serve a file that never satisfied the manifest identity.
    """
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678", "RESULT_DOWNLOAD_MODE": "nginx"},
    )
    content = b"score\n1.0\n"
    task_id, _result_dir, headers = _published_task(module, tmp_path, content)

    response = module.app.test_client().get(
        f"/compute/api/results/{task_id}/artifacts/result.txt", headers=headers
    )

    assert response.status_code == 200
    assert "X-Accel-Redirect" not in response.headers
    assert response.data == content


# ---------------------------------------------------------------------------
# The publication root of trust and the bounded reader.  The manifest is read
# through the canonical verified authority, and a verified descriptor is read in
# bounded chunks rather than with one artifact-sized read.
# ---------------------------------------------------------------------------


def _manifest_task(module, tmp_path, content: bytes = b"score\n1.0\n") -> tuple[str, Path, dict[str, str]]:
    headers = _test_client_auth(module)
    task_id, result_dir, _manifest = _single_artifact_task(module, tmp_path, content)
    return task_id, result_dir, headers


@pytest.mark.parametrize("tamper", ["symlink", "hardlink", "corrupt", "oversized", "replacement"])
def test_the_primary_results_route_fails_closed_on_a_tampered_manifest(monkeypatch, tmp_path, tamper) -> None:
    """A manifest the canonical reader refuses is not served by the results route.

    The manifest authorizes the whole publication and is its own root of trust,
    so a linked, unreadable, oversized, or *replaced* one must produce the
    route's not-found answer rather than a partial payload.  A replacement is
    the hardest case: the substituted file is an ordinary single-link regular
    JSON manifest describing real artifacts, so nothing about the file itself is
    wrong — it is refused because it is not the manifest Core finalized, which
    only the anchor recorded outside the result tree can say.
    """
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id, result_dir, headers = _manifest_task(module, tmp_path)
    manifest_path = result_dir / "manifest.json"
    published = manifest_path.read_bytes()
    outside = tmp_path / f"{tamper}.json"

    if tamper == "symlink":
        outside.write_bytes(published)
        manifest_path.unlink()
        manifest_path.symlink_to(outside)
    elif tamper == "hardlink":
        outside.write_bytes(published)
        manifest_path.unlink()
        manifest_path.hardlink_to(outside)
    elif tamper == "corrupt":
        manifest_path.write_bytes(b"{not a manifest")
    elif tamper == "replacement":
        (result_dir / "smuggled.txt").write_text("undeclared bytes\n", encoding="utf-8")
        replacement = {
            "schema_version": 3,
            "task_id": task_id,
            "artifacts": [
                {
                    "path": "smuggled.txt",
                    "size": len(b"undeclared bytes\n"),
                    "sha256": hashlib.sha256(b"undeclared bytes\n").hexdigest(),
                }
            ],
        }
        manifest_path.write_text(json.dumps(replacement), encoding="utf-8")
    else:
        manifest_path.write_bytes(published + b" " * (9 * 1024 * 1024))

    response = module.app.test_client().get(f"/compute/api/results/{task_id}", headers=headers)

    assert response.status_code == 404
    assert response.get_json()["status"] == "error"


def test_a_manifest_without_a_declared_digest_is_not_served(monkeypatch, tmp_path) -> None:
    """Identity evidence is required: no declared sha256 means no publication."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id, result_dir, headers = _manifest_task(module, tmp_path)
    (result_dir / "manifest.json").write_text(
        json.dumps({"artifacts": [{"path": "result.txt"}]}), encoding="utf-8"
    )

    artifact = module.app.test_client().get(
        f"/compute/api/results/{task_id}/artifacts/result.txt", headers=headers
    )

    assert artifact.status_code == 404


def test_a_manifest_with_a_malformed_digest_is_not_served(monkeypatch, tmp_path) -> None:
    """A malformed digest is not identity evidence either."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id, result_dir, headers = _manifest_task(module, tmp_path)
    content = (result_dir / "result.txt").read_bytes()
    (result_dir / "manifest.json").write_text(
        json.dumps({"artifacts": [{"path": "result.txt", "sha256": "not-a-digest", "size": len(content)}]}),
        encoding="utf-8",
    )

    artifact = module.app.test_client().get(
        f"/compute/api/results/{task_id}/artifacts/result.txt", headers=headers
    )

    assert artifact.status_code == 404


def test_a_large_artifact_is_streamed_in_bounded_chunks(monkeypatch, tmp_path) -> None:
    """The full-body path reads in chunk-sized reads, never one artifact-sized read."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    payload = b"x" * (200 * 1024)
    task_id, _result_dir, headers = _manifest_task(module, tmp_path, payload)
    client = module.app.test_client()
    observed: list[int] = []

    from revocompute import routes as routes_module
    from revocompute import storage as storage_module

    real_open_verified = storage_module.StorageResolver.open_verified_artifact
    class _SpyStream:
        def __init__(self, stream):
            self._stream = stream

        def __getattr__(self, name):
            return getattr(self._stream, name)

        def read(self, size=-1):
            observed.append(size)
            return self._stream.read(size)

    def spy_open(self, task, relative_path, manifest=None):
        resolved = real_open_verified(self, task, relative_path, manifest)
        if resolved is None:
            return None
        resolved["verified_stream"] = _SpyStream(resolved["verified_stream"])
        return resolved

    monkeypatch.setattr(storage_module.StorageResolver, "open_verified_artifact", spy_open)

    response = client.get(f"/compute/api/results/{task_id}/artifacts/result.txt", headers=headers)

    assert response.status_code == 200
    assert response.data == payload
    assert observed and max(observed) <= routes_module._STREAM_CHUNK_BYTES
    assert len(observed) > 1


def test_suffix_and_unsatisfiable_ranges_are_served_from_the_verified_descriptor(monkeypatch, tmp_path) -> None:
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    content = b"score\n1.0\n"
    task_id, _result_dir, headers = _manifest_task(module, tmp_path, content)
    client = module.app.test_client()
    url = f"/compute/api/results/{task_id}/artifacts/result.txt"

    full = client.get(url, headers=headers)
    suffix = client.get(url, headers={**headers, "Range": "bytes=-4"})
    beyond = client.get(url, headers={**headers, "Range": "bytes=9999-"})
    head = client.head(url, headers=headers)

    assert full.status_code == 200
    assert full.data == content
    assert suffix.status_code == 206
    assert suffix.data == content[-4:]
    assert suffix.headers["Content-Range"] == f"bytes {len(content) - 4}-{len(content) - 1}/{len(content)}"
    assert beyond.status_code == 416
    assert beyond.headers["Content-Range"] == f"bytes */{len(content)}"
    assert head.status_code == 200
    assert head.headers["Content-Length"] == str(len(content))


# ---------------------------------------------------------------------------
# The publication anchor.  A finalized manifest is self-describing, so nothing
# under the runner-writable result root can prove it is the manifest Core
# published.  These cases drive the public surfaces with a manifest replaced by
# another ordinary single-link regular JSON manifest after finalization: the
# replacement is structurally valid and can declare its own sizes and digests,
# and every consumer must still agree that it is not the publication.
# ---------------------------------------------------------------------------


def _replace_manifest(module, result_dir: Path, payload: dict) -> bytes:
    """Substitute the on-disk manifest with valid regular-JSON bytes."""
    body = json.dumps(payload).encode("utf-8")
    manifest_path = result_dir / "manifest.json"
    manifest_path.unlink()
    manifest_path.write_bytes(body)
    return body


def _replacement_declaring(module, task_id: str, result_dir: Path, relative_path: str, payload: bytes) -> dict:
    """A replacement manifest that declares one ordinary file correctly."""
    return {
        "schema_version": 3,
        "task_id": task_id,
        "artifacts": [
            {
                "path": relative_path,
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "media_type": "text/plain",
                "preview": "text",
                "role": "primary",
            }
        ],
        "result": {"files": {}},
    }


def _result_manifest_available(module, task: dict) -> bool:
    """The readiness probe the status and Task-list routes publish.

    Resolved through the registered route rather than by importing a second copy
    of the module: the endpoint reports availability through the same canonical
    reader every other consumer uses, so it is observed the way a client does.
    """
    client = module.app.test_client()
    headers = _test_client_auth(module)
    task_id = str(task["md5sum"])
    body = client.get(f"/compute/api/running/{task_id}", headers=headers).get_json() or {}
    return bool(body.get("result_available"))


def _first_logical_url(module, task_id: str) -> str:
    """The published logical-file URL for the first logical identity with bytes.

    The identity and its index come from the finalized manifest, so the URL is
    one the publication really declares and really resolves -- a declared but
    absent identity would be answered with a not-found by construction.
    """
    manifest = module.app.config["storage_resolver"].load_manifest(module.task_store.get_task(task_id))
    for file_id, entries in manifest["result"]["files"].items():
        if entries:
            return f"/compute/api/results/{task_id}/files/{file_id}?index=0"
    raise AssertionError("the finalized manifest declares no logical file with bytes")


def _anchored_task(module, tmp_path) -> tuple[str, Path, dict[str, str]]:
    """A finalized task that publishes an artifact, an array, and a logical file.

    ``result.txt`` is the ordinary artifact every consumer can address by path,
    ``scores.json`` is a real numeric projection target, and the alignment file
    is what the runner family's declaration publishes as a logical identity, so
    the logical-file surface is exercised on a real declaration rather than a
    guessed file id.
    """
    headers = _test_client_auth(module)
    task_id = _finished_task(module, tmp_path)

    def build(root: Path) -> None:
        (root / "result.txt").write_bytes(b"score\n1.0\n")
        (root / "scores.json").write_text(json.dumps({"plddt": [0.9, 0.8]}), encoding="utf-8")
        (root / "cpu_runner_msa").mkdir()
        (root / "cpu_runner_msa" / "input.i90c75.a3m").write_text(">query\nACDE\n", encoding="utf-8")

    manifest, result_dir = _finalize_dir(module, task_id, build)
    assert manifest["result"]["files"]["alignment"], manifest["result"]["files"]
    return task_id, result_dir, headers


def test_an_unchanged_finalized_manifest_keeps_working_for_every_consumer(monkeypatch, tmp_path) -> None:
    """The anchored manifest is the ordinary case: nothing is refused.

    The same finalized task is read through the canonical reader (the authority
    each consumer delegates to), the status probe, the results route, a
    logical-file URL, the artifact and ndarray projections' resolver, and the
    archive builder — they must all agree that the publication is available.
    """
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id, result_dir, headers = _anchored_task(module, tmp_path)
    task = module.task_store.get_task(task_id)
    storage = module.app.config["storage_resolver"]
    logical_url = _first_logical_url(module, task_id)
    client = module.app.test_client()

    # The canonical reader every consumer delegates to.
    assert storage.load_manifest(task) is not None
    # The readiness probe the Task list and status endpoints publish.
    assert _result_manifest_available(module, task) is True
    # The results manifest route.
    assert client.get(f"/compute/api/results/{task_id}", headers=headers).status_code == 200
    # A logical-file URL resolved through the manifest.
    assert client.get(_first_logical_url(module, task_id), headers=headers).status_code == 200
    # Artifact download, ndarray projection, and archive creation.
    assert client.get(f"/compute/api/results/{task_id}/artifacts/result.txt", headers=headers).status_code == 200
    assert client.get(
        f"/compute/api/results/{task_id}/ndarrays/scores.json?key=plddt&max_elements=2", headers=headers
    ).status_code == 200
    assert storage.resolve_artifact(task, "result.txt") is not None
    assert Path(module.task_runtime._build_results_archive(task)).is_file()
    assert storage.load_manifest(task) is not None


def test_a_valid_regular_manifest_replacement_is_rejected_as_a_publication(monkeypatch, tmp_path) -> None:
    """Replacement by another valid single-link regular JSON manifest fails closed.

    The replacement is a well-formed manifest for a real result tree, so its
    shape proves nothing: the anchored publication identity does, and it is
    resolved from server-owned state the result tree cannot rewrite.
    """
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    content = b"score\n1.0\n"
    task_id, result_dir, headers = _manifest_task(module, tmp_path, content)
    task = module.task_store.get_task(task_id)
    replacement = _replacement_declaring(module, task_id, result_dir, "result.txt", b"replaced\n")
    (result_dir / "result.txt").write_bytes(b"replaced\n")
    _replace_manifest(module, result_dir, replacement)

    assert module.app.config["storage_resolver"].load_manifest(task) is None
    assert _result_manifest_available(module, task) is False
    assert module.app.test_client().get(f"/compute/api/results/{task_id}", headers=headers).status_code == 404
    with pytest.raises(FileNotFoundError):
        module.task_runtime._build_results_archive(task)


def test_a_replacement_cannot_publish_an_undeclared_file_with_correct_size_and_digest(monkeypatch, tmp_path) -> None:
    """Even a perfectly self-consistent replacement cannot publish new bytes.

    The replacement declares ``smuggled.txt`` with that file's true size and
    SHA-256 — the substitution is internally consistent and would pass every
    check the manifest performs on its own declarations.  It is refused because
    the anchor, not the substituted manifest, is the publication authority, and
    the smuggled file was never declared by what Core published.
    """
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id, result_dir, headers = _manifest_task(module, tmp_path, b"score\n1.0\n")
    task = module.task_store.get_task(task_id)
    smuggled = b"undeclared payload\n"
    (result_dir / "smuggled.txt").write_bytes(smuggled)
    replacement = _replacement_declaring(module, task_id, result_dir, "smuggled.txt", smuggled)
    declared = replacement["artifacts"][0]
    # The replacement is self-consistent: it declares the true size and digest.
    assert declared["size"] == (result_dir / "smuggled.txt").stat().st_size
    assert declared["sha256"] == hashlib.sha256(smuggled).hexdigest()
    _replace_manifest(module, result_dir, replacement)

    client = module.app.test_client()
    assert client.get(f"/compute/api/results/{task_id}/artifacts/smuggled.txt", headers=headers).status_code == 404
    assert client.get(f"/compute/api/results/{task_id}/files/smuggled?index=0", headers=headers).status_code == 404
    body = client.get(f"/compute/api/results/{task_id}", headers=headers)
    assert body.status_code == 404
    assert b"smuggled" not in body.data


def test_every_publication_consumer_agrees_on_the_anchored_authority(monkeypatch, tmp_path) -> None:
    """The archive, Tool materialization, the projections, and the probe agree.

    A manifest replaced after finalization must be refused by *all* of them; a
    consumer that read the pathname instead of the anchored authority would
    disagree, which is the failure this asserts against.
    """
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id, result_dir, headers = _anchored_task(module, tmp_path)
    task = module.task_store.get_task(task_id)
    storage = module.app.config["storage_resolver"]
    logical_url = _first_logical_url(module, task_id)
    _replace_manifest(
        module, result_dir, _replacement_declaring(module, task_id, result_dir, "result.txt", b"score\n1.0\n")
    )

    client = module.app.test_client()
    verdicts = {
        "canonical_reader": storage.load_manifest(task) is not None,
        "artifact_download": client.get(
            f"/compute/api/results/{task_id}/artifacts/result.txt", headers=headers
        ).status_code
        == 200,
        "ndarray_projection": client.get(
            f"/compute/api/results/{task_id}/ndarrays/result.txt", headers=headers
        ).status_code
        == 200,
        "logical_file": client.get(logical_url, headers=headers).status_code == 200,
        "result_available": _result_manifest_available(module, task),
    }
    assert verdicts == {
        "canonical_reader": False,
        "artifact_download": False,
        "ndarray_projection": False,
        "logical_file": False,
        "result_available": False,
    }
    # Archive creation and Tool materialization consume the same authority: a
    # Task artifact reference resolves through the archived manifest, and the
    # unanchored replacement makes that reference unavailable.  The Tool path is
    # observed through the call route's own fail-closed answer for an
    # unavailable source Task, which is where that decision is made.
    with pytest.raises(FileNotFoundError):
        module.task_runtime._build_results_archive(task)
    assert storage.resolve_artifact(task, "result.txt") is None
    assert _source_task_artifact_is_unavailable(module, task_id, "result.txt")


def _source_task_artifact_is_unavailable(module, task_id: str, relative_path: str) -> bool:
    """Whether the Tool call route refuses an artifact from that source Task.

    The route resolves the reference through the publication authority before it
    materializes anything, so an unanchored manifest makes the reference
    unavailable and the call is refused rather than queued.
    """
    headers = _test_client_auth(module, "tester")
    response = module.app.test_client().post(
        "/compute/api/tools/fasta_inspect/call",
        headers=headers,
        data={
            "parameters": "{}",
            "artifact_references": f"@{task_id}/{relative_path}",
            "artifact_roles": "sequence",
        },
    )
    return response.status_code in {400, 403, 404, 409}


def test_the_existing_link_and_size_refusals_stay_closed_under_the_anchor(monkeypatch, tmp_path) -> None:
    """The anchor adds a check; it does not replace the descriptor contract.

    Symlink, hard link, oversized, and escaping-path cases are refused for their
    own reasons, and the anchored reader keeps refusing them.
    """
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    content = b"score\n1.0\n"
    task_id, result_dir, headers = _manifest_task(module, tmp_path, content)
    task = module.task_store.get_task(task_id)
    manifest_path = result_dir / "manifest.json"
    published = manifest_path.read_bytes()
    outside = tmp_path / "outside-manifest.json"
    storage = module.app.config["storage_resolver"]

    outside.write_bytes(published)
    manifest_path.unlink()
    manifest_path.symlink_to(outside)
    assert storage.load_manifest(task) is None

    manifest_path.unlink()
    outside.write_bytes(published)
    manifest_path.hardlink_to(outside)
    assert storage.load_manifest(task) is None

    manifest_path.unlink()
    manifest_path.write_bytes(published + b" " * (9 * 1024 * 1024))
    assert storage.load_manifest(task) is None

    # A manifest entry naming bytes outside the published root is never resolved,
    # anchor or not: path containment is checked before the declaration is used.
    manifest_path.unlink()
    manifest_path.write_bytes(published)
    assert storage.resolve_declared_artifact(task, "../outside.txt") is None
    assert storage.resolve_declared_artifact(task, "/etc/passwd") is None
    # The restored, still-anchored manifest is served again: the refusals above
    # were about the tampering, not about the anchor being permanent.
    restored = module.app.test_client().get(f"/compute/api/results/{task_id}", headers=headers)
    assert restored.status_code == 200


# ---------------------------------------------------------------------------
# The publication walk is descriptor-relative, so an adversarial result tree
# cannot redirect it with a name.  Every case below mutates the tree *between*
# enumeration and open, driven by a barrier rather than a sleep: the walk is
# paused inside ``os.stat``, the tree is rewritten, and the walk resumes.
# ---------------------------------------------------------------------------


class _SwapOnBarrier:
    """Run *swap* once, the first time ``stat`` is called on a given name.

    Holding the real ``stat`` open until the swap has landed is what makes the
    race deterministic: there is no window to lose, so a walk that trusted a
    pathname would fail this while a descriptor-relative one cannot.
    """

    def __init__(self, module, monkeypatch, swap, trigger: str):
        self._swap = swap
        self._trigger = trigger
        self._done = False
        self.fired = False
        real = os.stat

        def barrier(path, *args, **kwargs):
            if not self._done and os.path.basename(str(path)) == trigger:
                self._done = True
                self.fired = True
                swap()
            return real(path, *args, **kwargs)

        monkeypatch.setattr(module.task_runtime.os, "stat", barrier)


def _fail_anchor(module, monkeypatch, *, error=OSError("database is locked")) -> None:
    """Make the publication anchor transition fail, as a locked store would."""

    def _raise(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(module.task_store, "record_result_publication", _raise)


def test_an_intermediate_directory_swapped_for_a_symlink_is_not_followed(monkeypatch, tmp_path) -> None:
    """The classic TOCTOU: the directory is a real one at enumeration, a link at open.

    ``publish/`` is a directory when the walk enumerates it and a symlink to the
    runner's own home by the time its entry is stat-ed.  Publication must not
    follow it: what reaches the manifest is a name that can only be resolved
    inside the result tree, and the planted bytes never become a published
    artifact.
    """
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id = _finished_task(module, tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("host secret\n", encoding="utf-8")
    result_dir = Path(module.app.config["storage_resolver"].get_task_root(module.task_store.get_task(task_id)))

    def build(root: Path) -> None:
        (root / "publish").mkdir()
        (root / "publish" / "secret.txt").write_text("intended\n", encoding="utf-8")

    task = module.task_store.get_task(task_id)
    build(result_dir)

    def swap() -> None:
        shutil.rmtree(result_dir / "publish")
        (result_dir / "publish").symlink_to(outside, target_is_directory=True)

    barrier = _SwapOnBarrier(module, monkeypatch, swap, "secret.txt")
    manifest = module.task_runtime._finalize_results_manifest(
        task, execution_state="completed", finished_at=1_700_000_000
    )
    assert barrier.fired, "the race was not exercised"

    published = {artifact["path"]: artifact for artifact in manifest["artifacts"]}
    assert "publish/secret.txt" not in published
    # And what the manifest does declare resolves to the same bytes it hashed:
    # the walk's names are the reader's names.
    storage = module.app.config["storage_resolver"]
    for relative_path in published:
        resolved = storage.resolve_artifact(task, relative_path)
        assert resolved is not None, relative_path
        resolved["verified_stream"].close()


def test_a_component_swapped_between_enumeration_and_open_is_refused(monkeypatch, tmp_path) -> None:
    """A regular file replaced by a symlink mid-walk is not hashed through the link."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id = _finished_task(module, tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("host bytes\n", encoding="utf-8")
    result_dir = Path(module.app.config["storage_resolver"].get_task_root(module.task_store.get_task(task_id)))

    (result_dir / "target.txt").write_text("intended bytes\n", encoding="utf-8")

    def swap() -> None:
        (result_dir / "target.txt").unlink()
        (result_dir / "target.txt").symlink_to(outside)

    barrier = _SwapOnBarrier(module, monkeypatch, swap, "target.txt")
    manifest = module.task_runtime._finalize_results_manifest(
        module.task_store.get_task(task_id), execution_state="completed", finished_at=1_700_000_000
    )
    assert barrier.fired, "the race was not exercised"

    assert "target.txt" not in {artifact["path"] for artifact in manifest["artifacts"]}
    assert manifest["output_check"]["state"] == "failed"


def test_intermediate_component_traversal_is_refused(monkeypatch, tmp_path) -> None:
    """A ``..`` component is refused by the one path vocabulary both sides share."""
    from revocompute.storage import manifest_relative_parts

    assert manifest_relative_parts("../outside.txt") is None
    assert manifest_relative_parts("a/../../b") is None
    assert manifest_relative_parts("/etc/passwd") is None
    assert manifest_relative_parts("") is None
    assert manifest_relative_parts("a//b") is None
    assert manifest_relative_parts("a\\b") is None
    assert manifest_relative_parts("a/\x01b") is None
    assert manifest_relative_parts("x" * 256 + "/f.txt") is None
    assert manifest_relative_parts("dir/model.pdb") == ("dir", "model.pdb")

    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id, result_dir, headers = _manifest_task(module, tmp_path)
    task = module.task_store.get_task(task_id)
    storage = module.app.config["storage_resolver"]
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"outside bytes\n")
    # A manifest entry naming bytes outside the published root is never resolved.
    for probe in ("../outside.txt", "a/../../outside.txt", "/etc/passwd"):
        assert storage.resolve_declared_artifact(task, probe) is None
    assert module.app.test_client().get(
        f"/compute/api/results/{task_id}/artifacts/..%2Foutside.txt", headers=headers
    ).status_code == 404


def test_a_real_subdirectory_is_published_and_resolvable(monkeypatch, tmp_path) -> None:
    """The descriptor walk keeps the ordinary nested case working end to end."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id = _finished_task(module, tmp_path)
    content = b"score\n1.0\n"

    def build(root: Path) -> None:
        (root / "nested" / "deeper").mkdir(parents=True)
        (root / "nested" / "deeper" / "result.txt").write_bytes(content)

    manifest, result_dir = _finalize_dir(module, task_id, build)
    published = {artifact["path"] for artifact in manifest["artifacts"]}
    assert "nested/deeper/result.txt" in published

    task = module.task_store.get_task(task_id)
    resolved = module.app.config["storage_resolver"].resolve_artifact(task, "nested/deeper/result.txt")
    assert resolved is not None
    with resolved["verified_stream"] as stream:
        assert stream.read() == content


def test_an_anchored_manifest_over_the_byte_limit_is_never_written(monkeypatch, tmp_path) -> None:
    """The writer and the reader share one ceiling, so neither can produce a dead publication.

    An ordinary result set whose manifest would not fit the canonical byte limit
    is refused as a capacity guard: the Task must not be finished with a manifest
    its own reader classifies as unreadable.
    """
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    from revocompute import storage as storage_module

    monkeypatch.setattr(storage_module, "MANIFEST_MAX_BYTES", 4096)
    monkeypatch.setattr(module.task_runtime.storage_module, "MANIFEST_MAX_BYTES", 4096)
    task_id = _finished_task(module, tmp_path)

    def build(root: Path) -> None:
        for index in range(200):
            (root / f"result_{index:03d}.txt").write_text("v\n", encoding="utf-8")

    manifest, result_dir = _finalize_dir(module, task_id, build)

    raw = (result_dir / "manifest.json").read_bytes()
    assert len(raw) <= 4096
    assert manifest["artifacts"] == []
    assert manifest["output_check"]["state"] == "failed"
    assert any("manifest limit" in problem for problem in manifest["output_check"]["problems"])
    # And the canonical reader accepts exactly what the writer anchored.
    task = module.task_store.get_task(task_id)
    storage = module.app.config["storage_resolver"]
    assert storage.load_manifest(task) is not None


def test_a_manifest_just_below_the_ceiling_publishes_normally(monkeypatch, tmp_path) -> None:
    """The boundary is a ceiling, not a target: an admitted manifest publishes.

    A ceiling the serialized manifest cannot fit is refused as a capacity guard
    -- the writer never anchors a manifest its own reader must reject -- and a
    ceiling that admits the same rows publishes them unchanged.
    """
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    from revocompute import storage as storage_module

    task_id = _finished_task(module, tmp_path)
    result_dir = Path(module.app.config["storage_resolver"].get_task_root(module.task_store.get_task(task_id)))
    for index in range(200):
        (result_dir / f"result_{index:03d}.txt").write_text("value\n", encoding="utf-8")

    # A ceiling the full serialized manifest does not fit but the bounded
    # skeleton does: the writer refuses to anchor a manifest its own reader must
    # reject, and says so as a capacity guard rather than anchoring a dead
    # publication.
    monkeypatch.setattr(storage_module, "MANIFEST_MAX_BYTES", 8192)
    monkeypatch.setattr(module.task_runtime.storage_module, "MANIFEST_MAX_BYTES", 8192)
    guard = module.task_runtime._finalize_results_manifest(
        module.task_store.get_task(task_id), execution_state="completed", finished_at=1_700_000_000
    )
    assert guard["artifacts"] == []
    assert guard["total_size"] == 0
    assert any("manifest limit" in problem for problem in guard["output_check"]["problems"])
    assert guard.get("outcome") is None and guard.get("work_items") is None
    assert len((result_dir / "manifest.json").read_bytes()) <= 8192
    assert module.app.config["storage_resolver"].load_manifest(module.task_store.get_task(task_id)) is not None

    # Every over-limit row is excluded from the published namespace, so what the
    # canonical reader resolves is exactly what the writer declared: nothing.
    task = module.task_store.get_task(task_id)
    assert module.app.config["storage_resolver"].resolve_artifact(task, "result_000.txt") is None

    # Re-publish under a ceiling comfortably above the manifest's own size: the
    # same rows publish normally and the anchored bytes are readable.
    monkeypatch.setattr(storage_module, "MANIFEST_MAX_BYTES", 1048576)
    monkeypatch.setattr(module.task_runtime.storage_module, "MANIFEST_MAX_BYTES", 1048576)
    manifest_again = module.task_runtime._finalize_results_manifest(
        module.task_store.get_task(task_id), execution_state="completed", finished_at=1_700_000_001
    )
    assert len(manifest_again["artifacts"]) == 200
    assert len((result_dir / "manifest.json").read_bytes()) <= 1048576
    assert module.app.config["storage_resolver"].load_manifest(module.task_store.get_task(task_id)) is not None


def test_the_writer_anchors_exactly_at_the_reader_ceiling_and_not_above(monkeypatch, tmp_path) -> None:
    """The manifest byte ceiling is one contract, on the byte.

    The published manifest is re-published twice with the ceiling moved to the
    exact serialized size the canonical reader already accepted and then one byte
    below it.  At the limit the result is publishable and the reader accepts it;
    one byte lower the writer refuses to anchor rather than emitting a manifest
    its own reader must classify as unreadable.
    """
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    from revocompute import storage as storage_module

    task_id = _finished_task(module, tmp_path)
    result_dir = Path(module.app.config["storage_resolver"].get_task_root(module.task_store.get_task(task_id)))
    for index in range(12):
        (result_dir / f"result_{index:03d}.txt").write_text("value\n", encoding="utf-8")
    module.task_runtime._finalize_results_manifest(
        module.task_store.get_task(task_id), execution_state="completed", finished_at=1_700_000_000
    )
    exact = len((result_dir / "manifest.json").read_bytes())
    storage = module.app.config["storage_resolver"]
    task = module.task_store.get_task(task_id)
    assert len(storage.load_manifest(task)["artifacts"]) == 12

    # Exactly at the ceiling the same result set is published and readable.
    monkeypatch.setattr(storage_module, "MANIFEST_MAX_BYTES", exact)
    at_limit = module.task_runtime._finalize_results_manifest(
        task, execution_state="completed", finished_at=1_700_000_001
    )
    assert len(at_limit["artifacts"]) == 12
    assert len((result_dir / "manifest.json").read_bytes()) == exact
    assert len(storage.load_manifest(module.task_store.get_task(task_id))["artifacts"]) == 12

    # One byte below, the writer refuses to anchor the very same result set.
    monkeypatch.setattr(storage_module, "MANIFEST_MAX_BYTES", exact - 1)
    guard = module.task_runtime._finalize_results_manifest(
        module.task_store.get_task(task_id), execution_state="completed", finished_at=1_700_000_002
    )
    assert guard["artifacts"] == []
    assert any("manifest limit" in problem for problem in guard["output_check"]["problems"])
    assert len((result_dir / "manifest.json").read_bytes()) <= exact - 1
    # The refused publication is still a publication the reader can read: the
    # guard skeleton is anchored, not a manifest no consumer can open.
    refused = storage.load_manifest(module.task_store.get_task(task_id))
    assert refused is not None and refused["artifacts"] == []
    assert storage.resolve_artifact(task, "result_000.txt") is None


def test_an_over_capacity_artifact_is_refused_without_reading_its_bytes(monkeypatch, tmp_path) -> None:
    """Capacity is enforced from the verified size, so the bytes are never read.

    The probe counts the reads the publication actually performs on the
    over-capacity file: a reader that hashed first and compared afterwards would
    show the whole 4 MiB here.
    """
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id = _finished_task(module, tmp_path)
    monkeypatch.setattr(module.task_runtime, "_published_byte_limit", lambda: 8)
    result_dir = Path(module.app.config["storage_resolver"].get_task_root(module.task_store.get_task(task_id)))
    target = result_dir / "huge.bin"
    target.write_bytes(b"x" * (4 * 1024 * 1024))
    hashed: list[int] = []

    import revocompute.storage as storage_module

    real_hash = storage_module._hash_bounded

    def counting_hash(handle, limit):
        # The bounded hasher is the only reader of an artifact's bytes during
        # publication, so counting what it is asked to read counts the work.
        hashed.append(limit)
        return real_hash(handle, limit)

    monkeypatch.setattr(storage_module, "_hash_bounded", counting_hash)

    manifest = module.task_runtime._finalize_results_manifest(
        module.task_store.get_task(task_id), execution_state="completed", finished_at=1_700_000_000
    )

    assert manifest["artifacts"] == []
    assert any("capacity limit" in problem for problem in manifest["output_check"]["problems"])
    # Nothing was hashed at all: the verified size was already over the budget,
    # so the bounded hasher was never entered for this file.
    assert hashed == []
    assert target.stat().st_size == 4 * 1024 * 1024


def test_a_fifo_where_the_manifest_belongs_cannot_block_the_reader(monkeypatch, tmp_path) -> None:
    """A hostile entry type is refused from its descriptor, never waited on.

    A FIFO opened for reading would block forever, so ``publication_state``,
    ``load_manifest``, and the download would each hang a shared worker while a
    runner-owned task simply never writes to the pipe.  The one walker opens
    non-blocking and refuses anything that is not a private regular file.
    """
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id, result_dir, headers = _manifest_task(module, tmp_path)
    manifest_path = result_dir / "manifest.json"
    manifest_path.unlink()
    os.mkfifo(manifest_path)
    task = module.task_store.get_task(task_id)
    storage = module.app.config["storage_resolver"]
    client = module.app.test_client()

    # Every reader answers, and none of them can be blocked by the pipe.
    assert storage.publication_state(task) == "manifest_unreadable"
    assert storage.load_manifest(task) is None
    assert storage.resolve_artifact(task, "result.txt") is None
    assert client.get(f"/compute/api/results/{task_id}", headers=headers).status_code == 404
    assert client.get(f"/compute/api/results/{task_id}/artifacts/result.txt", headers=headers).status_code == 404


def test_a_fifo_where_an_artifact_belongs_is_refused_not_opened(monkeypatch, tmp_path) -> None:
    """A declared artifact replaced by a FIFO is refused, not opened and waited on."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id, result_dir, _manifest = _single_artifact_task(module, tmp_path, b"score\n1.0\n")
    artifact = result_dir / "result.txt"
    artifact.unlink()
    os.mkfifo(artifact)
    task = module.task_store.get_task(task_id)

    assert module.app.config["storage_resolver"].resolve_artifact(task, "result.txt") is None
    with pytest.raises(FileNotFoundError):
        module.task_runtime._build_results_archive(task)


def test_a_journaled_entry_is_never_hung_on_by_the_walk(monkeypatch, tmp_path) -> None:
    """The publication walk refuses a journal-owned FIFO instead of blocking on it."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id = _finished_task(module, tmp_path)
    result_dir = Path(module.app.config["storage_resolver"].get_task_root(module.task_store.get_task(task_id)))
    (result_dir / "real.txt").write_text("real\n", encoding="utf-8")
    os.mkfifo(result_dir / "journal.fifo")

    manifest = module.task_runtime._finalize_results_manifest(
        module.task_store.get_task(task_id), execution_state="completed", finished_at=1_700_000_000
    )

    published = {artifact["path"] for artifact in manifest["artifacts"]}
    assert "real.txt" in published
    assert "journal.fifo" not in published
    assert any("journal.fifo" in problem for problem in manifest["output_check"]["problems"])


def test_a_flagged_published_file_cannot_be_extended_after_verification(monkeypatch, tmp_path) -> None:
    """Bytes appended after identity verification do not reach the caller.

    The published artifact contract is a length: the descriptor a consumer reads
    is the one whose size and digest were checked, so bytes appended to the same
    inode afterwards -- which keep the inode, the link count, and the manifest
    entry's declared prefix -- must not be served.
    """
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    headers = _test_client_auth(module)
    content = b"score\n1.0\n"
    task_id, result_dir, _manifest = _single_artifact_task(module, tmp_path, content)
    artifact = result_dir / "result.txt"
    resolver = module.app.config["storage_resolver"]
    resolve = resolver.resolve_artifact

    def append_after_verify(task, relative_path):
        resolved = resolve(task, relative_path)
        if resolved is not None:
            # Same inode, same link count: only the length changes, which is
            # exactly what a manifest entry cannot describe.
            with open(artifact, "ab") as handle:
                handle.write(b"UNVERIFIED-APPENDED-BYTES\n")
        return resolved

    monkeypatch.setattr(resolver, "resolve_artifact", append_after_verify)

    response = module.app.test_client().get(
        f"/compute/api/results/{task_id}/artifacts/result.txt", headers=headers
    )

    assert b"UNVERIFIED" not in response.data


def test_an_artifact_that_grows_while_being_hashed_is_refused(monkeypatch, tmp_path) -> None:
    """A file that grows under the reader is rejected, never hashed to its new size."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id = _finished_task(module, tmp_path)
    result_dir = Path(module.app.config["storage_resolver"].get_task_root(module.task_store.get_task(task_id)))
    target = result_dir / "growing.bin"
    target.write_bytes(b"a" * 512)
    real_open = os.open
    grew = False

    def growing_open(path, *args, **kwargs):
        nonlocal grew
        fd = real_open(path, *args, **kwargs)
        if os.path.basename(str(path)) == "growing.bin" and not grew:
            grew = True
            # Grow the file through the descriptor the reader is about to hash,
            # so the size it reported and the bytes it can read disagree.
            os.write(fd, b"b" * 4096)
            os.lseek(fd, 0, os.SEEK_SET)
        return fd

    monkeypatch.setattr(module.task_runtime.os, "open", growing_open)
    manifest = module.task_runtime._finalize_results_manifest(
        module.task_store.get_task(task_id), execution_state="completed", finished_at=1_700_000_000
    )
    assert grew
    assert "growing.bin" not in {artifact["path"] for artifact in manifest["artifacts"]}
    assert manifest["output_check"]["state"] == "failed"


def test_an_artifact_truncated_while_being_hashed_is_refused(monkeypatch, tmp_path) -> None:
    """A file truncated under the reader is rejected rather than digested short."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id = _finished_task(module, tmp_path)
    result_dir = Path(module.app.config["storage_resolver"].get_task_root(module.task_store.get_task(task_id)))
    target = result_dir / "truncating.bin"
    target.write_bytes(b"a" * 4096)
    real_open = os.open
    truncated = False

    def truncating_open(path, *args, **kwargs):
        nonlocal truncated
        fd = real_open(path, *args, **kwargs)
        if os.path.basename(str(path)) == "truncating.bin" and not truncated:
            truncated = True
            os.ftruncate(fd, 0)
            os.lseek(fd, 0, os.SEEK_SET)
        return fd

    monkeypatch.setattr(module.task_runtime.os, "open", truncating_open)
    manifest = module.task_runtime._finalize_results_manifest(
        module.task_store.get_task(task_id), execution_state="completed", finished_at=1_700_000_000
    )
    assert truncated
    assert "truncating.bin" not in {artifact["path"] for artifact in manifest["artifacts"]}


def test_an_artifact_replaced_by_a_hardlink_while_being_hashed_is_refused(monkeypatch, tmp_path) -> None:
    """A second link appearing mid-hash means the bytes are not privately owned."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id = _finished_task(module, tmp_path)
    result_dir = Path(module.app.config["storage_resolver"].get_task_root(module.task_store.get_task(task_id)))
    target = result_dir / "linked.bin"
    target.write_bytes(b"a" * 4096)
    outside = tmp_path / "outside.bin"
    real_open = os.open
    linked = False

    def linking_open(path, *args, **kwargs):
        nonlocal linked
        fd = real_open(path, *args, **kwargs)
        if os.path.basename(str(path)) == "linked.bin" and not linked:
            linked = True
            os.link(target, outside)
        return fd

    monkeypatch.setattr(module.task_runtime.os, "open", linking_open)
    manifest = module.task_runtime._finalize_results_manifest(
        module.task_store.get_task(task_id), execution_state="completed", finished_at=1_700_000_000
    )
    assert linked
    assert "linked.bin" not in {artifact["path"] for artifact in manifest["artifacts"]}
    assert manifest["output_check"]["state"] == "failed"


def test_no_publication_consumer_reopens_a_resolved_name(monkeypatch, tmp_path) -> None:
    """A consumer reads the verified descriptor, never the artifact's name again.

    The file is replaced immediately after resolution, so a consumer that
    resolved the name a second time -- or reopened the resolved path -- would
    serve the replacement bytes instead of the ones the manifest authorized.
    """
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    headers = _test_client_auth(module)
    content = b"score\n1.0\n"
    task_id, result_dir, _manifest = _single_artifact_task(module, tmp_path, content)
    artifact = result_dir / "result.txt"
    resolver = module.app.config["storage_resolver"]
    resolve = resolver.resolve_artifact
    replaced: list[int] = []

    def replace_after_verify(task, relative_path):
        resolved = resolve(task, relative_path)
        if resolved is not None and not replaced:
            # Replace after the *first* consumer has resolved, so the second
            # resolution in the same request -- the one a name-based reader would
            # make -- sees different bytes.
            replaced.append(1)
            swapped = artifact.with_suffix(".swapped")
            swapped.write_bytes(b"substituted bytes\n")
            os.replace(swapped, artifact)
        return resolved

    monkeypatch.setattr(resolver, "resolve_artifact", replace_after_verify)
    client = module.app.test_client()

    response = client.get(f"/compute/api/results/{task_id}/artifacts/result.txt", headers=headers)
    assert replaced, "the substitution was never exercised"
    assert response.status_code == 200
    assert response.data == content
    assert b"substituted" not in response.data


def test_the_archive_refuses_a_quarantined_publication(monkeypatch, tmp_path) -> None:
    """A quarantined publication cannot be packed, and the reason is reported."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    headers = _test_client_auth(module)
    content = b"score\n1.0\n"
    task_id, result_dir, _manifest = _single_artifact_task(module, tmp_path, content)
    _replace_manifest(
        module, result_dir, _replacement_declaring(module, task_id, result_dir, "result.txt", content)
    )
    task = module.task_store.get_task(task_id)
    assert module.app.config["storage_resolver"].publication_state(task) == "anchor_mismatch"
    client = module.app.test_client()

    post = client.post(f"/compute/api/results/{task_id}/archive", headers=headers)
    download = client.get(f"/compute/api/download/{task_id}", headers=headers)
    with pytest.raises(FileNotFoundError):
        module.task_runtime._build_results_archive(task)

    assert post.status_code == 409
    assert post.get_json()["result_publication"] == "anchor_mismatch"
    assert download.status_code == 409
    assert download.get_json()["result_publication"] == "anchor_mismatch"


def test_a_retry_after_a_failed_publication_leaves_no_false_published_state(monkeypatch, tmp_path) -> None:
    """A refused publication never leaves a manifest.published claim behind."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id = _finished_task(module, tmp_path)
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(module.task_runtime, "emit_event", lambda event, **fields: events.append((event, fields)))
    _fail_anchor(module, monkeypatch, error=OSError("database is locked"))

    def build(root: Path) -> None:
        (root / "result.txt").write_text("score\n", encoding="utf-8")

    task = module.task_store.get_task(task_id)
    result_dir = Path(module.app.config["storage_resolver"].get_task_root(task))
    build(result_dir)

    with pytest.raises(ResultPublicationError):
        module.task_runtime._finalize_results_manifest(task, execution_state="completed", finished_at=1_700_000_000)

    assert [event for event, _ in events if event == "manifest.published"] == []
    assert not (result_dir / "manifest.json").exists()
    assert module.task_store.get_result_publication(task_id) is None
    assert module.app.config["storage_resolver"].publication_state(
        module.task_store.get_task(task_id)
    ) == "not_finalized"

    # The retry publishes through the ordinary transition and is then the
    # authority every consumer agrees on.
    monkeypatch.undo()
    manifest = module.task_runtime._finalize_results_manifest(
        task, execution_state="completed", finished_at=1_700_000_001
    )
    assert "result.txt" in {artifact["path"] for artifact in manifest["artifacts"]}
    assert (
        module.app.config["storage_resolver"].publication_state(module.task_store.get_task(task_id)) == "available"
    )
