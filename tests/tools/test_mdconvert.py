# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

# MDAnalysis belongs to the mdconvert Tool runtime, not the Server environment.
# The Server suite skips these scientific checks cleanly when that dependency is
# absent; the mdconvert SIF `%test` and target-host Tool acceptance remain
# authoritative for the real runtime.
pytest.importorskip("MDAnalysis", reason="mdconvert Tool CLI dependencies live in its SIF runtime")

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "data" / "mdconvert"
LIMITS = {
    "request_bytes": 108_000_000,
    "input_bytes": {"topology": 8_000_000, "trajectory": 100_000_000},
}


def _module():
    path = REPO_ROOT / "docker" / "tools" / "mdconvert" / "python" / "tool_cli.py"
    spec = importlib.util.spec_from_file_location("mdconvert_tool_cli", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _pdb_identity(path: Path) -> list[tuple[str, int, str, str]]:
    """The identity tuples CAVER compares across a snapshot series."""
    return [
        (line[21:22].strip(), int(line[22:26]), line[26:27].strip(), line[12:16].strip())
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith(("ATOM", "HETATM"))
    ]


def _fixture(tmp_path: Path, name: str) -> Path:
    target = tmp_path / "inputs" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((FIXTURES / name).read_bytes())
    return target


def _request(
    tmp_path: Path,
    parameters: dict,
    *,
    topology: str = "tiny.gro",
    trajectory: str = "tiny.xtc",
    topology_format: str = "gro",
    trajectory_format: str = "xtc",
) -> tuple[Path, Path]:
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "tool": "md_trajectory_convert",
                "parameters": parameters,
                "inputs": {
                    "topology": [{"path": str(_fixture(tmp_path, topology)), "format": topology_format}],
                    "trajectory": [{"path": str(_fixture(tmp_path, trajectory)), "format": trajectory_format}],
                },
                "limits": LIMITS,
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "output"
    output.mkdir()
    return request, output


def _run(tmp_path: Path, parameters: dict, **kwargs) -> tuple[dict, Path, dict]:
    module = _module()
    request, output = _request(tmp_path, parameters, **kwargs)
    response = module.md_trajectory_convert(request, output)
    manifest = json.loads((output / "conversion_manifest.json").read_text(encoding="utf-8"))
    return response, output, manifest


def _pdb_coordinates(path: Path) -> list[tuple[float, float, float]]:
    coordinates = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(("ATOM", "HETATM")):
            coordinates.append((float(line[30:38]), float(line[38:46]), float(line[46:54])))
    return coordinates


def test_gro_xtc_conversion_preserves_known_units_identity_and_times(tmp_path):
    response, output, manifest = _run(
        tmp_path, {"output_adapter": "caver_pdb_snapshots", "pbc_treatment": "none"}
    )

    assert [item["path"] for item in response["outputs"]["reference"]] == ["reference.pdb"]
    assert [item["path"] for item in response["outputs"]["snapshots"]] == [
        "snapshot_001.pdb",
        "snapshot_002.pdb",
    ]
    # Fixture coordinates are authored in nanometres; the PDB must carry the
    # same physical points in Angstrom with no second scale factor.
    assert _pdb_coordinates(output / "reference.pdb") == [
        (1.0, 2.0, 3.0),
        (4.0, 5.0, 6.0),
        (7.0, 8.0, 9.0),
        (10.0, 11.0, 12.0),
    ]
    assert _pdb_coordinates(output / "snapshot_001.pdb")[0] == (2.0, 3.0, 4.0)
    assert _pdb_coordinates(output / "snapshot_002.pdb")[0] == (3.0, 4.0, 5.0)
    assert "CRYST1   20.000   20.000   20.000" in (output / "reference.pdb").read_text(encoding="utf-8")

    assert manifest["frame_count"] == 3
    assert manifest["reference"]["source_frame_index"] == 0
    assert [item["time_ps"] for item in manifest["snapshots"]] == [10.0, 20.0]
    assert all(
        item["box_angstrom"][:3] == [20.0, 20.0, 20.0]
        for item in [manifest["reference"], *manifest["snapshots"]]
    )
    assert manifest["units"]["source_coordinate_unit"] == "nm"
    assert manifest["units"]["output_coordinate_unit"] == "angstrom"
    assert manifest["pbc"]["treatment"] == "none"
    assert manifest["atoms"]["selected_atom_count"] == 4
    assert {"elements_not_representable", "chain_identity_synthetic"} <= {
        item["code"] for item in manifest["warnings"]
    }
    assert manifest["atoms"]["selection"] == "all"
    assert len(manifest["atoms"]["atom_map_sha256"]) == 64
    assert manifest["sources"]["topology"]["sha256"] == hashlib.sha256(
        (tmp_path / "inputs" / "tiny.gro").read_bytes()
    ).hexdigest()
    assert manifest["sources"]["trajectory"]["sha256"] == hashlib.sha256(
        (tmp_path / "inputs" / "tiny.xtc").read_bytes()
    ).hexdigest()
    for item in [manifest["reference"], *manifest["snapshots"]]:
        written = output / item["output"]
        assert item["sha256"] == hashlib.sha256(written.read_bytes()).hexdigest()

    # Every frame keeps the reference's fixed-order atom/residue identity.
    reference_identity = _pdb_identity(output / "reference.pdb")
    assert [item[3] for item in reference_identity] == ["N", "CA", "C", "O"]
    assert [item[1] for item in reference_identity] == [1, 1, 2, 2]
    for name in ("snapshot_001.pdb", "snapshot_002.pdb"):
        assert _pdb_identity(output / name) == reference_identity


def test_reference_frame_and_selection_keep_stable_atom_identity(tmp_path):
    _response, output, manifest = _run(
        tmp_path,
        {"selection": "name CA", "frame_indices": [0, 2], "reference_frame": 2},
    )

    assert manifest["atoms"]["selection"] == "name CA"
    assert manifest["atoms"]["selected_atom_count"] == 1
    assert manifest["reference"]["source_frame_index"] == 2
    assert [item["source_frame_index"] for item in manifest["snapshots"]] == [0]
    assert _pdb_coordinates(output / "reference.pdb") == [(6.0, 7.0, 8.0)]
    assert _pdb_coordinates(output / "snapshot_001.pdb") == [(4.0, 5.0, 6.0)]
    assert "CA  ALA X   1" in (output / "reference.pdb").read_text(encoding="utf-8")


def test_no_periodic_box_is_reported_without_invention(tmp_path):
    _response, output, manifest = _run(tmp_path, {}, trajectory="no_box.xtc")

    assert manifest["pbc"]["treatment"] == "none"
    assert manifest["reference"]["box_angstrom"] is None
    assert "no_periodic_box" in {item["code"] for item in manifest["warnings"]}
    assert "CRYST1" not in (output / "reference.pdb").read_text(encoding="utf-8")


def test_mixed_periodic_box_frames_fail_closed(tmp_path):
    module = _module()
    request, output = _request(tmp_path, {}, trajectory="mixed_box.xtc")

    with pytest.raises(module.ToolInputError) as error:
        module.md_trajectory_convert(request, output)
    assert error.value.code == "missing_pbc_box"


def test_duplicate_pdb_identity_is_refused(tmp_path):
    module = _module()
    request, output = _request(
        tmp_path, {}, topology="duplicate_identity.gro", trajectory="three_atoms.xtc"
    )

    with pytest.raises(module.ToolInputError) as error:
        module.md_trajectory_convert(request, output)
    assert error.value.code == "pdb_identity_unrepresentable"


@pytest.mark.parametrize(
    ("parameters", "code"),
    [
        ({"pbc_treatment": "unwrap"}, "pbc_unwrap_unsupported"),
        ({"selection": "name CA and resid 1"}, "selection_invalid"),
        ({"selection": "resid 9-1"}, "selection_invalid"),
        ({"frame_indices": list(range(52))}, "frame_selection_invalid"),
        ({"frame_indices": [0, 2], "reference_frame": 1}, "reference_frame_not_selected"),
        ({"start": 0, "stop": 9}, "frame_selection_range"),
        ({"frame_indices": [0, 0]}, "frame_selection_invalid"),
        ({"output_adapter": "amber_netcdf"}, "output_adapter_unknown"),
    ],
)
def test_parameter_refusals_are_typed(tmp_path, parameters, code):
    module = _module()
    request, output = _request(tmp_path, parameters)

    with pytest.raises(module.ToolInputError) as error:
        module.md_trajectory_convert(request, output)
    assert error.value.code == code


def test_unsupported_format_pair_is_refused_before_parsing(tmp_path):
    module = _module()
    (tmp_path / "inputs").mkdir(exist_ok=True)
    (tmp_path / "inputs" / "toy.prmtop").write_text("%VERSION 1.0\n%FLAG POINTERS\n", encoding="utf-8")
    request, output = _request(tmp_path, {}, topology_format="prmtop")
    request.write_text(
        json.dumps(
            {
                "tool": "md_trajectory_convert",
                "parameters": {},
                "inputs": {
                    "topology": [{"path": str(tmp_path / "inputs" / "toy.prmtop"), "format": "prmtop"}],
                    "trajectory": [{"path": str(tmp_path / "inputs" / "tiny.xtc"), "format": "xtc"}],
                },
                "limits": LIMITS,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(module.ToolInputError) as error:
        module.md_trajectory_convert(request, output)
    assert error.value.code == "unsupported_format_pair"


@pytest.mark.parametrize("trajectory", ["three_atoms.xtc", "truncated.xtc", "bad_magic.xtc"])
def test_corrupt_or_mismatched_trajectory_writes_typed_failure(tmp_path, trajectory):
    module = _module()
    request, output = _request(tmp_path, {}, trajectory=trajectory)

    result = module.main(
        ["run", "--tool", "md_trajectory_convert", "--request", str(request), "--output", str(output)]
    )
    assert result == 2
    detail = json.loads((output / ".tool-error.json").read_text(encoding="utf-8"))
    assert detail["code"] == "trajectory_parse_failed"
    assert not (output / ".tool-response.json").exists()


def test_nan_coordinate_fails_closed(tmp_path):
    module = _module()
    request, output = _request(tmp_path, {}, trajectory="nan.xtc")

    with pytest.raises(module.ToolInputError) as error:
        module.md_trajectory_convert(request, output)
    assert error.value.code == "non_finite_coordinates"


def test_unsafe_input_path_is_refused(tmp_path):
    module = _module()
    request, output = _request(tmp_path, {})
    payload = json.loads(request.read_text(encoding="utf-8"))
    link = tmp_path / "inputs" / "linked.gro"
    link.symlink_to(tmp_path / "inputs" / "tiny.gro")
    payload["inputs"]["topology"] = [{"path": str(link), "format": "gro"}]
    request.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(module.ToolInputError) as error:
        module.md_trajectory_convert(request, output)
    assert error.value.code == "input_missing"


def test_child_resource_and_output_caps_are_enforced(tmp_path, monkeypatch):
    module = _module()
    request, output = _request(tmp_path, {})
    monkeypatch.setattr(module, "MAX_RSS_BYTES", -1)
    with pytest.raises(module.ToolInputError) as error:
        module.md_trajectory_convert(request, output)
    assert error.value.code == "rss_limit"

    monkeypatch.setattr(module, "MAX_RSS_BYTES", 2 * 1024 * 1024 * 1024)
    monkeypatch.setattr(module, "MAX_CPU_SECONDS", -1.0)
    with pytest.raises(module.ToolInputError) as error:
        module.md_trajectory_convert(request, output)
    assert error.value.code == "cpu_limit"

    monkeypatch.setattr(module, "MAX_CPU_SECONDS", 240.0)
    monkeypatch.setattr(module, "MAX_OUTPUT_BYTES", 500)
    with pytest.raises(module.ToolInputError) as error:
        module.md_trajectory_convert(request, output)
    assert error.value.code == "output_size_limit"

    monkeypatch.setattr(module, "MAX_OUTPUT_BYTES", 33_554_432)
    monkeypatch.setattr(module, "MAX_ATOMS", 2)
    with pytest.raises(module.ToolInputError) as error:
        module.md_trajectory_convert(request, output)
    assert error.value.code == "atom_count_limit"


def test_decoded_input_limits_are_rechecked_in_the_child(tmp_path):
    module = _module()
    request, output = _request(tmp_path, {})
    payload = json.loads(request.read_text(encoding="utf-8"))
    payload["limits"] = {"request_bytes": 10, "input_bytes": {"topology": 10, "trajectory": 10}}
    request.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(module.ToolInputError) as error:
        module.md_trajectory_convert(request, output)
    assert error.value.code == "input_size_limit"
