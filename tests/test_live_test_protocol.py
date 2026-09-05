# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
from pathlib import Path

import pytest

from revocompute.live_tests import (
    LiveTestConfigurationError,
    atomic_write_json,
    canonical_digest,
    load_live_test_plan,
    receipt_matches,
    resolve_fixture,
    sanitized_mapping,
)


SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "properties": {"iterations": {"type": "integer", "minimum": 1}},
}


def _tree(tmp_path: Path) -> tuple[Path, Path]:
    fixture = tmp_path / "tests" / "data" / "demo" / "tiny.fasta"
    fixture.parent.mkdir(parents=True)
    fixture.write_text(">tiny\nACDE\n", encoding="utf-8")
    family = tmp_path / "docker" / "runners" / "demo"
    family.mkdir(parents=True)
    declaration = family / "test.yaml"
    declaration.write_text(
        "version: 1\ncollections:\n  smoke:\n    cases:\n"
        "      - id: minimal\n        task: predict\n"
        "        input:\n          files: [tests/data/demo/tiny.fasta]\n"
        "        parameters: {iterations: 1}\n",
        encoding="utf-8",
    )
    return fixture, declaration


def test_load_live_test_plan_supports_collections_and_real_task_schema(tmp_path):
    _fixture, declaration = _tree(tmp_path)
    plan = load_live_test_plan(declaration, repo_root=tmp_path, task_schemas={"predict": SCHEMA})

    assert plan.select("smoke")[0].id == "minimal"
    assert plan.select("smoke", task="other") == ()
    assert plan.digest.startswith("sha256:")


def test_live_test_parameter_validation_rejects_unknown_parameter(tmp_path):
    _fixture, declaration = _tree(tmp_path)
    declaration.write_text(declaration.read_text().replace("iterations: 1", "unknown: 1"), encoding="utf-8")
    with pytest.raises(LiveTestConfigurationError, match="parameters are invalid"):
        load_live_test_plan(declaration, repo_root=tmp_path, task_schemas={"predict": SCHEMA})


@pytest.mark.parametrize("path", ["/etc/passwd", "../tiny.fasta", "tests/data/../outside"])
def test_fixture_resolution_rejects_absolute_and_traversal(tmp_path, path):
    (tmp_path / "tests" / "data").mkdir(parents=True)
    with pytest.raises(LiveTestConfigurationError):
        resolve_fixture(tmp_path, path)


def test_fixture_resolution_rejects_symlink_escape(tmp_path):
    outside = tmp_path / "outside.fasta"
    outside.write_text(">x\nACDE\n", encoding="utf-8")
    link = tmp_path / "tests" / "data" / "demo" / "link.fasta"
    link.parent.mkdir(parents=True)
    link.symlink_to(outside)
    with pytest.raises(LiveTestConfigurationError, match="escapes"):
        resolve_fixture(tmp_path, "tests/data/demo/link.fasta")


def test_receipt_is_invalidated_by_each_identity_and_required_case():
    identity = {
        "sif_sha256": "sha256:sif",
        "build_provenance_digest": "sha256:build",
        "test_definition_digest": "sha256:test",
        "configuration_digest": "sha256:config",
    }
    receipt = {**identity, "passed": True, "cases": [{"case_id": "minimal", "passed": True}]}
    assert receipt_matches(receipt, **identity, required_case_ids={"minimal"})
    for key in identity:
        changed = dict(identity)
        changed[key] += "-changed"
        assert not receipt_matches(receipt, **changed, required_case_ids={"minimal"})
    assert not receipt_matches(receipt, **identity, required_case_ids={"minimal", "missing"})


def test_sanitized_configuration_digest_excludes_secret_values():
    public = sanitized_mapping({"mount": "/db", "API_TOKEN": "do-not-persist", "nested": {"password": "x", "cpus": 4}})
    assert public == {"mount": "/db", "nested": {"cpus": 4}}
    assert canonical_digest(public) == canonical_digest({"nested": {"cpus": 4}, "mount": "/db"})


def test_atomic_report_write_is_machine_readable(tmp_path):
    path = tmp_path / "reports" / "result.json"
    atomic_write_json(path, {"passed": True})
    assert json.loads(path.read_text(encoding="utf-8")) == {"passed": True}
