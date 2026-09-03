# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json

from revocompute.doctor import diagnose, main


def _config(tmp_path):
    (tmp_path / "runners").mkdir()
    (tmp_path / "runners" / "demo.yaml").write_text("mounts: []\n", encoding="utf-8")
    (tmp_path / "task_types.yaml").write_text(
        "runtime_families:\n  demo:\n    docker_image: demo:latest\n    dockerfile: Dockerfile\n    definition: demo.def\n"
        "task_types:\n  fold:\n    runtime_family: demo\n",
        encoding="utf-8",
    )
    return tmp_path


def test_doctor_reports_valid_minimal_configuration(tmp_path):
    report = diagnose(_config(tmp_path))
    assert report.ok
    assert report.diagnostics == ()


def test_doctor_reports_broken_task_link(tmp_path):
    config = _config(tmp_path)
    config.joinpath("task_types.yaml").write_text(
        config.joinpath("task_types.yaml").read_text(encoding="utf-8").replace("runtime_family: demo", "runtime_family: missing"),
        encoding="utf-8",
    )
    report = diagnose(config)
    assert any(item.code == "E5101" for item in report.diagnostics)


def test_doctor_json_and_strict_exit(tmp_path, capsys):
    config = tmp_path / "empty"
    config.mkdir()
    assert main(["--config-root", str(config), "--json", "--strict"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["code"] == "E1001"

