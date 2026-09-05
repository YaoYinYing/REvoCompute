# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from pathlib import Path

import yaml

SERVER_ROOT = Path(__file__).resolve().parents[1]


def test_freebindcraft_contract():
    plugin_root = SERVER_ROOT / "docker/runners/freebindcraft"
    manifest = yaml.safe_load((plugin_root / "plugin.yaml").read_text(encoding="utf-8"))
    task = yaml.safe_load((plugin_root / "tasks/freebindcraft/task.yaml").read_text(encoding="utf-8"))
    runtime = manifest["runtime"]
    runner = yaml.safe_load((plugin_root / "runner.yaml").read_text(encoding="utf-8"))
    script = (SERVER_ROOT / "docker/runners/freebindcraft/run.sh").read_text(encoding="utf-8")
    definition = (plugin_root / runtime["definition"]).read_text(encoding="utf-8")
    consumed = {line.split("_parse_param ", 1)[1].split()[0] for line in script.splitlines() if "_parse_param " in line}

    assert manifest["id"] == "freebindcraft"
    assert task["category"] == "design"
    assert task["gpus"] is True
    assert task["input_extensions"] == [".pdb"]
    assert runner["mounts"] == [
        {
            "host_path": "/mnt/db/weights/alphafold/2022-12-06",
            "container_path": "/mnt/db/bindcraft/af_params",
            "mode": "ro",
        }
    ]
    assert set(task["parameters"]["properties"]) <= consumed
    assert 'filters_file="/opt/bindcraft/settings_filters/${filters_preset}.json"' in script
    assert '"filter_file"' not in script
    assert 'accepted_designs=("$output_dir"/Accepted/*.pdb)' in script
    assert "final_designs <= max_trajectories" in script
    assert script.count("tr -s '[:space:],' ','") == 2
    assert "Bootstrap: docker" in definition
    assert "export HTTP_PROXY= HTTPS_PROXY=" in definition
