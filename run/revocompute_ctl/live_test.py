# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Deterministic target-instance Runner build and live acceptance."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from revocompute_ctl import SERVER_ROOT
from revocompute_ctl.compose import run_cmd
from revocompute_ctl.registry import (
    RegistryError,
    RuntimeFamily,
    _build_provenance,
    _read_sif_manifest,
    build_slurm_images,
    load_plugin_families,
)
from revocompute.live_tests import (
    LiveTestConfigurationError,
    LiveTestReport,
    atomic_write_json,
    canonical_digest,
    load_live_test_plan,
    resolve_fixture,
    receipt_matches,
    sanitized_mapping,
    sha256_file,
)
from revocompute.resource_policy import resolve_submission_resources


class RunnerLiveTestError(RuntimeError):
    """Live acceptance failed with a stable machine-readable category."""

    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category


def load_validation_identity(family: RuntimeFamily, *, repo_root: str | Path = SERVER_ROOT):
    """Return the family smoke plan and its current public runtime-contract digest."""
    if family.root is None:
        raise LiveTestConfigurationError("Runner family source root is unavailable")
    from revocompute.task_types import discover_plugins, get

    plugin_root = family.root.parent
    discover_plugins(str(plugin_root))
    manifest = next(item for item in load_plugin_families(plugin_root) if item.name == family.name)
    manager_doc = yaml.safe_load((manifest.root / "runner.yaml").read_text(encoding="utf-8")) or {}
    schemas: dict[str, dict[str, Any]] = {}
    defaults: dict[str, dict[str, Any]] = {}
    task_contracts: list[dict[str, Any]] = []
    plugin_doc = yaml.safe_load((manifest.root / "plugin.yaml").read_text(encoding="utf-8")) or {}
    for ref in plugin_doc.get("tasks", ()):
        task_doc = yaml.safe_load((manifest.root / ref).read_text(encoding="utf-8")) or {}
        task_id = str(task_doc.get("id") or Path(ref).parent.name)
        task_type, runner = get(task_id)
        schemas[task_id] = task_type.schema
        defaults[task_id] = runner.defaults
        task_contracts.append(task_doc)
    plan = load_live_test_plan(
        manifest.root / "test.yaml",
        repo_root=repo_root,
        task_schemas=schemas,
        task_defaults=defaults,
    )
    config_public = sanitized_mapping(
        {"runtime": plugin_doc.get("runtime", {}), "runner": manager_doc, "tasks": task_contracts}
    )
    return plan, canonical_digest(config_public)


class RunnerLiveTestWorker:
    """Build, validate, seed, execute, accept, and receipt one exact SIF."""

    def __init__(
        self,
        state,
        family: RuntimeFamily,
        *,
        collection: str = "smoke",
        task: str | None = None,
        artifact_path: str | Path | None = None,
    ):
        self.state = state
        self.family = family
        self.collection = collection
        self.task = task
        self._explicit_artifact = Path(artifact_path) if artifact_path is not None else None
        self.repo_root = Path(SERVER_ROOT)
        self.reports_dir = Path(family.slurm_image).parent / "live-tests" / family.name
        self.receipt_path = Path(family.slurm_image).parent / "receipts" / f"{family.name}.json"
        # Nanosecond precision keeps independent cases/runs isolated even when
        # an operator reruns a failed candidate in the same process/second.
        self.work_root = (
            Path(state.server_dir()) / "live-tests" / family.name / f"{time.time_ns()}-{os.getpid()}"
        )

    @property
    def candidate(self) -> Path:
        return Path(f"{self.family.slurm_image}.next")

    @property
    def artifact(self) -> Path:
        """Return the exact SIF selected for this run."""
        if self._explicit_artifact is not None:
            return self._explicit_artifact
        return self.candidate if self.candidate.is_file() else Path(self.family.slurm_image)

    def run(self, *, build: bool = True) -> LiveTestReport:
        started = time.monotonic()
        report = LiveTestReport(self.family.name, self.collection, "", "", "", "")
        try:
            if build and self._explicit_artifact is None:
                self._transition(report, "BUILDING")
                build_slurm_images(self.state, [self.family], fail_on_error=True)
            artifact = self.artifact
            if not artifact.is_file():
                raise RunnerLiveTestError("BUILD_FAILURE", f"SIF artifact is missing: {artifact}")
            provenance = _read_sif_manifest(self.family).get(self.family.name) or {}
            current = _build_provenance(self.state, self.family)
            sif_sha256 = sha256_file(artifact)
            if (
                provenance.get("sif_sha256") != sif_sha256
                or provenance.get("build_provenance_digest") != current["build_provenance_digest"]
            ):
                raise RunnerLiveTestError("BUILD_FAILURE", "Candidate SIF does not match its direct-build provenance")
            plan, configuration_digest = self._load_plan()
            report.sif_sha256 = sif_sha256
            report.build_provenance_digest = str(current["build_provenance_digest"])
            report.test_definition_digest = plan.digest
            report.configuration_digest = configuration_digest
            self._transition(report, "VALIDATING")
            report.apptainer_version = str(current["apptainer_version"])
            self._validate_candidate()
            selected = plan.select(self.collection, task=self.task)
            if not selected:
                raise RunnerLiveTestError("TEST_CONFIGURATION_FAILURE", "The selected live-test scope contains no cases")
            for case in selected:
                self._transition(report, "SEEDING")
                case_started = time.monotonic()
                try:
                    case_result = self._run_case(case, report)
                except RunnerLiveTestError as exc:
                    # Preserve the failed case in the machine report before
                    # propagating its structured category to the run level.
                    case_result = self._failed_case(
                        case, {}, exc.category, str(exc), case_started
                    )
                report.cases.append(case_result)
                if not case_result["passed"]:
                    raise RunnerLiveTestError(
                        str(case_result["failure_category"]), str(case_result["failure_message"])
                    )
            self._transition(report, "PASSED")
            report.passed = True
            return report
        except LiveTestConfigurationError as exc:
            self._transition(report, "FAILED")
            report.failure_category = "TEST_CONFIGURATION_FAILURE"
            report.failure_message = str(exc)
            return report
        except (RegistryError, RunnerLiveTestError, OSError, subprocess.SubprocessError) as exc:
            self._transition(report, "FAILED")
            report.failure_category = getattr(exc, "category", "BUILD_FAILURE")
            report.failure_message = str(exc)
            return report
        finally:
            report.ended_at = datetime.now(timezone.utc).isoformat()
            report.duration_seconds = round(time.monotonic() - started, 3)
            destination = self.reports_dir / f"{time.time_ns()}-{self.collection}.json"
            atomic_write_json(destination, report.as_dict())
            if report.passed:
                atomic_write_json(self.receipt_path, report.as_dict())
            print(self._summary(report, destination))

    @staticmethod
    def _transition(report: LiveTestReport, state: str) -> None:
        report.state = state
        if not report.transitions or report.transitions[-1] != state:
            report.transitions.append(state)

    def _load_plan(self):
        return load_validation_identity(self.family, repo_root=self.repo_root)

    def _validate_candidate(self) -> None:
        artifact = self.artifact
        for command in (
            ["apptainer", "inspect", str(artifact)],
            ["apptainer", "test", str(artifact)],
        ):
            result = run_cmd(command, env=self.state.exported(), check=False, capture=True)
            if result.returncode != 0:
                message = (result.stderr or result.stdout or "Apptainer validation failed").strip()
                raise RunnerLiveTestError("SIF_VALIDATION_FAILURE", message[-2000:])

    def _runtime_environment(self, work_root: Path) -> dict[str, str]:
        environment = self.state.exported()
        environment.update(
            {
                "SERVER_DIR": str(work_root),
                "DB_PATH": str(work_root / "live-test.sqlite3"),
                "MANAGE_DB_PATH": self.state.get("MANAGE_DB_PATH")
                or str(Path(self.state.server_dir()) / "manage.sqlite"),
                "RUNNERS_DIR": str(self.family.root.parent),
                "REVOCOMPUTE_IMAGE_DIR": str(Path(self.family.slurm_image).parent),
                "REVOCOMPUTE_RUNTIME_ARTIFACT_OVERRIDES": json.dumps(
                    {self.family.name: str(self.artifact.resolve())}, sort_keys=True
                ),
                "ENABLED_TASKRUNNERS": self.family.name,
                "REVOCOMPUTE_JOB_EXECUTOR": "slurm",
                "REVOCOMPUTE_CONTAINER_RUNTIME": "apptainer",
                "SLURM_ENABLED": "true",
            }
        )
        return environment

    def _run_case(self, case, report: LiveTestReport) -> dict[str, Any]:
        case_started = time.monotonic()
        unexpected_category = "INPUT_SEED_FAILURE"
        run_key = f"{self.work_root.name}-{case.id}"
        work_root = self.work_root
        work_root.mkdir(parents=True, exist_ok=True)
        old_environment = dict(os.environ)
        try:
            os.environ.clear()
            os.environ.update(self._runtime_environment(work_root))
            # Import after the isolated production environment and candidate
            # artifact override are installed.
            from revocompute.input_validators import validate_input_file
            from revocompute.schemas import TaskSubmissionRequest
            from revocompute.storage import StorageResolver
            from revocompute import task_runtime

            submission = TaskSubmissionRequest.model_validate(
                {"task_type": case.task, "params": dict(case.parameters)}
            )
            parameters = submission.coerce_params()
            identity_seed = json.dumps(
                {"run": run_key, "task": case.task, "parameters": parameters}, sort_keys=True
            ).encode()
            task_id = hashlib.sha256(identity_seed).hexdigest()[:32]
            storage_key = f"live-test-{self.family.name}"
            resolver = StorageResolver(str(work_root / "results"), str(work_root / "workspaces"))
            task_identity = {
                "md5sum": task_id,
                "scope_type": "personal",
                "scope_id": "live-test",
                "storage_key": storage_key,
            }
            snapshot_root = Path(resolver.get_input_root(task_identity)) / "inputs"
            output_root = Path(resolver.get_output_root(task_identity))
            upload_root = work_root / "upload"
            snapshot_root.mkdir(parents=True, exist_ok=True)
            output_root.mkdir(parents=True, exist_ok=True)
            upload_root.mkdir(parents=True, exist_ok=True)
            entities: list[dict[str, Any]] = []
            manifest_files = []
            for index, relative in enumerate(case.files):
                source = resolve_fixture(self.repo_root, relative)
                error = validate_input_file(str(source), source.name)
                if error:
                    raise RunnerLiveTestError("INPUT_SEED_FAILURE", error)
                digest = sha256_file(source).split(":", 1)[1]
                destination = snapshot_root / source.name
                shutil.copyfile(source, destination)
                destination.chmod(0o440)
                shutil.copyfile(source, upload_root / f"{digest}.upload")
                mounted = f"/mnt/revocompute/{storage_key}/inputs/{source.name}"
                entities.append(
                    {
                        "name": "primary_input" if index == 0 else f"input_{index + 1}",
                        "type": "file",
                        "value": source.name,
                        "verified_value": source.name,
                        "relative_path": source.name,
                        "mounted": mounted,
                        "hash": digest,
                        "snapshot_path": str(destination),
                        "snapshot_root": str(snapshot_root),
                        "workspace_key": storage_key,
                    }
                )
                manifest_files.append(
                    {"name": entities[-1]["name"], "path": mounted, "relative_path": source.name, "hash": digest}
                )
            task_type, _runner = task_runtime._get_task_type(case.task)
            resource_policy, resource_policies = resolve_submission_resources(
                task_runtime._manage_db, task_type, _runner
            )
            param_types = {param.name: param.type for param in task_type.params}
            for name, value in parameters.items():
                entities.append(
                    {
                        "name": name,
                        "type": param_types.get(name, "str"),
                        "value": value,
                        "verified_value": value,
                    }
                )
            task_manifest = {
                "task_id": task_id,
                "task_type": case.task,
                "params": parameters,
                "files": manifest_files,
            }
            atomic_write_json(snapshot_root / "task.json", task_manifest)
            now = time.time()
            task_runtime.task_store.upsert_task(
                task_id,
                filename=manifest_files[0]["relative_path"],
                file_path=str(upload_root / f"{entities[0]['hash']}.upload"),
                uploaded_at=now,
                started_at=None,
                finished_at=None,
                walltime=None,
                status="pending",
                is_binary=0,
                source_ip="target-instance",
                user_agent="RunnerLiveTestWorker",
                username="runner-live-test",
                local_user="runner-live-test",
                request_headers=None,
                run_stage=None,
                error=None,
                celery_task_id=None,
                task_type=case.task,
                input_form=json.dumps(
                    {
                        "entities": entities,
                        "resource_policy": (
                            resource_policy.public_dict() if resource_policy is not None else None
                        ),
                        "resource_policies": {
                            name: policy.public_dict() for name, policy in resource_policies.items()
                        },
                    },
                    sort_keys=True,
                ),
                slurm_job_id=None,
                container_id=None,
                workflow_state=None,
                scope_type="personal",
                scope_id="live-test",
                storage_key=storage_key,
                submitted_by_user_id=0,
                artifact_provenance="[]",
            )
            unexpected_category = "SUBMISSION_FAILURE"
            self._transition(report, "SUBMITTED")
            self._transition(report, "RUNNING")
            unexpected_category = "RUNTIME_FAILURE"
            task_runtime._execute_compute_task(task_id, case.task)
            unexpected_category = "RESULT_PARSING_FAILURE"
            self._transition(report, "ACCEPTING")
            completed = task_runtime.task_store.get_task(task_id) or {}
            manifest_path = output_root / "manifest.json"
            if completed.get("status") != "finished":
                message = str(completed.get("error") or "Task did not finish")
                category = self._runtime_failure_category(completed, message)
                return self._failed_case(case, completed, category, message, case_started)
            try:
                result = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                return self._failed_case(case, completed, "RESULT_PARSING_FAILURE", str(exc), case_started)
            output_check = result.get("output_check", {})
            artifacts = result.get("artifacts", [])
            if output_check.get("state") != "passed" or not any(item.get("size", 0) > 0 for item in artifacts):
                return self._failed_case(
                    case,
                    completed,
                    "ARTIFACT_ACCEPTANCE_FAILURE",
                    "; ".join(output_check.get("problems", ())) or "Required output contracts did not pass",
                    case_started,
                )
            return {
                "case_id": case.id,
                "task_type": case.task,
                "passed": True,
                "task_status": completed.get("status"),
                **self._slurm_evidence(completed),
                "artifact_count": len(artifacts),
                "output_check": output_check,
                "duration_seconds": round(time.monotonic() - case_started, 3),
            }
        except RunnerLiveTestError:
            raise
        except Exception as exc:
            return self._failed_case(case, {}, unexpected_category, str(exc), case_started)
        finally:
            os.environ.clear()
            os.environ.update(old_environment)

    @staticmethod
    def _failed_case(case, task: dict[str, Any], category: str, message: str, started: float) -> dict[str, Any]:
        return {
            "case_id": case.id,
            "task_type": case.task,
            "passed": False,
            "task_status": task.get("status"),
            "slurm_job_id": task.get("slurm_job_id"),
            "failure_category": category,
            "failure_message": message,
            "duration_seconds": round(time.monotonic() - started, 3),
        }

    def _slurm_evidence(self, task: dict[str, Any]) -> dict[str, Any]:
        active_job_id = str(task.get("slurm_job_id") or "")
        jobs: list[dict[str, str]] = []
        try:
            workflow_state = json.loads(task.get("workflow_state") or "{}")
        except (TypeError, json.JSONDecodeError):
            workflow_state = {}
        if isinstance(workflow_state, dict):
            for stage, details in workflow_state.items():
                if not isinstance(details, dict) or not details.get("job_id"):
                    continue
                jobs.append(
                    {
                        "stage": str(stage),
                        "job_id": str(details["job_id"]),
                        "state": str(details.get("status") or ""),
                    }
                )
        job_id = active_job_id or (jobs[-1]["job_id"] if jobs else "")
        terminal_state = self._slurm_state(job_id)
        if not terminal_state and jobs and jobs[-1]["state"]:
            terminal_state = jobs[-1]["state"].upper()
        return {"slurm_job_id": job_id or None, "slurm_terminal_state": terminal_state, "slurm_jobs": jobs}

    @staticmethod
    def _runtime_failure_category(task: dict[str, Any], message: str) -> str:
        lowered = message.lower()
        if "time limit" in lowered or "timed out" in lowered or "timeout" in lowered:
            return "TIMEOUT"
        if any(term in lowered for term in ("no such file", "not found", "missing", "permission denied")):
            return "RESOURCE_MISSING"
        if not task.get("slurm_job_id"):
            return "SUBMISSION_FAILURE"
        return "RUNTIME_FAILURE"

    def _slurm_state(self, job_id: str) -> str:
        if not job_id:
            return ""
        result = run_cmd(
            ["sacct", "-n", "-X", "-j", job_id, "-o", "State", "--parsable2"],
            env=self.state.exported(),
            check=False,
            capture=True,
        )
        return next((line.strip().split("|", 1)[0] for line in result.stdout.splitlines() if line.strip()), "")

    @staticmethod
    def _summary(report: LiveTestReport, destination: Path) -> str:
        result = "PASS" if report.passed else "FAIL"
        suffix = (
            f" ({report.failure_category}: {report.failure_message})"
            if report.failure_category
            else ""
        )
        return f"Runner live test {result}: {report.runner_family}/{report.collection}{suffix}\nReport: {destination}"


def run_live_tests(
    state,
    *,
    runner: str | None,
    task: str | None,
    collection: str,
    all_runners: bool,
    build: bool = True,
) -> bool:
    source_root = Path(state.get("RUNNER_SOURCE_ROOT") or Path(SERVER_ROOT) / "docker" / "runners")
    image_root = Path(state.server_dir()).parent / "images"
    families = [
        replace(family, slurm_image=str(image_root / family.slurm_image))
        if not Path(family.slurm_image).is_absolute()
        else family
        for family in load_plugin_families(source_root)
    ]
    selected = [
        family
        for family in families
        if (all_runners or runner is None or family.name == runner)
        and (task is None or _family_owns_task(family, task))
    ]
    if not selected:
        raise RegistryError("No Runner Families match the requested live-test scope")
    passed = True
    for family in selected:
        report = RunnerLiveTestWorker(state, family, collection=collection, task=task).run(build=build)
        passed = passed and report.passed
    return passed


def _family_owns_task(family: RuntimeFamily, task: str) -> bool:
    if family.root is None:
        return False
    doc = yaml.safe_load((family.root / "plugin.yaml").read_text(encoding="utf-8")) or {}
    for ref in doc.get("tasks", ()):
        task_doc = yaml.safe_load((family.root / ref).read_text(encoding="utf-8")) or {}
        if str(task_doc.get("id") or Path(ref).parent.name) == task:
            return True
    return False


def receipt_valid_for_artifact(state, family: RuntimeFamily, artifact_path: str | Path) -> bool:
    """Return whether required smoke tests passed for the exact artifact identity."""
    worker = RunnerLiveTestWorker(state, family, artifact_path=artifact_path)
    artifact = worker.artifact
    if not artifact.is_file() or not worker.receipt_path.is_file():
        return False
    try:
        receipt = json.loads(worker.receipt_path.read_text(encoding="utf-8"))
        plan, configuration_digest = worker._load_plan()
        provenance = _build_provenance(state, family)
        required = {case.id for case in plan.select("smoke")}
        return receipt_matches(
            receipt,
            sif_sha256=sha256_file(artifact),
            build_provenance_digest=str(provenance["build_provenance_digest"]),
            test_definition_digest=plan.digest,
            configuration_digest=configuration_digest,
            required_case_ids=required,
        )
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        StopIteration,
        LiveTestConfigurationError,
        RegistryError,
        yaml.YAMLError,
    ):
        return False


def candidate_receipt_valid(state, family: RuntimeFamily) -> bool:
    """Return whether required smoke tests passed for the staged candidate."""
    return receipt_valid_for_artifact(state, family, f"{family.slurm_image}.next")


def active_receipt_valid(state, family: RuntimeFamily) -> bool:
    """Return whether required smoke tests passed for the active SIF."""
    return receipt_valid_for_artifact(state, family, family.slurm_image)
