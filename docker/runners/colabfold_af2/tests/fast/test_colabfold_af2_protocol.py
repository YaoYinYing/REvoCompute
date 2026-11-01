# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import hashlib
import json
import os
from functools import partial
from pathlib import Path

import pytest
from revocompute.task_types import get, isolated_discovery
from runner_protocol import ROOT, run_with_manifest

COLABFOLD_RUNNER_SCRIPT = ROOT / "docker/runners/colabfold_af2/run.sh"
COLABFOLD_NORMALIZER = ROOT / "docker/runners/colabfold_af2/normalize_interface_scores.py"
_run_with_manifest = partial(run_with_manifest, role="sequence")

def _write_fake_context(tmp_path: Path, **parameters) -> Path:
    values = {
        "model_type": "auto",
        "msa_mode": "mmseqs2_uniref_env",
        "num_recycle": 3,
        "num_models": 5,
        "num_seeds": 1,
        "random_seed": 0,
        "num_relax": 1,
        "use_fast_kernels": "false",
        "kernel_backend": "auto",
        "compile_mode": "tuned",
        **parameters,
    }
    resolved = " ".join(f"{name}) echo {value};;" for name, value in values.items())
    script = tmp_path / "task_context.sh"
    script.write_text(
        f'_parse_param() {{ case "$1" in {resolved} esac; }}\n'
        'task_input() { printf "%s\\n" "$FAKE_PRIMARY_INPUT"; }\n',
        encoding="utf-8",
    )
    return script

RESULT_SUBDIR = "colabfold"


def _result_dir(output_dir: Path) -> Path:
    """The Runner-owned result subtree that every ColabFold output lives under."""
    return output_dir / RESULT_SUBDIR


def _msa_digest(output_dir: Path, jobs: tuple[str, ...] = ("query",)) -> str:
    """Mirror run.sh's digest of every job's a3m and pickle cache, sorted by job."""
    result_dir = _result_dir(output_dir)
    lines = []
    for job in sorted(jobs):
        for suffix in (".a3m", ".pickle"):
            path = result_dir / f"{job}{suffix}"
            if path.is_file():
                lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n")
    return hashlib.sha256("".join(lines).encode()).hexdigest()


def _seed_features(output_dir: Path, jobs: tuple[str, ...] = ("query",)) -> None:
    """Write the features output and digest marker a features stage publishes."""
    result_dir = _result_dir(output_dir)
    result_dir.mkdir(parents=True, exist_ok=True)
    for job in jobs:
        (result_dir / f"{job}.a3m").write_text(f">{job}\nAAAA\n>hit\nAAAA\n", encoding="utf-8")
        (result_dir / f"{job}.pickle").write_text("MSA\n", encoding="utf-8")
    (result_dir / ".colabfold-msa-complete").write_text(_msa_digest(output_dir, jobs), encoding="utf-8")


def _write_fake_colabfold(tmp_path: Path) -> Path:
    executable = tmp_path / "colabfold_batch"
    executable.write_text(
        r"""#!/bin/bash
set -e
printf "%s\n" "$@" > "$FAKE_ARGS_FILE"
if [[ " $* " == *" --msa-only "* ]]; then
  printf "features\n" >> "$FAKE_CALL_LOG"
else
  printf "model\n" >> "$FAKE_CALL_LOG"
fi
output_dir="${@: -1}"
fasta="${@: -2:1}"
mapfile -t jobs < <(python3 - "$fasta" <<'PY'
import sys

for line in open(sys.argv[1], encoding="utf-8"):
    line = line.strip()
    if line.startswith(">"):
        print("".join(c if c.isalnum() or c in "_.-" else "_" for c in line[1:]))
PY
)
if [[ -n "${FAKE_FAIL_STAGE:-}" ]]; then
  [[ "$FAKE_FAIL_STAGE" == features && " $* " == *" --msa-only "* ]] && exit 9
  [[ "$FAKE_FAIL_STAGE" == model && " $* " != *" --msa-only "* ]] && exit 9
fi
if [[ "${FAKE_NO_OUTPUT:-}" == "1" ]]; then exit 0; fi
for job in "${jobs[@]}"; do
  if [[ -n "${FAKE_NO_JOB:-}" && "$FAKE_NO_JOB" == "$job" ]]; then continue; fi
  if [[ -f "$output_dir/${job}.done.txt" ]]; then
    echo "Skipping ${job} (already done)" >&2
    continue
  fi
  if [[ " $* " == *" --msa-only "* ]]; then
    if [[ -f "$output_dir/${job}.pickle" ]]; then src=REUSED; else src=FRESH; fi
    printf ">%s\nAAAA\n%s\n" "$job" "$src" > "$output_dir/${job}.a3m"
    printf "%s\n" "$src" > "$output_dir/${job}.pickle"
  else
    [[ -s "$output_dir/${job}.pickle" ]] || { echo "missing MSA cache for $job" >&2; exit 7; }
    if [[ -f "$output_dir/${job}_unrelaxed_rank_001_model_1.pdb" ]]; then src=REUSED; else src=FRESH; fi
    printf "%s\n" "$src" > "$output_dir/${job}_unrelaxed_rank_001_model_1.pdb"
    if [[ "${FAKE_INTERFACE_SCORES:-no}" == "yes" ]]; then
      printf '{"ptm":0.8,"ipsae":{"A-B":0.61,"A-C":0.74},"pdockq2":{"A-B":0.71,"A-C":0.42}}\n' \
        > "$output_dir/${job}_scores_rank_001_model_1.json"
    fi
    printf "done\n" > "$output_dir/${job}.done.txt"
  fi
done
""",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable

def _runner_env(tmp_path: Path, fake_context: Path, input_file: Path, fake_args: Path) -> dict:
    env = os.environ.copy()
    env.update(
        {
            "COLABFOLD_BATCH": str(_write_fake_colabfold(tmp_path)),
            "COLABFOLD_NORMALIZER": str(COLABFOLD_NORMALIZER),
            "FAKE_ARGS_FILE": str(fake_args),
            "FAKE_CALL_LOG": str(tmp_path / "calls"),
            "FAKE_PRIMARY_INPUT": str(input_file),
            "TASK_CONTEXT_SRC": str(fake_context),
        }
    )
    return env

def test_colabfold_feature_stage_uses_online_msa_and_stops_before_modeling(tmp_path):
    input_file = tmp_path / "input.fasta"
    output_dir = tmp_path / "outputs"
    fake_args = tmp_path / "colabfold.args"
    input_file.write_text(">query\nAAAA\n", encoding="utf-8")
    output_dir.mkdir()
    env = _runner_env(tmp_path, _write_fake_context(tmp_path), input_file, fake_args)
    completed = _run_with_manifest(COLABFOLD_RUNNER_SCRIPT, input_file, output_dir, env, extra_args=("-s", "features"))

    assert completed.returncode == 0, completed.stderr
    args = fake_args.read_text(encoding="utf-8")
    assert "--msa-only" in args
    assert "--host-url\nhttps://api.colabfold.com" in args
    assert "--data\n/mnt/colabfold" in args
    assert (_result_dir(output_dir) / ".colabfold-msa-complete").is_file()
    assert not (output_dir / "task_finished").exists()

def test_colabfold_model_stage_reuses_msa_and_relaxes_on_gpu(tmp_path):
    input_file = tmp_path / "input.fasta"
    output_dir = tmp_path / "outputs"
    fake_args = tmp_path / "colabfold.args"
    input_file.write_text(">query\nAAAA\n", encoding="utf-8")
    output_dir.mkdir()
    _seed_features(output_dir)
    env = _runner_env(tmp_path, _write_fake_context(tmp_path), input_file, fake_args)
    completed = _run_with_manifest(
        COLABFOLD_RUNNER_SCRIPT,
        input_file,
        output_dir,
        env,
        extra_args=("-s", "model"),
        params={
            "model_type": "auto",
            "msa_mode": "mmseqs2_uniref_env",
            "num_recycle": 3,
            "num_models": 5,
            "num_seeds": 1,
            "random_seed": 0,
            "num_relax": 1,
        },
    )

    assert completed.returncode == 0, completed.stderr
    args = fake_args.read_text(encoding="utf-8")
    assert "--msa-only" not in args
    assert "--amber\n--use-gpu-relax\n--num-relax\n1" in args
    assert (output_dir / "task_finished").is_file()

def test_colabfold_model_stage_leaves_fused_kernels_off_by_default(tmp_path):
    input_file = tmp_path / "input.fasta"
    output_dir = tmp_path / "outputs"
    fake_args = tmp_path / "colabfold.args"
    input_file.write_text(">query\nAAAA\n", encoding="utf-8")
    output_dir.mkdir()
    _seed_features(output_dir)
    env = _runner_env(tmp_path, _write_fake_context(tmp_path), input_file, fake_args)
    completed = _run_with_manifest(COLABFOLD_RUNNER_SCRIPT, input_file, output_dir, env, extra_args=("-s", "model"))

    assert completed.returncode == 0, completed.stderr
    args = fake_args.read_text(encoding="utf-8").splitlines()
    assert "--use-fast-kernels" not in args
    assert args[args.index("--kernel-backend") + 1] == "auto"
    assert args[args.index("--compile-mode") + 1] == "tuned"

def test_colabfold_model_stage_forwards_requested_kernel_settings(tmp_path):
    input_file = tmp_path / "input.fasta"
    output_dir = tmp_path / "outputs"
    fake_args = tmp_path / "colabfold.args"
    input_file.write_text(">query\nAAAA\n", encoding="utf-8")
    output_dir.mkdir()
    _seed_features(output_dir)
    fake_context = _write_fake_context(
        tmp_path,
        use_fast_kernels="true",
        kernel_backend="pallas",
        compile_mode="full",
    )
    env = _runner_env(tmp_path, fake_context, input_file, fake_args)
    completed = _run_with_manifest(COLABFOLD_RUNNER_SCRIPT, input_file, output_dir, env, extra_args=("-s", "model"))

    assert completed.returncode == 0, completed.stderr
    args = fake_args.read_text(encoding="utf-8").splitlines()
    assert "--use-fast-kernels" in args
    assert args[args.index("--kernel-backend") + 1] == "pallas"
    assert args[args.index("--compile-mode") + 1] == "full"

def test_colabfold_model_stage_summarizes_complex_interface_confidence(tmp_path):
    input_file = tmp_path / "input.fasta"
    output_dir = tmp_path / "outputs"
    fake_args = tmp_path / "colabfold.args"
    input_file.write_text(">query\nAAAA\n", encoding="utf-8")
    output_dir.mkdir()
    _seed_features(output_dir)
    env = _runner_env(tmp_path, _write_fake_context(tmp_path), input_file, fake_args)
    env["FAKE_INTERFACE_SCORES"] = "yes"
    completed = _run_with_manifest(COLABFOLD_RUNNER_SCRIPT, input_file, output_dir, env, extra_args=("-s", "model"))

    assert completed.returncode == 0, completed.stderr
    summary = json.loads((_result_dir(output_dir) / "interface_scores.json").read_text(encoding="utf-8"))
    assert summary["interface"] == "A-C"
    assert summary["ipsae"] == 0.74
    assert summary["pdockq2"] == 0.42
    assert summary["scores_file"] == "query_scores_rank_001_model_1.json"

def test_colabfold_model_stage_omits_interface_summary_for_monomers(tmp_path):
    input_file = tmp_path / "input.fasta"
    output_dir = tmp_path / "outputs"
    fake_args = tmp_path / "colabfold.args"
    input_file.write_text(">query\nAAAA\n", encoding="utf-8")
    output_dir.mkdir()
    _seed_features(output_dir)
    env = _runner_env(tmp_path, _write_fake_context(tmp_path), input_file, fake_args)
    completed = _run_with_manifest(COLABFOLD_RUNNER_SCRIPT, input_file, output_dir, env, extra_args=("-s", "model"))

    assert completed.returncode == 0, completed.stderr
    assert not (_result_dir(output_dir) / "interface_scores.json").exists()
    assert (output_dir / "task_finished").is_file()


def _retry_env(tmp_path: Path) -> tuple[dict, Path, Path]:
    input_file = tmp_path / "input.fasta"
    input_file.write_text(">query\nAAAA\n", encoding="utf-8")
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    fake_args = tmp_path / "colabfold.args"
    env = _runner_env(tmp_path, _write_fake_context(tmp_path), input_file, fake_args)
    return env, input_file, output_dir


def _run_stage(env: dict, input_file: Path, output_dir: Path, stage: str):
    return _run_with_manifest(COLABFOLD_RUNNER_SCRIPT, input_file, output_dir, env, extra_args=("-s", stage))


def _calls(env: dict) -> list[str]:
    calls = Path(env["FAKE_CALL_LOG"])
    return calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []


def test_colabfold_features_recomputes_and_clears_its_own_subtree(tmp_path):
    env, input_file, output_dir = _retry_env(tmp_path)
    result = _result_dir(output_dir)
    result.mkdir()
    (result / "query.a3m").write_text("STALE\n", encoding="utf-8")
    (result / "query.pickle").write_text("STALE\n", encoding="utf-8")
    (result / "query.done.txt").write_text("", encoding="utf-8")
    (result / "query_unrelaxed_rank_001_model_1.pdb").write_text("STALE\n", encoding="utf-8")
    (result / "query_coverage.png").write_text("STALE\n", encoding="utf-8")
    (result / "config.json").write_text("STALE\n", encoding="utf-8")
    (result / "log.txt").write_text("STALE\n", encoding="utf-8")
    (result / "interface_scores.json").write_text("{}\n", encoding="utf-8")
    (output_dir / "task_finished").write_text("", encoding="utf-8")

    first = _run_stage(env, input_file, output_dir, "features")

    assert first.returncode == 0, first.stderr
    assert "FRESH" in (result / "query.a3m").read_text(encoding="utf-8")
    assert "FRESH" in (result / "query.pickle").read_text(encoding="utf-8")
    assert not (result / "query.done.txt").exists()
    assert not (result / "query_unrelaxed_rank_001_model_1.pdb").exists()
    assert not (result / "query_coverage.png").exists()
    assert not (result / "config.json").exists()
    assert not (result / "log.txt").exists()
    assert not (result / "interface_scores.json").exists()
    assert not (output_dir / "task_finished").exists()
    marker = result / ".colabfold-msa-complete"
    assert marker.read_text(encoding="utf-8").strip() == _msa_digest(output_dir)

    rerun = _run_stage(env, input_file, output_dir, "features")

    assert rerun.returncode == 0, rerun.stderr
    assert "FRESH" in (result / "query.a3m").read_text(encoding="utf-8")
    assert _calls(env) == ["features", "features"]


def test_colabfold_model_stage_requires_the_features_marker(tmp_path):
    env, input_file, output_dir = _retry_env(tmp_path)
    result = _result_dir(output_dir)
    result.mkdir()
    (result / "query.a3m").write_text(">query\nAAAA\n", encoding="utf-8")
    (result / "query.pickle").write_text("MSA\n", encoding="utf-8")
    (result / "query_unrelaxed_rank_001_model_1.pdb").write_text("STALE\n", encoding="utf-8")
    (result / "query.done.txt").write_text("", encoding="utf-8")
    (output_dir / "task_finished").write_text("", encoding="utf-8")

    model = _run_stage(env, input_file, output_dir, "model")

    assert model.returncode != 0
    assert "MSA is missing" in model.stderr
    assert not (result / "query_unrelaxed_rank_001_model_1.pdb").exists()
    assert not (result / "query.done.txt").exists()
    assert not (output_dir / "task_finished").exists()
    assert _calls(env) == []


@pytest.mark.parametrize("changed", ["query.a3m", "query.pickle"])
def test_colabfold_model_stage_rejects_changed_features(tmp_path, changed):
    env, input_file, output_dir = _retry_env(tmp_path)
    assert _run_stage(env, input_file, output_dir, "features").returncode == 0
    (_result_dir(output_dir) / changed).write_text("CHANGED\n", encoding="utf-8")

    model = _run_stage(env, input_file, output_dir, "model")

    assert model.returncode != 0
    assert "changed after feature validation" in model.stderr
    assert not (_result_dir(output_dir) / "query_unrelaxed_rank_001_model_1.pdb").exists()
    assert not (output_dir / "task_finished").exists()
    assert _calls(env) == ["features"]


def test_colabfold_model_stage_recomputes_instead_of_skipping_on_done_marker(tmp_path):
    env, input_file, output_dir = _retry_env(tmp_path)
    result = _result_dir(output_dir)
    assert _run_stage(env, input_file, output_dir, "features").returncode == 0
    assert _run_stage(env, input_file, output_dir, "model").returncode == 0
    ranked = result / "query_unrelaxed_rank_001_model_1.pdb"
    assert ranked.read_text(encoding="utf-8") == "FRESH\n"
    ranked.write_text("STALE\n", encoding="utf-8")
    assert (result / "query.done.txt").is_file()

    rerun = _run_stage(env, input_file, output_dir, "model")

    assert rerun.returncode == 0, rerun.stderr
    assert ranked.read_text(encoding="utf-8") == "FRESH\n"
    assert _calls(env) == ["features", "model", "model"]
    assert (output_dir / "task_finished").is_file()
    assert (result / "query.a3m").is_file()
    assert (result / "query.pickle").is_file()
    assert (result / ".colabfold-msa-complete").is_file()


def test_colabfold_job_prefix_follows_the_sanitized_fasta_header(tmp_path):
    env, input_file, output_dir = _retry_env(tmp_path)
    input_file.write_text(">my protein\nAAAA\n", encoding="utf-8")
    result = _result_dir(output_dir)
    result.mkdir()
    (result / "my_protein.a3m").write_text("STALE\n", encoding="utf-8")
    (result / "my_protein.pickle").write_text("STALE\n", encoding="utf-8")

    completed = _run_stage(env, input_file, output_dir, "features")

    assert completed.returncode == 0, completed.stderr
    assert "FRESH" in (result / "my_protein.a3m").read_text(encoding="utf-8")
    assert (result / ".colabfold-msa-complete").is_file()


def test_colabfold_missing_output_is_not_masked_by_a_sibling_producer(tmp_path):
    env, input_file, output_dir = _retry_env(tmp_path)
    (output_dir / "sibling.a3m").write_text("SIBLING\n", encoding="utf-8")
    (output_dir / "sibling.pickle").write_text("SIBLING\n", encoding="utf-8")
    env["FAKE_NO_OUTPUT"] = "1"

    features = _run_stage(env, input_file, output_dir, "features")

    assert features.returncode != 0
    assert "produced no MSA" in features.stderr

    env.pop("FAKE_NO_OUTPUT")
    assert _run_stage(env, input_file, output_dir, "features").returncode == 0
    (output_dir / "sibling_unrelaxed_rank_001_model_1.pdb").write_text("SIBLING\n", encoding="utf-8")
    env["FAKE_NO_OUTPUT"] = "1"

    model = _run_stage(env, input_file, output_dir, "model")

    assert model.returncode != 0
    assert "produced no structure" in model.stderr
    assert not (output_dir / "task_finished").exists()
    assert (output_dir / "sibling_unrelaxed_rank_001_model_1.pdb").is_file()


MULTIRECORD_FASTA = (
    ">multirecord_1\nGSHMASMTGGQQMGRDLYDD\n"
    ">multirecord_2\nMKTAYIAKQRQISFVKSHFS\n"
)


def _multirecord_env(tmp_path: Path):
    env, input_file, output_dir = _retry_env(tmp_path)
    input_file.write_text(MULTIRECORD_FASTA, encoding="utf-8")
    return env, input_file, output_dir, ("multirecord_1", "multirecord_2")


def test_colabfold_multirecord_recomputes_every_job(tmp_path):
    env, input_file, output_dir, jobs = _multirecord_env(tmp_path)
    result = _result_dir(output_dir)
    result.mkdir()
    for job in jobs:
        (result / f"{job}.a3m").write_text("STALE\n", encoding="utf-8")
        (result / f"{job}.pickle").write_text("STALE\n", encoding="utf-8")
        (result / f"{job}.done.txt").write_text("", encoding="utf-8")
        (result / f"{job}_unrelaxed_rank_001_model_1.pdb").write_text("STALE\n", encoding="utf-8")
    (output_dir / "task_finished").write_text("", encoding="utf-8")

    features = _run_stage(env, input_file, output_dir, "features")

    assert features.returncode == 0, features.stderr
    for job in jobs:
        assert "FRESH" in (result / f"{job}.a3m").read_text(encoding="utf-8")
        assert "FRESH" in (result / f"{job}.pickle").read_text(encoding="utf-8")
        assert not (result / f"{job}.done.txt").exists()
        assert not (result / f"{job}_unrelaxed_rank_001_model_1.pdb").exists()
    marker = result / ".colabfold-msa-complete"
    assert marker.read_text(encoding="utf-8").strip() == _msa_digest(output_dir, jobs)

    model = _run_stage(env, input_file, output_dir, "model")

    assert model.returncode == 0, model.stderr
    for job in jobs:
        assert (result / f"{job}_unrelaxed_rank_001_model_1.pdb").read_text(encoding="utf-8") == "FRESH\n"
        assert (result / f"{job}.done.txt").is_file()
    assert (output_dir / "task_finished").is_file()
    assert _calls(env) == ["features", "model"]

    for job in jobs:
        (result / f"{job}_unrelaxed_rank_001_model_1.pdb").write_text("STALE\n", encoding="utf-8")
    rerun = _run_stage(env, input_file, output_dir, "model")

    assert rerun.returncode == 0, rerun.stderr
    for job in jobs:
        assert (result / f"{job}_unrelaxed_rank_001_model_1.pdb").read_text(encoding="utf-8") == "FRESH\n"
    assert _calls(env) == ["features", "model", "model"]


def test_colabfold_multirecord_missing_second_job_output_fails(tmp_path):
    env, input_file, output_dir, jobs = _multirecord_env(tmp_path)
    env["FAKE_NO_JOB"] = jobs[1]

    features = _run_stage(env, input_file, output_dir, "features")

    assert features.returncode != 0
    assert "produced no MSA for multirecord_2" in features.stderr
    assert not (_result_dir(output_dir) / ".colabfold-msa-complete").exists()

    env.pop("FAKE_NO_JOB")
    assert _run_stage(env, input_file, output_dir, "features").returncode == 0
    (output_dir / "sibling.txt").write_text("SIBLING\n", encoding="utf-8")
    env["FAKE_NO_JOB"] = jobs[1]

    model = _run_stage(env, input_file, output_dir, "model")

    assert model.returncode != 0
    assert "produced no structure for multirecord_2" in model.stderr
    assert (_result_dir(output_dir) / "multirecord_1_unrelaxed_rank_001_model_1.pdb").is_file()
    assert not (output_dir / "task_finished").exists()
    assert (output_dir / "sibling.txt").read_text(encoding="utf-8") == "SIBLING\n"


def test_colabfold_duplicate_headers_clear_one_prefix_once(tmp_path):
    env, input_file, output_dir = _retry_env(tmp_path)
    input_file.write_text(">same\nAAAA\n>same\nCCCC\n", encoding="utf-8")
    result = _result_dir(output_dir)
    result.mkdir()
    (result / "same.a3m").write_text("STALE\n", encoding="utf-8")
    (result / "same.pickle").write_text("STALE\n", encoding="utf-8")

    completed = _run_stage(env, input_file, output_dir, "features")

    assert completed.returncode == 0, completed.stderr
    assert (result / "same.pickle").read_text(encoding="utf-8") != "STALE\n"
    marker = result / ".colabfold-msa-complete"
    assert marker.read_text(encoding="utf-8").strip() == _msa_digest(output_dir, ("same",))


def test_colabfold_multirecord_result_contract_accepts_one_alignment_per_job(tmp_path):
    from revocompute.result_storyboard import expected_file_tree, resolve_expected_files
    from revocompute.task_runtime import _port_matches, _resolve_result_views

    files = {
        "colabfold/multirecord_1.a3m": ">multirecord_1\nAAAA\n",
        "colabfold/multirecord_2.a3m": ">multirecord_2\nBBBB\n",
        "colabfold/multirecord_1_unrelaxed_rank_001_model_1.pdb": "MODEL\n",
        "colabfold/multirecord_2_unrelaxed_rank_001_model_1.pdb": "MODEL\n",
        "colabfold/multirecord_1_scores_rank_001_model_1.json": '{"plddt":[80.0],"pae":[[1.0]],"ptm":0.8,"max_pae":1.0}\n',
        "colabfold/multirecord_2_scores_rank_001_model_1.json": '{"plddt":[80.0],"pae":[[1.0]],"ptm":0.8,"max_pae":1.0}\n',
        "colabfold/interface_scores.json": '{"ipsae":0.7,"pdockq2":0.4}\n',
    }
    artifacts = []
    for relative_path, content in files.items():
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        artifacts.append({"path": relative_path, "size": path.stat().st_size, "role": "artifact"})

    with isolated_discovery(str(ROOT / "docker/runners"), {"colabfold_af2"}):
        task, _ = get("colabfold_af2")
        views, _, problems = _resolve_result_views(task, artifacts, str(tmp_path))
        logical, _, tree_problems = resolve_expected_files(expected_file_tree(task, str(ROOT)), artifacts)

    assert problems == []
    assert tree_problems == []
    alignment_view = next(view for view in views if view["id"] == "model_alignment")
    assert alignment_view["sources"]["alignment"] == [
        "colabfold/multirecord_1.a3m",
        "colabfold/multirecord_2.a3m",
    ]
    interface_view = next(view for view in views if view["id"] == "interface_confidence")
    assert interface_view["sources"]["data"] == ["colabfold/interface_scores.json"]
    assert len(logical["alignment"]) == 2
    assert [item["path"] for item in logical["interface_scores"]] == ["colabfold/interface_scores.json"]
    assert {item["path"] for item in logical["structures"]} == {
        "colabfold/multirecord_1_unrelaxed_rank_001_model_1.pdb",
        "colabfold/multirecord_2_unrelaxed_rank_001_model_1.pdb",
    }

    # The features port is recursive inside the Runner-owned subtree and does
    # not claim a sibling producer's root-level A3M.
    (tmp_path / "sibling.a3m").write_text(">sibling\nAAAA\n", encoding="utf-8")
    features = next(stage for stage in task.workflow if stage.outputs)
    assert _port_matches(str(tmp_path), features.outputs[0]) == [
        ("colabfold", "multirecord_1.a3m"),
        ("colabfold", "multirecord_2.a3m"),
    ]


def test_colabfold_stages_leave_a_sibling_producers_files_untouched(tmp_path):
    env, input_file, output_dir = _retry_env(tmp_path)
    result = _result_dir(output_dir)
    sibling_dir = output_dir / "other_family"
    sibling_dir.mkdir()
    (sibling_dir / "ranked_0.pdb").write_text("SIBLING\n", encoding="utf-8")
    (output_dir / "sibling_summary.json").write_text("{}\n", encoding="utf-8")
    # A sibling file whose name starts with this job's ColabFold prefix must
    # survive: the clear boundary is the colabfold/ subtree, not the prefix.
    (output_dir / "query_sibling_rank_001.pdb").write_text("SIBLING\n", encoding="utf-8")
    (output_dir / "query_extra_notes.txt").write_text("SIBLING\n", encoding="utf-8")

    assert _run_stage(env, input_file, output_dir, "features").returncode == 0
    assert (sibling_dir / "ranked_0.pdb").read_text(encoding="utf-8") == "SIBLING\n"
    assert (output_dir / "sibling_summary.json").is_file()
    assert (output_dir / "query_sibling_rank_001.pdb").read_text(encoding="utf-8") == "SIBLING\n"
    assert (result / "query.a3m").is_file()
    assert (result / "query.pickle").is_file()

    assert _run_stage(env, input_file, output_dir, "model").returncode == 0
    assert (sibling_dir / "ranked_0.pdb").read_text(encoding="utf-8") == "SIBLING\n"
    assert (output_dir / "sibling_summary.json").is_file()
    assert (output_dir / "query_sibling_rank_001.pdb").read_text(encoding="utf-8") == "SIBLING\n"
    assert (output_dir / "query_extra_notes.txt").read_text(encoding="utf-8") == "SIBLING\n"
    assert (result / "query.a3m").is_file()
    assert (result / "query.pickle").is_file()
    assert (result / "query_unrelaxed_rank_001_model_1.pdb").is_file()
    assert (output_dir / "task_finished").is_file()


def test_colabfold_failed_attempt_publishes_no_stale_output(tmp_path):
    env, input_file, output_dir = _retry_env(tmp_path)
    assert _run_stage(env, input_file, output_dir, "features").returncode == 0
    assert _run_stage(env, input_file, output_dir, "model").returncode == 0

    result = _result_dir(output_dir)
    env["FAKE_FAIL_STAGE"] = "features"
    failed = _run_stage(env, input_file, output_dir, "features")
    assert failed.returncode == 9
    assert not (result / "query.a3m").exists()
    assert not (result / "query.pickle").exists()
    assert not (result / ".colabfold-msa-complete").exists()
    assert not (result / "query.done.txt").exists()
    assert not (result / "query_unrelaxed_rank_001_model_1.pdb").exists()
    assert not (output_dir / "task_finished").exists()

    env.pop("FAKE_FAIL_STAGE")
    assert _run_stage(env, input_file, output_dir, "features").returncode == 0
    assert _run_stage(env, input_file, output_dir, "model").returncode == 0

    env["FAKE_FAIL_STAGE"] = "model"
    failed_model = _run_stage(env, input_file, output_dir, "model")
    assert failed_model.returncode == 9
    assert not (result / "query_unrelaxed_rank_001_model_1.pdb").exists()
    assert not (result / "query.done.txt").exists()
    assert not (output_dir / "task_finished").exists()
    assert (result / "query.a3m").is_file()
    assert (result / ".colabfold-msa-complete").is_file()
