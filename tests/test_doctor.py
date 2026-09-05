# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json

from revocompute.doctor import diagnose, main


def _config(tmp_path):
    family = tmp_path / "runners" / "demo_impl"
    (family / "tasks" / "fold").mkdir(parents=True)
    (family / "plugin.yaml").write_text("id: demo\nversion: '1'\nruntime:\n  definition: demo.def\ntasks: [tasks/fold/task.yaml]\n", encoding="utf-8")
    (family / "demo.def").write_text("Bootstrap: demo\n", encoding="utf-8")
    (family / "tasks" / "fold" / "task.yaml").write_text("id: fold\nparameters: {type: object}\n", encoding="utf-8")
    return tmp_path / "runners"


def test_doctor_reports_valid_minimal_configuration(tmp_path):
    report = diagnose(_config(tmp_path))
    assert report.ok
    assert report.diagnostics == ()


def test_doctor_reports_broken_task_link(tmp_path):
    config = _config(tmp_path)
    (config / "demo_impl" / "plugin.yaml").write_text("id: demo\nversion: '1'\ntasks: [tasks/missing.yaml]\n", encoding="utf-8")
    report = diagnose(config)
    assert any(item.code == "E3002" for item in report.diagnostics)


def test_doctor_json_and_strict_exit(tmp_path, capsys):
    config = tmp_path / "empty"
    config.mkdir()
    assert main(["--config-root", str(config), "--json", "--strict"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["diagnostics"] == []


def test_doctor_runner_and_task_filters_use_manifest_and_task_ids(tmp_path):
    root = _config(tmp_path)
    other = root / "other_storage"
    (other / "tasks" / "score").mkdir(parents=True)
    (other / "plugin.yaml").write_text(
        "id: other\nversion: '1'\nruntime: {}\ntasks: [tasks/score/task.yaml]\n", encoding="utf-8"
    )
    (other / "tasks" / "score" / "task.yaml").write_text(
        "id: score\nparameters: {type: object}\n", encoding="utf-8"
    )

    report = diagnose(root, runner="demo", task="fold")
    assert report.ok
    assert "demo/fold" in report.checked
    assert "other/score" not in report.checked

    unknown_runner = diagnose(root, runner="missing")
    assert any(item.code == "E1005" for item in unknown_runner.diagnostics)
    unknown_task = diagnose(root, task="missing")
    assert any(item.code == "E3001" for item in unknown_task.diagnostics)


def test_doctor_rejects_invalid_plugin_manifest_and_duplicate_ids(tmp_path):
    root = tmp_path / "runners"
    (root / "invalid").mkdir(parents=True)
    (root / "invalid" / "plugin.yaml").write_text("id: 'not valid'\nversion: '1'\n", encoding="utf-8")
    report = diagnose(root)
    assert any(item.code == "E1004" for item in report.diagnostics)

    (root / "invalid" / "plugin.yaml").write_text("id: duplicate\nversion: '1'\n", encoding="utf-8")
    (root / "second").mkdir()
    (root / "second" / "plugin.yaml").write_text("id: duplicate\nversion: '1'\n", encoding="utf-8")
    duplicate = diagnose(root)
    assert any(item.code == "E1004" for item in duplicate.diagnostics)


def test_doctor_rejects_invalid_schema_and_unsafe_manifest_paths(tmp_path):
    root = _config(tmp_path)
    plugin = root / "demo_impl" / "plugin.yaml"
    plugin.write_text(
        "id: demo\nversion: '1'\nruntime:\n  definition: ../outside.def\n"
        "tasks: [../outside.yaml]\n",
        encoding="utf-8",
    )
    report = diagnose(root)
    assert sum(item.code == "E2002" for item in report.diagnostics) == 2

    plugin.write_text("id: demo\nversion: '1'\ntasks: [tasks/fold/task.yaml]\n", encoding="utf-8")
    task = root / "demo_impl" / "tasks" / "fold" / "task.yaml"
    task.write_text("id: fold\nparameters: {type: definitely-not-a-schema-type}\n", encoding="utf-8")
    invalid_schema = diagnose(root)
    assert any(item.code == "E3002" for item in invalid_schema.diagnostics)


def test_doctor_reports_missing_access_policy_contribution(tmp_path):
    root = _config(tmp_path)
    plugin = root / "demo_impl" / "plugin.yaml"
    plugin.write_text(
        "id: demo\nversion: '1'\nruntime:\n  access_policy: missing_policy\n"
        "tasks: [tasks/fold/task.yaml]\n",
        encoding="utf-8",
    )
    report = diagnose(root)
    assert any(item.code in {"E1004", "E2100"} for item in report.diagnostics)


def test_doctor_reports_missing_runtime_asset(tmp_path):
    root = _config(tmp_path)
    (root / "demo_impl" / "demo.def").unlink()
    report = diagnose(root)
    assert any(item.code == "E2003" for item in report.diagnostics)
