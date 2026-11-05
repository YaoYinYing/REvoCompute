# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

WEIGHTS = Path('/mnt/db/weights/rfd4-proteina')
CONTIG_TOKEN = re.compile(
    r'(?:/\d+|\d+(?:-\d+)?|[A-Za-z][A-Za-z0-9]*\d+(?::\d+)?(?:-\d+[A-Za-z]?|R)?)\Z'
)
SPEC_KEYS = {'input', 'input_as_annotated_cif', 'contig', 'conditions'}
CONDITION_KEYS = {'C_CRD', 'C_CRDGRP', 'C_SEQ', 'C_HOT'}


def verify_assets() -> None:
    import hashlib
    manifest = Path(__file__).with_name('model-assets.sha256')
    rows = [line.split(None, 1) for line in manifest.read_text(encoding='utf-8').splitlines()
            if line.strip() and not line.lstrip().startswith('#')]
    if not rows or any(len(row) != 2 or not re.fullmatch(r'[0-9a-f]{64}', row[0]) for row in rows):
        raise RuntimeError(f'ASSET_BLOCKED: verified file hashes required in {manifest}; provision at {WEIGHTS}')
    for digest, relative in rows:
        path = (WEIGHTS / relative).resolve()
        if not path.is_relative_to(WEIGHTS.resolve()) or not path.is_file():
            raise RuntimeError(f'ASSET_BLOCKED: required asset missing: {relative}')
        hasher = hashlib.sha256()
        with path.open('rb') as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                hasher.update(chunk)
        if hasher.hexdigest() != digest:
            raise RuntimeError(f'ASSET_BLOCKED: SHA256 mismatch: {relative}')


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
            if not isinstance(key, (str, bool, int)):
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
    if not isinstance(spec, dict) or not spec or 'global_args' in spec:
        raise ValueError('provide one or more named native design specifications; global overrides are unsupported')
    for name, design in spec.items():
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', name):
            raise ValueError('invalid design name')
        if not isinstance(design, dict) or set(design) - SPEC_KEYS:
            raise ValueError('unsupported condition-spec directive')
        validate_contig(design.get('contig'))
        conditions = design.get('conditions')
        if not isinstance(conditions, dict) or not conditions or set(conditions) - CONDITION_KEYS:
            raise ValueError('conditions must use supported native RFD4 motif directives')
        _validate_data(conditions)
    _validate_data(spec)
    return spec


def prepare_input(condition: Path, scaffold: Path | None, scratch: Path) -> Path:
    suffix = condition.suffix.lower()
    if suffix in {'.cif', '.mmcif', '.bcif'}:
        if scaffold is not None:
            raise ValueError('upload either an annotated CIF or a condition specification with its scaffold')
        text = condition.read_text(encoding='utf-8', errors='replace')
        if '_atom_site' not in text and 'ATOM' not in text:
            raise ValueError('annotated CIF input contains no atom records')
        return condition
    if suffix not in {'.yaml', '.yml', '.json'}:
        raise ValueError('RFD4 input must be a native YAML/JSON condition specification or annotated CIF')
    if scaffold is None or not scaffold.is_file() or scaffold.suffix.lower() not in {'.cif', '.mmcif'}:
        raise ValueError('a native condition specification requires one CIF scaffold input')
    spec = parse_condition_spec(condition)
    for design in spec.values():
        design['input'] = str(scaffold)
    resolved = scratch / 'resolved_condition.yaml'
    import yaml
    resolved.write_text(yaml.safe_dump(spec, sort_keys=True), encoding='utf-8')
    return resolved


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
        f'hf_ckpt_path={weights}', f'hydra.run.dir={output / "hydra"}',
    ]


def validate_outputs(output: Path) -> list[Path]:
    sample_dir = output / 'inference_samples'
    designs = sorted(path for path in sample_dir.rglob('*_generated.cif')
                     if path.is_file() and path.stat().st_size > 0) if sample_dir.is_dir() else []
    if not designs:
        raise ValueError('RFD4 produced zero non-empty annotated CIF designs')
    return designs


def run_task(condition: Path, scaffold: Path | None, output: Path,
             num_designs: int, steps: int, seed: int) -> list[Path]:
    verify_assets()
    condition, output = condition.resolve(), output.resolve()
    if scaffold is not None:
        scaffold = scaffold.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='rfd4-input-') as temp_dir:
        native_input = prepare_input(condition, scaffold, Path(temp_dir))
        command = build_command(native_input, output, num_designs, steps, seed)
        subprocess.run(command, check=True, cwd='/opt/RFD4-Proteina')
    return validate_outputs(output)


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
