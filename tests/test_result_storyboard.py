# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import pytest

from revocompute import result_storyboard
from revocompute.result_storyboard import ResultContractError, expected_file_tree, resolve_expected_files, runner_root


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
    family = runners / "easifa"
    family.mkdir(parents=True)
    monkeypatch.setenv("RUNNERS_DIR", str(runners))

    runtime = type("Runtime", (), {"root": str(family), "definition": "easifa.def"})()
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
