from __future__ import annotations

import importlib.util
import json
from pathlib import Path

MODULE = Path(__file__).resolve().parents[2] / 'adapter.py'
ROOT = Path(__file__).resolve().parents[5]

spec = importlib.util.spec_from_file_location('proton_adapter', MODULE)
assert spec and spec.loader
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


class FakeDesign:
    canonical_sequence = 'HDEA'
    extended_tokens = ['HIS-P', 'ASP-D', 'GLU-D', 'ALA']

    def design_id(self):
        return 'fake-design'

    def to_metadata(self):
        return {'design_id': self.design_id(), 'potts_energy': -2.0, 'selective_energy': -1.0,
                'global_protonation_dH': -0.5, 'extended_tokens': ' '.join(self.extended_tokens),
                'center_res_ids': [1], 'center_protonation_types': ['HIS-P']}


class FakeCriteria:
    @classmethod
    def from_params(cls, params):
        cls.params = params
        return ('criteria', params)


class FakeEngine:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.__class__.instances.append(self)

    def run_ph_redesign(self, **kwargs):
        self.run_kwargs = kwargs
        return [FakeDesign()]


def test_pinned_v6_vocabulary_is_the_three_letter_token_contract():
    vocab = set(adapter.AA3) | {'UNK'} | adapter.V6_PROTONATION_TOKENS
    assert len(vocab) == 30
    adapter.validate_vocabulary(vocab)
    adapter.validate_vocabulary({token: None for token in vocab})
    try:
        # Upstream token_atoms is keyed by three-letter CCD tokens, never by one-letter codes.
        adapter.validate_vocabulary(set('ACDEFGHIKLMNPQRSTVWY') | {'UNK'} | adapter.V6_PROTONATION_TOKENS)
    except ValueError:
        pass
    else:
        raise AssertionError('one-letter vocabulary accepted')
    bad = vocab - {'HIS-P'} | {'HIS-X'}
    try:
        adapter.validate_vocabulary(bad)
    except ValueError:
        pass
    else:
        raise AssertionError('wrong checkpoint vocabulary accepted')
    assert adapter.STATE_PAIRS == {'HIS-P': 'HIS-S', 'ASP-P': 'ASP-D', 'GLU-P': 'GLU-D'}
    try:
        from mpnn.transforms.feature_aggregation.token_encodings import POTTS_MPNN_V6_TOKEN_ENCODING
    except ImportError:
        pass
    else:
        adapter.validate_vocabulary(POTTS_MPNN_V6_TOKEN_ENCODING.token_atoms)


def test_api_binding_uses_task_input_parameters_checkpoint_and_output(tmp_path, capsys):
    pdb = tmp_path / 'complex.pdb'
    pdb.write_text(
        'ATOM      1  CA  HIS A   1      11.000  12.000  13.000  1.00 20.00           C\n'
        'ATOM      2  CA  ASP A   2      12.000  12.000  13.000  1.00 20.00           C\n'
        'ATOM      3  CA  GLU A   3      13.000  12.000  13.000  1.00 20.00           C\n'
        'ATOM      4  CA  ALA A   4      14.000  12.000  13.000  1.00 20.00           C\n'
        'ATOM      5  CA  GLU B   1      15.000  12.000  13.000  1.00 20.00           C\n',
        encoding='utf-8',
    )
    checkpoint = tmp_path / 'epoch-0125.ckpt'
    checkpoint.write_bytes(b'pinned-checkpoint-fixture')
    output = tmp_path / 'out'
    task = {
        'binder_chain': 'A', 'centres': [{'position': 1, 'state': 'HIS-P'}],
        'states': ['HIS-P', 'HIS-S'], 'combined_lambda': 0.4,
        'block_size': 2, 'temperature': 0.05, 'neighbour_k': 7,
        'max_mutations': 12, 'samples_per_site': 2, 'seed': 17,
    }
    atom_array = object()
    FakeEngine.instances.clear()
    adapter.run_design(pdb, output, task, checkpoint=checkpoint,
                       engine_type=FakeEngine, criteria_type=FakeCriteria,
                       load_structure=lambda path: atom_array)

    engine = FakeEngine.instances[-1]
    assert 'REVODESIGN_STAGE:design' in capsys.readouterr().out
    assert engine.kwargs == {
        'checkpoint_path': str(checkpoint), 'extended_vocab': 'v6', 'out_directory': None,
        'write_fasta': False, 'write_structures': False,
    }
    assert engine.run_kwargs['atom_array'] is atom_array
    assert engine.run_kwargs['binder_chain'] == 'A'
    assert engine.run_kwargs['seed'] == 17
    assert engine.run_kwargs['criteria_list'] == [('criteria', FakeCriteria.params)]
    scores = json.loads((output / 'design_scores.json').read_text(encoding='utf-8'))
    assert scores['designs'][0]['potts_energy'] == -2.0
    assert scores['designs'][0]['extended_tokens'] == 'HIS-P ASP-D GLU-D ALA'
    assert scores['designs'][0]['protonation_tokens'] == ['HIS-P', 'ASP-D', 'GLU-D', 'ALA']
    assert scores['checkpoint_path'] == str(checkpoint)
    assert (output / 'candidates' / 'designs.fa').read_text(encoding='utf-8') == '>fake-design\nHDEA\n'
    assert (output / 'candidates' / 'designs_states.fa').read_text(encoding='utf-8') == '>fake-design\nHIS-P ASP-D GLU-D ALA\n'
    adapter.validate_outputs(output, {1:'H',2:'D',3:'E',4:'A'}, task['centres'], task['states'])


def test_engine_receives_checkpoint_v6_and_task_bound_inputs(tmp_path):
    pdb = tmp_path / 'complex.pdb'
    pdb.write_text(
        'ATOM      1  CA  HIS A   1      11.000  12.000  13.000  1.00 20.00           C\n'
        'ATOM      2  CA  ASP A   2      12.000  12.000  13.000  1.00 20.00           C\n'
        'ATOM      3  CA  GLU A   3      13.000  12.000  13.000  1.00 20.00           C\n'
        'ATOM      4  CA  ALA A   4      14.000  12.000  13.000  1.00 20.00           C\n',
        encoding='utf-8',
    )
    checkpoint = tmp_path / 'epoch-0125.ckpt'
    checkpoint.write_bytes(b'checkpoint')
    task = {'binder_chain':'A','centres':[{'position':1,'state':'HIS-P'}],
            'states':['HIS-P','HIS-S'],'seed':9}
    captured = {}

    class Engine(FakeEngine):
        def __init__(self, **kwargs):
            captured['engine'] = kwargs

        def run_ph_redesign(self, **kwargs):
            captured['run'] = kwargs
            return [FakeDesign()]

    adapter.run_design(pdb, tmp_path / 'output', task, checkpoint=checkpoint,
                       engine_type=Engine, criteria_type=FakeCriteria,
                       load_structure=lambda path: 'parsed-atom-array')
    assert captured['engine'] == {
        'checkpoint_path': str(checkpoint), 'extended_vocab': 'v6', 'out_directory': None,
        'write_fasta': False, 'write_structures': False,
    }
    assert captured['run']['atom_array'] == 'parsed-atom-array'
    assert captured['run']['binder_chain'] == 'A'
    assert captured['run']['criteria_list'] == [('criteria', FakeCriteria.params)]
    assert captured['run']['seed'] == 9


def pdb_line(serial, atom, comp, chain, position, *, icode=' ', altloc=' ', x=11.0):
    return (
        f'ATOM  {serial:5d} {atom:^4}{altloc}{comp:>3} {chain}{position:>4}{icode}'
        f'      {x:8.3f}{12.0:8.3f}{13.0:8.3f}  1.00 20.00           {atom[0]:>2}\n'
    )


def test_two_chain_smoke_complex_binder_addressing_is_accepted():
    mapping = adapter.read_binder_residues(
        ROOT / 'tests' / 'data' / 'proton_pottsmpnn' / 'complex.pdb', 'B', {9}
    )
    assert len(mapping) == 115
    assert mapping[9] == 'D'


def test_zero_and_negative_authored_residue_numbers_are_supported(tmp_path):
    pdb = tmp_path / 'complex.pdb'
    pdb.write_text(
        ''.join([
            pdb_line(1, 'CA', 'ASP', 'A', -2),
            pdb_line(2, 'CA', 'HIS', 'A', 0),
            pdb_line(3, 'CA', 'GLU', 'A', 4),
        ]),
        encoding='utf-8',
    )
    assert adapter.read_binder_residues(pdb, 'A', {-2}) == {-2: 'D', 0: 'H', 4: 'E'}


def test_nonconsecutive_ascending_binder_numbering_is_supported(tmp_path):
    pdb = tmp_path / 'complex.pdb'
    pdb.write_text(
        ''.join([
            pdb_line(1, 'CA', 'HIS', 'A', 1),
            pdb_line(2, 'CA', 'ASP', 'A', 5),
            pdb_line(3, 'CA', 'GLU', 'A', 9),
        ]),
        encoding='utf-8',
    )
    mapping = adapter.read_binder_residues(pdb, 'A', {5})
    assert mapping == {1: 'H', 5: 'D', 9: 'E'}
    output = tmp_path / 'out'
    (output / 'candidates').mkdir(parents=True)
    (output / 'candidates' / 'designs.fa').write_text('>d\nHDE\n', encoding='utf-8')
    (output / 'candidates' / 'designs_states.fa').write_text(
        '>d\nHIS-P ASP-P GLU-D\n', encoding='utf-8'
    )
    (output / 'design_scores.json').write_text(json.dumps({'designs': [{
        'design_id': 'd', 'extended_tokens': 'HIS-P ASP-P GLU-D',
        'center_res_ids': [5], 'center_protonation_types': ['ASP-P'],
    }]}), encoding='utf-8')
    (output / 'task_config.json').write_text(
        json.dumps({'checkpoint_path': '/mnt/model.ckpt'}), encoding='utf-8'
    )
    adapter.validate_outputs(output, mapping, [{'position': 5, 'state': 'ASP-P'}], ['ASP-P', 'ASP-D'])


def test_ambiguous_binder_addressing_is_refused_before_design(tmp_path):
    task = {'binder_chain': 'A', 'centres': [{'position': 1, 'state': 'HIS-P'}],
            'states': ['HIS-P', 'HIS-S']}
    checkpoint = tmp_path / 'epoch-0125.ckpt'
    checkpoint.write_bytes(b'checkpoint')
    pdb = tmp_path / 'complex.pdb'
    FakeEngine.instances.clear()
    for lines, message in [
        ([pdb_line(1, 'CA', 'HIS', 'A', 1, icode='A')], 'insertion code'),
        ([pdb_line(1, 'CA', 'HIS', 'A', 1), pdb_line(2, 'CA', 'ASP', 'A', 1)], 'duplicate numbering'),
        ([pdb_line(1, 'CA', 'HIS', 'A', 5), pdb_line(2, 'CA', 'ASP', 'A', 1)], 'ascending authored order'),
        ([pdb_line(1, 'CA', 'HIS', 'A', 1, altloc='A')], 'alternate locations'),
        (
            [pdb_line(1, 'CA', 'ALA', 'T', 1), 'TER\n',
             pdb_line(2, 'CA', 'HIS', 'A', 9), pdb_line(3, 'CA', 'ASP', 'A', 10),
             'TER\n', pdb_line(4, 'CA', 'ASP', 'A', 10)],
            'chain break',
        ),
    ]:
        pdb.write_text(''.join(lines), encoding='utf-8')
        try:
            adapter.run_design(pdb, tmp_path / 'out', task, checkpoint=checkpoint,
                               engine_type=FakeEngine, criteria_type=FakeCriteria,
                               load_structure=lambda path: object())
        except ValueError as exc:
            assert message in str(exc), str(exc)
        else:
            raise AssertionError(f'ambiguous binder addressing accepted: {message}')
    assert FakeEngine.instances == []


def test_invalid_task_mapping_and_empty_results_fail_closed(tmp_path):
    binder_residues = {1: 'H', 2: 'D'}
    valid = {'binder_chain':'A','centres':[{'position':1,'state':'HIS-P'}],
             'states':['HIS-P','HIS-S']}
    assert adapter.validate_request(valid, binder_residues) == valid
    for bad in [
        {**valid, 'states':['HIS-P','ASP-D']},
        {**valid, 'states':['HIS-S','HIS-P']},
        {**valid, 'centres':[{'position':2,'state':'HIS-P'}]},
        {**valid, 'centres':[{'position':1,'state':'HIS-S'}]},
        {**valid, 'block_size':3},
        {**valid, 'unexpected':'shell'},
    ]:
        try:
            adapter.validate_request(bad, binder_residues)
        except ValueError:
            pass
        else:
            raise AssertionError(f'invalid Task parameters accepted: {bad}')
    try:
        adapter.write_outputs(tmp_path, [], valid, tmp_path / 'model.ckpt')
    except ValueError:
        pass
    else:
        raise AssertionError('empty design set accepted')


def test_output_identity_counterexample_is_refused(tmp_path):
    """A 50-residue binder must not accept a 4-residue design with the wrong centre state."""
    output = tmp_path / 'bad'
    (output / 'candidates').mkdir(parents=True)
    (output / 'candidates' / 'designs.fa').write_text('>bad\nHAAA\n', encoding='utf-8')
    (output / 'candidates' / 'designs_states.fa').write_text('>bad\nHIS-S ALA ALA ALA\n', encoding='utf-8')
    (output / 'design_scores.json').write_text(json.dumps({'designs': [{
        'design_id': 'bad', 'extended_tokens': 'HIS-S ALA ALA ALA',
        'center_res_ids': [1], 'center_protonation_types': ['HIS-S'],
    }]}), encoding='utf-8')
    (output / 'task_config.json').write_text(json.dumps({'checkpoint_path': '/mnt/model.ckpt'}), encoding='utf-8')
    binder = {position: 'A' for position in range(1, 51)}
    binder[1] = 'H'
    try:
        adapter.validate_outputs(output, binder, [{'position': 1, 'state': 'HIS-P'}], ['HIS-P', 'HIS-S'])
    except ValueError:
        pass
    else:
        raise AssertionError('wrong-length/wrong-state design accepted')
    binder_small = {1: 'H', 2: 'D', 3: 'E', 4: 'A'}
    try:
        adapter.validate_outputs(output, binder_small, [{'position': 1, 'state': 'HIS-P'}], ['HIS-P', 'HIS-S'])
    except ValueError:
        pass
    else:
        raise AssertionError('wrong centre state accepted')


def test_canonical_sequence_must_match_every_token_parent(tmp_path):
    output = tmp_path / 'bad'
    (output / 'candidates').mkdir(parents=True)
    (output / 'candidates' / 'designs.fa').write_text('>bad\nHDDA\n', encoding='utf-8')
    (output / 'candidates' / 'designs_states.fa').write_text(
        '>bad\nHIS-P ASP-D GLU-D ALA\n', encoding='utf-8'
    )
    (output / 'design_scores.json').write_text(json.dumps({'designs': [{
        'design_id': 'bad', 'extended_tokens': 'HIS-P ASP-D GLU-D ALA',
        'center_res_ids': [1], 'center_protonation_types': ['HIS-P'],
    }]}), encoding='utf-8')
    (output / 'task_config.json').write_text(
        json.dumps({'checkpoint_path': '/mnt/model.ckpt'}), encoding='utf-8'
    )
    try:
        adapter.validate_outputs(
            output, {1: 'H', 2: 'D', 3: 'E', 4: 'A'},
            [{'position': 1, 'state': 'HIS-P'}], ['HIS-P', 'HIS-S'],
        )
    except ValueError as exc:
        assert 'canonical residue' in str(exc)
    else:
        raise AssertionError('token/canonical-parent mismatch accepted')


def test_asset_manifest_remains_blocked_without_hash(tmp_path):
    manifest = tmp_path / 'model-assets.sha256'
    manifest.write_text('# ASSET_BLOCKED\n', encoding='utf-8')
    try:
        adapter.verify_checkpoint(manifest)
    except RuntimeError as exc:
        assert 'ASSET_BLOCKED' in str(exc)
    else:
        raise AssertionError('unverified checkpoint manifest accepted')
