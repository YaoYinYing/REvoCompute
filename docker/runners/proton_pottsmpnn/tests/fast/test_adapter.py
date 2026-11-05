from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE = Path(__file__).resolve().parents[2] / 'adapter.py'
spec = importlib.util.spec_from_file_location('proton_adapter', MODULE)
assert spec and spec.loader
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


def test_command_is_argv_only(tmp_path):
    assert adapter.build_command(tmp_path / 'x.pdb', tmp_path / 'config.json', tmp_path) == [
        'python', '/opt/ProtonPottsMPNN/inference/design_ph.py', '--input', str(tmp_path / 'x.pdb'),
        '--config', str(tmp_path / 'config.json'), '--output', str(tmp_path),
    ]


def test_state_grammar_chain_centres_and_locks(tmp_path):
    chains = {'A': {1: 'H', 2: 'D', 3: 'E', 4: 'A'}}
    request = {'binder_chain':'A','designable_residues':[1,4], 'locked_residues':[2], 'mutation_cap':1,
               'centres':[{'position':1,'state':'HIS-P'}], 'states':['HIS-P','HIS-S']}
    assert adapter.validate_request(request, chains) == request
    for bad in [
        {**request, 'states':['HIS-X','HIS-S']},
        {**request, 'states':['HIS-P','HIS-P']},
        {**request, 'centres':[{'position':2,'state':'GLU-D'}]},
        {**request, 'binder_chain':'Z'},
        {**request, 'locked_residues':[1]},
    ]:
        try:
            adapter.validate_request(bad, chains)
        except (ValueError, TypeError):
            pass
        else:
            raise AssertionError(f'invalid design request accepted: {bad}')


def test_vocabulary_and_candidate_output_validation(tmp_path):
    vocab = list('ACDEFGHIKLMNPQRSTVWY') + sorted(adapter.STATES) + ['<a>','<b>','<c>','<d>']
    adapter.validate_vocabulary(vocab)
    bad_vocab = vocab.copy()
    bad_vocab[bad_vocab.index('HIS-P')] = 'HIS-X'
    for wrong in [vocab[:-1], bad_vocab, vocab[:-1] + [vocab[0]]]:
        try:
            adapter.validate_vocabulary(wrong)
        except ValueError:
            pass
        else:
            raise AssertionError('wrong checkpoint vocabulary accepted')
    (tmp_path / 'candidates').mkdir()
    (tmp_path / 'candidates' / 'a.fa').write_text('>design\nHDEA\n', encoding='utf-8')
    (tmp_path / 'design_scores.json').write_text('{"objective":1}', encoding='utf-8')
    adapter.validate_outputs(tmp_path, {1:'H',2:'D',3:'E',4:'A'}, [2], 1)
    (tmp_path / 'candidates' / 'a.fa').write_text('>design\nHAAA\n', encoding='utf-8')
    try:
        adapter.validate_outputs(tmp_path, {1:'H',2:'D',3:'E',4:'A'}, [2], 1)
    except ValueError:
        pass
    else:
        raise AssertionError('locked-residue mutation accepted')


def test_missing_score_and_bad_fasta_are_rejected(tmp_path):
    (tmp_path / 'candidates').mkdir()
    (tmp_path / 'candidates' / 'a.fa').write_text('broken', encoding='utf-8')
    try:
        adapter.validate_outputs(tmp_path, {1:'A'}, [], 1)
    except ValueError:
        pass
    else:
        raise AssertionError('malformed candidate output accepted')
