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
        return self.result.artifact_for(path) if self.result is not None else None

    def artifact_body(self, task_id: str, path: str) -> tuple[bytes, str] | None:
        if task_id != self.task_id:
            return None
        artifact = self._artifact(path)
        if artifact is None:
            return None
        body = (artifact.body or "").encode("utf-8")
        media_type = artifact.media_type or _MEDIA_TYPE_BY_SUFFIX.get(
            Path(unquote(path)).suffix.lower(), "application/octet-stream",
        )
        return body, media_type

    def logical_file_artifact(self, task_id: str, file_id: str, index: int) -> tuple[bytes, str] | None:
        """Serve the artifact bytes behind one logical file entry."""
        if self.result is None or task_id != self.task_id:
            return None
        path = self.result.logical_artifact_path(file_id, index)
        return self.artifact_body(task_id, path) if path is not None else None

    def table_page(self, task_id: str, path: str) -> dict[str, Any] | None:
        if task_id != self.task_id:
            return None
        artifact = self._artifact(path)
        if artifact is None or artifact.capability != "table" or not artifact.table:
            return None
        return builders.build_table_page(artifact.columns, artifact.table)

    def projection(self, task_id: str, path: str, *, kind: str = "numeric") -> dict[str, Any] | None:
        if task_id != self.task_id:
            return None
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
        parameters=(ParameterSpec.integer("iterations", default=2, has_default=True, minimum=1, maximum=4),),
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
    """A frontend scenario mirroring the real ``gremlin_lh_fit`` contract.

    The Runner identity, input role, workspace steps, parameters, and citations
    are transcribed from the owning ``task.yaml`` (the source of truth), so the
    detail page a browser test drives matches what the enabled 309 Runner
    actually declares. The artifact bytes are fixtures: this exercises rendering
    and makes no scientific claim.
    """
    runner = RunnerDefinition(
        name="gremlin_lh_fit",
        display_name="GREMLIN_LH Potts model",
        category="evolution",
        category_label="Evolution",
        summary="Fit a regularized Potts model and residue-coupling landscape from a supplied protein MSA.",
        use_when=(
            "Use this when an aligned homolog set is already available and conservation, "
            "sequence energy, or coupling scores are required."
        ),
        input_summary="One aligned protein FASTA or A3M file containing at least two equal-length sequences.",
        output_summary=(
            "Model fields and couplings, raw and APC score matrices, ranked residue pairs, "
            "sequence scores, and fit provenance."
        ),
        considerations=(
            "Runtime and memory grow rapidly with alignment width because the fitted coupling tensor is "
            "quadratic in positions and amino-acid states.",
            "Coupling strength is statistical dependence extracted from the fitted model; it is not by itself "
            "proof of a physical contact, causal interaction, or functional coupling, and the contact-oriented "
            "reading is a downstream use of these scores.",
            "The reported Hamiltonian is the model's statistical MRF energy, not a thermodynamic free energy. "
            "The source paper's stability correlations are empirical and system-specific and say nothing about "
            "any particular run.",
        ),
        runtime_family="gremlin_lh",
        inputs=(
            InputRole(
                id="alignment",
                title="Protein multiple-sequence alignment",
                logical_type="alignment",
                formats=("a3m", "fasta", "fa"),
                extensions=(".a3m", ".fasta", ".fa"),
                description="One aligned protein FASTA or A3M file containing at least two equal-length sequences.",
            ),
        ),
        # Transcribed from gremlin_lh_fit's task.yaml parameter schema: names,
        # types, defaults, enum, bounds (exclusiveMinimum where declared), and
        # the seed x-ui-control. No ``title`` — real task.yaml schemas do not
        # carry one, so the frontend derives the label from the name.
        parameters=(
            ParameterSpec.enumeration(
                "regularization",
                ("L2", "LH", "LB"),
                default="LH",
                has_default=True,
                description="Coupling penalty: conventional squared L2, low-rank spectral LH, or group-sparse block LB.",
            ),
            ParameterSpec.number(
                "lambda_l2",
                default=0.01,
                has_default=True,
                exclusive_minimum=0.0,
                maximum=10.0,
                description="L2 coupling strength; also regularizes fields when field terms are enabled.",
            ),
            ParameterSpec.number(
                "lambda_lh",
                default=0.1,
                has_default=True,
                exclusive_minimum=0.0,
                maximum=10.0,
                description="Low-rank spectral penalty strength used in LH mode.",
            ),
            ParameterSpec.number(
                "lambda_lb",
                default=0.005,
                has_default=True,
                exclusive_minimum=0.0,
                maximum=10.0,
                description="Group-sparse block penalty strength used in LB mode.",
            ),
            ParameterSpec.integer(
                "iterations",
                default=400,
                has_default=True,
                minimum=1,
                maximum=5000,
                description="Number of Adam optimization updates.",
            ),
            ParameterSpec.integer(
                "batch_size",
                default=100,
                has_default=True,
                minimum=2,
                maximum=10000,
                description=(
                    "Maximum number of MSA rows sampled without replacement for each update; the effective batch "
                    "is clamped to the row count, so smaller alignments use every row."
                ),
            ),
            ParameterSpec.number(
                "learning_rate",
                default=1.0,
                has_default=True,
                exclusive_minimum=0.0,
                maximum=10.0,
                description="Learning rate for the notebook's scalar-second-moment Adam optimizer.",
            ),
            ParameterSpec.number(
                "identity_cutoff",
                default=0.8,
                has_default=True,
                minimum=0.1,
                maximum=1.0,
                description="Aligned-sequence identity threshold used to down-weight phylogenetically similar rows.",
            ),
            ParameterSpec.number(
                "gap_cutoff",
                default=0.5,
                has_default=True,
                minimum=0,
                maximum=1,
                description=(
                    "Columns whose gap-state fraction exceeds this value are excluded only when computing "
                    "sequence similarity weights; they are still modeled."
                ),
            ),
            ParameterSpec.boolean(
                "use_bias",
                default=True,
                has_default=True,
                description="Fit one-body residue fields in addition to pairwise couplings.",
            ),
            ParameterSpec.boolean(
                "inverse_covariance_init",
                default=False,
                has_default=True,
                description=(
                    "Initialize couplings from the regularized inverse covariance instead of zeros. The upstream "
                    "notebook uses this initialization; zero initialization is the bounded production default."
                ),
            ),
            ParameterSpec.boolean(
                "exact_lh_eigenvalue",
                default=False,
                has_default=True,
                description="Use an exact eigendecomposition for LH instead of the notebook's faster one-step power estimate.",
            ),
            ParameterSpec.boolean(
                "a3m",
                default=True,
                has_default=True,
                description=(
                    "Remove lowercase A3M insertion residues and insertion-gap dots before validating alignment "
                    "width; match-state deletion gaps are preserved."
                ),
            ),
            ParameterSpec.integer(
                "seed",
                default=0,
                has_default=True,
                minimum=0,
                maximum=4294967295,
                ui_control=(("kind", "seed"),),
                description="Random seed controlling mini-batch sampling.",
            ),
        ),
        workspace_steps=(
            WorkspaceStep(
                id="material",
                title="Provide the alignment",
                description="Choose the aligned homolog set used to fit the model",
                capabilities=(
                    WorkspaceCapability("files", "source_files", "MSA file", "Choose the aligned homolog set used to fit the model"),
                ),
            ),
            WorkspaceStep(
                id="settings",
                title="Set the experiment",
                description="Configure model fitting and regularization",
                capabilities=(
                    WorkspaceCapability("parameters", "task_parameters", "Fit settings", "Configure model fitting and regularization"),
                ),
            ),
            WorkspaceStep(
                id="review",
                title="Review and run",
                description="Check the alignment and settings before creating the task snapshot",
                capabilities=(
                    WorkspaceCapability(
                        "review",
                        "submission_review",
                        "Experiment review",
                        "Check the alignment and settings before creating the task snapshot",
                        (("show_paths", True),),
                    ),
                ),
            ),
        ),
        citations=(
            Citation(
                num=1,
                doi="10.1103/PRXLife.2.023005",
                title="Disentanglement of Evolutionary Constraints in Statistical Models of Proteins",
                url="https://doi.org/10.1103/PRXLife.2.023005",
            ),
            Citation(
                num=2,
                doi="10.1073/pnas.1314045110",
                title="Assessing the utility of coevolution-based residue–residue contact predictions in a sequence- and structure-rich era",
                url="https://doi.org/10.1073/pnas.1314045110",
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
            # raw couplings are the primary matrix (raw Frobenius norm, >= 0);
            # the APC matrix is evidence. This mirrors gremlin_lh_fit's
            # result_workspace: raw_couplings role: primary, apc_couplings
            # role: evidence.
            ResultArtifactSpec(
                "couplings/raw_scores.csv",
                role="primary",
                capability="table",
                media_type="text/csv",
                columns=("position", "10", "11"),
                table=(("10", "0.0", "0.51"), ("11", "0.51", "0.0")),
            ),
            ResultArtifactSpec(
                "couplings/apc_scores.csv",
                role="evidence",
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
            # expected_files.yaml declares model/metadata.json and summary.json
            # as provenance (type json), and the server projects a .json preview
            # as text, so both render inline rather than as a download.
            ResultArtifactSpec(
                "model/metadata.json",
                role="provenance",
                capability="text",
                media_type="application/json",
                body='{"positions": 2}\n',
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
                role="provenance",
                capability="text",
                media_type="application/json",
                body='{"alignment": {"sequence_count": 2}}\n',
            ),
            # No mimetype for .stdout and it is a diagnostic: the server
            # publishes it download-only, with no inline preview.
            ResultArtifactSpec(
                "execution/slurm.stdout",
                role="diagnostic",
                capability="download_only",
                media_type="application/octet-stream",
                body="worker ready\nfit accepted\n",
            ),
            ResultArtifactSpec(
                "citations.bib",
                role="provenance",
                capability="text",
                media_type="text/x-bibtex",
                body="@article{Wang_2024}\n",
            ),
        ),
        # The view set mirrors gremlin_lh_fit's declared result_workspace
        # exactly: raw_couplings is the primary matrix, apc_couplings is
        # evidence, and the remaining views are evidence.
        views=(
            builders.view_entry(
                "matrix",
                "raw_couplings",
                "Coupling strength (raw Frobenius)",
                {"matrices": ["couplings/raw_scores.csv"]},
                role="primary",
                format="csv",
                row_labels_column="position",
                x_label="Alignment position (one-based)",
                y_label="Alignment position (one-based)",
                unit="coupling score",
                direction="higher",
                scale="sequential",
            ),
            builders.view_entry(
                "matrix",
                "apc_couplings",
                "Coupling strength (average-product corrected)",
                {"matrices": ["couplings/apc_scores.csv"]},
                role="evidence",
                format="csv",
                row_labels_column="position",
                x_label="Alignment position (one-based)",
                y_label="Alignment position (one-based)",
                unit="coupling score",
                direction="higher",
                scale="diverging",
                center=0,
            ),
            builders.view_entry(
                "entity-table",
                "ranked_pairs",
                "Ranked residue pairs",
                {"table": ["couplings/pairwise_scores.tsv"]},
                role="evidence",
                entity="residue",
                key_columns=["alignment_i", "alignment_j"],
                evidence_columns=["raw_score", "apc_score"],
            ),
            builders.view_entry(
                "alignment",
                "filtered_alignment",
                "Filtered alignment",
                {"alignment": ["alignment/filtered_alignment.a3m"]},
                role="evidence",
                format="a3m",
                numbering="alignment",
            ),
            builders.view_entry(
                "scalar-summary",
                "fit_summary",
                "Model fit summary",
                {"data": ["summary.json"]},
                role="evidence",
                fields=[
                    {"path": "alignment.sequence_count", "label": "MSA rows", "unit": "sequences", "direction": "neutral"},
                    {"path": "alignment.alignment_length", "label": "Alignment width", "unit": "positions", "direction": "neutral"},
                    {"path": "alignment.effective_sequence_count", "label": "Effective rows", "unit": "sequences", "direction": "higher"},
                    {"path": "alignment.columns_excluded_by_gap_cutoff", "label": "Columns excluded from weighting", "unit": "positions", "direction": "neutral"},
                    {"path": "model.positions", "label": "Model positions", "unit": "positions", "direction": "neutral"},
                    {"path": "optimization.final_loss", "label": "Final loss", "unit": "natural log units", "direction": "lower"},
                ],
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
                    ("raw_couplings", "matrices", ("couplings/raw_scores.csv",)),
                    ("apc_couplings", "matrices", ("couplings/apc_scores.csv",)),
                    ("ranked_pairs", "table", ("couplings/pairwise_scores.tsv",)),
                    ("filtered_alignment", "alignment", ("alignment/filtered_alignment.a3m",)),
                    ("fit_summary", "data", ("summary.json",)),
                )
            ),
        ),
        run_inputs=(("alignment", "alignment.a3m", "a3m"),),
        run_parameters=(("gap_cutoff", "Gap cutoff", 0.5, ""),),
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
            ParameterSpec.integer("num_models", default=3, has_default=True, minimum=1, maximum=5),
            ParameterSpec.enumeration("precision", ("bf16", "fp32"), default="bf16", has_default=True),
            ParameterSpec.boolean("use_msa", default=True, has_default=True),
            ParameterSpec.integer("seed", minimum=0, advanced=True),
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
