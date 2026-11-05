# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Produce the stage input document the Server writes for a cross-Task reuse role.

Runner contract tests must consume what the Server actually writes, not a
hand-copied document: the role key, the staged layout and the verified file
records are the Server's, so a writer/consumer drift fails in the Runner's own
lane rather than only in a full Task execution.

The output root is a temporary directory instead of a Task workspace and the
container path is redirected to it, which is the only difference from the
production write.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

from revocompute import task_runtime


def write_server_reuse_document(
    tmp_path: Path,
    monkeypatch,
    *,
    stage: str,
    role: str,
    port_path: str,
    relative: tuple[str, ...],
    content: bytes,
):
    """Write the Server's reuse document and return ``(document, staged file)``."""
    source_root = tmp_path / "server-source"
    source_file = source_root.joinpath(*relative)
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_bytes(content)
    stage_inputs_dir = tmp_path / "server-stage-inputs"
    digest = hashlib.sha256(content).hexdigest()
    monkeypatch.setattr(task_runtime, "STAGE_INPUTS_CONTAINER_DIR", str(stage_inputs_dir))
    monkeypatch.setattr(
        task_runtime, "_storage",
        lambda: SimpleNamespace(get_output_root=lambda _task: str(source_root)),
    )
    monkeypatch.setattr(
        task_runtime, "resolve_reuse_source",
        lambda *_args, **_kwargs: {
            "source_task": "d" * 32, "stage": stage, "port": "features", "attempt": 2,
            "port_path": port_path, "artifact_digest": digest, "task": {},
            "files": [{"path": "/".join(relative), "size": len(content), "sha256": digest}],
        },
    )
    node = SimpleNamespace(id="model", inputs={"features": f"reuse:{role}"})
    refusal = task_runtime._materialize_stage_inputs(
        str(stage_inputs_dir), str(source_root), node, {}, {},
        reuse={role: {"role": role, "type": "artifact"}},
        consumer_owner_id=0, consumer_task_type="contract-test",
    )
    assert refusal is None, refusal
    document = stage_inputs_dir / task_runtime.STAGE_INPUTS_DOCUMENT_NAME
    return document, stage_inputs_dir.joinpath(role, *relative)
