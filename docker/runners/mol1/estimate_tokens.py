# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Conservative Mol-1 token estimate used before the checkpoint is loaded.

Mol-1 tokenizes each standard polymer residue as one token and each heavy atom
of a ligand, ion, or modified residue as one token. The estimate mirrors that
rule from the input JSON. It is deliberately an upper bound for modified
residues and FILE_ ligands: the reference atom array drops some hydrogens and
leaving atoms, while this count does not. Device memory grows roughly with the
square of the token count, so an upper-bound admission check never admits a
system larger than the number it reports.
"""

from __future__ import annotations

import argparse
import json
import pickle
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class TokenEstimateError(ValueError):
    """The input cannot be sized without a ligand or CCD reference."""


@dataclass(frozen=True)
class TokenEstimate:
    total: int
    by_job: dict[str, int]


class CcdAtomCounts:
    """Lazy heavy-atom counts from the operator's RDKit CCD cache.

    The cache maps each CCD code to an RDKit molecule. It is only loaded when a
    CCD code is encountered, so a polymer- or SMILES-only input never pays for
    the 149 MiB cache.
    """

    def __init__(self, cache_path: str | Path | None) -> None:
        self._cache_path = Path(cache_path) if cache_path else None
        self._molecules: Mapping[str, Any] | None = None
        self._counts: dict[str, int] = {}

    def heavy_atoms(self, code: str) -> int:
        if code in self._counts:
            return self._counts[code]
        if self._molecules is None:
            if self._cache_path is None or not self._cache_path.is_file():
                raise TokenEstimateError(
                    f"CCD code {code!r} needs the operator's RDKit CCD cache; "
                    "set MOL_ROOT_DIR or MOL1_CCD_CACHE"
                )
            try:
                with self._cache_path.open("rb") as handle:
                    mapping = pickle.load(handle)
            except (OSError, pickle.UnpicklingError) as exc:
                raise TokenEstimateError(f"Could not read the RDKit CCD cache: {exc}") from exc
            if not isinstance(mapping, Mapping):
                raise TokenEstimateError("The RDKit CCD cache is not a code-to-molecule mapping")
            self._molecules = mapping
        molecule = self._molecules.get(code)
        if molecule is None:
            raise TokenEstimateError(f"CCD code {code!r} is absent from the operator's CCD cache")
        try:
            count = sum(1 for atom in molecule.GetAtoms() if atom.GetAtomicNum() > 1)
        except AttributeError as exc:
            raise TokenEstimateError(f"CCD code {code!r} has no readable RDKit molecule") from exc
        self._counts[code] = count
        return count


def _rdkit_heavy_atoms(value: str, is_file: bool, path: str | None = None) -> int:
    try:
        from rdkit import Chem
    except ImportError as exc:  # pragma: no cover - the runner image installs rdkit
        raise TokenEstimateError("RDKit is required to size a ligand") from exc
    try:
        if is_file:
            suffix = Path(path or "").suffix.lower()
            readers = {
                ".sdf": Chem.MolFromMolFile,
                ".mol2": Chem.MolFromMol2File,
                ".pdb": Chem.MolFromPDBFile,
            }
            reader = readers.get(suffix)
            if reader is None:
                raise TokenEstimateError(f"Unsupported ligand file format: {suffix or '(none)'}")
            molecule = reader(str(path), sanitize=True, removeHs=False)
            atoms = len(molecule.GetAtoms()) if molecule is not None else 0
        else:
            molecule = Chem.MolFromSmiles(value)
            atoms = sum(1 for atom in molecule.GetAtoms() if atom.GetAtomicNum() > 1) if molecule is not None else 0
    except TokenEstimateError:
        raise
    except Exception as exc:
        raise TokenEstimateError(f"Could not parse ligand: {value[:80]}") from exc
    if not molecule or atoms < 1:
        raise TokenEstimateError(f"Could not parse ligand: {value[:80]}")
    return atoms


def _ccd_code(value: str) -> str:
    return value[len("CCD_") :] if value.startswith("CCD_") else value


def _ligand_atoms(
    description: str,
    ccd: CcdAtomCounts,
    rdkit_loader: Callable[[str, bool, str | None], int],
) -> int:
    if description.startswith("CCD_"):
        return sum(ccd.heavy_atoms(code) for code in description[len("CCD_") :].split("_"))
    if description.startswith("FILE_"):
        path = description[len("FILE_") :]
        return rdkit_loader(description, True, path)
    return rdkit_loader(description, False, None)


def estimate(
    document: list[dict[str, Any]],
    ccd: CcdAtomCounts,
    rdkit_loader: Callable[[str, bool, str | None], int] = _rdkit_heavy_atoms,
) -> TokenEstimate:
    """Return the estimated total and per-job token counts."""
    by_job: dict[str, int] = {}
    for index, job in enumerate(document):
        job_tokens = 0
        for entry in job.get("sequences") or []:
            entity_type, entity = next(iter(entry.items()))
            count = int(entity["count"])
            if entity_type in {"proteinChain", "dnaSequence", "rnaSequence"}:
                modifications = entity.get("modifications") or []
                residues = len(entity["sequence"]) - len(modifications)
                modified = sum(
                    ccd.heavy_atoms(_ccd_code(item.get("ptmType") or item.get("modificationType")))
                    for item in modifications
                )
                job_tokens += count * (residues + modified)
            elif entity_type == "ligand":
                job_tokens += count * _ligand_atoms(entity["ligand"], ccd, rdkit_loader)
            else:
                job_tokens += count * ccd.heavy_atoms(_ccd_code(entity["ion"]))
        name = str(job.get("name") or f"job_{index + 1}")
        if name in by_job:
            raise TokenEstimateError(f"Duplicate job name: {name!r}")
        by_job[name] = job_tokens
    return TokenEstimate(total=sum(by_job.values()), by_job=by_job)


def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("json", type=Path)
    parser.add_argument("--ccd-cache", type=Path, default=None)
    args = parser.parse_args()
    document = json.loads(args.json.read_text(encoding="utf-8"))
    result = estimate(document, CcdAtomCounts(args.ccd_cache))
    print(json.dumps({"total": result.total, "by_job": result.by_job}, indent=2))


if __name__ == "__main__":
    _main()
