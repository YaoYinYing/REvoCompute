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
