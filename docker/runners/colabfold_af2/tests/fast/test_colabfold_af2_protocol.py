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

def _msa_digest(output_dir: Path, job: str = "query") -> str:
    """Mirror run.sh's digest of this job's a3m and pickle cache."""
    lines = []
    for suffix in (".a3m", ".pickle"):
        path = output_dir / f"{job}{suffix}"
        if path.is_file():
            lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n")
    return hashlib.sha256("".join(lines).encode()).hexdigest()


def _seed_features(output_dir: Path, job: str = "query") -> None:
    """Write the features output and digest marker a features stage publishes."""
    (output_dir / f"{job}.a3m").write_text(f">query\nAAAA\n>hit\nAAAA\n", encoding="utf-8")
    (output_dir / f"{job}.pickle").write_text("MSA\n", encoding="utf-8")
    (output_dir / ".colabfold-msa-complete").write_text(_msa_digest(output_dir, job), encoding="utf-8")


def _write_fake_colabfold(tmp_path: Path) -> Path:
    executable = tmp_path / "colabfold_batch"
    executable.write_text(
        "#!/bin/bash\n"
        "set -e\n"
        'printf "%s\\n" "$@" > "$FAKE_ARGS_FILE"\n'
        'if [[ " $* " == *" --msa-only "* ]]; then printf "features\\n" >> "$FAKE_CALL_LOG"; '
        'else printf "model\\n" >> "$FAKE_CALL_LOG"; fi\n'
        "output_dir=${@: -1}\n"
        "fasta=${@: -2:1}\n"
        'job=$(sed -n "1s/^>//p" "$fasta" | sed "s/[^[:alnum:]_.-]/_/g")\n'
        'if [[ -n "${FAKE_FAIL_STAGE:-}" ]]; then\n'
        '  [[ "$FAKE_FAIL_STAGE" == features && " $* " == *" --msa-only "* ]] && exit 9\n'
        '  [[ "$FAKE_FAIL_STAGE" == model && " $* " != *" --msa-only "* ]] && exit 9\n'
        "fi\n"
        'if [[ "${FAKE_NO_OUTPUT:-}" == "1" ]]; then exit 0; fi\n'
        'if [[ -f "$output_dir/${job}.done.txt" ]]; then\n'
        '  echo "Skipping ${job} (already done)" >&2\n'
        "  exit 0\n"
        "fi\n"
        'if [[ " $* " == *" --msa-only "* ]]; then\n'
        '  if [[ -f "$output_dir/${job}.pickle" ]]; then src=REUSED; else src=FRESH; fi\n'
        '  printf ">query\\nAAAA\\n%s\\n" "$src" > "$output_dir/${job}.a3m"\n'
        '  printf "%s\\n" "$src" > "$output_dir/${job}.pickle"\n'
        "else\n"
        '  [[ -s "$output_dir/${job}.pickle" ]] || { echo "missing MSA cache" >&2; exit 7; }\n'
        '  if [[ -f "$output_dir/${job}_unrelaxed_rank_001_model_1.pdb" ]]; then src=REUSED; else src=FRESH; fi\n'
        '  printf "%s\\n" "$src" > "$output_dir/${job}_unrelaxed_rank_001_model_1.pdb"\n'
        '  if [[ "${FAKE_INTERFACE_SCORES:-no}" == "yes" ]]; then\n'
        '    printf \'{"ptm":0.8,"ipsae":{"A-B":0.61,"A-C":0.74},"pdockq2":{"A-B":0.71,"A-C":0.42}}\\n\''
        ' > "$output_dir/${job}_scores_rank_001_model_1.json"\n'
        "  fi\n"
        '  printf "done\\n" > "$output_dir/${job}.done.txt"\n'
        "fi\n",
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
    assert (output_dir / ".colabfold-msa-complete").is_file()
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
    summary = json.loads((output_dir / "interface_scores.json").read_text(encoding="utf-8"))
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
    assert not (output_dir / "interface_scores.json").exists()
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


def test_colabfold_features_recomputes_and_clears_a_previous_tree(tmp_path):
    env, input_file, output_dir = _retry_env(tmp_path)
    (output_dir / "query.a3m").write_text("STALE\n", encoding="utf-8")
    (output_dir / "query.pickle").write_text("STALE\n", encoding="utf-8")
    (output_dir / "query.done.txt").write_text("", encoding="utf-8")
    (output_dir / "query_unrelaxed_rank_001_model_1.pdb").write_text("STALE\n", encoding="utf-8")
    (output_dir / "query_coverage.png").write_text("STALE\n", encoding="utf-8")
    (output_dir / "config.json").write_text("STALE\n", encoding="utf-8")
    (output_dir / "log.txt").write_text("STALE\n", encoding="utf-8")
    (output_dir / "interface_scores.json").write_text("{}\n", encoding="utf-8")
    (output_dir / "task_finished").write_text("", encoding="utf-8")

    first = _run_stage(env, input_file, output_dir, "features")

    assert first.returncode == 0, first.stderr
    assert "FRESH" in (output_dir / "query.a3m").read_text(encoding="utf-8")
    assert "FRESH" in (output_dir / "query.pickle").read_text(encoding="utf-8")
    assert not (output_dir / "query.done.txt").exists()
    assert not (output_dir / "query_unrelaxed_rank_001_model_1.pdb").exists()
    assert not (output_dir / "query_coverage.png").exists()
    assert not (output_dir / "config.json").exists()
    assert not (output_dir / "log.txt").exists()
    assert not (output_dir / "interface_scores.json").exists()
    assert not (output_dir / "task_finished").exists()
    marker = output_dir / ".colabfold-msa-complete"
    assert marker.read_text(encoding="utf-8").strip() == _msa_digest(output_dir)

    rerun = _run_stage(env, input_file, output_dir, "features")

    assert rerun.returncode == 0, rerun.stderr
    assert "FRESH" in (output_dir / "query.a3m").read_text(encoding="utf-8")
    assert _calls(env) == ["features", "features"]


def test_colabfold_model_stage_requires_the_features_marker(tmp_path):
    env, input_file, output_dir = _retry_env(tmp_path)
    (output_dir / "query.a3m").write_text(">query\nAAAA\n", encoding="utf-8")
    (output_dir / "query.pickle").write_text("MSA\n", encoding="utf-8")
    (output_dir / "query_unrelaxed_rank_001_model_1.pdb").write_text("STALE\n", encoding="utf-8")
    (output_dir / "query.done.txt").write_text("", encoding="utf-8")
    (output_dir / "task_finished").write_text("", encoding="utf-8")

    model = _run_stage(env, input_file, output_dir, "model")

    assert model.returncode != 0
    assert "MSA is missing" in model.stderr
    assert not (output_dir / "query_unrelaxed_rank_001_model_1.pdb").exists()
    assert not (output_dir / "query.done.txt").exists()
    assert not (output_dir / "task_finished").exists()
    assert _calls(env) == []


@pytest.mark.parametrize("changed", ["query.a3m", "query.pickle"])
def test_colabfold_model_stage_rejects_changed_features(tmp_path, changed):
    env, input_file, output_dir = _retry_env(tmp_path)
    assert _run_stage(env, input_file, output_dir, "features").returncode == 0
    (output_dir / changed).write_text("CHANGED\n", encoding="utf-8")

    model = _run_stage(env, input_file, output_dir, "model")

    assert model.returncode != 0
    assert "changed after feature validation" in model.stderr
    assert not (output_dir / "query_unrelaxed_rank_001_model_1.pdb").exists()
    assert not (output_dir / "task_finished").exists()
    assert _calls(env) == ["features"]


def test_colabfold_model_stage_recomputes_instead_of_skipping_on_done_marker(tmp_path):
    env, input_file, output_dir = _retry_env(tmp_path)
    assert _run_stage(env, input_file, output_dir, "features").returncode == 0
    assert _run_stage(env, input_file, output_dir, "model").returncode == 0
    ranked = output_dir / "query_unrelaxed_rank_001_model_1.pdb"
    assert ranked.read_text(encoding="utf-8") == "FRESH\n"
    ranked.write_text("STALE\n", encoding="utf-8")
    assert (output_dir / "query.done.txt").is_file()

    rerun = _run_stage(env, input_file, output_dir, "model")

    assert rerun.returncode == 0, rerun.stderr
    assert ranked.read_text(encoding="utf-8") == "FRESH\n"
    assert _calls(env) == ["features", "model", "model"]
    assert (output_dir / "task_finished").is_file()
    assert (output_dir / "query.a3m").is_file()
    assert (output_dir / "query.pickle").is_file()
    assert (output_dir / ".colabfold-msa-complete").is_file()


def test_colabfold_job_prefix_follows_the_sanitized_fasta_header(tmp_path):
    env, input_file, output_dir = _retry_env(tmp_path)
    input_file.write_text(">my protein\nAAAA\n", encoding="utf-8")
    (output_dir / "my_protein.a3m").write_text("STALE\n", encoding="utf-8")
    (output_dir / "my_protein.pickle").write_text("STALE\n", encoding="utf-8")

    completed = _run_stage(env, input_file, output_dir, "features")

    assert completed.returncode == 0, completed.stderr
    assert "FRESH" in (output_dir / "my_protein.a3m").read_text(encoding="utf-8")
    assert (output_dir / ".colabfold-msa-complete").is_file()


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


def test_colabfold_stages_leave_a_sibling_producers_files_untouched(tmp_path):
    env, input_file, output_dir = _retry_env(tmp_path)
    sibling_dir = output_dir / "other_family"
    sibling_dir.mkdir()
    (sibling_dir / "ranked_0.pdb").write_text("SIBLING\n", encoding="utf-8")
    (output_dir / "sibling_summary.json").write_text("{}\n", encoding="utf-8")

    assert _run_stage(env, input_file, output_dir, "features").returncode == 0
    assert (sibling_dir / "ranked_0.pdb").read_text(encoding="utf-8") == "SIBLING\n"
    assert (output_dir / "sibling_summary.json").is_file()

    assert _run_stage(env, input_file, output_dir, "model").returncode == 0
    assert (sibling_dir / "ranked_0.pdb").read_text(encoding="utf-8") == "SIBLING\n"
    assert (output_dir / "sibling_summary.json").is_file()
    assert (output_dir / "query.a3m").is_file()
    assert (output_dir / "query.pickle").is_file()


def test_colabfold_failed_attempt_publishes_no_stale_output(tmp_path):
    env, input_file, output_dir = _retry_env(tmp_path)
    assert _run_stage(env, input_file, output_dir, "features").returncode == 0
    assert _run_stage(env, input_file, output_dir, "model").returncode == 0

    env["FAKE_FAIL_STAGE"] = "features"
    failed = _run_stage(env, input_file, output_dir, "features")
    assert failed.returncode == 9
    assert not (output_dir / "query.a3m").exists()
    assert not (output_dir / "query.pickle").exists()
    assert not (output_dir / ".colabfold-msa-complete").exists()
    assert not (output_dir / "query.done.txt").exists()
    assert not (output_dir / "query_unrelaxed_rank_001_model_1.pdb").exists()
    assert not (output_dir / "task_finished").exists()

    env.pop("FAKE_FAIL_STAGE")
    assert _run_stage(env, input_file, output_dir, "features").returncode == 0
    assert _run_stage(env, input_file, output_dir, "model").returncode == 0

    env["FAKE_FAIL_STAGE"] = "model"
    failed_model = _run_stage(env, input_file, output_dir, "model")
    assert failed_model.returncode == 9
    assert not (output_dir / "query_unrelaxed_rank_001_model_1.pdb").exists()
    assert not (output_dir / "query.done.txt").exists()
    assert not (output_dir / "task_finished").exists()
    assert (output_dir / "query.a3m").is_file()
    assert (output_dir / ".colabfold-msa-complete").is_file()
