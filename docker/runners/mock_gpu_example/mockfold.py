# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""A deterministic, GPU-free folding stand-in for the persistent/OOM machinery.

This family is a **test/reference-only** Runner. It exists so the persistent
multi-input lifecycle, the bounded adaptive-OOM recovery ladder, and the
per-attempt recovery provenance can be exercised end to end — the real
``PersistentTask`` in ``common/runtime/persistent_runner.py``, the real ladder,
the real ``work_items.json`` — **without a GPU and without a production SIF**.
It fabricates a configurable *pseudo-device* and a deterministic pseudo-model,
so a reviewer can drive every recovery path on a laptop or a CPU-only CI worker.

It is not science. It is the smallest runner that has the *shape* of a folding
Runner: a runtime loaded once per task, one work item per FASTA record, a memory
demand that grows with sequence length and sample concurrency, a bounded
fallback ladder that walks on a real OOM, and per-sample artifacts whose bytes
depend only on the *effective scientific parameters*.

The pseudo-model is deterministic by construction, which is what makes it a
useful comparator:

* the effective scientific parameters are ``num_samples``, ``seed``, the
  resolved ``kernel_backend``, and the sample grouping;
* a **resource-only** recovery (``cache_clear``, ``chunk_size``,
  ``token_budget``, ``cpu_offload``, ``batch_size``) changes the memory demand
  and *never* the artifact bytes — so the equivalence of a recovered run to the
  uninterrupted baseline is checkable by hashing the output;
* a **numerical-backend** recovery (``kernel_backend``) and a
  **scientific-output** recovery (``sample_group_size``) *do* change the bytes,
  and the runner reports them as such rather than as neutral resource knobs;
* a plan naming a scientific parameter is refused at the lifecycle boundary and
  never executes.

The three evidence layers this family sits in are spelled out in the family
README; the short version is that it proves the *mechanism* (layer 1) and
nothing about a real model's scientific equivalence (layer 2) or a production
SIF's packaging (layer 3).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import sys

# ---------------------------------------------------------------------------
# Comparison contract (mirrors the real folding families)
# ---------------------------------------------------------------------------

#: Parameters that govern what the model computes. A comparison of two
#: executions holds these fixed; a recovery that changed one would change the
#: result.
SCIENTIFIC_PARAMETERS = frozenset({"num_samples", "seed", "kernel_backend"})
#: Execution-only keys a fallback may name (the server's adaptation vocabulary).
RESOURCE_ONLY_PARAMETERS = frozenset(
    {"sample_group_size", "batch_size", "token_budget", "chunk_size", "cpu_offload", "kernel_backend", "cache_clear"}
)
#: Identity carried into provenance — never an execution parameter.
PROVENANCE_PARAMETERS = frozenset({"input_name", "input_sha256"})
#: The subset this plugin realizes. ``batch_size`` is fixed at 1 (one item is
#: one chain), so a plan naming it would advertise a reduction it cannot deliver.
#: ``cache_clear`` is accepted but changes *when* memory is released, not how
#: much is asked for, so a plan that sets only it is a no-op for the ladder and
#: is dropped by the shared lifecycle before it consumes an attempt.
SUPPORTED_ADJUSTMENTS = frozenset({"sample_group_size", "kernel_backend", "cache_clear", "chunk_size", "token_budget", "cpu_offload"})

KERNEL_BACKENDS = ("reference", "triton")

#: Pseudo-model memory model, in MiB. Deliberately simple and fully documented
#: so the OOM a test provokes is a computed number, not a coincidence.
#:
#: * demand grows with sequence length and with the *concurrency* (the number of
#:   samples the first group draws together, i.e. the grouping);
#: * ``cpu_offload`` halves it; ``kernel_backend=reference`` scales it by 0.8;
#:   ``chunk_size`` and ``token_budget`` relieve a fixed amount;
#: * ``cache_clear`` relieves nothing — it changes when memory is released, not
#:   how much is asked for — so it is not a lever here either.
BASE_MB = 128
PER_RESIDUE_MB = 4
PER_CONCURRENT_SAMPLE_MB = 512
CHUNK_RELIEF_MB = 64
TOKEN_BUDGET_RELIEF_MB = 32
REFERENCE_BACKEND_SCALE = 0.8


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def resolve_sample_plan(num_samples: int, seed: int, adjustments: dict | None) -> dict:
    """Turn one attempt's adjustments into the effective sample plan.

    ``num_samples`` and ``seed`` pass through untouched: a fallback changes *how*
    the requested samples are drawn, never how many were requested or which seed
    was asked for. Sample ``j`` always carries ``seed + j``; each group is seeded
    from its first sample, because the samples inside a group share one stream.
    """
    num_samples = int(num_samples)
    if num_samples < 1:
        raise ValueError(f"num_samples must be a positive integer; got {num_samples}")
    adjustments = dict(adjustments or {})
    requested_group = adjustments.get("sample_group_size")
    group_size = num_samples if requested_group is None else int(requested_group)
    if group_size < 1:
        raise ValueError(f"sample_group_size must be a positive integer; got {requested_group!r}")
    group_size = min(group_size, num_samples)
    groups = [{"start": start, "size": min(group_size, num_samples - start)} for start in range(0, num_samples, group_size)]
    return {
        "num_samples": num_samples,
        "seed": int(seed),
        "sample_group_size": group_size,
        "sample_groups": [group["size"] for group in groups],
        "group_seeds": [int(seed) + group["start"] for group in groups],
        "sample_seeds": [int(seed) + index for index in range(num_samples)],
        "groups": groups,
    }


def memory_demand_mb(length: int, plan: dict, adjustments: dict | None) -> int:
    """The pseudo-device memory one attempt would demand, in MiB.

    Concurrency is the requested sample count capped to the group size, so a
    smaller grouping demands less instantaneous memory. The resource-only knobs
    each relieve a fixed, documented amount.
    """
    adjustments = dict(adjustments or {})
    concurrent = int(plan["groups"][0]["size"]) if plan["groups"] else 1
    mb = BASE_MB + PER_RESIDUE_MB * int(length) + PER_CONCURRENT_SAMPLE_MB * concurrent
    if adjustments.get("cpu_offload"):
        mb = int(mb * 0.5)
    if adjustments.get("kernel_backend") == "reference":
        mb = int(mb * REFERENCE_BACKEND_SCALE)
    if adjustments.get("chunk_size"):
        mb -= CHUNK_RELIEF_MB
    if adjustments.get("token_budget"):
        mb -= TOKEN_BUDGET_RELIEF_MB
    return max(16, mb)


def sample_coordinates(sequence_hash: str, plan: dict, group_seed: int, index_in_group: int, backend: str) -> list[float]:
    """The three deterministic coordinates of one sample.

    A pure function of the *effective scientific parameters*: the sequence, the
    requested sample count and seed (through ``group_seed`` and
    ``index_in_group``), and the kernel backend. No resource-only knob reaches
    it, so a resource-only recovery cannot move a coordinate.
    """
    seed_bytes = f"{sequence_hash}|{plan['num_samples']}|{group_seed}|{index_in_group}|{backend}".encode("utf-8")
    coordinates: list[float] = []
    block = seed_bytes
    while len(coordinates) < 3:
        block = hashlib.sha256(block).digest()
        for offset in range(0, 32, 4):
            if len(coordinates) == 3:
                break
            coordinates.append(round(int.from_bytes(block[offset : offset + 4], "big") / 2**32, 6))
    return coordinates


def draw_samples(sequence_hash: str, num_samples: int, seed: int, adjustments: dict | None) -> list[dict]:
    """Draw the requested samples under one attempt's effective plan."""
    adjustments = dict(adjustments or {})
    plan = resolve_sample_plan(num_samples, seed, adjustments)
    backend = str(adjustments.get("kernel_backend") or "default")
    samples: list[dict] = []
    for group in plan["groups"]:
        group_seed = int(seed) + group["start"]
        for offset in range(group["size"]):
            index = group["start"] + offset
            samples.append(
                {
                    "index": index,
                    "sample_seed": int(seed) + index,
                    "group_start": group["start"],
                    "group_seed": group_seed,
                    "coordinates": sample_coordinates(sequence_hash, plan, group_seed, offset, backend),
                }
            )
    return samples


def write_item(output_dir: Path, identifier: str, samples: list[dict], *, parameters: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "mock_samples.json").write_text(
        json.dumps(
            {"schema_version": 1, "sequence_id": identifier, "parameters": parameters, "samples": samples},
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "summary.json").write_text(
        json.dumps(
            {"schema_version": 1, "sequence_id": identifier, "sample_count": len(samples), "parameters": parameters},
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Standalone entry (no lifecycle): one FASTA file, one pseudo-fold
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mock folding (mockfold.py --input ... --output-dir ...)")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--num-samples", type=int, default=4)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args(argv)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common" / "runtime"))
    from work_items import read_fasta_records

    for identifier, sequence in read_fasta_records(args.input):
        samples = draw_samples(sha256_text(sequence), args.num_samples, args.seed, {})
        write_item(
            args.output_dir / identifier,
            identifier,
            samples,
            parameters={"num_samples": args.num_samples, "seed": args.seed},
        )
    return 0


# ---------------------------------------------------------------------------
# Persistent multi-work-item execution
# ---------------------------------------------------------------------------

from persistent_runner import (  # noqa: E402
    OUTCOME_OOM,
    OUTCOME_SUCCESS,
    FAILED_RUNTIME,
    WorkItemError,
    execute_task,
    exit_code_for,
)
from work_items import build_config, read_task_manifest, record_problem, sequence_work_items  # noqa: E402

#: The pseudo-runtime is the interpreter itself, so its fingerprint names it.
RUNTIME_FINGERPRINT = f"mockfold-py3-{platform.python_version()}"
#: Per-item supported maximum.
MAX_ITEM_RESIDUES = 4096


class MockFoldPlugin:
    """The plugin surface ``persistent_runner.execute_task`` calls.

    A real folding family replaces ``initialize_runtime`` with a model load and
    ``run_item`` with an inference call; the *lifecycle* around them is exactly
    the same, which is the point of this family. The pseudo-device is configured
    through the environment so one test can pick a VRAM envelope that makes the
    default path OOM and a declared fallback fit.
    """

    runner = "mock_gpu_example"
    runner_version = "1"
    model_revision = "mockfold-v1"
    runtime_fingerprint = RUNTIME_FINGERPRINT

    def __init__(self, params: dict) -> None:
        self.params = dict(params)
        self._device_model = os.environ.get("MOCK_DEVICE_MODEL", "mock-gpu-8gb")
        self._total_vram_mb = int(os.environ.get("MOCK_DEVICE_VRAM_MB", "8192"))
        self._free_vram_mb = int(os.environ.get("MOCK_DEVICE_FREE_VRAM_MB", str(self._total_vram_mb)))

    # -- lifecycle ----------------------------------------------------------

    def initialize_runtime(self, execution: dict) -> dict:
        runtime = {
            "device_model": self._device_model,
            "total_vram_mb": self._total_vram_mb,
            "free_vram_mb": self._free_vram_mb,
            "num_samples": int(self.params["num_samples"]),
            "seed": int(self.params["seed"]),
            "kernel_backend": str(self.params.get("kernel_backend") or "triton"),
        }
        print("REVODESIGN_STAGE:mock_folding", flush=True)
        return runtime

    def finalize(self, runtime: dict) -> None:
        runtime.clear()

    def finalize_task(self, output_dir: str, manifest: dict) -> None:
        summaries: dict[str, dict] = {}
        for entry in manifest["items"]:
            if entry["status"] != "SUCCEEDED":
                continue
            try:
                with open(os.path.join(output_dir, entry["name"], "summary.json"), encoding="utf-8") as handle:
                    summaries[entry["name"]] = json.load(handle)
            except (OSError, json.JSONDecodeError):
                pass
        rollup = {
            "schema_version": 1,
            "task_id": manifest.get("task_id") or "",
            "sequence_count": len(manifest["items"]),
            "succeeded_count": len(summaries),
            "failed_count": len(manifest["items"]) - len(summaries),
            "total_samples": sum(int(summary.get("sample_count") or 0) for summary in summaries.values()),
            "items": [
                {
                    "sequence_id": entry["id"],
                    "status": entry["status"],
                    "attempts": entry["attempts"],
                    "output_path": entry["output_path"],
                }
                for entry in manifest["items"]
            ],
        }
        (Path(output_dir) / "task_summary.json").write_text(
            json.dumps(rollup, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    # -- measurement --------------------------------------------------------

    def device_profile(self, runtime: dict) -> dict:
        """The configurable pseudo-device. No accelerator is touched."""
        return {
            "vendor": "mock",
            "model": str(runtime["device_model"]),
            "compute_capability": "",
            "total_vram_mb": int(runtime["total_vram_mb"]),
            "mig_profile": "",
        }

    def runtime_usage(self, runtime: dict) -> tuple[int, int, int]:
        return int(runtime["free_vram_mb"]), int(runtime["free_vram_mb"]), 0

    def available_vram_mb(self, runtime: dict) -> int:
        return int(runtime["free_vram_mb"])

    # -- plan resolution ----------------------------------------------------

    def effective_plan_key(self, payload: dict, adjustments: dict | None) -> str:
        """Effective execution key, so the lifecycle skips no-op plans.

        Every adjustment this plugin *realizes* as a change to the execution
        shape is in the key, so a plan that only repeats an earlier execution is
        dropped before it consumes an attempt. ``cache_clear`` is deliberately
        absent: it changes when memory is released, not how much is asked for, so
        a ``cache_clear``-only plan is a no-op and is correctly skipped.
        """
        adjustments = dict(adjustments or {})
        plan = resolve_sample_plan(
            int(payload.get("sample_count") or self.params["num_samples"]),
            int(self.params["seed"]),
            adjustments,
        )
        return "|".join(
            str(value)
            for value in (
                plan["sample_group_size"],
                adjustments.get("kernel_backend") or self.params.get("kernel_backend") or "triton",
                bool(adjustments.get("cpu_offload")),
                adjustments.get("chunk_size") or "",
                adjustments.get("token_budget") or "",
            )
        )

    def effective_parameters(self, payload: dict, adjustments: dict | None) -> dict:
        """The effective *scientific* parameter set one attempt executes.

        The requested count and seed are fixed before any adaptation runs, so
        they always keep the user's value. The kernel backend is the one
        parameter that is both user-selected and a resource key, so it is
        reported at the value actually executed. The resolved grouping is carried
        too, because the samples inside a group share that group's stream — the
        requested samples come out with different coordinates under a different
        grouping — which makes the divergence explicit instead of leaving a split
        run looking like the baseline.
        """
        params = dict(self.params)
        plan = resolve_sample_plan(int(params["num_samples"]), int(params["seed"]), adjustments)
        params["kernel_backend"] = str((adjustments or {}).get("kernel_backend") or params.get("kernel_backend") or "triton")
        params["sample_group_size"] = plan["sample_group_size"]
        params["sample_groups"] = plan["sample_groups"]
        params["group_seeds"] = plan["group_seeds"]
        params["sample_seeds"] = plan["sample_seeds"]
        return params

    # -- one work item ------------------------------------------------------

    def run_item(self, runtime: dict, payload: dict, adjustments: dict, work_dir: str, execution: dict) -> tuple:
        sequence = str(payload.get("sequence") or "")
        problem = record_problem(sequence, max_length=MAX_ITEM_RESIDUES)
        if problem:
            raise WorkItemError("FAILED_INPUT", problem)
        identifier = str(payload.get("id") or "item")
        num_samples = int(payload.get("sample_count") or runtime["num_samples"])
        seed = int(runtime["seed"])
        plan = resolve_sample_plan(num_samples, seed, adjustments)
        demand = memory_demand_mb(len(sequence), plan, adjustments)
        free = int(runtime["free_vram_mb"])
        if demand > free:
            # A real OOM: the item fails as FAILED_RESOURCE and the ladder walks.
            return OUTCOME_OOM, demand, demand, demand, "MOCK_OOM"
        samples = draw_samples(sha256_text(sequence), num_samples, seed, adjustments)
        write_item(
            Path(work_dir),
            identifier,
            samples,
            parameters=self.effective_parameters(payload, adjustments),
        )
        return OUTCOME_SUCCESS, demand, demand, demand, ""

    def validate_item(self, work_dir: str, payload: dict, adjustments: dict) -> None:
        for filename in ("mock_samples.json", "summary.json"):
            path = os.path.join(work_dir, filename)
            if not os.path.isfile(path) or os.path.getsize(path) == 0:
                raise WorkItemError(FAILED_RUNTIME, f"work item produced no {filename}")


def run_task(task_manifest: Path, output_dir: Path) -> int:
    manifest = read_task_manifest(task_manifest)
    params = dict(manifest.get("params") or {})
    if "num_samples" not in params or "seed" not in params:
        print("task.json carries no resolved num_samples/seed parameters", file=sys.stderr)
        return 2
    items, payload = sequence_work_items(
        manifest,
        "sequence",
        item_fields={"sample_count": int(params["num_samples"]), "requested_parameters": dict(params)},
    )
    config = build_config(manifest, MockFoldPlugin.runner, items, payload, execution_defaults={"max_item_attempts": 3})
    result = execute_task(config, MockFoldPlugin(params), output_dir=str(output_dir))
    return exit_code_for(result)


if __name__ == "__main__":
    argv = sys.argv[1:]
    if argv and argv[0] == "task":
        raise SystemExit(run_task(Path(argv[1]), Path(argv[2])))
    raise SystemExit(main())
