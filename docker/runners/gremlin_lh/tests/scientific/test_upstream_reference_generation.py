# Copyright (C) 2024-2026 YaoYinYing
# SPDX-License-Identifier: GPL-3.0-only
"""Guards for the checked-in upstream-notebook transcription.

The scientific receipt is built from ``upstream_notebook_reference.py``, a
literal transcription of the pinned notebook's reusable cells, rather than by
``exec``-ing the notebook.  These tests protect that arrangement:

* the transcription is still the pinned notebook's own source;
* the generator fails closed on a notebook that is not the pinned blob, and does
  so before it parses or uses any cell; and
The notebook identity and transcription retain the recorded scientific provenance.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.scientific_acceptance

ROOT = Path(__file__).resolve().parents[5]
DATA = Path(__file__).resolve().parent / "references"
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
    __import__("jax")
    __import__("optax")
    return _module("gremlin_lh_upstream_transcription", TRANSCRIPTION_PATH)


@pytest.fixture(scope="module")
def generator():
    __import__("jax")
    __import__("optax")
    return _module("gremlin_lh_upstream_generator", GENERATOR_PATH)


def _notebook_path() -> Path:
    configured = os.environ.get("REVOCOMPUTE_GREMLIN_NOTEBOOK")
    path = Path(configured) if configured else _DEFAULT_NOTEBOOK
    if not path.is_file():
        pytest.fail(f"required pinned notebook not available at {path}")
    return path


def test_transcription_is_the_pinned_notebook_source(transcription) -> None:
    """Every transcribed function must be verbatim the pinned cell's source."""
    path = _notebook_path()
    generator = _module("gremlin_lh_identity_guard", GENERATOR_PATH)
    generator.assert_pinned_identity(path)
    notebook = json.loads(path.read_text(encoding="utf-8"))
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


def test_generator_refuses_an_edited_copy_of_the_pinned_notebook(generator, tmp_path: Path) -> None:
    """Editing the pinned notebook changes both the blob and the digest."""
    notebook = _notebook_path()
    edited = tmp_path / "GREMLIN_LH_outline_7.edited.ipynb"
    try:
        edited.write_bytes(notebook.read_bytes() + b"\n")
        with pytest.raises(SystemExit, match="not the pinned GREMLIN_LH notebook"):
            generator.assert_pinned_identity(edited)
    finally:
        edited.unlink(missing_ok=True)
