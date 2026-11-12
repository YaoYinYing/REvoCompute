# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The server-owned media type live scientific artifacts are served with.

The deployment image has no host MIME database, so the projection must not
depend on ``mimetypes`` for the scientific formats the browser fetches. These
drive the same function the manifest publication and artifact delivery paths
use, so a gateway allowlist can be derived from what is actually served.
"""

from __future__ import annotations

import os

import pytest

from revocompute.media_types import media_type_for_path


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("model.pdb", "chemical/x-pdb"),
        ("model.ent", "chemical/x-pdb"),
        ("model.cif", "chemical/x-cif"),
        ("model.mmcif", "chemical/x-mmcif"),
        ("model.gro", "chemical/x-gro"),
        ("sequence.fasta", "text/x-fasta"),
        ("table.csv", "text/csv"),
        ("run.xtc", "application/octet-stream"),
        ("run.dcd", "application/octet-stream"),
        ("results.zip", "application/zip"),
        ("plot.png", "image/png"),
        ("model.pdb.gz", "application/octet-stream"),
        ("array.npz", "application/octet-stream"),
        ("unrecognized.bin", "application/octet-stream"),
    ],
)
def test_the_projection_is_explicit_for_scientific_and_container_paths(name, expected):
    assert media_type_for_path(name) == expected


def test_publication_projects_the_live_artifact_media_type(tmp_path):
    from revocompute import task_runtime

    (tmp_path / "model.cif").write_bytes(b"data_x\n")
    directory_fd = os.open(tmp_path, os.O_RDONLY)
    try:
        record, reason = task_runtime._publishable_artifact(
            directory_fd, "model.cif", "structure/model.cif", 1024
        )
    finally:
        os.close(directory_fd)

    assert reason is None
    assert record is not None
    assert record["media_type"] == "chemical/x-cif"
