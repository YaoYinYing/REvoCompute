# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""SimpleFold as a persistent multi-item Runner plugin.

Upstream ``predict_structures_from_fastas`` seeds once, initializes the folding
model, the pLDDT modules, ESM-2, and the tokenizer/featurizer/processor/flow/
sampler, then loops over every structure and samples ``nsample_per_protein``
conformations for each. That loop is split here so the shared
:mod:`persistent_runner` lifecycle drives it: every module loads **once per
task** in :meth:`SimpleFoldPlugin.initialize_runtime`, one FASTA *record* is one
work item executed by :meth:`run_item` into its own work directory, and
:meth:`finalize` releases the runtime.

Determinism (the subtle part):

* A work item's effective seed is ``params["seed"] + item_order``. Re-seeding
  immediately before the item's sample step reproduces upstream's stream for
  item 0 exactly, and makes every other item independently reproducible after a
  restart instead of depending on how many items ran before it.
* ``num_samples`` is scientific and is never changed. The default path draws all
  requested samples from one multiplicity-N draw, exactly as upstream. A
  declared ``sample_group_size`` fallback splits that draw into consecutive
  independent groups that still cover every requested sample index; each group
  re-seeds from ``item_seed + group_index`` and the resulting per-sample stream
  seeds are recorded in ``run_metadata.json`` beside the plan's title, so a
  split run is inspectable rather than silent.
* Featurization runs after the seed and consumes no randomness, so the initial
  noise tensor is the first draw of the item's stream — which is what makes
  ``seed`` reproduce a run.

Measurements come from the framework that owns the GPU allocations
(``torch.cuda``); the plugin reports them and the server owns the estimator.
"""

from __future__ import annotations

import argparse
import gc
import json
import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from finalize import (  # noqa: E402
    build_run_metadata,
    promote_input_manifest,
    validate_item_outputs,
    write_run_metadata,
)
from persistent_runner import (  # noqa: E402
    OUTCOME_OOM,
    OUTCOME_SUCCESS,
    execute_task,
    safe_item_name,
)
from work_items import (  # noqa: E402
    InputError,
    build_config,
    read_task_manifest,
    sequence_work_items,
)

#: Upstream pinned revision, recorded in provenance.
UPSTREAM_REVISION = "c7a5570a6be9f5c695126e27c804e77567209934"
#: Upstream default: a SimpleFold target supports at most 1022 residues.
DEFAULT_MAX_RESIDUES = 1022
#: FASTA extensions accepted for the ``sequence`` role.
SEQUENCE_EXTENSIONS = (".fasta", ".fa", ".fas", ".faa")
#: Parameters every SimpleFold task manifest must carry.
REQUIRED_PARAMS = ("model", "num_steps", "tau", "num_samples", "predict_plddt", "output_format", "seed")

#: The adjustments this family *implements*: ``sample_group_size`` is the only
#: dimension in which SimpleFold can lower its peak without touching the
#: requested science, and ``cache_clear`` releases the caching allocator between
#: groups.
SUPPORTED_ADJUSTMENTS = frozenset({"sample_group_size", "cache_clear"})
#: Execution-only keys a fallback may name (the server's adaptation vocabulary).
#: Anything else — ``num_samples``, ``seed``, a model or sampling parameter — is
#: scientific, and a plan that asks for it is rejected at manifest load.
RESOURCE_ADJUSTMENT_KEYS = frozenset(
    {"sample_group_size", "batch_size", "token_budget", "chunk_size", "cpu_offload", "kernel_backend", "cache_clear"}
)
#: ``group_size`` is the shorthand the estimator's planner may emit.
ADJUSTMENT_ALIASES = {"group_size": "sample_group_size"}


# ---------------------------------------------------------------------------
# Effective plan (pure, so it is testable without a GPU)
# ---------------------------------------------------------------------------


def canonical_adjustments(adjustments: dict | None) -> dict:
    """Normalize adjustment spelling without dropping or inventing a key."""
    canonical = {ADJUSTMENT_ALIASES.get(str(key), str(key)): value for key, value in dict(adjustments or {}).items()}
    if len(canonical) != len(dict(adjustments or {})):
        raise ValueError("Fallback plan declares two spellings of the same adjustment")
    return canonical


def declared_plans(resource_adaptation: dict | None) -> dict:
    """Index the manifest's declared fallback plans, rejecting invalid ones.

    The runner enforces exactly what its own manifest declares. A declared plan
    that names a scientific parameter is a load-time failure: an adaptation may
    change how the requested computation is executed, never what was requested.
    A plan naming a recognized *execution* key this plugin does not realize is
    kept and reported per item, because the server may legitimately send one
    from a sibling declaration.
    """
    plans: dict[str, dict] = {}
    for entry in (resource_adaptation or {}).get("fallback_plans") or []:
        if not isinstance(entry, dict) or set(entry) - {"label", "title", "adjustments"}:
            raise ValueError(f"SimpleFold fallback plan has unknown fields: {entry!r}")
        adjustments = canonical_adjustments(entry.get("adjustments"))
        unknown = set(adjustments) - RESOURCE_ADJUSTMENT_KEYS
        if unknown:
            raise ValueError(
                f"SimpleFold fallback plan {entry.get('label')!r} changes non-resource "
                f"parameter(s): {sorted(unknown)}"
            )
        unrealized = sorted(set(adjustments) - SUPPORTED_ADJUSTMENTS)
        if unrealized:
            print(f"SimpleFold does not realize declared adjustment(s) {unrealized}; they will be reported per item")
        label = str(entry.get("label") or "")
        if not label or label in plans:
            raise ValueError(f"SimpleFold fallback plan label must be unique and non-empty: {label!r}")
        plans[label] = {"label": label, "title": str(entry.get("title") or ""), "adjustments": adjustments}
    return plans


def resolve_sample_plan(
    num_samples: int, item_order: int, seed: int, adjustments: dict | None, declared: dict | None = None
) -> dict:
    """Turn one attempt's adjustments into the effective sample plan.

    Returns the consecutive groups the requested samples are drawn in, the stream
    seed of each group, and the adjustments this plugin does not implement
    (recorded rather than silently dropped). ``num_samples`` passes through
    untouched: a fallback changes *how* the samples are drawn, never how many the
    user requested.
    """
    num_samples = int(num_samples)
    if num_samples < 1:
        raise ValueError(f"num_samples must be a positive integer; got {num_samples}")
    canonical = canonical_adjustments(adjustments)
    requested_group = canonical.get("sample_group_size")
    group_size = num_samples if requested_group is None else int(requested_group)
    if group_size < 1:
        raise ValueError(f"sample_group_size must be a positive integer; got {requested_group!r}")
    group_size = min(group_size, num_samples)
    groups = [
        {"start": start, "size": min(group_size, num_samples - start)}
        for start in range(0, num_samples, group_size)
    ]
    item_seed = int(seed) + int(item_order)
    plan = {
        "sample_group_size": group_size,
        "sample_groups": [group["size"] for group in groups],
        "groups": groups,
        "item_seed": item_seed,
        "group_seeds": [item_seed + index for index in range(len(groups))],
        # One stream seed per produced sample, so a split run's mapping from
        # sample index to stream is explicit. The default path is one draw, so
        # every sample shares the item's stream.
        "sample_seeds": [item_seed + index for index, group in enumerate(groups) for _ in range(group["size"])],
        "cache_clear": bool(canonical.get("cache_clear")),
        "unapplied": {key: value for key, value in canonical.items() if key not in SUPPORTED_ADJUSTMENTS},
        "label": "",
        "title": "",
    }
    if declared:
        grouping = "+".join(str(size) for size in plan["sample_groups"])
        plan["label"] = declared["label"]
        plan["title"] = (
            f"{declared['title']} ({grouping} samples per group, {len(groups)} group(s); "
            "the requested sample count and item seed are unchanged)."
        ).strip()
    return plan


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


def _cuda_peaks(torch) -> tuple[int, int, int]:
    """Return ``(peak_allocated, peak_reserved, peak_process)`` in MiB.

    The caching allocator owns every large allocation this process makes, so its
    reserved peak is the closest observable to the process's device footprint.
    """
    if torch is None or not torch.cuda.is_available():
        return (0, 0, 0)
    reserved = _mb(torch.cuda.max_memory_reserved())
    return (_mb(torch.cuda.max_memory_allocated()), reserved, reserved)


def _release_transient(torch) -> None:
    gc.collect()
    if torch is not None and torch.cuda.is_available():
        torch.cuda.empty_cache()


def _is_out_of_memory(error: Exception) -> bool:
    """A CUDA OOM is recoverable at item level; any other CUDA fault is not."""
    torch = _torch()
    if torch is not None and isinstance(error, torch.cuda.OutOfMemoryError):
        return True
    return "out of memory" in str(error).lower()


# ---------------------------------------------------------------------------
# Offline patches (upstream would download assets the image already provisions)
# ---------------------------------------------------------------------------


def _import_inference():
    from simplefold import inference

    return inference


def _install_offline_patches(inference) -> None:
    """Bind upstream's FASTA utilities to the provisioned assets and keep pLDDT.

    Idempotent: a runtime restart reloads the modules without re-wrapping them.
    Upstream's helper would download a CCD and an unused Boltz confidence
    checkpoint; the image already carries both, so the download hook is a no-op
    and the CCD path supplied by the caller is used. ``save_structure`` also
    records the per-residue pLDDT beside each structure.
    """
    if getattr(inference, "_revocompute_offline_patched", False):
        return
    save_structure = inference.save_structure

    def save_structure_with_confidence(structure, save_dir, outname, output_format="mmcif", plddts=None) -> None:
        save_structure(structure, save_dir, outname, output_format=output_format, plddts=plddts)
        if plddts is None:
            return
        values = plddts.detach().cpu().tolist() if hasattr(plddts, "detach") else list(plddts)
        confidence_dir = Path(save_dir).parent / "confidence"
        confidence_dir.mkdir(parents=True, exist_ok=True)
        (confidence_dir / f"{outname}.json").write_text(
            json.dumps({"confidenceScore": values, "meanPlddt": sum(values) / len(values)}, indent=2) + "\n",
            encoding="utf-8",
        )

    inference.download_fasta_utilities = lambda cache: None
    inference.save_structure = save_structure_with_confidence
    inference._revocompute_offline_patched = True


class SimpleFoldPlugin:
    """The science: one SimpleFold protein record per work item."""

    runner = "simplefold"
    runner_version = "1"

    def __init__(
        self,
        params: dict,
        *,
        checkpoint_dir: str,
        ccd_path: str,
        fallback_plans: dict | None = None,
        max_residues: int = DEFAULT_MAX_RESIDUES,
        esm_model_sha256: str = "",
        esm_regression_sha256: str = "",
    ) -> None:
        # Requested science. Copied once and never mutated by an adaptation.
        self.params = dict(params)
        self.checkpoint_dir = str(checkpoint_dir)
        self.ccd_path = str(ccd_path)
        self.declared_plans = dict(fallback_plans or {})
        self.max_residues = int(max_residues)
        self.esm_model_sha256 = str(esm_model_sha256)
        self.esm_regression_sha256 = str(esm_regression_sha256)
        self.model_revision = f"{UPSTREAM_REVISION[:7]}/{self.params['model']}"
        self._fingerprint = ""
        self._announced_sampling = False
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
                    f"torch={getattr(torch, '__version__', 'absent') or 'absent'}",
                    f"cuda={getattr(getattr(torch, 'version', None), 'cuda', '') or 'none'}",
                    f"model={self.model_revision}",
                    "backend=torch",
                )
            )
        return self._fingerprint

    # -- lifecycle ----------------------------------------------------------

    def initialize_runtime(self, execution) -> dict:
        """Load the folding model, optional pLDDT modules, ESM-2, and the utilities once."""
        inference = _import_inference()
        _install_offline_patches(inference)
        args = self._upstream_args()
        model, device = inference.initialize_folding_model(args)
        plddt_latent_module, plddt_out_module = inference.initialize_plddt_module(args, device)
        esm_model, esm_dict, af2_to_esm = inference.initialize_esm_model(args, device)
        tokenizer, featurizer, processor, flow, sampler = inference.initialize_others(args, device)
        torch = _torch()
        baseline_mb = 0
        if torch is not None and torch.cuda.is_available():
            # The model's residency right after it reaches the device is the
            # baseline the estimator factors out of a workload peak.
            baseline_mb = _mb(max(torch.cuda.memory_allocated(), torch.cuda.memory_reserved()))
            torch.cuda.reset_peak_memory_stats()
        return {
            "baseline_mb": baseline_mb,
            "inference": inference,
            "args": args,
            "device": device,
            "model": model,
            "plddt_latent_module": plddt_latent_module,
            "plddt_out_module": plddt_out_module,
            "esm_model": esm_model,
            "esm_dict": esm_dict,
            "af2_to_esm": af2_to_esm,
            "tokenizer": tokenizer,
            "featurizer": featurizer,
            "processor": processor,
            "flow": flow,
            "sampler": sampler,
        }

    def finalize(self, runtime) -> None:
        """Release the model and its device memory; teardown must not rewrite results."""
        runtime.clear()
        _release_transient(_torch())

    def finalize_task(self, output_dir: str, manifest: dict) -> None:
        """No task-level artifact: ``work_items.json`` already is the task summary."""

    # -- one item -----------------------------------------------------------

    def run_item(self, runtime, payload, adjustments, work_dir, execution):
        """Sample one record's structures into ``work_dir`` and measure the peak."""
        torch = _torch()
        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        requested = int(self.params["num_samples"])
        canonical = canonical_adjustments(adjustments)
        plan = resolve_sample_plan(
            requested,
            int(payload.get("order") or 0),
            int(self.params["seed"]),
            canonical,
            self._declared_for(canonical),
        )
        if plan["unapplied"]:
            print(f"SimpleFold ignoring unrealized adjustments: {sorted(plan['unapplied'])}", file=sys.stderr)
        if torch is not None and torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
        try:
            if not self._announced_sampling:
                self._announced_sampling = True
                print("REVODESIGN_STAGE:structure_sampling", flush=True)
            record_fasta = self._write_record_fasta(work_dir, payload)
            # Upstream featurizes a whole file; one record per item is what makes
            # one record one independently committed structure set.
            runtime["inference"].process_fastas(data=[record_fasta], out_dir=work_dir, ccd_path=self.ccd_path)
            prediction_dir = work_dir / f"predictions_{self.params['model']}"
            prediction_dir.mkdir(parents=True, exist_ok=True)
            for group_index, group in enumerate(plan["groups"]):
                self._sample_group(runtime, plan, group_index, group, prediction_dir, work_dir, record_fasta.stem)
                if plan["cache_clear"]:
                    _release_transient(torch)
            promote_input_manifest(work_dir)
            write_run_metadata(
                work_dir,
                build_run_metadata(
                    work_dir=work_dir,
                    model=self.params["model"],
                    parameters=self.params,
                    item={
                        "id": str(payload["id"]),
                        "order": int(payload.get("order") or 0),
                        "length": int(payload.get("length") or 0),
                    },
                    effective_seed=plan["item_seed"],
                    plan=plan,
                    runtime_fingerprint=self.runtime_fingerprint,
                    esm_model_sha256=self.esm_model_sha256,
                    esm_regression_sha256=self.esm_regression_sha256,
                ),
            )
        except Exception as error:  # classified here, never swallowed
            _release_transient(torch)
            if _is_out_of_memory(error):
                return (OUTCOME_OOM, *_cuda_peaks(torch), "CUDA_OOM")
            raise
        return (OUTCOME_SUCCESS, *_cuda_peaks(torch), "")

    def validate_item(self, work_dir, payload, adjustments) -> None:
        """Fail closed unless the item's artifacts are exactly what was requested."""
        if not self._announced_validation:
            self._announced_validation = True
            print("REVODESIGN_STAGE:output_validation", flush=True)
        validate_item_outputs(
            Path(work_dir),
            num_samples=int(self.params["num_samples"]),
            predict_plddt=bool(self.params["predict_plddt"]),
            output_format=self.params["output_format"],
        )

    # -- internals ----------------------------------------------------------

    def _declared_for(self, canonical: dict) -> dict | None:
        return next(
            (declared for declared in self.declared_plans.values() if declared["adjustments"] == canonical),
            None,
        )

    def _sample_group(
        self, runtime, plan: dict, group_index: int, group: dict, prediction_dir: Path, work_dir: Path, record_name: str
    ) -> None:
        """Draw one consecutive group of samples from its own seeded stream."""
        processor = runtime["processor"]
        # The requested samples are drawn as one multiplicity-N batch upstream; a
        # group is that same draw at a smaller multiplicity, so the sample set is
        # the requested one and only the stream grouping differs.
        processor.inference_multiplicity = group["size"]
        runtime["inference"].seed_everything(plan["group_seeds"][group_index])
        batch, structure, record = runtime["inference"].process_one_inference_structure(
            work_dir / "structures" / f"{record_name}.npz",
            work_dir / "records" / f"{record_name}.json",
            runtime["tokenizer"],
            runtime["featurizer"],
            processor,
            runtime["esm_model"],
            runtime["esm_dict"],
            runtime["af2_to_esm"],
        )
        sampled_coord, pad_mask, plddts = runtime["inference"].generate_structure(
            runtime["args"],
            batch,
            runtime["sampler"],
            runtime["flow"],
            processor,
            runtime["model"],
            runtime["plddt_latent_module"],
            runtime["plddt_out_module"],
            runtime["device"],
        )
        for offset in range(group["size"]):
            sample_index = group["start"] + offset
            structure_save = runtime["inference"].process_structure(
                deepcopy(structure), sampled_coord[offset], pad_mask[offset], record, backend="torch"
            )
            runtime["inference"].save_structure(
                structure_save,
                prediction_dir,
                f"{record.id}_sampled_{sample_index}",
                output_format=self.params["output_format"],
                plddts=plddts[offset] if plddts is not None else None,
            )

    def _write_record_fasta(self, work_dir: Path, payload: dict) -> Path:
        """Write the work item's single record as its own FASTA.

        The file stem is the work item's normalized name, and upstream names the
        parsed target after the file stem, so an item's structures, records, and
        output directory all carry the same stable identifier.
        """
        identifier = safe_item_name(str(payload["id"]))
        path = work_dir / f"{identifier}.fasta"
        path.write_text(f">{identifier}\n{payload['sequence']}\n", encoding="utf-8")
        return path

    def _upstream_args(self) -> argparse.Namespace:
        params = self.params
        return argparse.Namespace(
            simplefold_model=params["model"],
            ckpt_dir=self.checkpoint_dir,
            output_dir="",
            num_steps=int(params["num_steps"]),
            tau=float(params["tau"]),
            no_log_timesteps=False,
            fasta_path="",
            nsample_per_protein=int(params["num_samples"]),
            plddt=bool(params["predict_plddt"]),
            output_format=params["output_format"],
            backend="torch",
            seed=int(params["seed"]),
        )

    # -- measurement --------------------------------------------------------

    def runtime_usage(self, runtime) -> tuple[int, int, int]:
        """``(baseline_residency_mb, allocated_mb, reserved_mb)`` on the device.

        The baseline is the model's residency as measured right after it reached
        the device, which is what the server's estimator factors out of a peak.
        """
        torch = _torch()
        baseline = int(runtime.get("baseline_mb") or 0)
        if torch is None or not torch.cuda.is_available():
            return (baseline, 0, 0)
        return (baseline, _mb(torch.cuda.memory_allocated()), _mb(torch.cuda.memory_reserved()))

    def available_vram_mb(self, runtime) -> int:
        torch = _torch()
        if torch is None or not torch.cuda.is_available():
            return 0
        free, _total = torch.cuda.mem_get_info()
        return _mb(free)

    def device_profile(self, runtime) -> dict:
        torch = _torch()
        if torch is None or not torch.cuda.is_available():
            return {
                "vendor": "unknown",
                "model": "unknown",
                "compute_capability": "",
                "total_vram_mb": 1,
                "mig_profile": "",
            }
        properties = torch.cuda.get_device_properties(torch.cuda.current_device())
        name = str(torch.cuda.get_device_name(properties))
        return {
            "vendor": "nvidia",
            "model": name,
            # ``major.minor`` on current torch; older builds expose the same
            # pair as a tuple attribute.
            "compute_capability": (
                f"{properties.major}.{properties.minor}"
                if hasattr(properties, "major")
                else ".".join(str(part) for part in getattr(properties, "compute_capability", ()) or ())
            ),
            "total_vram_mb": _mb(properties.total_memory),
            "mig_profile": name if "MIG" in name.upper() else "",
        }


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run pinned SimpleFold inference as a persistent multi-item task.")
    parser.add_argument("--task-manifest", "-i", required=True, type=Path)
    parser.add_argument("--output-dir", "-o", required=True, type=Path)
    parser.add_argument("--checkpoint-dir", required=True, type=Path)
    parser.add_argument("--ccd-path", required=True, type=Path)
    parser.add_argument("--max-residues", type=int, default=DEFAULT_MAX_RESIDUES)
    parser.add_argument("--esm-model-sha256", default="")
    parser.add_argument("--esm-regression-sha256", default="")
    return parser.parse_args()


def build_plugin(manifest: dict, args: argparse.Namespace) -> SimpleFoldPlugin:
    """Read the manifest's declared plans and requested parameters into a plugin."""
    params = dict(manifest.get("params") or {})
    missing = [name for name in REQUIRED_PARAMS if name not in params]
    if missing:
        raise InputError(f"Task manifest is missing the required SimpleFold parameter(s): {', '.join(missing)}")
    return SimpleFoldPlugin(
        params,
        checkpoint_dir=str(args.checkpoint_dir),
        ccd_path=str(args.ccd_path),
        fallback_plans=declared_plans(manifest.get("resource_adaptation")),
        max_residues=args.max_residues,
        esm_model_sha256=args.esm_model_sha256,
        esm_regression_sha256=args.esm_regression_sha256,
    )


def main() -> None:
    args = parse_args()
    manifest = read_task_manifest(args.task_manifest)
    items, payload = sequence_work_items(
        manifest, "sequence", max_length=args.max_residues, extensions=SEQUENCE_EXTENSIONS
    )
    plugin = build_plugin(manifest, args)
    execute_task(build_config(manifest, "simplefold", items, payload), plugin, output_dir=str(args.output_dir))


if __name__ == "__main__":
    main()
