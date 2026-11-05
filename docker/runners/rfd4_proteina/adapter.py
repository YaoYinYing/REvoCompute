# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

WEIGHTS = Path('/mnt/db/weights/rfd4-proteina')
CONTIG_TOKEN = re.compile(
    r'(?:/\d+|\d+(?:-\d+)?[PRD]?|[A-Za-z][A-Za-z0-9]*(?::\d+(?:-\d+)?[PRD]?|\d+(?:-\d+)?))\Z'
)
SPEC_KEYS = {'input', 'input_as_annotated_cif', 'contig', 'conditions'}
CONDITION_KEYS = {
    'C_CRD', 'C_CRDGRP', 'C_SEQ', 'C_HOT', 'C_RAS', 'C_HB',
    'C_PISTACK', 'C_PICATION', 'C_CATH', 'C_CENTROID', 'C_IDX',
}
SEQ_PROB_KEY = re.compile(r'C_SEQ_PROB_[A-Z0-9]+\Z')
REQUIRED_ASSETS = {'config.json', 'model.safetensors'}


def verify_assets() -> None:
    import hashlib
    manifest = Path(__file__).with_name('model-assets.sha256')
    rows = [line.split(None, 1) for line in manifest.read_text(encoding='utf-8').splitlines()
            if line.strip() and not line.lstrip().startswith('#')]
    if not rows or any(len(row) != 2 or not re.fullmatch(r'[0-9a-f]{64}', row[0]) for row in rows):
        raise RuntimeError(f'ASSET_BLOCKED: verified file hashes required in {manifest}; provision at {WEIGHTS}')
    digests = {relative: digest for digest, relative in rows}
    missing = REQUIRED_ASSETS - set(digests)
    if missing:
        raise RuntimeError(f'ASSET_BLOCKED: manifest must pin {", ".join(sorted(missing))}')
    for relative, digest in digests.items():
        path = (WEIGHTS / relative).resolve()
        if not path.is_relative_to(WEIGHTS.resolve()) or not path.is_file():
            raise RuntimeError(f'ASSET_BLOCKED: required asset missing: {relative}')
        hasher = hashlib.sha256()
        with path.open('rb') as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                hasher.update(chunk)
        if hasher.hexdigest() != digest:
            raise RuntimeError(f'ASSET_BLOCKED: SHA256 mismatch: {relative}')
    config = json.loads((WEIGHTS / 'config.json').read_text(encoding='utf-8'))
    if config.get('weights_sha256') != digests['model.safetensors']:
        raise RuntimeError('ASSET_BLOCKED: config.json weights_sha256 does not match model.safetensors')


def _validate_data(value: Any) -> None:
    if isinstance(value, str):
        if len(value) > 2048 or any(char in value for char in ('$','`',';','\\','\n','\r')):
            raise ValueError('condition values contain unsupported interpolation or directives')
    elif isinstance(value, list):
        if len(value) > 500:
            raise ValueError('condition list exceeds the supported size')
        for item in value:
            _validate_data(item)
    elif isinstance(value, dict):
        if len(value) > 500:
            raise ValueError('condition mapping exceeds the supported size')
        for key, item in value.items():
            if key is not None and not isinstance(key, (str, bool, int, float)):
                raise ValueError('condition keys must be plain scalar values')
            _validate_data(item)
    elif value is not None and type(value) not in (bool, int, float):
        raise ValueError('condition contains an unsupported value type')


def validate_contig(value: object) -> str:
    if not isinstance(value, str) or len(value) > 256:
        raise ValueError('contig must be a bounded native RFD4 string')
    tokens = [token.strip() for token in value.split(',')]
    if not tokens or any(not token or not CONTIG_TOKEN.fullmatch(token) for token in tokens):
        raise ValueError('invalid contig grammar')
    return value


def parse_condition_spec(path: Path) -> dict:
    text = path.read_text(encoding='utf-8')
    if len(text) > 65536:
        raise ValueError('condition specification exceeds 64 KiB')
    if path.suffix.lower() == '.json':
        spec = json.loads(text)
    else:
        import yaml
        spec = yaml.safe_load(text)
    if not isinstance(spec, dict) or not spec:
        raise ValueError('provide one or more named RFD4 design specifications')
    global_args = spec.get('global_args', {})
    if not isinstance(global_args, dict) or set(global_args) - SPEC_KEYS:
        raise ValueError('unsupported global_args directive')
    designs = {name: design for name, design in spec.items() if name != 'global_args'}
    if not designs:
        raise ValueError('provide one or more named RFD4 design specifications')
    resolved = {}
    for name, design in designs.items():
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', name):
            raise ValueError('invalid design name')
        if not isinstance(design, dict):
            raise ValueError('each named design must be a mapping')
        merged = {**global_args, **design}
        if set(merged) - SPEC_KEYS:
            raise ValueError('unsupported condition-spec directive')
        if 'input_as_annotated_cif' in merged and type(merged['input_as_annotated_cif']) is not bool:
            raise ValueError('input_as_annotated_cif must be a boolean, not a path')
        if 'input' in merged:
            supplied = merged['input']
            if not isinstance(supplied, (str, list)) or (
                isinstance(supplied, list) and any(not isinstance(item, str) for item in supplied)
            ):
                raise ValueError('condition-spec input must be a path string or a list of path strings')
        if 'contig' in merged:
            validate_contig(merged['contig'])
        conditions = merged.get('conditions', {})
        if not isinstance(conditions, dict):
            raise ValueError('conditions must be a mapping of RFD4 directives')
        unsupported = [key for key in conditions
                       if not (isinstance(key, str) and (key in CONDITION_KEYS or SEQ_PROB_KEY.fullmatch(key)))]
        if unsupported:
            raise ValueError('conditions must use supported RFD4 directive aliases')
        _validate_data(conditions)
        resolved[name] = merged
    _validate_data(resolved)
    return resolved


def prepare_input(condition: Path, scaffold: Path | None, scratch: Path) -> tuple[Path, int]:
    suffix = condition.suffix.lower()
    if suffix in {'.cif', '.mmcif', '.bcif'}:
        if scaffold is not None:
            raise ValueError('upload either an annotated CIF or a condition specification with its scaffold')
        text = condition.read_text(encoding='utf-8', errors='replace')
        if '_atom_site' not in text and 'ATOM' not in text:
            raise ValueError('annotated CIF input contains no atom records')
        return condition, 1
    if suffix not in {'.yaml', '.yml', '.json'}:
        raise ValueError('RFD4 input must be a native YAML/JSON condition specification or annotated CIF')
    if scaffold is None or not scaffold.is_file() or scaffold.suffix.lower() not in {'.cif', '.mmcif'}:
        raise ValueError('a YAML/JSON condition specification requires one CIF scaffold input')
    spec = parse_condition_spec(condition)
    for design in spec.values():
        design['input'] = str(scaffold)
    resolved = scratch / 'resolved_condition.yaml'
    import yaml
    resolved.write_text(yaml.safe_dump(spec, sort_keys=True), encoding='utf-8')
    return resolved, len(spec)


def build_command(input_path: Path, output: Path, num_designs: int, steps: int, seed: int,
                  weights: Path = WEIGHTS) -> list[str]:
    if (type(num_designs) is not int or not 1 <= num_designs <= 8
            or type(steps) is not int or not 1 <= steps <= 500
            or type(seed) is not int or not 0 <= seed <= 2147483647):
        raise ValueError('generation parameter outside supported bounds')
    return [
        'rfd4-generate', f'inputs={input_path}', f'out_dir={output}',
        f'num_replicates={num_designs}', f'seed={seed}',
        f'generation.args.nsteps={steps}', 'hardware.accelerator=gpu',
        'skip_existing=false', 'metrics_tags=[]',
        f'hf_ckpt_path={weights}', f'hydra.run.dir={output / "hydra"}',
    ]


AMINO_ACIDS = {
    'ALA', 'ARG', 'ASN', 'ASP', 'CYS', 'GLN', 'GLU', 'GLY', 'HIS', 'ILE',
    'LEU', 'LYS', 'MET', 'PHE', 'PRO', 'SER', 'THR', 'TRP', 'TYR', 'VAL',
}


def parse_atom_site(text: str) -> tuple[list[str], list[list[str]]]:
    """Parse the first atom_site loop with real CIF loop grammar.

    An incomplete final row is a truncation error, not a row to discard.
    """
    columns: list[str] = []
    values: list[str] = []
    atom_columns: list[str] = []
    atom_rows: list[list[str]] = []
    in_loop = False
    seen_values = False
    parsed = False

    def finish() -> None:
        nonlocal parsed, atom_columns
        if parsed or not columns:
            return
        if not any(column.startswith('_atom_site.') for column in columns):
            return
        if not all(column.startswith('_atom_site.') for column in columns):
            raise ValueError('atom_site loop mixes incompatible column categories')
        if not seen_values:
            raise ValueError('empty atom_site loop')
        if len(values) % len(columns):
            raise ValueError('truncated or incomplete atom_site loop')
        atom_columns = list(columns)
        atom_rows.extend(values[index:index + len(columns)] for index in range(0, len(values), len(columns)))
        parsed = True

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            if in_loop and seen_values:
                finish()
                in_loop = False
            continue
        if line == 'loop_':
            if in_loop:
                finish()
            in_loop, columns, values, seen_values = True, [], [], False
            continue
        if in_loop and seen_values and (
            line.startswith('_') or line.startswith('data_') or line.startswith('save_') or line == 'stop_'
        ):
            finish()
            in_loop = False
            continue
        if in_loop and line.startswith('_'):
            columns.append(line.split(maxsplit=1)[0].lower())
            continue
        if in_loop and columns:
            try:
                values.extend(shlex.split(line, comments=False, posix=True))
            except ValueError as exc:
                raise ValueError('malformed quoted atom_site data') from exc
            seen_values = True
            continue
        if in_loop:
            raise ValueError('atom_site loop has no columns')
    if in_loop:
        finish()
    if not parsed:
        raise ValueError('generated CIF has no atom_site loop')
    return atom_columns, atom_rows


def validate_generated_cif(path: Path) -> None:
    """Require grounded polymer backbone content, not a placeholder or ligand-only file."""
    text = path.read_text(encoding='utf-8', errors='replace')
    if len(text) > 10 * 1024 * 1024:
        raise ValueError(f'generated CIF exceeds the supported size: {path.name}')
    columns, rows = parse_atom_site(text)
    index = {name: position for position, name in enumerate(columns)}
    required = ('_atom_site.group_pdb', '_atom_site.label_atom_id', '_atom_site.label_comp_id',
                '_atom_site.label_asym_id', '_atom_site.label_seq_id',
                '_atom_site.cartn_x', '_atom_site.cartn_y', '_atom_site.cartn_z')
    if any(name not in index for name in required):
        raise ValueError(f'generated CIF omits polymer atom identity or coordinates: {path.name}')
    residue_atoms: dict[tuple[str, str, str], dict[str, object]] = {}
    for row in rows:
        if row[index['_atom_site.group_pdb']].upper() != 'ATOM':
            continue
        comp = row[index['_atom_site.label_comp_id']]
        if comp not in AMINO_ACIDS:
            continue
        chain = row[index['_atom_site.label_asym_id']]
        sequence = row[index['_atom_site.label_seq_id']]
        insertion_column = index.get('_atom_site.pdbx_pdb_ins_code')
        altloc_column = index.get('_atom_site.label_alt_id')
        insertion = row[insertion_column] if insertion_column is not None else '.'
        if sequence in {'.', '?'} or chain in {'.', '?'}:
            continue
        key = (chain, sequence, insertion)
        entry = residue_atoms.setdefault(key, {'comp': comp, 'atoms': set(), 'altlocs': set()})
        if entry['comp'] != comp:
            raise ValueError(f'generated CIF has inconsistent residue identity: {path.name}')
        atom = row[index['_atom_site.label_atom_id']].upper()
        if atom in entry['atoms']:
            raise ValueError(f'generated CIF repeats an atom in one residue: {path.name}')
        entry['atoms'].add(atom)
        entry['altlocs'].add(row[altloc_column] if altloc_column is not None else '.')
        for name in ('_atom_site.cartn_x', '_atom_site.cartn_y', '_atom_site.cartn_z'):
            try:
                float(row[index[name]])
            except ValueError as exc:
                raise ValueError(f'generated CIF has a non-numeric backbone coordinate: {path.name}') from exc
    if not residue_atoms:
        raise ValueError(f'ligand-only or non-polymer generated CIF: {path.name}')
    complete_by_chain: dict[str, int] = {}
    for (chain, _sequence, _insertion), entry in residue_atoms.items():
        altlocs = {value for value in entry['altlocs'] if value not in {'.', '?'}}
        if altlocs:
            raise ValueError(f'generated CIF has ambiguous alternate locations: {path.name}')
        if {'N', 'CA', 'C'}.issubset(entry['atoms']):
            complete_by_chain[chain] = complete_by_chain.get(chain, 0) + 1
    if not any(count >= 2 for count in complete_by_chain.values()):
        raise ValueError('insufficient polymer backbone: need two residues with N, CA and C')


def validate_outputs(output: Path, expected: int) -> list[Path]:
    sample_dir = output / 'inference_samples'
    designs = sorted(path for path in sample_dir.rglob('*_generated.cif')
                     if path.is_file() and path.stat().st_size > 0) if sample_dir.is_dir() else []
    if not designs:
        raise ValueError('RFD4 produced zero non-empty annotated CIF designs')
    if len(designs) != expected:
        raise ValueError(f'RFD4 produced {len(designs)} annotated CIF designs, expected {expected}')
    for design in designs:
        validate_generated_cif(design)
    return designs


def run_task(condition: Path, scaffold: Path | None, output: Path,
             num_designs: int, steps: int, seed: int) -> list[Path]:
    verify_assets()
    condition, output = condition.resolve(), output.resolve()
    if scaffold is not None:
        scaffold = scaffold.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='rfd4-input-') as temp_dir:
        native_input, examples = prepare_input(condition, scaffold, Path(temp_dir))
        command = build_command(native_input, output, num_designs, steps, seed)
        subprocess.run(command, check=True, cwd='/opt/RFD4-Proteina')
    return validate_outputs(output, examples * num_designs)


def main() -> int:
    condition_path, output, task_file = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    task = json.loads(task_file.read_text(encoding='utf-8'))
    roles = task.get('inputs', {})
    conditions = roles.get('condition', [])
    scaffolds = roles.get('scaffold', [])
    if len(conditions) != 1 or Path(conditions[0]['path']) != condition_path or len(scaffolds) > 1:
        raise ValueError('expected one condition input and at most one scaffold role')
    scaffold = Path(scaffolds[0]['path']) if scaffolds else None
    params = task.get('params')
    if not isinstance(params, dict) or set(params) - {'num_designs','steps','seed'}:
        raise ValueError('task has unsupported generation parameters')
    run_task(condition_path, scaffold, output, int(params['num_designs']),
             int(params['steps']), int(params['seed']))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
