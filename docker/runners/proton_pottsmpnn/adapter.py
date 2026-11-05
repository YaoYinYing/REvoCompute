# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

WEIGHTS = Path('/mnt/db/weights/proton-pottsmpnn')
CHECKPOINT_RELATIVE = 'checkpoints/potts_v6_afdb_edge_his0.3_acid0.06/epoch-0125.ckpt'
STATES = {'HIS-P': ('H', 'HIS-S'), 'HIS-S': ('H', 'HIS-P'),
          'ASP-P': ('D', 'ASP-D'), 'ASP-D': ('D', 'ASP-P'),
          'GLU-P': ('E', 'GLU-D'), 'GLU-D': ('E', 'GLU-P')}
STATE_PAIRS = {'HIS-P': 'HIS-S', 'ASP-P': 'ASP-D', 'GLU-P': 'GLU-D'}
AA3 = {'ALA':'A','ARG':'R','ASN':'N','ASP':'D','CYS':'C','GLU':'E','GLN':'Q','GLY':'G',
       'HIS':'H','ILE':'I','LEU':'L','LYS':'K','MET':'M','PHE':'F','PRO':'P','SER':'S',
       'THR':'T','TRP':'W','TYR':'Y','VAL':'V'}
V6_TOKENS = set(AA3) | set(STATES) | {'UNK'}


def verify_checkpoint(manifest_path: Path | None = None) -> Path:
    import hashlib
    manifest = manifest_path or Path(__file__).with_name('model-assets.sha256')
    rows = [line.split(None, 1) for line in manifest.read_text(encoding='utf-8').splitlines()
            if line.strip() and not line.lstrip().startswith('#')]
    if (len(rows) != 1 or len(rows[0]) != 2 or rows[0][1] != CHECKPOINT_RELATIVE
            or not re.fullmatch(r'[0-9a-f]{64}', rows[0][0])):
        raise RuntimeError(f'ASSET_BLOCKED: verified checkpoint SHA256 required in {manifest}; provision under {WEIGHTS}')
    checkpoint = WEIGHTS / CHECKPOINT_RELATIVE
    if not checkpoint.is_file() or checkpoint.stat().st_size != 21494143:
        raise RuntimeError(f'ASSET_BLOCKED: expected checkpoint missing or wrong size: {checkpoint}')
    digest = hashlib.sha256()
    with checkpoint.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    if digest.hexdigest() != rows[0][0]:
        raise RuntimeError(f'ASSET_BLOCKED: checkpoint SHA256 mismatch: {checkpoint}')
    return checkpoint


def read_binder_residues(path: Path, binder_chain: object,
                         centre_positions: set[int]) -> dict[int, str]:
    """Map the binder chain's authored residue numbering, refusing ambiguous addressing."""
    if not isinstance(binder_chain, str) or len(binder_chain) != 1:
        raise ValueError('binder_chain must be one PDB chain identifier')
    residues: dict[int, dict[str, object]] = {}
    after_ter = False
    previous_position: int | None = None
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        if line.startswith('TER'):
            after_ter = True
            continue
        if not line.startswith('ATOM  ') or len(line) < 27 or line[21] != binder_chain:
            continue
        residue_text = line[22:26].strip()
        if not residue_text.lstrip('-').isdigit():
            raise ValueError(f'binder residue number is not an integer: {residue_text!r}')
        position = int(residue_text)
        insertion = line[26]
        if insertion.strip():
            raise ValueError(
                f'binder residue {position} uses insertion code {insertion!r}; residue addressing is ambiguous'
            )
        entry = residues.get(position)
        if entry is None:
            if previous_position is not None and position < previous_position:
                raise ValueError(
                    f'binder residues must appear in ascending authored order; '
                    f'{position} follows {previous_position}'
                )
            previous_position = position
        elif position != previous_position:
            raise ValueError(f'binder residue numbering repeats or is out of order at {position}')
        name = AA3.get(line[17:20].strip())
        if name is None:
            continue
        if entry is None:
            residues[position] = {'names': {name}, 'altlocs': {line[16]}, 'after_ter': after_ter}
            continue
        if after_ter and not entry['after_ter']:
            raise ValueError(f'binder residue {position} has duplicate numbering across a chain break')
        names = entry['names']
        assert isinstance(names, set)
        names.add(name)
        if len(names) > 1:
            raise ValueError(f'binder residue {position} has duplicate numbering with conflicting residue types')
        altlocs = entry['altlocs']
        assert isinstance(altlocs, set)
        altlocs.add(line[16])
    if not residues:
        raise ValueError('binder chain contains no recognized protein residues')
    for position in centre_positions:
        entry = residues.get(position)
        if entry is None or len(entry['names']) != 1:
            raise ValueError(f'requested centre {position} does not resolve to one binder residue')
        altlocs = {value for value in entry['altlocs'] if value.strip()}
        if altlocs:
            raise ValueError(
                f'requested centre {position} has alternate locations {sorted(altlocs)}; '
                'residue addressing is ambiguous'
            )
    return {position: next(iter(entry['names'])) for position, entry in residues.items()}


def validate_request(data: object, binder_residues: dict[int, str]) -> dict:
    allowed = {'binder_chain','centres','states','combined_lambda','block_size','temperature',
               'neighbour_k','max_mutations','samples_per_site','seed'}
    if not isinstance(data, dict) or set(data) - allowed:
        raise ValueError('unsupported task parameter')
    binder = data.get('binder_chain')
    if not isinstance(binder, str) or len(binder) != 1:
        raise ValueError('binder_chain must be one PDB chain identifier')
    states = data.get('states')
    if (not isinstance(states, list) or len(states) != 2 or states[0] not in STATE_PAIRS
            or STATE_PAIRS[states[0]] != states[1]):
        raise ValueError('states must be one supported protonated/deprotonated v6 pair')
    centres = data.get('centres')
    if not isinstance(centres, list) or not centres or len(centres) > 30:
        raise ValueError('at least one and at most 30 centres are required')
    seen: set[int] = set()
    for centre in centres:
        if (not isinstance(centre, dict) or set(centre) != {'position','state'}
                or type(centre['position']) is not int or centre['state'] != states[0]):
            raise ValueError('each centre must use the protonated token from the selected v6 state pair')
        pos = centre['position']
        if pos not in binder_residues or binder_residues[pos] != STATES[centre['state']][0] or pos in seen:
            raise ValueError('centre position is duplicated, missing, or has the wrong input residue type')
        seen.add(pos)
    if type(data.get('block_size', 2)) is not int or not 1 <= data.get('block_size', 2) <= 8:
        raise ValueError('block_size must be between 1 and 8')
    if type(data.get('neighbour_k', 8)) is not int or not 1 <= data.get('neighbour_k', 8) <= 128:
        raise ValueError('neighbour_k must be between 1 and 128')
    if type(data.get('max_mutations', 20)) is not int or not 1 <= data.get('max_mutations', 20) <= 500:
        raise ValueError('max_mutations must be between 1 and 500')
    if type(data.get('samples_per_site', 1)) is not int or not 1 <= data.get('samples_per_site', 1) <= 8:
        raise ValueError('samples_per_site must be between 1 and 8')
    if type(data.get('seed', 0)) is not int or not 0 <= data.get('seed', 0) <= 2147483647:
        raise ValueError('seed must be a nonnegative 32-bit integer')
    weight = data.get('combined_lambda', 0.5)
    temperature = data.get('temperature', 0.05)
    if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not 0 <= weight <= 1:
        raise ValueError('combined_lambda must be between 0 and 1')
    if isinstance(temperature, bool) or not isinstance(temperature, (int, float)) or not 0 <= temperature <= 2:
        raise ValueError('temperature must be between 0 and 2')
    return data


def criteria_parameters(data: dict) -> dict:
    state_pair = data['states']
    return {
        'method': 'block_descent',
        'backend': 'potts',
        'seed_source': 'native',
        'dep_map': {state_pair[0]: [state_pair[1]]},
        'forbidden_tokens': ['HIS-A', 'ASP-A', 'GLU-A', 'UNK'],
        'explicit_centers': [
            {'res_id': centre['position'], 'protonation_type': centre['state']}
            for centre in data['centres']
        ],
        'center_count': len(data['centres']),
        'combined_lambda': float(data.get('combined_lambda', 0.5)),
        'block_size': data.get('block_size', 2),
        'temperature': float(data.get('temperature', 0.05)),
        'neighbour_k': data.get('neighbour_k', 8),
        'max_mutations': data.get('max_mutations', 20),
        'samples_per_site': data.get('samples_per_site', 1),
        'record_trajectory': False,
    }


def validate_vocabulary(tokens: object) -> None:
    required = set('ACDEFGHIKLMNPQRSTVWY') | {'UNK'} | {
        'HIS-P','HIS-S','HIS-A','ASP-P','ASP-D','ASP-A','GLU-P','GLU-D','GLU-A'
    }
    if isinstance(tokens, Mapping):
        tokens = set(tokens)
    if not isinstance(tokens, (list, tuple, set)) or set(tokens) != required or len(tokens) != 30:
        raise ValueError('checkpoint vocabulary is not the pinned 30-token v6 vocabulary')


def write_outputs(output: Path, designs: list[Any], params: dict, checkpoint: Path,
                  upstream_revision: str = '09682abfa7d20e0abcdeea0490b7a4b1c190aee3') -> None:
    if not designs:
        raise ValueError('PottsMPNN returned zero designs')
    candidates = output / 'candidates'
    candidates.mkdir(parents=True, exist_ok=True)
    metadata = [design.to_metadata() for design in designs]
    if any(not design.canonical_sequence or not design.extended_tokens for design in designs):
        raise ValueError('PottsMPNN returned a design without canonical and protonation-token sequences')
    with (candidates / 'designs.fa').open('w', encoding='utf-8') as handle:
        for design in designs:
            handle.write(f">{design.design_id()}\n{design.canonical_sequence}\n")
    with (candidates / 'designs_states.fa').open('w', encoding='utf-8') as handle:
        for design in designs:
            handle.write(f">{design.design_id()}\n{' '.join(design.extended_tokens)}\n")
    payload = {
        'schema_version': 1,
        'score_semantics': 'Model proxy energies; lower is better. Not measured pKa, affinity, or pH-selective binding.',
        'objective_terms': ['potts_energy', 'selective_energy', 'global_protonation_dH'],
        'designs': metadata,
        'parameters': params,
        'checkpoint_path': str(checkpoint),
        'checkpoint_sha256': checkpoint_sha256(checkpoint),
        'upstream_revision': upstream_revision,
    }
    (output / 'design_scores.json').write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=float) + '\n', encoding='utf-8'
    )
    config = {'parameters': params, 'checkpoint_path': str(checkpoint), 'upstream_revision': upstream_revision}
    (output / 'task_config.json').write_text(
        json.dumps(config, indent=2, sort_keys=True) + '\n', encoding='utf-8'
    )


def checkpoint_sha256(path: Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def run_design(input_path: Path, output: Path, params: dict, *, checkpoint: Path,
               engine_type: Any, criteria_type: Any, load_structure: Any) -> None:
    centres = params.get('centres')
    centre_positions = {
        centre['position'] for centre in centres
        if isinstance(centre, dict) and type(centre.get('position')) is int
    } if isinstance(centres, list) else set()
    binder_residues = read_binder_residues(input_path, params.get('binder_chain'), centre_positions)
    validate_request(params, binder_residues)
    criteria = criteria_type.from_params(criteria_parameters(params))
    engine = engine_type(
        checkpoint_path=str(checkpoint), extended_vocab='v6', out_directory=None,
        write_fasta=False, write_structures=False,
    )
    designs = engine.run_ph_redesign(
        atom_array=load_structure(input_path), binder_chain=params['binder_chain'],
        criteria_list=[criteria], seed=params.get('seed', 0),
    )
    output.mkdir(parents=True, exist_ok=True)
    write_outputs(output, list(designs), params, checkpoint)
    validate_outputs(output, binder_residues, params['centres'], params['states'])


def main() -> int:
    input_path, output, task_file = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    manifest = json.loads(task_file.read_text(encoding='utf-8'))
    params = manifest.get('params')
    if not isinstance(params, dict):
        raise ValueError('task manifest has no resolved parameters')
    input_roles = manifest.get('inputs', {}).get('complex', [])
    if len(input_roles) != 1 or Path(input_roles[0]['path']).resolve() != input_path.resolve():
        raise ValueError('complex input must be the single named complex role')
    checkpoint = verify_checkpoint()
    from biotite.structure.io.pdb import PDBFile
    from mpnn.inference_engines.potts_mpnn_ph import PHDesignCriteria, PottsMPNNPHEngine
    from mpnn.transforms.feature_aggregation.token_encodings import POTTS_MPNN_V6_TOKEN_ENCODING
    validate_vocabulary(POTTS_MPNN_V6_TOKEN_ENCODING.token_atoms)
    run_design(input_path, output, params, checkpoint=checkpoint,
               engine_type=PottsMPNNPHEngine, criteria_type=PHDesignCriteria,
               load_structure=lambda path: PDBFile.read(str(path)).get_structure(model=1))
    return 0


def validate_outputs(output: Path, binder_residues: dict[int, str], centres: list[dict],
                     states: list[str]) -> None:
    canonical = output / 'candidates' / 'designs.fa'
    states_file = output / 'candidates' / 'designs_states.fa'
    try:
        canonical_records = [line.strip() for line in canonical.read_text(encoding='utf-8').splitlines()
                             if line.strip() and not line.startswith('>')]
        state_records = [line.strip() for line in states_file.read_text(encoding='utf-8').splitlines()
                         if line.strip() and not line.startswith('>')]
        scores = json.loads((output / 'design_scores.json').read_text(encoding='utf-8'))
        config = json.loads((output / 'task_config.json').read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError('missing or malformed Proton-PottsMPNN result artifacts') from exc
    designs = scores.get('designs', [])
    if not isinstance(designs, list) or not canonical_records or not state_records:
        raise ValueError('PottsMPNN produced no aligned candidate designs')
    if not (len(canonical_records) == len(state_records) == len(designs)):
        raise ValueError('candidate sequences, protonation states, and score records are misaligned')
    positions = list(binder_residues)
    expected_centres = sorted((int(c['position']), str(c['state'])) for c in centres)
    requested_tokens = {str(c['state']) for c in centres}
    for index, (sequence, state_line, design) in enumerate(zip(canonical_records, state_records, designs)):
        tokens = state_line.split()
        if len(sequence) != len(positions) or len(tokens) != len(positions):
            raise ValueError(f'design {index} does not match the binder chain length')
        if set(sequence) - set(AA3.values()) or set(tokens) - V6_TOKENS:
            raise ValueError(f'design {index} contains an unsupported sequence or protonation token')
        for position, state in expected_centres:
            if position not in binder_residues:
                raise ValueError(f'requested centre {position} is absent from the binder chain')
            offset = positions.index(position)
            if tokens[offset] != state or sequence[offset] != STATES[state][0]:
                raise ValueError(f'design {index} does not preserve requested centre {position}:{state}')
        if not isinstance(design, dict) or not design.get('design_id'):
            raise ValueError(f'design {index} has no score metadata identity')
        if str(design.get('extended_tokens', '')) != state_line:
            raise ValueError(f'design {index} score metadata disagrees with its protonation sequence')
        recorded = sorted(zip(design.get('center_res_ids') or [], design.get('center_protonation_types') or []))
        if recorded != expected_centres:
            raise ValueError(f'design {index} score metadata does not match the requested centres')
        if set(design.get('center_protonation_types') or []) != requested_tokens:
            raise ValueError(f'design {index} score metadata does not match the requested states')
    if not config.get('checkpoint_path'):
        raise ValueError('result provenance omits the checkpoint path')


if __name__ == '__main__':
    raise SystemExit(main())
