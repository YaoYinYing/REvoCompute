# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Content validators for uploaded scientific inputs.

Legitimate files pass, pathological files are rejected, and the caps are
generous enough that no plausible real file can trip them.
"""

from __future__ import annotations

import gzip
import io
import json
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import _load_pssm_module, _test_client_auth
from revocompute.input_validators import MAX_CIF_ATOMS  # noqa: F401
from revocompute.input_validators import (
    MAX_CIF_RECORD_LENGTH,
    MAX_FASTA_RECORD_LENGTH,
    MAX_FASTA_SEQUENCES,
    MAX_FASTA_TOTAL_RESIDUES,
    MAX_JSON_DEPTH,
    MAX_JSON_NODES,
    MAX_PDB_LINES,
    MAX_PDB_RECORD_LENGTH,
    supported_input_formats,
    validate_a3m,
    validate_fasta,
    validate_input_file,
    validate_json,
    validate_logical_input,
    validate_mmcif,
    validate_pdb,
)
from revocompute.task_types import TaskInputRole, list_types

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write(tmp_path: Path, content: bytes, name: str = "input") -> Path:
    path = tmp_path / name
    path.write_bytes(content)
    return path


# ── real fixtures must pass ────────────────────────────────────────────────────


def test_real_fasta_fixtures_pass():
    for path in (
        REPO_ROOT / "tests/data/msa/2KL8.fasta",
        REPO_ROOT / "tests/data/msa/2KL8_blast.fasta",
        Path(__file__).parent / "data/test_esm.fasta",
    ):
        assert validate_fasta(str(path)) is None, path


@pytest.mark.parametrize(
    "relative",
    [
        "tests/data/pdb/1SUO.pdb",
        "tests/data/pdb/5an7.pdb",
        "tests/data/pdb/2KL8.pdb",
        "tests/data/pdb/3fap_hf3_A_short_lig.pdb",
        "tests/data/pdb/3fap_hf3_A_short_00001.pdb",
        "tests/data/3fap_hf3_A_short.pdb",
        "tests/data/6zcy_lig.pdb",
        "tests/data/lig/lig.fa.pdb",
        "tests/data/lig/lig.cen_conformers.pdb",
    ],
)
def test_real_pdb_fixtures_pass(relative):
    assert validate_pdb(str(REPO_ROOT / relative)) is None


@pytest.mark.parametrize(
    "relative",
    [
        "tests/data/json/sm_input/12968814160.json",
        "tests/data/ddg_csv.json",
        "tests/data/kinetics/openkinetics_1SUO/manifest.json",
        "tests/data/kinetics/openkinetics_1SUO/substrate.json",
        "tests/data/kinetics/openkinetics_1SUO/submit_response.json",
    ],
)
def test_real_json_fixtures_pass(relative):
    assert validate_json(str(REPO_ROOT / relative)) is None


# ── FASTA / A3M ────────────────────────────────────────────────────────────────


def test_fasta_requires_header(tmp_path):
    path = _write(tmp_path, b"ACDEFGHIK\n")
    assert "'>' header" in validate_fasta(str(path))


def test_fasta_rejects_sequence_before_header(tmp_path):
    path = _write(tmp_path, b"ACDE\n>h\nACDE\n")
    assert "start with a '>' header" in validate_fasta(str(path))


def test_fasta_rejects_non_alphabet_characters(tmp_path):
    path = _write(tmp_path, b">h\nACD2EF\n")
    assert "invalid character '2'" in validate_fasta(str(path))


def test_fasta_rejects_lowercase_but_a3m_allows_it(tmp_path):
    lower = _write(tmp_path, b">h\nACDEfghi\n")
    assert "invalid character" in validate_fasta(str(lower))
    assert validate_a3m(str(lower)) is None


def test_fasta_accepts_full_alphabet_and_gaps(tmp_path):
    path = _write(
        tmp_path,
        b">h\nACDEFGHIKLMNPQRSTVWYXBZJOU*-. ACDE\n",  # interior space tolerated
    )
    assert validate_fasta(str(path)) is None


def test_fasta_rejects_nul_byte_deep_in_file(tmp_path):
    # The HTTP-layer sniff only reads 4096 bytes, so the NUL must be caught here.
    path = _write(tmp_path, b">h\n" + b"A" * 8192 + b"\0ACDE\n")
    assert "NUL byte" in validate_fasta(str(path))


def test_fasta_rejects_too_many_sequences(tmp_path):
    path = _write(tmp_path, b">s\nA\n" * (MAX_FASTA_SEQUENCES + 1))
    assert f"more than {MAX_FASTA_SEQUENCES} sequences" in validate_fasta(str(path))


def test_fasta_rejects_overlong_header(tmp_path):
    path = _write(tmp_path, b">" + b"X" * MAX_FASTA_RECORD_LENGTH + b"\nA\n")

    assert f"record longer than {MAX_FASTA_RECORD_LENGTH}" in validate_fasta(str(path))


def test_fasta_residue_cap_cannot_be_reached_within_upload_limit():
    # 16 MiB upload cap / 1 byte per residue — the cap is a safety valve that
    # cannot fire on any file that fits in MAX_CONTENT_LENGTH.
    assert MAX_FASTA_TOTAL_RESIDUES > 16 * 1024 * 1024


# ── PDB ────────────────────────────────────────────────────────────────────────


def test_pdb_accepts_long_remark_preamble(tmp_path):
    preamble = b"REMARK 999 long preamble\n" * 200
    body = (
        b"CRYST1  100.0 100.0 100.0  90 90 90 P 1\n"
        b"ATOM      1  CA  ALA A   1      0.000   0.000   0.000  1.00  0.00           C\n"
        b"END\n"
    )
    path = _write(tmp_path, preamble + body)
    assert validate_pdb(str(path)) is None


def test_pdb_accepts_single_atom_line_without_end(tmp_path):
    # Mirrors the minimal PDB used by existing route tests.
    path = _write(tmp_path, b"ATOM      1  CA  ALA A   1\n")
    assert validate_pdb(str(path)) is None


def test_pdb_rejects_gzip_binary(tmp_path):
    # Compressed bytes are rejected by either the NUL check or the record
    # sniff — what matters is that no gzip stream passes for a PDB.
    path = _write(tmp_path, gzip.compress(b"ATOM      1  CA  ALA A   1\n" * 100), "model.pdb")
    assert validate_pdb(str(path)) is not None


def test_pdb_rejects_plain_text_without_records(tmp_path):
    path = _write(tmp_path, b"this is not a pdb\n" * 50)
    assert "ATOM, HETATM, or END" in validate_pdb(str(path))


def test_pdb_rejects_too_many_lines(tmp_path):
    path = _write(tmp_path, b"END\n" * (MAX_PDB_LINES + 1))
    assert f"more than {MAX_PDB_LINES} lines" in validate_pdb(str(path))


def test_pdb_rejects_overlong_record(tmp_path):
    path = _write(tmp_path, b"ATOM  " + b"X" * MAX_PDB_RECORD_LENGTH + b"\n")
    assert "longer than" in validate_pdb(str(path))


def test_pdb_rejects_nul_byte(tmp_path):
    path = _write(tmp_path, b"ATOM      1  CA  ALA A   1\n\0ACDE\n")
    assert "NUL byte" in validate_pdb(str(path))


# ── mmCIF ──────────────────────────────────────────────────────────────────────


def _mmcif(atom_rows: int) -> bytes:
    head = (
        "data_1SUO\n"
        "#\n"
        "_cell.length_a 100.0\n"
        "_cell.length_b 100.0\n"
        "loop_\n"
        "_atom_site.group_PDB\n"
        "_atom_site.id\n"
        "_atom_site.type_symbol\n"
        "_atom_site.label_atom_id\n"
        "_atom_site.label_comp_id\n"
    )
    rows = "".join(f"ATOM {i} N N ALA\n" for i in range(1, atom_rows + 1))
    return (head + rows + "#\nloop_\n_entity.id\n1\n").encode()


def test_mmcif_realistic_file_passes(tmp_path):
    path = _write(tmp_path, _mmcif(100))
    assert validate_mmcif(str(path)) is None


def test_mmcif_accepts_second_data_block_without_atoms(tmp_path):
    # A .cif used for restraints/topology may have no _atom_site loop at all.
    path = _write(tmp_path, b"data_restraints\n_chem_comp.id 'ALA'\n")
    assert validate_mmcif(str(path)) is None


def test_mmcif_rejects_plain_text(tmp_path):
    path = _write(tmp_path, b"this is not a cif\n" * 50)
    assert "data_ block or _atom_site." in validate_mmcif(str(path))


def test_mmcif_rejects_too_many_atoms(tmp_path):
    path = _write(tmp_path, _mmcif(MAX_CIF_ATOMS + 1))
    assert f"more than {MAX_CIF_ATOMS} atoms" in validate_mmcif(str(path))


def test_mmcif_rejects_overlong_record(tmp_path):
    path = _write(tmp_path, b"data_x\n" + b"_atom_site.id " + b"Y" * MAX_CIF_RECORD_LENGTH + b"\n")
    assert "longer than" in validate_mmcif(str(path))


def test_mmcif_rejects_nul_byte(tmp_path):
    path = _write(tmp_path, b"data_x\n\x00")
    assert "NUL byte" in validate_mmcif(str(path))


# ── JSON ───────────────────────────────────────────────────────────────────────


def test_json_accepts_valid_documents(tmp_path):
    for doc in ("{}", "[]", '"plain string"', "42", '[{"a": [1, 2, {"b": null}]}]'):
        path = _write(tmp_path, doc.encode())
        assert validate_json(str(path)) is None, doc


def test_json_rejects_invalid_json(tmp_path):
    path = _write(tmp_path, b'{"contigs": ["A1-10", }')
    assert "not appear to be valid JSON" in validate_json(str(path))


# -- PDB syntax ---------------------------------------------------------------


def _pdb_line(serial, name, res, chain, seq, x, y, z, element, altloc=" "):
    return (
        f"ATOM  {serial:5d} {name:>4s}{altloc}{res:>3s} {chain}{seq:4d}    "
        f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00          {element:>2s}"
    )


def _write_pdb(tmp_path, name, atoms):
    path = tmp_path / name
    path.write_text("\n".join(atoms) + "\nTER\nEND\n", encoding="utf-8")
    return path


def test_pdb_syntax_accepts_altloc_records(tmp_path):
    atoms = [
        _pdb_line(1, "N", "SER", "A", 1, 1.5, 0.0, 0.0, "N"),
        _pdb_line(2, "CA", "SER", "A", 1, 2.5, 0.0, 0.0, "C"),
        _pdb_line(3, "CB", "SER", "A", 1, 2.5, 1.0, 0.0, "C"),
        _pdb_line(4, "OG", "SER", "A", 1, 2.5, 1.9, 0.0, "O"),
    ]
    # duplicate the OG with an alternate location indicator (col 17 = 'B')
    alt = _pdb_line(4, "OG", "SER", "A", 1, 2.6, 1.9, 0.0, "O", altloc="B")
    path = _write_pdb(tmp_path, "altloc.pdb", atoms + [alt])
    assert validate_pdb(str(path)) is None


def test_json_rejects_oversized_input_before_parsing(tmp_path):
    # A flat list of MAX_JSON_NODES + 1 elements is well-formed JSON but
    # exceeds the pre-parse byte ceiling, which rejects it before the full
    # object graph is allocated (the node-count cap is the second line of
    # defence and stays for future ceiling changes).
    path = _write(tmp_path, ("[" + "0," * MAX_JSON_NODES + "0]").encode())
    assert "MiB input limit" in validate_json(str(path))


def test_json_rejects_deep_nesting(tmp_path):
    # The leaf sits at depth MAX_JSON_DEPTH + 1 — one level past the cap.
    doc = "[" * MAX_JSON_DEPTH + "0" + "]" * MAX_JSON_DEPTH
    path = _write(tmp_path, doc.encode())
    assert f"nested deeper than {MAX_JSON_DEPTH}" in validate_json(str(path))


def test_json_accepts_nesting_at_the_cap(tmp_path):
    # The deepest value of MAX_JSON_DEPTH containers sits at depth
    # MAX_JSON_DEPTH and must pass.
    doc = "[" * (MAX_JSON_DEPTH - 1) + "0" + "]" * (MAX_JSON_DEPTH - 1)
    path = _write(tmp_path, doc.encode())
    assert validate_json(str(path)) is None


def test_json_rejects_non_utf8(tmp_path):
    path = _write(tmp_path, b'{"name": "\xff\xfe"}')
    assert "not valid UTF-8" in validate_json(str(path))


def test_json_rejects_nul_byte(tmp_path):
    path = _write(tmp_path, b'{"a": 1}\x00')
    assert "NUL byte" in validate_json(str(path))


# ── extension dispatch ─────────────────────────────────────────────────────────


def test_dispatch_routes_by_extension(tmp_path):
    pdb = _write(tmp_path, b"ATOM      1  CA  ALA A   1\n", "model.pdb")
    assert validate_input_file(str(pdb), "model.pdb") is None
    assert validate_input_file(str(pdb), "sub/dir/model.pdb") is None
    fasta = _write(tmp_path, b"not fasta\n", "seqs.fasta")
    assert validate_input_file(str(fasta), "seqs.fasta") is not None
    assert validate_input_file(str(pdb), "model.txt") == "Unsupported input format: .txt"


def test_a3m_dispatched_by_extension(tmp_path):
    path = _write(tmp_path, b">h\nACDEfghi\n", "msa.a3m")
    assert validate_input_file(str(path), "msa.a3m") is None


def test_every_production_task_format_has_a_core_security_validator():
    declared = {format_name for task_type in list_types() for role in task_type.inputs for format_name in role.formats}

    assert declared <= supported_input_formats()


@pytest.mark.parametrize("extension", ["fasta", "fas", "yaml", "yml", "csv", "restraints"])
def test_declared_text_formats_reject_binary_content(tmp_path, extension):
    path = _write(tmp_path, b"valid-looking prefix\n\xff\xfe\x00payload", f"input.{extension}")

    assert validate_input_file(str(path), path.name) is not None


def test_yaml_and_delimited_text_formats_are_content_checked(tmp_path):
    yaml_path = _write(tmp_path, b"version: 1\nsequences: []\n", "input.yaml")
    csv_path = _write(tmp_path, b"key,value\nquery,ACDE\n", "input.csv")
    restraints_path = _write(tmp_path, b"restraint_id\n", "input.restraints")
    html_path = _write(tmp_path, b"<script>alert(1)</script>\n", "markup.csv")

    assert validate_input_file(str(yaml_path), yaml_path.name) is None
    assert validate_input_file(str(csv_path), csv_path.name) is None
    assert validate_input_file(str(restraints_path), restraints_path.name) is None
    assert validate_input_file(str(html_path), html_path.name) is not None


def test_yaml_aliases_are_rejected_before_runner_parsing(tmp_path):
    yaml_path = _write(tmp_path, b"shared: &shared [A, B]\nsequences: *shared\n", "input.yaml")

    assert "aliases are not supported" in validate_input_file(str(yaml_path), yaml_path.name)


def test_parquet_transport_magic_is_checked(tmp_path):
    parquet = _write(tmp_path, b"PAR1metadataPAR1", "alignment.pqt")
    renamed = _write(tmp_path, b"#!/bin/sh\necho unsafe\n", "alignment-renamed.pqt")

    assert validate_input_file(str(parquet), parquet.name) is None
    assert validate_logical_input(str(parquet), "pqt", "alignment") is None
    assert validate_input_file(str(renamed), renamed.name) is not None


@pytest.mark.parametrize(
    ("relative", "logical_type"),
    [
        ("tests/data/json/alphafold3_tiny.json", "alphafold3_specification"),
        ("tests/data/json/opendde_tiny.json", "opendde_specification"),
        ("tests/data/foundry/rf3_monomer.json", "foundry_specification"),
        ("tests/data/foundry/rfd3_unconditional.json", "foundry_specification"),
    ],
)
def test_production_json_specification_profiles_accept_real_fixtures(relative, logical_type):
    path = REPO_ROOT / relative

    assert validate_logical_input(str(path), "json", logical_type) is None


@pytest.mark.parametrize("key", ["userCCDPath", "unpairedMsaPath", "pairedMsaPath", "mmcifPath"])
def test_alphafold3_specification_rejects_upstream_external_file_fields(tmp_path, key):
    path = _write(
        tmp_path,
        json.dumps(
            {
                "name": "unsafe",
                "modelSeeds": [1],
                "sequences": [{"protein": {"id": "A", "sequence": "ACDE", key: "/etc/passwd"}}],
                "dialect": "alphafold3",
                "version": 1,
            }
        ).encode(),
        "input.json",
    )

    assert "external file field" in validate_logical_input(str(path), "json", "alphafold3_specification")


@pytest.mark.parametrize("logical_type", ["alphafold3_specification", "opendde_specification"])
def test_json_specifications_reject_external_urls(tmp_path, logical_type):
    path = _write(tmp_path, b'{"name":"unsafe","description":"https://example.invalid/input"}', "input.json")

    assert "external URL" in validate_logical_input(str(path), "json", logical_type)


def test_json_specifications_reject_external_urls_nested_in_arrays(tmp_path):
    path = _write(tmp_path, b'{"inputs":["https://example.invalid/input"]}', "input.json")

    assert "external URL" in validate_logical_input(str(path), "json", "opendde_specification")


@pytest.mark.parametrize(
    "document",
    [
        {"name": "missing metadata", "modelSeeds": [1], "sequences": [{"protein": {"sequence": "ACDE"}}]},
        {
            "name": "wrong dialect",
            "dialect": "other",
            "version": 1,
            "modelSeeds": [1],
            "sequences": [{"protein": {"sequence": "ACDE"}}],
        },
    ],
)
def test_alphafold3_native_objects_require_upstream_dialect_metadata(tmp_path, document):
    path = _write(tmp_path, json.dumps(document).encode(), "input.json")

    assert "dialect" in validate_logical_input(str(path), "json", "alphafold3_specification")


def test_foundry_specification_allows_confined_assets_and_rejects_escapes(tmp_path):
    safe = _write(tmp_path, b'{"input":"assets/template.pdb"}', "safe.json")
    absolute = _write(tmp_path, b'{"input":"/etc/passwd"}', "absolute.json")
    traversal = _write(tmp_path, b'{"template_path":"../private.pdb"}', "traversal.json")
    remote = _write(tmp_path, b'{"msa_path":"https://example.invalid/msa.a3m"}', "remote.json")

    assert validate_logical_input(str(safe), "json", "foundry_specification") is None
    for path in (absolute, traversal, remote):
        assert "confined uploaded asset" in validate_logical_input(str(path), "json", "foundry_specification")


@pytest.mark.parametrize(
    ("document", "logical_type"),
    [
        ("42", "alphafold3_specification"),
        ("[]", "opendde_specification"),
        ('"value"', "foundry_specification"),
    ],
)
def test_json_specification_profiles_reject_invalid_top_level_shapes(tmp_path, document, logical_type):
    path = _write(tmp_path, document.encode(), "input.json")

    assert "top-level" in validate_logical_input(str(path), "json", logical_type)


def test_executable_renamed_as_pdb_and_zip_renamed_as_cif_are_rejected(tmp_path):
    executable = _write(tmp_path, b"#!/bin/sh\necho unsafe\n", "payload.pdb")
    archive = _write(tmp_path, b"PK\x03\x04" + b"\x00" * 32, "payload.cif")

    assert validate_input_file(str(executable), executable.name) is not None
    assert validate_input_file(str(archive), archive.name) is not None


# ── route level: the security fix ──────────────────────────────────────────────


def _pdb_task_module(monkeypatch, tmp_path):
    """Load the app with a registered non-GREMLIN .pdb task type."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    base_type, runner = module.task_runtime._get_task_type("gremlin")
    module.task_runtime._register_tt(
        replace(
            base_type,
            name="pdb_only",
            display_name="PDB Only",
            inputs=(
                TaskInputRole(
                    name="structure",
                    title="PDB file",
                    type="protein_structure",
                    formats=("pdb",),
                    minimum=1,
                    maximum=1,
                ),
            ),
            params=(),
        ),
        runner,
    )
    return module


def test_upload_gzip_disguised_as_pdb_rejected(monkeypatch, tmp_path):
    """Non-GREMLIN inputs are content-checked: a gzip bomb named .pdb is refused."""
    module = _pdb_task_module(monkeypatch, tmp_path)
    client = module.app.test_client()
    auth_header = _test_client_auth(module)
    payload = gzip.compress(b"ATOM      1  CA  ALA A   1\n" * 100)

    response = client.post(
        "/compute/api/post",
        data={"task_type": "pdb_only", "files": (io.BytesIO(payload), "model.pdb"), "input_roles": "structure"},
        headers=auth_header,
    )
    assert response.status_code == 400, response.get_data(as_text=True)


def test_upload_text_without_pdb_records_rejected(monkeypatch, tmp_path):
    """Plain text (not caught by the binary sniff) named .pdb is refused."""
    module = _pdb_task_module(monkeypatch, tmp_path)
    client = module.app.test_client()
    auth_header = _test_client_auth(module)

    response = client.post(
        "/compute/api/post",
        data={"task_type": "pdb_only", "files": (io.BytesIO(b"this is not a pdb\n" * 50), "model.pdb"), "input_roles": "structure"},
        headers=auth_header,
    )
    assert response.status_code == 400, response.get_data(as_text=True)
    assert "ATOM, HETATM, or END" in response.json["error"]


def test_upload_bad_fasta_for_gremlin_rejected(monkeypatch, tmp_path):
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    client = module.app.test_client()
    auth_header = _test_client_auth(module)

    response = client.post(
        "/compute/api/post",
        data={"task_type": "gremlin", "files": (io.BytesIO(b"ACDE\n>h\nACDE\n"), "seqs.fasta"), "input_roles": "sequence"},
        headers=auth_header,
    )
    assert response.status_code == 400, response.get_data(as_text=True)
    assert "start with a '>' header" in response.json["error"]


def test_upload_valid_pdb_accepted(monkeypatch, tmp_path):
    module = _pdb_task_module(monkeypatch, tmp_path)
    client = module.app.test_client()
    auth_header = _test_client_auth(module)

    class _Queued:
        id = "queued-pdb"

    monkeypatch.setattr(module.run_compute_task, "apply_async", lambda *args, **kwargs: _Queued())
    response = client.post(
        "/compute/api/post",
        data={"task_type": "pdb_only", "files": (io.BytesIO(b"ATOM      1  CA  ALA A   1\n"), "model.pdb"), "input_roles": "structure"},
        headers=auth_header,
    )
    assert response.status_code == 302, response.get_json()
