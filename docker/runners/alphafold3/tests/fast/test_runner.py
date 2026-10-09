# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from revocompute.task_types import get, isolated_discovery

ROOT = Path(__file__).resolve().parents[5]
RUNNER = ROOT / "docker/runners/alphafold3/run.sh"


def test_alphafold3_result_workspace_resolves_representative_outputs(monkeypatch, tmp_path):
    files = {
        "modeling/test_job/test_job_model.cif": "data_test_job",
        "modeling/test_job/test_job_ranking_scores.csv": "seed,sample,ranking_score\n1,0,0.9\n",
        "modeling/test_job/test_job_confidences.json": '{"pae": []}',
        "modeling/test_job/test_job_summary_confidences.json": (
            '{"ptm":0.9,"iptm":null,"ranking_score":0.9,'
            '"fraction_disordered":0.1,"has_clash":0}'
        ),
        "modeling/test_job/TERMS_OF_USE.md": "terms",
        "features/test_job/test_job_data.json": '{"name":"Test Job"}',
    }
    artifacts = []
    for relative_path, content in files.items():
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        artifacts.append({"path": relative_path, "size": path.stat().st_size, "role": "artifact"})

    from revocompute.task_runtime import _resolve_result_views

    with isolated_discovery(str(ROOT / "docker/runners"), {"alphafold3"}):
        af3, _ = get("alphafold3")
        views, checks, problems = _resolve_result_views(af3, artifacts, str(tmp_path))

    assert problems == []
    assert all(check["status"] == "passed" for check in checks)
    by_id = {view["id"]: view for view in views}
    assert by_id["predicted_structures"]["sources"]["candidates"] == [
        "modeling/test_job/test_job_model.cif"
    ]
    assert next(field for field in by_id["confidence_summary"]["mapping"]["fields"] if field["path"] == "iptm")[
        "nullable"
    ] is True
    assert "features/test_job/test_job_data.json" in by_id["prediction_data"]["sources"]["items"]




def _write_fake_af3(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
values = {arg.split('=', 1)[0]: arg.split('=', 1)[1] for arg in args if arg.startswith('--') and '=' in arg}
with open(os.environ['AF3_CALL_LOG'], 'a', encoding='utf-8') as handle:
    handle.write(json.dumps(args) + '\\n')
stage = 'features' if '--run_data_pipeline=true' in args else 'model'
if os.environ.get('AF3_FAIL_STAGE') == stage:
    raise SystemExit(9)
out = Path(values['--output_dir']) / 'test_job'
out.mkdir(parents=True)
if stage == 'features':
    (out / 'test_job_data.json').write_text('{\"name\": \"Test Job\"}', encoding='utf-8')
else:
    if not values['--json_path'].endswith('/features/test_job/test_job_data.json'):
        raise SystemExit(8)
    (out / 'test_job_ranking_scores.csv').write_text('seed,sample,ranking_score\\n1,0,0.9\\n', encoding='utf-8')
    (out / 'test_job_confidences.json').write_text('{\"pae\": []}', encoding='utf-8')
    (out / 'test_job_summary_confidences.json').write_text('{\"ptm\": 0.9, \"iptm\": 0.8, \"ranking_score\": 0.9, \"fraction_disordered\": 0.1, \"has_clash\": 0}', encoding='utf-8')
    (out / 'TERMS_OF_USE.md').write_text('terms', encoding='utf-8')
    if os.environ.get('AF3_NO_STRUCTURE') != '1':
        (out / 'test_job_model.cif').write_text('data_test_job', encoding='utf-8')
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _runner_env(tmp_path: Path) -> tuple[dict[str, str], Path, Path]:
    fake = tmp_path / "fake_af3.py"
    _write_fake_af3(fake)
    db_dir = tmp_path / "databases"
    db_dir.mkdir()
    reduced = tmp_path / "reduced_bfd.fasta"
    reduced.write_text(">x\nACDE\n", encoding="utf-8")
    models = tmp_path / "models"
    models.mkdir()
    (models / "af3.bin.zst").write_bytes(b"weights-placeholder")
    user_input = tmp_path / "input.json"
    user_input.write_text('{"name":"Test Job"}', encoding="utf-8")
    manifest = tmp_path / "task.json"
    manifest.write_text(
        json.dumps(
            {
                "inputs": {"specification": [{"path": str(user_input)}]},
                "params": {
                    "max_template_date": "2021-09-30",
                    "resolve_msa_overlaps": True,
                    "fix_standalone_glycans": False,
                    "num_recycles": 10,
                    "num_diffusion_samples": 7,
                    "save_embeddings": False,
                    "save_distogram": False,
                },
            }
        ),
        encoding="utf-8",
    )
    call_log = tmp_path / "calls.jsonl"
    env = {
        **os.environ,
        "TASK_MANIFEST": str(manifest),
        "TASK_CONTEXT_SRC": str(ROOT / "docker/runners/common/runtime/task_context.sh"),
        "ALPHAFOLD3_PYTHON": "python3",
        "ALPHAFOLD3_SCRIPT": str(fake),
        "ALPHAFOLD3_DB_DIR": str(db_dir),
        "ALPHAFOLD3_SMALL_BFD_PATH": str(reduced),
        "ALPHAFOLD3_MODEL_DIR": str(models),
        "AF3_CALL_LOG": str(call_log),
    }
    return env, manifest, call_log


def _run_stage(env: dict[str, str], manifest: Path, output: Path, stage: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(RUNNER), "-i", str(manifest), "-o", str(output), "-s", stage],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_alphafold3_wrapper_composes_stages_and_hands_off_processed_json(tmp_path):
    env, manifest, call_log = _runner_env(tmp_path)
    output = tmp_path / "result"

    features = _run_stage(env, manifest, output, "features")
    assert features.returncode == 0, features.stderr
    assert "REVODESIGN_STAGE:data_pipeline" in features.stdout
    assert "REVODESIGN_STAGE:feature_validation" in features.stdout
    assert "REVODESIGN_STAGE:inference" not in features.stdout
    assert not (output / "task_finished").exists()
    model = _run_stage(env, manifest, output, "model")
    assert model.returncode == 0, model.stderr
    assert "REVODESIGN_STAGE:inference" in model.stdout
    assert "REVODESIGN_STAGE:output_validation" in model.stdout
    assert "REVODESIGN_STAGE:data_pipeline" not in model.stdout
    assert (output / "task_finished").is_file()

    calls = [json.loads(line) for line in call_log.read_text(encoding="utf-8").splitlines()]
    assert "--run_data_pipeline=true" in calls[0]
    assert "--run_inference=false" in calls[0]
    assert f"--db_dir={env['ALPHAFOLD3_DB_DIR']}" in calls[0]
    assert "--run_data_pipeline=false" in calls[1]
    assert "--run_inference=true" in calls[1]
    assert f"--model_dir={env['ALPHAFOLD3_MODEL_DIR']}" in calls[1]
    assert "--num_diffusion_samples=7" in calls[1]
    assert any(arg.endswith("/features/test_job/test_job_data.json") for arg in calls[1])


@pytest.mark.parametrize(
    ("nproc", "jackhmmer", "nhmmer", "hmmsearch"),
    [(8, 2, 2, 8), (16, 4, 5, 8), (32, 8, 8, 8), (128, 8, 8, 8)],
)
def test_alphafold3_runner_translates_total_cpu_budget(tmp_path, nproc, jackhmmer, nhmmer, hmmsearch):
    env, manifest, call_log = _runner_env(tmp_path)
    env["NPROC"] = str(nproc)
    completed = _run_stage(env, manifest, tmp_path / "result", "features")

    assert completed.returncode == 0, completed.stderr
    args = json.loads(call_log.read_text(encoding="utf-8").splitlines()[0])
    assert f"--jackhmmer_n_cpu={jackhmmer}" in args
    assert f"--nhmmer_n_cpu={nhmmer}" in args
    assert f"--hmmsearch_n_cpu={hmmsearch}" in args
    assert "--jackhmmer_max_parallel_shards=1" in args
    assert "--nhmmer_max_parallel_shards=1" in args


@pytest.mark.parametrize("nproc", ["1", "3", "invalid"])
def test_alphafold3_runner_rejects_insufficient_or_invalid_cpu_budget(tmp_path, nproc):
    env, manifest, call_log = _runner_env(tmp_path)
    env["NPROC"] = nproc
    completed = _run_stage(env, manifest, tmp_path / "result", "features")

    assert completed.returncode != 0
    assert not call_log.exists()
    assert "NPROC" in completed.stderr


def test_alphafold3_wrapper_rejects_missing_or_modified_processed_json(tmp_path):
    env, manifest, call_log = _runner_env(tmp_path)
    output = tmp_path / "result"
    missing = _run_stage(env, manifest, output, "model")
    assert missing.returncode != 0
    assert "processed JSON is missing" in missing.stderr
    assert not call_log.exists()

    assert _run_stage(env, manifest, output, "features").returncode == 0
    processed = output / "features/test_job/test_job_data.json"
    processed.write_text('{"changed":true}', encoding="utf-8")
    modified = _run_stage(env, manifest, output, "model")
    assert modified.returncode != 0
    assert "changed after feature validation" in modified.stderr
    assert len(call_log.read_text(encoding="utf-8").splitlines()) == 1
    assert not (output / "task_finished").exists()


def test_alphafold3_wrapper_propagates_upstream_failure_and_validates_structure(tmp_path):
    env, manifest, _ = _runner_env(tmp_path)
    output = tmp_path / "failed"
    env["AF3_FAIL_STAGE"] = "features"
    failed = _run_stage(env, manifest, output, "features")
    assert failed.returncode == 9
    assert not (output / "task_finished").exists()

    env.pop("AF3_FAIL_STAGE")
    recovered = _run_stage(env, manifest, output, "features")
    assert recovered.returncode == 0, recovered.stderr
    assert (output / ".alphafold3-features-complete").is_file()
    output = tmp_path / "missing-structure"
    assert _run_stage(env, manifest, output, "features").returncode == 0
    env["AF3_NO_STRUCTURE"] = "1"
    model = _run_stage(env, manifest, output, "model")
    assert model.returncode != 0
    assert "no expected mmCIF" in model.stderr
    assert not (output / "task_finished").exists()
    env.pop("AF3_NO_STRUCTURE")
    recovered_model = _run_stage(env, manifest, output, "model")
    assert recovered_model.returncode == 0, recovered_model.stderr
    assert (output / "task_finished").is_file()
