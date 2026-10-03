# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Capability-oriented ResultManifest fixtures.

One entry per frontend rendering class: text and logs, a table, a matrix, an
alignment, single and ranked structures, a trajectory, a metric series, a large
download-only artifact, a nested artifact tree, a partial result, a failed result
with diagnostics, and archive pending/ready. Each uses only the ``ResultView``
plugins and ``Artifact`` capabilities that ``openapi.json`` declares, and every
built manifest is validated against the canonical schema.
"""

from __future__ import annotations

from typing import Any, Mapping

from .builders import validate_payload, view_entry
from .models import (
    ArchiveSpec,
    OutputCheckSpec,
    ResultArtifactSpec,
    ResultFixture,
    StoryboardSpec,
    WorkerView,
)

# A minimal single-residue PDB record: the smallest file the structure viewer
# will load, so a structure fixture needs no checked-in asset. The confidence
# variant differs only in the B-factor the viewer colours by.
PDB_BODY = "ATOM      1  CA  ALA A  10      11.000  12.000  13.000  1.00 88.00           C\n"
PDB_BODY_LOW_CONFIDENCE = "ATOM      1  CA  ALA A  10      11.000  12.000  13.000  1.00 51.00           C\n"


def _text_artifacts() -> tuple[ResultArtifactSpec, ...]:
    return (
        _artifact("results/summary.txt", role="primary", capability="text", body="alignment rows: 42\n"),
        _artifact("execution/slurm.stdout", role="diagnostic", capability="text", body="worker ready\ntask accepted\n"),
        _artifact("execution/task_finished", role="diagnostic", capability="text", size=0, body=""),
        _artifact("citations.bib", role="provenance", capability="download_only", media_type="text/x-bibtex"),
    )


def _artifact(path: str, capability: str, *, role: str = "artifact", **overrides: Any) -> ResultArtifactSpec:
    """Declare one manifest artifact by path and rendering capability."""
    return ResultArtifactSpec(path, role=role, capability=capability, **overrides)


def _structure_artifact(path: str, *, role: str = "primary", confidence: bool = True) -> ResultArtifactSpec:
    return _artifact(
        path,
        "molecular_structure",
        role=role,
        media_type="chemical/x-pdb",
        body=PDB_BODY,
        confidence_encoding="plddt_bfactor" if confidence else None,
    )


RESULT_FIXTURES: dict[str, ResultFixture] = {}


def _register(fixture: ResultFixture) -> ResultFixture:
    RESULT_FIXTURES[fixture.name] = fixture
    return fixture


minimal_success = _register(
    ResultFixture(
        name="minimal_success",
        outcome=None,
        run_inputs=(("sequence", "sample.fasta", "fasta"),),
    )
)

text_log = _register(
    ResultFixture(
        name="text_log",
        artifacts=_text_artifacts(),
        views=(view_entry("evidence-bundle", "logs", "Run logs", {"files": ["results/summary.txt"]}, role="primary"),),
        run_inputs=(("sequence", "sample.fasta", "fasta"),),
        run_parameters=(("iterations", "Iterations", 2, ""),),
    )
)

table = _register(
    ResultFixture(
        name="table",
        artifacts=(
            _artifact(
                "tables/pairs.tsv",
                role="primary",
                capability="table",
                media_type="text/tab-separated-values",
                columns=("alignment_i", "alignment_j", "apc_score"),
                table=(("10", "11", "0.42"), ("12", "18", "0.31")),
            ),
            _artifact("execution/slurm.stdout", role="diagnostic", capability="text"),
        ),
        views=(view_entry("entity-table", "ranked_pairs", "Ranked residue pairs", {"table": ["tables/pairs.tsv"]}),),
        run_inputs=(("alignment", "alignment.a3m", "a3m"),),
    )
)

matrix = _register(
    ResultFixture(
        name="matrix",
        artifacts=(
            _artifact(
                "couplings/apc_scores.csv",
                role="primary",
                capability="table",
                media_type="text/csv",
                projection=(0.0, 0.4, 0.4, 0.0),
            ),
            _artifact("execution/slurm.stdout", role="diagnostic", capability="text"),
        ),
        views=(
            view_entry(
                "matrix",
                "apc_couplings",
                "APC-corrected coupling strengths",
                {"matrices": ["couplings/apc_scores.csv"]},
                format="csv",
                scale="diverging",
                x_label="Alignment position",
                y_label="Alignment position",
            ),
        ),
        run_inputs=(("alignment", "alignment.a3m", "a3m"),),
    )
)

alignment = _register(
    ResultFixture(
        name="alignment",
        artifacts=(
            _artifact(
                "alignment/filtered_alignment.a3m", role="primary",
                capability="text",
                media_type="text/x-a3m",
                body=">seq1\nACDEFG\n>seq2\nACD-FG\n",
            ),
            _artifact("execution/slurm.stdout", role="diagnostic", capability="text"),
        ),
        views=(view_entry("alignment", "filtered_alignment", "Filtered alignment", {"alignment": ["alignment/filtered_alignment.a3m"]}, format="a3m", numbering="alignment"),),
        run_inputs=(("alignment", "alignment.a3m", "a3m"),),
    )
)

structure = _register(
    ResultFixture(
        name="structure",
        artifacts=(
            _structure_artifact("structures/model_0.pdb"),
            _artifact("execution/slurm.stdout", role="diagnostic", capability="text"),
        ),
        views=(view_entry("structure", "predicted_structure", "Predicted structure", {"candidates": ["structures/model_0.pdb"]}, confidence_encoding="plddt_bfactor"),),
        output_check=OutputCheckSpec(state="passed", checks=((("view_id", "predicted_structure"), ("source", "candidates"), ("required", True), ("status", "passed"), ("matched", 1)),)),
        run_inputs=(("sequence", "query.fasta", "fasta"),),
    )
)

multi_structure = _register(
    ResultFixture(
        name="multi_structure",
        artifacts=(
            _structure_artifact("predictions/model_0.cif", role="evidence"),
            _structure_artifact("predictions/model_1.cif", role="evidence"),
            _structure_artifact("predictions/model_2.cif", role="evidence"),
            _artifact(
                "predictions/confidence.json", role="evidence",
                capability="unknown",
                media_type="application/json",
            ),
        ),
        views=(
            view_entry(
                "candidate-collection",
                "predicted_structures",
                "Confidence-ranked structures",
                {"candidates": ["predictions/model_0.cif", "predictions/model_1.cif", "predictions/model_2.cif"]},
                confidence_encoding="plddt_bfactor",
            ),
        ),
        output_check=OutputCheckSpec(state="passed", checks=((("view_id", "predicted_structures"), ("source", "candidates"), ("required", True), ("status", "passed"), ("matched", 3)),)),
        run_inputs=(("sequence", "query.fasta", "fasta"),),
    )
)

large_download_only = _register(
    ResultFixture(
        name="large_download_only",
        artifacts=(
            _artifact(
                "models/weights.bin", role="primary",
                capability="download_only",
                size=536_870_912,
                media_type="application/octet-stream",
            ),
            _artifact("execution/slurm.stdout", role="diagnostic", capability="text"),
        ),
        run_inputs=(("sequence", "query.fasta", "fasta"),),
    )
)

nested_tree = _register(
    ResultFixture(
        name="nested_tree",
        artifacts=(
            _artifact(
                "models/run_0001/result.pdb", role="primary",
                capability="molecular_structure",
                media_type="chemical/x-pdb",
                body=PDB_BODY,
            ),
            _artifact("models/run_0001/metrics/scores.csv", role="evidence", capability="table", media_type="text/csv"),
            _artifact(
                "models/run_0002/result.pdb", role="evidence",
                capability="molecular_structure",
                media_type="chemical/x-pdb",
                body=PDB_BODY_LOW_CONFIDENCE,
            ),
            _artifact("execution/logs/run.log", role="diagnostic", capability="text"),
            _artifact("execution/logs/run.err", role="diagnostic", capability="text"),
            _artifact("citations.bib", role="provenance", capability="download_only"),
        ),
        run_inputs=(("structure", "target.pdb", "pdb"),),
    )
)

partial = _register(
    ResultFixture(
        name="partial",
        artifacts=(
            _artifact(
                "models/run_0001/result.pdb", role="primary",
                capability="molecular_structure",
                media_type="chemical/x-pdb",
                body=PDB_BODY,
            ),
            _artifact(
                "execution/slurm.stderr", role="diagnostic",
                capability="text",
                body="run_0002 exceeded its time limit\n",
            ),
        ),
        views=(view_entry("candidate-collection", "predicted_structures", "Predicted structures", {"candidates": ["models/run_0001/result.pdb"]}),),
        output_check=OutputCheckSpec(
            state="failed",
            checks=((("view_id", "predicted_structures"), ("source", "candidates"), ("required", True), ("status", "passed"), ("matched", 1)),),
            problems=("run_0002 did not publish a model",),
        ),
        work_items=(
            WorkerView("run_0001", "SUCCEEDED", output_path="models/run_0001/result.pdb"),
            WorkerView("run_0002", "FAILED_RUNTIME", attempts=2, error="run_0002 exceeded its time limit"),
        ),
        run_inputs=(("structure", "target.pdb", "pdb"),),
    )
)

failed_diagnostics = _register(
    ResultFixture(
        name="failed_diagnostics",
        status="failed",
        outcome="FAILED",
        error="Runner stopped before publishing a model",
        artifacts=(
            _artifact("task_failed.txt", role="diagnostic", capability="text", body="REvoDesign example task failed\n"),
            _artifact(
                "execution/slurm.stderr", role="diagnostic",
                capability="text",
                body="container exited with status 137\n",
            ),
        ),
        output_check=OutputCheckSpec(state="not_assessed"),
        run_inputs=(("structure", "target.pdb", "pdb"),),
    )
)

trajectory = _register(
    ResultFixture(
        name="trajectory",
        artifacts=(
            _artifact(
                "topology.pdb", role="primary",
                capability="molecular_structure",
                media_type="chemical/x-pdb",
                body=PDB_BODY,
            ),
            _artifact(
                "samples.xtc", role="evidence",
                capability="download_only",
                size=2_097_152,
                media_type="application/octet-stream",
            ),
            _artifact("execution/slurm.stdout", role="diagnostic", capability="text"),
        ),
        views=(
            view_entry(
                "trajectory",
                "conformational_ensemble",
                "Sampled conformational ensemble",
                {"topology": ["topology.pdb"], "coordinates": ["samples.xtc"]},
                role="evidence",
            ),
        ),
        run_inputs=(("structure", "target.pdb", "pdb"),),
    )
)

metric_series = _register(
    ResultFixture(
        name="metric_series",
        artifacts=(
            _artifact(
                "confidence_0.json", role="primary",
                capability="download_only",
                media_type="application/json",
                projection=(88.0, 91.0, 74.0),
            ),
            _artifact("execution/slurm.stdout", role="diagnostic", capability="text"),
        ),
        views=(
            view_entry(
                "metric-series",
                "residue_confidence",
                "Per-residue model confidence",
                {"series": ["confidence_0.json"]},
                role="evidence",
                format="json",
                value_path="confidenceScore",
            ),
        ),
        run_inputs=(("sequence", "query.fasta", "fasta"),),
    )
)

archive_pending = _register(
    ResultFixture(
        name="archive_pending",
        artifacts=(ResultArtifactSpec("results/summary.txt", role="primary", capability="text"),),
        archive=ArchiveSpec(),
    )
)

archive_ready = _register(
    ResultFixture(
        name="archive_ready",
        artifacts=(ResultArtifactSpec("results/summary.txt", role="primary", capability="text"),),
        archive=ArchiveSpec(requested=True),
    )
)

storyboard = _register(
    ResultFixture(
        name="storyboard",
        artifacts=(
            _artifact(
                "models/run_0001/result.pdb", role="primary",
                capability="molecular_structure",
                media_type="chemical/x-pdb",
                body=PDB_BODY,
            ),
            _artifact(
                "models/run_0002/result.pdb", role="evidence",
                capability="molecular_structure",
                media_type="chemical/x-pdb",
                body=PDB_BODY_LOW_CONFIDENCE,
            ),
        ),
        logical_files=(("predicted_structures", ("models/run_0001/result.pdb", "models/run_0002/result.pdb")),),
        storyboard=StoryboardSpec(
            identifier="example-ensemble",
            entrypoint="storyboard.js",
            requires=("predicted_structures",),
            module_body="export default { mount(host) { host.dataset.fixtureStoryboard = 'mounted'; return { destroy() {} }; } };\n",
        ),
        run_inputs=(("structure", "target.pdb", "pdb"),),
    )
)


def result_fixture(name: str) -> ResultFixture:
    """Return one named capability-oriented result fixture."""
    try:
        fixture = RESULT_FIXTURES[name]
    except KeyError:
        raise KeyError(f"Unknown result fixture {name!r}; available: {sorted(RESULT_FIXTURES)}") from None
    return fixture


def validate_manifest(manifest: Mapping[str, Any]) -> None:
    validate_payload("ResultManifest", manifest)


__all__ = ["RESULT_FIXTURES", "result_fixture", "validate_manifest"]
