from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE = Path(__file__).resolve().parents[2] / 'adapter.py'
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
        'hardware.accelerator=gpu', f'hf_ckpt_path={weights}',
        f'hydra.run.dir={tmp_path / "out" / "hydra"}',
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
        adapter.validate_outputs(output)
    except ValueError:
        pass
    else:
        raise AssertionError('zero-design output accepted')
    (output / 'condition_metrics.json').write_text('{"satisfied": true}', encoding='utf-8')
    try:
        adapter.validate_outputs(output)
    except ValueError:
        pass
    else:
        raise AssertionError('local metrics JSON substituted for a generated CIF')
    designs = output / 'inference_samples' / 'example'
    designs.mkdir(parents=True)
    (designs / 'design_0.cif').write_text('data_x\n#\n', encoding='utf-8')
    try:
        adapter.validate_outputs(output)
    except ValueError:
        pass
    else:
        raise AssertionError('a non-generated CIF substituted for a generated design')
    generated = designs / 'design_0_generated.cif'
    generated.write_text('data_x\n#\n', encoding='utf-8')
    try:
        adapter.validate_outputs(output)
    except ValueError:
        pass
    else:
        raise AssertionError('header-only generated CIF accepted as a design')
    generated.write_text(
        'data_design\n'
        'loop_\n'
        '_atom_site.group_PDB\n'
        '_atom_site.id\n'
        '_atom_site.Cartn_x\n'
        '_atom_site.Cartn_y\n'
        '_atom_site.Cartn_z\n'
        '_atom_site.label_comp_id\n'
        '_atom_site.label_seq_id\n'
        'ATOM 1 0.000 0.000 0.000 ALA 1\n'
        '#\n',
        encoding='utf-8',
    )
    assert adapter.validate_outputs(output) == [generated]


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
        'design:\n  contig: "A1-4"\n  conditions: {C_CRD: {true: []}}\n  shell: "rm -rf /"\n',
        'design:\n  contig: "A1-4"\n  input_as_annotated_cif: /etc/passwd\n  conditions: {C_CRD: {true: []}}\n',
        'global_args: {seed: 1}\n',
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


def test_annotated_cif_is_accepted_without_scaffold(tmp_path):
    cif = tmp_path / 'input.cif'
    cif.write_text('data_x\nloop_\n_atom_site.id\nATOM 1\n', encoding='utf-8')
    assert adapter.prepare_input(cif, None, tmp_path) == cif
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
    resolved = adapter.prepare_input(spec, scaffold, tmp_path)
    assert resolved == tmp_path / 'resolved_condition.yaml'
    assert str(scaffold) in resolved.read_text(encoding='utf-8')
    try:
        adapter.prepare_input(spec, tmp_path / 'scaffold.pdb', tmp_path)
    except ValueError:
        pass
    else:
        raise AssertionError('non-CIF scaffold accepted')
