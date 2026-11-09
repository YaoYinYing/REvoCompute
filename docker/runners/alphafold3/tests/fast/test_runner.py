# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest
from revocompute.task_types import get, isolated_discovery
from stage_input_contract import write_server_reuse_document

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
    source = json.loads(Path(values['--json_path']).read_text(encoding='utf-8'))
    processed = {'name': 'Test Job'}
    if 'modelSeeds' in source:
        processed['modelSeeds'] = source['modelSeeds']
    (out / 'test_job_data.json').write_text(json.dumps(processed), encoding='utf-8')
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


def test_features_stage_recomputes_instead_of_reusing_an_existing_tree(tmp_path):
    env, manifest, call_log = _runner_env(tmp_path)
    output = tmp_path / "result"
    assert _run_stage(env, manifest, output, "features").returncode == 0
    assert (output / ".alphafold3-features-complete").is_file()

    rerun = _run_stage(env, manifest, output, "features")

    assert rerun.returncode == 0, rerun.stderr
    assert "REVODESIGN_STAGE:data_pipeline" in rerun.stdout
    assert len(call_log.read_text(encoding="utf-8").splitlines()) == 2


def test_model_stage_recomputes_instead_of_reusing_finished_outputs(tmp_path):
    env, manifest, call_log = _runner_env(tmp_path)
    output = tmp_path / "result"
    assert _run_stage(env, manifest, output, "features").returncode == 0
    assert _run_stage(env, manifest, output, "model").returncode == 0

    rerun = _run_stage(env, manifest, output, "model")

    assert rerun.returncode == 0, rerun.stderr
    assert "REVODESIGN_STAGE:inference" in rerun.stdout
    assert len(call_log.read_text(encoding="utf-8").splitlines()) == 3
    assert (output / "task_finished").is_file()


def _staged_processed_document(
    tmp_path: Path, monkeypatch, content: bytes = b'{"name": "Test Job"}', *, role: str = "prepared_features"
):
    """The document the Server's reuse path writes for the AF3 model input."""
    return write_server_reuse_document(
        tmp_path, monkeypatch, stage="alphafold3.features", role=role,
        port_path="features/*/*_data.json", relative=("test_job", "test_job_data.json"), content=content,
    )


def _stage_inputs_env(env: dict[str, str], document: Path) -> dict[str, str]:
    env.update({
        "TASK_STAGE_INPUTS": str(document),
        "ALPHAFOLD3_STAGE_INPUTS_PY": str(ROOT / "docker" / "runners" / "common" / "runtime" / "stage_inputs.py"),
    })
    return env


def test_model_stage_models_the_verified_staged_processed_json(tmp_path, monkeypatch):
    env, manifest, call_log = _runner_env(tmp_path)
    output = tmp_path / "result"
    document, staged = _staged_processed_document(tmp_path, monkeypatch)
    _stage_inputs_env(env, document)

    model = _run_stage(env, manifest, output, "model")

    assert model.returncode == 0, model.stderr
    materialized = output / "features/test_job/test_job_data.json"
    assert materialized.read_bytes() == staged.read_bytes()
    assert (output / ".alphafold3-features-complete").read_text(encoding="utf-8").strip() == hashlib.sha256(
        staged.read_bytes()
    ).hexdigest()
    calls = [json.loads(line) for line in call_log.read_text(encoding="utf-8").splitlines()]
    assert len(calls) == 1
    assert f"--json_path={materialized}" in calls[0]
    assert (output / "task_finished").is_file()


def test_model_stage_refuses_staged_processed_json_that_changed(tmp_path, monkeypatch):
    env, manifest, call_log = _runner_env(tmp_path)
    output = tmp_path / "result"
    document, staged = _staged_processed_document(tmp_path, monkeypatch)
    staged.write_bytes(b'{"name": "Test Jab"}')
    _stage_inputs_env(env, document)

    model = _run_stage(env, manifest, output, "model")

    assert model.returncode != 0
    assert "digest does not match" in model.stderr
    assert not (output / "features/test_job/test_job_data.json").exists()
    assert not (output / "task_finished").exists()
    assert not call_log.exists()


def test_model_stage_ignores_a_document_without_the_reuse_role(tmp_path, monkeypatch):
    # A full-mode model stage exports a document for its in-graph "features"
    # role. Only the reuse role selects the staged artifact; without it the
    # attempt still requires this Task's own validated feature tree.
    env, manifest, call_log = _runner_env(tmp_path)
    output = tmp_path / "result"
    document, _ = _staged_processed_document(tmp_path, monkeypatch, role="features")
    _stage_inputs_env(env, document)

    model = _run_stage(env, manifest, output, "model")

    assert model.returncode != 0
    assert "Validated AlphaFold 3 processed JSON is missing" in model.stderr
    assert not call_log.exists()
    assert not (output / "task_finished").exists()


def test_full_mode_ignores_a_staged_reuse_document(tmp_path, monkeypatch):
    env, manifest, call_log = _runner_env(tmp_path)
    output = tmp_path / "result"
    document, staged = _staged_processed_document(tmp_path, monkeypatch, content=b'{"name": "Other Task"}', role="features")
    _stage_inputs_env(env, document)

    full = _run_stage(env, manifest, output, "all")

    assert full.returncode == 0, full.stderr
    assert (output / "features/test_job/test_job_data.json").read_bytes() == b'{"name": "Test Job"}'
    assert staged.read_bytes() == b'{"name": "Other Task"}'
    assert len(call_log.read_text(encoding="utf-8").splitlines()) == 2


def test_failed_attempt_publishes_no_output_from_the_previous_one(tmp_path):
    env, manifest, _ = _runner_env(tmp_path)
    output = tmp_path / "result"
    assert _run_stage(env, manifest, output, "features").returncode == 0
    assert _run_stage(env, manifest, output, "model").returncode == 0
    assert (output / "modeling/test_job/test_job_model.cif").is_file()

    # A failed features attempt invalidates the whole task tree: the declared
    # result is the structure, so an earlier attempt's modeling output must not
    # survive it.
    env["AF3_FAIL_STAGE"] = "features"
    failed_features = _run_stage(env, manifest, output, "features")
    assert failed_features.returncode == 9
    assert not (output / "features/test_job/test_job_data.json").exists()
    assert not (output / ".alphafold3-features-complete").exists()
    assert not (output / "modeling/test_job/test_job_model.cif").exists()
    assert not (output / "task_finished").exists()

    env.pop("AF3_FAIL_STAGE")
    assert _run_stage(env, manifest, output, "features").returncode == 0
    assert _run_stage(env, manifest, output, "model").returncode == 0

    env["AF3_FAIL_STAGE"] = "model"
    failed_model = _run_stage(env, manifest, output, "model")
    assert failed_model.returncode == 9
    assert not (output / "task_finished").exists()
    assert not (output / "modeling/test_job/test_job_model.cif").exists()


def test_a_preflight_failure_publishes_no_output_from_the_previous_attempt(tmp_path):
    env, manifest, _ = _runner_env(tmp_path)
    output = tmp_path / "result"
    assert _run_stage(env, manifest, output, "features").returncode == 0
    assert _run_stage(env, manifest, output, "model").returncode == 0
    assert (output / "modeling/test_job/test_job_model.cif").is_file()

    missing_db = {**env, "ALPHAFOLD3_DB_DIR": str(tmp_path / "absent")}
    features = _run_stage(missing_db, manifest, output, "features")
    assert features.returncode != 0
    assert not (output / "modeling/test_job/test_job_model.cif").exists()
    assert not (output / "task_finished").exists()

    assert _run_stage(env, manifest, output, "features").returncode == 0
    assert _run_stage(env, manifest, output, "model").returncode == 0
    low_cpu = {**env, "NPROC": "3"}
    model = _run_stage(low_cpu, manifest, output, "model")
    assert model.returncode != 0
    assert not (output / "modeling/test_job/test_job_model.cif").exists()
    assert not (output / "task_finished").exists()

    assert _run_stage(env, manifest, output, "features").returncode == 0
    assert _run_stage(env, manifest, output, "model").returncode == 0
    missing_manifest = _run_stage(env, tmp_path / "absent.json", output, "features")
    assert missing_manifest.returncode != 0
    assert not (output / "modeling/test_job/test_job_model.cif").exists()
    assert not (output / "task_finished").exists()


def test_model_stage_with_an_invalid_feature_marker_publishes_no_output(tmp_path):
    env, manifest, _ = _runner_env(tmp_path)
    output = tmp_path / "result"
    assert _run_stage(env, manifest, output, "features").returncode == 0
    assert _run_stage(env, manifest, output, "model").returncode == 0
    (output / ".alphafold3-features-complete").write_text("0" * 64, encoding="utf-8")

    tampered = _run_stage(env, manifest, output, "model")

    assert tampered.returncode != 0
    assert "changed after feature validation" in tampered.stderr
    assert not (output / "modeling/test_job/test_job_model.cif").exists()
    assert not (output / "task_finished").exists()


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


def _sequence_runner_env(tmp_path: Path) -> tuple[dict[str, str], Path, Path, Path]:
    env, _, call_log = _runner_env(tmp_path)
    source = tmp_path / "single.fasta"
    source.write_text(">query\nMKTAYIAK\n", encoding="utf-8")
    manifest = tmp_path / "task.json"
    manifest.write_text(
        json.dumps(
            {
                "task_type": "alphafold3_single_sequence",
                "inputs": {"sequence": [{"path": str(source)}]},
                "params": {
                    "model_seed": 23,
                    "num_recycles": 10,
                    "num_diffusion_samples": 2,
                    "save_embeddings": False,
                    "save_distogram": False,
                },
            }
        ),
        encoding="utf-8",
    )
    env["ALPHAFOLD3_SEQUENCE_TO_JSON"] = str(ROOT / "docker/runners/alphafold3/sequence_to_json.py")
    return env, manifest, call_log, source


def _documents(call_log: Path) -> list[list[str]]:
    return [json.loads(line) for line in call_log.read_text(encoding="utf-8").splitlines()]


def test_single_sequence_task_generates_the_upstream_json_and_preserves_the_source(tmp_path):
    env, manifest, call_log, source = _sequence_runner_env(tmp_path)
    output = tmp_path / "result"
    source_bytes = source.read_bytes()

    features = _run_stage(env, manifest, output, "features")

    assert features.returncode == 0, features.stderr
    derived = output / "derived/af3_input.json"
    document = json.loads(derived.read_text(encoding="utf-8"))
    assert document == {
        "name": "single",
        "modelSeeds": [23],
        "sequences": [
            {
                "protein": {
                    "id": "A",
                    "sequence": "MKTAYIAK",
                    "unpairedMsa": "",
                    "pairedMsa": "",
                    "templates": [],
                }
            }
        ],
        "dialect": "alphafold3",
        "version": 1,
    }
    feature_call = _documents(call_log)[0]
    assert f"--json_path={derived}" in feature_call
    assert "--run_data_pipeline=true" in feature_call
    assert "--run_inference=false" in feature_call
    assert "--max_template_date=2021-09-30" in feature_call
    assert "--resolve_msa_overlaps=true" in feature_call
    assert "--fix_standalone_glycans=false" in feature_call
    assert not any(arg.startswith("--conformer_max_iterations") for arg in feature_call)
    assert source.read_bytes() == source_bytes

    model = _run_stage(env, manifest, output, "model")

    assert model.returncode == 0, model.stderr
    model_call = _documents(call_log)[1]
    assert f"--json_path={output}/features/test_job/test_job_data.json" in model_call
    assert "--run_data_pipeline=false" in model_call
    assert "--run_inference=true" in model_call
    assert "--num_diffusion_samples=2" in model_call
    provenance = json.loads((output / "derived/input_provenance.json").read_text(encoding="utf-8"))
    assert provenance["source"] == {"role": "sequence", "sha256": hashlib.sha256(source_bytes).hexdigest()}
    assert provenance["generated"] == {
        "path": "derived/af3_input.json",
        "sha256": hashlib.sha256(derived.read_bytes()).hexdigest(),
    }
    assert provenance["mode"] == "single_sequence_no_msa"
    assert provenance["unpairedMsa"] == provenance["pairedMsa"] == ""
    assert provenance["templates"] == []
    assert provenance["modelSeeds"] == [23]
    assert (output / "task_finished").is_file()
    assert source.read_bytes() == source_bytes


def test_single_sequence_attempt_regenerates_a_stale_derived_input(tmp_path):
    env, manifest, _, _ = _sequence_runner_env(tmp_path)
    output = tmp_path / "result"
    assert _run_stage(env, manifest, output, "features").returncode == 0
    derived = output / "derived/af3_input.json"
    derived.write_text('{"stale": true}', encoding="utf-8")

    env["AF3_FAIL_STAGE"] = "features"
    failed = _run_stage(env, manifest, output, "features")

    assert failed.returncode == 9
    assert json.loads(derived.read_text(encoding="utf-8"))["sequences"][0]["protein"]["sequence"] == "MKTAYIAK"
    assert not (output / "features/test_job/test_job_data.json").exists()
    assert not (output / "task_finished").exists()


def test_single_sequence_model_only_refuses_a_seed_the_prepared_features_did_not_use(tmp_path, monkeypatch):
    env, manifest, call_log, _ = _sequence_runner_env(tmp_path)
    output = tmp_path / "result"
    document, _ = _staged_processed_document(
        tmp_path, monkeypatch, content=b'{"name": "Test Job", "modelSeeds": [23]}'
    )
    _stage_inputs_env(env, document)

    matching = _run_stage(env, manifest, output, "model")
    assert matching.returncode == 0, matching.stderr

    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["params"]["model_seed"] = 9
    manifest.write_text(json.dumps(data), encoding="utf-8")
    mismatch = _run_stage(env, manifest, output, "model")

    assert mismatch.returncode != 0
    assert "modelSeeds=[23]" in mismatch.stderr
    assert "requested model_seed=9" in mismatch.stderr
    assert len(call_log.read_text(encoding="utf-8").splitlines()) == 1
    assert not (output / "task_finished").exists()


def test_alphafold3_tasks_are_discoverable_with_their_contracts():
    with isolated_discovery(str(ROOT / "docker/runners"), {"alphafold3"}):
        normal, _ = get("alphafold3")
        single, _ = get("alphafold3_single_sequence")

    assert normal.name == "alphafold3"
    assert single.display_name == "AlphaFold3 — Single sequence (no MSA)"
    assert single.runtime.access_policy.id == "alphafold3_noncommercial"
    assert [(role.name, role.type) for role in single.inputs] == [("sequence", "single_protein_sequence")]
    assert [param.name for param in single.params] == [
        "model_seed",
        "num_recycles",
        "num_diffusion_samples",
        "save_embeddings",
        "save_distogram",
    ]
    assert single.workflow[1].inputs[0].source == "alphafold3_single_sequence.features:processed_input"
