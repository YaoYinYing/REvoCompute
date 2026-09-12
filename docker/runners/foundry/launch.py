#!/usr/bin/env python3
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

TASK_MODELS = {"foundry_rfd3_design": "rfd3", "foundry_rfd3na_design": "rfd3na", "foundry_rf3_fold": "rf3"}
PATH_KEYS = {"input", "path", "msa_path", "template_path"}


def die(message: str) -> None:
    raise SystemExit(message)


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def integer(params: dict[str, Any], name: str, default: int, minimum: int, maximum: int) -> int:
    value = params.get(name, default)
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        die(f"{name} must be an integer between {minimum} and {maximum}")
    return value


def boolean(params: dict[str, Any], name: str, default: bool) -> bool:
    value = params.get(name, default)
    if not isinstance(value, bool):
        die(f"{name} must be a boolean")
    return value


def number(params: dict[str, Any], name: str, default: float, minimum: float, maximum: float) -> float:
    value = params.get(name, default)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not minimum <= float(value) <= maximum:
        die(f"{name} must be a number between {minimum} and {maximum}")
    return float(value)


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
    files = document.get("files")
    params = document.get("params", {})
    if not isinstance(files, list) or not files or not isinstance(params, dict):
        die("Foundry requires input files and an object of parameters")
    source_paths = [Path(item.get("path", "")).resolve() for item in files if isinstance(item, dict)]
    if len(source_paths) != len(files) or any(not item.is_file() for item in source_paths):
        die("Every Foundry input must be an existing file")
    json_files = [item for item in source_paths if item.suffix.lower() == ".json"]
    if len(json_files) != 1:
        die("Foundry requires exactly one JSON input specification")
    names = [item.name for item in source_paths]
    if len(names) != len(set(names)):
        die("Foundry input basenames must be unique")
    input_dir = output_dir / "normalized_inputs"
    input_dir.mkdir(parents=True)
    copied = {}
    records = []
    for source in source_paths:
        destination = input_dir / source.name
        if source != json_files[0]:
            shutil.copyfile(source, destination)
        copied[source.name] = destination
        records.append({"name": source.name, "sha256": sha256(source)})
    try:
        specification = json.loads(json_files[0].read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        die(f"Invalid Foundry JSON input specification: {exc}")
    normalized = normalize_paths(specification, copied)
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
    allowed_params = {"num_designs", "diffusion_steps", "num_recycles", "seed", "dump_trajectories"}
    allowed_params.add("early_stopping_plddt_threshold" if model == "rf3" else "low_memory_mode")
    unknown_params = sorted(set(params) - allowed_params)
    if unknown_params:
        die(f"Unsupported {args.task_type} parameters: {', '.join(unknown_params)}")
    designs = integer(params, "num_designs", 1, 1, 8)
    steps = integer(params, "diffusion_steps", 50, 1, 200)
    recycles = integer(params, "num_recycles", 2 if model != "rf3" else 5, 1, 20)
    seed = integer(params, "seed", 0, 0, 2_147_483_647)
    trajectories = boolean(params, "dump_trajectories", False)
    command = [os.environ.get("FOUNDRY_EXECUTABLE", model), "design" if model != "rf3" else "fold"]
    command.extend([f"inputs={normalized}", f"out_dir={args.output_dir}", f"ckpt_path={args.checkpoint}"])
    if model == "rf3":
        threshold = number(params, "early_stopping_plddt_threshold", 0.5, 0.0, 1.0)
        command.extend(
            [
                f"diffusion_batch_size={designs}",
                f"num_steps={steps}",
                f"n_recycles={recycles}",
                f"seed={seed}",
                f"early_stopping_plddt_threshold={threshold:g}",
            ]
        )
    else:
        low_memory = boolean(params, "low_memory_mode", False)
        command.extend(
            [
                f"diffusion_batch_size={designs}",
                "n_batches=1",
                f"inference_sampler.num_timesteps={steps}",
                f"inference_sampler.n_recycle={recycles}",
                f"seed={seed}",
                f"low_memory_mode={str(low_memory)}",
                "prevalidate_inputs=True",
            ]
        )
    command.extend(["skip_existing=False", f"dump_trajectories={str(trajectories)}"])
    provenance = {
        "task_type": args.task_type,
        "model": model,
        "upstream_commit": "b02eed6a6bdf8f44d14a80cc36e3da13c9f2291c",
        "checkpoint": {"name": args.checkpoint.name, "sha256": sha256(args.checkpoint)},
        "inputs": inputs,
        "parameters": params,
        "runtime_network": False,
    }
    (args.output_dir / "foundry-run.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    completed = subprocess.run(command, cwd=os.environ.get("FOUNDRY_SOURCE_ROOT", "/opt/foundry"), check=False)
    raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
