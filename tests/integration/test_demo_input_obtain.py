# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""One obtain serves one declared demo, through the built application.

The demo catalog and the fixture route are one protocol: a Task declares demos,
the catalog publishes them, and the obtain route serves the bytes a declaration
already validated. This case holds the boundary between those two reads - the
catalog validates a whole manifest, while an obtain resolves only the demo it
names - so the traffic one form fill costs stays proportional to the example the
reader chose rather than to every example the Task declares.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import shutil

import yaml

from conftest import _load_pssm_module

SYNTHETIC_TASK = "cpu_runner"
TASK_DIR = "tasks/predict"
FIXTURE_NAME = "records.fasta"
FIXTURE_SOURCE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "runners" / SYNTHETIC_TASK / "tasks" / "predict"
    / "demo" / "files" / FIXTURE_NAME
)


def _declaration(digest: str) -> dict:
    return {
        "demos": [
            {
                "id": "records",
                "title": "Records preset",
                "purpose": "Load a working preset.",
                "source": {"name": "Synthetic corpus", "url": "https://example.invalid/synthetic"},
                "license": {"id": "cc0-1.0", "name": "CC0 1.0", "url": "https://example.invalid/cc0"},
                "inputs": {
                    "sequence": [
                        {"path": f"files/{FIXTURE_NAME}", "sha256": digest, "media_type": "text/x-fasta"}
                    ]
                },
                "parameters": {"iter": 100},
            }
        ]
    }


def test_serving_one_fixture_resolves_only_the_demo_that_declares_it(monkeypatch, tmp_path):
    """One obtain reads one declaration, while the catalog still reads them all.

    A Task may declare several demos; a reader loading one of them issues one
    request per fixture it binds. Resolving every other demo on each of those
    requests would re-read and re-hash a whole catalog per asset, so the obtain
    route resolves exactly the demo the request names. The catalog keeps its own,
    stricter posture: a declaration in which *any* demo is invalid is still not
    published at all, so nothing reaches a reader from a manifest that has not
    been validated whole.

    Deleting the sibling fixture is what makes the difference observable: it
    cannot be read or hashed, so a route that touched it could not answer.
    """
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    import revocompute.routes  # noqa: F401  (installs the runner registry snapshot)
    task_type, _runner = module.task_runtime._get_task_type(SYNTHETIC_TASK)
    object.__setattr__(task_type, "task_dir", TASK_DIR)
    root = Path(task_type.runtime.root) / TASK_DIR / "demo"
    (root / "files").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURE_SOURCE, root / "files" / FIXTURE_NAME)
    digest = hashlib.sha256((root / "files" / FIXTURE_NAME).read_bytes()).hexdigest()
    served = _declaration(digest)["demos"][0]
    absent = {**served, "id": "absent", "inputs": {"sequence": [{**served["inputs"]["sequence"][0], "path": "files/absent.fasta"}]}}
    (root / "demos.yaml").write_text(yaml.safe_dump({"demos": [served, absent]}, sort_keys=False), encoding="utf-8")
    client = module.app.test_client()
    asset = f"/compute/api/types/{SYNTHETIC_TASK}/demos/{served['id']}/files/files/{FIXTURE_NAME}"

    # One invalid demo is an operator problem for the whole manifest, so the
    # catalog refuses to publish it - and the named demo is still resolvable.
    assert client.get(f"/compute/api/types/{SYNTHETIC_TASK}/demos").status_code == 503
    assert client.get(asset).status_code == 200
    # Membership is still an allowlist: the request cannot name what the demo does
    # not declare, and the bytes served are re-verified against the digest the
    # declaration carries rather than trusted because the path matched.
    assert client.get(f"/compute/api/types/{SYNTHETIC_TASK}/demos/{served['id']}/files/files/absent.fasta").status_code == 404
    (root / "files" / FIXTURE_NAME).write_bytes(b">tampered\nACDE\n")
    assert client.get(asset).status_code == 404


