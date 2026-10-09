# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""A CPU-only stand-in for the pinned ``esm.models.esmfold2`` package.

It mirrors the call seams the ESMFold 2 plugin binds to: the model loader (one
call per task, counted), ``set_kernel_backend``, ``ESMFold2InputBuilder.fold``
(one call per sample group), ``write_sample``'s result surface, and the MSA
loader. Behavior is driven by environment variables so a test can count model
loads, fail one record, or reproduce a deterministic CUDA OOM, and every
``fold`` call's parameters are recorded verbatim so a test can assert the
requested science reached the model unchanged.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# -- instrumentation --------------------------------------------------------


def _state_dir() -> Path | None:
    root = os.environ.get("ESMFOLD2_FAKE_STATE")
    return Path(root) if root else None


def _record_call(name: str, payload) -> None:
    root = _state_dir()
    if root is None:
        return
    path = root / f"{name}.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def fake_loads() -> int:
    root = _state_dir()
    path = root / "loads.count" if root else None
    return int(path.read_text()) if path is not None and path.exists() else 0


def fake_folds() -> list[dict]:
    root = _state_dir()
    path = root / "folds.jsonl" if root else None
    if path is None or not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def fake_backends() -> list[str]:
    root = _state_dir()
    path = root / "backends.jsonl" if root else None
    if path is None or not path.exists():
        return []
    return [json.loads(line)["backend"] for line in path.read_text(encoding="utf-8").splitlines() if line]


def _failing_records() -> set[str]:
    return {value for value in os.environ.get("ESMFOLD2_FAKE_FAIL_RECORDS", "").split(",") if value}


def _oom_at() -> int:
    """Fold call index (1-based) that reproduces a CUDA OOM; 0 disables it."""
    return int(os.environ.get("ESMFOLD2_FAKE_OOM_AT", "0") or 0)


def _oom_always() -> bool:
    return os.environ.get("ESMFOLD2_FAKE_OOM_ALWAYS") == "1"


class OutOfMemoryError(RuntimeError):
    """Stands in for ``torch.cuda.OutOfMemoryError`` in the fake environment."""


class _FakeAllocator:
    """The small slice of ``torch.cuda`` the plugin measures through.

    A real device is not required to exercise the plugin: the numbers are
    deterministic, and a test asserts they flow into the observation unchanged.
    """

    OutOfMemoryError = OutOfMemoryError

    def __init__(self) -> None:
        self.allocated = 1024 * 1024 * 2048
        self.reserved = 1024 * 1024 * 2560
        self.peak_allocated = 1024 * 1024 * 4096
        self.peak_reserved = 1024 * 1024 * 4608
        self.free = 1024 * 1024 * 30000
        self.emptied = 0

    def is_available(self) -> bool:
        return True

    def memory_allocated(self) -> int:
        return self.allocated

    def memory_reserved(self) -> int:
        return self.reserved

    def max_memory_allocated(self) -> int:
        return self.peak_allocated

    def max_memory_reserved(self) -> int:
        return self.peak_reserved

    def reset_peak_memory_stats(self) -> None:
        self.peak_allocated = self.allocated
        self.peak_reserved = self.reserved

    def empty_cache(self) -> None:
        self.emptied += 1

    def mem_get_info(self):
        return (self.free, 1024 * 1024 * 40960)

    def current_device(self) -> int:
        return 0

    def get_device_name(self, index=0):
        del index
        return "NVIDIA A100-PCIE-40GB"

    def get_device_capability(self, index=0):
        del index
        return (8, 0)

    def get_device_properties(self, index=0):
        del index

        class Properties:
            total_memory = 1024 * 1024 * 40960

        return Properties()


def install_fake_torch() -> None:
    """Give the plugin the allocator surface it measures through."""
    import sys
    import types

    torch = sys.modules.get("torch") or types.ModuleType("torch")
    torch.__version__ = "2.11.0+cu128"
    torch.version = types.SimpleNamespace(cuda="12.8")
    torch.cuda = _FakeAllocator()
    sys.modules["torch"] = torch
    sys.modules["torch.cuda"] = torch.cuda


# -- upstream call seams ----------------------------------------------------


class EsmFold2Config:
    def __init__(self) -> None:
        self.esmc_id = ""

    @classmethod
    def from_pretrained(cls, local_dir, **overrides):
        del local_dir, overrides
        return cls()


def default_module_flags(local_dir):
    del local_dir
    return {}


class EsmFold2Model:
    """The loader counts itself; the instance records the backend it is set to."""

    def __init__(self) -> None:
        self.backend = "cuequivariance"

    @classmethod
    def from_pretrained(cls, model_dir, config=None, device=None, esmc_precision=None):
        del model_dir, config, device, esmc_precision
        root = _state_dir()
        if root is not None:
            path = root / "loads.count"
            path.write_text(str(int(path.read_text()) + 1 if path.exists() else 1))
        return cls()

    def eval(self):
        return self

    def set_kernel_backend(self, backend) -> None:
        # Upstream spells the reference path as ``None``; record the semantic
        # name so a test reads the backend the model was actually set to.
        self.backend = "reference" if backend is None else backend
        _record_call("backends", {"backend": self.backend})


class ProteinInput:
    def __init__(self, id, sequence, msa=None, modifications=None) -> None:  # noqa: A002
        self.id = id
        self.sequence = sequence
        self.msa = msa
        self.modifications = modifications


class StructurePredictionInput:
    def __init__(self, sequences, **rest) -> None:
        self.sequences = list(sequences)
        self.rest = rest


class MSA:
    def __init__(self, path) -> None:
        self.path = str(path)

    @classmethod
    def from_a3m(cls, path, remove_insertions=False, max_sequences=None):
        del remove_insertions, max_sequences
        if not Path(path).is_file():
            raise FileNotFoundError(f"A3M not found: {path}")
        return cls(path)


class _Complex:
    def to_mmcif(self) -> str:
        return "data_esmfold2\n"


class FakeResult:
    """The result surface ``write_sample`` consumes."""

    def __init__(self, index: int, length: int) -> None:
        self.complex = _Complex()
        self.plddt = _Tensor([0.7 + 0.01 * index] * length)
        self.pae = _Tensor([[float(index)]] * length)
        self.ptm = 0.5
        self.iptm = None
        self.output_embedding_pair_pooled = _Tensor([0.1, 0.2])


class _Tensor:
    def __init__(self, values) -> None:
        self.values = values

    def detach(self):
        return self

    def float(self):
        return self

    def cpu(self):
        return self

    def tolist(self):
        return self.values

    def numpy(self):
        import numpy

        return numpy.asarray(self.values)


class ESMFold2InputBuilder:
    """``fold`` is the one seam a work item drives; every call is recorded."""

    def __init__(self, ccd_cache=None) -> None:
        del ccd_cache
        self.folds = 0

    def fold(self, model, input, **kwargs):  # noqa: A002
        self.folds += 1
        chain = input.sequences[0]
        _record_call(
            "folds",
            {
                "call": self.folds,
                "model_backend": model.backend,
                "id": chain.id,
                "sequence": chain.sequence,
                "msa": chain.msa.path if chain.msa is not None else None,
                **kwargs,
            },
        )
        count = int(kwargs["num_diffusion_samples"])
        if _oom_always() or (_oom_at() and self.folds == _oom_at()):
            raise OutOfMemoryError(
                "CUDA out of memory. Tried to allocate 64.00 MiB (GPU 0; 39.39 GiB total capacity)"
            )
        if chain.id in _failing_records():
            raise RuntimeError(f"inference failed for {chain.id}")
        samples = [FakeResult(index, len(chain.sequence)) for index in range(1, count + 1)]
        return samples[0] if count == 1 else samples


def clean_esmfold2_input(value):  # pragma: no cover - parity with upstream
    return value


__all__ = [
    "MSA",
    "ESMFold2InputBuilder",
    "EsmFold2Config",
    "EsmFold2Model",
    "ProteinInput",
    "StructurePredictionInput",
    "clean_esmfold2_input",
    "default_module_flags",
    "install_fake_torch",
]
