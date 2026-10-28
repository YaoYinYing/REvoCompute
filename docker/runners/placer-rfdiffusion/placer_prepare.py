# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Build and validate one PLACER invocation from the immutable task manifest.

The pinned PLACER CLI takes a directory of PDB files (``--idir``), which batches
every PDB in it and cannot read mmCIF. This Task submits exactly one complex, so
the adapter passes that file through ``--ifile`` instead.

PLACER's PDB parse drops insertion codes and alternate locations, its mmCIF
parse resolves alternates by occupancy and keys chains/numbers by the label and
author columns, and its ligand specification is a string. All are checked here
before the model is loaded, and the manifest parameters become an argument
vector, never shell text.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

_CENTER_FLAGS = ("crop_centers", "corruption_centers")

# Mirror of modules/utils.py::get_common_ligands() at PLACER 7dc5563.
# ``--exclude_common_ligands`` drops these names during parsing, so the ligand
# census below must drop them too or every count drifts from upstream.
_COMMON_LIGANDS = frozenset(
    """144 15P 1PE 2F2 2JC 3HR 3SY 7N5 7PE 9JE AAE ABA ACE ACN ACT ACY AZI BAM BCN
    BCT BDN BEN BME BO3 BTB BTC BU1 C8E CAD CAQ CBM CCN CIT CL CLR CM CMO CO3 CXS D10
    DEP DIO DMS DN DOD DOX EDO EEE EGL EOH EOX EPE ETF FCY FJO FLC FMT FW5 GOL GSH
    GTT GYF HED IHP IHS IMD IOD IPA IPH LDA MB3 MEG MES MLA MLI MOH MPD MRD MSE MYR N
    NA NH2 NH4 NHE NO3 O4B OHE OLA OLC OMB OME OXA P6G PE3 PE4 PEG PEO PEP PG0 PG4 PGE
    PGR PLM PO4 POL POP PVO SAR SCN SEO SEP SIN SO4 SPD SPM SR STE STO STU TAR TBU TME
    TPO TRS UNK UNL UNX UPL URE""".split()
)


class PreparationError(ValueError):
    """A user-correctable manifest, parameter, or input-structure failure."""


@lru_cache(maxsize=1)
def _ccd_library() -> dict[str, frozenset[str]]:
    """Residue names and template atom names in PLACER's shipped CCD library."""
    path = Path(os.environ.get("PLACER_PATH", "/opt/PLACER")) / "data" / "ligands.json.gz"
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            definitions = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise PreparationError(f"PLACER residue library is not readable: {exc}") from None
    return {name: frozenset(entry.get("atom_id") or ()) for name, entry in definitions.items()}


@dataclass(frozen=True)
class Residue:
    record: str
    chain: str
    number: int | None
    name: str
    atom: str
    insertion: str = ""
    altloc: str = ""


@dataclass(frozen=True)
class ParsedParams:
    predict_ligand: list[str]
    fixed_ligand: list[str]
    crop_centers: list[str]
    corruption_centers: list[str]
    bonds: list[str]
    mutate: list[str]
    target_res: str


def _tokens(value: Any) -> list[str]:
    return str(value or "").split()


def _parse_ligand_spec(token: str) -> tuple[str, ...]:
    parts = token.split("-")
    if len(parts) == 1 and parts[0]:
        return ("name", parts[0])
    if len(parts) == 2 and parts[0] and parts[1].isdigit():
        return ("name_res", parts[0], int(parts[1]))
    if len(parts) == 3 and parts[0] and parts[1] and parts[2].isdigit():
        return ("chain_name_res", parts[0], parts[1], int(parts[2]))
    raise PreparationError(
        f"Invalid ligand identifier {token!r}; use name3, name3-resno, or chain-name3-resno."
    )


def _parse_target_res(token: str) -> tuple[str, int]:
    # Upstream parses a three-part target as chain-resno-name3, so the former
    # chain-name3-resno help drove ``int('ALA')`` and failed inside the SIF.
    parts = token.split("-")
    if len(parts) == 2 and parts[0] and parts[1].isdigit():
        return (parts[0], int(parts[1]))
    raise PreparationError(f"Invalid target residue {token!r}; use chain-resno, for example A-149.")


def _parse_center(token: str, flag: str) -> tuple[str, int, str, str]:
    parts = token.split("-")
    if len(parts) != 4 or not parts[0] or not parts[1].isdigit() or not parts[2] or not parts[3]:
        raise PreparationError(
            f"Invalid center {token!r} for {flag}; use chain-resno-name3-atom, for example B-200-HEM-FE."
        )
    return (parts[0], int(parts[1]), parts[2], parts[3])


def _parse_bond(token: str) -> None:
    parts = token.split(":")
    if len(parts) != 3:
        raise PreparationError(
            f"Invalid bond {token!r}; use atom:atom:length, for example A-42-ALA-CB:B-173-JRP-CL:1.8."
        )
    _parse_center(parts[0], "bonds")
    _parse_center(parts[1], "bonds")
    try:
        length = float(parts[2])
    except ValueError:
        raise PreparationError(f"Invalid bond length in {token!r}; it must be a number.") from None
    if not math.isfinite(length) or length <= 0:
        raise PreparationError(f"Invalid bond length in {token!r}; it must be positive.")


def _parse_mutation(token: str) -> tuple[str, int, str]:
    parts = token.split(":")
    if len(parts) != 2 or not parts[1]:
        raise PreparationError(
            f"Invalid mutation {token!r}; use resno+chain:name3, for example 128A:TRP."
        )
    position, name = parts
    index = 0
    while index < len(position) and position[index].isdigit():
        index += 1
    if index == 0:
        raise PreparationError(f"Invalid mutation {token!r}; the residue number must come first.")
    return (position[index:], int(position[:index]), name)


def validate_params(params: dict[str, Any]) -> ParsedParams:
    """Reject conflicting or malformed parameters before the model is loaded."""
    parsed = ParsedParams(
        predict_ligand=_tokens(params.get("predict_ligand")),
        fixed_ligand=_tokens(params.get("fixed_ligand")),
        crop_centers=_tokens(params.get("crop_centers")),
        corruption_centers=_tokens(params.get("corruption_centers")),
        bonds=_tokens(params.get("bonds")),
        mutate=_tokens(params.get("mutate")),
        target_res=str(params.get("target_res") or ""),
    )
    if parsed.predict_ligand and parsed.fixed_ligand:
        raise PreparationError("predict_ligand and fixed_ligand cannot both be set.")
    if parsed.crop_centers and parsed.corruption_centers:
        raise PreparationError("crop_centers and corruption_centers cannot both be set.")
    if params.get("use_sm") is False and (parsed.predict_ligand or parsed.fixed_ligand):
        raise PreparationError(
            "use_sm: false removes the small molecule from the model, so it cannot be combined with "
            "predict_ligand or fixed_ligand."
        )
    for token in (*parsed.predict_ligand, *parsed.fixed_ligand):
        _parse_ligand_spec(token)
    if parsed.target_res:
        _parse_target_res(parsed.target_res)
    for flag in _CENTER_FLAGS:
        for token in getattr(parsed, flag):
            _parse_center(token, flag)
    for token in parsed.bonds:
        _parse_bond(token)
    for token in parsed.mutate:
        _parse_mutation(token)
    rerank = str(params.get("rerank") or "")
    if rerank not in {"", "prmsd", "plddt", "plddt_pde"}:
        raise PreparationError(f"Invalid rerank metric {rerank!r}.")
    samples = params.get("num_samples")
    if not isinstance(samples, int) or isinstance(samples, bool) or samples < 1:
        raise PreparationError("num_samples must be a positive integer.")
    noise = params.get("fixed_ligand_noise")
    if noise is not None and (isinstance(noise, bool) or not isinstance(noise, (int, float)) or float(noise) < 0):
        raise PreparationError("fixed_ligand_noise must be a non-negative number.")
    return parsed


def _pdb_residues(text: str) -> list[Residue]:
    residues: list[Residue] = []
    block_chains: set[str] = set()
    current_chain: str | None = None
    models = 0
    for line in text.splitlines():
        if line.startswith("MODEL"):
            models += 1
            if models > 1:
                raise PreparationError(
                    "Multi-MODEL PDB input is not supported; PLACER keeps only the last model. "
                    "Submit a single model."
                )
            continue
        if line[:6] not in {"ATOM  ", "HETATM"} or len(line) < 27:
            continue
        # Keep the raw column: upstream keys a blank chain as " ", not "".
        chain = line[21:22]
        if line[:6] == "ATOM  " and chain != current_chain:
            # Upstream groups contiguous ATOM runs by chain, so a repeated
            # non-contiguous block silently overwrites the earlier one.
            if chain in block_chains:
                raise PreparationError(
                    f"PDB chain {chain!r} appears in more than one block; PLACER would keep only the last block. "
                    "Reorder the chains so each appears once."
                )
            block_chains.add(chain)
            current_chain = chain
        try:
            number: int | None = int(line[22:26])
        except ValueError:
            number = None
        residues.append(
            Residue(
                record=line[:6].strip(),
                chain=chain,
                number=number,
                name=line[17:20].strip(),
                atom=line[12:16].strip(),
                insertion=line[26:27].strip(),
                altloc=line[16:17].strip(),
            )
        )
    return residues


def _closes_quote(line: str, index: int, quote: str) -> bool:
    return line[index] == quote and (index + 1 == len(line) or line[index + 1].isspace())


def _cif_tokens(line: str) -> list[str]:
    tokens: list[str] = []
    index = 0
    while index < len(line):
        while index < len(line) and line[index].isspace():
            index += 1
        if index >= len(line):
            break
        quote = line[index] if line[index] in {"'", '"'} else ""
        if quote:
            index += 1
            start = index
            while index < len(line) and not _closes_quote(line, index, quote):
                index += 1
            tokens.append(line[start:index])
            index += 1
        else:
            start = index
            while index < len(line) and not line[index].isspace():
                index += 1
            tokens.append(line[start:index])
    return tokens


def _cif_residues(text: str) -> list[Residue]:
    lines = text.splitlines()
    residues: list[Residue] = []
    index = 0
    while index < len(lines):
        if lines[index].strip() != "loop_":
            index += 1
            continue
        cursor = index + 1
        columns: list[str] = []
        while cursor < len(lines) and lines[cursor].lstrip().startswith("_"):
            columns.append(lines[cursor].strip())
            cursor += 1
        if not columns or not columns[0].startswith("_atom_site."):
            index = max(cursor, index + 1)
            continue
        rows: list[list[str]] = []
        while cursor < len(lines):
            stripped = lines[cursor].strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("_") or stripped in {"loop_", "stop_"}:
                break
            if stripped.startswith(("data_", "save_")):
                break
            rows.append(_cif_tokens(stripped))
            cursor += 1
        positions = {name: position for position, name in enumerate(columns)}

        def column(*names: str) -> int | None:
            return next((positions[name] for name in names if name in positions), None)

        def value(raw: str) -> str:
            return "" if raw in {"?", "."} else raw

        group = column("_atom_site.group_PDB")
        chain_column = column("_atom_site.label_asym_id")
        label_number = column("_atom_site.label_seq_id")
        auth_number = column("_atom_site.auth_seq_id")
        name_column = column("_atom_site.auth_comp_id", "_atom_site.label_comp_id")
        atom_column = column("_atom_site.label_atom_id", "_atom_site.auth_atom_id")
        model_column = column("_atom_site.pdbx_PDB_model_num")
        if (
            chain_column is None
            or label_number is None
            or auth_number is None
            or name_column is None
            or atom_column is None
        ):
            raise PreparationError("mmCIF atom-site records lack the columns PLACER needs.")
        if model_column is not None:
            models = {
                row[model_column]
                for row in rows
                if len(row) == len(columns) and row[model_column] not in {"?", "."}
            }
            if len(models) > 1:
                raise PreparationError(
                    "Multi-model mmCIF input is not supported; PLACER keeps one model. Submit a single model."
                )
        # Upstream keys chains by label_asym_id, polymer residues by
        # label_seq_id, and non-polymer residues by auth_seq_id. Alternates are
        # resolved by occupancy and insertion codes are not read.
        polymer_chains = {
            value(row[chain_column])
            for row in rows
            if len(row) == len(columns) and (group is None or row[group].upper() != "HETATM")
        }
        for row in rows:
            if len(row) != len(columns):
                continue
            group_value = row[group].upper() if group is not None else "ATOM"
            chain = value(row[chain_column])
            polymer = chain in polymer_chains
            raw_number = row[label_number] if polymer else row[auth_number]
            if raw_number in {"?", "."}:
                continue
            try:
                number: int | None = int(raw_number)
            except ValueError:
                number = None
            residues.append(
                Residue(
                    record="HETATM" if group_value == "HETATM" and not polymer else "ATOM",
                    chain=chain,
                    number=number,
                    name=value(row[name_column]),
                    atom=value(row[atom_column]),
                )
            )
        index = cursor
    return residues


def read_structure(path: str) -> list[Residue]:
    suffix = Path(path).suffix.lower()
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    if suffix == ".pdb":
        return _pdb_residues(text)
    if suffix in {".cif", ".mmcif"}:
        return _cif_residues(text)
    # PLACER's -f dispatch also accepts .ent, but .ent is outside this Task's
    # declared formats, so it is rejected here instead of being forwarded.
    raise PreparationError(f"Unsupported structure format {suffix or path!r}; use PDB or mmCIF.")


def _ligands(residues: list[Residue], skip_common: bool = False) -> list[tuple[str, int, str]]:
    skipped = {"HOH", *_COMMON_LIGANDS} if skip_common else {"HOH"}
    instances = {
        (residue.chain, residue.number, residue.name)
        for residue in residues
        if residue.record == "HETATM" and residue.name not in skipped and residue.number is not None
    }
    return sorted(instances)


def _ligand_matches(spec: tuple[str, ...], ligand: tuple[str, int, str]) -> bool:
    chain, number, name = ligand
    if spec[0] == "name":
        return spec[1] == name
    if spec[0] == "name_res":
        return spec[1] == name and spec[2] == number
    return spec[1] == chain and spec[2] == name and spec[3] == number


def _matching_ligands(specs: list[str], ligands: list[tuple[str, int, str]]) -> list[tuple[str, int, str]]:
    matched = set()
    for token in specs:
        spec = _parse_ligand_spec(token)
        hits = [ligand for ligand in ligands if _ligand_matches(spec, ligand)]
        if not hits:
            raise PreparationError(f"Ligand identifier {token!r} matches no ligand in the input structure.")
        matched.update(hits)
    return sorted(matched)


def validate_structure(params: dict[str, Any], parsed: ParsedParams, residues: list[Residue], path: str) -> None:
    """Cross-check the requested identifiers against the submitted structure."""
    suffix = Path(path).suffix.lower()
    cif_input = suffix in {".cif", ".mmcif"}
    skip_common = bool(params.get("exclude_common_ligands"))
    skipped = {"HOH", *_COMMON_LIGANDS} if skip_common else {"HOH"}
    # Upstream drops skipped ligands before parsing. For mmCIF the skip list
    # also removes those names from the residue library, so polymer names go too.
    relevant = [
        residue
        for residue in residues
        if residue.name not in skipped or (residue.record == "ATOM" and not cif_input)
    ]
    # PLACER parses only residues and atoms present in its shipped library; check
    # mmCIF ligands and every selector against that library before dispatch.
    needs_ccd = cif_input or bool(
        parsed.mutate or parsed.crop_centers or parsed.corruption_centers or parsed.bonds
    )
    ccd = _ccd_library() if needs_ccd else {}
    if cif_input:
        unknown = sorted(
            {residue.name for residue in relevant if residue.record == "HETATM" and residue.name not in ccd}
        )
        if unknown:
            raise PreparationError(
                "Ligand name3 "
                + ", ".join(repr(name) for name in unknown)
                + " is not in PLACER's shipped residue library; PLACER would drop it."
            )
    # The mmCIF parser resolves alternates by highest occupancy and never reads
    # insertion codes, so these PDB-parser restrictions apply to PDB only.
    if not cif_input:
        insertion = sorted({residue.insertion for residue in relevant if residue.insertion})
        if insertion:
            raise PreparationError(
                "PLACER does not preserve residue insertion codes; the input contains "
                f"{', '.join(insertion)}. Remove or renumber those residues first."
            )
        altloc = sorted({residue.altloc for residue in relevant if residue.altloc})
        if altloc:
            raise PreparationError(
                "PLACER does not resolve alternate locations; the input contains "
                f"{', '.join(altloc)}. Keep one conformer per atom first."
            )
    unnamed = sorted({residue.chain for residue in relevant if residue.number is None})
    if unnamed:
        raise PreparationError(
            f"Residue numbers are not integers in chain(s) {', '.join(repr(chain) for chain in unnamed)}."
        )
    if cif_input:
        # A CIF residue is keyed by chain and sequence number, so two names at
        # one number collapse; a PDB keeps the name in its residue key.
        numbering: dict[tuple[str, int | None], set[str]] = {}
        for residue in relevant:
            numbering.setdefault((residue.chain, residue.number), set()).add(residue.name)
        collisions = sorted(key for key, names in numbering.items() if len(names) > 1)
        if collisions:
            chain, number = collisions[0]
            raise PreparationError(
                f"Residues {chain}{number} share a chain and residue number with different names; "
                "PLACER would merge them."
            )

    ligands = _ligands(residues, skip_common)
    ligand_chains = {ligand[0] for ligand in ligands}
    protein_chains = {residue.chain for residue in relevant if residue.record == "ATOM"}
    shared_chains = sorted(ligand_chains & protein_chains)
    if shared_chains:
        raise PreparationError(
            "Chain(s) "
            + ", ".join(repr(chain) for chain in shared_chains)
            + " contain both protein residues and ligands; PLACER needs a separate chain letter for each ligand."
        )

    predicted = set(ligands)
    if parsed.predict_ligand:
        predicted = set(_matching_ligands(parsed.predict_ligand, ligands))
    elif parsed.fixed_ligand:
        predicted -= set(_matching_ligands(parsed.fixed_ligand, ligands))

    target = _parse_target_res(parsed.target_res) if parsed.target_res else None
    if target is not None:
        chain, number = target
        matches = [
            residue
            for residue in relevant
            if residue.record == "ATOM" and residue.chain == chain and residue.number == number
        ]
        if not matches:
            raise PreparationError(f"target_res {parsed.target_res!r} matches no protein residue in the input.")
        if cif_input:
            unknown = sorted({residue.name for residue in matches if residue.name not in ccd})
            if unknown:
                raise PreparationError(
                    f"target_res residue {unknown[0]!r} is not in PLACER's shipped residue library."
                )
    elif not ligands:
        raise PreparationError("target_res is required when the input structure has no ligand.")
    if not ligands and (parsed.crop_centers or parsed.corruption_centers):
        # Upstream builds one center per non-fixed ligand; with no ligand that
        # list is empty and get_crop indexes it (dataloader_pdb.py:279).
        raise PreparationError(
            "crop_centers and corruption_centers require a ligand in the input structure; "
            "use target_res alone for a ligand-free structure."
        )
    if not predicted and (target is None or parsed.crop_centers or parsed.corruption_centers):
        # Same empty-center crash when fixed_ligand leaves no ligand to predict.
        raise PreparationError(
            "No ligand remains to predict: fixed_ligand covers every ligand. "
            "Leave at least one ligand unfixed, or use target_res alone."
        )

    def selector_residue(chain: str, number: int, name: str, atom: str, label: str) -> None:
        match = next(
            (
                residue
                for residue in relevant
                if residue.chain == chain
                and residue.number == number
                and residue.name == name
                and residue.atom == atom
            ),
            None,
        )
        if match is None:
            raise PreparationError(f"{label} atom {chain}-{number}-{name}-{atom!r} is absent from the input.")
        if (cif_input or match.record == "ATOM") and atom not in ccd.get(name, frozenset()):
            raise PreparationError(
                f"{label} atom {chain}-{number}-{name}-{atom!r} is not an atom PLACER parses for residue {name!r}."
            )

    for flag in _CENTER_FLAGS:
        for token in getattr(parsed, flag):
            chain, number, name, atom = _parse_center(token, flag)
            selector_residue(chain, number, name, atom, flag)

    for token in parsed.bonds:
        left, right, _length = token.split(":")
        for atom in (left, right):
            chain, number, name, atom_name = _parse_center(atom, "bonds")
            selector_residue(chain, number, name, atom_name, "Bond")

    if parsed.mutate and cif_input:
        raise PreparationError("mutate is PDB-only; PLACER does not apply it to mmCIF input.")
    for token in parsed.mutate:
        chain, number, name = _parse_mutation(token)
        if name not in ccd:
            raise PreparationError(
                f"Mutation target {name!r} is not in PLACER's shipped residue library."
            )
        # Upstream groups a blank PDB chain as " " for mutations.
        chain = chain or " "
        if not any(
            residue.record == "ATOM" and residue.chain == chain and residue.number == number for residue in relevant
        ):
            raise PreparationError(f"Mutation {token!r} names a residue absent from the input structure.")

    if params.get("predict_multi") and len(ligands) < 2:
        raise PreparationError("predict_multi requires more than one ligand in the input structure.")
    if parsed.corruption_centers and len(parsed.corruption_centers) < len(predicted):
        raise PreparationError(
            "corruption_centers needs at least one center per non-fixed ligand "
            f"({len(predicted)} to predict, {len(parsed.corruption_centers)} given)."
        )


def build_argv(
    params: dict[str, Any],
    parsed: ParsedParams,
    structure_path: str,
    output_dir: str,
) -> list[str]:
    """Turn validated parameters into the pinned PLACER argument vector."""
    argv = ["-f", structure_path, "-o", output_dir, "-n", str(int(params["num_samples"]))]
    if params.get("use_sm") is False:
        argv.append("--no-use_sm")
    if params.get("exclude_common_ligands"):
        argv.append("--exclude_common_ligands")
    if params.get("predict_multi"):
        argv.append("--predict_multi")
    if parsed.predict_ligand:
        argv.extend(["--predict_ligand", *parsed.predict_ligand])
    elif parsed.fixed_ligand:
        argv.extend(["--fixed_ligand", *parsed.fixed_ligand])
    if parsed.target_res:
        argv.extend(["--target_res", parsed.target_res])
    noise = params.get("fixed_ligand_noise")
    if noise is not None:
        argv.extend(["--fixed_ligand_noise", str(noise)])
    rerank = str(params.get("rerank") or "")
    if rerank:
        argv.extend(["--rerank", rerank])
    for flag, values in (
        ("bonds", parsed.bonds),
        ("mutate", parsed.mutate),
        ("crop_centers", parsed.crop_centers),
        ("corruption_centers", parsed.corruption_centers),
    ):
        if values:
            argv.extend([f"--{flag}", *values])
    return argv


def normalize_structure_path(path: str) -> tuple[str, str | None]:
    """Give PLACER the lowercase suffix its extension dispatch matches.

    PLACER checks ``.pdb``/``.cif`` case-sensitively and does not recognize
    ``.mmcif``, so those uploads are linked under an equivalent supported name.
    The basename stem is unchanged, so PLACER's output label is unchanged.
    """
    suffix = Path(path).suffix
    target = ".cif" if suffix.lower() == ".mmcif" else suffix.lower()
    if target == suffix:
        return path, None
    directory = tempfile.mkdtemp(prefix="placer-input-")
    link = Path(directory) / f"{Path(path).stem}{target}"
    os.symlink(path, link)
    return str(link), directory


def _manifest_inputs(manifest: dict[str, Any], role: str) -> list[dict[str, Any]]:
    inputs = manifest.get("inputs")
    files = inputs.get(role) if isinstance(inputs, dict) else None
    return files if isinstance(files, list) else []


def _single_input(manifest: dict[str, Any], role: str) -> str:
    files = _manifest_inputs(manifest, role)
    if len(files) != 1 or not isinstance(files[0], dict) or not isinstance(files[0].get("path"), str):
        raise PreparationError(f"Input role {role!r} must contain exactly one file.")
    return files[0]["path"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, help="immutable task.json path")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--print-argv", action="store_true", help="print the validated argument vector and exit")
    args = parser.parse_args(argv)
    temporary: str | None = None
    try:
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        params = manifest.get("params")
        if not isinstance(params, dict):
            raise PreparationError("Task manifest has no parameter object.")
        structure = _single_input(manifest, "structures")
        parsed = validate_params(params)
        validate_structure(params, parsed, read_structure(structure), structure)
        placer_structure, temporary = normalize_structure_path(structure)
        placer_argv = build_argv(params, parsed, placer_structure, args.output_dir)
        if args.print_argv:
            print(json.dumps(placer_argv))
            return 0
        placer_path = os.environ.get("PLACER_PATH", "/opt/PLACER")
        command = [sys.executable, os.path.join(placer_path, "run_PLACER.py"), *placer_argv]
        subprocess.run(command, check=True)
        return 0
    except PreparationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        if temporary is not None:
            for entry in Path(temporary).iterdir():
                entry.unlink()
            Path(temporary).rmdir()


if __name__ == "__main__":
    raise SystemExit(main())
