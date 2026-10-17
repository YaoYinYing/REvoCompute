# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from revocompute import result_storyboard
from revocompute.result_storyboard import (
    ResultContractError,
    contract_dir,
    contract_directory,
    declared_result_contracts,
    expected_file_tree,
    resolve_expected_files,
    runner_root,
    storyboard_asset_root,
    storyboard_declaration,
)

ROOT = Path(__file__).resolve().parents[1]


def test_expected_file_tree_resolves_logical_files_without_paths() -> None:
    files, checks, problems = resolve_expected_files(
        {
            "models": {"pattern": "models/*.cif", "required": True, "cardinality": "many", "type": "structure"},
            "scores": {"path": "scores.csv", "required": False, "cardinality": "one"},
        },
        [
            {"path": "models/a.cif", "size": 1},
            {"path": "models/b.cif", "size": 1},
            {"path": "scores.csv", "size": 0},
        ],
    )
    assert [item["path"] for item in files["models"]] == ["models/a.cif", "models/b.cif"]
    assert {item["cardinality"] for item in files["models"]} == {"many"}
    assert {item["logical_type"] for item in files["models"]} == {"structure"}
    assert files["scores"] == []
    assert [item["status"] for item in checks] == ["passed", "passed"]
    assert problems == []


def test_runner_root_honors_isolated_runner_mount(monkeypatch, tmp_path) -> None:
    runners = tmp_path / "candidate-runners"
    family = runners / "profile_runner"
    family.mkdir(parents=True)
    monkeypatch.setenv("RUNNERS_DIR", str(runners))

    runtime = type("Runtime", (), {"root": str(family), "definition": "profile_runner.def"})()
    task_type = type("TaskType", (), {"runtime": runtime})()

    assert runner_root(task_type, str(tmp_path / "isolated-server")) == family.resolve()


def test_expected_file_tree_rejects_logical_ids_outside_route_grammar(monkeypatch, tmp_path) -> None:
    runner = tmp_path / "runner"
    runner.mkdir()
    (runner / "expected_files.yaml").write_text(
        "result:\n"
        "  files:\n"
        "    result_naive:\n"
        "      path: output.txt\n"
        "      required: false\n"
        "    result-naive:\n"
        "      path: output.txt\n"
        "      required: false\n"
        "    resulté:\n"
        "      path: output.txt\n"
        "      required: false\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(result_storyboard, "runner_root", lambda _task_type, _server_dir: runner)

    with pytest.raises(ResultContractError, match="Invalid logical result file"):
        expected_file_tree(object(), "")


# ── Task-scoped contract resolution ──────────────────────────────────────────
#
# The family below mirrors the shape that forced the split: one runtime family
# hosting a fold Task and a design Task whose published file names cannot be
# described by one tree. Nothing here names a real TaskType; the resolver is
# exercised through positions, which is the whole point of the rule.

_TREE = "result:\n  files:\n    outputs:\n      pattern: '{pattern}'\n      required: true\n      type: structure\n"
_STORYBOARD = (
    "identifier: synthetic-{name}\n"
    "entrypoint: ./index.js\n"
    "requires: [outputs]\n"
    "optional: []\n"
)


def _family(tmp_path: Path, monkeypatch) -> Path:
    """A family with a family-scoped tree and two Task directories.

    ``tasks/fold`` ships no contract of its own (family-scoped); ``tasks/design``
    ships both its own tree and its own Storyboard. ``RUNNERS_DIR`` points at the
    synthetic runner root so the resolver validates these candidates exactly as
    it validates a deployment's, rather than reading the shipped fleet.
    """
    runners = tmp_path / "runners"
    monkeypatch.setenv("RUNNERS_DIR", str(runners))
    family = runners / "synthetic"
    (family / "tasks" / "fold").mkdir(parents=True)
    (family / "tasks" / "design" / "storyboard").mkdir(parents=True)
    (family / "expected_files.yaml").write_text(_TREE.format(pattern="*.cif"), encoding="utf-8")
    (family / "storyboard").mkdir()
    (family / "storyboard" / "index.js").write_text("export default {};\n", encoding="utf-8")
    (family / "storyboard" / "storyboard.yaml").write_text(_STORYBOARD.format(name="fold"), encoding="utf-8")
    (family / "tasks" / "fold" / "task.yaml").write_text("id: synthetic_fold\n", encoding="utf-8")
    (family / "tasks" / "design" / "task.yaml").write_text("id: synthetic_design\n", encoding="utf-8")
    (family / "tasks" / "design" / "expected_files.yaml").write_text(
        _TREE.format(pattern="*.cif.gz"), encoding="utf-8"
    )
    (family / "tasks" / "design" / "storyboard" / "index.js").write_text("export default {};\n", encoding="utf-8")
    (family / "tasks" / "design" / "storyboard" / "storyboard.yaml").write_text(
        _STORYBOARD.format(name="design"), encoding="utf-8"
    )
    return family


def _drop_task_contract(family: Path) -> None:
    """Remove one Task's own contract, leaving the family-scoped one in place."""
    task = family / "tasks" / "design"
    (task / "expected_files.yaml").unlink()
    for child in (task / "storyboard").iterdir():
        child.unlink()
    (task / "storyboard").rmdir()


def _task(family: Path, task_dir: str):
    runtime = type("Runtime", (), {"root": str(family), "definition": "synthetic.def"})()
    return type("TaskType", (), {"runtime": runtime, "task_dir": task_dir})()


def test_a_task_contract_is_resolved_from_the_directory_beside_its_manifest(tmp_path, monkeypatch) -> None:
    family = _family(tmp_path, monkeypatch)
    fold, design = _task(family, "tasks/fold"), _task(family, "tasks/design")

    assert expected_file_tree(fold, "")["outputs"]["pattern"] == "*.cif"
    assert expected_file_tree(design, "")["outputs"]["pattern"] == "*.cif.gz"
    # ... and each Task's Storyboard comes from the same directory as its tree:
    # no Task can take its logical files from one place and its module from another.
    assert storyboard_declaration(fold, "", {"outputs"})["identifier"] == "synthetic-fold"
    assert storyboard_declaration(design, "", {"outputs"})["identifier"] == "synthetic-design"
    assert storyboard_asset_root(fold, "") == (family / "storyboard").resolve()
    assert storyboard_asset_root(design, "") == (family / "tasks" / "design" / "storyboard").resolve()


def test_a_task_without_its_own_tree_keeps_the_family_contract_unchanged(tmp_path, monkeypatch) -> None:
    """The migration is additive: an existing family-scoped family is untouched."""
    family = _family(tmp_path, monkeypatch)
    _drop_task_contract(family)

    for task_dir in ("", "tasks/fold", "tasks/design"):
        task = _task(family, task_dir)
        assert expected_file_tree(task, "")["outputs"]["pattern"] == "*.cif"
        assert storyboard_declaration(task, "", {"outputs"})["identifier"] == "synthetic-fold"


@pytest.mark.parametrize("task_dir", ["../escape", "tasks/../../escape", "/absolute", "tasks/./fold", "tasks//fold"])
def test_a_task_directory_cannot_escape_its_family(tmp_path, monkeypatch, task_dir: str) -> None:
    family = _family(tmp_path, monkeypatch)
    with pytest.raises(ResultContractError, match="beneath its runner family"):
        contract_directory(family, task_dir)


def test_a_task_directory_that_is_not_a_directory_is_refused(tmp_path, monkeypatch) -> None:
    family = _family(tmp_path, monkeypatch)
    (family / "tasks" / "file").write_text("not a directory\n", encoding="utf-8")
    with pytest.raises(ResultContractError, match="beneath its runner family"):
        contract_directory(family, "tasks/file")


def test_a_task_directory_symlinked_out_of_the_family_is_refused(tmp_path, monkeypatch) -> None:
    family = _family(tmp_path, monkeypatch)
    outside = tmp_path / "outside"
    (outside / "storyboard").mkdir(parents=True)
    (outside / "expected_files.yaml").write_text(_TREE.format(pattern="*.xyz"), encoding="utf-8")
    (family / "tasks" / "linked").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ResultContractError, match="beneath its runner family"):
        contract_directory(family, "tasks/linked")


def test_a_storyboard_without_its_own_tree_is_a_contract_error(tmp_path, monkeypatch) -> None:
    """A Task's module binds to logical files *this* Task declares.

    Answering such a Task from the family tree would bind its module to
    identities it never declared, so the declaration is refused instead.
    """
    family = _family(tmp_path, monkeypatch)
    (family / "tasks" / "design" / "expected_files.yaml").unlink()

    with pytest.raises(ResultContractError, match="needs its own expected_files.yaml"):
        contract_dir(_task(family, "tasks/design"), "")


def test_a_split_family_records_one_contract_per_owner(tmp_path, monkeypatch) -> None:
    """The live-test identity follows the owning declaration, not a re-derivation."""
    family = _family(tmp_path, monkeypatch)
    contracts = declared_result_contracts(family, {"synthetic_fold": "tasks/fold", "synthetic_design": "tasks/design"})

    assert sorted(contracts) == ["synthetic_design", "synthetic_fold"]
    assert contracts["synthetic_fold"]["outputs"]["pattern"] == "*.cif"
    assert contracts["synthetic_design"]["outputs"]["pattern"] == "*.cif.gz"


def test_an_unsplit_family_records_one_shared_contract(tmp_path, monkeypatch) -> None:
    """A family that adopts no split keeps the byte-identical record it had."""
    family = _family(tmp_path, monkeypatch)
    (family / "tasks" / "design" / "expected_files.yaml").write_text(_TREE.format(pattern="*.cif"), encoding="utf-8")
    _drop_task_contract(family)

    contracts = declared_result_contracts(family, {"synthetic_fold": "tasks/fold", "synthetic_design": "tasks/design"})

    assert contracts == result_storyboard.load_expected_file_tree(family / "expected_files.yaml")
    assert contracts["outputs"]["pattern"] == "*.cif"
