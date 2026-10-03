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
import json
from pathlib import Path
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



def test_declared_roles_map_glob_selectors_onto_published_paths() -> None:
    roles = declared_file_roles(
        {
            "structures": {"pattern": "ranked/rank_*.cif", "cardinality": "many", "required": True, "role": "artifact"},
            "metadata": {"path": "run_metadata.json", "cardinality": "one", "required": True},
        },
        ["ranked/rank_0.cif", "ranked/rank_1.cif", "run_metadata.json"],
    )
    assert roles == {"ranked/rank_0.cif": "artifact", "ranked/rank_1.cif": "artifact"}


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


def _type_with(view: tuple[str, str, str]):
    view_id, role, path = view
    return type("TaskType", (), {"result_workspace": (replace(_role_view(role, path), id=view_id),)})()
