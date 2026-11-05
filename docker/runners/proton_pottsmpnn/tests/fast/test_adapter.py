from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from packaging.requirements import Requirement

MODULE = Path(__file__).resolve().parents[2] / 'adapter.py'
ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))

from revocompute import task_types  # noqa: E402

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


def test_pinned_v6_vocabulary_and_state_pair():
    vocab = set('ACDEFGHIKLMNPQRSTVWY') | {'UNK'} | {
        'HIS-P','HIS-S','HIS-A','ASP-P','ASP-D','ASP-A','GLU-P','GLU-D','GLU-A'
    }
    assert len(vocab) == 30
    adapter.validate_vocabulary(vocab)
    adapter.validate_vocabulary({token: None for token in vocab})
    bad = vocab - {'HIS-P'} | {'HIS-X'}
    try:
        adapter.validate_vocabulary(bad)
    except ValueError:
        pass
    else:
        raise AssertionError('wrong checkpoint vocabulary accepted')
    assert adapter.STATE_PAIRS == {'HIS-P': 'HIS-S', 'ASP-P': 'ASP-D', 'GLU-P': 'GLU-D'}


def test_api_binding_uses_task_input_parameters_checkpoint_and_output(tmp_path):
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
        'block_size': 3, 'temperature': 0.05, 'neighbour_k': 7,
        'max_mutations': 12, 'samples_per_site': 2, 'seed': 17,
    }
    atom_array = object()
    FakeEngine.instances.clear()
    adapter.run_design(pdb, output, task, checkpoint=checkpoint,
                       engine_type=FakeEngine, criteria_type=FakeCriteria,
                       load_structure=lambda path: atom_array)

    engine = FakeEngine.instances[-1]
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


def test_invalid_task_mapping_and_empty_results_fail_closed(tmp_path):
    chains = {'A': {1: 'H', 2: 'D'}}
    valid = {'binder_chain':'A','centres':[{'position':1,'state':'HIS-P'}],
             'states':['HIS-P','HIS-S']}
    assert adapter.validate_request(valid, chains) == valid
    for bad in [
        {**valid, 'states':['HIS-P','ASP-D']},
        {**valid, 'centres':[{'position':2,'state':'HIS-P'}]},
        {**valid, 'centres':[{'position':1,'state':'HIS-S'}]},
        {**valid, 'unexpected':'shell'},
    ]:
        try:
            adapter.validate_request(bad, chains)
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


def test_runtime_build_inputs_declare_pinned_inference_extras():
    task_types.discover_plugins(str(ROOT / 'docker' / 'runners'), enabled={'proton_pottsmpnn'})
    family, _runner = task_types.get_family('proton_pottsmpnn')
    relative = 'proton_pottsmpnn/requirements-extra.txt'
    assert relative in family.build_inputs
    requirements = {}
    for line in (ROOT / 'docker' / 'runners' / relative).read_text(encoding='utf-8').splitlines():
        entry = line.split('#', 1)[0].strip()
        if entry:
            requirement = Requirement(entry)
            requirements[requirement.name] = requirement
    assert {'ipdb', 'propka', 'pandas'} <= set(requirements)
    assert requirements['propka'].specifier.contains('3.5')
    assert requirements['pandas'].specifier.contains('2.2', prereleases=True)
    assert not requirements['pandas'].specifier.contains('3.0', prereleases=True)


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


def test_asset_manifest_remains_blocked_without_hash(tmp_path):
    manifest = tmp_path / 'model-assets.sha256'
    manifest.write_text('# ASSET_BLOCKED\n', encoding='utf-8')
    try:
        adapter.verify_checkpoint(manifest)
    except RuntimeError as exc:
        assert 'ASSET_BLOCKED' in str(exc)
    else:
        raise AssertionError('unverified checkpoint manifest accepted')
