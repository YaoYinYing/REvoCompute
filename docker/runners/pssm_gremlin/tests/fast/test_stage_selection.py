# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""PSSM-GREMLIN stage selection.

Each test runs the real ``run.sh`` against a protocol manifest with stub
search tools on PATH, so the assertions cover the executable stage logic:
which stage ran, what it wrote, and whether a repeated stage is skipped.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.runner_contract

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "docker" / "runner_testkit"))
from runner_protocol import run_with_manifest

RUN_SCRIPT = ROOT / "docker" / "runners" / "pssm_gremlin" / "run.sh"
FASTA = ">2KL8\nMKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQ\n"
INSTANCE = "2KL8"


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _stub_environment(tmp_path: Path) -> tuple[dict[str, str], Path, Path]:
    """A PATH with stub search tools and a link to the test interpreter."""
    bin_dir = tmp_path / "bin"
    calls = tmp_path / "calls"
    bin_dir.mkdir()
    calls.mkdir()
    os.symlink(sys.executable, bin_dir / "python")
    _write_executable(
        bin_dir / "hhblits",
        """#!/bin/bash
set -e
prev=""
for arg in "$@"; do
  if [[ "$prev" == "-oa3m" ]]; then printf ">q\\nACDE\\n>h\\nACDE\\n" > "$arg"; fi
  prev="$arg"
done
echo "hhblits" >> "${STUB_CALLS}/hhblits.calls"
""",
    )
    _write_executable(
        bin_dir / "hhfilter",
        """#!/bin/bash
set -e
prev=""
source=""
for arg in "$@"; do
  [[ "$prev" == "-i" ]] && source="$arg"
  if [[ "$prev" == "-o" ]]; then cp "$source" "$arg"; fi
  prev="$arg"
done
echo "hhfilter" >> "${STUB_CALLS}/hhfilter.calls"
""",
    )
    _write_executable(
        bin_dir / "psiblast",
        """#!/bin/bash
set -e
if [[ "${1:-}" == "-version" ]]; then echo "psiblast: 2.13.0+"; exit 0; fi
prev=""
for arg in "$@"; do
  if [[ "$prev" == "-out_ascii_pssm" ]]; then printf "1 A 0\\n" > "$arg"; fi
  prev="$arg"
done
echo "psiblast" >> "${STUB_CALLS}/psiblast.calls"
""",
    )
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:/usr/local/bin:/usr/bin:/bin",
        "STUB_CALLS": str(calls),
    }
    return env, bin_dir, calls


def _calls(calls: Path, tool: str) -> int:
    path = calls / f"{tool}.calls"
    return len(path.read_text(encoding="utf-8").splitlines()) if path.exists() else 0


def _run(tmp_path: Path, *extra_args: str, output: Path | None = None, env=None):
    source = tmp_path / f"{INSTANCE}.fasta"
    if not source.exists():
        source.write_text(FASTA, encoding="utf-8")
    output = output or (tmp_path / "output")
    env = env or _stub_environment(tmp_path)[0]
    return run_with_manifest(
        RUN_SCRIPT, source, output, env, params={}, extra_args=extra_args, role="sequence"
    )


def _formatted_uniref90(tmp_path: Path) -> str:
    directory = tmp_path / "uniref90"
    directory.mkdir()
    (directory / "uniref90.phr").write_text("index", encoding="utf-8")
    return str(directory / "uniref90")


def test_unknown_stage_is_rejected_before_any_search(tmp_path: Path) -> None:
    completed = _run(tmp_path, "-s", "nonsense")
    assert completed.returncode != 0
    assert "Unknown stage" in completed.stderr
    assert not (tmp_path / "output" / "task_finished").exists()


def test_msa_stage_writes_alignment_and_does_not_run_pssm(tmp_path: Path) -> None:
    env, _bin, calls = _stub_environment(tmp_path)
    completed = _run(tmp_path, "-s", "msa", "-U", str(tmp_path / "uniref30"), env=env)
    assert completed.returncode == 0, completed.stderr
    alignment = tmp_path / "output" / "gremlin_msa" / f"{INSTANCE}.i90c75_aln.fas"
    assert alignment.is_file() and alignment.stat().st_size > 0
    assert _calls(calls, "hhblits") == 1
    assert _calls(calls, "hhfilter") == 1
    assert _calls(calls, "psiblast") == 0


def test_msa_stage_is_idempotent(tmp_path: Path) -> None:
    env, _bin, calls = _stub_environment(tmp_path)
    output = tmp_path / "output"
    first = _run(tmp_path, "-s", "msa", "-U", str(tmp_path / "uniref30"), output=output, env=env)
    second = _run(tmp_path, "-s", "msa", "-U", str(tmp_path / "uniref30"), output=output, env=env)
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert _calls(calls, "hhblits") == 1
    assert _calls(calls, "hhfilter") == 1
    assert "skipping hhblits/hhfilter" in second.stdout


def test_fit_stage_without_msa_alignment_fails_closed(tmp_path: Path) -> None:
    env, _bin, calls = _stub_environment(tmp_path)
    completed = _run(tmp_path, "-s", "fit", env=env)
    assert completed.returncode != 0
    assert "requires the msa-stage alignment" in completed.stderr
    assert _calls(calls, "hhblits") == 0
    assert _calls(calls, "psiblast") == 0
    assert not (tmp_path / "output" / "task_finished").exists()


def test_pssm_stage_requires_a_formatted_uniref90_database(tmp_path: Path) -> None:
    env, _bin, calls = _stub_environment(tmp_path)
    completed = _run(tmp_path, "-s", "pssm", "-u", str(tmp_path / "missing" / "uniref90"), env=env)
    assert completed.returncode != 0
    assert "not found" in completed.stderr
    assert _calls(calls, "psiblast") == 0
    assert not (tmp_path / "output" / "task_finished").exists()


def test_all_selects_msa_fit_and_pssm(tmp_path: Path) -> None:
    env, _bin, calls = _stub_environment(tmp_path)
    output = tmp_path / "output"
    model = output / "gremlin_res" / f"{INSTANCE}.i90c75_aln.GREMLIN.mrf.pkl"
    model.parent.mkdir(parents=True)
    # The fit stage skips a present checkpoint; the point here is that this run
    # selected it, ran msa before it and pssm after it.
    model.write_text("checkpoint", encoding="utf-8")
    completed = _run(
        tmp_path, "-s", "all", "-U", str(tmp_path / "uniref30"),
        "-u", _formatted_uniref90(tmp_path), output=output, env=env,
    )
    assert completed.returncode == 0, completed.stderr
    assert "Checkpoint file exists" in completed.stdout
    assert (output / "gremlin_msa" / f"{INSTANCE}.i90c75_aln.fas").is_file()
    assert (output / "pssm_msa" / f"{INSTANCE}_ascii_mtx_file").is_file()
    assert (output / "log" / "task_finished").is_file()
    assert _calls(calls, "hhblits") == 1
    assert _calls(calls, "psiblast") == 1


def _stage_inputs_document(tmp_path: Path, artifact: Path, digest: str | None = None) -> Path:
    import hashlib
    import json

    document = tmp_path / "stage_inputs.json"
    document.write_text(
        json.dumps({
            "version": 1,
            "stage": "gremlin_msa_to_lh_fit.fit",
            "inputs": {
                "alignment": {
                    "path": str(artifact),
                    "files": [{
                        "path": str(artifact),
                        "source_path": f"gremlin_msa/{artifact.name}",
                        "sha256": digest or hashlib.sha256(artifact.read_bytes()).hexdigest(),
                        "size": artifact.stat().st_size,
                    }],
                    "producer": "gremlin_msa_to_lh_fit.msa",
                    "producer_attempt": 1,
                }
            },
        }),
        encoding="utf-8",
    )
    return document


def test_fit_stage_without_a_shared_alignment_runs_from_the_document(tmp_path: Path) -> None:
    """A composed fit consumes the Server's copy; the shared tree need not exist."""
    env, _bin, _calls = _stub_environment(tmp_path)
    output = tmp_path / "output"
    staged = tmp_path / "stage" / "alignment"
    staged.mkdir(parents=True)
    artifact = staged / f"{INSTANCE}.i90c75_aln.fas"
    artifact.write_text(">q\nACDE\n>h\nACDE\n", encoding="utf-8")
    document = _stage_inputs_document(tmp_path, artifact)
    model = output / "gremlin_res" / f"{INSTANCE}.i90c75_aln.GREMLIN.mrf.pkl"
    model.parent.mkdir(parents=True)
    model.write_text("checkpoint", encoding="utf-8")

    completed = _run(
        tmp_path, "-s", "fit", output=output, env={**env, "TASK_STAGE_INPUTS": str(document)}
    )

    assert completed.returncode == 0, completed.stderr
    assert "Checkpoint file exists" in completed.stdout


def test_fit_stage_refuses_a_documented_alignment_that_changed(tmp_path: Path) -> None:
    """The document, not the shared writable tree, decides which bytes are modelled."""
    env, _bin, calls = _stub_environment(tmp_path)
    output = tmp_path / "output"
    shared = output / "gremlin_msa"
    shared.mkdir(parents=True)
    (shared / f"{INSTANCE}.i90c75_aln.fas").write_text(">q\nACDE\n", encoding="utf-8")
    staged = tmp_path / "stage" / "alignment"
    staged.mkdir(parents=True)
    artifact = staged / f"{INSTANCE}.i90c75_aln.fas"
    artifact.write_text(">q\nACDE\n>h\nACDE\n", encoding="utf-8")
    document = _stage_inputs_document(tmp_path, artifact)
    artifact.write_text(">q\nAAAA\n>h\nAAAA\n", encoding="utf-8")

    completed = _run(
        tmp_path, "-s", "fit", output=output, env={**env, "TASK_STAGE_INPUTS": str(document)}
    )

    assert completed.returncode != 0
    assert "digest does not match" in completed.stderr
    assert _calls(calls, "hhblits") == 0
    assert _calls(calls, "psiblast") == 0
