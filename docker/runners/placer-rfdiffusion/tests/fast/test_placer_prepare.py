# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[2] / "placer_prepare.py"
_SPEC = importlib.util.spec_from_file_location("placer_prepare", MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
prepare = importlib.util.module_from_spec(_SPEC)
sys.modules["placer_prepare"] = prepare
_SPEC.loader.exec_module(prepare)


def _line(record: str, serial: int, atom: str, name: str, chain: str, number: int, insertion: str = "",
          altloc: str = "", x: float = 0.0) -> str:
    return (
        f"{record:<6}{serial:>5} {atom:<4}{altloc:1}{name:>3} {chain}{number:>4}{insertion}"
        f"   {x:8.3f}{0.0:8.3f}{0.0:8.3f}{1.0:6.2f}{20.0:6.2f}          {atom[0]:>2}"
    )


def _complex(insertion: str = "", altloc: str = "") -> str:
    return "\n".join(
        [
            _line("ATOM", 1, "N", "ALA", "A", 1, insertion, altloc),
            _line("ATOM", 2, "CA", "ALA", "A", 1, insertion, altloc, 1.0),
            _line("HETATM", 3, "C1", "LIG", "B", 1, insertion, altloc, 5.0),
            _line("HETATM", 4, "C2", "LIG", "B", 1, insertion, altloc, 6.0),
            "END",
        ]
    )


def _apo() -> str:
    return "\n".join(
        [
            _line("ATOM", 1, "N", "ALA", "A", 1),
            _line("ATOM", 2, "CA", "ALA", "A", 1, x=1.0),
            "END",
        ]
    )


def _cif_complex() -> str:
    return "\n".join(
        [
            "data_test",
            "loop_",
            "_atom_site.group_PDB",
            "_atom_site.id",
            "_atom_site.label_atom_id",
            "_atom_site.label_comp_id",
            "_atom_site.label_asym_id",
            "_atom_site.label_seq_id",
            "_atom_site.pdbx_PDB_ins_code",
            "ATOM 1 N ALA A 1 ?",
            "HETATM 2 C1 LIG B 1 ?",
            "#",
        ]
    )


def _write(tmp_path: Path, name: str, content: str) -> str:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return str(path)


def _params(**overrides):
    values = {
        "num_samples": 3,
        "predict_ligand": "LIG",
        "fixed_ligand": "",
        "target_res": "",
        "fixed_ligand_noise": None,
        "rerank": "prmsd",
        "use_sm": True,
        "exclude_common_ligands": False,
        "predict_multi": False,
        "bonds": "",
        "mutate": "",
        "crop_centers": "",
        "corruption_centers": "",
    }
    values.update(overrides)
    return values


def test_build_argv_roundtrips_every_supported_option():
    params = _params(
        bonds="A-1-ALA-CA:B-1-LIG-C1:1.8",
        crop_centers="B-1-LIG-C1",
        fixed_ligand_noise=0.2,
        exclude_common_ligands=True,
    )
    parsed = prepare.validate_params(params)
    argv = prepare.build_argv(params, parsed, "/in/complex.pdb", "/in/residues.json", "/out")
    assert argv == [
        "-f", "/in/complex.pdb", "-o", "/out", "-n", "3",
        "--exclude_common_ligands",
        "--predict_ligand", "LIG",
        "--fixed_ligand_noise", "0.2",
        "--rerank", "prmsd",
        "--bonds", "A-1-ALA-CA:B-1-LIG-C1:1.8",
        "--crop_centers", "B-1-LIG-C1",
        "--residue_json", "/in/residues.json",
    ]


def test_sidechain_mode_fixes_ligand_and_targets_residue(tmp_path):
    params = _params(predict_ligand="", fixed_ligand="LIG", target_res="A-1")
    parsed = prepare.validate_params(params)
    structure = _write(tmp_path, "complex.pdb", _complex())
    prepare.validate_structure(params, parsed, prepare.read_structure(structure), structure)
    argv = prepare.build_argv(params, parsed, structure, None, "/out")
    assert argv[argv.index("--fixed_ligand") + 1] == "LIG"
    assert argv[argv.index("--target_res") + 1] == "A-1"
    assert "--predict_ligand" not in argv


def test_apo_run_emits_no_use_sm():
    params = _params(predict_ligand="", target_res="A-1", use_sm=False)
    parsed = prepare.validate_params(params)
    argv = prepare.build_argv(params, parsed, "/in/complex.pdb", None, "/out")
    assert "--no-use_sm" in argv
    assert "--use_sm" not in argv


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"predict_ligand": "LIG", "fixed_ligand": "HEM"}, "cannot both be set"),
        ({"predict_ligand": "", "crop_centers": "B-1-LIG-C1", "corruption_centers": "B-1-LIG-C1"},
         "cannot both be set"),
        ({"predict_ligand": "LIG-1-extra"}, "Invalid ligand identifier"),
        ({"target_res": "A-B-C"}, "Invalid target residue"),
        ({"crop_centers": "B-1-LIG"}, "Invalid center"),
        ({"bonds": "A-1-ALA-CA:B-1-LIG-C1"}, "Invalid bond"),
        ({"mutate": "ALA:1A"}, "Invalid mutation"),
        ({"rerank": "rmsd"}, "Invalid rerank"),
    ],
)
def test_malformed_or_conflicting_parameters_are_rejected(overrides, message):
    with pytest.raises(prepare.PreparationError, match=message):
        prepare.validate_params(_params(**overrides))


def test_insertion_codes_and_alternate_locations_are_rejected(tmp_path):
    insertion = _write(tmp_path, "insertion.pdb", _complex(insertion="A"))
    parsed = prepare.validate_params(_params())
    with pytest.raises(prepare.PreparationError, match="insertion codes"):
        prepare.validate_structure(_params(), parsed, prepare.read_structure(insertion), insertion)

    alternate = _write(tmp_path, "altloc.pdb", _complex(altloc="A"))
    with pytest.raises(prepare.PreparationError, match="alternate locations"):
        prepare.validate_structure(_params(), parsed, prepare.read_structure(alternate), alternate)


def test_ligand_and_center_identifiers_must_exist(tmp_path):
    structure = _write(tmp_path, "complex.pdb", _complex())
    records = prepare.read_structure(structure)
    with pytest.raises(prepare.PreparationError, match="matches no ligand"):
        prepare.validate_structure(_params(predict_ligand="XYZ"), prepare.validate_params(
            _params(predict_ligand="XYZ")), records, structure)
    with pytest.raises(prepare.PreparationError, match="absent from the input"):
        prepare.validate_structure(_params(predict_ligand="", crop_centers="B-1-LIG-C9"),
                                   prepare.validate_params(_params(predict_ligand="", crop_centers="B-1-LIG-C9")),
                                   records, structure)


def test_target_res_is_required_for_a_ligand_free_structure(tmp_path):
    structure = _write(tmp_path, "apo.pdb", _apo())
    records = prepare.read_structure(structure)
    params = _params(predict_ligand="")
    with pytest.raises(prepare.PreparationError, match="target_res is required"):
        prepare.validate_structure(params, prepare.validate_params(params), records, structure)
    target = _params(predict_ligand="", target_res="A-1")
    prepare.validate_structure(target, prepare.validate_params(target), records, structure)


def test_corruption_centers_need_one_per_predicted_ligand(tmp_path):
    structure = _write(tmp_path, "complex.pdb", "\n".join([
        _line("ATOM", 1, "CA", "ALA", "A", 1),
        _line("HETATM", 2, "C1", "LIG", "B", 1, x=5.0),
        _line("HETATM", 3, "C1", "HEM", "C", 2, x=8.0),
        "END",
    ]))
    params = _params(predict_ligand="LIG HEM", corruption_centers="A-1-ALA-CA")
    with pytest.raises(prepare.PreparationError, match="at least one center per predicted ligand"):
        prepare.validate_structure(params, prepare.validate_params(params), prepare.read_structure(structure),
                                   structure)


def test_predict_multi_requires_more_than_one_ligand(tmp_path):
    structure = _write(tmp_path, "complex.pdb", _complex())
    params = _params(predict_multi=True)
    with pytest.raises(prepare.PreparationError, match="predict_multi requires more than one ligand"):
        prepare.validate_structure(params, prepare.validate_params(params), prepare.read_structure(structure),
                                   structure)


def test_mutation_is_pdb_only(tmp_path):
    structure = _write(tmp_path, "complex.cif", _cif_complex())
    params = _params(predict_ligand="LIG", mutate="1A:TRP")
    with pytest.raises(prepare.PreparationError, match="PDB-only"):
        prepare.validate_structure(params, prepare.validate_params(params), prepare.read_structure(structure),
                                   structure)


def test_mmcif_records_are_read_and_mmcif_path_is_normalized(tmp_path):
    structure = _write(tmp_path, "complex.mmcif", _cif_complex())
    records = prepare.read_structure(structure)
    assert [(record.record, record.chain, record.number, record.name) for record in records] == [
        ("ATOM", "A", 1, "ALA"),
        ("HETATM", "B", 1, "LIG"),
    ]
    params = _params(predict_ligand="LIG")
    prepare.validate_structure(params, prepare.validate_params(params), records, structure)
    normalized, temporary = prepare.normalize_structure_path(structure)
    assert temporary is not None
    assert Path(normalized).name == "complex.cif"
    assert Path(normalized).resolve() == Path(structure).resolve()
    Path(normalized).unlink()
    Path(temporary).rmdir()

    uppercase = _write(tmp_path, "UPPER.PDB", _complex())
    renamed, temporary = prepare.normalize_structure_path(uppercase)
    assert temporary is not None
    assert Path(renamed).name == "UPPER.pdb"
    Path(renamed).unlink()
    Path(temporary).rmdir()


def test_manifest_print_argv_uses_the_named_input_roles(tmp_path, capsys):
    structure = _write(tmp_path, "complex.pdb", _complex())
    manifest = tmp_path / "task.json"
    manifest.write_text(
        json.dumps({"params": _params(), "inputs": {"structures": [{"path": structure}], "custom_residues": []}}),
        encoding="utf-8",
    )
    assert prepare.main(["--manifest", str(manifest), "--output-dir", str(tmp_path / "out"), "--print-argv"]) == 0
    assert json.loads(capsys.readouterr().out) == [
        "-f", structure, "-o", str(tmp_path / "out"), "-n", "3",
        "--predict_ligand", "LIG", "--rerank", "prmsd",
    ]


def test_custom_residue_definitions_follow_the_upstream_shape(tmp_path):
    valid = _write(tmp_path, "residues.json", json.dumps({
        "75I": {"sdf": "mol", "atom_id": ["N", "CA"], "leaving": [True, False], "pdbx_align": [0, 0]},
    }))
    prepare.validate_custom_residues(valid)
    invalid = _write(tmp_path, "invalid.json", json.dumps({"75I": {"sdf": "mol", "atom_id": ["N"]}}))
    with pytest.raises(prepare.PreparationError, match="leaving flag"):
        prepare.validate_custom_residues(invalid)
