# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Resolve a Mol-1 task manifest into one confined, writable input tree.

Core validation has already rejected unsafe uploads. This module owns the
runner-side scientific boundary: it copies the specification and its referenced
assets into one tree, rewrites every path field to that copy, enforces the
explicit MSA/template mode, and sizes the system before the checkpoint is
loaded. A path that was not uploaded is an error; upstream would otherwise warn
and silently search the public ColabFold service instead.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from pathlib import Path, PurePosixPath
from typing import Any

from estimate_tokens import CcdAtomCounts, TokenEstimateError, estimate

MODES = {
    "msa_mode": frozenset({"none", "supply", "search"}),
    "template_mode": frozenset({"none", "supply", "search"}),
    "rna_msa_mode": frozenset({"none", "supply"}),
}
PATH_FIELDS = ("pairedMsaPath", "unpairedMsaPath", "templatesPath")
POLYMER_TYPES = frozenset({"proteinChain", "dnaSequence", "rnaSequence"})
# Files this runner writes into the prepared tree; an uploaded asset with one
# of these names would be overwritten or would hide the generated file.
RESERVED_ARTIFACT_NAMES = frozenset(
    {
        "normalized-input.json",
        "provenance.json",
        "normalized-input-update-msa.json",
        "normalized-input-final-updated.json",
    }
)
MAX_SEEDS_LENGTH = 256
MAX_SEED_VALUE = 2**63 - 1
# Mirrors the server result-projection cap (revocompute/result_storyboard.py and
# revocompute/task_runtime.py): more matches fail the output check after inference.
MAX_PROJECTED_MATCHES = 500
_SEEDS = re.compile(r"[0-9]+(,[0-9]+)*")


class PreparationError(ValueError):
    """The task manifest cannot be prepared without guessing."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_path(entity: dict[str, Any]) -> PurePosixPath:
    source = Path(str(entity["path"]))
    raw = str(entity.get("relative_path") or source.name)
    relative = PurePosixPath(raw)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise PreparationError(f"unsafe input relative path: {raw!r}")
    if relative.name in RESERVED_ARTIFACT_NAMES:
        raise PreparationError(
            f"input relative path collides with a Mol-1 generated artifact: {relative.as_posix()!r}"
        )
    return relative


def _load_manifest(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PreparationError(f"Invalid task manifest: {exc}") from exc
    inputs = manifest.get("inputs")
    params = manifest.get("params")
    specification = inputs.get("specification") if isinstance(inputs, dict) else None
    if not isinstance(specification, list) or len(specification) != 1:
        raise PreparationError("Mol-1 requires exactly one specification input")
    if not isinstance(params, dict):
        raise PreparationError("Mol-1 task params must be an object")
    for mode, allowed in MODES.items():
        if params.get(mode) not in allowed:
            raise PreparationError(f"{mode} must be one of {', '.join(sorted(allowed))}")
    return manifest, params


def _copy_inputs(
    manifest: dict[str, Any], destination: Path
) -> tuple[Path, dict[str, Path], dict[str, str], str]:
    inputs = manifest["inputs"]
    entities = list(inputs["specification"]) + list(inputs.get("assets") or [])
    if not all(isinstance(entity, dict) for entity in entities):
        raise PreparationError("Mol-1 input roles contain a malformed entry")
    available: dict[str, Path] = {}
    hashes: dict[str, str] = {}
    specification: Path | None = None
    specification_key: str | None = None
    for role, group in (("specification", inputs["specification"]), ("assets", inputs.get("assets") or [])):
        for entity in group:
            source = Path(str(entity.get("path", "")))
            if not source.is_file():
                raise PreparationError(f"Mol-1 {role} input is missing: {source.name}")
            relative = _relative_path(entity)
            key = relative.as_posix()
            if key in available:
                raise PreparationError(f"duplicate Mol-1 input relative path: {key}")
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            hashes[key] = _sha256(source)
            shutil.copyfile(source, target)
            available[key] = target
            if role == "specification":
                specification = target
                specification_key = key
    assert specification is not None and specification_key is not None
    return specification, available, hashes, specification_key


def _resolve_reference(reference: Any, root: Path, available: dict[str, Path]) -> Path:
    if not isinstance(reference, str):
        raise PreparationError("Mol-1 path references must be strings")
    relative = PurePosixPath(reference)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise PreparationError(f"Mol-1 path reference escapes the input tree: {reference!r}")
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()) or relative.as_posix() not in available or not target.is_file():
        raise PreparationError(f"Mol-1 path reference names no uploaded asset: {reference!r}")
    return target


def _resolve_references(document: list[dict[str, Any]], root: Path, available: dict[str, Path]) -> None:
    for index, job in enumerate(document):
        for entry in job.get("sequences") or []:
            entity_type, entity = next(iter(entry.items()))
            if entity_type in POLYMER_TYPES:
                for field in PATH_FIELDS:
                    if field in entity:
                        entity[field] = str(_resolve_reference(entity[field], root, available))
            elif entity_type == "ligand" and str(entity.get("ligand", "")).startswith("FILE_"):
                reference = entity["ligand"][len("FILE_") :]
                entity["ligand"] = "FILE_" + str(_resolve_reference(reference, root, available))
            elif entity_type not in {"ligand", "ion"}:
                raise PreparationError(f"Mol-1 job {index + 1} has an unsupported entity type")


def _chains(document: list[dict[str, Any]]):
    for job in document:
        for entry in job.get("sequences") or []:
            entity_type, entity = next(iter(entry.items()))
            yield entity_type, entity


def _enforce_modes(document: list[dict[str, Any]], params: dict[str, Any]) -> None:
    msa_mode = params["msa_mode"]
    template_mode = params["template_mode"]
    rna_msa_mode = params["rna_msa_mode"]
    if template_mode == "search" and msa_mode == "none":
        raise PreparationError("template search needs an MSA: set msa_mode to search")
    # Upstream's template search only searches when the MSA directory holds
    # pairing.a3m/non_pairing.a3m, which a supplied MSA never has; it would
    # no-op and verification would fail after the allocation.
    if template_mode == "search" and msa_mode == "supply":
        raise PreparationError(
            "template search needs a searched MSA: use msa_mode 'search', "
            "or supply templates with template_mode 'supply'"
        )
    # Upstream builds every MSA feature only when use_msa is true, and search
    # refuses a supplied RNA MSA, so supply is the only workable MSA mode here.
    if rna_msa_mode == "supply" and msa_mode != "supply":
        raise PreparationError(
            "rna_msa_mode 'supply' needs msa_mode 'supply': upstream reads RNA MSAs only when MSAs are enabled"
        )
    for entity_type, entity in _chains(document):
        if entity_type == "proteinChain":
            supplied = bool(entity.get("pairedMsaPath") or entity.get("unpairedMsaPath"))
            if msa_mode == "supply" and not supplied:
                raise PreparationError(
                    "msa_mode 'supply' requires pairedMsaPath or unpairedMsaPath on every protein chain"
                )
            if msa_mode == "search" and supplied:
                raise PreparationError(
                    "msa_mode 'search' re-searches every protein chain in a job with one missing MSA and "
                    "overwrites supplied MSAs, uploading those protein sequences to the public ColabFold "
                    "MMseqs2 service; supply every MSA with msa_mode 'supply' to keep it private"
                )
            if template_mode == "supply" and not entity.get("templatesPath"):
                raise PreparationError("template_mode 'supply' requires templatesPath on every protein chain")
        elif entity_type == "rnaSequence":
            if msa_mode == "search" and entity.get("unpairedMsaPath"):
                raise PreparationError(
                    "msa_mode 'search' uploads protein sequences to the public ColabFold MMseqs2 service "
                    "and cannot preserve a supplied RNA MSA; use msa_mode 'supply' to keep supplied MSAs private"
                )
            if rna_msa_mode == "supply" and not entity.get("unpairedMsaPath"):
                raise PreparationError("rna_msa_mode 'supply' requires unpairedMsaPath on every RNA chain")


def _seed_list(params: dict[str, Any]) -> list[int]:
    raw = params.get("sample_seeds")
    if not isinstance(raw, str) or len(raw) > MAX_SEEDS_LENGTH or not _SEEDS.fullmatch(raw):
        raise PreparationError(
            f"sample_seeds must be a comma-separated integer list of at most {MAX_SEEDS_LENGTH} characters"
        )
    seeds = [int(value) for value in raw.split(",")]
    if any(seed > MAX_SEED_VALUE for seed in seeds):
        raise PreparationError(f"sample_seeds values must not exceed {MAX_SEED_VALUE}")
    return seeds


def _check_projected_samples(document: list[dict[str, Any]], params: dict[str, Any]) -> None:
    """Refuse work the server's result projection cannot admit."""
    seeds = _seed_list(params)
    samples = params.get("num_samples")
    if isinstance(samples, bool) or not isinstance(samples, int) or samples < 1:
        raise PreparationError("num_samples must be a positive integer")
    projected = len(document) * len(seeds) * samples
    if projected > MAX_PROJECTED_MATCHES:
        raise PreparationError(
            f"Mol-1 would publish {projected} structures, exceeding the server's "
            f"{MAX_PROJECTED_MATCHES}-match result projection limit; reduce the job count, "
            "sample_seeds, or num_samples"
        )


def _token_limit() -> int:
    raw = os.environ.get("MOL1_MAX_TOKENS", "")
    if not raw.isdigit() or int(raw) < 1:
        raise PreparationError("MOL1_MAX_TOKENS must be a positive integer")
    return int(raw)


def _ccd_cache_path() -> Path | None:
    configured = os.environ.get("MOL1_CCD_CACHE")
    if configured:
        return Path(configured)
    root = os.environ.get("MOL_ROOT_DIR")
    return Path(root) / "common/components.cif.rdkit_mol.pkl" if root else None


def prepare(manifest_path: Path, destination: Path) -> Path:
    manifest, params = _load_manifest(manifest_path)
    destination.mkdir(parents=True, exist_ok=True)
    prepared_specification, available, hashes, specification_key = _copy_inputs(manifest, destination)
    try:
        document = json.loads(prepared_specification.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PreparationError(f"Invalid Mol-1 JSON specification: {exc}") from exc
    _enforce_modes(document, params)
    _check_projected_samples(document, params)
    _resolve_references(document, destination, available)
    try:
        token_estimate = estimate(document, CcdAtomCounts(_ccd_cache_path()))
    except TokenEstimateError as exc:
        raise PreparationError(str(exc)) from exc
    limit = _token_limit()
    if token_estimate.total > limit:
        raise PreparationError(
            f"Estimated {token_estimate.total} tokens exceeds the {limit}-token admission bound. "
            "Reduce the system or raise MOL1_MAX_TOKENS after measuring device memory."
        )
    # The uploaded specification copy stays untouched: the normalized document
    # is a separate file, and these hashes are of the user's original bytes,
    # recorded at copy time.
    normalized = destination / "normalized-input.json"
    normalized.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    provenance = {
        "specification": {"name": prepared_specification.name, "sha256": hashes[specification_key]},
        "assets": [
            {"path": relative, "sha256": hashes[relative]}
            for relative in sorted(available)
            if relative != specification_key
        ],
        "token_estimate": {
            "total": token_estimate.total,
            "by_job": token_estimate.by_job,
            "limit": limit,
        },
        "modes": {mode: params[mode] for mode in MODES},
    }
    (destination / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    return normalized


def verify(final_json: Path, *, msa_mode: str, template_mode: str, rna_msa_mode: str) -> None:
    """Refuse a prediction input that would still trigger an upstream search."""
    try:
        document = json.loads(final_json.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PreparationError(f"Invalid prepared Mol-1 JSON: {exc}") from exc
    for entity_type, entity in _chains(document):
        for field in PATH_FIELDS:
            if field in entity and not Path(str(entity[field])).is_file():
                raise PreparationError(f"Prepared Mol-1 path does not exist: {field}")
        if entity_type != "proteinChain":
            if entity_type == "rnaSequence" and rna_msa_mode == "supply" and not Path(
                str(entity.get("unpairedMsaPath", ""))
            ).is_file():
                raise PreparationError("RNA MSA preparation found no unpairedMsaPath")
            continue
        has_msa = any(Path(str(entity.get(field, ""))).is_file() for field in ("pairedMsaPath", "unpairedMsaPath"))
        if msa_mode != "none" and not has_msa:
            raise PreparationError(
                "Protein MSA preparation produced no usable MSA; refusing to let prediction search again"
            )
        if template_mode != "none" and not Path(str(entity.get("templatesPath", ""))).is_file():
            raise PreparationError(
                "Protein template preparation produced no usable templatesPath; refusing to let prediction search again"
            )


def _asset_records(path: Path) -> list[dict[str, str]]:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        digest, _, name = line.partition("  ")
        if digest and name:
            records.append({"path": name, "sha256": digest})
    return records


def finalize(manifest_path: Path, output_dir: Path) -> Path:
    manifest, params = _load_manifest(manifest_path)
    prepared = json.loads((output_dir / "normalized_inputs/provenance.json").read_text(encoding="utf-8"))
    upstream_path = Path(os.environ.get("MOL1_UPSTREAM", "/app/revocompute/upstream.json"))
    model_manifest = Path(os.environ.get("MOL1_MODEL_MANIFEST", "/app/revocompute/model-assets.sha256"))
    search_manifest = Path(os.environ.get("MOL1_SEARCH_MANIFEST", "/app/revocompute/search-assets.sha256"))
    upstream = json.loads(upstream_path.read_text(encoding="utf-8"))
    predictions = output_dir / "predictions"
    structures = sorted(output_dir.glob("*/seed_*/predictions/*_sample_*.cif"))
    summaries = sorted(output_dir.glob("*/seed_*/predictions/*_summary_confidence_sample_*.json"))
    full = sorted(output_dir.glob("*/seed_*/predictions/*_full_data_sample_*.json"))
    provenance = {
        "schema_version": 1,
        "upstream": upstream,
        "parameters": params,
        "prepared_input": prepared,
        "network": {
            "msa_service": upstream.get("msa_service"),
            "template_structure_service": upstream.get("template_structure_service"),
            "msa_mode": params["msa_mode"],
            "template_mode": params["template_mode"],
            "rna_msa_mode": params["rna_msa_mode"],
        },
        "delivered": {
            "structures": len(structures),
            "summaries": len(summaries),
            "full_confidences": len(full),
        },
        "model_assets": _asset_records(model_manifest),
        "search_assets": _asset_records(search_manifest),
    }
    shutil.copyfile(model_manifest, output_dir / "mol1-model-assets.sha256")
    shutil.copyfile(search_manifest, output_dir / "mol1-search-assets.sha256")
    target = output_dir / "mol1-provenance.json"
    target.write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    return target


def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("manifest", type=Path)
    prepare_parser.add_argument("destination", type=Path)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("json", type=Path)
    for mode in MODES:
        verify_parser.add_argument(f"--{mode.replace('_', '-')}", required=True)
    finalize_parser = subparsers.add_parser("finalize")
    finalize_parser.add_argument("manifest", type=Path)
    finalize_parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            print(prepare(args.manifest, args.destination))
        elif args.command == "verify":
            verify(
                args.json,
                msa_mode=args.msa_mode,
                template_mode=args.template_mode,
                rna_msa_mode=args.rna_msa_mode,
            )
        else:
            print(finalize(args.manifest, args.output_dir))
    except PreparationError as exc:
        raise SystemExit(f"Mol-1 input preparation failed: {exc}") from exc


if __name__ == "__main__":
    _main()
