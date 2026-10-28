# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import hashlib
import json
import os
import pickle
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
FAMILY = ROOT / "docker/runners/mol1"
FIXTURES = ROOT / "tests/data/mol1"
sys.path.insert(0, str(FAMILY))

import estimate_tokens  # noqa: E402
import prepare_input  # noqa: E402

PARAMS = {
    "sample_seeds": "101",
    "num_samples": 1,
    "num_recycles": 1,
    "diffusion_steps": 1,
    "need_atom_confidence": False,
    "msa_mode": "none",
    "template_mode": "none",
    "rna_msa_mode": "none",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _document(name: str) -> list[dict]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _rdkit_stub(value: str, is_file: bool, path: str | None) -> int:
    del is_file, path
    if value != "CCO":
        raise estimate_tokens.TokenEstimateError("unsupported test ligand")
    return 3


def test_estimates_a_protein_by_residue_count() -> None:
    result = estimate_tokens.estimate(_document("minimal.json"), estimate_tokens.CcdAtomCounts(None))
    assert result.total == 20
    assert result.by_job == {"trp_cage": 20}


class _AtomCount:
    def __init__(self, heavy: int) -> None:
        self._heavy = heavy

    def GetAtoms(self):
        return [type("Atom", (), {"GetAtomicNum": lambda self, n=n: 6})() for n in range(self._heavy)]


def test_estimates_ligands_and_ions_by_heavy_atoms() -> None:
    counts = estimate_tokens.CcdAtomCounts(None)
    counts._molecules = {"MG": _AtomCount(1)}
    result = estimate_tokens.estimate(
        _document("ligand_dimer.json"),
        counts,
        rdkit_loader=_rdkit_stub,
    )
    assert result.total == 44


def test_modified_residues_are_counted_conservatively() -> None:
    document = [
        {
            "name": "modified",
            "sequences": [
                {
                    "proteinChain": {
                        "sequence": "NLYIQWLKDGGPSSGRPPPS",
                        "count": 1,
                        "modifications": [
                            {"ptmType": "CCD_HY3", "ptmPosition": 1},
                            {"ptmType": "CCD_P1L", "ptmPosition": 5},
                        ],
                    }
                }
            ],
        }
    ]
    counts = estimate_tokens.CcdAtomCounts(None)
    counts._molecules = {"HY3": _AtomCount(9), "P1L": _AtomCount(24)}
    assert estimate_tokens.estimate(document, counts).total == 51


def test_unknown_ccd_code_fails_closed() -> None:
    document = [{"name": "ion", "sequences": [{"ion": {"ion": "ZZ", "count": 1}}]}]
    with pytest.raises(estimate_tokens.TokenEstimateError):
        estimate_tokens.estimate(document, estimate_tokens.CcdAtomCounts(None))


def _ccd_counts(codes: dict[str, int]) -> estimate_tokens.CcdAtomCounts:
    counts = estimate_tokens.CcdAtomCounts(None)
    counts._molecules = {code: _AtomCount(heavy) for code, heavy in codes.items()}
    return counts


@pytest.mark.parametrize(
    ("entity_type", "sequence", "code", "heavy"),
    [
        ("dnaSequence", "UUUU", "DU", 20),
        ("dnaSequence", "IIII", "DI", 22),
        ("rnaSequence", "IIII", "I", 23),
    ],
)
def test_non_standard_polymer_residues_are_counted_per_atom(
    entity_type: str, sequence: str, code: str, heavy: int
) -> None:
    document = [{"name": "nonstandard", "sequences": [{entity_type: {"sequence": sequence, "count": 1}}]}]
    result = estimate_tokens.estimate(document, _ccd_counts({code: heavy}))
    assert result.total == len(sequence) * heavy


@pytest.mark.parametrize(
    ("entity_type", "residue", "code", "heavy"),
    [
        ("dnaSequence", "U", "DU", 20),
        ("dnaSequence", "I", "DI", 22),
        ("rnaSequence", "I", "I", 23),
    ],
)
def test_non_standard_residues_cannot_pass_the_800_bound(
    tmp_path: Path, monkeypatch, entity_type: str, residue: str, code: str, heavy: int
) -> None:
    document = [{"name": "large", "sequences": [{entity_type: {"sequence": residue * 50, "count": 1}}]}]
    specification = tmp_path / "large.json"
    specification.write_text(json.dumps(document), encoding="utf-8")
    cache = tmp_path / "assets/common/components.cif.rdkit_mol.pkl"
    cache.parent.mkdir(parents=True)
    cache.write_bytes(pickle.dumps({code: _AtomCount(heavy)}))
    manifest = _manifest(tmp_path, specification=specification)

    with pytest.raises(prepare_input.PreparationError, match="exceeds the 800-token"):
        _prepare(tmp_path, manifest, monkeypatch)


class _Conformer:
    def __init__(self, is3d: bool) -> None:
        self._is3d = is3d

    def Is3D(self) -> bool:
        return self._is3d


class _LigandMol:
    def __init__(self, is3d: bool) -> None:
        self._is3d = is3d

    def GetNumConformers(self) -> int:
        return 1

    def GetConformer(self) -> _Conformer:
        return _Conformer(self._is3d)

    def GetAtoms(self) -> list:
        return [type("Atom", (), {"GetAtomicNum": lambda self: 6})()]


def test_ligand_files_without_a_3d_conformer_are_refused(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "ligand.sdf"
    path.write_text("fake", encoding="utf-8")
    rdkit = types.ModuleType("rdkit")
    rdkit.Chem = types.SimpleNamespace(
        MolFromMolFile=lambda *_args, **_kwargs: _LigandMol(False),
        MolFromMol2File=lambda *_args, **_kwargs: _LigandMol(False),
        MolFromPDBFile=lambda *_args, **_kwargs: _LigandMol(False),
        MolFromSmiles=lambda *_args, **_kwargs: None,
    )
    monkeypatch.setitem(sys.modules, "rdkit", rdkit)

    with pytest.raises(estimate_tokens.TokenEstimateError, match="no 3D conformer"):
        estimate_tokens._rdkit_heavy_atoms("FILE_ligand.sdf", True, str(path))


def _manifest(tmp_path: Path, *, specification: Path, assets: list[tuple[Path, str]] | None = None, **params) -> Path:
    manifest = {
        "inputs": {
            "specification": [{"path": str(specification), "relative_path": specification.name}],
            "assets": [
                {"path": str(source), "relative_path": relative} for source, relative in (assets or [])
            ],
        },
        "params": {**PARAMS, **params},
    }
    path = tmp_path / "task.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def _prepare(tmp_path: Path, manifest: Path, monkeypatch, limit: int = 800) -> Path:
    monkeypatch.setenv("MOL1_MAX_TOKENS", str(limit))
    monkeypatch.setenv("MOL_ROOT_DIR", str(tmp_path / "assets"))
    return prepare_input.prepare(manifest, tmp_path / "prepared")


def test_prepare_rewrites_a_supplied_msa_to_a_confined_copy(tmp_path: Path, monkeypatch) -> None:
    manifest = _manifest(
        tmp_path,
        specification=FIXTURES / "supplied_msa.json",
        assets=[(FIXTURES / "msa.a3m", "msa.a3m")],
        msa_mode="supply",
    )
    prepared = _prepare(tmp_path, manifest, monkeypatch)
    document = json.loads(prepared.read_text(encoding="utf-8"))
    reference = document[0]["sequences"][0]["proteinChain"]["unpairedMsaPath"]
    assert Path(reference).is_absolute()
    assert Path(reference).is_file()
    assert Path(reference).parent == prepared.parent
    provenance = json.loads((prepared.parent / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["token_estimate"]["total"] == 12
    assert provenance["assets"][0]["sha256"] == _sha256(FIXTURES / "msa.a3m")


def test_prepare_rejects_a_reference_that_was_not_uploaded(tmp_path: Path, monkeypatch) -> None:
    manifest = _manifest(tmp_path, specification=FIXTURES / "supplied_msa.json", msa_mode="supply")
    with pytest.raises(prepare_input.PreparationError, match="no uploaded asset"):
        _prepare(tmp_path, manifest, monkeypatch)


def test_prepare_rejects_supply_mode_without_a_protein_msa(tmp_path: Path, monkeypatch) -> None:
    manifest = _manifest(tmp_path, specification=FIXTURES / "minimal.json", msa_mode="supply")
    with pytest.raises(prepare_input.PreparationError, match="requires pairedMsaPath"):
        _prepare(tmp_path, manifest, monkeypatch)


def test_prepare_rejects_template_search_without_an_msa_mode(tmp_path: Path, monkeypatch) -> None:
    manifest = _manifest(tmp_path, specification=FIXTURES / "minimal.json", template_mode="search")
    with pytest.raises(prepare_input.PreparationError, match="template search needs an MSA"):
        _prepare(tmp_path, manifest, monkeypatch)


def test_prepare_rejects_a_system_over_the_token_bound(tmp_path: Path, monkeypatch) -> None:
    manifest = _manifest(tmp_path, specification=FIXTURES / "minimal.json")
    with pytest.raises(prepare_input.PreparationError, match="exceeds the 10-token"):
        _prepare(tmp_path, manifest, monkeypatch, limit=10)


def test_prepare_rejects_rna_msa_supply_when_msas_are_off(tmp_path: Path, monkeypatch) -> None:
    manifest = _manifest(tmp_path, specification=FIXTURES / "minimal.json", rna_msa_mode="supply")

    with pytest.raises(prepare_input.PreparationError, match="needs msa_mode 'supply'"):
        _prepare(tmp_path, manifest, monkeypatch)


def test_prepare_rejects_msa_search_when_a_protein_msa_is_supplied(tmp_path: Path, monkeypatch) -> None:
    manifest = _manifest(
        tmp_path,
        specification=FIXTURES / "supplied_msa.json",
        assets=[(FIXTURES / "msa.a3m", "msa.a3m")],
        msa_mode="search",
    )

    with pytest.raises(prepare_input.PreparationError, match="public ColabFold"):
        _prepare(tmp_path, manifest, monkeypatch)


def test_prepare_rejects_msa_search_when_an_rna_msa_is_supplied(tmp_path: Path, monkeypatch) -> None:
    specification = tmp_path / "rna.json"
    specification.write_text(
        json.dumps(
            [
                {
                    "name": "rna",
                    "sequences": [
                        {"rnaSequence": {"sequence": "ACGU", "count": 1, "unpairedMsaPath": "msa.a3m"}}
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )
    manifest = _manifest(
        tmp_path,
        specification=specification,
        assets=[(FIXTURES / "msa.a3m", "msa.a3m")],
        msa_mode="search",
    )

    with pytest.raises(prepare_input.PreparationError, match="cannot preserve a supplied RNA MSA"):
        _prepare(tmp_path, manifest, monkeypatch)


def test_prepare_rejects_a_supplied_name_reserved_for_generated_output(tmp_path: Path, monkeypatch) -> None:
    specification = tmp_path / "reserved.json"
    specification.write_text(
        json.dumps(
            [
                {
                    "name": "job",
                    "sequences": [
                        {"proteinChain": {"sequence": "ACDE", "count": 1, "templatesPath": "normalized-input.json"}}
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )
    asset = tmp_path / "host.json"
    asset.write_text("[]", encoding="utf-8")
    manifest = _manifest(
        tmp_path,
        specification=specification,
        assets=[(asset, "normalized-input.json")],
        template_mode="supply",
    )

    with pytest.raises(prepare_input.PreparationError, match="collides with a Mol-1 generated artifact"):
        _prepare(tmp_path, manifest, monkeypatch)


def test_prepare_rejects_an_over_long_seed_list(tmp_path: Path, monkeypatch) -> None:
    manifest = _manifest(
        tmp_path,
        specification=FIXTURES / "minimal.json",
        sample_seeds=",".join(["1"] * 200),
    )

    with pytest.raises(prepare_input.PreparationError, match="at most 256 characters"):
        _prepare(tmp_path, manifest, monkeypatch)


def test_prepare_rejects_an_out_of_range_seed(tmp_path: Path, monkeypatch) -> None:
    manifest = _manifest(
        tmp_path,
        specification=FIXTURES / "minimal.json",
        sample_seeds=str(prepare_input.MAX_SEED_VALUE + 1),
    )

    with pytest.raises(prepare_input.PreparationError, match="must not exceed"):
        _prepare(tmp_path, manifest, monkeypatch)


def _many_jobs(count: int) -> Path:
    return [{"name": f"job{i}", "sequences": [{"proteinChain": {"sequence": "A", "count": 1}}]} for i in range(count)]


def test_prepare_rejects_more_structures_than_the_projection_limit(tmp_path: Path, monkeypatch) -> None:
    specification = tmp_path / "jobs.json"
    specification.write_text(json.dumps(_many_jobs(21)), encoding="utf-8")
    manifest = _manifest(tmp_path, specification=specification, num_samples=25)

    with pytest.raises(prepare_input.PreparationError, match="500-match"):
        _prepare(tmp_path, manifest, monkeypatch)


def test_prepare_admits_exactly_the_projection_limit(tmp_path: Path, monkeypatch) -> None:
    specification = tmp_path / "jobs.json"
    specification.write_text(json.dumps(_many_jobs(20)), encoding="utf-8")
    manifest = _manifest(tmp_path, specification=specification, num_samples=25)

    assert _prepare(tmp_path, manifest, monkeypatch).is_file()


def test_prepare_rejects_template_search_with_supplied_msas(tmp_path: Path, monkeypatch) -> None:
    manifest = _manifest(
        tmp_path,
        specification=FIXTURES / "supplied_msa.json",
        assets=[(FIXTURES / "msa.a3m", "msa.a3m")],
        msa_mode="supply",
        template_mode="search",
    )

    with pytest.raises(prepare_input.PreparationError, match="needs a searched MSA"):
        _prepare(tmp_path, manifest, monkeypatch)


def test_prepare_confines_file_ligand_references(tmp_path: Path) -> None:
    root = tmp_path / "prepared"
    root.mkdir()
    ligand = root / "ligand.sdf"
    ligand.write_text("fake\n", encoding="utf-8")
    document = [{"name": "job", "sequences": [{"ligand": {"ligand": "FILE_ligand.sdf", "count": 1}}]}]
    prepare_input._resolve_references(document, root, {"ligand.sdf": ligand})
    assert document[0]["sequences"][0]["ligand"]["ligand"] == f"FILE_{ligand}"


def test_verify_rejects_a_search_input_without_msa(tmp_path: Path) -> None:
    final = tmp_path / "final.json"
    final.write_text(json.dumps(_document("minimal.json")), encoding="utf-8")
    with pytest.raises(prepare_input.PreparationError, match="refusing to let prediction search"):
        prepare_input.verify(final, msa_mode="search", template_mode="none", rna_msa_mode="none")


def test_verify_accepts_supplied_paths(tmp_path: Path) -> None:
    msa = tmp_path / "msa.a3m"
    msa.write_text(">a\nAAAA\n>b\nAAAA\n", encoding="utf-8")
    final = tmp_path / "final.json"
    final.write_text(
        json.dumps(
            [
                {
                    "name": "job",
                    "sequences": [{"proteinChain": {"sequence": "AAAA", "count": 1, "unpairedMsaPath": str(msa)}}],
                }
            ]
        ),
        encoding="utf-8",
    )
    prepare_input.verify(final, msa_mode="supply", template_mode="none", rna_msa_mode="none")


def _write_fake_mol(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
Path(os.environ["MOL1_CALL_LOG"]).write_text(json.dumps(args), encoding="utf-8")
input_path = Path(args[args.index("-i") + 1])
out_dir = Path(args[args.index("-o") + 1])
job = json.loads(input_path.read_text(encoding="utf-8"))[0]["name"]
predictions = out_dir / job / "seed_101" / "predictions"
predictions.mkdir(parents=True)
if os.environ.get("MOL1_FAKE_NO_STRUCTURE") != "1":
    (predictions / f"{job}_sample_0.cif").write_text("data_x\\n", encoding="utf-8")
(predictions / f"{job}_summary_confidence_sample_0.json").write_text(
    '{"plddt":90.0,"ptm":0.8,"iptm":0.0,"gpde":1.0,"ranking_score":0.5,"has_clash":false}',
    encoding="utf-8",
)
want_full = "--need_atom_confidence" in args and args[args.index("--need_atom_confidence") + 1] == "true"
if want_full and os.environ.get("MOL1_FAKE_SKIP_FULL") != "1":
    (predictions / f"{job}_full_data_sample_0.json").write_text("{}", encoding="utf-8")
if os.environ.get("MOL1_FAKE_ERR") == "1":
    (out_dir / "ERR").mkdir()
    (out_dir / "ERR" / "error.txt").write_text("upstream failure", encoding="utf-8")
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _asset_tree(tmp_path: Path) -> tuple[Path, Path, Path]:
    assets = tmp_path / "assets"
    files = {
        "checkpoint/mol-1-base.pt": b"checkpoint",
        "common/components.cif": b"ccd",
        "common/components.cif.rdkit_mol.pkl": b"cache",
        "common/clusters-by-entity-40.txt": b"clusters",
        "common/obsolete_release_date.csv": b"dates",
    }
    for relative, content in files.items():
        target = assets / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    model_manifest = tmp_path / "model-assets.sha256"
    model_manifest.write_text(
        "".join(f"{hashlib.sha256(content).hexdigest()}  {relative}\n" for relative, content in files.items()),
        encoding="ascii",
    )
    template_files = {"common/obsolete_to_successor.json": b"successor"}
    for relative, content in template_files.items():
        target = assets / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    search_manifest = tmp_path / "search-assets.sha256"
    search_manifest.write_text(
        "".join(f"{hashlib.sha256(content).hexdigest()}  {relative}\n" for relative, content in template_files.items()),
        encoding="ascii",
    )
    return assets, model_manifest, search_manifest


def _runner_env(tmp_path: Path, manifest: Path, **overrides: str) -> dict[str, str]:
    assets, model_manifest, search_manifest = _asset_tree(tmp_path)
    fake = tmp_path / "mol"
    _write_fake_mol(fake)
    env = {
        **os.environ,
        "TASK_TYPE": "mol1_predict",
        "TASK_MANIFEST": str(manifest),
        "TASK_CONTEXT_SRC": str(ROOT / "docker/runners/common/runtime/task_context.sh"),
        "MOL_CLI": str(fake),
        "MOL1_PREPARE_INPUT": str(FAMILY / "prepare_input.py"),
        "MOL1_UPSTREAM": str(FAMILY / "upstream.json"),
        "MOL1_MODEL_MANIFEST": str(model_manifest),
        "MOL1_SEARCH_MANIFEST": str(search_manifest),
        "MOL_ROOT_DIR": str(assets),
        "MOL1_CHECKPOINT": str(assets / "checkpoint/mol-1-base.pt"),
        "MOL1_MAX_TOKENS": "800",
        "MOL1_CALL_LOG": str(tmp_path / "call.json"),
        "TMPDIR": str(tmp_path),
    }
    env.update(overrides)
    return env


def _run(env: dict[str, str], manifest: Path, output: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(FAMILY / "run.sh"), "-i", str(manifest), "-o", str(output)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_runner_maps_parameters_and_keeps_msa_search_off(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, specification=FIXTURES / "minimal.json")
    env = _runner_env(tmp_path, manifest)
    output = tmp_path / "result"

    completed = _run(env, manifest, output)

    assert completed.returncode == 0, completed.stderr
    args = json.loads((tmp_path / "call.json").read_text(encoding="utf-8"))
    assert args[0] == "pred"
    assert args[args.index("--device") + 1] == "cuda"
    assert args[args.index("--use_msa") + 1] == "false"
    assert args[args.index("--use_template") + 1] == "false"
    assert args[args.index("--use_rna_msa") + 1] == "false"
    assert args[args.index("--seeds") + 1] == "101"
    assert args[args.index("--sample") + 1] == "1"
    assert args[args.index("--cycle") + 1] == "1"
    assert args[args.index("--step") + 1] == "1"
    assert args[args.index("--load_checkpoint_path") + 1].endswith("checkpoint/mol-1-base.pt")
    assert (output / "task_finished").is_file()
    provenance = json.loads((output / "mol1-provenance.json").read_text(encoding="utf-8"))
    assert provenance["delivered"]["structures"] == 1
    assert provenance["parameters"]["msa_mode"] == "none"
    assert (output / "mol1-model-assets.sha256").is_file()
    assert (output / "mol1-search-assets.sha256").is_file()


def test_runner_finds_prepare_input_in_the_runtime_bundle(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, specification=FIXTURES / "minimal.json")
    env = _runner_env(tmp_path, manifest)
    env.pop("MOL1_PREPARE_INPUT")
    env["RUNNER_RUNTIME_ROOT"] = str(FAMILY.parent)
    output = tmp_path / "result"

    completed = _run(env, manifest, output)

    assert completed.returncode == 0, completed.stderr
    assert (output / "normalized_inputs/normalized-input.json").is_file()


def test_runner_uses_supplied_msa_without_search(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        specification=FIXTURES / "supplied_msa.json",
        assets=[(FIXTURES / "msa.a3m", "msa.a3m")],
        msa_mode="supply",
    )
    env = _runner_env(tmp_path, manifest)
    output = tmp_path / "result"

    completed = _run(env, manifest, output)

    assert completed.returncode == 0, completed.stderr
    args = json.loads((tmp_path / "call.json").read_text(encoding="utf-8"))
    assert args[args.index("--use_msa") + 1] == "true"
    assert args[args.index("--use_template") + 1] == "false"
    prepared = json.loads((output / "normalized_inputs/normalized-input.json").read_text(encoding="utf-8"))
    reference = prepared[0]["sequences"][0]["proteinChain"]["unpairedMsaPath"]
    assert Path(reference).is_absolute() and Path(reference).is_file()


def test_runner_refuses_a_missing_checkpoint_before_the_cli(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, specification=FIXTURES / "minimal.json")
    env = _runner_env(tmp_path, manifest, MOL1_CHECKPOINT=str(tmp_path / "missing.pt"))

    completed = _run(env, manifest, tmp_path / "result")

    assert completed.returncode != 0
    assert "checkpoint is missing" in completed.stderr
    assert not (tmp_path / "call.json").exists()


def test_runner_refuses_an_asset_hash_mismatch_before_the_cli(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, specification=FIXTURES / "minimal.json")
    env = _runner_env(tmp_path, manifest)
    (tmp_path / "assets/checkpoint/mol-1-base.pt").write_bytes(b"tampered")

    completed = _run(env, manifest, tmp_path / "result")

    assert completed.returncode != 0
    assert "asset integrity verification failed" in completed.stderr
    assert not (tmp_path / "call.json").exists()


def test_runner_fails_when_no_structure_is_published(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, specification=FIXTURES / "minimal.json")
    env = _runner_env(tmp_path, manifest, MOL1_FAKE_NO_STRUCTURE="1")

    completed = _run(env, manifest, tmp_path / "result")

    assert completed.returncode != 0
    assert "produced no mmCIF structure" in completed.stderr


def test_runner_refuses_supply_mode_without_an_uploaded_msa(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        specification=FIXTURES / "supplied_msa.json",
        assets=[(FIXTURES / "msa.a3m", "other.a3m")],
        msa_mode="supply",
    )
    env = _runner_env(tmp_path, manifest)

    completed = _run(env, manifest, tmp_path / "result")

    assert completed.returncode != 0
    assert "no uploaded asset" in completed.stderr
    assert not (tmp_path / "call.json").exists()


def _template_specification(tmp_path: Path, *, with_template: bool) -> Path:
    chain = {"sequence": "ACDE", "count": 1}
    if with_template:
        chain["templatesPath"] = "complex_templates.a3m"
    path = tmp_path / "template-spec.json"
    path.write_text(json.dumps([{"name": "job", "sequences": [{"proteinChain": chain}]}]), encoding="utf-8")
    return path


def test_runner_uses_a_supplied_template_without_search(tmp_path: Path) -> None:
    templates = tmp_path / "complex_templates.a3m"
    templates.write_text(">hit\nACDE\n", encoding="utf-8")
    manifest = _manifest(
        tmp_path,
        specification=_template_specification(tmp_path, with_template=True),
        assets=[(templates, "complex_templates.a3m")],
        template_mode="supply",
    )
    env = _runner_env(tmp_path, manifest)
    output = tmp_path / "result"

    completed = _run(env, manifest, output)

    assert completed.returncode == 0, completed.stderr
    args = json.loads((tmp_path / "call.json").read_text(encoding="utf-8"))
    assert args[args.index("--use_template") + 1] == "true"
    assert args[args.index("--use_msa") + 1] == "false"
    prepared = json.loads((output / "normalized_inputs/normalized-input.json").read_text(encoding="utf-8"))
    reference = prepared[0]["sequences"][0]["proteinChain"]["templatesPath"]
    assert Path(reference).is_absolute() and Path(reference).is_file()


def test_runner_refuses_template_supply_without_an_uploaded_template(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        specification=_template_specification(tmp_path, with_template=False),
        template_mode="supply",
    )
    env = _runner_env(tmp_path, manifest)

    completed = _run(env, manifest, tmp_path / "result")

    assert completed.returncode != 0
    assert "requires templatesPath" in completed.stderr
    assert not (tmp_path / "call.json").exists()


def test_runner_fails_when_requested_full_confidence_is_missing(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, specification=FIXTURES / "minimal.json", need_atom_confidence=True)
    env = _runner_env(tmp_path, manifest, MOL1_FAKE_SKIP_FULL="1")

    completed = _run(env, manifest, tmp_path / "result")

    assert completed.returncode != 0
    assert "produced no requested full confidence data" in completed.stderr


def test_runner_fails_when_upstream_reports_an_internal_error(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, specification=FIXTURES / "minimal.json")
    env = _runner_env(tmp_path, manifest, MOL1_FAKE_ERR="1")

    completed = _run(env, manifest, tmp_path / "result")

    assert completed.returncode != 0
    assert "internal inference error" in completed.stderr


def test_runner_records_the_submitted_specification_hash(tmp_path: Path) -> None:
    specification = tmp_path / "compact.json"
    specification.write_text(
        '[{"name":"job","sequences":[{"proteinChain":{"sequence":"NLYIQWLKDGGPSSGRPPPS","count":1}}]}]',
        encoding="utf-8",
    )
    manifest = _manifest(tmp_path, specification=specification)
    env = _runner_env(tmp_path, manifest)
    output = tmp_path / "result"

    completed = _run(env, manifest, output)

    assert completed.returncode == 0, completed.stderr
    normalized = output / "normalized_inputs/normalized-input.json"
    provenance = json.loads((output / "mol1-provenance.json").read_text(encoding="utf-8"))
    submitted_sha256 = _sha256(specification)
    assert provenance["prepared_input"]["specification"]["sha256"] == submitted_sha256
    assert submitted_sha256 != _sha256(normalized)
    assert (output / "normalized_inputs/compact.json").read_bytes() == specification.read_bytes()
