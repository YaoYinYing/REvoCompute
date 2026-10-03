# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Runner scenarios: the frontend-visible state of one Runner workflow.

A scenario is an immutable value. Each ``with_*`` method returns a new scenario,
so a test states the state it wants once and nothing is shared between tests.
Lifecycle state is a pure function of the poll count: the router counts status
polls and asks the scenario for that step, so no fixture sleeps and no test
depends on wall-clock timing.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import unquote

from . import builders, results
from .auth import USER_AUTH, Session
from .models import (
    DEFAULT_TASK_ID,
    AccessState,
    ArchiveSpec,
    Citation,
    InputRole,
    LifecycleSpec,
    OutputCheckSpec,
    ParameterSpec,
    PreflightSpec,
    ReadinessState,
    ResultArtifactSpec,
    ResultFixture,
    RunnerDefinition,
    WorkspaceCapability,
    WorkspacePluginAsset,
    WorkspaceStep,
    WorkflowStage,
)

CONTROLLED_RUNNER_NAME = "sequence_demo"
CONTROLLED_ACCESS_POLICY = "academic-only"

# Media types for fixture artifact paths whose inline preview the browser fetches.
_MEDIA_TYPE_BY_SUFFIX = {
    ".txt": "text/plain",
    ".log": "text/plain",
    ".stdout": "text/plain",
    ".err": "text/plain",
    ".a3m": "text/x-a3m",
    ".fasta": "text/x-fasta",
    ".fa": "text/x-fasta",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".json": "application/json",
    ".pdb": "chemical/x-pdb",
    ".cif": "chemical/x-cif",
    ".mmcif": "chemical/x-mmcif",
    ".png": "image/png",
    ".zip": "application/zip",
}


@dataclass(frozen=True, slots=True)
class RunnerScenario:
    """One Runner, one readiness state, one lifecycle, one result fixture."""

    runner: RunnerDefinition
    session: Session = USER_AUTH
    readiness_state: ReadinessState = field(default_factory=ReadinessState)
    preflight: PreflightSpec = field(default_factory=PreflightSpec)
    lifecycle: LifecycleSpec = field(default_factory=LifecycleSpec)
    result: ResultFixture | None = None
    archive: ArchiveSpec = field(default_factory=ArchiveSpec)
    task_id: str = DEFAULT_TASK_ID
    extra_runners: tuple[RunnerDefinition, ...] = ()
    access_policies: tuple[AccessState, ...] = ()
    task_summaries: tuple[Mapping[str, Any], ...] = ()
    reject_password_update: bool = False

    # -- immutable mutation -------------------------------------------------

    def with_session(self, session: Session) -> RunnerScenario:
        return replace(self, session=session)

    def with_role(self, role: str) -> RunnerScenario:
        return replace(self, session=self.session.with_role(role))

    def with_readiness(self, state: ReadinessState | str, **overrides: object) -> RunnerScenario:
        if isinstance(state, str):
            state = ReadinessState.with_status(ReadinessState(), state, **overrides)  # type: ignore[arg-type]
        elif overrides:
            state = replace(state, **overrides)  # type: ignore[arg-type]
        return replace(self, readiness_state=state)

    def with_preflight(self, spec: PreflightSpec | str) -> RunnerScenario:
        if isinstance(spec, str):
            spec = builders.PREFLIGHT_FIXTURES[spec]
        return replace(self, preflight=spec)

    def with_lifecycle(self, *statuses: str) -> RunnerScenario:
        return replace(self, lifecycle=LifecycleSpec(statuses=tuple(statuses)))

    def with_result(self, fixture: ResultFixture | str | None) -> RunnerScenario:
        if isinstance(fixture, str):
            fixture = results.result_fixture(fixture)
        return replace(self, result=fixture)

    def with_archive(self, archive: ArchiveSpec) -> RunnerScenario:
        return replace(self, archive=archive)

    def with_access(self, access: AccessState) -> RunnerScenario:
        return replace(self, runner=replace(self.runner, access=access))

    def with_catalog(self, definitions: Iterable[RunnerDefinition]) -> RunnerScenario:
        extras = tuple(definition for definition in definitions if definition.name != self.runner.name)
        return replace(self, extra_runners=extras)

    def with_access_policies(self, policies: Iterable[AccessState]) -> RunnerScenario:
        return replace(self, access_policies=tuple(policies))

    def with_task_summaries(self, summaries: Iterable[Mapping[str, Any]]) -> RunnerScenario:
        return replace(self, task_summaries=tuple(summaries))

    def with_password_rejection(self) -> RunnerScenario:
        return replace(self, reject_password_update=True)

    # -- catalog and Runner projections ------------------------------------

    def runners(self) -> list[RunnerDefinition]:
        return [self.runner, *self.extra_runners]

    def catalog(self) -> dict[str, Any]:
        return builders.build_catalog(self.runners())

    def detail(self) -> dict[str, Any]:
        return builders.build_detail(self.runner)

    def parameter_schema(self) -> dict[str, Any]:
        return builders.build_parameter_schema(self.runner)

    def runner_or_none(self, name: str) -> RunnerDefinition | None:
        return next((definition for definition in self.runners() if definition.name == name), None)

    def runner_for_task(self, task_id: str) -> RunnerDefinition | None:
        return self.runner if task_id == self.task_id else None

    @property
    def task_type(self) -> str:
        return self.runner.name

    @property
    def access_policy_id(self) -> str:
        return self.runner.access.policy_id

    # -- readiness and preflight -------------------------------------------

    def readiness(self) -> ReadinessState:
        return self.readiness_state

    def preflight_response(self, definition: RunnerDefinition) -> tuple[dict[str, Any], int]:
        return builders.build_preflight(definition, self.preflight)

    # -- lifecycle ----------------------------------------------------------
    #
    # The router owns the poll counter; the scenario maps a poll index to a
    # state. Keeping the mapping pure is what makes the lifecycle deterministic.

    def submit_status(self) -> str:
        return self.lifecycle.initial

    def status_at(self, poll_index: int) -> str:
        return self.lifecycle.at(poll_index)

    def result_available_at(self, poll_index: int, task_id: str) -> bool:
        """A finalized manifest exists only once a terminal state is reached."""
        return self.has_result() and task_id == self.task_id and LifecycleSpec.is_terminal(self.lifecycle.at(poll_index))

    def status_error(self, status: str) -> str | None:
        """Message the running endpoint reports for a terminal-but-empty task."""
        if status != "failed":
            return None
        if self.result is None:
            return "Runner stopped before publishing outputs"
        return self.result.error

    def task_status_payload(self, task_id: str, poll_index: int) -> tuple[dict[str, Any], bool, str]:
        status = self.status_at(poll_index)
        terminal = LifecycleSpec.is_terminal(status)
        result_available = terminal and self.result_available_at(poll_index, task_id)
        payload = builders.build_task_status(
            task_id,
            self.runner,
            status,
            result_available=result_available,
            error=self.status_error(status) if terminal else None,
        )
        return payload, terminal, status

    def summary_payloads(self) -> list[dict[str, Any]]:
        if self.task_summaries:
            return [dict(summary) for summary in self.task_summaries]
        return [
            builders.build_task_summary(
                self.task_id,
                self.runner,
                status=self.lifecycle.statuses[-1],
                result_available=self.has_result(),
                archive_ready=self.archive.requested,
                owner=self.session.username if self.session.role == "admin" else None,
                error=self.result.error if self.result else None,
            )
        ]

    # -- results ------------------------------------------------------------

    def result_manifest(self) -> dict[str, Any] | None:
        if self.result is None:
            return None
        fixture = self.result if self.result.archive is not None else replace(self.result, archive=self.archive)
        return builders.build_result_manifest(fixture, self.runner, task_id=self.task_id)

    def result_for(self, task_id: str) -> dict[str, Any] | None:
        return self.result_manifest() if task_id == self.task_id else None

    def has_result(self) -> bool:
        return self.result is not None

    def _artifact(self, path: str) -> ResultArtifactSpec | None:
        if self.result is None:
            return None
        decoded = unquote(path)
        return next((item for item in self.result.artifacts if item.path == decoded), None)

    def artifact_body(self, path: str) -> tuple[bytes, str] | None:
        artifact = self._artifact(path)
        if artifact is None:
            return None
        body = (artifact.body or "").encode("utf-8")
        media_type = artifact.media_type or _MEDIA_TYPE_BY_SUFFIX.get(
            Path(unquote(path)).suffix.lower(), "application/octet-stream",
        )
        return body, media_type

    def table_page(self, path: str) -> dict[str, Any] | None:
        artifact = self._artifact(path)
        if artifact is None or artifact.capability != "table" or not artifact.table:
            return None
        return builders.build_table_page(artifact.columns, artifact.table)

    def projection(self, path: str, *, kind: str = "numeric") -> dict[str, Any] | None:
        artifact = self._artifact(path)
        if artifact is None or not artifact.projection:
            return None
        if kind == "categorical":
            return builders.build_categorical_projection([str(value) for value in artifact.projection])
        return builders.build_matrix_projection([float(value) for value in artifact.projection])

    def storyboard_module(self, task_id: str, asset: str) -> str | None:
        fixture = self.result
        if task_id != self.task_id or fixture is None or fixture.storyboard is None:
            return None
        if asset != fixture.storyboard.entrypoint:
            return None
        return fixture.storyboard.module_body or "export default { mount() { return {}; } };\n"

    def archive_response(self, task_id: str) -> dict[str, Any]:
        if self.archive.requested:
            return {"status": "ready", "download_url": f"/compute/api/download/{task_id}"}
        return {"status": "building", "job_id": "fixture-archive-job", "md5sum": task_id}

    # -- access and static assets ------------------------------------------

    def policy_states(self) -> list[AccessState]:
        if self.access_policies:
            return list(self.access_policies)
        return [self.runner.access] if self.runner.access.restricted else []

    def workspace_plugin(self, plugin_id: str) -> WorkspacePluginAsset | None:
        return next((asset for asset in self.runner.workspace_plugins if asset.plugin_id == plugin_id), None)

    def static_assets(self) -> dict[str, str]:
        """Same-origin asset bodies the shell fetches outside the API."""
        return {}


# ---------------------------------------------------------------------------
# Capability-oriented scenarios
# ---------------------------------------------------------------------------

SEQUENCE_ROLE = InputRole(
    id="sequence",
    title="Protein sequence",
    logical_type="protein_sequence",
    formats=("fasta",),
    extensions=(".fasta", ".fa"),
    description="One FASTA record.",
)


def _sequence_workspace() -> tuple[WorkspaceStep, ...]:
    """The canonical three-step grammar: source, settings, review."""
    return (
        WorkspaceStep(
            id="input",
            title="Provide input",
            description="Choose one source.",
            capabilities=(
                WorkspaceCapability("files", "source_files", "Files", "Upload FASTA."),
                WorkspaceCapability("sequence", "sequence_editor", "Sequence", "Paste FASTA.", (("role", "sequence"),)),
            ),
        ),
        WorkspaceStep(
            id="settings",
            title="Settings",
            description="Configure the run.",
            capabilities=(WorkspaceCapability("parameters", "parameters", "Parameters", "Method controls."),),
        ),
        WorkspaceStep(
            id="review",
            title="Review",
            description="Check the snapshot.",
            capabilities=(WorkspaceCapability("review", "review", "Review", "Submission summary.", (("show_paths", True),)),),
        ),
    )


def controlled_runner(
    *,
    name: str = CONTROLLED_RUNNER_NAME,
    display_name: str = "Sequence demo",
    category: str = "evolution",
    category_label: str = "Evolution",
    summary: str = "Summarize one protein sequence.",
) -> RunnerDefinition:
    """A CPU-only Runner with the canonical sequence-input workspace."""
    return RunnerDefinition(
        name=name,
        display_name=display_name,
        category=category,
        category_label=category_label,
        summary=summary,
        use_when="Use this for a small sequence summary.",
        input_summary="One protein sequence.",
        output_summary="A text summary.",
        runtime_family="example",
        inputs=(SEQUENCE_ROLE,),
        parameters=(ParameterSpec.integer("iterations", title="Iterations", default=2, has_default=True, minimum=1, maximum=4),),
        workspace_steps=_sequence_workspace(),
    )


def controlled_scenario(**overrides: Any) -> RunnerScenario:
    """The canonical CPU scenario the browser acceptance suite drives."""
    return replace(RunnerScenario(runner=controlled_runner()), **overrides)


def runner_scenario(
    runner: RunnerDefinition,
    *,
    session: Session | None = None,
    lifecycle: Sequence[str] = ("finished",),
    result: ResultFixture | str | None = None,
    preflight: PreflightSpec | str = "valid",
    readiness: ReadinessState | str = "READY",
) -> RunnerScenario:
    """Build a scenario for an arbitrary Runner definition or capability."""
    scenario = RunnerScenario(
        runner=runner,
        session=session or USER_AUTH,
        preflight=builders.PREFLIGHT_FIXTURES[preflight] if isinstance(preflight, str) else preflight,
        lifecycle=LifecycleSpec(statuses=tuple(lifecycle)),
    )
    scenario = scenario.with_readiness(readiness)
    if result is not None:
        scenario = scenario.with_result(result)
    return scenario


def pssm_gremlin_scenario() -> RunnerScenario:
    """A realistic PSSM-GREMLIN frontend scenario for the enabled 309 Runner.

    The artifact set mirrors what the Runner's declared result workspace
    publishes — alignment, ranked pairs, couplings, logs, downloads — but the
    bytes are fixtures. This exercises rendering; it makes no scientific claim.
    """
    runner = RunnerDefinition(
        name="gremlin_lh_fit",
        display_name="PSSM-GREMLIN fit",
        category="evolution",
        category_label="Evolution",
        summary="Fit a generative model of a protein family from an alignment.",
        use_when="Use to infer a co-evolutionary model from a multiple-sequence alignment.",
        input_summary="A protein multiple-sequence alignment.",
        output_summary="A filtered alignment, ranked residue pairs, and coupling scores.",
        considerations=("The alignment must contain enough diverse sequences to estimate couplings.",),
        runtime_family="gremlin_lh",
        inputs=(
            InputRole(
                id="alignment",
                title="Multiple sequence alignment",
                logical_type="alignment",
                formats=("a3m", "fasta"),
                extensions=(".a3m", ".fasta"),
                description="A protein multiple-sequence alignment.",
            ),
        ),
        parameters=(
            ParameterSpec.integer("min_seqs", title="Minimum sequences", default=10, has_default=True, minimum=2),
            ParameterSpec.number(
                "gap_cutoff",
                title="Gap cutoff",
                default=0.5,
                has_default=True,
                minimum=0.0,
                maximum=1.0,
            ),
        ),
        workspace_steps=(
            WorkspaceStep(
                id="input",
                title="Provide input",
                description="Choose an alignment source.",
                capabilities=(
                    WorkspaceCapability("files", "alignment_files", "Alignment", "Upload an alignment."),
                    WorkspaceCapability(
                        "sequence",
                        "alignment_editor",
                        "Alignment",
                        "Paste an alignment.",
                        (("role", "alignment"),),
                    ),
                ),
            ),
            WorkspaceStep(
                id="settings",
                title="Settings",
                description="Configure the fit.",
                capabilities=(WorkspaceCapability("parameters", "parameters", "Parameters", "Fit controls."),),
            ),
            WorkspaceStep(
                id="review",
                title="Review",
                description="Check the snapshot.",
                capabilities=(WorkspaceCapability("review", "review", "Review", "Submission summary.", (("show_paths", True),)),),
            ),
        ),
        citations=(
            Citation(
                num=1,
                doi="10.0000/example.gremlin",
                title="Inference of couplings in protein families",
                url="https://example.org/gremlin",
            ),
        ),
    )
    fixture = ResultFixture(
        name="pssm_gremlin_fit",
        task_type="gremlin_lh_fit",
        artifacts=(
            ResultArtifactSpec(
                "alignment/filtered_alignment.a3m",
                role="evidence",
                capability="text",
                media_type="text/x-a3m",
                body=">seq1\nACDEFG\n>seq2\nACD-FG\n",
            ),
            ResultArtifactSpec(
                "couplings/apc_scores.csv",
                role="primary",
                capability="table",
                media_type="text/csv",
                columns=("position", "10", "11"),
                table=(("10", "0.0", "0.42"), ("11", "0.42", "0.0")),
            ),
            ResultArtifactSpec(
                "couplings/pairwise_scores.tsv",
                role="evidence",
                capability="table",
                media_type="text/tab-separated-values",
                columns=("alignment_i", "alignment_j", "raw_score", "apc_score"),
                table=(("10", "11", "0.51", "0.42"),),
            ),
            ResultArtifactSpec(
                "model/gremlin_mrf.npz",
                role="evidence",
                capability="download_only",
                media_type="application/octet-stream",
            ),
            ResultArtifactSpec(
                "model/metadata.json",
                role="evidence",
                capability="download_only",
                media_type="application/json",
            ),
            ResultArtifactSpec(
                "profiles/profile.tsv",
                role="evidence",
                capability="table",
                media_type="text/tab-separated-values",
                columns=("position", "amino_acid", "weight"),
                table=(("10", "A", "0.8"),),
            ),
            ResultArtifactSpec(
                "summary.json",
                role="evidence",
                capability="download_only",
                media_type="application/json",
            ),
            ResultArtifactSpec(
                "execution/slurm.stdout",
                role="diagnostic",
                capability="text",
                body="worker ready\nfit accepted\n",
            ),
            ResultArtifactSpec("execution/task_finished", role="diagnostic", capability="text", size=0, body=""),
            ResultArtifactSpec(
                "citations.bib",
                role="provenance",
                capability="download_only",
                media_type="text/x-bibtex",
            ),
        ),
        # The view set mirrors gremlin_lh_fit's declared result_workspace,
        # including the two views the current frontend presents as artifacts
        # rather than separate rendering plugins.
        views=(
            builders.view_entry(
                "matrix",
                "apc_couplings",
                "APC-corrected coupling strengths",
                {"matrices": ["couplings/apc_scores.csv"]},
                format="csv",
                scale="diverging",
                x_label="Alignment position (one-based)",
                y_label="Alignment position (one-based)",
            ),
            builders.view_entry(
                "entity-table",
                "ranked_pairs",
                "Ranked residue pairs",
                {"table": ["couplings/pairwise_scores.tsv"]},
                role="evidence",
                entity="residue",
            ),
            builders.view_entry(
                "alignment",
                "filtered_alignment",
                "Filtered alignment",
                {"alignment": ["alignment/filtered_alignment.a3m"]},
                role="evidence",
                format="a3m",
            ),
            builders.view_entry(
                "evidence-bundle",
                "model_artifacts",
                "Model artifacts",
                {"items": ["model/gremlin_mrf.npz", "model/metadata.json", "profiles/profile.tsv"]},
                role="evidence",
            ),
            builders.view_entry(
                "scalar-summary",
                "fit_summary",
                "Model fit summary",
                {"data": ["summary.json"]},
                role="evidence",
                fields=[{"path": "alignment.sequence_count", "label": "MSA rows", "unit": "sequences"}],
            ),
        ),
        output_check=OutputCheckSpec(
            state="passed",
            checks=tuple(
                (
                    ("view_id", view_id),
                    ("source", source),
                    ("required", True),
                    ("status", "passed"),
                    ("matched", len(paths)),
                )
                for view_id, source, paths in (
                    ("apc_couplings", "matrices", ("couplings/apc_scores.csv",)),
                    ("ranked_pairs", "table", ("couplings/pairwise_scores.tsv",)),
                    ("filtered_alignment", "alignment", ("alignment/filtered_alignment.a3m",)),
                    ("model_artifacts", "items", ("model/gremlin_mrf.npz", "model/metadata.json", "profiles/profile.tsv")),
                    ("fit_summary", "data", ("summary.json",)),
                )
            ),
        ),
        run_inputs=(("alignment", "alignment.a3m", "a3m"),),
        run_parameters=(("min_seqs", "Minimum sequences", 10, ""), ("gap_cutoff", "Gap cutoff", 0.5, "")),
    )
    return runner_scenario(runner, lifecycle=("queued", "running", "finished"), result=fixture)


def structure_scenario() -> RunnerScenario:
    """A GPU structure-prediction scenario that needs no weights or inference."""
    runner = RunnerDefinition(
        name="fold_demo",
        display_name="Fold demo",
        category="structure",
        category_label="Structure prediction",
        summary="Predict a protein structure from one sequence.",
        use_when="Use to obtain a candidate structure for a single chain.",
        input_summary="One protein sequence.",
        output_summary="Confidence-ranked predicted structures.",
        runtime_family="fold_demo",
        gpus=True,
        inputs=(SEQUENCE_ROLE,),
        parameters=(
            ParameterSpec.integer(
                "num_models",
                title="Number of models",
                default=3,
                has_default=True,
                minimum=1,
                maximum=5,
            ),
            ParameterSpec.enumeration(
                "precision",
                ("bf16", "fp32"),
                title="Precision",
                default="bf16",
                has_default=True,
            ),
            ParameterSpec.boolean("use_msa", title="Use MSA", default=True, has_default=True),
            ParameterSpec.integer("seed", title="Random seed", minimum=0, advanced=True),
        ),
        workspace_steps=_sequence_workspace(),
        workflow=(
            WorkflowStage(name="msa", display_name="MSA search"),
            WorkflowStage(name="predict", display_name="Structure prediction", requires_gpu=True),
            WorkflowStage(name="score", display_name="Confidence scoring", requires_gpu=True),
        ),
    )
    return runner_scenario(runner, lifecycle=("queued", "running", "finished"), result="multi_structure")


__all__ = [
    "CONTROLLED_ACCESS_POLICY",
    "CONTROLLED_RUNNER_NAME",
    "SEQUENCE_ROLE",
    "RunnerScenario",
    "controlled_runner",
    "controlled_scenario",
    "pssm_gremlin_scenario",
    "runner_scenario",
    "structure_scenario",
]
