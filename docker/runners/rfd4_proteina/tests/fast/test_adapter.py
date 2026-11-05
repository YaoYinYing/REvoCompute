from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE = Path(__file__).resolve().parents[2] / 'adapter.py'
spec = importlib.util.spec_from_file_location('rfd4_adapter', MODULE)
assert spec and spec.loader
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


def test_command_uses_argv_and_bounds_only(tmp_path):
    argv = adapter.build_command(tmp_path / 'condition.json', tmp_path, 2, 200, 7)
    assert argv == ['rfd4-generate', '--config', str(tmp_path / 'condition.json'), '--output-dir', str(tmp_path),
                    '--num-designs', '2', '--steps', '200', '--seed', '7']
    for values in [(0, 1, 0), (1, 501, 0), (1, 1, -1)]:
        try:
            adapter.build_command(tmp_path / 'c.json', tmp_path, *values)
        except ValueError:
            pass
        else:
            raise AssertionError('out-of-range parameters accepted')


def test_condition_refusal():
    for condition in [
        {'unknown_directive': 'anything'}, {'contig': 'A:1-4; touch /tmp/x'},
        {'contig': '$HOME'}, {'motif': 'ACD*'}, {'residues': [0]}, {'chain': 'AA'},
    ]:
        try:
            adapter.validate_condition(condition)
        except ValueError:
            pass
        else:
            raise AssertionError(f'unsafe condition accepted: {condition}')


def test_output_validation(tmp_path):
    path = tmp_path / 'condition_metrics.json'
    for content in ('', '[]', '{}', '{broken'):
        path.write_text(content, encoding='utf-8')
        try:
            adapter.validate_outputs(path)
        except ValueError:
            pass
        else:
            raise AssertionError('malformed output accepted')
    path.write_text('{"satisfied": true}', encoding='utf-8')
    assert adapter.validate_outputs(path)['satisfied'] is True
