# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The fleet result-contract audit, and the negatives that prove it bites.

The audit is one static pass over every Task the canonical loader discovers
(``revocompute.result_audit``). Two things are asserted here: the real fleet
audits clean apart from the open defects recorded below, and each invariant the
audit claims to enforce actually fires on a small deliberately-broken fixture --
so a green fleet run is evidence that the declarations cohere, not that the
check is inert. Nothing here executes a Runner or claims scientific correctness.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from revocompute.result_audit import audit_fleet, audit_task
from revocompute.result_storyboard import ResultContractError
from revocompute.task_types import discover_plugins, get

ROOT = Path(__file__).resolve().parents[1]
RUNNERS = ROOT / "docker" / "runners"

#: Open, known result-contract defects in the shipped fleet. Each is a real
#: finding the audit is meant to surface; it carries the owning family and the
#: reason it is open, so a new finding cannot hide behind it.
KNOWN_DEFECTS: dict[tuple[str, str], str] = {
    ("foundry_rfd3_design", "result.required_source_unaddressed"): (
        "RFD3 design writes '<name>_model_<n>.cif.gz' (pinned upstream "
        "rfd3/engine.py), but the foundry family's single shared expected_files.yaml "
        "declares only the RF3 fold spelling '*_model.cif' under 'structures', so the "
        "design tasks' primary candidates have no declared logical identity and the "
        "shared storyboard resolves no structures for them. Resolving it means giving "
        "the design tasks their own result tree/storyboard, which is a family "
        "redesign outside this audit."
    ),
    ("foundry_rfd3na_design", "result.required_source_unaddressed"): (
        "Same shared-foundry-tree defect as foundry_rfd3_design."
    ),
}


@dataclass(frozen=True)
class _SyntheticFamily:
    """A minimal on-disk runner family the real loader can discover."""

    root: Path

    def discover(self):
        discover_plugins(str(self.root))
        return get("fold")[0]


def _write_family(root: Path, *, view_yaml: str, tree_yaml: str | None = None, storyboard: str | None = None) -> _SyntheticFamily:
    family = root / "docker" / "runners" / "demo_impl"
    (family / "tasks" / "fold").mkdir(parents=True)
    (family / "plugin.yaml").write_text(
        "api_version: 1\nid: demo\nversion: '1'\n"
        "runtime:\n  definition: demo.def\n  image_artifact: demo.sif\n"
        "tasks: [tasks/fold/task.yaml]\n",
        encoding="utf-8",
    )
    (family / "demo.def").write_text("Bootstrap: docker\nFrom: python:3.12-slim\n", encoding="utf-8")
    (family / "tasks" / "fold" / "task.yaml").write_text(
        "id: fold\ndisplay_name: Fold\nsummary: s\nuse_when: w\ninput_summary: i\noutput_summary: o\n"
        "inputs:\n  sequence: {title: Sequence, type: protein_sequence, cardinality: {min: 1, max: 1}, formats: [fasta]}\n"
        "input_workspace:\n  steps:\n"
        "  - id: material\n    title: m\n    capabilities: [{plugin: files, id: source_files, title: f}]\n"
        "  - id: review\n    title: r\n    capabilities: [{plugin: review, id: submission_review, title: review}]\n"
        f"{view_yaml}",
        encoding="utf-8",
    )
    if tree_yaml is not None:
        (family / "expected_files.yaml").write_text(tree_yaml, encoding="utf-8")
    if storyboard is not None:
        (family / "storyboard").mkdir()
        (family / "storyboard" / "storyboard.yaml").write_text(storyboard, encoding="utf-8")
        (family / "storyboard" / "index.js").write_text("export default { mount() { return {}; } };\n", encoding="utf-8")
    return _SyntheticFamily(root / "docker" / "runners")


def _audit(family: _SyntheticFamily, tmp_path: Path):
    """Audit one synthetic family through the real loaders (rooted at its tmp tree)."""
    return audit_task(family.discover(), server_dir=str(tmp_path))


def _codes(findings) -> set[str]:
    return {finding.code for finding in findings}


def _matrix_view(plugin: str, selector: str, *, required: bool = True, mapping: str = "format: csv\n      scale: sequential\n      direction: neutral") -> str:
    return (
        "result_workspace:\n  views:\n"
        f"  - plugin: {plugin}\n    id: m1\n    role: primary\n    title: M\n    description: d\n"
        f"    sources:\n      matrices: [{{path: {selector}, required: {str(required).lower()}}}]\n"
        f"    mapping:\n      {mapping}\n"
    )


# ---------------------------------------------------------------------------
# The real fleet
# ---------------------------------------------------------------------------


def test_real_fleet_is_discovered_and_audited_end_to_end():
    """The audit runs over every Task the production loader discovers."""
    report = audit_fleet(str(RUNNERS), server_dir=str(ROOT))

    assert len(report.tasks) == len(set(report.tasks)) >= 50
    for representative in ("gremlin_lh_fit", "fpocket", "boltz_predict", "foundry_rfd3_design", "alphafold3"):
        assert representative in report.tasks


def test_real_fleet_reports_no_unrecorded_contract_defect():
    """A green run means every declaration is satisfiable or a recorded defect."""
    report = audit_fleet(str(RUNNERS), server_dir=str(ROOT))

    unrecorded = [
        finding for finding in report.findings if (finding.task, finding.code) not in KNOWN_DEFECTS
    ]
    assert unrecorded == [], "\n".join(str(finding) for finding in unrecorded)
    # A finding must name the owning Task and view so it is actionable.
    for finding in report.findings:
        assert finding.task and finding.task != "-"
        if finding.code == "result.required_source_unaddressed":
            assert finding.view


# ---------------------------------------------------------------------------
# Contract-negative fixtures (TODO §8)
# ---------------------------------------------------------------------------


def test_missing_required_source_is_reported(tmp_path):
    family = _write_family(
        tmp_path,
        view_yaml=_matrix_view("matrix", "absent.csv"),
        tree_yaml="result:\n  files:\n    declared:\n      path: present.csv\n      cardinality: one\n      required: true\n      type: table\n",
    )
    findings = _audit(family, tmp_path)
    assert "result.required_source_unaddressed" in _codes(findings)


def test_incompatible_renderer_and_source_type_is_reported(tmp_path):
    family = _write_family(
        tmp_path,
        view_yaml=(
            "result_workspace:\n  views:\n"
            "  - plugin: entity-table\n    id: m1\n    role: primary\n    title: M\n    description: d\n"
            "    sources:\n      table: [{path: pockets.csv, required: true}]\n"
            "    mapping:\n      entity: candidate\n      key_columns: [pocket]\n"
        ),
        tree_yaml=(
            "result:\n  files:\n    pockets:\n      path: pockets.csv\n"
            "      cardinality: one\n      required: true\n      type: structure\n"
        ),
    )
    findings = _audit(family, tmp_path)
    assert "result.renderer_source_kind_mismatch" in _codes(findings)


def test_format_and_source_extension_mismatch_is_reported(tmp_path):
    family = _write_family(tmp_path, view_yaml=_matrix_view("matrix", "matrix.pdb"))
    findings = _audit(family, tmp_path)
    assert "result.format_source_mismatch" in _codes(findings)


def test_optional_trajectory_topology_is_not_forced_to_the_coordinate_format(tmp_path):
    """A trajectory's declared format governs its coordinates, not its topology."""
    family = _write_family(
        tmp_path,
        view_yaml=(
            "result_workspace:\n  views:\n"
            "  - plugin: trajectory\n    id: m1\n    role: primary\n    title: M\n    description: d\n"
            "    sources:\n      topology: [{path: topology.pdb, required: true}]\n"
            "      coordinates: [{path: samples.xtc, required: false}]\n"
            "    mapping:\n      coordinate_format: xtc\n      frame_unit: sample\n      timestep: 1\n"
            "      association: single\n"
        ),
    )
    findings = _audit(family, tmp_path)
    assert findings == []


def test_ambiguous_logical_ownership_is_reported(tmp_path):
    family = _write_family(
        tmp_path,
        view_yaml=_matrix_view("matrix", "matrix.csv"),
        tree_yaml=(
            "result:\n  files:\n"
            "    broad:\n      pattern: '*.csv'\n      cardinality: many\n      required: true\n"
            "      type: table\n      role: evidence\n"
            "    narrow:\n      path: matrix.csv\n      cardinality: one\n      required: true\n"
            "      type: table\n      role: provenance\n"
        ),
    )
    findings = _audit(family, tmp_path)
    assert "result.ambiguous_logical_ownership" in _codes(findings)


def test_storyboard_requiring_an_optional_logical_file_is_reported(tmp_path):
    family = _write_family(
        tmp_path,
        view_yaml=_matrix_view("matrix", "matrix.csv"),
        tree_yaml=(
            "result:\n  files:\n"
            "    matrix:\n      path: matrix.csv\n      cardinality: one\n      required: false\n      type: table\n"
        ),
        storyboard=(
            "identifier: demo-result\nentrypoint: ./index.js\nrequires: [matrix]\noptional: []\n"
        ),
    )
    findings = _audit(family, tmp_path)
    assert "result.storyboard_requires_optional_file" in _codes(findings)


@pytest.mark.parametrize(
    ("view_yaml", "tree_yaml"),
    [
        # A source selector cannot escape the task result root -- the loader is the
        # owner of selector safety, so it refuses before the audit runs.
        (_matrix_view("matrix", "../escape.csv"), None),
        # A renderer mapping must carry exactly the fields its plugin declares.
        (_matrix_view("matrix", "matrix.csv", mapping="scale: sequential\n      direction: neutral"), None),
    ],
)
def test_loader_refuses_an_unsafe_selector_or_an_incomplete_mapping(tmp_path, view_yaml, tree_yaml):
    family = _write_family(tmp_path, view_yaml=view_yaml, tree_yaml=tree_yaml)
    with pytest.raises(ValueError):
        family.discover()


def test_loader_refuses_a_duplicate_view_id_naming_the_offending_view(tmp_path):
    """A duplicate view identity fails with the id that collided."""
    duplicate = (
        "result_workspace:\n  views:\n"
        "  - plugin: matrix\n    id: m1\n    role: primary\n    title: M\n    description: d\n"
        "    sources:\n      matrices: [{path: matrix.csv, required: true}]\n"
        "    mapping: {format: csv, scale: sequential, direction: neutral}\n"
        "  - plugin: matrix\n    id: m1\n    role: evidence\n    title: M2\n    description: d\n"
        "    sources:\n      matrices: [{path: other.csv, required: true}]\n"
        "    mapping: {format: csv, scale: sequential, direction: neutral}\n"
    )
    family = _write_family(tmp_path, view_yaml=duplicate)
    with pytest.raises(ValueError) as failure:
        family.discover()
    assert "m1" in str(failure.value)


def test_a_storyboard_referencing_an_unknown_logical_file_is_refused(tmp_path):
    family = _write_family(
        tmp_path,
        view_yaml=_matrix_view("matrix", "matrix.csv"),
        tree_yaml=(
            "result:\n  files:\n"
            "    matrix:\n      path: matrix.csv\n      cardinality: one\n      required: true\n      type: table\n"
        ),
        storyboard="identifier: demo-result\nentrypoint: ./index.js\nrequires: [absent]\noptional: []\n",
    )
    task = family.discover()
    with pytest.raises(ResultContractError):
        from revocompute.result_storyboard import storyboard_declaration

        storyboard_declaration(task, str(ROOT), {"matrix"})
