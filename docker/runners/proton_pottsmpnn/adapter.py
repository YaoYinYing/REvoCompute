# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

WEIGHTS = Path('/mnt/db/weights/proton-pottsmpnn')
STATES = {'HIS-P': 'H', 'HIS-S': 'H', 'ASP-P': 'D', 'ASP-D': 'D', 'GLU-P': 'E', 'GLU-D': 'E'}
AA3 = {'ALA':'A','ARG':'R','ASN':'N','ASP':'D','CYS':'C','GLU':'E','GLN':'Q','GLY':'G','HIS':'H','ILE':'I','LEU':'L','LYS':'K','MET':'M','PHE':'F','PRO':'P','SER':'S','THR':'T','TRP':'W','TYR':'Y','VAL':'V'}


def verify_checkpoint() -> None:
    import hashlib
    relative = 'checkpoints/potts_v6_afdb_edge_his0.3_acid0.06/epoch-0125.ckpt'
    manifest = Path(__file__).with_name('model-assets.sha256')
    rows = [line.split(None, 1) for line in manifest.read_text(encoding='utf-8').splitlines()
            if line.strip() and not line.lstrip().startswith('#')]
    if len(rows) != 1 or len(rows[0]) != 2 or rows[0][1] != relative or not re.fullmatch(r'[0-9a-f]{64}', rows[0][0]):
        raise RuntimeError(f'ASSET_BLOCKED: verified checkpoint SHA256 required in {manifest}; provision under {WEIGHTS}')
    path = WEIGHTS / relative
    if not path.is_file() or path.stat().st_size != 21494143:
        raise RuntimeError(f'ASSET_BLOCKED: expected checkpoint missing or wrong size: {path}')
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    if digest.hexdigest() != rows[0][0]:
        raise RuntimeError(f'ASSET_BLOCKED: checkpoint SHA256 mismatch: {path}')


def read_chain_residues(path: Path) -> dict[str, dict[int, str]]:
    chains: dict[str, dict[int, str]] = {}
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        if not line.startswith('ATOM  ') or len(line) < 27:
            continue
        chain, residue = line[21], line[22:26].strip()
        if line[16] not in (' ', 'A') or not residue.lstrip('-').isdigit():
            continue
        name = AA3.get(line[17:20].strip())
        if name:
            chains.setdefault(chain, {})[int(residue)] = name
    if not chains:
        raise ValueError('complex contains no recognized protein residues')
    return chains


def validate_request(data: object, chains: dict[str, dict[int, str]]) -> dict:
    if not isinstance(data, dict) or set(data) - {'binder_chain','designable_residues','locked_residues','centres','states','lambda','block_size','temperature','neighbour_count','mutation_cap','seed'}:
        raise ValueError('unsupported task parameter')
    binder = data.get('binder_chain')
    if binder not in chains:
        raise ValueError('binder chain is missing from the complex')
    positions = set(chains[binder])
    designable, locked = data.get('designable_residues'), data.get('locked_residues', [])
    if not isinstance(designable, list) or not designable or any(type(x) is not int or x not in positions for x in designable):
        raise ValueError('designable residues must map to binder positions')
    if not isinstance(locked, list) or any(type(x) is not int or x not in positions for x in locked):
        raise ValueError('locked residues must map to binder positions')
    if set(designable) & set(locked):
        raise ValueError('a residue cannot be both designable and locked')
    states = data.get('states')
    if not isinstance(states, list) or len(states) != 2 or any(s not in STATES for s in states) or states[0] == states[1]:
        raise ValueError('states must be two distinct v6 protonation tokens')
    centres = data.get('centres')
    if not isinstance(centres, list) or not centres:
        raise ValueError('at least one centre is required')
    for centre in centres:
        if not isinstance(centre, dict) or set(centre) != {'position','state'} or type(centre['position']) is not int or centre['state'] not in STATES:
            raise ValueError('invalid centre grammar')
        actual = chains[binder].get(centre['position'])
        if actual != STATES[centre['state']]:
            raise ValueError('centre state does not match the input residue type')
    if not 1 <= int(data.get('block_size', 1)) <= 64 or not 1 <= int(data.get('neighbour_count', 8)) <= 128:
        raise ValueError('optimizer setting outside supported bounds')
    if not 1 <= int(data.get('mutation_cap', 20)) <= len(designable):
        raise ValueError('mutation cap exceeds designable positions')
    return data


def validate_vocabulary(tokens: object) -> None:
    required = set('ACDEFGHIKLMNPQRSTVWY') | set(STATES)
    if not isinstance(tokens, list) or len(tokens) != 30 or len(set(tokens)) != 30 or not required.issubset(tokens):
        raise ValueError('checkpoint vocabulary is not the expected 30-token v6 vocabulary')


def build_command(input_path: Path, config_path: Path, output: Path) -> list[str]:
    return ['python', '/opt/ProtonPottsMPNN/inference/design_ph.py', '--input', str(input_path),
            '--config', str(config_path), '--output', str(output)]


def validate_outputs(output: Path, original: dict[int, str], locked: list[int], mutation_cap: int) -> None:
    candidates = output / 'candidates'
    files = list(candidates.glob('*.fa')) if candidates.is_dir() else []
    positions = sorted(original)
    if not files:
        raise ValueError('missing candidate FASTA outputs')
    for fasta in files:
        lines = fasta.read_text(encoding='utf-8').splitlines()
        sequence = ''.join(line.strip() for line in lines if line and not line.startswith('>'))
        if not lines or not lines[0].startswith('>') or len(sequence) != len(positions) or set(sequence) - set(AA3.values()):
            raise ValueError('malformed candidate FASTA output')
        changes = {position for position, residue in zip(positions, sequence) if residue != original[position]}
        if changes & set(locked) or len(changes) > mutation_cap:
            raise ValueError('candidate changed a locked residue or exceeded mutation cap')
    score = output / 'design_scores.json'
    try:
        data = json.loads(score.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError('missing or malformed design score output') from exc
    if not isinstance(data, dict) or not data:
        raise ValueError('design score output must be a non-empty object')


def main() -> int:
    input_path, output, task_file = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    manifest = json.loads(task_file.read_text(encoding='utf-8'))
    data = manifest.get('params')
    if not isinstance(data, dict):
        raise ValueError('task manifest has no resolved parameters')
    verify_checkpoint()
    chains = read_chain_residues(input_path)
    validate_request(data, chains)
    original = chains[data['binder_chain']]
    vocab_path = WEIGHTS / 'vocab.json'
    if not vocab_path.is_file():
        raise RuntimeError(f'ASSET_BLOCKED: verified 30-token v6 vocabulary metadata missing at {vocab_path}')
    validate_vocabulary(json.loads(vocab_path.read_text(encoding='utf-8')))
    output.mkdir(parents=True, exist_ok=True)
    config = output / 'task_config.json'
    config.write_text(json.dumps(data, sort_keys=True), encoding='utf-8')
    subprocess.run(build_command(input_path, config, output), check=True)
    validate_outputs(output, original, data.get('locked_residues', []), int(data.get('mutation_cap', 20)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
