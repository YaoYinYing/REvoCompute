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
import yaml

from revocompute import task_types

ROOT = Path(__file__).resolve().parents[1]
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


def test_pallatom_contract_is_restricted_gpu_unconditional_generation():
    with _RegistryContext():
        task_types.discover_plugins(str(ROOT / "docker" / "runners"), {"pallatom"})
        task, runner = task_types.get("pallatom_generate")

        assert task.runtime.name == "pallatom"
        assert task.runtime.access_policy.id == "pallatom_noncommercial"
        assert task.runtime.access_policy.requires == ("pallatom_noncommercial",)
        assert task.gpus is True
        assert task.min_input_files == 0
        assert task.schema["additionalProperties"] is False
        assert task.schema["properties"]["length"] == {
            "type": "integer",
            "description": "Number of amino-acid residues in each generated single-chain protein.",
            "default": 100,
            "minimum": 16,
            "maximum": 512,
        }
        assert task.schema["properties"]["num_samples"]["maximum"] == 32
        assert task.citation_dois == (
            (1, "10.1101/2024.08.16.608235", "P(all-atom) Is Unlocking New Path For Protein Design"),
        )
        assert [mount.mode for mount in runner.mounts] == ["ro"]
        assert runner.mounts[0].container_path == "/mnt/db/weights/revocompute/pallatom"


def test_pallatom_definition_pins_official_source_runtime_and_removes_bundled_params():
    definition = (FAMILY / "pallatom.def").read_text(encoding="utf-8")
    requirements = (FAMILY / "requirements.txt").read_text(encoding="utf-8")
    lock = (FAMILY / "requirements.lock").read_text(encoding="utf-8")

    assert "From: nvidia/cuda:12.6.3-cudnn-runtime-ubuntu22.04" in definition
    assert "https://github.com/levinthal/Pallatom.git" in definition
    assert "b27d70054dec6ce2f5ceadf8977de3d3baf00663" in definition
    assert "--require-hashes" in definition
    assert "rm -rf /opt/Pallatom/.git /opt/Pallatom/params" in definition
    assert "/mnt/db/weights/revocompute/pallatom" not in definition.split("%post", 1)[1].split("%environment", 1)[0]
    assert "mirror" not in definition.lower()
    assert "jax[cuda12]==0.4.34" in requirements
    assert "tensorflow-cpu==2.16.1" in requirements
    assert "numpy==1.24.3" in requirements
    for line in requirements.splitlines():
        assert "==" in line
    assert "--hash=sha256:" in lock
    assert "jax==0.4.34" in lock


def test_pallatom_asset_and_license_records_are_exact():
    assets = (FAMILY / "MODEL_ASSETS.md").read_text(encoding="utf-8")
    policy = yaml.safe_load(
        (ROOT / "docker/runners/common/policy/pallatom_noncommercial.yaml").read_text(encoding="utf-8")
    )

    assert "71,002,706" in assets
    assert "57dff1c37cb1d99984ab664a7dc96e2a44afb100ea6f1f3c397dbe838124bc2f" in assets
    assert "CC BY-NC-SA 4.0" in assets
    assert policy["id"] == "pallatom_noncommercial"
    assert policy["requestable"] is True
    assert "Attribution-NonCommercial-ShareAlike 4.0" in policy["license"]["name"]


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
                "files": [],
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
    manifest.write_text(json.dumps({"files": [], "params": {}}), encoding="utf-8")
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


def test_pallatom_smoke_uses_small_unconditional_case():
    smoke = yaml.safe_load((FAMILY / "test.yaml").read_text(encoding="utf-8"))
    case = smoke["collections"]["smoke"]["cases"][0]
    fixture = ROOT / case["input"]["files"][0]

    assert case["task"] == "pallatom_generate"
    assert case["parameters"]["length"] == 16
    assert case["parameters"]["num_samples"] == 1
    assert case["parameters"]["diffusion_steps"] == 2
    assert json.loads(fixture.read_text(encoding="utf-8")) == {"mode": "unconditional"}
