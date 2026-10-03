# Copyright (C) 2024-2026 YaoYinYing
# SPDX-License-Identifier: GPL-3.0-only
"""Guards for the checked-in upstream-notebook transcription.

The scientific receipt is built from ``upstream_notebook_reference.py``, a
literal transcription of the pinned notebook's reusable cells, rather than by
``exec``-ing the notebook.  These tests protect that arrangement:

* the transcription is still the pinned notebook's own source;
* the generator fails closed on a notebook that is not the pinned blob, and does
  so before it parses or uses any cell; and
* the generator and the transcription contain no dynamic-execution call.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "tests" / "data" / "gremlin_lh"
TRANSCRIPTION_PATH = DATA / "upstream_notebook_reference.py"
GENERATOR_PATH = DATA / "generate_upstream_reference.py"

#: The pinned notebook is maintainer-supplied and is not committed.  Point
#: ``REVOCOMPUTE_GREMLIN_NOTEBOOK`` at it, or rely on the recorded intake path.
_DEFAULT_NOTEBOOK = Path.home() / "revocompute-handoff-309" / "references" / "GREMLIN_LH_outline_7.ipynb"


def _module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def transcription():
    pytest.importorskip("jax")
    pytest.importorskip("optax")
    return _module("gremlin_lh_upstream_transcription", TRANSCRIPTION_PATH)


@pytest.fixture(scope="module")
def generator():
    pytest.importorskip("jax")
    pytest.importorskip("optax")
    return _module("gremlin_lh_upstream_generator", GENERATOR_PATH)


def _notebook_path() -> Path:
    configured = os.environ.get("REVOCOMPUTE_GREMLIN_NOTEBOOK")
    path = Path(configured) if configured else _DEFAULT_NOTEBOOK
    if not path.is_file():
        pytest.skip(f"pinned notebook not available at {path}")
    return path


def test_transcription_is_the_pinned_notebook_source(transcription) -> None:
    """Every transcribed function must be verbatim the pinned cell's source."""
    notebook = json.loads(_notebook_path().read_text(encoding="utf-8"))
    cells = ["".join(cell.get("source", [])) for cell in notebook["cells"]]
    try:
        transcription.assert_matches_pinned_notebook(cells)
    except SystemExit as exc:  # the guard refuses; surface it as a test failure
        pytest.fail(str(exc))


def test_generator_refuses_an_unpinned_notebook(generator, tmp_path: Path) -> None:
    """A notebook that is neither pinned nor even parseable is refused first."""
    bogus = tmp_path / "not_the_pinned_notebook.ipynb"
    bogus.write_bytes(b"not a notebook at all")
    with pytest.raises(SystemExit, match="not the pinned GREMLIN_LH notebook"):
        generator.build_receipt(bogus, ROOT / "tests/data/msa/2KL8.i90c75_aln.a3m")


def test_generator_refuses_an_edited_copy_of_the_pinned_notebook(generator) -> None:
    """Editing the pinned notebook changes both the blob and the digest."""
    notebook = _notebook_path()
    edited = notebook.parent / "GREMLIN_LH_outline_7.edited.ipynb"
    try:
        edited.write_bytes(notebook.read_bytes() + b"\n")
        with pytest.raises(SystemExit, match="not the pinned GREMLIN_LH notebook"):
            generator.assert_pinned_identity(edited)
    finally:
        edited.unlink(missing_ok=True)


def test_generator_and_transcription_have_no_dynamic_execution() -> None:
    """No eval/exec/compile( call may exist in the reference path (project ban)."""
    pattern = re.compile(r"\b(eval|exec|compile)\s*\(")
    for path in (GENERATOR_PATH, TRANSCRIPTION_PATH):
        offenders = [line for line in path.read_text(encoding="utf-8").splitlines() if pattern.search(line)]
        assert not offenders, (path.name, offenders)
