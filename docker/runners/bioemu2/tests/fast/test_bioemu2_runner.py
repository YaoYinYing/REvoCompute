# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""BioEmu2 adapter and entrypoint contract.

No GPU and no network: a fake ``bioemu2`` on ``PYTHONPATH`` mirrors the call
seams the adapter binds to and writes the upstream output files, so the real
``run.sh`` is exercised end to end -- including the model-asset check and the
publication check -- against the calls it actually makes.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
FAMILY = ROOT / "docker" / "runners" / "bioemu2"
RUNNER = FAMILY / "run.sh"

FAKE_BIOEMU2 = """
import json
import os
from pathlib import Path


class System:
    @classmethod
    def from_description(cls, **kwargs):
        _capture("system", kwargs)
        return cls()


def _capture(key, value):
    path = Path(os.environ["BIOEMU2_CALL"])
    calls = json.loads(path.read_text()) if path.exists() else {}
    calls[key] = value
    path.write_text(json.dumps(calls))


def load_model(*, checkpoint_path):
    _capture("checkpoint", str(checkpoint_path))
    return object()


class _Frame:
    def save_pdb(self, path):
        if os.environ.get("BIOEMU2_OMIT_OUTPUT") == Path(path).name:
            return
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00  0.00           C\\n")


def sample_equilibrium(system, *, model, output_dir, **kwargs):
    _capture("sampling", kwargs)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    omit = os.environ.get("BIOEMU2_OMIT_OUTPUT", "")
    reject_first = os.environ.get("BIOEMU2_REJECT_FIRST") == "1"
    report = [
        {
            "frame": frame,
            "status": "rejected" if reject_first and frame == 0 else "passed",
            "reason": "bad_bonds_sidechain" if reject_first and frame == 0 else None,
        }
        for frame in range(kwargs["num_samples"])
    ]
    published = {
        "samples.xtc": b"xtc",
        "topology.cif": b"data_topology\\n",
        "system.yaml": b"entities: []\\n",
        "physicality.json": json.dumps(report).encode(),
    }
    for name, payload in published.items():
        if name != omit:
            (out / name).write_bytes(payload)
    return [_Frame() for _ in range(kwargs["num_samples"])]
"""


def _adapter():
    spec = importlib.util.spec_from_file_location("bioemu2_sample", FAMILY / "sample.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _workspace(tmp_path):
    """A fake checkpoint, its verified asset manifest, and the fake modules."""
    asset_root = tmp_path / "weights"
    checkpoint_dir = asset_root / "checkpoints" / "bioemu2-preview"
    checkpoint_dir.mkdir(parents=True)
    (checkpoint_dir / "checkpoint.ckpt").write_bytes(b"checkpoint")
    (checkpoint_dir / "config.yaml").write_text("model: test\n", encoding="utf-8")
    manifest = tmp_path / "model-assets.sha256"
    manifest.write_text(
        "".join(
            f"{hashlib.sha256((checkpoint_dir / name).read_bytes()).hexdigest()}  "
            f"checkpoints/bioemu2-preview/{name}\n"
            for name in ("checkpoint.ckpt", "config.yaml")
        ),
        encoding="utf-8",
    )
    modules = tmp_path / "modules"
    (modules / "bioemu2").mkdir(parents=True)
    (modules / "bioemu2" / "__init__.py").write_text(FAKE_BIOEMU2, encoding="utf-8")
    fasta = tmp_path / "input.fasta"
    fasta.write_text(">2KL8\nMEMDIRFRG\n", encoding="utf-8")
    return asset_root, manifest, modules, fasta


def _run(tmp_path, asset_root, manifest, modules, fasta, params, extra_env=None):
    from runner_protocol import run_with_manifest

    output_dir = tmp_path / "outputs"
    capture = tmp_path / "calls.json"
    env = os.environ.copy()
    env.update(
        {
            "BIOEMU2_PYTHON": sys.executable,
            "BIOEMU2_ASSET_ROOT": str(asset_root),
            "BIOEMU2_ASSET_MANIFEST": str(manifest),
            "BIOEMU2_CALL": str(capture),
            "RUNNER_RUNTIME_ROOT": str(ROOT / "docker" / "runners"),
            "PYTHONPATH": str(modules),
        }
    )
    env.update(extra_env or {})
    completed = run_with_manifest(RUNNER, fasta, output_dir, env, params=params, role="sequence")
    return completed, output_dir, capture


def test_bioemu2_parameters_and_sequence_reach_upstream(tmp_path):
    asset_root, manifest, modules, fasta = _workspace(tmp_path)
    params = {
        "num_samples": 3,
        "sampler": "edm_fk",
        "num_steps": 5,
        "batch_size": 2,
        "physicality_mode": "no_violations",
        "seed": 11,
    }

    completed, output_dir, capture = _run(tmp_path, asset_root, manifest, modules, fasta, params)

    assert completed.returncode == 0, completed.stderr
    calls = json.loads(capture.read_text(encoding="utf-8"))
    assert calls["system"] == {"proteins": ["MEMDIRFRG"]}
    assert calls["checkpoint"].endswith("checkpoints/bioemu2-preview/checkpoint.ckpt")
    assert calls["sampling"] == {
        "num_samples": 3,
        "sampler": "edm_fk",
        "num_steps": 5,
        "batch_size": 2,
        "physicality_mode": "no_violations",
        "seed": 11,
    }
    assert (output_dir / "topology.pdb").is_file()
    assert (output_dir / "sequence.fasta").read_text(encoding="utf-8") == ">input\nMEMDIRFRG\n"
    assert (output_dir / "task_finished").is_file()


def test_bioemu2_missing_published_output_fails_the_task(tmp_path):
    asset_root, manifest, modules, fasta = _workspace(tmp_path)

    completed, output_dir, _ = _run(
        tmp_path,
        asset_root,
        manifest,
        modules,
        fasta,
        {"num_samples": 1},
        {"BIOEMU2_OMIT_OUTPUT": "physicality.json"},
    )

    assert completed.returncode != 0
    assert "physicality.json" in completed.stderr
    assert not (output_dir / "task_finished").exists()


def test_bioemu2_publication_check_covers_every_required_contract_file(tmp_path):
    """The entrypoint drives its check from the same expected_files.yaml the server reads."""
    import yaml

    required = {
        entry["path"]
        for entry in yaml.safe_load((FAMILY / "tasks" / "bioemu2_equilibrium" / "expected_files.yaml").read_text())[
            "result"
        ]["files"].values()
        if entry.get("required")
    }
    assert "topology.cif" in required
    # sequence.fasta is written by the adapter itself, so the fake has no seam to
    # omit it; every other required path is staged by the fake upstream.
    for path in sorted(required - {"sequence.fasta"}):
        case = tmp_path / path
        case.mkdir()
        asset_root, manifest, modules, fasta = _workspace(case)
        completed, output_dir, _ = _run(
            case,
            asset_root,
            manifest,
            modules,
            fasta,
            {"num_samples": 1},
            {"BIOEMU2_OMIT_OUTPUT": path},
        )
        assert completed.returncode != 0, path
        assert path in completed.stderr, completed.stderr
        assert not (output_dir / "task_finished").exists(), path


def test_bioemu2_rejected_frames_are_reported_not_failed(tmp_path):
    """A rejected ensemble still succeeds, and its counts must reach the log."""
    asset_root, manifest, modules, fasta = _workspace(tmp_path)

    completed, output_dir, _ = _run(
        tmp_path,
        asset_root,
        manifest,
        modules,
        fasta,
        {"num_samples": 2},
        {"BIOEMU2_REJECT_FIRST": "1"},
    )

    assert completed.returncode == 0, completed.stderr
    assert "BioEmu2 physicality: 1/2 frames accepted (bad_bonds_sidechain: 1), 1 rejected" in completed.stdout
    assert (output_dir / "task_finished").is_file()


def test_bioemu2_sequence_framing(tmp_path):
    adapter = _adapter()
    fasta = tmp_path / "one.fasta"
    fasta.write_text(">query\nacdefg hik\n", encoding="utf-8")
    assert adapter.query_sequence(fasta) == "ACDEFGHIK"

    # A blank header is rejected on its own terms; a second record is rejected
    # as a second record even when its separator carries no header.
    fasta.write_text(">\nACDE\n", encoding="utf-8")
    with pytest.raises(ValueError, match="empty FASTA header"):
        adapter.query_sequence(fasta)

    fasta.write_text(">a\nACDE\n>b\nFGHI\n", encoding="utf-8")
    with pytest.raises(ValueError, match="exactly one protein sequence"):
        adapter.query_sequence(fasta)

    fasta.write_text(">a\nACDE\n>\nFGHI\n", encoding="utf-8")
    with pytest.raises(ValueError, match="exactly one protein sequence"):
        adapter.query_sequence(fasta)

    fasta.write_text(">a\nACDZ\n", encoding="utf-8")
    with pytest.raises(ValueError, match="residues Z"):
        adapter.query_sequence(fasta)


def test_bioemu2_optional_parameters_keep_upstream_defaults():
    adapter = _adapter()
    assert adapter.sampling_kwargs({"num_samples": 4}) == {"num_samples": 4}
