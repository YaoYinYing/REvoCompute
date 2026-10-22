#!/usr/bin/env python3
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

TASK_MODELS = {"foundry_rfd3_design": "rfd3", "foundry_rfd3na_design": "rfd3na", "foundry_rf3_fold": "rf3"}
PATH_KEYS = {"input", "path", "msa_path", "template_path"}
SHA1_RE = re.compile(r"[0-9a-f]{40}")

#: The one place a declared parameter becomes an upstream Hydra override.  The
#: keys are exactly the owning ``task.yaml`` parameter vocabulary, which the
#: server materializes -- with the schema default and range already applied --
#: into the task manifest before dispatch.  Iterating this table builds the
#: command, so a declared parameter cannot be silently dropped, and a manifest
#: field with no override here is rejected instead of ignored.  The kind is the
#: schema type, used to re-check the value the server already validated.
PARAM_OVERRIDES: dict[str, dict[str, tuple[str, str]]] = {
    "rfd3": {
        "num_designs": ("diffusion_batch_size", "int"),
        "diffusion_steps": ("inference_sampler.num_timesteps", "int"),
        "num_recycles": ("inference_sampler.n_recycle", "int"),
        "seed": ("seed", "int"),
        "low_memory_mode": ("low_memory_mode", "bool"),
        "dump_trajectories": ("dump_trajectories", "bool"),
        "inference_mode": ("inference_mode", "str"),
        "sampler_step_scale": ("inference_sampler.step_scale", "float"),
        "sampler_gamma_0": ("inference_sampler.gamma_0", "float"),
        "classifier_free_guidance": ("inference_sampler.use_classifier_free_guidance", "bool"),
        "centering": ("inference_sampler.center_option", "str"),
    },
    # RFD3NA's ``SampleDiffusionConfig`` has no ``n_recycle`` field and its
    # checkpoint fixes recycling, so RFD3NA declares no recycling control and
    # there is no override to build for one.  ``+inference_sampler.n_recycle``
    # would only append a key its sampler silently drops, which is exactly the
    # false control this adapter must not offer.
    "rfd3na": {
        "num_designs": ("diffusion_batch_size", "int"),
        "diffusion_steps": ("inference_sampler.num_timesteps", "int"),
        "seed": ("seed", "int"),
        "low_memory_mode": ("low_memory_mode", "bool"),
        "dump_trajectories": ("dump_trajectories", "bool"),
        "sampler_step_scale": ("inference_sampler.step_scale", "float"),
        "sampler_gamma_0": ("inference_sampler.gamma_0", "float"),
        "classifier_free_guidance": ("inference_sampler.use_classifier_free_guidance", "bool"),
        "centering": ("inference_sampler.center_option", "str"),
    },
    "rf3": {
        "num_designs": ("diffusion_batch_size", "int"),
        "diffusion_steps": ("num_steps", "int"),
        "num_recycles": ("n_recycles", "int"),
        "seed": ("seed", "int"),
        "early_stopping_plddt_threshold": ("early_stopping_plddt_threshold", "float"),
        "dump_trajectories": ("dump_trajectories", "bool"),
        "template_noise_scale": ("template_noise_scale", "float"),
        "add_missing_atoms": ("add_missing_atoms", "bool"),
        "annotate_b_factor_with_plddt": ("annotate_b_factor_with_plddt", "bool"),
    },
}

#: Overrides this adapter fixes rather than exposing as a user parameter.
FIXED_OVERRIDES: dict[str, tuple[str, ...]] = {
    "rfd3": ("n_batches=1", "prevalidate_inputs=True", "skip_existing=False"),
    "rfd3na": ("n_batches=1", "prevalidate_inputs=True", "skip_existing=False"),
    "rf3": ("skip_existing=False",),
}


def die(message: str) -> None:
    raise SystemExit(message)


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def override_value(params: dict[str, Any], name: str, kind: str) -> str:
    """Render one declared parameter as its upstream Hydra override value.

    The owning ``task.yaml`` schema is the single source of a parameter's
    default and range, and the server applies both into the manifest before
    dispatch, so this adapter never invents a default.  A manifest that omits a
    declared parameter is malformed and fails closed here rather than silently
    falling back to a second, divergent default.
    """
    if name not in params:
        die(f"Missing {name} in the task manifest")
    value = params[name]
    if kind == "int":
        if not isinstance(value, int) or isinstance(value, bool):
            die(f"{name} must be an integer")
        return str(value)
    if kind == "bool":
        if not isinstance(value, bool):
            die(f"{name} must be a boolean")
        return str(value)
    if kind == "str":
        if not isinstance(value, str):
            die(f"{name} must be a string")
        return value
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        die(f"{name} must be a number")
    return f"{float(value):g}"


def load_upstream_identity(path: Path) -> dict[str, str]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        die(f"Invalid Foundry upstream identity: {exc}")
    commit = document.get("upstream_commit")
    distribution = document.get("upstream_distribution")
    version = document.get("upstream_version")
    if not isinstance(commit, str) or not SHA1_RE.fullmatch(commit):
        die("Foundry upstream identity has no immutable commit")
    if not all(isinstance(value, str) and value for value in (distribution, version)):
        die("Foundry upstream identity has no distribution version")
    return {"commit": commit, "distribution": distribution, "version": version}


def normalize_paths(value: Any, files: dict[str, Path]) -> Any:
    if isinstance(value, list):
        return [normalize_paths(item, files) for item in value]
    if not isinstance(value, dict):
        return value
    normalized = {}
    for key, item in value.items():
        if key in PATH_KEYS and isinstance(item, str):
            name = Path(item).name
            if name not in files:
                die(f"Input specification references an unuploaded file: {item}")
            normalized[key] = str(files[name])
        else:
            normalized[key] = normalize_paths(item, files)
    return normalized


def load_manifest(path: Path, output_dir: Path) -> tuple[Path, dict[str, Any], list[dict[str, str]]]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        die(f"Invalid task manifest: {exc}")
    inputs = document.get("inputs")
    params = document.get("params", {})
    if not isinstance(inputs, dict) or len(inputs.get("specification", ())) != 1 or not isinstance(params, dict):
        die("Foundry requires input files and an object of parameters")
    files = inputs["specification"] + inputs.get("assets", [])
    source_paths = [Path(item.get("path", "")).resolve() for item in files if isinstance(item, dict)]
    if len(source_paths) != len(files) or any(not item.is_file() for item in source_paths):
        die("Every Foundry input must be an existing file")
    specification = Path(inputs["specification"][0]["path"]).resolve()
    names = [item.name for item in source_paths]
    if len(names) != len(set(names)):
        die("Foundry input basenames must be unique")
    input_dir = output_dir / "normalized_inputs"
    input_dir.mkdir(parents=True)
    copied = {}
    records = []
    for source in source_paths:
        destination = input_dir / source.name
        if source != specification:
            shutil.copyfile(source, destination)
        copied[source.name] = destination
        records.append({"name": source.name, "sha256": sha256(source)})
    try:
        specification_document = json.loads(specification.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        die(f"Invalid Foundry JSON input specification: {exc}")
    normalized = normalize_paths(specification_document, copied)
    normalized_path = input_dir / "input.json"
    normalized_path.write_text(json.dumps(normalized, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return normalized_path, params, records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-type", required=True, choices=sorted(TASK_MODELS))
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--checkpoint", required=True, type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    normalized, params, inputs = load_manifest(args.manifest, args.output_dir)
    model = TASK_MODELS[args.task_type]
    overrides = PARAM_OVERRIDES[model]
    upstream = load_upstream_identity(
        Path(os.environ.get("FOUNDRY_UPSTREAM_MANIFEST", "/app/revocompute/upstream.json"))
    )
    unknown_params = sorted(set(params) - set(overrides))
    if unknown_params:
        die(f"Unsupported {args.task_type} parameters: {', '.join(unknown_params)}")
    command = [os.environ.get("FOUNDRY_EXECUTABLE", model), "design" if model != "rf3" else "fold"]
    command.extend([f"inputs={normalized}", f"out_dir={args.output_dir}", f"ckpt_path={args.checkpoint}"])
    command.extend(FIXED_OVERRIDES[model])
    # Every declared parameter becomes exactly one override, so the invocation
    # cannot drift from the schema the user was shown.
    parameter_overrides = []
    for name, (key, kind) in overrides.items():
        parameter_overrides.append(f"{key}={override_value(params, name, kind)}")
    command.extend(parameter_overrides)
    provenance = {
        "task_type": args.task_type,
        "model": model,
        "upstream": upstream,
        "checkpoint": {"name": args.checkpoint.name, "sha256": sha256(args.checkpoint)},
        "inputs": inputs,
        "parameters": params,
        "upstream_overrides": dict(
            item.split("=", 1) for item in (*FIXED_OVERRIDES[model], *parameter_overrides)
        ),
        "runtime_network": False,
    }
    (args.output_dir / "foundry-run.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    completed = subprocess.run(command, cwd=os.environ.get("FOUNDRY_SOURCE_ROOT", "/opt/foundry"), check=False)
    raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
