# Copyright (c) 2026 The REvoDesign Developers.
# SPDX-License-Identifier: GPL-3.0-only

"""Validate Boltz-2 inputs and construct an offline upstream invocation."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys

import yaml

ASSETS = ("ccd.pkl", "mols.tar", "boltz2_conf.ckpt", "boltz2_aff.ckpt")
# The extracted Boltz-2 CCD library is what upstream actually reads (load_canonicals);
# mols.tar is only its transport. A deterministic digest over the extracted tree binds
# those bytes; it is recorded in model-assets.sha256 under the name "mols". The operator
# extracts mols.tar once; the family never extracts or downloads at runtime.
MOLS_DIR = "mols"


def _tree_digest(root: Path) -> str:
    """Hash every regular file under ``root`` with its relative path, refusing symlinks."""
    if not root.is_dir():
        raise ValueError(f"missing Boltz-2 extracted directory: {root}")
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ValueError(f"symlink inside extracted Boltz-2 assets: {relative}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError(f"unsupported entry in extracted Boltz-2 assets: {relative}")
        digest.update(relative.encode("utf-8") + b"\0")
        digest.update(hashlib.file_digest(path.open("rb"), "sha256").hexdigest().encode("ascii") + b"\n")
    return digest.hexdigest()


def verify_assets(root: Path, manifest: Path) -> None:
    if not manifest.is_file() or manifest.stat().st_size == 0:
        raise ValueError("Boltz-2 asset digest manifest is unavailable (ASSET_BLOCKED)")
    expected: dict[str, str] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) != 2 or len(parts[0]) != 64:
            if line.strip() and not line.lstrip().startswith("#"):
                raise ValueError("invalid Boltz-2 asset digest manifest")
            continue
        expected[parts[1].lstrip("*")] = parts[0].lower()
    if not expected:
        raise ValueError("Boltz-2 asset digest manifest has no reviewed digests (ASSET_BLOCKED)")
    if set(expected) != {*ASSETS, MOLS_DIR}:
        raise ValueError("Boltz-2 digest manifest must cover the four asset files and the extracted mols/ tree")
    for name, digest in expected.items():
        if name == MOLS_DIR:
            actual = _tree_digest(root / MOLS_DIR)
        else:
            path = root / name
            if not path.is_file():
                raise ValueError(f"missing Boltz-2 asset: {path}")
            actual = hashlib.file_digest(path.open("rb"), "sha256").hexdigest()
        if actual != digest:
            raise ValueError(f"Boltz-2 asset digest mismatch: {name}")


def _cif_tokens(line: str) -> list[str]:
    """Split one CIF row, honouring simple single/double-quoted values."""
    tokens: list[str] = []
    index = 0
    while index < len(line):
        char = line[index]
        if char.isspace():
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            index += 1
            start = index
            while index < len(line) and line[index] != quote:
                index += 1
            tokens.append(line[start:index])
            index += 1
            continue
        start = index
        while index < len(line) and not line[index].isspace():
            index += 1
        tokens.append(line[start:index])
    return tokens


def _valid_atom(values: list[str], columns: dict[str, int]) -> bool:
    def value(name: str) -> str:
        index = columns.get(name)
        return values[index].strip() if index is not None and index < len(values) else ""

    residue = value("_atom_site.label_comp_id") or value("_atom_site.auth_comp_id")
    atom = value("_atom_site.label_atom_id") or value("_atom_site.auth_atom_id")
    if residue in {"", ".", "?"} or atom in {"", ".", "?"}:
        return False
    try:
        coords = [float(value(f"_atom_site.cartn_{axis}")) for axis in "xyz"]
    except ValueError:
        return False
    return all(math.isfinite(coord) for coord in coords)


# ponytail: line-oriented _atom_site reader, sufficient for upstream-emitted mmCIF;
# a wrapped or multi-block CIF needs a real parser (gemmi is available in the SIF).
def structure_atom_count(path: Path) -> int:
    """Count atom-site rows with finite coordinates and a residue/atom identity."""
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        raise ValueError(f"empty structure file: {path.name}")
    lines = text.splitlines()
    atoms = 0
    index = 0
    while index < len(lines):
        if lines[index].strip().lower() != "loop_":
            index += 1
            continue
        index += 1
        tags: list[str] = []
        while index < len(lines) and lines[index].strip().startswith("_"):
            tags.append(lines[index].strip().split()[0].lower())
            index += 1
        if not tags or not all(tag.startswith("_atom_site.") for tag in tags):
            continue
        columns = {tag: position for position, tag in enumerate(tags)}
        if not {
            "_atom_site.cartn_x",
            "_atom_site.cartn_y",
            "_atom_site.cartn_z",
        } <= set(columns) or not (
            {"_atom_site.label_comp_id", "_atom_site.auth_comp_id"} & set(columns)
            and {"_atom_site.label_atom_id", "_atom_site.auth_atom_id"} & set(columns)
        ):
            return 0
        while index < len(lines):
            row = lines[index].strip()
            if (
                not row
                or row.startswith("#")
                or row.startswith("_")
                or row.lower() == "loop_"
                or row.lower().startswith("data_")
            ):
                break
            values = _cif_tokens(row)
            if len(values) >= len(tags) and _valid_atom(values, columns):
                atoms += 1
            index += 1
    return atoms


def _relative(entity: dict[str, object]) -> Path:
    raw = str(entity.get("relative_path") or Path(str(entity.get("path", ""))).name)
    rel = PurePosixPath(raw)
    if rel.is_absolute() or any(part in {"", ".", ".."} for part in rel.parts):
        raise ValueError(f"unsafe input relative path: {raw!r}")
    return Path(*rel.parts)


def _reject_unconfined_references(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in {"path", "file", "template", "templates", "constraints", "url"}:
                raise ValueError(f"unconfined file reference is not supported: {key}")
            _reject_unconfined_references(child)
    elif isinstance(value, list):
        for child in value:
            _reject_unconfined_references(child)


def prepare(task_path: Path, destination: Path, task_type: str) -> tuple[Path, dict[str, object]]:
    task = json.loads(task_path.read_text(encoding="utf-8"))
    inputs = task.get("inputs", {})
    spec_role = inputs.get("specification", [])
    assets = inputs.get("assets", [])
    if len(spec_role) != 1 or not isinstance(assets, list):
        raise ValueError("Boltz-2 requires one specification and zero or more supplied alignments")
    spec_ent = spec_role[0]
    spec_path = Path(str(spec_ent.get("path", "")))
    if not spec_path.is_file() or spec_path.suffix.lower() not in {".yaml", ".yml"}:
        raise ValueError("Boltz-2 requires one YAML specification")
    if len(assets) > 32:
        raise ValueError("too many supplied MSA files")
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    used: set[Path] = set()
    for role, entries in (("specification", spec_role), ("assets", assets)):
        for entry in entries:
            src = Path(str(entry.get("path", "")))
            rel = _relative(entry)
            if not src.is_file() or rel in used:
                raise ValueError(f"missing or duplicate {role} input")
            if role == "assets" and src.suffix.lower() not in {".a3m", ".csv"}:
                raise ValueError("MSA assets must be A3M or CSV")
            used.add(rel)
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(src.read_bytes())
    spec = (root / _relative(spec_ent)).resolve()
    document = yaml.safe_load(spec.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("sequences"), list):
        raise ValueError("invalid Boltz-2 specification")
    _reject_unconfined_references(document)
    # Upstream resolves Path(msa) against the process CWD, which is the spec's
    # parent. Verify the path upstream will actually consume, not a root-relative
    # string that can name a different file.
    allowed = {_relative(item).as_posix() for item in assets}
    msa_records: list[dict[str, object]] = []
    for item in document["sequences"]:
        if not isinstance(item, dict) or len(item) != 1:
            raise ValueError("each sequence entry must declare exactly one molecule")
        entity_type, entity = next(iter(item.items()))
        if entity_type not in {"protein", "dna", "rna", "ligand"} or not isinstance(entity, dict):
            raise ValueError("unsupported Boltz-2 molecule entry")
        if entity_type == "protein":
            if "msa" not in entity:
                raise ValueError("protein chain must explicitly declare msa: empty or a supplied A3M/CSV path")
            msa = entity["msa"]
            chain_ids = entity.get("id")
            chains = chain_ids if isinstance(chain_ids, list) else [chain_ids]
            if msa == "empty":
                msa_records.extend({"chain": str(chain), "declared": "empty", "consumed": None, "sha256": None} for chain in chains)
                continue
            raw = str(msa)
            relative = PurePosixPath(raw)
            if relative.is_absolute() or any(p in {"", ".", ".."} for p in relative.parts):
                raise ValueError(f"unsafe MSA reference: {raw!r}")
            resolved = (spec.parent / relative).resolve()
            if not resolved.is_relative_to(root):
                raise ValueError(f"MSA reference escapes prepared inputs: {raw!r}")
            consumed = resolved.relative_to(root).as_posix()
            if consumed not in allowed or not resolved.is_file():
                raise ValueError(
                    f"MSA reference resolves to {consumed!r} relative to the specification, "
                    "which is not a supplied asset; move the alignment to that path or correct the reference"
                )
            digest = hashlib.file_digest(resolved.open("rb"), "sha256").hexdigest()
            msa_records.extend(
                {"chain": str(chain), "declared": raw, "consumed": consumed, "sha256": digest} for chain in chains
            )
    if task_type == "boltz2_affinity":
        properties = document.get("properties") or []
        affinity = [p["affinity"] for p in properties if isinstance(p, dict) and "affinity" in p]
        if len(affinity) != 1 or not isinstance(affinity[0], dict):
            raise ValueError("affinity task requires exactly one upstream affinity property")
        binder = affinity[0].get("binder")
        by_id: dict[str, str] = {}
        for item in document["sequences"]:
            kind, entity = next(iter(item.items()))
            ids = entity.get("id")
            for chain_id in ids if isinstance(ids, list) else [ids]:
                by_id[str(chain_id)] = kind
        if by_id.get(str(binder)) != "ligand":
            raise ValueError("affinity binder must identify one ligand chain")
        if sum(kind == "ligand" for kind in by_id.values()) != 1:
            raise ValueError("affinity supports one ligand chain only")
        kinds = set(by_id.values())
        if "protein" not in kinds or kinds.intersection({"dna", "rna"}):
            raise ValueError("affinity is qualified only for a protein target and small-molecule ligand")
    elif document.get("properties"):
        raise ValueError("structure prediction does not accept affinity properties; use boltz2_affinity")
    provenance: dict[str, object] = {
        "specification": spec.relative_to(root).as_posix(),
        "specification_sha256": hashlib.file_digest(spec.open("rb"), "sha256").hexdigest(),
        "msa": msa_records,
    }
    return spec, provenance


def command(cli: str, spec: Path, output: Path, cache: Path, params: dict[str, object], affinity: bool) -> list[str]:
    args = [cli, "predict", str(spec), "--model", "boltz2", "--out_dir", str(output), "--cache", str(cache),
            "--checkpoint", str(cache / "boltz2_conf.ckpt"), "--devices", "1", "--accelerator", "gpu",
            "--output_format", "mmcif", "--recycling_steps", str(params["recycling_steps"]),
            "--sampling_steps", str(params["sampling_steps"]), "--diffusion_samples", str(params["diffusion_samples"]),
            "--num_workers", str(params["preprocessing_workers"]), "--seed", str(params["seed"]), "--override"]
    if affinity:
        args += ["--affinity_checkpoint", str(cache / "boltz2_aff.ckpt")]
    return args


def main() -> int:
    mode = sys.argv[1]
    task_path, output = Path(sys.argv[2]), Path(sys.argv[3])
    task_type = os.environ.get("TASK_TYPE", "")
    if task_type not in {"boltz2_predict", "boltz2_affinity"} or (mode == "affinity") != (task_type == "boltz2_affinity"):
        raise ValueError(f"unsupported task type: {task_type}")
    task = json.loads(task_path.read_text(encoding="utf-8"))
    spec, provenance = prepare(task_path, output / "prepared", task_type)
    cache = Path(os.environ.get("BOLTZ_ASSET_ROOT", "/mnt/db/weights/boltz2"))
    verify_assets(cache, Path(os.environ.get("BOLTZ_ASSET_MANIFEST", "/app/revocompute/model-assets.sha256")))
    args = command(os.environ.get("BOLTZ_CLI", "/opt/venv/bin/boltz"), spec, output, cache, task["params"], mode == "affinity")
    print("REVODESIGN_STAGE:boltz2_predict")
    subprocess.run(args, check=True, cwd=spec.parent)
    prediction = output / f"boltz_results_{spec.stem}" / "predictions"
    structures = list(prediction.glob("*/*_model_*.cif"))
    if not structures:
        raise ValueError("Boltz-2 produced no native mmCIF structure")
    for structure in structures:
        if structure_atom_count(structure) == 0:
            raise ValueError(f"Boltz-2 produced no parseable atom record in {structure.name}")
    if mode == "affinity" and not list(prediction.glob("*/affinity_*.json")):
        raise ValueError("Boltz-2 affinity task produced no affinity JSON")
    if not list(prediction.glob("*/confidence_*_model_*.json")):
        raise ValueError("Boltz-2 produced no confidence JSON")
    upstream = json.loads((Path(__file__).with_name("upstream.json")).read_text(encoding="utf-8"))
    # The committed file is build provenance; verification is the runtime fact.
    upstream["asset_status"] = "verified"
    (output / "boltz2-upstream.json").write_text(
        json.dumps(upstream, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output / "boltz2-input-provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output / "boltz2-model-assets.sha256").write_text(
        Path(os.environ.get("BOLTZ_ASSET_MANIFEST", "/app/revocompute/model-assets.sha256")).read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    (output / "task_finished").touch()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyError, OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        print(f"Boltz-2 failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
