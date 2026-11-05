# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

WEIGHTS = Path('/mnt/db/weights/rfd4-proteina')
ALLOWED = {'contig', 'motif', 'chain', 'residues', 'sequence'}
CONTIG = re.compile(r'(?:\d+|[A-Za-z]:\d+-\d+)(?:/(?:\d+|[A-Za-z]:\d+-\d+))*\Z')


def validate_condition(data: object) -> dict:
    if not isinstance(data, dict) or set(data) - ALLOWED:
        raise ValueError('condition must be an object containing only supported condition fields')
    if 'contig' in data and (not isinstance(data['contig'], str) or not CONTIG.fullmatch(data['contig'])):
        raise ValueError('invalid contig grammar')
    if 'chain' in data and (not isinstance(data['chain'], str) or not re.fullmatch(r'[A-Za-z0-9]', data['chain'])):
        raise ValueError('invalid chain identifier')
    if 'residues' in data:
        residues = data['residues']
        if not isinstance(residues, list) or not residues or any(
            not isinstance(r, int) or isinstance(r, bool) or r < 1 for r in residues
        ):
            raise ValueError('residues must be positive one-based integers')
    if 'motif' in data and (not isinstance(data['motif'], str) or not re.fullmatch(r'[ACDEFGHIKLMNPQRSTVWYXBZJUO]{1,64}', data['motif'])):
        raise ValueError('invalid motif sequence')
    def unsafe(value: object) -> bool:
        if isinstance(value, str):
            return any(char in value for char in ('$','`','\\n',';'))
        if isinstance(value, list):
            return any(unsafe(item) for item in value)
        if isinstance(value, dict):
            return any(unsafe(key) or unsafe(item) for key, item in value.items())
        return False
    if unsafe(data):
        raise ValueError('shell interpolation and directives are not accepted')
    return data


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


def validate_outputs(metrics: Path) -> dict:
    try:
        data = json.loads(metrics.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError('upstream produced missing or malformed condition_metrics.json') from exc
    if not isinstance(data, dict) or not data:
        raise ValueError('upstream condition_metrics.json must be a non-empty object')
    return data


def build_command(spec: Path, output: Path, num_designs: int, steps: int, seed: int) -> list[str]:
    if not 1 <= num_designs <= 8 or not 1 <= steps <= 500 or not 0 <= seed <= 2147483647:
        raise ValueError('generation parameter outside supported bounds')
    return ['rfd4-generate', '--config', str(spec), '--output-dir', str(output),
            '--num-designs', str(num_designs), '--steps', str(steps), '--seed', str(seed)]


def main() -> int:
    spec, output, task_file = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    manifest = json.loads(task_file.read_text(encoding='utf-8'))
    scaffold_files = manifest.get('inputs', {}).get('scaffold', [])
    if len(scaffold_files) > 1:
        raise ValueError('scaffold role accepts at most one input')
    scaffold = scaffold_files[0]['path'] if scaffold_files else None
    verify_assets()
    try:
        import yaml
        raw = yaml.safe_load(spec.read_text(encoding='utf-8'))
        validate_condition(raw)
    except Exception as exc:
        raise SystemExit(f'invalid condition specification: {exc}') from exc
    if scaffold is not None:
        if not Path(scaffold).is_file():
            raise ValueError('scaffold role path does not exist')
        raw['scaffold_path'] = scaffold
    output.mkdir(parents=True, exist_ok=True)
    safe = output / 'condition.json'
    safe.write_text(json.dumps(raw, sort_keys=True), encoding='utf-8')
    command = build_command(safe, output, int(sys.argv[4]), int(sys.argv[5]), int(sys.argv[6]))
    subprocess.run(command, check=True)
    metrics = output / 'condition_metrics.json'
    validate_outputs(metrics)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
