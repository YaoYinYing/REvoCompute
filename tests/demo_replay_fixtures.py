# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""A synthetic replay bundle for demo-profile tests.

The demo profile installs an index, validates each bundle through the canonical
loader, and serves whatever that bundle captured. The machinery is the same for
every Task, so demo tests stand in a synthetic result with the canonical shape
instead of naming a production Runner. Replaying authentic captured results
stays in the fleet boundary.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

from frontend_fixtures import (
    OutputCheckSpec,
    ResultArtifactSpec,
    ResultFixture,
    build_result_manifest,
    capture_replay_bundle,
    view_entry,
    write_bundle,
)

#: A stand-in Task type with the canonical shape but no delivery family.
SYNTHETIC_TASK_TYPE = "sequence_demo"
SYNTHETIC_TASK_ID = "0123456789abcdef0123456789abcdef"
#: An artifact the bundle carries and the demo serves byte for byte.
CAPTURED_ARTIFACT = "results/summary.txt"
#: A table artifact whose numeric column also backs the array projection route.
TABLE_ARTIFACT = "results/scores.csv"
#: An optional artifact the bundle excludes because it exceeds the payload budget.
EXCLUDED_ARTIFACT = "execution/status.log"

_SUMMARY = "residue pairs above threshold: 2\n"
_SCORES = "name,score\nalpha,1.5\nbeta,2.5\n"
_STATUS_LOG = "ready\n" * 128


def write_synthetic_replay_bundle(destination: Path) -> Path:
    """Capture one synthetic replay bundle at *destination*."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    fixture = ResultFixture(
        name="demo_replay",
        task_type=SYNTHETIC_TASK_TYPE,
        output_check=OutputCheckSpec(
            state="passed",
            checks=(
                (("view_id", "recorded_summary"), ("source", "data"), ("required", True),
                 ("status", "passed"), ("matched", 1)),
            ),
        ),
        artifacts=(
            ResultArtifactSpec(CAPTURED_ARTIFACT, role="primary", capability="text", body=_SUMMARY),
            ResultArtifactSpec(TABLE_ARTIFACT, role="artifact", capability="table", body=_SCORES),
            ResultArtifactSpec(
                EXCLUDED_ARTIFACT, role="diagnostic", capability="download_only",
                media_type="text/plain", body=_STATUS_LOG,
            ),
        ),
        views=(
            view_entry(
                "scalar-summary", "recorded_summary", "Recorded summary",
                {"data": [CAPTURED_ARTIFACT]}, role="primary",
            ),
        ),
        logical_files=(("summary", (CAPTURED_ARTIFACT,)),),
    )
    manifest = build_result_manifest(fixture, task_id=SYNTHETIC_TASK_ID)
    specs = {spec.path: spec for spec in fixture.artifacts}
    artifacts = {artifact["path"]: artifact for artifact in manifest["artifacts"]}
    with tempfile.TemporaryDirectory(prefix="synthetic-replay-") as build:
        result_root = Path(build) / "result"
        for path, artifact in artifacts.items():
            body = (specs[path].body or "").encode("utf-8")
            target = result_root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
            artifact["size"] = len(body)
            artifact["sha256"] = hashlib.sha256(body).hexdigest()
        for file_id, entries in manifest["result"]["files"].items():
            paths = fixture.logical_file_paths()[file_id]
            for index, entry in enumerate(entries):
                source = artifacts[paths[index]]
                entry.update(path=paths[index], size=source["size"], sha256=source["sha256"])
        manifest["total_size"] = sum(artifact["size"] for artifact in artifacts.values())
        (result_root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        bundle = capture_replay_bundle(
            task_id=SYNTHETIC_TASK_ID,
            result_root=result_root,
            max_payload_bytes=max(len(_SUMMARY), len(_SCORES)) + 8,
        )
    return write_bundle(destination, bundle)
