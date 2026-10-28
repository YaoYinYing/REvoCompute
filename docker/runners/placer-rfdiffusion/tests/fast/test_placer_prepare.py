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


def _complex_with_ligands(ligands: list[tuple[str, str, int]]) -> str:
    lines = [_line("ATOM", 1, "CA", "ALA", "A", 1)]
    for serial, (chain, name, number) in enumerate(ligands, start=2):
        lines.append(_line("HETATM", serial, "C1", name, chain, number, x=float(serial)))
    lines.append("END")
    return "\n".join(lines)


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
            "_atom_site.auth_seq_id",
            "_atom_site.pdbx_PDB_ins_code",
            "ATOM 1 N ALA A 1 1 ?",
            # Non-polymer residues are numbered by auth_seq_id upstream.
            "HETATM 2 C1 LIG B . 1 ?",
            "#",
        ]
    )


def _cif_label_auth() -> str:
    return "\n".join(
        [
            "data_test",
            "loop_",
            "_atom_site.group_PDB",
            "_atom_site.id",
            "_atom_site.label_atom_id",
            "_atom_site.label_comp_id",
            "_atom_site.label_asym_id",
            "_atom_site.auth_asym_id",
            "_atom_site.label_seq_id",
            "_atom_site.auth_seq_id",
            "_atom_site.label_alt_id",
            "_atom_site.pdbx_PDB_ins_code",
            # Upstream keys the polymer by label A/1, not author X/42, resolves
            # alternates by occupancy, and never reads insertion codes.
            "ATOM 1 CA ALA A X 1 42 A B",
            "HETATM 2 C1 LIG B Y . 7 . ?",
            "#",
        ]
    )


FIXTURES = Path(__file__).resolve().parent / "4dtz.cif"


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
    argv = prepare.build_argv(params, parsed, "/in/complex.pdb", "/out")
    assert argv == [
        "-f", "/in/complex.pdb", "-o", "/out", "-n", "3",
        "--exclude_common_ligands",
        "--predict_ligand", "LIG",
        "--fixed_ligand_noise", "0.2",
        "--rerank", "prmsd",
        "--bonds", "A-1-ALA-CA:B-1-LIG-C1:1.8",
        "--crop_centers", "B-1-LIG-C1",
    ]


def test_sidechain_mode_fixes_ligand_and_targets_residue(tmp_path):
    params = _params(predict_ligand="", fixed_ligand="LIG", target_res="A-1")
    parsed = prepare.validate_params(params)
    structure = _write(tmp_path, "complex.pdb", _complex())
    prepare.validate_structure(params, parsed, prepare.read_structure(structure), structure)
    argv = prepare.build_argv(params, parsed, structure, "/out")
    assert argv[argv.index("--fixed_ligand") + 1] == "LIG"
    assert argv[argv.index("--target_res") + 1] == "A-1"
    assert "--predict_ligand" not in argv


def test_apo_run_emits_no_use_sm():
    params = _params(predict_ligand="", target_res="A-1", use_sm=False)
    parsed = prepare.validate_params(params)
    argv = prepare.build_argv(params, parsed, "/in/complex.pdb", "/out")
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
        # Upstream's three-part order is chain-resno-name3; the retired
        # chain-name3-resno help made it evaluate int("ALA").
        ({"target_res": "A-42-ALA"}, "Invalid target residue"),
        ({"target_res": "A-ALA-42"}, "Invalid target residue"),
        ({"use_sm": False}, "cannot be combined with predict_ligand or fixed_ligand"),
        ({"predict_ligand": "", "fixed_ligand": "LIG", "use_sm": False},
         "cannot be combined with predict_ligand or fixed_ligand"),
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
    # Crop or corruption centers do not replace the protein center upstream
    # needs: it still builds an empty center list and indexes it.
    for overrides in ({}, {"crop_centers": "A-1-ALA-CA"}, {"corruption_centers": "A-1-ALA-CA"}):
        params = _params(predict_ligand="", **overrides)
        with pytest.raises(prepare.PreparationError, match="target_res is required"):
            prepare.validate_structure(params, prepare.validate_params(params), records, structure)
    target = _params(predict_ligand="", target_res="A-1")
    prepare.validate_structure(target, prepare.validate_params(target), records, structure)


def test_centers_are_rejected_for_a_ligand_free_structure(tmp_path):
    # Even with target_res, upstream builds one center per non-fixed ligand;
    # an empty list reaches get_crop and raises IndexError.
    structure = _write(tmp_path, "apo.pdb", _apo())
    records = prepare.read_structure(structure)
    for overrides in ({"crop_centers": "A-1-ALA-CA"}, {"corruption_centers": "A-1-ALA-CA"}):
        params = _params(predict_ligand="", target_res="A-1", **overrides)
        with pytest.raises(prepare.PreparationError, match="require a ligand"):
            prepare.validate_structure(params, prepare.validate_params(params), records, structure)


def test_corruption_centers_need_one_per_non_fixed_ligand_in_every_mode(tmp_path):
    two = _write(tmp_path, "two.pdb", _complex_with_ligands([("B", "LIG", 1), ("C", "HEM", 2)]))
    records = prepare.read_structure(two)
    # No ligand specification: both ligands are non-fixed.
    params = _params(predict_ligand="", corruption_centers="A-1-ALA-CA")
    with pytest.raises(prepare.PreparationError, match="per non-fixed ligand"):
        prepare.validate_structure(params, prepare.validate_params(params), records, two)

    three = _write(tmp_path, "three.pdb", _complex_with_ligands([("B", "LIG", 1), ("C", "HEM", 2), ("D", "JRP", 3)]))
    records = prepare.read_structure(three)
    # One fixed ligand still leaves two to predict.
    params = _params(predict_ligand="", fixed_ligand="LIG", corruption_centers="A-1-ALA-CA")
    with pytest.raises(prepare.PreparationError, match="per non-fixed ligand"):
        prepare.validate_structure(params, prepare.validate_params(params), records, three)
    # Fixing all but one satisfies the upstream count.
    params = _params(predict_ligand="", fixed_ligand="LIG HEM", corruption_centers="A-1-ALA-CA")
    prepare.validate_structure(params, prepare.validate_params(params), records, three)


def test_predict_multi_requires_more_than_one_ligand(tmp_path):
    structure = _write(tmp_path, "complex.pdb", _complex())
    params = _params(predict_multi=True)
    with pytest.raises(prepare.PreparationError, match="predict_multi requires more than one ligand"):
        prepare.validate_structure(params, prepare.validate_params(params), prepare.read_structure(structure),
                                   structure)


def test_excluded_common_ligands_leave_the_ligand_census(tmp_path):
    structure = _write(tmp_path, "ligands.pdb", _complex_with_ligands([("B", "LIG", 1), ("C", "SO4", 2)]))
    records = prepare.read_structure(structure)
    # Without the flag PLACER parses both ligands, so predict_multi is legal.
    params = _params(predict_ligand="", predict_multi=True)
    prepare.validate_structure(params, prepare.validate_params(params), records, structure)
    # With --exclude_common_ligands only LIG remains.
    params = _params(predict_ligand="", predict_multi=True, exclude_common_ligands=True)
    with pytest.raises(prepare.PreparationError, match="predict_multi requires more than one ligand"):
        prepare.validate_structure(params, prepare.validate_params(params), records, structure)
    params = _params(predict_ligand="SO4", exclude_common_ligands=True)
    with pytest.raises(prepare.PreparationError, match="matches no ligand"):
        prepare.validate_structure(params, prepare.validate_params(params), records, structure)

    # A structure whose only hetero group is a skipped additive has no ligand.
    so4_only = _write(tmp_path, "so4.pdb", _complex_with_ligands([("C", "SO4", 2)]))
    params = _params(predict_ligand="", exclude_common_ligands=True)
    with pytest.raises(prepare.PreparationError, match="target_res is required"):
        prepare.validate_structure(params, prepare.validate_params(params), prepare.read_structure(so4_only),
                                   so4_only)


def test_ligand_chain_cannot_be_reused_by_protein(tmp_path):
    # Upstream parses protein ATOM records and ligand HETATM records separately
    # and asserts that no ligand chain letter already exists in the protein.
    structure = _write(tmp_path, "shared.pdb", "\n".join([
        _line("ATOM", 1, "CA", "ALA", "A", 1),
        _line("HETATM", 2, "C1", "LIG", "A", 5, x=5.0),
        "END",
    ]))
    params = _params(predict_ligand="LIG")
    with pytest.raises(prepare.PreparationError, match="both protein residues and ligands"):
        prepare.validate_structure(params, prepare.validate_params(params), prepare.read_structure(structure),
                                   structure)


def test_legacy_ent_extension_is_not_forwarded(tmp_path):
    # PLACER's -f dispatch parses only .pdb/.cif, so .ent is dead on this Task.
    path = _write(tmp_path, "model.ent", _complex())
    with pytest.raises(prepare.PreparationError, match="Unsupported structure format"):
        prepare.read_structure(path)


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
        json.dumps({"params": _params(), "inputs": {"structures": [{"path": structure}]}}),
        encoding="utf-8",
    )
    assert prepare.main(["--manifest", str(manifest), "--output-dir", str(tmp_path / "out"), "--print-argv"]) == 0
    assert json.loads(capsys.readouterr().out) == [
        "-f", structure, "-o", str(tmp_path / "out"), "-n", "3",
        "--predict_ligand", "LIG", "--rerank", "prmsd",
    ]


def test_rcsb_cif_uses_label_chains_and_ligand_auth_numbers(tmp_path):
    records = prepare.read_structure(str(FIXTURES))
    # 4dtz is RCSB with polymer alternates and a ligand whose label chain (D)
    # differs from its author chain (A).
    assert ("D", 501, "LDP") in prepare._ligands(records)
    params = _params(predict_ligand="D-LDP-501", target_res="A-10")
    prepare.validate_structure(params, prepare.validate_params(params), records, str(FIXTURES))


def test_cif_polymer_uses_label_numbering_not_author_numbering(tmp_path):
    structure = _write(tmp_path, "label_auth.cif", _cif_label_auth())
    records = prepare.read_structure(structure)
    assert [(record.record, record.chain, record.number, record.name) for record in records] == [
        ("ATOM", "A", 1, "ALA"),
        ("HETATM", "B", 7, "LIG"),
    ]
    # Upstream raises KeyError for the author chain; the label chain works.
    author = _params(predict_ligand="B-LIG-7", target_res="X-42")
    with pytest.raises(prepare.PreparationError, match="matches no protein residue"):
        prepare.validate_structure(author, prepare.validate_params(author), records, structure)
    label = _params(predict_ligand="B-LIG-7", target_res="A-1")
    prepare.validate_structure(label, prepare.validate_params(label), records, structure)


def test_cif_alternate_locations_and_insertion_codes_are_not_rejected(tmp_path):
    structure = _write(tmp_path, "label_auth.cif", _cif_label_auth())
    records = prepare.read_structure(structure)
    assert not any(record.altloc or record.insertion for record in records)
    params = _params(predict_ligand="B-LIG-7", target_res="A-1")
    prepare.validate_structure(params, prepare.validate_params(params), records, structure)


def test_single_model_pdb_block_is_accepted(tmp_path):
    path = _write(tmp_path, "model.pdb", "\n".join([
        "MODEL        1",
        _line("ATOM", 1, "CA", "ALA", "A", 1),
        "ENDMDL",
        "END",
    ]))
    assert [residue.name for residue in prepare.read_structure(path)] == ["ALA"]


def test_multi_model_pdb_is_rejected(tmp_path):
    path = _write(tmp_path, "models.pdb", "\n".join([
        "MODEL        1",
        _line("ATOM", 1, "CA", "ALA", "A", 1),
        "ENDMDL",
        "MODEL        2",
        _line("ATOM", 1, "CA", "ALA", "A", 1),
        "ENDMDL",
        "END",
    ]))
    with pytest.raises(prepare.PreparationError, match="Multi-MODEL"):
        prepare.read_structure(path)


def test_non_contiguous_pdb_chain_blocks_are_rejected(tmp_path):
    path = _write(tmp_path, "blocks.pdb", "\n".join([
        _line("ATOM", 1, "CA", "ALA", "A", 1),
        _line("ATOM", 2, "CA", "GLY", "B", 2),
        _line("ATOM", 3, "CA", "SER", "A", 3),
        "END",
    ]))
    with pytest.raises(prepare.PreparationError, match="more than one block"):
        prepare.read_structure(path)


@pytest.mark.parametrize(
    "overrides",
    [
        {"crop_centers": "B-1-LIG-C1"},
        {"corruption_centers": "B-1-LIG-C1"},
        {"predict_multi": True},
    ],
)
def test_a_fixed_ligand_covering_every_ligand_leaves_nothing_to_predict(tmp_path, overrides):
    structure = _write(tmp_path, "complex.pdb", _complex())
    records = prepare.read_structure(structure)
    params = _params(predict_ligand="", fixed_ligand="LIG", **overrides)
    with pytest.raises(prepare.PreparationError, match="No ligand remains to predict"):
        prepare.validate_structure(params, prepare.validate_params(params), records, structure)


def test_fixed_every_ligand_still_runs_in_target_res_mode(tmp_path):
    structure = _write(tmp_path, "complex.pdb", _complex())
    params = _params(predict_ligand="", fixed_ligand="LIG", target_res="A-1")
    prepare.validate_structure(params, prepare.validate_params(params), prepare.read_structure(structure), structure)


def test_the_adapter_does_not_restate_the_num_samples_default():
    # The server resolves the Task default into task.json; inventing 50 here
    # would silently override the authoritative declaration.
    params = _params()
    del params["num_samples"]
    with pytest.raises(prepare.PreparationError, match="num_samples"):
        prepare.validate_params(params)

