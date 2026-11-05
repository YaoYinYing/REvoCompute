# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

MODULE = Path(__file__).resolve().parents[2] / 'adapter.py'
FIXTURES = Path(__file__).resolve().parents[5] / 'tests' / 'data' / 'rfd4_proteina'
spec = importlib.util.spec_from_file_location('rfd4_adapter', MODULE)
assert spec and spec.loader
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


def test_hydra_command_uses_pinned_option_names(tmp_path):
    weights = tmp_path / 'weights'
    argv = adapter.build_command(tmp_path / 'in', tmp_path / 'out', 2, 60, 7, weights)
    assert argv == [
        'rfd4-generate', f'inputs={tmp_path / "in"}', f'out_dir={tmp_path / "out"}',
        'num_replicates=2', 'seed=7', 'generation.args.nsteps=60',
        'hardware.accelerator=gpu', 'skip_existing=false', 'metrics_tags=[]',
        'compress_outputs=false',
        f'hf_ckpt_path={weights}', f'hydra.run.dir={tmp_path / "out" / "hydra"}',
    ]
    assert not any(arg.startswith('--') for arg in argv)
    for values in [(0, 1, 0), (1, 501, 0), (1, 1, -1)]:
        try:
            adapter.build_command(tmp_path / 'in', tmp_path / 'out', *values)
        except ValueError:
            pass
        else:
            raise AssertionError('out-of-range parameters accepted')


def test_zero_cif_output_is_refused(tmp_path):
    output = tmp_path / 'out'
    output.mkdir()
    try:
        adapter.validate_outputs(output, 1)
    except ValueError:
        pass
    else:
        raise AssertionError('zero-design output accepted')
    (output / 'condition_metrics.json').write_text('{"satisfied": true}', encoding='utf-8')
    try:
        adapter.validate_outputs(output, 1)
    except ValueError:
        pass
    else:
        raise AssertionError('local metrics JSON substituted for a generated CIF')
    designs = output / 'inference_samples' / 'example'
    designs.mkdir(parents=True)
    (designs / 'design_0.cif').write_text('data_x\n#\n', encoding='utf-8')
    try:
        adapter.validate_outputs(output, 1)
    except ValueError:
        pass
    else:
        raise AssertionError('a non-generated CIF substituted for a generated design')
    generated = designs / 'design_0_generated.cif'
    generated.write_text('data_x\n#\n', encoding='utf-8')
    try:
        adapter.validate_outputs(output, 1)
    except ValueError:
        pass
    else:
        raise AssertionError('header-only generated CIF accepted as a design')
    generated.write_bytes((FIXTURES / 'generated_minimal.cif').read_bytes())
    assert adapter.validate_outputs(output, 1) == [generated]


def test_partial_design_count_is_refused(tmp_path):
    designs = tmp_path / 'out' / 'inference_samples' / 'example'
    designs.mkdir(parents=True)
    (designs / 'design_0_generated.cif').write_bytes((FIXTURES / 'generated_minimal.cif').read_bytes())
    try:
        adapter.validate_outputs(tmp_path / 'out', 2)
    except ValueError as exc:
        assert 'expected 2' in str(exc), str(exc)
    else:
        raise AssertionError('a partial design set was accepted')


def test_generated_cif_requires_two_polymer_backbone_residues():
    adapter.validate_generated_cif(FIXTURES / 'generated_minimal.cif')
    for name, message in [
        ('generated_ligand_only.cif', 'ligand-only'),
        ('generated_one_atom.cif', 'insufficient polymer backbone'),
        ('generated_truncated.cif', 'truncated'),
    ]:
        try:
            adapter.validate_generated_cif(FIXTURES / name)
        except ValueError as exc:
            assert message in str(exc), (name, str(exc))
        else:
            raise AssertionError(f'placeholder generated CIF accepted: {name}')


def test_authentic_upstream_generated_cif_is_accepted():
    adapter.validate_generated_cif(FIXTURES / 'upstream_enzyme_design_generated.cif')


def test_condition_spec_accepts_native_grammar(tmp_path):
    path = tmp_path / 'native.yaml'
    path.write_text(
        'global_args:\n  input_as_annotated_cif: false\n'
        'motif:\n  contig: "A1-2, /0, 10R"\n'
        '  conditions:\n'
        '    C_RAS: {BURIED: [{select: "sel(\'A\')"}]}\n'
        '    C_HB: {DONOR: [{select: "sel(\'A/*/*/N\')"}]}\n'
        '    C_SEQ_PROB_CYS: {0.0: [{select: "sel(\'A/*/[1-2]\')"}]}\n'
        '    C_IDX: {false: [{select: "sel(\'A\')", group: linker}]}\n',
        encoding='utf-8',
    )
    parsed = adapter.parse_condition_spec(path)
    assert parsed['motif']['input_as_annotated_cif'] is False
    assert parsed['motif']['contig'] == 'A1-2, /0, 10R'

    minimal = tmp_path / 'minimal.yaml'
    minimal.write_text('monomer: {}\n', encoding='utf-8')
    assert adapter.parse_condition_spec(minimal) == {'monomer': {}}


def test_condition_spec_refuses_unsupported_directives_and_shell_text(tmp_path):
    valid = tmp_path / 'ok.yaml'
    valid.write_text(
        'motif:\n  contig: "A1-4"\n  conditions:\n'
        '    C_CRD: {true: [{select: "sel(\'A\') and is_protein_backbone"}]}\n'
        '    C_SEQ: {true: [{select: "sel(\'A\')"}]}\n',
        encoding='utf-8',
    )
    assert 'motif' in adapter.parse_condition_spec(valid)
    for body in [
        'design:\n  contig: "A1-4"\n  conditions: {C_CRD: {true: [{select: "$HOME"}]}}\n',
        'design:\n  contig: "A1-4; touch /tmp/x"\n  conditions: {C_CRD: {true: []}}\n',
        'design:\n  contig: "A1-4, /1"\n  conditions: {C_CRD: {true: []}}\n',
        'design:\n  contig: "A1-4"\n  conditions: {C_CRD: {true: []}}\n  shell: "rm -rf /"\n',
        'design:\n  contig: "A1-4"\n  input_as_annotated_cif: /etc/passwd\n  conditions: {C_CRD: {true: []}}\n',
        'global_args: {shell: x}\ndesign: {}\n',
        'design:\n  contig: "A1-4"\n  conditions: {C_FAKE: {true: []}}\n',
        'design:\n  conditions: {null: {true: []}}\n',
    ]:
        path = tmp_path / 'bad.yaml'
        path.write_text(body, encoding='utf-8')
        try:
            adapter.parse_condition_spec(path)
        except ValueError:
            pass
        else:
            raise AssertionError(f'unsafe condition spec accepted: {body}')
    try:
        adapter.validate_contig('not a contig')
    except ValueError:
        pass
    else:
        raise AssertionError('invalid contig accepted')


def test_smoke_condition_fits_scaffold():
    """Every preserved segment must name residues the declared scaffold contains."""
    parsed = adapter.parse_condition_spec(FIXTURES / 'condition.yaml')
    columns, rows = adapter.parse_atom_site((FIXTURES / 'scaffold.cif').read_text(encoding='utf-8'))
    index = {name: position for position, name in enumerate(columns)}
    residues: dict[str, set[int]] = {}
    for row in rows:
        residues.setdefault(row[index['_atom_site.label_asym_id']], set()).add(
            int(row[index['_atom_site.label_seq_id']])
        )
    preserved = [token.strip() for design in parsed.values() for token in design['contig'].split(',')]
    checked = 0
    for token in preserved:
        if token == '/0' or token[0].isdigit() or ':' in token:
            continue
        match = re.fullmatch(r'([A-Za-z][A-Za-z0-9]*?)(\d+)(?:-(\d+))?', token)
        assert match, token
        chain, start = match.group(1), int(match.group(2))
        end = int(match.group(3) or start)
        checked += 1
        assert chain in residues, token
        assert set(range(start, end + 1)) <= residues[chain], token
    assert checked, 'the smoke specification declares no preserved segment'


def test_annotated_cif_is_accepted_without_scaffold(tmp_path):
    cif = tmp_path / 'input.cif'
    cif.write_text('data_x\nloop_\n_atom_site.id\nATOM 1\n', encoding='utf-8')
    assert adapter.prepare_input(cif, None, tmp_path) == (cif, 1)
    try:
        adapter.prepare_input(cif, tmp_path / 'other.cif', tmp_path)
    except ValueError:
        pass
    else:
        raise AssertionError('ambiguous annotated CIF plus scaffold accepted')
    bad = tmp_path / 'empty.cif'
    bad.write_text('data_x\n', encoding='utf-8')
    try:
        adapter.prepare_input(bad, None, tmp_path)
    except ValueError:
        pass
    else:
        raise AssertionError('annotated CIF without atoms accepted')


def test_condition_spec_binds_scaffold_without_shell_interpolation(tmp_path):
    scaffold = tmp_path / 'scaffold.cif'
    scaffold.write_text('data_x\nloop_\n_atom_site.id\nATOM 1\n', encoding='utf-8')
    spec = tmp_path / 'condition.yaml'
    spec.write_text(
        'motif:\n  contig: "A1-4"\n  conditions:\n'
        '    C_CRD: {true: [{select: "sel(\'A\') and is_protein_backbone"}]}\n',
        encoding='utf-8',
    )
    resolved, examples = adapter.prepare_input(spec, scaffold, tmp_path)
    assert resolved == tmp_path / 'resolved_condition.yaml'
    assert examples == 1
    assert str(scaffold) in resolved.read_text(encoding='utf-8')
    try:
        adapter.prepare_input(spec, tmp_path / 'scaffold.pdb', tmp_path)
    except ValueError:
        pass
    else:
        raise AssertionError('non-CIF scaffold accepted')
