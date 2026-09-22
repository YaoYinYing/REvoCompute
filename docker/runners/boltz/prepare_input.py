# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Reconstruct a Boltz specification and its referenced assets in one tree."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path, PurePosixPath


def _relative_path(entity: dict[str, object]) -> Path:
    source = Path(str(entity["path"]))
    raw = str(entity.get("relative_path") or source.name)
    relative = PurePosixPath(raw)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError(f"unsafe input relative path: {raw!r}")
    return Path(*relative.parts)


def _protein_msas(specification: Path) -> list[tuple[str, str]]:
    """Return ``(chain_id, msa)`` for every protein entity in a specification.

    An empty *msa* means the chain declared none: either the YAML entry omits
    the key or the FASTA header carries no third field.
    """
    text = specification.read_text(encoding="utf-8")
    if specification.suffix.lower() in {".yaml", ".yml"}:
        import yaml

        document = yaml.safe_load(text) or {}
        proteins = []
        for item in document.get("sequences") or []:
            if isinstance(item, dict) and isinstance(item.get("protein"), dict):
                entity = item["protein"]
                msa = entity.get("msa")
                proteins.append((str(entity.get("id") or "?"), msa if isinstance(msa, str) else ""))
        return proteins
    proteins = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if not stripped.startswith(">"):
            continue
        fields = [field.strip() for field in stripped[1:].split("|")]
        if len(fields) >= 2 and fields[1].lower() == "protein":
            proteins.append((fields[0], fields[2] if len(fields) == 3 else ""))
    return proteins


def _resolve_msa_modes(
    specification: Path, online: bool
) -> list[str]:
    """Classify every protein chain into one of upstream's three MSA modes.

    Boltz rejects a protein chain that supplies no alignment unless
    ``--use_msa_server`` is set, so a specification whose chains all omit their
    MSA fails only inside the CLI after the GPU allocation. Decide it here
    instead, where the resolved parameter is available: return the local
    references to verify, and reject anything that has no mode at all.
    """
    references: list[str] = []
    for chain, msa in _protein_msas(specification):
        if msa and msa != "empty":
            references.append(msa)
        elif not msa and not online:
            raise ValueError(
                f"Boltz protein chain {chain!r} declares no MSA and 'use_msa_server' is false; "
                "reference an uploaded alignment, request single-sequence mode with 'msa: empty', "
                "or enable the MSA server"
            )
    return references


def prepare(manifest_path: Path, destination: Path) -> Path:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    specification = manifest.get("inputs", {}).get("specification", [])
    assets = manifest.get("inputs", {}).get("assets", [])
    if not isinstance(specification, list) or len(specification) != 1 or not isinstance(assets, list):
        raise ValueError("Boltz input manifest has invalid specification or assets roles")
    params = manifest.get("params", {})
    if not isinstance(params, dict):
        raise ValueError("Boltz task params must be an object")
    use_msa_server = params.get("use_msa_server")
    online = use_msa_server is True or (isinstance(use_msa_server, str) and use_msa_server.lower() == "true")

    # Every uploaded input keeps the relative path it was submitted under, so a
    # specification's confined MSA reference resolves to exactly one asset.
    available = {_relative_path(entity).as_posix() for entity in specification + assets if isinstance(entity, dict)}
    prepared_specification: Path | None = None
    occupied: set[Path] = set()
    for role, entities in (("specification", specification), ("assets", assets)):
        for entity in entities:
            if not isinstance(entity, dict) or not Path(str(entity.get("path", ""))).is_file():
                raise ValueError(f"Boltz {role} input is missing")
            relative = _relative_path(entity)
            if relative in occupied:
                raise ValueError(f"duplicate Boltz input relative path: {relative.as_posix()}")
            occupied.add(relative)
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(entity["path"]), target)
            if role == "specification":
                prepared_specification = target

    assert prepared_specification is not None
    root = destination.resolve()
    for reference in _resolve_msa_modes(prepared_specification, online):
        resolved = (prepared_specification.parent / reference).resolve()
        if not resolved.is_relative_to(root) or (resolved.relative_to(root).as_posix() not in available):
            raise ValueError(f"Boltz MSA reference does not name an uploaded asset: {reference!r}")
    return prepared_specification


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: prepare_input.py <task.json> <destination>")
    try:
        print(prepare(Path(sys.argv[1]), Path(sys.argv[2])))
    except (KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Boltz input preparation failed: {exc}") from exc
