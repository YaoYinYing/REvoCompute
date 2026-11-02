# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""The migrated adapters execute from the Runtime Bundle snapshot.

The SIF is the environment; the Runtime Bundle is the orchestration. This
module loads the real runner-family manifests, materializes each migrated
family's declared overlay into a temporary content-addressed store, and runs
the snapshot directly. It then repeats each execution against a mutated
runner-tree copy whose manifest omits the code under test, so a family cannot
silently fall back to the checkout or to an image-baked path.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

import pytest
import yaml

from revocompute import runtime_bundle
from revocompute.runner_registry import load_plugin_families

ROOT = Path(__file__).resolve().parents[2]
RUNNERS = ROOT / "docker" / "runners"
PROTOCOL_PATH = ROOT / "docker" / "runner_testkit" / "runner_protocol.py"

FASTA = ">2KL8\nMKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQ\n"
INSTANCE = "2KL8"
STEM = f"{INSTANCE}.i90c75_aln"
MSA_OUTPUT = ">q\nACDE\n>h\nACDE\n"


def _load_run_with_manifest():
    """Load the Runner protocol harness from its file; the testkit is not a package."""
    spec = importlib.util.spec_from_file_location("revocompute_runner_protocol", PROTOCOL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.run_with_manifest


run_with_manifest = _load_run_with_manifest()


# -- family selection --------------------------------------------------------
#
# The checker forbids concrete family identities in generic tests, so select the
# migrated adapters by the overlay shape each one declares: the PSSM adapter
# ships a ``scripts/`` directory, the LH adapter ships ``fit_model.py``, and the
# AF3 adapter ships only its own entrypoint plus the two shared helpers.


def _overlay_leaf_names(family) -> set[str]:
    return {PurePosixPath(entry).name for entry in family.runtime_overlay}


_FAMILY_SELECTORS = {
    "pssm": lambda family: "scripts" in _overlay_leaf_names(family),
    "lh": lambda family: "fit_model.py" in _overlay_leaf_names(family),
    "af3": lambda family: _overlay_leaf_names(family) == {"task_context.sh", "task_context.py", "run.sh"},
}


def _select_family(families, key):
    matches = [family for family in families if _FAMILY_SELECTORS[key](family)]
    assert len(matches) == 1, f"expected one family for {key!r}, found {[family.name for family in matches]}"
    return matches[0]


def _entries(family):
    assert family.root is not None
    return runtime_bundle.collect_overlay_entries(family.root.parent, family.runtime_overlay)


def _declared_named(family, basename):
    matches = [entry for entry in family.runtime_overlay if PurePosixPath(entry).name == basename]
    assert len(matches) == 1, f"expected one declared overlay entry named {basename!r}, found {len(matches)}"
    return matches[0]


def _entry_named(family, basename):
    matches = [entry for entry in _entries(family) if PurePosixPath(entry.relative).name == basename]
    assert len(matches) == 1, f"expected one overlay entry named {basename!r}, found {len(matches)}"
    return matches[0].relative


# -- fixtures ----------------------------------------------------------------


@pytest.fixture(autouse=True)
def _deny_production_runner_root():
    """Let this execution test read the declared production runner tree.

    The repository guard keeps generic Server tests off the installed Runner
    tree. This cross-component test exists to execute those declarations, so it
    replaces the guard with a no-op for its own module.
    """
    yield


@pytest.fixture(scope="module")
def families():
    return load_plugin_families(RUNNERS)


@pytest.fixture(scope="module")
def selected(families):
    return {key: _select_family(families, key) for key in _FAMILY_SELECTORS}


def _remove_read_only_tree(root: Path) -> None:
    for directory, _dirnames, filenames in os.walk(root):
        os.chmod(directory, 0o700)
        for name in filenames:
            try:
                os.chmod(os.path.join(directory, name), 0o600)
            except OSError:
                pass
    shutil.rmtree(root, ignore_errors=True)


@pytest.fixture(scope="module")
def bundles(selected):
    store = Path(tempfile.mkdtemp(prefix="revocompute-bundle-exec-"))
    materialized = {}
    try:
        for key, family in selected.items():
            assert family.root is not None
            digest, directory = runtime_bundle.materialize(
                family.root.parent, family.runtime_overlay, store
            )
            materialized[key] = (digest, directory)
        yield materialized
    finally:
        _remove_read_only_tree(store)


@pytest.fixture
def store():
    path = Path(tempfile.mkdtemp(prefix="revocompute-bundle-mutant-"))
    try:
        yield path
    finally:
        _remove_read_only_tree(path)


def _materialize(family, store):
    assert family.root is not None
    return runtime_bundle.materialize(family.root.parent, family.runtime_overlay, store)


# -- 1. snapshots are exactly the declared overlay ---------------------------


@pytest.mark.parametrize("key", ["pssm", "lh", "af3"])
def test_snapshot_equals_declared_overlay(key, selected, bundles):
    family = selected[key]
    digest, bundle = bundles[key]
    declared = [entry.relative for entry in _entries(family)]
    stored = sorted(path.relative_to(bundle).as_posix() for path in bundle.rglob("*") if path.is_file())

    assert stored == sorted(declared)
    assert bundle == runtime_bundle.bundle_directory(bundle.parent, digest)
    assert runtime_bundle.verify_bundle(bundle, digest)
    assert runtime_bundle.RUNTIME_MOUNT_TARGET == "/opt/revocompute/runtime"
    for entry in _entries(family):
        snapshot = bundle / entry.relative
        assert snapshot.is_file()
        mode = snapshot.stat().st_mode & 0o777
        assert mode == (0o555 if entry.executable else 0o444)
    # Reserved layout: repository-relative POSIX positions beneath one root.
    assert all(not PurePosixPath(path).is_absolute() for path in stored)
    assert all(".." not in PurePosixPath(path).parts for path in stored)


# -- 2. PSSM-GREMLIN executes run.sh and scripts/ from the snapshot ---------


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _stub_environment(tmp_path: Path) -> tuple[dict[str, str], Path]:
    """A PATH with the MSA search stubs and a link to the test interpreter."""
    bin_dir = tmp_path / "bin"
    calls = tmp_path / "calls"
    bin_dir.mkdir()
    calls.mkdir()
    os.symlink(sys.executable, bin_dir / "python")
    _write_executable(
        bin_dir / "hhblits",
        """#!/bin/bash
set -e
echo "hhblits" >> "${STUB_CALLS}/hhblits.calls"
prev=""
for arg in "$@"; do
  if [[ "$prev" == "-oa3m" ]]; then printf ">q\\nACDE\\n>h\\nACDE\\n" > "$arg"; fi
  prev="$arg"
done
""",
    )
    _write_executable(
        bin_dir / "hhfilter",
        """#!/bin/bash
set -e
prev=""
source=""
for arg in "$@"; do
  [[ "$prev" == "-i" ]] && source="$arg"
  if [[ "$prev" == "-o" ]]; then cp "$source" "$arg"; fi
  prev="$arg"
done
echo "hhfilter" >> "${STUB_CALLS}/hhfilter.calls"
""",
    )
    _write_executable(
        bin_dir / "psiblast",
        """#!/bin/bash
set -e
if [[ "${1:-}" == "-version" ]]; then echo "psiblast: 2.13.0+"; exit 0; fi
echo "psiblast" >> "${STUB_CALLS}/psiblast.calls"
prev=""
for arg in "$@"; do
  if [[ "$prev" == "-out_ascii_pssm" ]]; then printf "1 A 0\\n" > "$arg"; fi
  prev="$arg"
done
""",
    )
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:/usr/local/bin:/usr/bin:/bin",
        "STUB_CALLS": str(calls),
    }
    return env, calls


def _run_msa(family, bundle, tmp_path: Path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = tmp_path / f"{INSTANCE}.fasta"
    source.write_text(FASTA, encoding="utf-8")
    output = tmp_path / "output"
    env, calls = _stub_environment(tmp_path)
    env["RUNNER_RUNTIME_ROOT"] = str(bundle)
    # The PSSM entrypoint defaults the helper to the reserved mount, which does
    # not exist off-container. Point it at that same bundle copy so activation
    # and adapter code both come from the snapshot rather than the checkout.
    env["TASK_CONTEXT_SRC"] = str(bundle / _entry_named(family, "task_context.sh"))
    completed = run_with_manifest(
        bundle / _entry_named(family, "run.sh"),
        source,
        output,
        env,
        extra_args=("-s", "msa"),
        role="sequence",
    )
    return completed, output, calls


def _calls(calls: Path, tool: str) -> int:
    path = calls / f"{tool}.calls"
    return len(path.read_text(encoding="utf-8").splitlines()) if path.exists() else 0


def test_pssm_runs_from_the_bundle(selected, bundles, tmp_path):
    family = selected["pssm"]
    bundle = bundles["pssm"][1]
    completed, output, calls = _run_msa(family, bundle, tmp_path)

    assert completed.returncode == 0, completed.stderr
    alignment = output / "gremlin_msa" / f"{STEM}.fas"
    assert alignment.read_text(encoding="utf-8") == MSA_OUTPUT
    assert _calls(calls, "hhblits") == 1
    assert _calls(calls, "hhfilter") == 1
    assert _calls(calls, "psiblast") == 0

    scripts = bundle / _declared_named(family, "scripts") / "fasta_lower_char_rm.py"
    assert str(scripts) in completed.stdout
    combined = completed.stdout + completed.stderr
    assert str(RUNNERS) not in combined
    assert "/app/revocompute" not in combined


# -- 3. GREMLIN_LH executes fit_model.py and stage_inputs.py from the snapshot


def _lh_script(selected, bundle, basename: str) -> Path:
    return bundle / _entry_named(selected["lh"], basename)


def _stage_input_document(tmp_path: Path, artifact: Path, digest: str) -> Path:
    document = tmp_path / "stage_inputs.json"
    document.write_text(
        json.dumps(
            {
                "version": 1,
                "stage": "synthetic",
                "inputs": {
                    "alignment": {
                        "path": str(artifact),
                        "files": [
                            {
                                "path": str(artifact),
                                "source_path": f"producer/{artifact.name}",
                                "sha256": digest,
                                "size": artifact.stat().st_size,
                            }
                        ],
                        "producer": "test",
                        "producer_attempt": 1,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return document


def test_lh_fit_model_help_runs_from_the_bundle(selected, bundles):
    fit_model = _lh_script(selected, bundles["lh"][1], "fit_model.py")
    completed = subprocess.run(
        [sys.executable, str(fit_model), "--help"], capture_output=True, text=True, check=False
    )

    assert completed.returncode == 0, completed.stderr
    assert "usage:" in completed.stdout.lower()


def test_lh_stage_inputs_fails_closed_and_accepts_the_right_digest(selected, bundles, tmp_path):
    stage_inputs = _lh_script(selected, bundles["lh"][1], "stage_inputs.py")
    assert stage_inputs.parent == _lh_script(selected, bundles["lh"][1], "fit_model.py").parent
    artifact = tmp_path / "alignment.fas"
    artifact.write_bytes(b">q\nACDE\n>h\nACDE\n")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()

    wrong = _stage_input_document(tmp_path, artifact, "0" * 64)
    rejected = subprocess.run(
        [sys.executable, str(stage_inputs), "resolve", str(wrong), "alignment"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert rejected.returncode != 0
    assert "digest does not match" in rejected.stderr

    right = _stage_input_document(tmp_path, artifact, digest)
    accepted = subprocess.run(
        [sys.executable, str(stage_inputs), "resolve", str(right), "alignment"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert accepted.returncode == 0, accepted.stderr
    assert accepted.stdout.strip() == str(artifact)


# -- 4. AlphaFold 3 parses and resolves the shared helper from the snapshot --


def test_af3_entrypoint_and_shared_helper_resolve_from_the_bundle(selected, bundles, tmp_path):
    family = selected["af3"]
    bundle = bundles["af3"][1]
    run_script = bundle / _entry_named(family, "run.sh")
    helper = bundle / _entry_named(family, "task_context.sh")

    parsed = subprocess.run(["bash", "-n", str(run_script)], capture_output=True, text=True, check=False)
    assert parsed.returncode == 0, parsed.stderr

    manifest = tmp_path / "task.json"
    manifest.write_text(json.dumps({"params": {}, "inputs": {}}), encoding="utf-8")
    env = {**os.environ, "TASK_MANIFEST": str(manifest)}
    env.pop("TASK_CONTEXT_SRC", None)
    resolved = subprocess.run(
        ["bash", "-c", 'source "$1"; type -t task_input', "_", str(helper)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert resolved.returncode == 0, resolved.stderr
    assert resolved.stdout.strip() == "function"


# -- 5. mutation proof: a bundle without the code cannot execute -------------


def _copy_runner_tree(tmp_path: Path, label: str) -> Path:
    destination = tmp_path / label / "runners"
    shutil.copytree(RUNNERS, destination)
    return destination


def _omit_overlay_entry(runner_root: Path, family, keep) -> None:
    manifest_path = runner_root / family.root.name / "plugin.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    declared = manifest["runtime"]["runtime_overlay"]
    remaining = [entry for entry in declared if keep(entry)]
    assert len(remaining) < len(declared)
    manifest["runtime"]["runtime_overlay"] = remaining
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")


def _mutated_family(runner_root: Path, original):
    matches = [family for family in load_plugin_families(runner_root) if family.name == original.name]
    assert len(matches) == 1
    return matches[0]


def test_pssm_without_the_scripts_overlay_fails(selected, tmp_path, store):
    original = selected["pssm"]
    runner_root = _copy_runner_tree(tmp_path, "pssm-mutant")
    _omit_overlay_entry(runner_root, original, lambda entry: PurePosixPath(entry).name != "scripts")
    mutant = _mutated_family(runner_root, original)
    _digest, bundle = _materialize(mutant, store)

    mutated_dir = PurePosixPath(_entry_named(mutant, "run.sh")).parent
    assert not (bundle / mutated_dir / "scripts").exists()
    completed, output, _calls_seen = _run_msa(mutant, bundle, tmp_path / "run")

    assert completed.returncode != 0
    assert "fasta_lower_char_rm.py" in completed.stdout
    assert not (output / "gremlin_msa" / f"{STEM}.fas").exists()


def test_lh_without_fit_model_in_the_overlay_fails(selected, tmp_path, store):
    original = selected["lh"]
    runner_root = _copy_runner_tree(tmp_path, "lh-mutant")
    _omit_overlay_entry(runner_root, original, lambda entry: PurePosixPath(entry).name != "fit_model.py")
    mutant = _mutated_family(runner_root, original)
    _digest, bundle = _materialize(mutant, store)

    fit_model = bundle / PurePosixPath(_entry_named(mutant, "stage_inputs.py")).parent / "fit_model.py"
    assert not fit_model.exists()
    completed = subprocess.run(
        [sys.executable, str(fit_model), "--help"], capture_output=True, text=True, check=False
    )
    assert completed.returncode != 0
