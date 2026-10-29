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

_CCD_STUB = {
    "ALA": frozenset({"N", "CA", "C", "O", "CB", "OXT"}),
    "GLY": frozenset({"N", "CA", "C", "O"}),
    "THR": frozenset({"N", "CA", "C", "O", "CB", "OG1", "CG2"}),
    "TRP": frozenset({"N", "CA"}),
    "UNK": frozenset({"N", "CA", "C", "O"}),
    "LIG": frozenset({"C1", "C2"}),
    # The 4dtz ligands' real atom names, so the RCSB fixture exercises the
    # atom-set check with a template rather than only a name.
    "HEM": frozenset(
        "C1A C1B C1C C1D C2A C2B C2C C2D C3A C3B C3C C3D C4A C4B C4C C4D CAA CAB CAC CAD "
        "CBA CBB CBC CBD CGA CGD CHA CHB CHC CHD CMA CMB CMC CMD FE NA NB NC ND O1A O1D O2A O2D".split()
    ),
    "LDP": frozenset("C1 C2 C3 C4 C5 C6 C7 C8 N1 O1 O2".split()),
    "SO4": frozenset({"S", "O1"}),
    # A distinct, real CCD name whose atom set differs from 4dtz LDP.
    "ZZQ": frozenset({"CAB", "CAC", "CAD"}),
}


@pytest.fixture(autouse=True)
def _ccd_stub(monkeypatch):
    monkeypatch.setattr(prepare, "_ccd_library", lambda: _CCD_STUB)


def _line(record: str, serial: int, atom: str, name: str, chain: str, number: int, insertion: str = "",
          altloc: str = "", x: float = 0.0) -> str:
    return (
        f"{record:<6}{serial:>5} {atom:<4}{altloc:1}{name:>3} {chain:1}{number:>4}{insertion}"
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
        atom = sorted(_CCD_STUB[name])[0] if name in _CCD_STUB else "C1"
        lines.append(_line("HETATM", serial, atom, name, chain, number, x=float(serial)))
    lines.append("END")
    return "\n".join(lines)


def _cif_complex() -> str:
    return "\n".join(
        [
            "data_test",
            "loop_",
            "_atom_site.group_PDB",
            "_atom_site.id",
            "_atom_site.type_symbol",
            "_atom_site.label_atom_id",
            "_atom_site.label_comp_id",
            "_atom_site.label_asym_id",
            "_atom_site.label_seq_id",
            "_atom_site.auth_seq_id",
            "_atom_site.pdbx_PDB_ins_code",
            "ATOM 1 N N ALA A 1 1 ?",
            # Non-polymer residues are numbered by auth_seq_id upstream.
            "HETATM 2 C C1 LIG B . 1 ?",
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
            "_atom_site.type_symbol",
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
            "ATOM 1 C CA ALA A X 1 42 A B",
            "HETATM 2 C C1 LIG B Y . 7 . ?",
            "#",
        ]
    )


def _cif_namespaces(
    *, polymer_label: str = "ALA", polymer_auth: str = "ALA",
    ligand_label: str = "LIG", ligand_auth: str = "LIG",
) -> str:
    return "\n".join(
        [
            "data_test",
            "loop_",
            "_atom_site.group_PDB",
            "_atom_site.id",
            "_atom_site.type_symbol",
            "_atom_site.label_atom_id",
            "_atom_site.label_comp_id",
            "_atom_site.auth_comp_id",
            "_atom_site.label_asym_id",
            "_atom_site.label_seq_id",
            "_atom_site.auth_seq_id",
            f"ATOM 1 C CA {polymer_label} {polymer_auth} A 1 1",
            f"HETATM 2 C C1 {ligand_label} {ligand_auth} B . 1",
            "#",
        ]
    )


FIXTURES = Path(__file__).resolve().parent / "4dtz.cif"


def _ccd_from(records: list[prepare.Residue]) -> dict[str, frozenset[str]]:
    """Templates matching the fixture, so its mapping test is not an atom audit."""
    templates: dict[str, set[str]] = {}
    for record in records:
        templates.setdefault(record.name, set()).add(record.atom)
    return {name: frozenset(atoms) for name, atoms in templates.items()}


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


def _flag_values(argv: list[str]) -> dict[str, list[str]]:
    """Map each flag to its values, so a test names semantics, not argv order."""
    flags: dict[str, list[str]] = {}
    index = 0
    while index < len(argv):
        token = argv[index]
        if not token.startswith("-"):
            index += 1
            continue
        values: list[str] = []
        index += 1
        while index < len(argv) and not argv[index].startswith("-"):
            values.append(argv[index])
            index += 1
        flags[token] = values
    return flags


def test_build_argv_roundtrips_every_supported_option():
    params = _params(
        bonds="A-1-ALA-CA:B-1-LIG-C1:1.8",
        crop_centers="B-1-LIG-C1",
        fixed_ligand_noise=0.2,
        exclude_common_ligands=True,
    )
    parsed = prepare.validate_params(params)
    argv = prepare.build_argv(params, parsed, "/in/complex.pdb", "/out")
    flags = _flag_values(argv)
    assert flags["-f"] == ["/in/complex.pdb"]
    assert flags["-o"] == ["/out"]
    assert flags["-n"] == ["3"]
    assert flags["--exclude_common_ligands"] == []
    assert flags["--predict_ligand"] == ["LIG"]
    assert flags["--fixed_ligand_noise"] == ["0.2"]
    assert flags["--rerank"] == ["prmsd"]
    assert flags["--bonds"] == ["A-1-ALA-CA:B-1-LIG-C1:1.8"]
    assert flags["--crop_centers"] == ["B-1-LIG-C1"]
    assert not (
        {"--use_sm", "--predict_multi", "--fixed_ligand", "--target_res", "--mutate", "--corruption_centers"}
        & flags.keys()
    )
    assert not (
        {"--cautious", "--ignore_ligand_hydrogens", "--ligand_file", "--residue_json", "--idir", "--suffix"}
        & flags.keys()
    )


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


def test_blank_pdb_chains_for_protein_and_ion_do_not_conflict(tmp_path):
    # Upstream keeps a blank polymer chain as " " but strips the HETATM chain
    # to "", so these are different keys and the shared-chain guard must not
    # reject a blank-chain ion.
    structure = _write(tmp_path, "blank_both.pdb", "\n".join([
        _line("ATOM", 1, "CA", "ALA", "", 1),
        _line("HETATM", 2, "C1", "LIG", "", 1, x=5.0),
        "END",
    ]))
    records = prepare.read_structure(structure)
    assert {record.chain for record in records} == {" ", ""}
    params = _params(predict_ligand="LIG")
    prepare.validate_structure(params, prepare.validate_params(params), records, structure)


def test_named_pdb_ligand_chain_is_matched(tmp_path):
    structure = _write(tmp_path, "complex.pdb", _complex())
    records = prepare.read_structure(structure)
    assert ("B", 1, "LIG") in prepare._ligands(records)
    params = _params(predict_ligand="B-LIG-1")
    prepare.validate_structure(params, prepare.validate_params(params), records, structure)


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
    flags = _flag_values(json.loads(capsys.readouterr().out))
    assert flags["-f"] == [structure]
    assert flags["-o"] == [str(tmp_path / "out")]
    assert flags["-n"] == ["3"]
    assert flags["--predict_ligand"] == ["LIG"]
    assert flags["--rerank"] == ["prmsd"]
    assert not ({"--fixed_ligand", "--target_res", "--use_sm", "--no-use_sm", "--bonds", "--mutate"} & flags.keys())


def test_rcsb_cif_uses_label_chains_and_ligand_auth_numbers(tmp_path, monkeypatch):
    records = prepare.read_structure(str(FIXTURES))
    # 4dtz is RCSB with polymer alternates and a ligand whose label chain (D)
    # differs from its author chain (A). The library is derived from the fixture
    # here; the real-CCD probe for this file runs against the pinned SIF.
    monkeypatch.setattr(prepare, "_ccd_library", lambda: _ccd_from(records))
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


def test_cif_polymer_component_name_comes_from_label_comp_id(tmp_path):
    # cifutils populates polymer residues from entity_poly_seq/label_comp_id;
    # auth_comp_id is only the non-polymer identity.
    wrong = _write(tmp_path, "label_xqz.cif", _cif_namespaces(polymer_label="XQZ", polymer_auth="ALA"))
    with pytest.raises(prepare.PreparationError, match=r"Protein residue name\(s\) 'XQZ'"):
        prepare.validate_structure(
            _params(), prepare.validate_params(_params()), prepare.read_structure(wrong), wrong
        )
    right = _write(tmp_path, "label_ala.cif", _cif_namespaces(polymer_label="ALA", polymer_auth="XQZ"))
    params = _params(predict_ligand="LIG")
    prepare.validate_structure(params, prepare.validate_params(params), prepare.read_structure(right), right)


def test_cif_non_polymer_component_names_must_agree(tmp_path):
    # Upstream keys the ligand by auth_comp_id; a differing label_comp_id would
    # select an atom set under one name and publish the residue under another.
    structure = _write(
        tmp_path, "ligand_namespace.cif", _cif_namespaces(ligand_label="LIG", ligand_auth="ZZQ")
    )
    with pytest.raises(prepare.PreparationError, match="Non-polymer residue B-1"):
        prepare.read_structure(structure)


def test_cif_alternate_locations_and_insertion_codes_are_not_rejected(tmp_path):
    content = _cif_label_auth()
    # The fixture carries altloc "A" and insertion code "B" on the polymer row.
    assert "ATOM 1 C CA ALA A X 1 42 A B" in content
    structure = _write(tmp_path, "label_auth.cif", content)
    params = _params(predict_ligand="B-LIG-7", target_res="A-1")
    prepare.validate_structure(params, prepare.validate_params(params), prepare.read_structure(structure), structure)


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


def _cif_atom_site(rows: list[str], *, model: bool = False) -> str:
    columns = [
        "_atom_site.group_PDB",
        "_atom_site.id",
        "_atom_site.type_symbol",
        "_atom_site.label_atom_id",
        "_atom_site.label_comp_id",
        "_atom_site.label_asym_id",
        "_atom_site.label_seq_id",
        "_atom_site.auth_seq_id",
    ]
    if model:
        columns.append("_atom_site.pdbx_PDB_model_num")
    return "\n".join(["data_test", "loop_", *columns, *rows, "#"])


def _cif_with_typed_ligand(atoms: list[tuple[str, str]]) -> str:
    rows = ["ATOM 1 C CA ALA A 1 1"]
    rows.extend(f"HETATM {serial} {element} {atom} LIG B . 1" for serial, (atom, element) in enumerate(atoms, start=2))
    return _cif_atom_site(rows)


def _cif_with_models(count: int) -> str:
    rows = [
        f"{group} {serial} {element} {atom} {name} {chain} {label_seq} {auth_seq} {model}"
        for model in range(1, count + 1)
        for group, serial, element, atom, name, chain, label_seq, auth_seq in (
            ("ATOM", 1, "C", "CA", "ALA", "A", 1, 1),
            ("HETATM", 2, "C", "C1", "LIG", "B", ".", 1),
        )
    ]
    return _cif_atom_site(rows, model=True)


def _cif_with_ligand(name: str) -> str:
    return _cif_atom_site([
        "ATOM 1 C CA ALA A 1 1",
        f"HETATM 2 C C1 {name} C . 2",
    ])


def _cif_with_collision() -> str:
    return _cif_atom_site([
        "ATOM 1 C CA ALA A 1 1",
        "ATOM 2 C CA GLY A 1 1",
        "HETATM 3 C C1 LIG B . 1",
    ])


def test_single_model_cif_is_accepted(tmp_path):
    structure = _write(tmp_path, "one.cif", _cif_with_models(1))
    records = prepare.read_structure(structure)
    assert len(records) == 2
    prepare.validate_structure(_params(), prepare.validate_params(_params()), records, structure)


def test_multi_model_cif_is_rejected(tmp_path):
    structure = _write(tmp_path, "two.cif", _cif_with_models(2))
    with pytest.raises(prepare.PreparationError, match="Multi-model mmCIF"):
        prepare.read_structure(structure)


def test_cif_ligand_must_be_in_the_residue_library(tmp_path):
    structure = _write(tmp_path, "unl.cif", _cif_with_ligand("UNL"))
    params = _params()
    with pytest.raises(prepare.PreparationError, match="not in PLACER's shipped residue library"):
        prepare.validate_structure(params, prepare.validate_params(params), prepare.read_structure(structure),
                                   structure)
    named = _params(predict_ligand="UNL")
    with pytest.raises(prepare.PreparationError, match="not in PLACER's shipped residue library"):
        prepare.validate_structure(named, prepare.validate_params(named), prepare.read_structure(structure),
                                   structure)


def test_mutation_target_must_be_in_the_residue_library(tmp_path):
    structure = _write(tmp_path, "complex.pdb", _complex())
    records = prepare.read_structure(structure)
    bad = _params(mutate="1A:75I")
    with pytest.raises(prepare.PreparationError, match="not in PLACER's shipped residue library"):
        prepare.validate_structure(bad, prepare.validate_params(bad), records, structure)
    good = _params(mutate="1A:TRP")
    prepare.validate_structure(good, prepare.validate_params(good), records, structure)


def test_pdb_element_falls_back_to_the_atom_name_when_the_column_is_blank(tmp_path):
    # An old PDB may stop before the element columns; the first letter of the
    # atom name still identifies the unmatched hydrogen as H, not a heavy atom.
    hydrogen = _line("ATOM", 2, "H9", "ALA", "A", 1, x=2.0)[:76]
    structure = _write(tmp_path, "old.pdb", "\n".join([
        _line("ATOM", 1, "CA", "ALA", "A", 1),
        hydrogen,
        _line("HETATM", 3, "C1", "LIG", "B", 1, x=5.0),
        "END",
    ]))
    params = _params(predict_ligand="LIG")
    prepare.validate_structure(params, prepare.validate_params(params), prepare.read_structure(structure), structure)


@pytest.mark.parametrize(
    "overrides",
    [
        {"crop_centers": "A-1-ALA-H99"},
        {"bonds": "A-1-ALA-H99:B-1-LIG-C1:1.8"},
    ],
)
def test_selectors_cannot_name_a_hydrogen_the_residue_check_ignored(tmp_path, overrides):
    # An unmatched H/D atom is skipped by cifutils/pdbparser, so it exists in
    # the input but not in the parsed residue; upstream would KeyError or loop.
    structure = _write(tmp_path, "hydrogen.pdb", "\n".join([
        _line("ATOM", 1, "CA", "ALA", "A", 1),
        _line("ATOM", 2, "H99", "ALA", "A", 1, x=2.0),
        _line("HETATM", 3, "C1", "LIG", "B", 1, x=5.0),
        "END",
    ]))
    params = _params(**overrides)
    with pytest.raises(prepare.PreparationError, match="is not an atom PLACER parses"):
        prepare.validate_structure(params, prepare.validate_params(params), prepare.read_structure(structure),
                                   structure)


@pytest.mark.parametrize("atom", ["OT1", "OT2"])
def test_pdb_polymer_heavy_atoms_must_match_the_residue_library(tmp_path, atom):
    # pdbparser fills each ATOM residue from its CCD template, so an Amber
    # terminal oxygen outside that template is silently dropped upstream.
    structure = _write(tmp_path, "amber.pdb", "\n".join([
        _line("ATOM", 1, "CA", "ALA", "A", 1),
        _line("ATOM", 2, atom, "ALA", "A", 1, x=2.0),
        _line("HETATM", 3, "C1", "LIG", "B", 1, x=5.0),
        "END",
    ]))
    params = _params(predict_ligand="LIG")
    with pytest.raises(prepare.PreparationError, match=f"Residue A-1-ALA has heavy atoms .*'{atom}'"):
        prepare.validate_structure(params, prepare.validate_params(params), prepare.read_structure(structure),
                                   structure)


def test_blank_pdb_polymer_chain_is_keyed_as_space_and_cannot_be_selected(tmp_path):
    structure = _write(tmp_path, "blank.pdb", "\n".join([
        _line("ATOM", 1, "CA", "ALA", "", 1),
        _line("HETATM", 2, "C1", "LIG", "B", 1, x=5.0),
        "END",
    ]))
    assert {record.chain for record in prepare.read_structure(structure)} == {" ", "B"}
    with pytest.raises(prepare.PreparationError, match="Invalid center"):
        prepare.validate_params(_params(crop_centers="-1-ALA-CA"))


def test_pdb_keeps_same_chain_number_residues_with_different_names(tmp_path):
    structure = _write(tmp_path, "collision.pdb", "\n".join([
        _line("ATOM", 1, "CA", "ALA", "A", 1),
        _line("ATOM", 2, "CA", "GLY", "A", 1, x=1.0),
        _line("HETATM", 3, "C1", "LIG", "B", 1, x=5.0),
        "END",
    ]))
    params = _params()
    prepare.validate_structure(params, prepare.validate_params(params), prepare.read_structure(structure), structure)


def test_cif_merges_same_chain_number_residues_with_different_names(tmp_path):
    structure = _write(tmp_path, "collision.cif", _cif_with_collision())
    params = _params()
    with pytest.raises(prepare.PreparationError, match="share a chain and residue number"):
        prepare.validate_structure(params, prepare.validate_params(params), prepare.read_structure(structure),
                                   structure)


def test_excluded_common_ligands_ignore_their_altlocs(tmp_path):
    structure = _write(tmp_path, "so4_altloc.pdb", "\n".join([
        _line("ATOM", 1, "CA", "ALA", "A", 1),
        _line("HETATM", 2, "S", "SO4", "C", 2, altloc="A", x=5.0),
        "END",
    ]))
    records = prepare.read_structure(structure)
    skipped = _params(predict_ligand="", target_res="A-1", exclude_common_ligands=True)
    prepare.validate_structure(skipped, prepare.validate_params(skipped), records, structure)
    strict = _params(predict_ligand="", target_res="A-1")
    with pytest.raises(prepare.PreparationError, match="alternate locations"):
        prepare.validate_structure(strict, prepare.validate_params(strict), records, structure)


def test_fixed_all_with_target_res_and_centers_is_rejected(tmp_path):
    structure = _write(tmp_path, "complex.pdb", _complex())
    params = _params(predict_ligand="", fixed_ligand="LIG", target_res="A-1", crop_centers="B-1-LIG-C1")
    with pytest.raises(prepare.PreparationError, match="No ligand remains to predict"):
        prepare.validate_structure(params, prepare.validate_params(params), prepare.read_structure(structure),
                                   structure)


def test_cif_ligand_atoms_must_match_the_residue_library(tmp_path):
    # ZZQ is a real CCD name, but its template does not contain 4dtz LDP's atoms.
    structure = _write(tmp_path, "zzq.cif", _cif_with_ligand("ZZQ"))
    params = _params(predict_ligand="ZZQ")
    with pytest.raises(prepare.PreparationError, match="has heavy atoms PLACER does not parse"):
        prepare.validate_structure(params, prepare.validate_params(params), prepare.read_structure(structure),
                                   structure)


def test_cif_ligand_unknown_heavy_atom_is_rejected(tmp_path):
    structure = _write(tmp_path, "heavy.cif", _cif_with_typed_ligand([("C1", "C"), ("ZZ", "C")]))
    params = _params(predict_ligand="LIG")
    with pytest.raises(prepare.PreparationError, match="has heavy atoms PLACER does not parse"):
        prepare.validate_structure(params, prepare.validate_params(params), prepare.read_structure(structure),
                                   structure)


@pytest.mark.parametrize("element", ["H", "D"])
def test_cif_ligand_unknown_hydrogen_is_ignored(tmp_path, element):
    # cifutils skips unmatched H/D atoms but masks the residue for a heavy atom.
    structure = _write(tmp_path, "hydrogen.cif", _cif_with_typed_ligand([("C1", "C"), ("H9", element)]))
    params = _params(predict_ligand="LIG")
    prepare.validate_structure(params, prepare.validate_params(params), prepare.read_structure(structure), structure)


def test_pdb_ligand_atoms_are_parsed_by_openbabel(tmp_path, monkeypatch):
    # PDB polymer ALA resolves in the library; the HEM ligand never does, so its
    # dnHEM-style C1/FE1 atoms are valid even though the stub has no HEM entry.
    structure = _write(tmp_path, "dnhem.pdb", "\n".join([
        _line("ATOM", 1, "CA", "ALA", "A", 1),
        _line("HETATM", 2, "FE1", "HEM", "B", 213, x=5.0),
        _line("HETATM", 3, "C1", "HEM", "B", 213, x=6.0),
        "END",
    ]))
    monkeypatch.setattr(prepare, "_ccd_library", lambda: {"ALA": _CCD_STUB["ALA"]})
    params = _params(predict_ligand="HEM")
    prepare.validate_structure(params, prepare.validate_params(params), prepare.read_structure(structure), structure)


def test_pdb_polymer_residue_must_be_in_the_residue_library(tmp_path, monkeypatch):
    # pdbparser.py calls getRes for every ATOM residue; a None template raises.
    structure = _write(tmp_path, "xqz.pdb", "\n".join([
        _line("ATOM", 1, "CA", "XQZ", "A", 1),
        _line("HETATM", 2, "C1", "LIG", "B", 1, x=5.0),
        "END",
    ]))
    monkeypatch.setattr(prepare, "_ccd_library", lambda: {"ALA": _CCD_STUB["ALA"], "LIG": _CCD_STUB["LIG"]})
    params = _params()
    with pytest.raises(prepare.PreparationError, match=r"Protein residue name\(s\) 'XQZ'"):
        prepare.validate_structure(params, prepare.validate_params(params), prepare.read_structure(structure),
                                   structure)


def test_pdb_ligand_name_outside_the_library_is_parsed_by_openbabel(tmp_path):
    # The documented smoke ligand is lowercase "lig", which is not a CCD entry.
    structure = _write(tmp_path, "lower.pdb", _complex_with_ligands([("B", "lig", 1)]))
    params = _params(predict_ligand="lig")
    prepare.validate_structure(params, prepare.validate_params(params), prepare.read_structure(structure), structure)


def test_pdb_target_res_must_be_in_the_residue_library(tmp_path):
    # AAJ is a three-letter name that is absent from the shipped CCD.
    structure = _write(tmp_path, "aaj.pdb", "\n".join([
        _line("ATOM", 1, "CA", "AAJ", "A", 1),
        _line("HETATM", 2, "C1", "LIG", "B", 1, x=5.0),
        "END",
    ]))
    params = _params(target_res="A-1")
    with pytest.raises(prepare.PreparationError, match=r"Protein residue name\(s\) 'AAJ'"):
        prepare.validate_structure(params, prepare.validate_params(params), prepare.read_structure(structure),
                                   structure)


def _cif_with_polymer_atom(atom: str, element: str) -> str:
    return "\n".join([
        "data_test",
        "loop_",
        "_atom_site.group_PDB",
        "_atom_site.id",
        "_atom_site.type_symbol",
        "_atom_site.label_atom_id",
        "_atom_site.label_comp_id",
        "_atom_site.label_asym_id",
        "_atom_site.label_seq_id",
        "_atom_site.auth_seq_id",
        "ATOM 1 C CA ALA A 3 3",
        f"ATOM 2 {element} {atom} ALA A 3 3",
        "HETATM 3 C C1 LIG B . 1",
        "#",
    ])


def test_cif_polymer_heavy_atom_must_match_the_residue_library(tmp_path):
    # cifutils.py:609-610 masks the whole residue for an unmatched heavy atom.
    structure = _write(tmp_path, "poly.cif", _cif_with_polymer_atom("QQ", "C"))
    params = _params(predict_ligand="LIG")
    with pytest.raises(prepare.PreparationError, match="Residue A-3-ALA has heavy atoms PLACER does not parse"):
        prepare.validate_structure(params, prepare.validate_params(params), prepare.read_structure(structure),
                                   structure)


def test_cif_polymer_unknown_hydrogen_is_ignored(tmp_path):
    structure = _write(tmp_path, "poly_h.cif", _cif_with_polymer_atom("H9", "H"))
    params = _params(predict_ligand="LIG")
    prepare.validate_structure(params, prepare.validate_params(params), prepare.read_structure(structure), structure)


def test_cif_without_type_symbol_is_rejected(tmp_path):
    structure = _write(tmp_path, "no_symbol.cif", "\n".join([
        "data_test",
        "loop_",
        "_atom_site.group_PDB",
        "_atom_site.id",
        "_atom_site.label_atom_id",
        "_atom_site.label_comp_id",
        "_atom_site.label_asym_id",
        "_atom_site.label_seq_id",
        "_atom_site.auth_seq_id",
        "ATOM 1 CA ALA A 1 1",
        "HETATM 2 H9 LIG B . 1",
        "#",
    ]))
    with pytest.raises(prepare.PreparationError, match="_atom_site.type_symbol"):
        prepare.read_structure(structure)


def test_excluded_common_ligands_reject_a_polymer_name(tmp_path):
    structure = _write(tmp_path, "unk.pdb", "\n".join([
        _line("ATOM", 1, "CA", "UNK", "A", 1),
        _line("HETATM", 2, "C1", "LIG", "B", 1, x=5.0),
        "END",
    ]))
    records = prepare.read_structure(structure)
    params = _params(exclude_common_ligands=True)
    with pytest.raises(prepare.PreparationError, match="removes 'UNK' from PLACER's residue library"):
        prepare.validate_structure(params, prepare.validate_params(params), records, structure)
    # Without the flag PLACER still resolves UNK from its library.
    params = _params()
    prepare.validate_structure(params, prepare.validate_params(params), records, structure)

