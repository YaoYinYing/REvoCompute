# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Per-work-item validation and provenance for the SimpleFold plugin.

One SimpleFold work item owns one output directory, so the checks that used to
run once over a whole task output now run over one item's directory, and the
run provenance is written per item. Nothing here touches the model or the GPU.
"""

from __future__ import annotations

import json
from pathlib import Path

UPSTREAM_REVISION = "c7a5570a6be9f5c695126e27c804e77567209934"
ESM_REVISION = "2b369911bb5b4b0dda914521b9475cad1656b2ac"
ASSET_SHA256 = {
    "simplefold_1.6B.ckpt": "aaac2d73dcc59c61153c58a1d56e74a8ada9d6057d67000f7836f3c87325312b",
    "simplefold_3B.ckpt": "88d4c7a240bf3815cb35342b4ddc1128ac243a2ea0256eb8a4df1209125868b5",
    "plddt.ckpt": "cb32fa9cdc9e80406b793a8c09a929077534d9991a1d08f4c159d2e4ed81315f",
    "ccd.pkl": "2d3b2f03a3c5665944adba51e33263511e51b21c9cd05d902f9c4b7c1e58d2f4",
}
#: Upstream writes the processed-input manifest as ``manifest.json``; the item
#: keeps it under the name the result contract declares.
INPUT_MANIFEST_NAME = "simplefold_input_manifest.json"
CONFIDENCE_DIR_NAME = "confidence"
RECORDS_DIR_NAME = "records"


def structure_suffix(output_format: str) -> str:
    return ".cif" if output_format == "mmcif" else ".pdb"


def structure_paths(work_dir: Path, output_format: str) -> list[Path]:
    return sorted(Path(work_dir).glob(f"predictions_*/*_sampled_*{structure_suffix(output_format)}"))


def confidence_paths(work_dir: Path) -> list[Path]:
    return sorted((Path(work_dir) / CONFIDENCE_DIR_NAME).glob("*.json"))


def promote_input_manifest(work_dir: Path) -> None:
    """Rename upstream's ``manifest.json`` into the declared artifact name."""
    source = Path(work_dir) / "manifest.json"
    if source.is_file():
        source.replace(Path(work_dir) / INPUT_MANIFEST_NAME)


def asset_sha256(model: str, predict_plddt: bool, esm_model_sha256: str, esm_regression_sha256: str) -> dict[str, str]:
    assets = {
        f"{model}.ckpt": ASSET_SHA256[f"{model}.ckpt"],
        "ccd.pkl": ASSET_SHA256["ccd.pkl"],
        "esm2_t36_3B_UR50D.pt": esm_model_sha256,
        "esm2_t36_3B_UR50D-contact-regression.pt": esm_regression_sha256,
    }
    if predict_plddt:
        assets["simplefold_1.6B.ckpt"] = ASSET_SHA256["simplefold_1.6B.ckpt"]
        assets["plddt.ckpt"] = ASSET_SHA256["plddt.ckpt"]
    return assets


def build_run_metadata(
    *,
    work_dir: Path,
    model: str,
    parameters: dict,
    item: dict,
    effective_seed: int,
    plan: dict,
    runtime_fingerprint: str,
    esm_model_sha256: str,
    esm_regression_sha256: str,
) -> dict:
    """Assemble one item's provenance: requested parameters and effective plan.

    ``parameters`` is what the user requested and never changes; ``plan`` is the
    execution-only adaptation that actually ran, with the per-sample effective
    seeds, so a split sample group is inspectable rather than silent.
    """
    work_dir = Path(work_dir)
    predict_plddt = bool(parameters["predict_plddt"])
    return {
        "runner": "simplefold",
        "upstream_revision": UPSTREAM_REVISION,
        "esm_revision": ESM_REVISION,
        "model": model,
        "runtime_fingerprint": runtime_fingerprint,
        "item": dict(item),
        "parameters": dict(parameters),
        "effective": {
            "seed": int(effective_seed),
            "plan_label": str(plan.get("label") or ""),
            "plan_title": str(plan.get("title") or ""),
            "sample_group_size": int(plan["sample_group_size"]),
            "sample_groups": [int(size) for size in plan["sample_groups"]],
            "sample_seeds": [int(seed) for seed in plan["sample_seeds"]],
            "unapplied_adjustments": dict(plan.get("unapplied") or {}),
        },
        "asset_sha256": asset_sha256(model, predict_plddt, esm_model_sha256, esm_regression_sha256),
        "structures": [
            str(path.relative_to(work_dir)) for path in structure_paths(work_dir, parameters["output_format"])
        ],
        "confidence": [str(path.relative_to(work_dir)) for path in confidence_paths(work_dir)],
    }


def write_run_metadata(work_dir: Path, metadata: dict) -> None:
    (Path(work_dir) / "run_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


def validate_item_outputs(work_dir: Path, *, num_samples: int, predict_plddt: bool, output_format: str) -> None:
    """Fail closed when one item's artifacts do not match the requested science."""
    work_dir = Path(work_dir)
    structures = structure_paths(work_dir, output_format)
    if len(structures) != num_samples:
        raise ValueError(f"SimpleFold produced {len(structures)} structures; expected {num_samples}")
    if any(path.stat().st_size == 0 for path in structures):
        raise ValueError("SimpleFold produced an empty structure file")
    confidence = confidence_paths(work_dir)
    if predict_plddt and len(confidence) != num_samples:
        raise ValueError(f"SimpleFold produced {len(confidence)} confidence files; expected {num_samples}")
    if not predict_plddt and confidence:
        raise ValueError("SimpleFold produced confidence artifacts although pLDDT was disabled")
    if not (work_dir / INPUT_MANIFEST_NAME).is_file() or not any(
        (work_dir / RECORDS_DIR_NAME).glob("*.json")
    ):
        raise ValueError("SimpleFold did not preserve its processed-input manifest and record")
    if not (work_dir / "run_metadata.json").is_file():
        raise ValueError("SimpleFold did not write its run provenance")
