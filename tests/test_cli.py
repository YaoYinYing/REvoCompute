# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from revocompute.__main__ import main


def test_revocompute_doctor_subcommand(tmp_path, capsys):
    (tmp_path / "task_types.yaml").write_text("runtime_families: {}\ntask_types: {}\n", encoding="utf-8")
    assert main(["doctor", "--config-root", str(tmp_path), "--strict"]) == 0
    assert "No diagnostics" in capsys.readouterr().out


def test_revocompute_rejects_unknown_command(capsys):
    assert main(["unknown"]) == 2
    assert "Unknown command" in capsys.readouterr().err

