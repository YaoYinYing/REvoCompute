#!/usr/bin/env python3
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

UPSTREAM_COMMIT = "2475421477ab414b571149ad4a875c390ff8a35d"
UPSTREAM_VERSION = "2.0.0"
MODEL_NAME = "protenix-v2"
MODEL_SOURCE = "https://protenix.tos-cn-beijing.volces.com/checkpoint/protenix-v2.pt"
COMMON_SOURCES = {
    "common/components.cif": "https://protenix.tos-cn-beijing.volces.com/common/components.cif",
    "common/components.cif.rdkit_mol.pkl": (
        "https://protenix.tos-cn-beijing.volces.com/common/components.cif.rdkit_mol.pkl"
    ),
    "common/clusters-by-entity-40.txt": (
        "https://protenix.tos-cn-beijing.volces.com/common/clusters-by-entity-40.txt"
    ),
    "common/obsolete_release_date.csv": (
        "https://protenix.tos-cn-beijing.volces.com/common/obsolete_release_date.csv"
    ),
}
TEMPLATE_SOURCES = {
    "common/obsolete_to_successor.json": (
        "https://protenix.tos-cn-beijing.volces.com/common/obsolete_to_successor.json"
    ),
    "common/release_date_cache.json": "https://protenix.tos-cn-beijing.volces.com/common/release_date_cache.json",
}
PATH_FIELDS = ("pairedMsaPath", "unpairedMsaPath", "templatesPath")
PRIMARY_EXTENSIONS = frozenset({".json"})
ATTACHMENT_EXTENSIONS = frozenset({".a3m", ".hhr", ".sdf", ".mol", ".mol2", ".pdb"})
PROTEIN_ALPHABET = frozenset("ACDEFGHIKLMNPQRSTVWYX")
DNA_ALPHABET = frozenset("ATGCN")
RNA_ALPHABET = frozenset("AUGCN")
MAX_TOTAL_POLYMER_TOKENS = 2048
SAFE_JOB_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _().-]{0,127}$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_bool(params: dict[str, Any], key: str) -> bool:
    value = params.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"Resolved task parameter {key!r} must be a boolean")
    return value


def _require_int(params: dict[str, Any], key: str) -> int:
    value = params.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Resolved task parameter {key!r} must be an integer")
    return value


def read_task_manifest(manifest_path: Path) -> tuple[Path, list[Path], dict[str, Any]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw_files = manifest.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise ValueError("Task manifest must contain one Protenix JSON input")
    paths: list[Path] = []
    for item in raw_files:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise ValueError("Every task file must have a string path")
        path = Path(item["path"]).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Protenix task input not found: {path}")
        paths.append(path)
    if paths[0].suffix.lower() not in PRIMARY_EXTENSIONS:
        raise ValueError("The primary Protenix input must be a JSON file")
    for path in paths[1:]:
        if path.suffix.lower() not in ATTACHMENT_EXTENSIONS:
            raise ValueError(f"Unsupported Protenix attachment type: {path.name}")
    params = manifest.get("params")
    if not isinstance(params, dict):
        raise ValueError("Task manifest must contain resolved Protenix parameters")
    return paths[0], paths[1:], params


def _resolve_uploaded_reference(value: Any, attachments: list[Path], field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"Protenix {field} must be a non-empty uploaded-file reference")
    if "://" in value or value.startswith("data:"):
        raise ValueError(f"Protenix {field} cannot reference a URL")
    reference = Path(value)
    if ".." in reference.parts:
        raise ValueError(f"Protenix {field} cannot contain parent-directory traversal")
    candidates = [path for path in attachments if path == reference]
    if not candidates:
        reference_parts = tuple(part for part in reference.parts if part not in (reference.anchor, "."))
        candidates = [
            path
            for path in attachments
            if len(path.parts) >= len(reference_parts) and tuple(path.parts[-len(reference_parts) :]) == reference_parts
        ]
    if not candidates:
        candidates = [path for path in attachments if path.name == reference.name]
    if len(candidates) == 0:
        raise ValueError(f"Protenix {field} references an unuploaded file: {value}")
    if len(candidates) > 1:
        raise ValueError(f"Protenix {field} is ambiguous across uploaded files: {value}")
    return str(candidates[0])


def _validate_polymer(entity_name: str, entity: dict[str, Any], alphabet: frozenset[str]) -> int:
    sequence = entity.get("sequence")
    if not isinstance(sequence, str) or not sequence:
        raise ValueError(f"Protenix {entity_name} requires a non-empty sequence")
    normalized = sequence.upper()
    invalid = sorted(set(normalized) - alphabet)
    if invalid:
        raise ValueError(f"Protenix {entity_name} contains unsupported residues: {''.join(invalid)}")
    entity["sequence"] = normalized
    count = entity.get("count", 1)
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 16:
        raise ValueError(f"Protenix {entity_name} count must be an integer from 1 through 16")
    return len(normalized) * count


def normalize_input(
    input_path: Path,
    attachments: list[Path],
    params: dict[str, Any],
    output_path: Path,
) -> dict[str, Any]:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise ValueError("A Protenix task must contain exactly one system in its top-level JSON list")
    job = copy.deepcopy(payload[0])
    name = job.get("name")
    if not isinstance(name, str) or not SAFE_JOB_NAME.fullmatch(name):
        raise ValueError(
            "Protenix job name must contain 1-128 letters, numbers, spaces, dots, underscores, parentheses, or hyphens"
        )
    sequences = job.get("sequences")
    if not isinstance(sequences, list) or not 1 <= len(sequences) <= 64:
        raise ValueError("Protenix sequences must contain between 1 and 64 entities")

    use_msa = _require_bool(params, "use_msa")
    use_templates = _require_bool(params, "use_templates")
    use_rna_msa = _require_bool(params, "use_rna_msa")
    total_polymer_tokens = 0
    protein_count = 0
    rna_count = 0
    template_count = 0
    for item in sequences:
        if not isinstance(item, dict) or len(item) != 1:
            raise ValueError("Every Protenix sequence entry must contain exactly one entity type")
        entity_name, entity = next(iter(item.items()))
        if not isinstance(entity, dict):
            raise ValueError(f"Protenix {entity_name} entity must be an object")
        if entity_name == "proteinChain":
            protein_count += 1
            total_polymer_tokens += _validate_polymer(entity_name, entity, PROTEIN_ALPHABET)
            if "msa" in entity:
                raise ValueError("The deprecated Protenix msa object is unsupported; upload A3M files explicitly")
            for field in PATH_FIELDS:
                if field in entity:
                    entity[field] = _resolve_uploaded_reference(entity[field], attachments, field)
            if use_msa and not (entity.get("pairedMsaPath") or entity.get("unpairedMsaPath")):
                raise ValueError("use_msa requires an uploaded pairedMsaPath or unpairedMsaPath for every protein")
            if entity.get("templatesPath"):
                template_count += 1
        elif entity_name == "dnaSequence":
            total_polymer_tokens += _validate_polymer(entity_name, entity, DNA_ALPHABET)
        elif entity_name == "rnaSequence":
            rna_count += 1
            total_polymer_tokens += _validate_polymer(entity_name, entity, RNA_ALPHABET)
            if "unpairedMsaPath" in entity:
                entity["unpairedMsaPath"] = _resolve_uploaded_reference(
                    entity["unpairedMsaPath"], attachments, "unpairedMsaPath"
                )
            if use_rna_msa and not entity.get("unpairedMsaPath"):
                raise ValueError("use_rna_msa requires an uploaded unpairedMsaPath for every RNA entity")
        elif entity_name == "ligand":
            ligand = entity.get("ligand")
            if not isinstance(ligand, str) or not ligand:
                raise ValueError("Protenix ligand requires a CCD code, SMILES string, or uploaded FILE_ reference")
            if ligand.startswith("FILE_"):
                entity["ligand"] = "FILE_" + _resolve_uploaded_reference(
                    ligand.removeprefix("FILE_"), attachments, "ligand"
                )
            count = entity.get("count", 1)
            if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 16:
                raise ValueError("Protenix ligand count must be an integer from 1 through 16")
        elif entity_name == "ion":
            ion = entity.get("ion")
            count = entity.get("count", 1)
            if not isinstance(ion, str) or not ion or isinstance(count, bool) or not isinstance(count, int):
                raise ValueError("Protenix ion requires a code and integer count")
            if not 1 <= count <= 16:
                raise ValueError("Protenix ion count must be from 1 through 16")
        else:
            raise ValueError(f"Unsupported Protenix entity type: {entity_name}")

    if total_polymer_tokens > MAX_TOTAL_POLYMER_TOKENS:
        raise ValueError(f"Protenix input exceeds the {MAX_TOTAL_POLYMER_TOKENS}-polymer-token service limit")
    if use_msa and protein_count == 0:
        raise ValueError("use_msa requires at least one proteinChain")
    if use_templates and (protein_count == 0 or template_count == 0):
        raise ValueError("use_templates requires an uploaded templatesPath on at least one proteinChain")
    if use_rna_msa and rna_count == 0:
        raise ValueError("use_rna_msa requires at least one rnaSequence")
    if _require_bool(params, "use_tfg_guidance") and not isinstance(job.get("constraint"), dict):
        raise ValueError("use_tfg_guidance requires a constraint object in the Protenix JSON")

    normalized = [job]
    output_path.write_text(json.dumps(normalized, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return job


def validate_assets(asset_root: Path, use_templates: bool) -> dict[str, Any]:
    manifest_path = asset_root / "assets.json"
    required_sources = {f"checkpoint/{MODEL_NAME}.pt": MODEL_SOURCE, **COMMON_SOURCES}
    if use_templates:
        required_sources.update(TEMPLATE_SOURCES)
    missing = [str(asset_root / relative) for relative in required_sources if not (asset_root / relative).is_file()]
    if not manifest_path.is_file():
        missing.append(str(manifest_path))
    if missing:
        raise FileNotFoundError("Protenix assets are incomplete; missing: " + ", ".join(missing))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("upstream_commit") != UPSTREAM_COMMIT or manifest.get("model_name") != MODEL_NAME:
        raise ValueError("Protenix asset manifest does not match the pinned source and model revision")
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise ValueError("Protenix asset manifest has no file inventory")
    for relative, source_url in required_sources.items():
        record = files.get(relative)
        if not isinstance(record, dict) or record.get("source_url") != source_url:
            raise ValueError(f"Protenix asset manifest has an unexpected source for {relative}")
        size = record.get("size")
        checksum = record.get("sha256")
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            raise ValueError(f"Protenix asset manifest has an invalid size for {relative}")
        if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
            raise ValueError(f"Protenix asset manifest has an invalid SHA-256 for {relative}")
        path = asset_root / relative
        if path.stat().st_size != size:
            raise ValueError(f"Protenix asset has an unexpected size: {relative}")
        if sha256(path) != checksum:
            raise ValueError(f"Protenix asset failed SHA-256 verification: {relative}")
    return manifest


def upstream_kwargs(params: dict[str, Any], normalized_input: Path, output_dir: Path) -> dict[str, Any]:
    seed = _require_int(params, "seed")
    num_seeds = _require_int(params, "num_seeds")
    return {
        "json_file": str(normalized_input),
        "out_dir": str(output_dir),
        "use_msa": _require_bool(params, "use_msa"),
        "seeds": list(range(seed, seed + num_seeds)),
        "n_cycle": _require_int(params, "num_cycles"),
        "n_step": _require_int(params, "diffusion_steps"),
        "n_sample": _require_int(params, "samples_per_seed"),
        "dtype": "bf16",
        "model_name": MODEL_NAME,
        "trimul_kernel": params["triangle_multiplicative_kernel"],
        "triatt_kernel": params["triangle_attention_kernel"],
        "enable_cache": _require_bool(params, "enable_shared_cache"),
        "enable_fusion": _require_bool(params, "enable_fusion"),
        "enable_tf32": _require_bool(params, "enable_tf32"),
        "use_template": _require_bool(params, "use_templates"),
        "use_rna_msa": _require_bool(params, "use_rna_msa"),
        "use_seeds_in_json": False,
        "need_atom_confidence": _require_bool(params, "include_atom_confidence"),
        "use_tfg_guidance": _require_bool(params, "use_tfg_guidance"),
    }


def run(args: argparse.Namespace) -> None:
    input_path, attachments, params = read_task_manifest(args.task_manifest)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    normalized_input = args.output_dir / "normalized_input.json"
    job = normalize_input(input_path, attachments, params, normalized_input)
    asset_manifest = validate_assets(args.asset_root, _require_bool(params, "use_templates"))

    os.environ["PROTENIX_ROOT_DIR"] = str(args.asset_root)
    from runner import batch_inference

    def offline_assets(_configs: Any) -> None:
        # Assets were fully verified before importing the upstream runner. Its
        # downloader must never write to the read-only production namespace.
        return None

    def offline_preprocess(input_json: str, **_kwargs: Any) -> str:
        return input_json

    batch_inference.download_inference_cache = offline_assets
    batch_inference.preprocess_input = offline_preprocess
    batch_inference.inference_jsons(**upstream_kwargs(params, normalized_input, args.output_dir))

    error_files = [path for path in (args.output_dir / "ERR").glob("*") if path.is_file()]
    if error_files:
        raise RuntimeError("Protenix inference reported an error: " + error_files[0].read_text(encoding="utf-8"))
    structures = sorted(args.output_dir.glob("*/*/*_sample_*.cif"))
    confidence = sorted(args.output_dir.glob("*/*/*_summary_confidence_sample_*.json"))
    if not structures or not confidence:
        raise RuntimeError("Protenix inference produced no complete structure/confidence result pair")
    provenance = {
        "runner": "protenix",
        "task_type": "protenix_predict",
        "upstream": {
            "repository": "https://github.com/bytedance/Protenix",
            "commit": UPSTREAM_COMMIT,
            "version": UPSTREAM_VERSION,
            "model": MODEL_NAME,
        },
        "input": {"name": job["name"], "sha256": sha256(normalized_input)},
        "parameters": params,
        "assets": asset_manifest,
        "artifacts": {
            "structures": [str(path.relative_to(args.output_dir)) for path in structures],
            "confidence": [str(path.relative_to(args.output_dir)) for path in confidence],
        },
    }
    (args.output_dir / "prediction.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run pinned Protenix-v2 inference with provisioned assets only.")
    parser.add_argument("--task-manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--asset-root", required=True, type=Path)
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
