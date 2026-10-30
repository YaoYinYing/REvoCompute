# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""PSSM-GREMLIN stage selection and fit checkpoint identity.

Each test runs the real ``run.sh`` against a protocol manifest with stub
search tools on PATH, so the assertions cover the executable stage logic:
which stage ran, what it wrote, and whether a repeated stage is skipped. The
fit script is stubbed through ``GREMLIN_TFV1_SCRIPT`` so a test can observe
which alignment bytes were actually fitted.
"""

from __future__ import annotations

import hashlib
import json
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
STEM = f"{INSTANCE}.i90c75_aln"

# Runs as ``python <this file> <alignment> <output_dir> <iteration>``. It
# records the fitted alignment identity and writes the model the fit stage
# checks for; STUB_FIT_FAIL simulates an interrupted fit.
FIT_STUB = """\
import hashlib
import os
import pathlib
import sys

alignment, output_dir, iteration = sys.argv[1:4]
data = pathlib.Path(alignment).read_bytes()
digest = hashlib.sha256(data).hexdigest()
with open(os.path.join(os.environ["STUB_CALLS"], "fit.calls"), "a", encoding="utf-8") as handle:
    handle.write(f"{alignment}\\t{digest}\\t{iteration}\\n")
model = pathlib.Path(output_dir) / (pathlib.Path(alignment).stem + ".GREMLIN.mrf.pkl")
plot = pathlib.Path(output_dir) / (pathlib.Path(alignment).stem + "_GREMLIN_mtx.png")
if os.environ.get("STUB_FIT_FAIL"):
    model.write_text("interrupted\\n", encoding="utf-8")
    sys.exit(1)
model.write_text(f"model {digest}\\n", encoding="utf-8")
plot.write_text(f"plot {digest}\\n", encoding="utf-8")
"""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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
    fit_script = tmp_path / "fit_stub.py"
    fit_script.write_text(FIT_STUB, encoding="utf-8")
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
        "GREMLIN_TFV1_SCRIPT": str(fit_script),
    }
    return env, bin_dir, calls


def _calls(calls: Path, tool: str) -> int:
    path = calls / f"{tool}.calls"
    return len(path.read_text(encoding="utf-8").splitlines()) if path.exists() else 0


def _fit_calls(calls: Path) -> list[list[str]]:
    """Each recorded fit: [alignment path, alignment sha256, iteration]."""
    path = calls / "fit.calls"
    if not path.exists():
        return []
    return [line.split("\t") for line in path.read_text(encoding="utf-8").splitlines()]


def _model(output: Path) -> Path:
    return output / "gremlin_res" / f"{STEM}.GREMLIN.mrf.pkl"


def _key(output: Path) -> Path:
    return output / ".gremlin_fit" / f"{STEM}.identity"


def _key_fields(output: Path) -> list[str]:
    """The key authenticates the identity and the model bytes it names."""
    return _key(output).read_text(encoding="utf-8").split()


def _run(tmp_path: Path, *extra_args: str, output: Path | None = None, env=None, params=None):
    source = tmp_path / f"{INSTANCE}.fasta"
    if not source.exists():
        source.write_text(FASTA, encoding="utf-8")
    output = output or (tmp_path / "output")
    env = env or _stub_environment(tmp_path)[0]
    return run_with_manifest(
        RUN_SCRIPT, source, output, env, params=params or {}, extra_args=extra_args, role="sequence"
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
    alignment = tmp_path / "output" / "gremlin_msa" / f"{STEM}.fas"
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


def test_empty_stage_outputs_are_rebuilt_rather_than_reused(tmp_path: Path) -> None:
    """A zero-byte leftover from an interrupted stage is not a completed stage."""
    env, _bin, calls = _stub_environment(tmp_path)
    output = tmp_path / "output"
    alignment = output / "gremlin_msa" / f"{STEM}.fas"
    pssm = output / "pssm_msa" / f"{INSTANCE}_ascii_mtx_file"
    alignment.parent.mkdir(parents=True)
    pssm.parent.mkdir(parents=True)
    alignment.write_bytes(b"")
    pssm.write_bytes(b"")

    msa = _run(tmp_path, "-s", "msa", "-U", str(tmp_path / "uniref30"), output=output, env=env)
    pssm_run = _run(tmp_path, "-s", "pssm", "-u", _formatted_uniref90(tmp_path), output=output, env=env)

    assert msa.returncode == 0, msa.stderr
    assert pssm_run.returncode == 0, pssm_run.stderr
    assert _calls(calls, "hhblits") == 1
    assert _calls(calls, "psiblast") == 1
    assert alignment.stat().st_size > 0
    assert pssm.stat().st_size > 0


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
    completed = _run(
        tmp_path, "-s", "all", "-U", str(tmp_path / "uniref30"),
        "-u", _formatted_uniref90(tmp_path), output=output, env=env,
    )
    assert completed.returncode == 0, completed.stderr
    alignment = output / "gremlin_msa" / f"{STEM}.fas"
    assert alignment.is_file()
    digest = _sha(alignment.read_bytes())
    # The fit stage ran against the alignment the msa stage produced.
    assert [_line[1] for _line in _fit_calls(calls)] == [digest]
    assert _model(output).read_text(encoding="utf-8") == f"model {digest}\n"
    assert (output / "pssm_msa" / f"{INSTANCE}_ascii_mtx_file").is_file()
    assert (output / "log" / "task_finished").is_file()
    assert _calls(calls, "hhblits") == 1
    assert _calls(calls, "psiblast") == 1


def _stage_inputs_document(tmp_path: Path, artifact: Path, digest: str | None = None) -> Path:
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
                        "sha256": digest or _sha(artifact.read_bytes()),
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


def _staged_alignment(tmp_path: Path, name: str, body: bytes) -> Path:
    staged = tmp_path / name / f"{STEM}.fas"
    staged.parent.mkdir(parents=True)
    staged.write_bytes(body)
    return staged


def test_fit_stage_without_a_shared_alignment_runs_from_the_document(tmp_path: Path) -> None:
    """A composed fit consumes the Server's copy; the shared tree need not exist."""
    env, _bin, calls = _stub_environment(tmp_path)
    output = tmp_path / "output"
    artifact = _staged_alignment(tmp_path, "stage", b">q\nACDE\n>h\nACDE\n")
    document = _stage_inputs_document(tmp_path, artifact)

    completed = _run(
        tmp_path, "-s", "fit", output=output, env={**env, "TASK_STAGE_INPUTS": str(document)}
    )

    assert completed.returncode == 0, completed.stderr
    assert not (output / "gremlin_msa").exists()
    fitted = _fit_calls(calls)
    assert len(fitted) == 1
    assert fitted[0][0] == str(artifact)
    assert fitted[0][1] == _sha(artifact.read_bytes())
    assert _model(output).read_text(encoding="utf-8") == f"model {_sha(artifact.read_bytes())}\n"


def test_fit_stage_refuses_a_documented_alignment_that_changed(tmp_path: Path) -> None:
    """The document, not the shared writable tree, decides which bytes are modelled."""
    env, _bin, calls = _stub_environment(tmp_path)
    output = tmp_path / "output"
    shared = output / "gremlin_msa"
    shared.mkdir(parents=True)
    (shared / f"{STEM}.fas").write_text(">q\nACDE\n", encoding="utf-8")
    artifact = _staged_alignment(tmp_path, "stage", b">q\nACDE\n>h\nACDE\n")
    document = _stage_inputs_document(tmp_path, artifact)
    artifact.write_text(">q\nAAAA\n>h\nAAAA\n", encoding="utf-8")

    completed = _run(
        tmp_path, "-s", "fit", output=output, env={**env, "TASK_STAGE_INPUTS": str(document)}
    )

    assert completed.returncode != 0
    assert "digest does not match" in completed.stderr
    assert _calls(calls, "hhblits") == 0
    assert _calls(calls, "psiblast") == 0


def test_fit_reruns_for_different_alignment_bytes_with_the_same_filename(tmp_path: Path) -> None:
    """A checkpoint belongs to the bytes that produced it, not to a basename."""
    env, _bin, calls = _stub_environment(tmp_path)
    output = tmp_path / "output"
    first = _staged_alignment(tmp_path, "first", b">q\nACDE\n>h\nACDE\n")
    second = _staged_alignment(tmp_path, "second", b">q\nAAAA\n>h\nAAAA\n")
    assert first.name == second.name

    document = _stage_inputs_document(tmp_path, first)
    first_run = _run(
        tmp_path, "-s", "fit", output=output, env={**env, "TASK_STAGE_INPUTS": str(document)}
    )
    assert first_run.returncode == 0, first_run.stderr
    first_model = _model(output).read_text(encoding="utf-8")
    assert first_model == f"model {_sha(first.read_bytes())}\n"

    # The first model and key are still present; input B is a different verified
    # alignment that happens to share a filename.
    document = _stage_inputs_document(tmp_path, second)
    second_run = _run(
        tmp_path, "-s", "fit", output=output, env={**env, "TASK_STAGE_INPUTS": str(document)}
    )
    assert second_run.returncode == 0, second_run.stderr

    fitted = _fit_calls(calls)
    assert len(fitted) == 2
    assert fitted[1][0] == str(second)
    assert fitted[1][1] == _sha(second.read_bytes())
    assert _model(output).read_text(encoding="utf-8") != first_model
    assert _model(output).read_text(encoding="utf-8") == f"model {_sha(second.read_bytes())}\n"
    assert (output / "gremlin_res" / f"{STEM}_GREMLIN_mtx.png").read_text(encoding="utf-8") == (
        f"plot {_sha(second.read_bytes())}\n"
    )


def test_fit_skips_only_for_the_same_authenticated_identity(tmp_path: Path) -> None:
    env, _bin, calls = _stub_environment(tmp_path)
    output = tmp_path / "output"
    artifact = _staged_alignment(tmp_path, "stage", b">q\nACDE\n>h\nACDE\n")
    document = _stage_inputs_document(tmp_path, artifact)
    run_env = {**env, "TASK_STAGE_INPUTS": str(document)}

    first = _run(tmp_path, "-s", "fit", output=output, env=run_env)
    second = _run(tmp_path, "-s", "fit", output=output, env=run_env)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert len(_fit_calls(calls)) == 1
    assert "skip GREMLIN_TFv1" in second.stdout
    fields = _key_fields(output)
    assert len(fields) == 2
    assert fields[1] == _sha(_model(output).read_bytes())


def test_fit_reruns_when_the_model_does_not_match_its_key(tmp_path: Path) -> None:
    """A matching identity is not enough: the model bytes must match the key too."""
    env, _bin, calls = _stub_environment(tmp_path)
    output = tmp_path / "output"
    artifact = _staged_alignment(tmp_path, "stage", b">q\nACDE\n>h\nACDE\n")
    document = _stage_inputs_document(tmp_path, artifact)
    run_env = {**env, "TASK_STAGE_INPUTS": str(document)}
    expected = f"model {_sha(artifact.read_bytes())}\n"

    first = _run(tmp_path, "-s", "fit", output=output, env=run_env)
    assert first.returncode == 0, first.stderr
    model = _model(output)
    key_fields = _key_fields(output)
    assert len(key_fields) == 2
    assert key_fields[1] == _sha(model.read_bytes())

    # Truncated but non-empty model with its key left intact: the identity still
    # matches, so only the recorded model digest can refuse the reuse.
    model.write_bytes(model.read_bytes()[:8])
    second = _run(tmp_path, "-s", "fit", output=output, env=run_env)

    assert second.returncode == 0, second.stderr
    assert len(_fit_calls(calls)) == 2
    assert model.read_text(encoding="utf-8") == expected
    refreshed = _key_fields(output)
    assert len(refreshed) == 2
    assert refreshed[1] == _sha(model.read_bytes())


def test_fit_reruns_when_the_iteration_parameter_changes(tmp_path: Path) -> None:
    env, _bin, calls = _stub_environment(tmp_path)
    output = tmp_path / "output"
    artifact = _staged_alignment(tmp_path, "stage", b">q\nACDE\n>h\nACDE\n")
    document = _stage_inputs_document(tmp_path, artifact)
    run_env = {**env, "TASK_STAGE_INPUTS": str(document)}

    first = _run(tmp_path, "-s", "fit", output=output, env=run_env, params={"iter": 100})
    second = _run(tmp_path, "-s", "fit", output=output, env=run_env, params={"iter": 101})

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    fitted = _fit_calls(calls)
    assert len(fitted) == 2
    assert [line[2] for line in fitted] == ["100", "101"]


def test_fit_reruns_when_the_identity_key_is_missing_or_truncated(tmp_path: Path) -> None:
    env, _bin, calls = _stub_environment(tmp_path)
    output = tmp_path / "output"
    artifact = _staged_alignment(tmp_path, "stage", b">q\nACDE\n>h\nACDE\n")
    document = _stage_inputs_document(tmp_path, artifact)
    run_env = {**env, "TASK_STAGE_INPUTS": str(document)}
    expected = f"model {_sha(artifact.read_bytes())}\n"
    model = _model(output)
    key = _key(output)
    model.parent.mkdir(parents=True)

    # Model present but no key: it cannot be authenticated, so it is refitted.
    model.write_text("stale checkpoint", encoding="utf-8")
    missing = _run(tmp_path, "-s", "fit", output=output, env=run_env)
    assert missing.returncode == 0, missing.stderr
    assert len(_fit_calls(calls)) == 1
    assert model.read_text(encoding="utf-8") == expected
    assert len(_key_fields(output)) == 2

    # A truncated key is not an authenticated cache entry either.
    truncated = key.read_text(encoding="utf-8")[:16]
    model.write_text("stale checkpoint", encoding="utf-8")
    key.write_text(truncated, encoding="utf-8")
    retried = _run(tmp_path, "-s", "fit", output=output, env=run_env)
    assert retried.returncode == 0, retried.stderr
    assert len(_fit_calls(calls)) == 2
    assert model.read_text(encoding="utf-8") == expected
    assert key.read_text(encoding="utf-8") != truncated
    assert _key_fields(output)[1] == _sha(model.read_bytes())


def test_fit_rerun_after_an_interrupted_fit_leaves_no_key(tmp_path: Path) -> None:
    env, _bin, calls = _stub_environment(tmp_path)
    output = tmp_path / "output"
    artifact = _staged_alignment(tmp_path, "stage", b">q\nACDE\n>h\nACDE\n")
    document = _stage_inputs_document(tmp_path, artifact)
    run_env = {**env, "TASK_STAGE_INPUTS": str(document)}
    model = _model(output)
    key = _key(output)
    model.parent.mkdir(parents=True)
    model.write_text("checkpoint from a failed run", encoding="utf-8")

    # The interrupted fit removes the unauthenticated checkpoint, writes a
    # partial one, fails, and must not authenticate it.
    failed = _run(tmp_path, "-s", "fit", output=output, env={**run_env, "STUB_FIT_FAIL": "1"})
    assert failed.returncode != 0
    assert len(_fit_calls(calls)) == 1
    assert not key.exists()

    # The partial model is not trusted; the retry fits again and writes the key.
    retried = _run(tmp_path, "-s", "fit", output=output, env=run_env)
    assert retried.returncode == 0, retried.stderr
    assert len(_fit_calls(calls)) == 2
    assert key.is_file()
    assert model.read_text(encoding="utf-8") == f"model {_sha(artifact.read_bytes())}\n"
    fields = _key_fields(output)
    assert len(fields) == 2
    assert fields[1] == _sha(model.read_bytes())
