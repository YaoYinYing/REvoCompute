# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_with_manifest(script, input_file, output_dir, env, params=None, extra_args=(), *, role):
    """Run a Runner with a protocol-v4 manifest bound to its named input role."""
    manifest_path = input_file.parent / "task.json"
    manifest_path.write_text(
        json.dumps(
            {
                "task_id": "testtask",
                "task_type": "test",
                "params": params or {},
                "inputs": {
                    role: [{
                        "path": str(input_file),
                        "relative_path": input_file.name,
                        "sha256": "abc",
                    }]
                },
            }
        ),
        encoding="utf-8",
    )
    env["TASK_MANIFEST"] = str(manifest_path)
    env.setdefault(
        "TASK_CONTEXT_SRC",
        str(ROOT / "docker" / "runners" / "common" / "task_context.sh"),
    )
    return subprocess.run(
        ["bash", str(script), *extra_args, "-i", str(manifest_path), "-o", str(output_dir)],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
