#!/usr/bin/env python3
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""ESMFold 2 as a persistent multi-item Runner plugin.

Upstream folds one ``StructurePredictionInput`` per call, so a FASTA with many
records is one uninterruptible process. This module splits that loop and lets
the shared :mod:`persistent_runner` lifecycle own it: the assets are verified
and the model plus CUDA context load **once per task** in
:meth:`ESMFold2Plugin.initialize_runtime`, each FASTA *record* is one work item
folded by :meth:`run_item` into its own private directory, and
:meth:`finalize` releases the runtime.

The requested science is fixed before any adaptation runs: model variant,
``num_loops``, ``num_sampling_steps``, ``num_diffusion_samples``, ``seed``, the
LM knobs, and embedding capture are copied once from the task manifest and never
changed. A declared fallback may only change *how* the requested samples are
drawn — a smaller ``sample_group_size``, the ``reference`` kernel backend, or a
CUDA cache clear — and still produces exactly the requested number of samples,
one file per sample. ``fold`` restores the RNG on exit, so re-seeding identical
groups would return identical structures: consecutive groups take the stream seed
``seed + group index`` and every effective group and sample seed is recorded in
``prediction.json``, so a split run is inspectable rather than silent.

Resource measurements come from the framework that owns the GPU allocations
(``torch.cuda``); the plugin reports them and the server owns the estimator.
"""

from __future__ import annotations

import argparse
import csv
import gc
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from persistent_runner import OUTCOME_OOM, OUTCOME_SUCCESS, execute_task  # noqa: E402
from work_items import InputError, build_config, read_task_manifest  # noqa: E402

UPSTREAM_COMMIT = "bf343ba264b650dff7a073643725f9aaa1fdbe8d"
UPSTREAM_VERSION = "3.4.1"
MODEL_REVISIONS = {
    "standard": "8fc3ff471022fdce52c77030685eb775de0c00a3",
    "fast": "c6c7958d63f5f2f1f0fed0bb9462316f8ccceea6",
}
ESMC_REVISION = "45b0fa5d7fb06faefbd5e3b89bdcef35d564e79a"
MODEL_REQUIRED_FILES = ("config.json", "model.safetensors")
ESMC_REQUIRED_FILES = (
    "config.json",
    "model.safetensors.index.json",
    "model-00001-of-00006.safetensors",
    "model-00002-of-00006.safetensors",
    "model-00003-of-00006.safetensors",
    "model-00004-of-00006.safetensors",
    "model-00005-of-00006.safetensors",
    "model-00006-of-00006.safetensors",
)
ASSET_SPECS = {
    "ccd.pkl": (417306584, "9ff44b1927c6b9198e38ffe0928706827a09a350c15530beeeabebfa88038fc5"),
    "standard/config.json": (2337, "e9ec2496ec433a1dce18627ed4bf3785b4ce0c1d69e4bb4663dad1ab895da012"),
    "standard/model.safetensors": (
        939505228,
        "138fd4350d6892b81ce6be7ff9bf5a93ae9d4d3751f46a27438a3f9f0dcefa0e",
    ),
    "fast/config.json": (2338, "d24456b797ddcfb60ac6c53621b550db5e14b1575ee2d9ab5a380eb5b09902f2"),
    "fast/model.safetensors": (
        755416924,
        "60ca19f2898188beba92944365f7b909efd9c99212f5018af75cc47cd9a6184a",
    ),
    "esmc-6b/config.json": (341, "c5566fab6a17fd674141331fe75de917b7904d99fb7a410d2b1593c21e576913"),
    "esmc-6b/model.safetensors.index.json": (
        97349,
        "6846456e20e6ee2c37461f7bfc21d316d69bdaf165b925691afcb39e583244da",
    ),
    "esmc-6b/model-00001-of-00006.safetensors": (
        4864457920,
        "bd90149ff223e6ac1a0cac6147a5ae0df20d3a21df4f65356a1f19cd14f4aa8a",
    ),
    "esmc-6b/model-00002-of-00006.safetensors": (
        4971211344,
        "f75e2144d8269fe2eb4b3e0823fb089b94f176d8024153e85b8fb573a42294fa",
    ),
    "esmc-6b/model-00003-of-00006.safetensors": (
        4863752992,
        "f699f01ecc9691d9c6470492765fe54b8b5d2e9f277c139e89427433ffdfe0b2",
    ),
    "esmc-6b/model-00004-of-00006.safetensors": (
        4971211344,
        "46add1b7be098bbfdc3073884851ba3057f1b33ea23a158b650a37007dabd13d",
    ),
    "esmc-6b/model-00005-of-00006.safetensors": (
        4863752992,
        "1e1cb62f060a34e18f54a31a76683ef888b8cec59e73315f5b31d25d45a1f88c",
    ),
    "esmc-6b/model-00006-of-00006.safetensors": (
        873762296,
        "56c73e13ae96e777ce65eee99364056069ef93b646470f352f83c5f1037b1b18",
    ),
}
VALID_AMINO_ACIDS = frozenset("ACDEFGHIKLMNPQRSTVWYX")
#: One work item is one chain, so the residue limit applies per FASTA record
#: rather than to the file total: a task may legitimately carry many records.
MAX_TOTAL_RESIDUES = 1024
SEQUENCE_EXTENSIONS = (".fasta", ".fa", ".faa")
KERNEL_BACKENDS = ("reference", "cuequivariance")
#: User settings this plugin requires from the owning task manifest.
REQUIRED_PARAMS = (
    "model_variant",
    "num_loops",
    "num_sampling_steps",
    "num_diffusion_samples",
    "seed",
    "lm_dropout",
    "lm_mask_pct",
    "msa_max_depth",
    "msa_column_mask_rate",
    "kernel_backend",
    "include_embeddings",
)
#: Execution-only keys a fallback may name (mirror of the server's adaptation
#: vocabulary). Anything else — a sample count, a seed, a model or sampling
#: parameter — is scientific and is rejected at manifest load.
RESOURCE_ADJUSTMENT_KEYS = frozenset(
    {"sample_group_size", "batch_size", "token_budget", "chunk_size", "cpu_offload", "kernel_backend", "cache_clear"}
)
#: The subset this plugin realizes. A declared plan may not name more than this:
#: the planner only offers what the manifest declares, so a declaration the
#: implementation cannot honour would be a silent no-op.
#:
#: ``batch_size`` is deliberately absent. One work item is one chain, so "how
#: many chains of one item are folded together" can only ever be 1: a plan that
#: named it would advertise a reduction this runner cannot deliver.
SUPPORTED_ADJUSTMENTS = frozenset({"sample_group_size", "kernel_backend", "cache_clear"})


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_fasta(path: Path) -> list[tuple[str, str]]:
    """Read non-aligned protein FASTA records, preserving header order.

    A record identifier becomes an output directory name, so duplicates are
    rejected here rather than colliding later.
    """
    records: list[tuple[str, str]] = []
    header: str | None = None
    sequence: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(">"):
            if header is not None:
                records.append((header, "".join(sequence)))
            header = line[1:].strip().split()[0] if line[1:].strip() else f"chain_{len(records) + 1}"
            sequence = []
        elif header is None:
            raise ValueError("FASTA sequence data appears before its header")
        else:
            sequence.append(line)
    if header is not None:
        records.append((header, "".join(sequence)))
    if not records:
        raise ValueError("Protein FASTA contains no records")
    seen: set[str] = set()
    normalized: list[tuple[str, str]] = []
    for index, (name, sequence_text) in enumerate(records, start=1):
        chain_id = name or f"chain_{index}"
        if chain_id in seen:
            raise ValueError(f"Protein FASTA contains duplicate record id: {chain_id}")
        seen.add(chain_id)
        sequence_text = sequence_text.replace(" ", "").upper().rstrip("*_")
        if not sequence_text:
            raise ValueError(f"Protein FASTA record {chain_id!r} is empty")
        invalid = sorted(set(sequence_text) - VALID_AMINO_ACIDS)
        if invalid:
            raise ValueError(f"Protein FASTA record {chain_id!r} contains unsupported residues: {''.join(invalid)}")
        if len(sequence_text) > MAX_TOTAL_RESIDUES:
            raise ValueError(
                f"Protein FASTA record {chain_id!r} has {len(sequence_text)} residues; "
                f"the supported maximum is {MAX_TOTAL_RESIDUES}"
            )
        normalized.append((chain_id, sequence_text))
    return normalized


def manifest_paths(manifest: dict) -> tuple[Path, Path | None]:
    """Validate the declared input roles and return their filesystem paths.

    The optional A3M is a task-level input rather than a user parameter, so it is
    read from the role the owning manifest declares — the immutable snapshot is
    the only source of truth for it, which is why the runner takes no path for it.
    """
    inputs = manifest.get("inputs")
    if not isinstance(inputs, dict) or len(inputs.get("sequence", ())) != 1:
        raise ValueError("Task manifest must contain exactly one sequence input")
    fasta = Path(inputs["sequence"][0]["path"])
    if fasta.suffix.lower() not in SEQUENCE_EXTENSIONS:
        raise ValueError("The primary ESMFold 2 input must be a FASTA file")
    if not fasta.is_file():
        raise FileNotFoundError(f"Protein FASTA not found: {fasta}")
    alignments = inputs.get("alignment", [])
    if not isinstance(alignments, list) or len(alignments) > 1:
        raise ValueError("ESMFold 2 accepts at most one optional alignment")
    msa = Path(alignments[0]["path"]) if alignments else None
    if msa is not None and (msa.suffix.lower() != ".a3m" or not msa.is_file()):
        raise ValueError("The optional second ESMFold 2 input must be an existing A3M file")
    return fasta, msa


def validate_assets(asset_root: Path, variant: str) -> tuple[Path, Path, Path, dict[str, Any]]:
    model_dir = asset_root / variant
    esmc_dir = asset_root / "esmc-6b"
    ccd_path = asset_root / "ccd.pkl"
    manifest_path = asset_root / "assets.json"
    missing = [str(model_dir / name) for name in MODEL_REQUIRED_FILES if not (model_dir / name).is_file()]
    missing.extend(str(esmc_dir / name) for name in ESMC_REQUIRED_FILES if not (esmc_dir / name).is_file())
    if not ccd_path.is_file():
        missing.append(str(ccd_path))
    if not manifest_path.is_file():
        missing.append(str(manifest_path))
    if missing:
        raise FileNotFoundError("ESMFold 2 assets are incomplete; missing: " + ", ".join(missing))
    asset_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {
        "upstream_commit": UPSTREAM_COMMIT,
        "esmc_revision": ESMC_REVISION,
        "model_revisions": MODEL_REVISIONS,
    }
    for key, value in expected.items():
        if asset_manifest.get(key) != value:
            raise ValueError(f"ESMFold 2 asset manifest has unexpected {key}")
    required_paths = ["ccd.pkl", *(f"{variant}/{name}" for name in MODEL_REQUIRED_FILES)]
    required_paths.extend(f"esmc-6b/{name}" for name in ESMC_REQUIRED_FILES)
    recorded_files = asset_manifest.get("files")
    if not isinstance(recorded_files, dict):
        raise ValueError("ESMFold 2 asset manifest has no file inventory")
    for relative_path in required_paths:
        expected_size, expected_sha256 = ASSET_SPECS[relative_path]
        if recorded_files.get(relative_path) != {"size": expected_size, "sha256": expected_sha256}:
            raise ValueError(f"ESMFold 2 asset manifest has unexpected metadata for {relative_path}")
        path = asset_root / relative_path
        if path.stat().st_size != expected_size:
            raise ValueError(f"ESMFold 2 asset has unexpected size: {relative_path}")
        if sha256(path) != expected_sha256:
            raise ValueError(f"ESMFold 2 asset failed SHA-256 verification: {relative_path}")
    return model_dir, esmc_dir, ccd_path, asset_manifest


def normalized_a3m_query(path: Path) -> str:
    sequence: list[str] = []
    reading_query = False
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith(">"):
            if reading_query:
                break
            reading_query = True
        elif reading_query:
            sequence.append(
                "".join(character for character in line if not character.islower() and character not in "-.")
            )
    normalized = "".join(sequence).upper()
    if not normalized:
        raise ValueError("A3M contains no query sequence")
    return normalized


def _tensor_list(value: Any) -> Any:
    return value.detach().float().cpu().tolist() if value is not None else None


def write_sample(output_dir: Path, index: int, result: Any, include_embeddings: bool) -> dict[str, Any]:
    import numpy as np

    prefix = f"sample_{index:03d}"
    cif_path = output_dir / f"{prefix}.cif"
    cif_path.write_text(result.complex.to_mmcif(), encoding="utf-8")
    plddt = _tensor_list(result.plddt)
    if not plddt:
        raise RuntimeError(f"ESMFold 2 sample {index} did not contain pLDDT values")
    with (output_dir / f"{prefix}_plddt.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("token_index", "plddt"))
        writer.writerows((token_index, value) for token_index, value in enumerate(plddt, start=1))
    pae = _tensor_list(result.pae)
    if pae is None:
        raise RuntimeError(f"ESMFold 2 sample {index} did not contain a PAE matrix")
    (output_dir / f"{prefix}_pae.json").write_text(
        json.dumps({"pae": pae}, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    confidence = {
        "sample": index,
        "mean_plddt": sum(plddt) / len(plddt),
        "ptm": result.ptm,
        "iptm": result.iptm,
        "num_tokens": len(plddt),
    }
    (output_dir / f"{prefix}_confidence.json").write_text(
        json.dumps(confidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if include_embeddings:
        pair = result.output_embedding_pair_pooled
        if pair is None:
            raise RuntimeError("ESMFold 2 was asked for embeddings but returned none")
        np.savez_compressed(output_dir / f"{prefix}_embeddings.npz", pair_pooled=pair.float().cpu().numpy())
    return confidence


# ---------------------------------------------------------------------------
# Task planning and declared fallbacks (pure, so they are testable without a GPU)
# ---------------------------------------------------------------------------


def validate_params(params: Any) -> dict:
    """Return the task's resolved parameters, or fail before anything is loaded."""
    if not isinstance(params, dict):
        raise InputError("Task manifest declares no ESMFold 2 parameters")
    missing = [name for name in REQUIRED_PARAMS if name not in params]
    if missing:
        raise InputError(f"Task manifest is missing the required ESMFold 2 parameter(s): {', '.join(missing)}")
    resolved = dict(params)
    if resolved["model_variant"] not in MODEL_REVISIONS:
        raise InputError(f"Unsupported ESMFold 2 model variant: {resolved['model_variant']!r}")
    if resolved["kernel_backend"] not in KERNEL_BACKENDS:
        raise InputError(f"Unsupported ESMFold 2 kernel backend: {resolved['kernel_backend']!r}")
    if int(resolved["num_diffusion_samples"]) < 1:
        raise InputError("num_diffusion_samples must be a positive integer")
    return resolved


def validate_batch_size(manifest: dict) -> int:
    """Return the task's declared batch size, which ESMFold 2 requires to be 1.

    For this family ``batch_size`` can only mean "chains of one item folded
    together", and one work item is one chain: any other value would advertise a
    reduction the arithmetic cannot deliver, so it is a contract error rather
    than a knob.
    """
    batch_size = int((manifest.get("execution") or {}).get("batch_size") or 1)
    if batch_size != 1:
        raise InputError(
            f"ESMFold 2 folds one chain per work item; execution.batch_size must be 1, got {batch_size}"
        )
    return batch_size


def plan_task(manifest: dict) -> tuple[list[dict], dict]:
    """Turn one task manifest into work items plus the facts every item shares.

    One FASTA *record* is one work item: the file is read in header order, and
    each record becomes an item carrying its identifier, length, and sequence, so
    a plugin never re-reads the manifest or the FASTA. The optional alignment
    belongs to the task, not to a record, and is only attachable when the FASTA
    carries exactly one chain — an MSA conditions one chain, so pairing it with
    several would change the requested computation.
    """
    params = validate_params(manifest.get("params"))
    validate_batch_size(manifest)
    fasta_path, msa_path = manifest_paths(manifest)
    records = read_fasta(fasta_path)
    if msa_path is not None and len(records) != 1:
        raise ValueError("An A3M can only be attached when the FASTA contains exactly one protein chain")
    if msa_path is not None and params["model_variant"] != "standard":
        raise ValueError("MSA conditioning requires model_variant=standard")
    if msa_path is not None and normalized_a3m_query(msa_path) != records[0][1]:
        raise ValueError("A3M query sequence does not match the FASTA protein sequence")
    # The manifest's own identifier order is authoritative: the queue may execute
    # a different order, but what the user sees is the input order.
    items = [
        {
            "id": identifier,
            "order": index,
            "length": len(sequence),
            "sequence": sequence,
            # One chain per work item, plus the requested sample count, so the
            # shared queue and the server's estimator see the real shape.
            "sequence_count": 1,
            "sample_count": int(params["num_diffusion_samples"]),
        }
        for index, (identifier, sequence) in enumerate(records)
    ]
    inputs = manifest.get("inputs") or {}
    sequence_entry = (inputs.get("sequence") or [{}])[0]
    payload = {
        "params": params,
        "task_id": str(manifest.get("task_id") or ""),
        "task_type": str(manifest.get("task_type") or ""),
        "input_sha256": str(sequence_entry.get("sha256") or "") or sha256(fasta_path),
        "input_name": str(sequence_entry.get("original_name") or fasta_path.name),
        "sequence_count": len(items),
        "msa_path": str(msa_path) if msa_path is not None else None,
        "msa_name": msa_path.name if msa_path is not None else None,
        "msa_sha256": sha256(msa_path) if msa_path is not None else None,
    }
    return items, payload


def declared_plans(resource_adaptation: dict | None) -> dict[str, dict]:
    """Index the manifest's declared fallback plans, rejecting invalid ones.

    The runner enforces exactly what its own manifest declares. A plan naming a
    scientific parameter fails at load — an adaptation may change how the
    requested computation is executed, never what was requested — and so does a
    plan naming a resource key this plugin does not realize, because the planner
    only offers what the manifest declares and a declaration the implementation
    cannot honour would be a silent no-op.
    """
    plans: dict[str, dict] = {}
    for entry in (resource_adaptation or {}).get("fallback_plans") or []:
        if not isinstance(entry, dict) or set(entry) - {"label", "title", "adjustments"}:
            raise ValueError(f"ESMFold 2 fallback plan has unknown fields: {entry!r}")
        adjustments = dict(entry.get("adjustments") or {})
        unknown = set(adjustments) - RESOURCE_ADJUSTMENT_KEYS
        if unknown:
            raise ValueError(
                f"ESMFold 2 fallback plan {entry.get('label')!r} changes non-resource parameter(s): {sorted(unknown)}"
            )
        unrealized = set(adjustments) - SUPPORTED_ADJUSTMENTS
        if unrealized:
            raise ValueError(
                f"ESMFold 2 fallback plan {entry.get('label')!r} declares adjustment(s) this runner does not "
                f"implement: {sorted(unrealized)}"
            )
        if adjustments.get("kernel_backend") not in (None, *KERNEL_BACKENDS):
            raise ValueError(
                f"ESMFold 2 fallback plan {entry.get('label')!r} names an unknown kernel backend: "
                f"{adjustments['kernel_backend']!r}"
            )
        label = str(entry.get("label") or "")
        if not label or label in plans:
            raise ValueError(f"ESMFold 2 fallback plan label must be unique and non-empty: {label!r}")
        plans[label] = {
            "label": label,
            "title": str(entry.get("title") or ""),
            "adjustments": adjustments,
        }
    return plans


def resolve_sample_plan(num_samples: int, seed: int, adjustments: dict | None) -> dict:
    """Turn one attempt's adjustments into the effective sample plan.

    Returns the consecutive groups the requested ``num_samples`` are drawn in and
    the stream seed of each group. ``num_samples`` and ``seed`` pass through
    untouched: a fallback changes *how* the requested samples are drawn, never how
    many were requested or which seed was asked for. The first group runs under
    the requested seed, so a task that never needs a fallback reproduces the
    default path, and each following group takes the next stream so its samples
    differ.
    """
    num_samples = int(num_samples)
    if num_samples < 1:
        raise ValueError(f"num_diffusion_samples must be a positive integer; got {num_samples}")
    adjustments = dict(adjustments or {})
    requested_group = adjustments.get("sample_group_size")
    group_size = num_samples if requested_group is None else int(requested_group)
    if group_size < 1:
        raise ValueError(f"sample_group_size must be a positive integer; got {requested_group!r}")
    group_size = min(group_size, num_samples)
    groups = [
        {"start": start, "size": min(group_size, num_samples - start)}
        for start in range(0, num_samples, group_size)
    ]
    return {
        "num_samples": num_samples,
        "seed": int(seed),
        "sample_group_size": group_size,
        "sample_groups": [group["size"] for group in groups],
        "groups": groups,
        "group_seeds": [int(seed) + index for index in range(len(groups))],
        "sample_seeds": [
            int(seed) + group_index for group_index, group in enumerate(groups) for _ in range(group["size"])
        ],
        "kernel_backend": adjustments.get("kernel_backend"),
        "cache_clear": bool(adjustments.get("cache_clear")),
    }


def describe_plan(plan: dict, declared: dict | None = None) -> dict:
    """Name the effective plan, expanding the grouping that actually ran."""
    declared = declared or {}
    grouping = "+".join(str(size) for size in plan["sample_groups"])
    title = str(declared.get("title") or "")
    return {
        "label": str(declared.get("label") or ""),
        "title": f"{title} ({grouping} of {plan['num_samples']} requested samples per group)".strip(),
    }


# ---------------------------------------------------------------------------
# CUDA measurement helpers (framework-owned, best effort)
# ---------------------------------------------------------------------------


def _torch():
    try:
        import torch
    except ImportError:  # a CPU-only test image has no torch
        return None
    return torch


def _mb(value: float) -> int:
    return int(value // (1024 * 1024))


def _cuda_state_available(torch) -> bool:
    return torch is not None and bool(torch.cuda.is_available())


def _peaks(torch) -> tuple[int, int, int]:
    """Return ``(allocated, reserved, process)`` peaks in MiB.

    The caching allocator owns every large allocation this process makes, so its
    reserved peak is the closest observable to the process's device footprint.
    """
    if not _cuda_state_available(torch):
        return (0, 0, 0)
    reserved = _mb(torch.cuda.max_memory_reserved())
    return (_mb(torch.cuda.max_memory_allocated()), reserved, reserved)


def _release_transient(torch) -> None:
    gc.collect()
    if _cuda_state_available(torch):
        torch.cuda.empty_cache()


def _is_out_of_memory(error: Exception) -> bool:
    """A CUDA OOM is recoverable at item level; any other CUDA fault is not."""
    torch = _torch()
    if torch is not None and isinstance(error, torch.cuda.OutOfMemoryError):
        return True
    return "out of memory" in str(error).lower()


class ESMFold2Plugin:
    """The science: one ESMFold 2 protein chain per work item."""

    runner = "esmfold2"
    runner_version = "1"

    def __init__(
        self,
        params: dict,
        *,
        asset_root: str,
        input_name: str = "",
        input_sha256: str = "",
        msa_path: str = "",
        msa_name: str = "",
        msa_sha256: str = "",
        fallback_plans: dict | None = None,
    ) -> None:
        # Requested science. Copied once and never mutated by an adaptation.
        self.params = dict(params)
        self.asset_root = Path(asset_root)
        self.declared_plans = dict(fallback_plans or {})
        # The task's own identity, carried outside ``params`` because it is not a
        # user-facing scientific parameter: ``params`` stays exactly the resolved
        # vocabulary the owning task.yaml declares.
        self.input_name = str(input_name)
        self.input_sha256 = str(input_sha256)
        self.msa_path = Path(msa_path) if msa_path else None
        self.msa_name = str(msa_name)
        self.msa_sha256 = str(msa_sha256)
        self.model_revision = f"{UPSTREAM_COMMIT[:7]}/{params['model_variant']}"
        self._fingerprint = ""
        self._announced_inference = False
        self._announced_validation = False

    # -- identity -----------------------------------------------------------

    @property
    def runtime_fingerprint(self) -> str:
        """Observed identity of the execution environment, not a constant.

        Changes when the framework, CUDA runtime, model revision, or inference
        backend materially change, so observations from a different environment
        are demoted instead of trusted.
        """
        if not self._fingerprint:
            torch = _torch()
            self._fingerprint = "|".join(
                (
                    "torch=" + (getattr(torch, "__version__", "") or "absent" if torch is not None else "absent"),
                    "cuda="
                    + (getattr(getattr(torch, "version", None), "cuda", "") or "none" if torch is not None else "none"),
                    "model=" + self.model_revision,
                    "backend=" + str(self.params["kernel_backend"]),
                )
            )
        return self._fingerprint

    # -- lifecycle ----------------------------------------------------------

    def initialize_runtime(self, execution) -> dict:
        """Validate assets and load the model, ESMC encoder, and input builder once."""
        model_dir, esmc_dir, ccd_path, _asset_manifest = validate_assets(
            self.asset_root, self.params["model_variant"]
        )
        os.environ["ESMFOLD_CCD_PATH"] = str(ccd_path)

        import torch
        from esm.models.esmfold2 import (
            EsmFold2Config,
            ESMFold2InputBuilder,
            EsmFold2Model,
        )
        from esm.models.esmfold2.config import default_module_flags

        if not torch.cuda.is_available():
            raise RuntimeError("ESMFold 2 requires a CUDA GPU")
        config = EsmFold2Config.from_pretrained(model_dir, **default_module_flags(model_dir))
        config.esmc_id = str(esmc_dir)
        model = EsmFold2Model.from_pretrained(
            model_dir,
            config=config,
            device="cuda",
            esmc_precision="bf16",
        ).eval()
        model.set_kernel_backend(None if self.params["kernel_backend"] == "reference" else self.params["kernel_backend"])
        # The model's residency right after it reached the device: this is the
        # baseline the server's estimator factors out of a measured peak.
        baseline_mb = _mb(max(torch.cuda.memory_allocated(), torch.cuda.memory_reserved()))
        torch.cuda.reset_peak_memory_stats()
        msa = None
        if self.msa_path is not None:
            from esm.models.esmfold2 import MSA

            msa = MSA.from_a3m(self.msa_path, max_sequences=int(self.params["msa_max_depth"]))
        return {
            "torch": torch,
            "model": model,
            "builder": ESMFold2InputBuilder(),
            "msa": msa,
            "baseline_mb": baseline_mb,
            "batch_size": int(execution.get("batch_size") or 1),
            "asset_manifest_sha256": sha256(self.asset_root / "assets.json"),
        }

    def finalize(self, runtime) -> None:
        """Release the model and the CUDA cache; a teardown failure is not a result."""
        torch = runtime.pop("torch", None) or _torch()
        for key in ("model", "builder", "msa"):
            runtime[key] = None
        runtime.clear()
        _release_transient(torch)

    def finalize_task(self, output_dir: str, manifest: dict) -> None:
        """No task-level artifact: ``work_items.json`` already is the task summary."""

    # -- one item -----------------------------------------------------------

    def run_item(self, runtime, payload, adjustments, work_dir, execution):
        """Fold one chain into ``work_dir`` and measure the peak, one group at a time.

        ``execution`` carries the task's execution shape. The resource adjustments
        come from the attempt's declared plan and never from the user's parameters.
        """
        torch = runtime["torch"]
        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        adjustments = dict(adjustments or {})
        plan = resolve_sample_plan(
            int(self.params["num_diffusion_samples"]), int(self.params["seed"]), adjustments
        )
        plan.update(describe_plan(plan, self._declared_for(adjustments)))
        if torch is not None and torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
        try:
            samples = self._fold_groups(runtime, payload, plan, work_dir)
        except Exception as error:  # classified here, never swallowed
            _release_transient(torch)
            if _is_out_of_memory(error):
                return (OUTCOME_OOM, *_peaks(torch), "CUDA_OOM")
            raise
        self._write_provenance(work_dir, payload, plan, runtime, samples)
        return (OUTCOME_SUCCESS, *_peaks(torch), "")

    # -- internals ----------------------------------------------------------

    def _declared_for(self, adjustments: dict) -> dict | None:
        """The declared plan whose adjustments are the ones being enforced."""
        return next(
            (plan for plan in self.declared_plans.values() if plan["adjustments"] == adjustments),
            None,
        )

    def _fold_groups(self, runtime, payload: dict, plan: dict, work_dir: Path) -> list[dict]:
        """Fold every requested sample group, one ``fold`` call per group.

        ``fold(num_diffusion_samples=N)`` draws N independent samples and restores
        the RNG on exit, so a group is that same request at a smaller
        multiplicity: the sample set is the requested one and only the stream
        grouping differs. Each group re-seeds with its own stream, so groups are
        independent draws rather than N copies of one structure.
        """
        from esm.models.esmfold2 import ProteinInput, StructurePredictionInput

        torch = runtime["torch"]
        builder = runtime["builder"]
        model = runtime["model"]
        if not self._announced_inference:
            self._announced_inference = True
            print("REVODESIGN_STAGE:esmfold2_predict", flush=True)
        backend = plan.get("kernel_backend") or self.params["kernel_backend"]
        model.set_kernel_backend(None if backend == "reference" else backend)
        chain = ProteinInput(
            id=str(payload["id"]),
            sequence=str(payload["sequence"]),
            msa=runtime["msa"],
        )
        prediction_input = StructurePredictionInput(sequences=[chain])
        summaries: list[dict] = []
        for group_index, group in enumerate(plan["groups"]):
            results = builder.fold(
                model,
                prediction_input,
                num_loops=int(self.params["num_loops"]),
                num_sampling_steps=int(self.params["num_sampling_steps"]),
                num_diffusion_samples=int(group["size"]),
                seed=int(plan["group_seeds"][group_index]),
                lm_dropout=float(self.params["lm_dropout"]),
                lm_mask_pct=float(self.params["lm_mask_pct"]),
                msa_max_depth=int(self.params["msa_max_depth"]),
                msa_column_mask_rate=float(self.params["msa_column_mask_rate"]),
                include_embeddings=bool(self.params["include_embeddings"]),
                complex_id="esmfold2_prediction",
            )
            samples = results if isinstance(results, list) else [results]
            if len(samples) != int(group["size"]):
                raise RuntimeError(
                    f"ESMFold 2 returned {len(samples)} samples for a group of {group['size']}"
                )
            for offset, sample in enumerate(samples):
                index = int(group["start"]) + offset + 1
                summaries.append(write_sample(work_dir, index, sample, bool(self.params["include_embeddings"])))
            del samples, results
            if plan["cache_clear"] and torch is not None and torch.cuda.is_available():
                torch.cuda.empty_cache()
        expected = int(self.params["num_diffusion_samples"])
        if len(summaries) != expected:
            raise RuntimeError(f"ESMFold 2 produced {len(summaries)} samples; expected {expected}")
        return summaries

    def _write_provenance(self, work_dir: Path, payload: dict, plan: dict, runtime: dict, samples: list[dict]) -> None:
        record = {
            "item": {
                "id": str(payload["id"]),
                "order": int(payload.get("order") or 0),
                "length": int(payload.get("length") or 0),
            },
            "input": {
                "fasta": self.input_name,
                "fasta_sha256": self.input_sha256,
                "msa": self.msa_name or None,
                "msa_sha256": self.msa_sha256 or None,
            },
            "chains": [{"id": str(payload["id"]), "length": int(payload.get("length") or 0)}],
            # What the user requested. Copied verbatim; an adaptation never edits it.
            "parameters": dict(self.params),
            "effective": {
                "batch_size": int(runtime.get("batch_size") or 1),
                "plan_label": plan["label"],
                "plan_title": plan["title"],
                "seed": plan["seed"],
                "sample_group_size": plan["sample_group_size"],
                "sample_groups": plan["sample_groups"],
                "group_seeds": plan["group_seeds"],
                "sample_seeds": plan["sample_seeds"],
                "kernel_backend": plan.get("kernel_backend") or self.params["kernel_backend"],
                "cache_clear": plan["cache_clear"],
            },
            "software": {
                "repository": "https://github.com/Biohub/esm",
                "commit": UPSTREAM_COMMIT,
                "version": UPSTREAM_VERSION,
            },
            "models": {
                "variant_revision": MODEL_REVISIONS[self.params["model_variant"]],
                "esmc_revision": ESMC_REVISION,
                "asset_manifest_sha256": runtime.get("asset_manifest_sha256", ""),
            },
            "runtime_fingerprint": self.runtime_fingerprint,
            "samples": samples,
        }
        (work_dir / "prediction.json").write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    def validate_item(self, work_dir, payload, adjustments) -> None:
        """Fail closed unless the item's artifacts are exactly what was requested.

        The per-item commit is the only thing that publishes a result, so every
        artifact the result workspace declares must exist and be non-empty here —
        for every item, on every plan.
        """
        if not self._announced_validation:
            self._announced_validation = True
            print("REVODESIGN_STAGE:output_validation", flush=True)
        work_dir = Path(work_dir)
        expected = int(self.params["num_diffusion_samples"])
        written = sorted(path.name for path in work_dir.glob("sample_*.cif"))
        if written != [f"sample_{index:03d}.cif" for index in range(1, expected + 1)]:
            raise ValueError(f"ESMFold 2 wrote {len(written)} structure samples; expected {expected}")
        embeddings = bool(self.params["include_embeddings"])
        for sample in range(1, expected + 1):
            names = [
                f"sample_{sample:03d}_plddt.csv",
                f"sample_{sample:03d}_pae.json",
                f"sample_{sample:03d}_confidence.json",
            ]
            if embeddings:
                names.append(f"sample_{sample:03d}_embeddings.npz")
            for name in names:
                path = work_dir / name
                if not path.is_file() or path.stat().st_size == 0:
                    raise ValueError(f"ESMFold 2 did not write a usable {name}")
        if not (work_dir / "prediction.json").is_file():
            raise ValueError("ESMFold 2 did not write its prediction provenance")

    # -- measurement --------------------------------------------------------

    def runtime_usage(self, runtime) -> tuple[int, int, int]:
        """``(baseline_residency_mb, allocated_mb, reserved_mb)`` on the device.

        The baseline is the model's residency right after it reached the device,
        which is what the server's estimator factors out of a measured peak.
        """
        torch = runtime.get("torch") or _torch()
        baseline = int(runtime.get("baseline_mb") or 0)
        if not _cuda_state_available(torch):
            return (baseline, 0, 0)
        return (baseline, _mb(torch.cuda.memory_allocated()), _mb(torch.cuda.memory_reserved()))

    def available_vram_mb(self, runtime) -> int:
        torch = runtime.get("torch") or _torch()
        if not _cuda_state_available(torch):
            return 0
        free, total = torch.cuda.mem_get_info()
        return _mb(free) or _mb(total)

    def device_profile(self, runtime) -> dict:
        """The device actually allocated to this job, never a physical GPU id."""
        torch = runtime.get("torch") or _torch()
        if not _cuda_state_available(torch):
            return {"vendor": "unknown", "model": "unknown", "compute_capability": "", "total_vram_mb": 1, "mig_profile": ""}
        index = torch.cuda.current_device()
        name = str(torch.cuda.get_device_name(index))
        major, minor = torch.cuda.get_device_capability(index)
        properties = torch.cuda.get_device_properties(index)
        lowered = name.lower()
        vendor = "nvidia" if "nvidia" in lowered or "geforce" in lowered or "tesla" in lowered else name.split()[0].lower()
        return {
            "vendor": vendor or "unknown",
            "model": name,
            "compute_capability": f"{major}.{minor}",
            "total_vram_mb": _mb(properties.total_memory),
            "mig_profile": name if "MIG" in name.upper() else "",
        }


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run offline ESMFold 2 prediction as a persistent multi-item task")
    parser.add_argument("--task-manifest", "-i", required=True, type=Path)
    parser.add_argument("--output-dir", "-o", required=True, type=Path)
    parser.add_argument("--asset-root", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest = read_task_manifest(args.task_manifest)
    # Planning happens before the runtime loads: a bad record, a duplicate
    # identifier, or a declared plan this runner cannot honour must fail here,
    # before a single output path exists.
    items, payload = plan_task(manifest)
    plugin = ESMFold2Plugin(
        payload["params"],
        asset_root=str(args.asset_root),
        input_name=payload["input_name"],
        input_sha256=payload["input_sha256"],
        msa_path=payload["msa_path"] or "",
        msa_name=payload["msa_name"] or "",
        msa_sha256=payload["msa_sha256"] or "",
        fallback_plans=declared_plans(manifest.get("resource_adaptation")),
    )
    config = build_config(
        manifest, "esmfold2", items, payload, execution_defaults=dict(manifest.get("execution") or {})
    )
    execute_task(config, plugin, output_dir=str(args.output_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
