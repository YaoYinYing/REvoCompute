# Copyright (c) 2026 The REvoDesign Developers.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest

FAMILY = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("boltz2_adapter", FAMILY / "adapter.py")
assert SPEC and SPEC.loader
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)

_VALID_CIF = """data_model
loop_
_atom_site.label_atom_id
_atom_site.label_comp_id
_atom_site.Cartn_x
_atom_site.Cartn_y
_atom_site.Cartn_z
CA ALA 1.0 2.0 3.0
"""


def _assets(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "assets"
    root.mkdir()
    lines = []
    for name in adapter.ASSETS:
        (root / name).write_bytes(name.encode())
        lines.append(f"{hashlib.sha256(name.encode()).hexdigest()}  {name}")
    # A representative extracted library so the tree digest binds real bytes.
    for relative in ("mols/ligand.pkl", "mols/cofactor.pkl"):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(relative.encode())
    lines.append(f"{adapter._tree_digest(root / adapter.MOLS_DIR)}  {adapter.MOLS_DIR}")
    manifest = tmp_path / "assets.sha256"
    manifest.write_text("\n".join(lines) + "\n")
    return root, manifest


def _task(
    tmp_path: Path,
    content: str,
    *,
    spec_relative: str = "system.yaml",
    assets: tuple[tuple[Path, str], ...] = (),
) -> Path:
    source = tmp_path / "source-system.yaml"
    source.write_text(content)
    task = tmp_path / "task.json"
    task.write_text(json.dumps({
        "inputs": {
            "specification": [{"path": str(source), "relative_path": spec_relative}],
            "assets": [{"path": str(path), "relative_path": relative} for path, relative in assets],
        },
        "params": {"recycling_steps": 1, "sampling_steps": 2, "diffusion_samples": 1,
                   "preprocessing_workers": 0, "seed": 0},
    }))
    return task


def test_command_selects_boltz2_and_explicit_affinity_checkpoint(tmp_path: Path) -> None:
    args = adapter.command("boltz", tmp_path / "x.yaml", tmp_path, tmp_path / "assets",
                           {"recycling_steps": 3, "sampling_steps": 8, "diffusion_samples": 2,
                            "preprocessing_workers": 0, "seed": 9}, True)
    assert args[1:4] == ["predict", str(tmp_path / "x.yaml"), "--model"]
    assert "boltz2" in args
    assert args[args.index("--affinity_checkpoint") + 1].endswith("boltz2_aff.ckpt")
    assert "--use_msa_server" not in args
    assert "--output_format" in args and args[args.index("--output_format") + 1] == "mmcif"


def test_prepare_confines_msa_and_rejects_external_references(tmp_path: Path) -> None:
    task = _task(tmp_path, "version: 1\nsequences:\n- protein:\n    id: A\n    sequence: ACDE\n    msa: ../../etc/passwd\n")
    with pytest.raises(ValueError, match="unsafe MSA reference"):
        adapter.prepare(task, tmp_path / "prepared", "boltz2_predict")


def test_prepare_requires_explicit_empty_or_supplied_msa(tmp_path: Path) -> None:
    task = _task(tmp_path, "version: 1\nsequences:\n- protein:\n    id: A\n    sequence: ACDE\n")
    with pytest.raises(ValueError, match="must explicitly declare msa"):
        adapter.prepare(task, tmp_path / "prepared", "boltz2_predict")


def test_nested_spec_consumes_the_resolved_msa(tmp_path: Path) -> None:
    """Upstream resolves the raw msa against the spec's parent, not the root."""
    alignment = tmp_path / "q.a3m"
    alignment.write_text(">q\nACDE\n")
    task = _task(
        tmp_path,
        "version: 1\nsequences:\n- protein:\n    id: A\n    sequence: ACDE\n    msa: alignments/q.a3m\n",
        spec_relative="inputs/system.yaml",
        assets=((alignment, "inputs/alignments/q.a3m"),),
    )

    spec, provenance = adapter.prepare(task, tmp_path / "prepared", "boltz2_predict")

    assert spec == (tmp_path / "prepared/inputs/system.yaml").resolve()
    consumed = tmp_path / "prepared/inputs/alignments/q.a3m"
    assert consumed.read_text() == ">q\nACDE\n"
    assert provenance["msa"] == [
        {
            "chain": "A",
            "declared": "alignments/q.a3m",
            "consumed": "inputs/alignments/q.a3m",
            "sha256": hashlib.sha256(b">q\nACDE\n").hexdigest(),
        }
    ]


def test_duplicate_msa_paths_resolve_to_the_consumed_file(tmp_path: Path) -> None:
    """A root copy must not be verified while the spec-relative copy is consumed."""
    root_alignment = tmp_path / "root.a3m"
    root_alignment.write_text(">root\nAAAA\n")
    consumed_alignment = tmp_path / "nested.a3m"
    consumed_alignment.write_text(">nested\nBBBB\n")
    task = _task(
        tmp_path,
        "version: 1\nsequences:\n- protein:\n    id: A\n    sequence: ACDE\n    msa: alignments/q.a3m\n",
        spec_relative="inputs/system.yaml",
        assets=(
            (root_alignment, "alignments/q.a3m"),
            (consumed_alignment, "inputs/alignments/q.a3m"),
        ),
    )

    _, provenance = adapter.prepare(task, tmp_path / "prepared", "boltz2_predict")

    assert (tmp_path / "prepared/inputs/alignments/q.a3m").read_text() == ">nested\nBBBB\n"
    assert provenance["msa"][0]["consumed"] == "inputs/alignments/q.a3m"
    assert provenance["msa"][0]["sha256"] == hashlib.sha256(b">nested\nBBBB\n").hexdigest()


def test_nested_msa_must_resolve_to_a_supplied_asset(tmp_path: Path) -> None:
    """A root-relative asset that upstream would not read is refused before the CLI."""
    alignment = tmp_path / "q.a3m"
    alignment.write_text(">q\nACDE\n")
    task = _task(
        tmp_path,
        "version: 1\nsequences:\n- protein:\n    id: A\n    sequence: ACDE\n    msa: alignments/q.a3m\n",
        spec_relative="inputs/system.yaml",
        assets=((alignment, "alignments/q.a3m"),),
    )

    with pytest.raises(ValueError, match="not a supplied asset"):
        adapter.prepare(task, tmp_path / "prepared", "boltz2_predict")


def test_prepare_rejects_other_unconfined_file_references(tmp_path: Path) -> None:
    task = _task(
        tmp_path,
        "version: 1\nsequences:\n- protein:\n    id: A\n    sequence: ACDE\n    msa: empty\ntemplates: /etc/passwd\n",
    )
    with pytest.raises(ValueError, match="unconfined file reference"):
        adapter.prepare(task, tmp_path / "prepared", "boltz2_predict")


def test_affinity_requires_ligand_binder_and_protein_target(tmp_path: Path) -> None:
    task = _task(tmp_path, "version: 1\nsequences:\n- protein:\n    id: A\n    sequence: ACDE\n    msa: empty\nproperties:\n- affinity:\n    binder: A\n")
    with pytest.raises(ValueError, match="binder must identify one ligand"):
        adapter.prepare(task, tmp_path / "prepared", "boltz2_affinity")


def test_asset_digests_are_required_and_checked(tmp_path: Path) -> None:
    root, manifest = _assets(tmp_path)
    adapter.verify_assets(root, manifest)
    (root / "ccd.pkl").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="digest mismatch"):
        adapter.verify_assets(root, manifest)


def test_mutated_extracted_molecule_is_refused_despite_unchanged_tar(tmp_path: Path) -> None:
    """Changing one file under mols/ must fail even though mols.tar and checkpoints are byte-identical.

    Upstream reads the extracted library, not the tar, so existence-only acceptance let a
    tampered molecule pass. The tree digest binds the exact bytes it consumes.
    """
    root, manifest = _assets(tmp_path)
    adapter.verify_assets(root, manifest)
    before = {name: (root / name).read_bytes() for name in adapter.ASSETS}
    (root / "mols" / "ligand.pkl").write_bytes(b"mutated-molecule")
    with pytest.raises(ValueError, match="digest mismatch: mols"):
        adapter.verify_assets(root, manifest)
    assert {name: (root / name).read_bytes() for name in adapter.ASSETS} == before


def test_symlink_inside_extracted_assets_is_refused(tmp_path: Path) -> None:
    root, manifest = _assets(tmp_path)
    (root / "mols" / "escape").symlink_to("/etc/passwd")
    with pytest.raises(ValueError, match="symlink"):
        adapter.verify_assets(root, manifest)


def test_missing_mols_digest_is_rejected(tmp_path: Path) -> None:
    root, manifest = _assets(tmp_path)
    # The transport tar is present but its extracted tree digest is not committed.
    lines = [line for line in manifest.read_text().splitlines() if not line.endswith("  mols")]
    manifest.write_text("\n".join(lines) + "\n")
    with pytest.raises(ValueError, match="must cover the four asset files and the extracted mols"):
        adapter.verify_assets(root, manifest)


def test_empty_manifest_still_blocks_execution(tmp_path: Path) -> None:
    root, manifest = _assets(tmp_path)
    # The committed family manifest ships comment-only until assets are provisioned.
    manifest.write_text("# ASSET_BLOCKED: no reviewed digests yet\n")
    with pytest.raises(ValueError, match="ASSET_BLOCKED"):
        adapter.verify_assets(root, manifest)


def test_structure_parser_requires_coordinates_and_identity(tmp_path: Path) -> None:
    valid = tmp_path / "valid.cif"
    valid.write_text(_VALID_CIF)
    assert adapter.structure_atom_count(valid) == 1
    no_identity = tmp_path / "no_identity.cif"
    no_identity.write_text(_VALID_CIF.replace("CA ALA", "CA ?"))
    assert adapter.structure_atom_count(no_identity) == 0
    bad_coords = tmp_path / "bad_coords.cif"
    bad_coords.write_text(_VALID_CIF.replace("1.0 2.0 3.0", "x 2.0 3.0"))
    assert adapter.structure_atom_count(bad_coords) == 0


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("", "empty structure file"),
        ("data_model\n# header only\n", "no parseable atom record"),
    ],
)
def test_predict_refuses_zero_byte_or_header_only_structure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: str, message: str
) -> None:
    """A published structure must contain a real atom, not just a CIF header or empty file."""
    root, manifest = _assets(tmp_path)
    task = _task(tmp_path, "version: 1\nsequences:\n- protein:\n    id: A\n    sequence: ACDE\n    msa: empty\n")
    cli = tmp_path / "fake-boltz"
    cli.write_text("""#!/usr/bin/env python3
import os, sys
from pathlib import Path
args = sys.argv
input_path = Path(args[2])
out = Path(args[args.index('--out_dir') + 1]) / f'boltz_results_{input_path.stem}' / 'predictions' / input_path.stem
out.mkdir(parents=True)
(out / f'{input_path.stem}_model_0.cif').write_text(os.environ['FAKE_CIF'])
(out / f'confidence_{input_path.stem}_model_0.json').write_text('{}')
""")
    cli.chmod(0o755)
    output = tmp_path / "output"
    monkeypatch.setenv("TASK_TYPE", "boltz2_predict")
    monkeypatch.setenv("BOLTZ_ASSET_ROOT", str(root))
    monkeypatch.setenv("BOLTZ_ASSET_MANIFEST", str(manifest))
    monkeypatch.setenv("BOLTZ_CLI", str(cli))
    monkeypatch.setenv("FAKE_CIF", content)
    monkeypatch.setattr(sys, "argv", ["adapter.py", "structure", str(task), str(output)])

    with pytest.raises(ValueError, match=message):
        adapter.main()
    assert not (output / "task_finished").exists()


def test_successful_run_records_verified_assets_and_consumed_msa(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, manifest = _assets(tmp_path)
    alignment = tmp_path / "q.a3m"
    alignment.write_text(">q\nACDE\n")
    task = _task(
        tmp_path,
        "version: 1\nsequences:\n- protein:\n    id: A\n    sequence: ACDE\n    msa: alignments/q.a3m\n",
        spec_relative="inputs/system.yaml",
        assets=((alignment, "inputs/alignments/q.a3m"),),
    )
    cli = tmp_path / "fake-boltz"
    cli.write_text(f"""#!/usr/bin/env python3
import sys
from pathlib import Path
args = sys.argv
input_path = Path(args[2])
assert (input_path.parent / 'alignments/q.a3m').read_text() == '>q\\nACDE\\n'
out = Path(args[args.index('--out_dir') + 1]) / f'boltz_results_{{input_path.stem}}' / 'predictions' / input_path.stem
out.mkdir(parents=True)
(out / f'{{input_path.stem}}_model_0.cif').write_text({_VALID_CIF!r})
(out / f'confidence_{{input_path.stem}}_model_0.json').write_text('{{}}')
""")
    cli.chmod(0o755)
    output = tmp_path / "output"
    monkeypatch.setenv("TASK_TYPE", "boltz2_predict")
    monkeypatch.setenv("BOLTZ_ASSET_ROOT", str(root))
    monkeypatch.setenv("BOLTZ_ASSET_MANIFEST", str(manifest))
    monkeypatch.setenv("BOLTZ_CLI", str(cli))
    monkeypatch.setattr(sys, "argv", ["adapter.py", "structure", str(task), str(output)])

    assert adapter.main() == 0

    provenance = json.loads((output / "boltz2-input-provenance.json").read_text(encoding="utf-8"))
    assert provenance["msa"] == [
        {
            "chain": "A",
            "declared": "alignments/q.a3m",
            "consumed": "inputs/alignments/q.a3m",
            "sha256": hashlib.sha256(b">q\nACDE\n").hexdigest(),
        }
    ]
    upstream = json.loads((output / "boltz2-upstream.json").read_text(encoding="utf-8"))
    assert upstream["asset_status"] == "verified"
    assert (output / "boltz2-model-assets.sha256").is_file()
    assert (output / "task_finished").is_file()


def test_affinity_task_fails_when_upstream_omits_affinity_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, manifest = _assets(tmp_path)
    task = _task(tmp_path, "version: 1\nsequences:\n- protein:\n    id: A\n    sequence: ACDE\n    msa: empty\n- ligand:\n    id: L\n    smiles: C\nproperties:\n- affinity:\n    binder: L\n")
    cli = tmp_path / "fake-boltz"
    cli.write_text("""#!/usr/bin/env python3
import sys
from pathlib import Path
args=sys.argv
input_path=Path(args[2])
out=Path(args[args.index('--out_dir')+1])/f'boltz_results_{input_path.stem}'/'predictions'/input_path.stem
out.mkdir(parents=True)
(out/f'{input_path.stem}_model_0.cif').write_text('''data_model
loop_
_atom_site.label_atom_id
_atom_site.label_comp_id
_atom_site.Cartn_x
_atom_site.Cartn_y
_atom_site.Cartn_z
CA ALA 1.0 2.0 3.0
''')
(out/f'confidence_{input_path.stem}_model_0.json').write_text('{}')
""")
    cli.chmod(0o755)
    monkeypatch.setenv("TASK_TYPE", "boltz2_affinity")
    monkeypatch.setenv("BOLTZ_ASSET_ROOT", str(root))
    monkeypatch.setenv("BOLTZ_ASSET_MANIFEST", str(manifest))
    monkeypatch.setenv("BOLTZ_CLI", str(cli))
    monkeypatch.setattr(sys, "argv", ["adapter.py", "affinity", str(task), str(tmp_path / "output")])
    with pytest.raises(ValueError, match="no affinity JSON"):
        adapter.main()
