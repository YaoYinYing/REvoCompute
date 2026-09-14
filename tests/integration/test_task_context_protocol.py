# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[2]

def test_manifest_param_escaping_round_trip(tmp_path):
    """The v2 protocol must preserve param values byte-for-byte: backslash
    runs, quotes, shell metacharacters, newlines, and unicode all survive
    manifest -> task_context.py -> stdout."""
    values = {
        "smiles": "C=C(" + chr(92) + "C)" + chr(92) * 3 + "N",
        "quote": "it's 'quoted' \"double\"",
        "shell": "$(id) `whoami` ${HOME} && ; | > <",
        "newline": "line1" + chr(10) + "line2",
        "unicode": "β-转角-残基-序列",
        "backslash_run": chr(92) * 8,
    }
    manifest_path = tmp_path / "task.json"
    manifest_path.write_text(
        json.dumps(
            {
                "task_id": "t",
                "task_type": "test",
                "params": values,
                "inputs": {
                    "sequence": [{
                        "path": str(tmp_path / "input.fasta"),
                        "relative_path": "input.fasta",
                        "sha256": "x",
                    }]
                },
            }
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["TASK_MANIFEST"] = str(manifest_path)
    context_py = SERVER_ROOT / "docker" / "runners" / "common" / "task_context.py"
    for key, expected in values.items():
        completed = subprocess.run(
            ["python3", str(context_py), "param", key],
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
        assert completed.stdout == expected + chr(10), f"{key!r} did not round-trip: {completed.stdout!r}"

    # the bash wrapper path: one nasty value through _parse_param
    env["TASK_CONTEXT_SRC"] = str(SERVER_ROOT / "docker" / "runners" / "common" / "task_context.sh")
    bash_script = 'source "$TASK_CONTEXT_SRC"\nprintf "%s" "$(_parse_param smiles)"'
    completed = subprocess.run(["bash", "-c", bash_script], env=env, check=False, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == values["smiles"]
