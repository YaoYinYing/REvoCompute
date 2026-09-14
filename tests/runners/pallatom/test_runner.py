# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest
from revocompute import task_types

ROOT = Path(__file__).resolve().parents[3]
FAMILY = ROOT / "docker" / "runners" / "pallatom"
RUNNER = FAMILY / "run.sh"


class _RegistryContext:
    def __enter__(self):
        self.tasks = dict(task_types._registry)
        self.runtimes = dict(task_types._runtime_registry)
        self.categories = dict(task_types._category_registry)
        return self

    def __exit__(self, *_):
        task_types._registry.clear()
        task_types._registry.update(self.tasks)
        task_types._runtime_registry.clear()
        task_types._runtime_registry.update(self.runtimes)
        task_types._category_registry.clear()
        task_types._category_registry.update(self.categories)


def _load_adapter():
    spec = importlib.util.spec_from_file_location("pallatom_generate", FAMILY / "generate.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pallatom_checkpoint_validation_rejects_wrong_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    adapter = _load_adapter()
    checkpoint = tmp_path / "params_Pallatom.npz"
    checkpoint.write_bytes(b"pallatom-test-checkpoint")

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        adapter.validate_checkpoint(checkpoint)

    digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    monkeypatch.setattr(adapter, "CHECKPOINT_SHA256", digest)
    assert adapter.validate_checkpoint(checkpoint) == digest


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"seed": -1}, "seed must be"),
        ({"t_min": 1.0, "t_max": 1.0}, "noise levels must satisfy"),
        ({"gamma": 1.1}, "gamma must be"),
        ({"step_scale": 0.0}, "step_scale must be"),
    ],
)
def test_pallatom_adapter_rejects_unsafe_numeric_combinations(values: dict[str, float], message: str):
    adapter = _load_adapter()
    defaults = {"seed": 0, "t_min": 0.01, "t_max": 1.0, "gamma": 0.2, "step_scale": 2.25}
    defaults.update(values)
    namespace = type("Args", (), defaults)()
    with pytest.raises(ValueError, match=message):
        adapter.validate_numeric_args(namespace)


def test_pallatom_wrapper_forwards_controls_and_requires_solid_artifacts(tmp_path: Path):
    checkpoint = tmp_path / "assets" / "params" / "params_Pallatom.npz"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(b"fake-checkpoint")
    manifest = tmp_path / "task.json"
    manifest.write_text(
        json.dumps(
            {
                "inputs": {},
                "params": {
                    "length": 64,
                    "num_samples": 2,
                    "seed": 17,
                    "diffusion_steps": 20,
                    "t_min": 0.02,
                    "t_max": 0.9,
                    "gamma": 0.1,
                    "step_scale": 2.0,
                },
            }
        ),
        encoding="utf-8",
    )
    fake = tmp_path / "fake_generate.py"
    fake.write_text(
        """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys
args = sys.argv[1:]
Path(os.environ['PALLATOM_CALL_LOG']).write_text(json.dumps(args), encoding='utf-8')
out = Path(args[args.index('--output-dir') + 1])
out.mkdir(parents=True, exist_ok=True)
(out / 'sample_seq.fasta').write_text('>design_0001\\nACDE\\n', encoding='utf-8')
(out / 'design_0001.pdb').write_text('ATOM\\n', encoding='utf-8')
(out / 'generation_metadata.json').write_text('{}\\n', encoding='utf-8')
""",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    call_log = tmp_path / "call.json"
    output = tmp_path / "output"
    env = {
        **os.environ,
        "TASK_TYPE": "pallatom_generate",
        "TASK_CONTEXT_SRC": str(ROOT / "docker" / "runners" / "common" / "task_context.sh"),
        "PALLATOM_ASSET_ROOT": str(tmp_path / "assets"),
        "PALLATOM_GENERATE_SCRIPT": str(fake),
        "PALLATOM_PYTHON": "python3",
        "PALLATOM_CALL_LOG": str(call_log),
    }
    completed = subprocess.run(
        ["bash", str(RUNNER), "-i", str(manifest), "-o", str(output)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert (output / "task_finished").is_file()
    args = json.loads(call_log.read_text(encoding="utf-8"))
    assert args[args.index("--length") + 1] == "64"
    assert args[args.index("--num-samples") + 1] == "2"
    assert args[args.index("--seed") + 1] == "17"
    assert args[args.index("--diffusion-steps") + 1] == "20"


def test_pallatom_wrapper_rejects_wrong_task_type(tmp_path: Path):
    manifest = tmp_path / "task.json"
    manifest.write_text(json.dumps({"inputs": {}, "params": {}}), encoding="utf-8")
    completed = subprocess.run(
        ["bash", str(RUNNER), "-i", str(manifest), "-o", str(tmp_path / "output")],
        env={**os.environ, "TASK_TYPE": "pallatom_other"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode != 0
    assert completed.stderr == "Unsupported TASK_TYPE: pallatom_other\n"
    assert not (tmp_path / "output").exists()
