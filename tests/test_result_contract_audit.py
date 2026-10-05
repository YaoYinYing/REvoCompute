# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The fleet result-contract audit, and the negatives that prove it bites.

The audit is one static pass over every Task the canonical loader discovers
(``revocompute.result_audit``). It does NOT claim the whole fleet is clean. For
the real fleet this test asserts the three categories the audit reports --
*covered* Tasks whose declarations were evaluated against a declared result tree,
*unaudited* Tasks that require a view source but ship no ``expected_files.yaml``,
and the recorded known defects -- so a passing run cannot be read as "every
Runner passed". Each invariant the audit claims to enforce is then made to fire
on a small deliberately-broken fixture, including the glob-overlap classifier's
provable cases and its deliberately-undecidable ones, so a green fleet run is
evidence that the checks bite, not that they are inert. Nothing here executes a
Runner or claims scientific correctness.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from revocompute.result_audit import DISJOINT, OVERLAP, UNKNOWN, _overlap, audit_fleet, audit_task
from revocompute.result_storyboard import ResultContractError
from revocompute.task_types import isolated_discovery

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
        # Discover into an isolated registry and hand back the Task object. The
        # TaskType is a frozen value that carries its own runtime.root, so it
        # stays valid after the process-global registry is restored -- which is
        # the point: building a synthetic family must not leave it installed for
        # whatever test runs next in this worker.
        with isolated_discovery(str(self.root)) as manager:
            return manager.contributions.resolve("tasks", "fold")


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


def _matrix_glob_view(selector: str, *, required: bool = True) -> str:
    """A matrix view whose source is declared as a ``glob`` selector."""
    return (
        "result_workspace:\n  views:\n"
        "  - plugin: matrix\n    id: m1\n    role: primary\n    title: M\n    description: d\n"
        f"    sources:\n      matrices: [{{glob: '{selector}', required: {str(required).lower()}}}]\n"
        "    mapping:\n      format: csv\n      scale: sequential\n      direction: neutral\n"
    )


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
    """Every finding beyond the recorded defects is either a defect or a coverage gap.

    The fleet is NOT claimed clean. Three categories are asserted separately:
    the covered Tasks whose declarations the audit could evaluate, the unaudited
    Tasks that require a view source but ship no ``expected_files.yaml``, and the
    recorded known defects. The test fails if any finding appears that is not one
    of the recorded defects or the explicit ``result.required_source_undeclared_tree``
    coverage boundary, so the reported state cannot drift into looking greener
    than it is.
    """
    report = audit_fleet(str(RUNNERS), server_dir=str(ROOT))

    unrecorded = [
        finding
        for finding in report.findings
        if (finding.task, finding.code) not in KNOWN_DEFECTS
        and finding.code != "result.required_source_undeclared_tree"
    ]
    assert unrecorded == [], "\n".join(str(finding) for finding in unrecorded)
    for finding in report.findings:
        assert finding.task and finding.task != "-"
        if finding.code in {"result.required_source_unaddressed", "result.required_source_undeclared_tree"}:
            assert finding.view
    # Positive control: the recorded foundry defect is genuinely *present*, not
    # merely allowed. If the audit stopped reporting it, the allowlist above would
    # silently stop covering anything and the fleet would look cleaner than it is.
    assert ("foundry_rfd3_design", "result.required_source_unaddressed") in {
        (finding.task, finding.code) for finding in report.findings
    }


def test_fleet_report_separates_covered_unaudited_and_defective():
    """The three coverage categories are reported, not collapsed into one verdict.

    The audit's claim is bounded: it evaluated the covered Tasks against a
    declared result tree, it could not evaluate the unaudited ones (no tree), and
    it found a concrete defect in two Foundry design Tasks. The report exposes
    all three so it can never be read as "the whole fleet passed".
    """
    report = audit_fleet(str(RUNNERS), server_dir=str(ROOT))

    assert report.covered | report.unaudited == frozenset(report.tasks)
    assert not (report.covered & report.unaudited)
    assert set(report.defective) == {"foundry_rfd3_design", "foundry_rfd3na_design"}
    # A concrete defect means the report is not "ok" even though the only other
    # findings are coverage-boundary notices.
    assert report.ok is False
    assert len(report.covered) == 19 and len(report.unaudited) == 36
    summary = report.as_text().splitlines()[0]
    assert "covered" in summary and "unaudited" in summary and "defect" in summary


def test_fleet_audit_surfaces_the_families_with_no_declared_result_tree():
    """The uncovered set is explicit: required sources that no tree can be checked against.

    The required-source and renderer-kind invariants are statements about a view
    and the ``expected_files.yaml`` identities a family publishes. 48 of the 55
    Tasks declare a required view source; 15 Tasks ship a result tree, so 36
    Tasks require a source that no declared tree can be checked against. This
    test names that gap rather than letting the audit report those Tasks green,
    and it fails if the set changes -- either a family gained a tree (good;
    update the expected set) or a required source appeared where nothing can
    validate it.
    """
    report = audit_fleet(str(RUNNERS), server_dir=str(ROOT))
    undeclared = {
        finding.task for finding in report.findings if finding.code == "result.required_source_undeclared_tree"
    }
    # Tasks whose required view sources have no declared result tree to resolve
    # against. Each entry is a family that ships a ``result_workspace`` with a
    # required source but no ``expected_files.yaml``.
    expected = {
        "autodock_vina", "bioemu", "deeppocket", "diffdock", "dynamicmpnn", "easifa", "esm_1v",
        "esm_if1", "esm_msa", "evosplit_cluster", "fampnn_design", "fampnn_pack", "fampnn_score",
        "freebindcraft", "frodock", "frustrampnn", "geodock", "gnina", "hypermpnn", "lasermpnn",
        "ligandmpnn", "molprobity_validate", "p2rank", "pallatom_generate", "placer", "ppiformer_ddg",
        "ppiformer_embed", "prime", "prime_dms", "proteinmpnn", "pythia_ddg", "rfdiffusion",
        "rfdiffusion2_ligand_binder", "rfdiffusion2_motif_scaffold", "solublempnn", "thermompnn",
    }
    assert undeclared == expected
    # And the tree-bearing families are not in it: those ARE fully audited.
    assert "fpocket" not in undeclared and "gremlin_lh_fit" not in undeclared


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
        tree_yaml=(
            "result:\n  files:\n"
            "    topology:\n      path: topology.pdb\n      cardinality: one\n      required: true\n"
            "      type: structure\n"
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

def test_a_required_source_with_no_declared_tree_is_surfaced_not_passed(tmp_path):
    """A required source a family never gives a logical identity is not green."""
    family = _write_family(tmp_path, view_yaml=_matrix_view("matrix", "matrix.csv"))
    findings = _audit(family, tmp_path)
    assert "result.required_source_undeclared_tree" in _codes(findings)


def test_a_primary_view_overriding_a_declared_provenance_role_is_flagged(tmp_path):
    """A primary view's source must not also be declared provenance/diagnostic."""
    family = _write_family(
        tmp_path,
        view_yaml=_matrix_view("matrix", "matrix.csv"),
        tree_yaml=(
            "result:\n  files:\n"
            "    matrix:\n      path: matrix.csv\n      cardinality: one\n      required: true\n"
            "      type: table\n      role: provenance\n"
        ),
    )
    findings = _audit(family, tmp_path)
    assert "result.primary_view_overrides_declared_role" in _codes(findings)


def test_a_primary_view_over_a_plain_evidence_file_is_not_flagged(tmp_path):
    """The common case -- a primary view over an `evidence` file -- stays clean."""
    family = _write_family(
        tmp_path,
        view_yaml=_matrix_view("matrix", "matrix.csv"),
        tree_yaml=(
            "result:\n  files:\n"
            "    matrix:\n      path: matrix.csv\n      cardinality: one\n      required: true\n"
            "      type: table\n      role: evidence\n"
        ),
    )
    findings = _audit(family, tmp_path)
    assert findings == []


# ---------------------------------------------------------------------------
# The selector/tree overlap classifier (TODO §2 ambiguity invariant)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("left", "left_glob", "right", "right_glob", "expected"),
    [
        # Two different fixed paths cannot be the same file.
        ("a/b.csv", False, "a/c.csv", False, DISJOINT),
        ("a/b.csv", False, "a/b.csv", False, OVERLAP),
        # A literal against a pattern is decided by fnmatch, both directions.
        ("ranked/rank_0.cif", False, "ranked/rank_*.cif", True, OVERLAP),
        ("ranked/other.cif", False, "ranked/rank_*.cif", True, DISJOINT),
        ("modeling/*/*_model.cif", True, "modeling/a/x_model.cif", False, OVERLAP),
        ("modeling/*/*_model.cif", True, "elsewhere/a/x_model.cif", False, DISJOINT),
        # Identical globs intersect.
        ("*/pockets.csv", True, "*/pockets.csv", True, OVERLAP),
        # Different globs with disjoint trailing literals can never share a path.
        ("*.a3m", True, "*.pdb", True, DISJOINT),
        ("*/sample_*.cif", True, "*/sample_*_confidence.json", True, DISJOINT),
        # Different globs whose trailing literals can both be suffixes of one path
        # genuinely intersect (``x.cif.gz`` ends in both ``.gz`` and ``.cif.gz``): a
        # static comparison cannot prove this, so it is UNKNOWN, never a defect.
        ("*.gz", True, "*.cif.gz", True, UNKNOWN),
    ],
)
def test_overlap_classifier_proves_only_what_it_can(left, left_glob, right, right_glob, expected):
    assert _overlap(left, left_glob, right, right_glob) == expected


def test_an_undecidable_glob_pair_never_becomes_an_unaddressed_finding(tmp_path):
    """A required ``*.gz`` over a tree declaring only ``*.cif.gz`` is UNKNOWN, not a defect.

    The two globs do intersect (``model.cif.gz``), but a static comparison cannot
    prove it, so the audit must stay silent rather than report a false defect.
    """
    family = _write_family(
        tmp_path,
        view_yaml=_matrix_glob_view("*.gz"),
        tree_yaml=(
            "result:\n  files:\n"
            "    models:\n      pattern: '*.cif.gz'\n      cardinality: many\n      required: true\n      type: table\n"
        ),
    )
    findings = _audit(family, tmp_path)
    assert "result.required_source_unaddressed" not in _codes(findings)


def test_a_required_glob_disjoint_from_every_declared_pattern_is_reported(tmp_path):
    """A required ``*.pdb`` no entry can match is provably unaddressed."""
    family = _write_family(
        tmp_path,
        view_yaml=_matrix_glob_view("*.pdb"),
        tree_yaml=(
            "result:\n  files:\n"
            "    tables:\n      pattern: '*.csv'\n      cardinality: many\n      required: true\n      type: table\n"
        ),
    )
    findings = _audit(family, tmp_path)
    assert "result.required_source_unaddressed" in _codes(findings)


def test_two_glob_tree_entries_with_disjoint_suffixes_are_not_ambiguous(tmp_path):
    """Two patterns with disjoint trailing literals cannot select one path."""
    family = _write_family(
        tmp_path,
        view_yaml=_matrix_glob_view("*.csv"),
        tree_yaml=(
            "result:\n  files:\n"
            "    tables:\n      pattern: '*.csv'\n      cardinality: many\n      required: true\n"
            "      type: table\n      role: evidence\n"
            "    structures:\n      pattern: '*.pdb'\n      cardinality: many\n      required: true\n"
            "      type: structure\n      role: provenance\n"
        ),
    )
    findings = _audit(family, tmp_path)
    assert "result.ambiguous_logical_ownership" not in _codes(findings)


def test_json_format_cannot_select_a_csv_artifact(tmp_path):
    """A declared json format over a csv selector is a format/source mismatch."""
    family = _write_family(
        tmp_path,
        view_yaml=_matrix_view("matrix", "matrix.csv", mapping="format: json\n      value_path: score\n      scale: sequential\n      direction: neutral"),
    )
    findings = _audit(family, tmp_path)
    assert "result.format_source_mismatch" in _codes(findings)
