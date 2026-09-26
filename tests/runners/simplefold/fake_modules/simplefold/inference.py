# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""A CPU-only stand-in for the pinned ``simplefold`` package.

It mirrors the upstream call seams the SimpleFold plugin binds to:
``initialize_*`` model loaders (one call per task), ``seed_everything``,
``process_fastas`` (one ``structures/<name>.npz`` plus ``records/<name>.json``
plus ``manifest.json`` per input file), ``process_one_inference_structure``,
``generate_structure`` (one ``randn_like`` draw per target), ``process_structure``
and ``save_structure``. Behavior is driven by environment variables so a test can
count model loads, fail a record, or reproduce a CUDA OOM deterministically.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# -- instrumentation --------------------------------------------------------


def _counter_path(name: str) -> Path | None:
    root = os.environ.get("SIMPLEFOLD_FAKE_STATE")
    return Path(root) / f"{name}.count" if root else None


def _bump(name: str) -> int:
    path = _counter_path(name)
    if path is None:
        return 0
    count = int(path.read_text()) + 1 if path.exists() else 1
    path.write_text(str(count))
    return count


def fake_loads() -> int:
    path = _counter_path("loads")
    return int(path.read_text()) if path and path.exists() else 0


def fake_seeds() -> list[int]:
    path = _counter_path("seeds")
    return [int(value) for value in path.read_text().split()] if path and path.exists() else []


def _failing_records() -> set[str]:
    return {value for value in os.environ.get("SIMPLEFOLD_FAKE_FAIL_RECORDS", "").split(",") if value}


def _oom_multiplicity() -> int:
    return int(os.environ.get("SIMPLEFOLD_FAKE_OOM_MULTIPLICITY", "0") or 0)


class OutOfMemoryError(RuntimeError):
    """Stands in for ``torch.cuda.OutOfMemoryError`` in the fake environment."""


def install_fake_torch() -> None:
    """Give the plugin the exception type its OOM classification looks for."""
    import types

    import sys

    if "torch" in sys.modules:
        return
    torch = types.ModuleType("torch")
    cuda = types.ModuleType("torch.cuda")
    cuda.OutOfMemoryError = OutOfMemoryError
    cuda.is_available = lambda: False
    cuda.mem_get_info = lambda: (0, 0)
    torch.cuda = cuda
    sys.modules["torch"] = torch
    sys.modules["torch.cuda"] = cuda


# -- upstream call seams ----------------------------------------------------


def seed_everything(seed: int, workers: bool = False) -> None:
    path = _counter_path("seeds")
    if path is not None:
        previous = path.read_text() if path.exists() else ""
        path.write_text(f"{previous}{seed}\n")


def initialize_folding_model(args):
    _bump("loads")
    return ("folding", args.simplefold_model), "cpu"


def initialize_plddt_module(args, device):
    if not args.plddt:
        return None, None
    _bump("loads")
    return "plddt_latent", "plddt_out"


def initialize_esm_model(args, device):
    _bump("loads")
    return "esm_model", {"alphabet": "esm"}, "af2_to_esm"


def initialize_others(args, device):
    _bump("loads")
    return "tokenizer", "featurizer", ProteinDataProcessor(args.backend), "flow", "sampler"


class ProteinDataProcessor:
    """The one piece of runtime state a sample group changes: the multiplicity."""

    def __init__(self, backend: str) -> None:
        self.backend = backend
        self.inference_multiplicity = 1


def download_fasta_utilities(cache) -> None:
    raise RuntimeError("network downloader was called")


def process_fastas(*, data, out_dir, ccd_path) -> None:
    out_dir = Path(out_dir)
    (out_dir / "ccd-used.txt").write_text(str(ccd_path), encoding="utf-8")
    (out_dir / "structures").mkdir(parents=True, exist_ok=True)
    (out_dir / "records").mkdir(parents=True, exist_ok=True)
    for path in data:
        name = Path(path).stem
        (out_dir / "structures" / f"{name}.npz").write_text("structure", encoding="utf-8")
        (out_dir / "records" / f"{name}.json").write_text('{"id": "%s"}' % name, encoding="utf-8")
    (out_dir / "manifest.json").write_text(json.dumps({"records": [Path(p).stem for p in data]}), encoding="utf-8")


def process_one_inference_structure(
    structure_path, record_path, tokenizer, featurizer, processor, esm_model=None, esm_dict=None, af2_to_esm=None
):
    del tokenizer, featurizer, esm_model, esm_dict, af2_to_esm
    if not Path(structure_path).is_file() or not Path(record_path).is_file():
        raise FileNotFoundError(f"missing processed input for {record_path}")

    class Record:
        id = Path(record_path).stem

    class Batch:
        token_count = 4

    return Batch(), "structure", Record()


def generate_structure(args, batch, sampler, flow, processor, model, plddt_latent_module, plddt_out_module, device):
    del batch, sampler, flow, model, plddt_latent_module, plddt_out_module, device
    multiplicity = max(1, int(processor.inference_multiplicity))
    if _oom_multiplicity() and multiplicity >= _oom_multiplicity():
        raise OutOfMemoryError("CUDA out of memory. Tried to allocate 64.00 MiB (GPU 0; 39.39 GiB total capacity)")
    sampled = [[float(index)] for index in range(multiplicity)]
    pad_mask = [[True] for _ in range(multiplicity)]
    # Upstream returns no pLDDT unless the confidence head was requested.
    plddts = [PerResiduePlddt([81.0, 93.0]) for _ in range(multiplicity)] if args.plddt else None
    return sampled, pad_mask, plddts


class PerResiduePlddt:
    def __init__(self, values: list[float]) -> None:
        self.values = list(values)

    def detach(self):
        return self

    def cpu(self):
        return self

    def tolist(self) -> list[float]:
        return list(self.values)


def process_structure(structure, coords, mask, record, backend="torch"):
    del backend
    return {"structure": structure, "coords": coords, "mask": mask, "id": record.id}


def save_structure(structure, save_dir, outname, output_format="mmcif", plddts=None) -> None:
    suffix = ".cif" if output_format == "mmcif" else ".pdb"
    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    if structure["id"] in _failing_records():
        raise RuntimeError(f"inference failed for {structure['id']}")
    (save_dir / f"{outname}{suffix}").write_text("data_target\n", encoding="utf-8")
    if plddts is None:
        return
    values = plddts.detach().cpu().tolist()
    confidence = save_dir.parent / "confidence"
    confidence.mkdir(parents=True, exist_ok=True)
    (confidence / f"{outname}.json").write_text(
        json.dumps({"confidenceScore": values, "meanPlddt": sum(values) / len(values)}), encoding="utf-8"
    )
