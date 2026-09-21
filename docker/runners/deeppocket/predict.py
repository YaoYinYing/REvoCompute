#!/usr/bin/env python3
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Drive the pinned DeepPocket inference path against read-only checkpoints.

DeepPocket is applied as its upstream ``predict.py`` defines it: hetero-atom
removal, fpocket candidate generation, mass-weighted candidate centres,
gninatypes/conversion for the classifier, CNN reranking, then U-Net
segmentation of the top-ranked pockets. This adapter resolves the named input
role and the Task parameters from the immutable manifest, arranges the upstream
module imports in the order the pinned binary extension requires, invokes the
upstream step functions, and records the run provenance.

The classification and segmentation checkpoints are operator-owned immutable
resources; no Task parameter selects them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

DEFAULTS = {
    "top_pockets": 3,
    "segmentation_threshold": 0.5,
    "mask_to_residue_distance": 3.5,
    "volume_monte_carlo_iterations": 300,
}

# The pinned molgrid wheel is built against Boost.Python and aborts at import
# when torch has not been imported first. Importing torch here, before the
# upstream modules pull molgrid in, keeps the order deterministic.
import torch  # noqa: E402  (import order is load-bearing)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_manifest(path: Path) -> dict[str, object]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Invalid task manifest: {exc}") from exc
    structures = document.get("inputs", {}).get("structure")
    if not isinstance(structures, list) or len(structures) != 1:
        raise SystemExit("DeepPocket requires exactly one structure input")
    params = document.get("params", {})
    if not isinstance(params, dict):
        raise SystemExit("Task params must be an object")
    unsupported = sorted(set(params) - set(DEFAULTS))
    if unsupported:
        raise SystemExit(f"Unsupported DeepPocket parameters: {', '.join(unsupported)}")
    return params


def _resolve_parameters(params: dict[str, object]) -> dict[str, object]:
    resolved: dict[str, object] = {}
    for name, default in DEFAULTS.items():
        value = params.get(name, default)
        if isinstance(default, int):
            if not isinstance(value, int) or isinstance(value, bool):
                raise SystemExit(f"{name} must be an integer")
        elif not isinstance(value, (int, float)) or isinstance(value, bool):
            raise SystemExit(f"{name} must be a number")
        resolved[name] = value
    if not 1 <= resolved["top_pockets"] <= 50:
        raise SystemExit("top_pockets must be between 1 and 50")
    if not 0.0 < resolved["segmentation_threshold"] < 1.0:
        raise SystemExit("segmentation_threshold must be between 0 and 1")
    if not 0.1 <= resolved["mask_to_residue_distance"] <= 20.0:
        raise SystemExit("mask_to_residue_distance must be between 0.1 and 20")
    return resolved


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--structure", required=True, type=Path)
    parser.add_argument("--name", required=True)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--asset-root", required=True, type=Path)
    parser.add_argument("--manifest", type=Path, default=Path(os.environ.get("TASK_MANIFEST", "")))
    args = parser.parse_args()

    params = _resolve_parameters(_load_manifest(args.manifest))
    source_root = Path(os.environ.get("DEEPPOCKET_SOURCE_ROOT", "/opt/deeppocket"))
    if not (source_root / "predict.py").is_file():
        raise SystemExit(f"DeepPocket source is missing: {source_root}")

    class_checkpoint = args.asset_root / "checkpoints/classification_models/first_model_fold1_best_test_auc_85001.pth.tar"
    seg_checkpoint = args.asset_root / "checkpoints/segmentation_models/seg0_best_test_IOU_91.pth.tar"
    for checkpoint in (class_checkpoint, seg_checkpoint):
        if not checkpoint.is_file():
            raise SystemExit(f"DeepPocket checkpoint is missing: {checkpoint}")

    # The upstream modules are plain top-level scripts that import each other by
    # bare name, so the pinned checkout has to be the working tree and first on
    # sys.path exactly as upstream's own predict.py invocation does it.
    shutil.copyfile(args.structure, args.workspace / args.name)
    sys.path.insert(0, str(source_root))
    os.chdir(args.workspace)

    from clean_pdb import clean_pdb  # noqa: E402
    from get_centers import get_centers  # noqa: E402
    from types_and_gninatyper import create_types, gninatype  # noqa: E402

    fpocket = os.environ.get("DEEPPOCKET_FPOCKET", "fpocket")
    invocation = _run_pipeline(
        name=args.name,
        workspace=args.workspace,
        output_dir=args.output_dir,
        class_checkpoint=class_checkpoint,
        seg_checkpoint=seg_checkpoint,
        params=params,
        fpocket=fpocket,
        clean_pdb=clean_pdb,
        get_centers=get_centers,
        gninatype=gninatype,
        create_types=create_types,
    )

    (args.output_dir / "deeppocket-run.json").write_text(
        json.dumps(
            {
                "task_type": "deeppocket",
                "upstream_commit": "04ba9f564a81dbf35c6afbb1db5fb9ca255cedc0",
                "fpocket_revision": "4bb0d8447f62fee77e2c3c29f54b5fcaf5e2c066",
                "fpocket_release": "4.2.3",
                "runtime_network": False,
                "input_structure": {"name": args.name, "sha256": _sha256(args.structure)},
                "parameters": params,
                "checkpoints": {
                    "classification": {
                        "path": str(class_checkpoint.relative_to(args.asset_root)),
                        "sha256": _sha256(class_checkpoint),
                    },
                    "segmentation": {
                        "path": str(seg_checkpoint.relative_to(args.asset_root)),
                        "sha256": _sha256(seg_checkpoint),
                    },
                },
                "steps": invocation,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _run_pipeline(**kwargs: object) -> list[str]:
    """Execute the upstream steps in upstream order and return the step names run."""
    import subprocess

    name: str = kwargs["name"]  # type: ignore[assignment]
    workspace: Path = kwargs["workspace"]  # type: ignore[assignment]
    output_dir: Path = kwargs["output_dir"]  # type: ignore[assignment]
    params: dict[str, object] = kwargs["params"]  # type: ignore[assignment]
    fpocket: str = kwargs["fpocket"]  # type: ignore[assignment]
    clean_pdb = kwargs["clean_pdb"]
    get_centers = kwargs["get_centers"]
    gninatype = kwargs["gninatype"]
    create_types = kwargs["create_types"]

    stem = Path(name).stem
    steps = ["clean_pdb"]

    # 1. Hetero-atom removal, exactly as upstream clean_pdb performs it.
    nowat = workspace / f"{stem}_nowat.pdb"
    clean_pdb(str(workspace / name), str(nowat))

    # 2. fpocket candidate generation.
    completed = subprocess.run([fpocket, "-f", nowat.name, "-v", str(params["volume_monte_carlo_iterations"])], cwd=workspace, check=False)
    if completed.returncode != 0:
        raise SystemExit(f"fpocket failed with exit status {completed.returncode}")
    pockets_dir = workspace / f"{stem}_nowat_out" / "pockets"
    if not pockets_dir.is_dir():
        raise SystemExit(f"fpocket produced no pocket directory: {pockets_dir}")
    steps.append("fpocket")

    # 3. Mass-weighted candidate centres.
    get_centers(str(pockets_dir))
    barycenters = pockets_dir / "bary_centers.txt"
    if not barycenters.is_file():
        raise SystemExit("DeepPocket produced no candidate pocket centres")
    steps.append("get_centers")

    # 4. gninatypes conversion plus the types file the classifier/grid maker reads.
    protein_gninatypes = gninatype(str(nowat))
    class_types = create_types(str(barycenters), protein_gninatypes)
    steps.append("types_and_gninatyper")

    # 5. CNN reranking and 6. segmentation, in that order, using the upstream
    #    classifier and segmentation modules unchanged.
    ranked, confidences = _rank_pockets(class_types, kwargs["class_checkpoint"], params)
    steps.append("rank_pockets")
    _segment(ranked, kwargs["seg_checkpoint"], stem, output_dir, params)
    steps.append("segment_pockets")

    (output_dir / "pocket_confidence.txt").write_text(
        "\n".join(f"{value:g}" for value in confidences) + "\n", encoding="utf-8"
    )
    return steps


def _rank_pockets(class_types: str, checkpoint: Path, params: dict[str, object]) -> tuple[str, list[float]]:
    """Score candidate pockets with the pinned classifier and write the ranked order."""
    import torch.nn as nn  # noqa: F401  (upstream Model uses nn modules)

    from model import Model
    from rank_pockets import test_model

    types_lines = Path(class_types).read_text(encoding="utf-8").splitlines(keepends=True)
    batch_size = min(len(types_lines), 50)
    if batch_size == 0:
        raise SystemExit("DeepPocket found no candidate pockets to rank")

    import molgrid

    class_model = Model()
    class_model.cuda()
    class_model.load_state_dict(torch.load(str(checkpoint), map_location="cpu")["model_state_dict"])
    provider = molgrid.ExampleProvider(
        shuffle=False, stratify_receptor=False, labelpos=0, balanced=False,
        iteration_scheme=molgrid.IterationScheme.LargeEpoch, default_batch_size=batch_size,
    )
    provider.populate(class_types)
    grid_maker = molgrid.GridMaker()

    _, probabilities = test_model(class_model, provider, grid_maker, batch_size)
    paired = sorted(zip(probabilities[:len(types_lines)], types_lines), reverse=True)
    ranked_types = [line for _, line in paired]
    confidences = [float(score) for score, _ in paired]

    ranked_path = class_types.replace(".types", "_ranked.types")
    Path(ranked_path).write_text("".join(ranked_types), encoding="utf-8")
    return ranked_path, confidences


def _segment(ranked_types: str, checkpoint: Path, stem: str, output_dir: Path, params: dict[str, object]) -> None:
    """Run the pinned U-Net segmentation on the top-ranked pockets."""
    from segment_pockets import parse_args as segment_parse_args
    from segment_pockets import test as segment_test
    from segment_pockets import get_model_gmaker_eproviders
    from unet import Unet

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    search = [
        "--test_types", ranked_types,
        "--model_weights", str(checkpoint),
        "--dx_name", str(output_dir / stem),
        "--protein", str(Path(ranked_types).with_name(f"{stem}_nowat.pdb")),
        "-r", str(params["top_pockets"]),
        "-t", f"{params['segmentation_threshold']:g}",
        "--mask_dist", f"{params['mask_to_residue_distance']:g}",
    ]
    args, _ = segment_parse_args(search)
    grid_maker, provider = get_model_gmaker_eproviders(args)
    model = Unet(args.num_classes, args.upsample)
    model.to(device)
    model.load_state_dict(torch.load(str(checkpoint), map_location="cpu")["model_state_dict"])
    model = torch.nn.DataParallel(model)
    segment_test(model, provider, grid_maker, device, args.dx_name, args)


if __name__ == "__main__":
    main()
