# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Public result-manifest contracts for folding runner storyboards."""

from __future__ import annotations

import json

from test_scientific_result_protocols import _finalize


def test_colabfold_publishes_storyboard_logical_files(monkeypatch, tmp_path) -> None:
    manifest = _finalize(
        monkeypatch,
        tmp_path,
        "colabfold_af2",
        "colabfold_af2",
        {
            "job_relaxed_rank_001_model_1_seed_000.pdb": "MODEL        1\nENDMDL\n",
            "job_scores_rank_001_model_1_seed_000.json": json.dumps(
                {"plddt": [90], "ptm": 0.8, "max_pae": 1, "pae": [[1]]}
            ),
            "job.a3m": "#1\t1\n>query\nA\n",
        },
    )

    assert manifest["output_check"]["state"] == "passed", manifest["output_check"]
    assert manifest["storyboard"] == {
        "identifier": "colabfold-af2-result",
        "entrypoint": "index.js",
        "requires": ["structures", "scores", "alignment"],
        "optional": ["interface_scores"],
    }
    assert {key: len(value) for key, value in manifest["result"]["files"].items()} == {
        "structures": 1,
        "scores": 1,
        "alignment": 1,
        "interface_scores": 0,
    }


def test_opendde_publishes_full_confidence_only_as_optional_storyboard_data(monkeypatch, tmp_path) -> None:
    manifest = _finalize(
        monkeypatch,
        tmp_path,
        "opendde",
        "opendde",
        {
            "job/seed_101/predictions/job_sample_0.cif": "data_job\n#\n",
            "job/seed_101/predictions/job_summary_confidence_sample_0.json": json.dumps(
                {
                    "plddt": 90,
                    "gpde": 0.5,
                    "ptm": 0.8,
                    "iptm": 0.7,
                    "ranking_score": 0.7,
                    "has_clash": False,
                }
            ),
            "job/seed_101/predictions/job_full_data_sample_0.json": json.dumps({"token_pair_pae": [[1]]}),
        },
    )

    assert manifest["output_check"]["state"] == "passed", manifest["output_check"]
    assert manifest["storyboard"]["identifier"] == "opendde-result"
    assert manifest["storyboard"]["requires"] == ["structures", "summaries"]
    assert manifest["storyboard"]["optional"] == ["full_confidences"]
    assert len(manifest["result"]["files"]["full_confidences"]) == 1


def test_esmfold2_publishes_candidate_matched_storyboard_files(monkeypatch, tmp_path) -> None:
    manifest = _finalize(
        monkeypatch,
        tmp_path,
        "esmfold2_predict",
        "esmfold2",
        {
            "mini/sample_001.cif": "data_prediction\n#\n",
            "mini/sample_001_confidence.json": json.dumps(
                {"mean_plddt": 0.8, "ptm": 0.7, "iptm": None}
            ),
            "mini/sample_001_plddt.csv": "token_index,plddt\n1,0.8\n",
            "mini/sample_001_pae.json": json.dumps({"pae": [[1.0]]}),
            "mini/prediction.json": json.dumps({"sample_count": 1}),
        },
    )

    assert manifest["output_check"]["state"] == "passed", manifest["output_check"]
    assert manifest["storyboard"]["identifier"] == "esmfold2-result"
    assert all(len(manifest["result"]["files"][key]) == 1 for key in ("structures", "summaries", "local_confidence", "pae"))


def test_boltz_publishes_optional_pairwise_arrays(monkeypatch, tmp_path) -> None:
    root = "boltz_results_job/predictions/job"
    manifest = _finalize(
        monkeypatch,
        tmp_path,
        "boltz_predict",
        "boltz",
        {
            f"{root}/job_model_0.cif": "data_prediction\n#\n",
            f"{root}/confidence_job_model_0.json": json.dumps(
                {"confidence_score": 0.8, "ptm": 0.7, "iptm": 0.6, "complex_plddt": 0.9, "complex_pde": 1.2}
            ),
            f"{root}/plddt_job_model_0.npz": b"npz",
            f"{root}/pae_job_model_0.npz": b"npz",
            "boltz_results_job/processed/manifest.json": "{}",
            "boltz-model-assets.sha256": "hash  asset\n",
        },
    )

    assert manifest["output_check"]["state"] == "passed", manifest["output_check"]
    assert manifest["storyboard"]["identifier"] == "boltz-result"
    assert len(manifest["result"]["files"]["pae"]) == 1
    assert manifest["result"]["files"]["pde"] == []


def test_chai_publishes_all_ranked_ndarray_evidence(monkeypatch, tmp_path) -> None:
    manifest = _finalize(
        monkeypatch,
        tmp_path,
        "chai1_predict",
        "chai1",
        {
            "ranked/rank_0.model_idx_0.cif": "data_prediction\n#\n",
            "confidence.rank_0.json": json.dumps(
                {"aggregate_score": 0.8, "ptm": 0.7, "iptm": 0.6, "has_inter_chain_clashes": False}
            ),
            "plddt.rank_0.npy": b"npy",
            "pae.rank_0.npy": b"npy",
            "pde.rank_0.npy": b"npy",
            "ranking.json": "[]",
            "run_metadata.json": "{}",
            "chai1-model-assets.json": "{}",
        },
    )

    assert manifest["output_check"]["state"] == "passed", manifest["output_check"]
    assert manifest["storyboard"]["identifier"] == "chai1-result"
    assert all(len(manifest["result"]["files"][key]) == 1 for key in ("structures", "summaries", "local_confidence", "pae", "pde"))


def test_alphafold2_publishes_ranking_needed_to_join_ranked_evidence(monkeypatch, tmp_path) -> None:
    manifest = _finalize(
        monkeypatch,
        tmp_path,
        "alphafold",
        "alphafold",
        {
            "mini/ranked_0.pdb": "MODEL        1\nENDMDL\n",
            "mini/confidence_model_2_ptm_pred_0.json": json.dumps(
                {"confidenceScore": [90.0], "confidenceCategory": ["H"], "residueNumber": [1]}
            ),
            "mini/pae_model_2_ptm_pred_0.json": json.dumps([{"predicted_aligned_error": [[1.0]]}]),
            "mini/ranking_debug.json": json.dumps({"order": ["model_2_ptm_pred_0"]}),
        },
    )

    assert manifest["output_check"]["state"] == "passed", manifest["output_check"]
    assert manifest["storyboard"] == {
        "identifier": "alphafold2-result",
        "entrypoint": "index.js",
        "requires": ["structures", "confidences", "ranking"],
        "optional": ["pae"],
    }
    assert len(manifest["result"]["files"]["ranking"]) == 1
    pae = manifest["result"]["files"]["pae"][0]
    assert pae["path"] == "mini/pae_model_2_ptm_pred_0.json"


def test_simplefold_publishes_structure_format_and_optional_matching_confidence(monkeypatch, tmp_path) -> None:
    manifest = _finalize(
        monkeypatch,
        tmp_path,
        "simplefold_predict",
        "simplefold",
        {
            "mini/predictions_simplefold_1.6B/mini_sampled_0.cif": "data_prediction\n#\n",
            "mini/confidence/mini_sampled_0.json": json.dumps(
                {"confidenceScore": [80.0, 90.0], "meanPlddt": 85.0}
            ),
        },
    )

    assert manifest["output_check"]["state"] == "passed", manifest["output_check"]
    assert manifest["storyboard"]["identifier"] == "simplefold-result"
    assert len(manifest["result"]["files"]["structures_cif"]) == 1
    assert manifest["result"]["files"]["structures_pdb"] == []
    assert len(manifest["result"]["files"]["confidences"]) == 1


def test_foundry_rf3_publishes_exact_seed_sample_evidence_without_top_level_duplicates(monkeypatch, tmp_path) -> None:
    root = "minimal_rf3/seed-13_sample-1/minimal_rf3_seed-13_sample-1"
    manifest = _finalize(
        monkeypatch,
        tmp_path,
        "foundry_rf3_fold",
        "foundry",
        {
            f"{root}_model.cif": "data_prediction\n#\n",
            f"{root}_summary_confidences.json": json.dumps(
                {
                    "overall_plddt": 0.8,
                    "overall_pae": 2.0,
                    "overall_pde": 1.0,
                    "ptm": 0.7,
                    "iptm": 0.0,
                    "ranking_score": 0.7,
                    "has_clash": False,
                }
            ),
            f"{root}_confidences.json": json.dumps({"atom_plddts": [0.8], "pae": [[1.0]]}),
            "minimal_rf3/minimal_rf3_ranking_scores.csv": "seed,sample,ranking_score\n13,1,0.7\n",
            "minimal_rf3/minimal_rf3_model.cif": "data_selected_duplicate\n#\n",
            "minimal_rf3/minimal_rf3_confidences.json": json.dumps({"atom_plddts": [0.8]}),
            "foundry-run.json": json.dumps({"task_type": "foundry_rf3_fold", "model": "rf3"}),
            "foundry-model-assets.json": json.dumps({"schema_version": 1}),
        },
    )

    assert manifest["output_check"]["state"] == "passed", manifest["output_check"]
    assert manifest["storyboard"]["identifier"] == "foundry-rf3-result"
    assert len(manifest["result"]["files"]["structures"]) == 1
    assert len(manifest["result"]["files"]["summaries"]) == 1
    assert len(manifest["result"]["files"]["confidences"]) == 1


def test_foundry_rf3_early_stop_contract_does_not_require_a_structure(monkeypatch, tmp_path) -> None:
    manifest = _finalize(
        monkeypatch,
        tmp_path,
        "foundry_rf3_fold",
        "foundry",
        {
            "minimal_rf3/minimal_rf3_ranking_scores.csv": "early_stopped\ntrue\n",
            "foundry-run.json": json.dumps({"task_type": "foundry_rf3_fold", "model": "rf3"}),
            "foundry-model-assets.json": json.dumps({"schema_version": 1}),
        },
    )

    assert manifest["output_check"]["state"] == "passed", manifest["output_check"]
    assert manifest["result"]["files"]["structures"] == []
    assert len(manifest["result"]["files"]["rankings"]) == 1


def test_fpocket_publishes_the_structure_aware_storyboard_contract(monkeypatch, tmp_path) -> None:
    """The integration contract: the logical files the storyboard binds to resolve.

    fpocket is a third-party binary, so this asserts only that REvoCompute
    publishes the declared identities for the artifacts it parses (see
    docker/runners/fpocket/INTEGRATION.md), not that the pocket values are
    scientifically correct.
    """
    manifest = _finalize(
        monkeypatch,
        tmp_path,
        "fpocket",
        "fpocket",
        {
            # The full column set the task's entity-table mapping requires.
            "pockets.csv": (
                "pocket,rank,score,druggability_score,alpha_spheres,mean_alpha_sphere_radius_angstrom,"
                "total_sasa_angstrom2,apolar_sasa_angstrom2,polar_sasa_angstrom2,volume_angstrom3,"
                "hydrophobicity_score,volume_score,polarity_score,charge_score,apolar_alpha_sphere_proportion,"
                "center_x,center_y,center_z,residue_count,residue_ids,atom_count\n"
                "pocket1,1,0.63,0.75,38,3.9,10.0,5.0,5.0,250.0,20.0,4.0,3.0,0.0,0.9,1.0,2.0,3.0,1,A_101,2\n"
            ),
            "summary.json": json.dumps({"pocket_count": 1, "ranking_order": "descending"}),
            "fpocket-run.json": json.dumps({"task_type": "fpocket"}),
            "work/1SUO_out/1SUO_info.txt": "Pocket 1 :\n\tScore: 0.63\n",
            "work/1SUO_out/pockets/pocket1_atm.pdb": "ATOM      1  CA  ALA A 101       0.0   0.0   0.0  1.00  0.00           C\n",
            "work/1SUO_out/pockets/pocket1_vert.pqr": "ATOM      1   APOL   C  1      0.0   0.0   0.0  1.00  0.00     1.0\n",
        },
    )

    assert manifest["output_check"]["state"] == "passed", manifest["output_check"]
    assert manifest["storyboard"] == {
        "identifier": "fpocket-result",
        "entrypoint": "index.js",
        "requires": ["pockets"],
        "optional": [
            "protein_structure",
            "detection_summary",
            "run_record",
            "pocket_contacts",
            "pocket_alpha_spheres",
        ],
    }
    files = manifest["result"]["files"]
    assert len(files["pockets"]) == 1
    assert len(files["pocket_contacts"]) == 1
    assert len(files["pocket_alpha_spheres"]) == 1
    # The bound pockets.csv is the primary table source the task declares.
    assert files["pockets"][0]["path"] == "pockets.csv"
