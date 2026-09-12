# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Deterministic target-instance Runner build and live acceptance."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from revocompute_ctl import SERVER_ROOT
from revocompute_ctl.compose import detect_compose_cmd, run_cmd
from revocompute_ctl.build import build_web_images
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
    LiveTestPlan,
    LiveTestReport,
    atomic_write_json,
    canonical_digest,
    load_live_test_plan,
    resolve_fixture,
    receipt_matches,
    sanitized_mapping,
    sha256_file,
)
from revocompute.manage_db import read_resource_database
from revocompute.resource_policy import (
    ResourcePolicyValues,
    ResolvedResources,
    resolve_submission_resources,
)


class RunnerLiveTestError(RuntimeError):
    """Live acceptance failed with a stable machine-readable category."""

    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category


@dataclass(frozen=True, slots=True)
class TaskResourceSnapshot:
    """Canonical public resources for one TaskType, safe to hash and replay."""

    task_type: str
    resource_policy: str | None
    resource_policies: tuple[tuple[str, str], ...]

    @classmethod
    def from_resolved(
        cls,
        task_type: str,
        resource_policy: ResolvedResources | None,
        resource_policies: dict[str, ResolvedResources],
    ) -> TaskResourceSnapshot:
        def encode(value: ResolvedResources) -> str:
            return json.dumps(
                value.public_dict(), ensure_ascii=True, separators=(",", ":"), sort_keys=True
            )

        return cls(
            task_type,
            encode(resource_policy) if resource_policy is not None else None,
            tuple((name, encode(policy)) for name, policy in sorted(resource_policies.items())),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "resource_policy": json.loads(self.resource_policy) if self.resource_policy is not None else None,
            "resource_policies": {name: json.loads(payload) for name, payload in self.resource_policies},
        }


@dataclass(frozen=True, slots=True)
class ValidationIdentity:
    """Current validation contract and the exact resource snapshots it represents."""

    plan: LiveTestPlan
    configuration_digest: str
    resources: tuple[TaskResourceSnapshot, ...]

    def resources_for(self, task_type: str) -> TaskResourceSnapshot:
        try:
            return next(item for item in self.resources if item.task_type == task_type)
        except StopIteration:
            raise LiveTestConfigurationError(f"No resource snapshot was resolved for TaskType {task_type!r}") from None

    def required_resource_snapshots(self) -> dict[str, dict[str, Any]]:
        required_tasks = {case.task for case in self.plan.select("smoke")}
        return {item.task_type: item.as_dict() for item in self.resources if item.task_type in required_tasks}


def _resource_policy_values(state) -> ResourcePolicyValues:
    path = state.get("MANAGE_DB_PATH") or str(Path(state.server_dir()) / "manage.sqlite")
    try:
        global_values, task_values = read_resource_database(path)
    except (OSError, sqlite3.Error, KeyError, TypeError, ValueError) as exc:
        raise LiveTestConfigurationError(f"Effective resource configuration cannot be read: {exc}") from exc
    global_values = dict(global_values)
    allowed_queues = state.get("SLURM_ALLOWED_QUEUES")
    if "slurm_allowed_queues" not in global_values and allowed_queues:
        global_values["slurm_allowed_queues"] = allowed_queues
    return ResourcePolicyValues(global_values, task_values)


def load_validation_identity(
    family: RuntimeFamily,
    *,
    state=None,
    resource_provider=None,
    repo_root: str | Path = SERVER_ROOT,
) -> ValidationIdentity:
    """Resolve the family contract and effective resources into one replayable identity."""
    if family.root is None:
        raise LiveTestConfigurationError("Runner family source root is unavailable")
    from revocompute.task_types import discover_plugins, get

    plugin_root = family.root.parent
    discover_plugins(str(plugin_root))
    manifest = next(item for item in load_plugin_families(plugin_root) if item.name == family.name)
    manager_doc = yaml.safe_load((manifest.root / "runner.yaml").read_text(encoding="utf-8")) or {}
    schemas: dict[str, dict[str, Any]] = {}
    definitions: dict[str, tuple[Any, Any]] = {}
    task_contracts: list[dict[str, Any]] = []
    plugin_doc = yaml.safe_load((manifest.root / "plugin.yaml").read_text(encoding="utf-8")) or {}
    for ref in plugin_doc.get("tasks", ()):
        task_doc = yaml.safe_load((manifest.root / ref).read_text(encoding="utf-8")) or {}
        task_id = str(task_doc.get("id") or Path(ref).parent.name)
        task_type, runner = get(task_id)
        definitions[task_id] = (task_type, runner)
        schemas[task_id] = task_type.schema
        task_contracts.append(task_doc)
    plan = load_live_test_plan(
        manifest.root / "test.yaml",
        repo_root=repo_root,
        task_schemas=schemas,
    )
    if resource_provider is None and state is None:
        raise LiveTestConfigurationError("Validation identity requires current effective resource configuration")
    provider = resource_provider if resource_provider is not None else _resource_policy_values(state)
    resource_snapshots: list[TaskResourceSnapshot] = []
    all_tasks = sorted({case.task for cases in plan.collections.values() for case in cases})
    try:
        for task_id in all_tasks:
            task_type, runner = definitions[task_id]
            resource_policy, resource_policies = resolve_submission_resources(provider, task_type, runner)
            resource_snapshots.append(
                TaskResourceSnapshot.from_resolved(task_id, resource_policy, resource_policies)
            )
    except (KeyError, TypeError, ValueError) as exc:
        raise LiveTestConfigurationError(f"Effective resource configuration cannot be resolved: {exc}") from exc
    required_tasks = {case.task for case in plan.select("smoke")}
    required_resources = {
        snapshot.task_type: snapshot.as_dict()
        for snapshot in resource_snapshots
        if snapshot.task_type in required_tasks
    }
    config_public = sanitized_mapping(
        {
            "runtime": plugin_doc.get("runtime", {}),
            "runner": manager_doc,
            "tasks": task_contracts,
            "resources": required_resources,
        }
    )
    return ValidationIdentity(plan, canonical_digest(config_public), tuple(resource_snapshots))


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
            Path(os.environ.get("TMPDIR", "/tmp")) / "revocompute-live" / family.name / f"{time.time_ns()}-{os.getpid()}"
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
        # The controller is invoked by the deployment operator. Scientific
        # execution identity is established by the worker/Slurm boundary and
        # is recorded from the actual execution context below.
        report.operator_uid = os.geteuid()
        report.operator_gid = os.getegid()
        report.execution_uid = None
        report.execution_gid = None
        try:
            if build and self._explicit_artifact is None:
                self._transition(report, "BUILDING")
                # Candidate validation must work before a family is enabled;
                # enablement is gated on the receipt produced by this path.
                build_slurm_images(self.state, [self.family], fail_on_error=True, include_disabled=True)
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
            identity = self._load_identity()
            report.sif_sha256 = sif_sha256
            report.build_provenance_digest = str(current["build_provenance_digest"])
            report.test_definition_digest = identity.plan.digest
            report.configuration_digest = identity.configuration_digest
            report.resource_snapshots = identity.required_resource_snapshots()
            self._transition(report, "VALIDATING")
            report.apptainer_version = str(current["apptainer_version"])
            # Apptainer cannot safely nest inside the unprivileged one-off
            # worker. Validate the exact artifact on the target host before
            # delegating scientific execution to the worker and Slurm.
            self._validate_candidate()
            selected = identity.plan.select(self.collection, task=self.task)
            if not selected:
                raise RunnerLiveTestError(
                    "TEST_CONFIGURATION_FAILURE", "The selected live-test scope contains no cases"
                )
            for case in selected:
                self._transition(report, "SEEDING")
                case_started = time.monotonic()
                try:
                    case_result = self._run_case(case, report, identity.resources_for(case.task))
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

    def _load_identity(self) -> ValidationIdentity:
        return load_validation_identity(self.family, state=self.state, repo_root=self.repo_root)

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
            }
        )
        return environment

    def _run_case(self, case, report: LiveTestReport, resources: TaskResourceSnapshot) -> dict[str, Any]:
        case_started = time.monotonic()
        self.work_root.mkdir(parents=True, exist_ok=True)
        task_id = hashlib.sha256(f"{self.work_root.name}-{case.id}".encode()).hexdigest()[:32]
        request_path = self.work_root / f"{case.id}.request.json"
        result_path = self.work_root / f"{case.id}.execution.json"
        files = []
        for relative in case.files:
            source = resolve_fixture(self.repo_root, relative)
            files.append({"relative_path": str(source.relative_to(self.repo_root)), "sha256": sha256_file(source)})
        atomic_write_json(request_path, {"task_id": task_id, "task_type": case.task, "result_path": "/run/revocompute-live/result.json", "parameters": dict(case.parameters), "files": files, "resources": resources.as_dict(), "artifact_path": "/run/revocompute-live/artifact.sif", "artifact_sha256": sha256_file(self.artifact)})
        request_path.chmod(0o444)
        self._transition(report, "SUBMITTED")
        self._transition(report, "RUNNING")
        try:
            execution = self._execute_in_worker(task_id, case.task, self.work_root, request_path, result_path)
            report.execution_uid = execution.get("execution_uid")
            report.execution_gid = execution.get("execution_gid")
            report.scheduler_user = execution.get("scheduler_user")
            self._transition(report, "ACCEPTING")
            completed = {
                "status": execution.get("task_status"),
                "error": execution.get("error"),
                "slurm_job_id": execution.get("slurm_job_id"),
                "execution_uid": execution.get("execution_uid"),
                "execution_gid": execution.get("execution_gid"),
                "scheduler_user": execution.get("scheduler_user"),
                "slurm_jobs": execution.get("slurm_jobs", []),
            }
            try:
                expected_identity = self._configured_execution_identity()
            except RunnerLiveTestError as exc:
                return self._failed_case(case, completed, exc.category, str(exc), case_started)
            if not self._execution_identity_matches(execution, expected_identity):
                return self._failed_case(
                    case,
                    completed,
                    "IDENTITY_FAILURE",
                    "Worker execution or scheduler identity does not match configured Runner identity",
                    case_started,
                )
            if completed["status"] != "finished":
                message = str(completed.get("error") or "Task did not finish")
                return self._failed_case(case, completed, self._runtime_failure_category(completed, message), message, case_started)
            output_check, artifacts = execution.get("output_check", {}), execution.get("artifacts", [])
            if output_check.get("state") != "passed" or not any(item.get("size", 0) > 0 for item in artifacts):
                return self._failed_case(case, completed, "ARTIFACT_ACCEPTANCE_FAILURE", "; ".join(output_check.get("problems", ())) or "Required output contracts did not pass", case_started)
            return {"case_id": case.id, "task_type": case.task, "passed": True, "task_status": completed["status"], "slurm_job_id": execution.get("slurm_job_id"), "slurm_jobs": execution.get("slurm_jobs", []), "execution_uid": execution.get("execution_uid"), "execution_gid": execution.get("execution_gid"), "scheduler_user": execution.get("scheduler_user"), "artifact_count": len(artifacts), "output_check": output_check, "duration_seconds": round(time.monotonic() - case_started, 3)}
        except RunnerLiveTestError:
            raise
        except Exception as exc:
            return self._failed_case(case, {}, "RUNTIME_FAILURE", str(exc), case_started)

    def _configured_execution_identity(self) -> tuple[int, int, str]:
        try:
            uid = int(self.state.get("RUNNER_UID"))
            gid = int(self.state.get("RUNNER_GID"))
        except (TypeError, ValueError) as exc:
            raise RunnerLiveTestError("IDENTITY_FAILURE", "Configured Runner UID/GID are not numeric") from exc
        username = self.state.get("RUNNER_USERNAME")
        if not isinstance(username, str) or not username.strip():
            raise RunnerLiveTestError("IDENTITY_FAILURE", "Configured Runner username is unavailable")
        return uid, gid, username.strip()

    @staticmethod
    def _execution_identity_matches(execution: dict[str, Any], expected: tuple[int, int, str]) -> bool:
        uid, gid, username = expected
        if execution.get("execution_uid") != uid or execution.get("execution_gid") != gid:
            return False
        jobs = execution.get("slurm_jobs")
        if jobs is not None and not isinstance(jobs, list):
            return False
        if jobs:
            return all(isinstance(job, dict) and job.get("scheduler_user") == username for job in jobs)
        return execution.get("scheduler_user") == username

    def _execute_in_worker(self, task_id: str, task_type: str, work_root: Path, request_path: Path | None = None, result_path: Path | None = None) -> dict[str, Any]:
        request_path = request_path or work_root / "live-test-request.json"
        result_path = result_path or work_root / "live-test-execution.json"
        # Build the candidate server image without touching running containers.
        # Compose run below then starts a one-off worker from this image.
        try:
            uid = self.state.get("RUNNER_UID") or "1000"
            gid = self.state.get("RUNNER_GID") or "1000"
            if not getattr(self.state, "_runner_live_server_image_prepared", False):
                build_web_images(self.state, detect_compose_cmd(), [], uid, gid)
                setattr(self.state, "_runner_live_server_image_prepared", True)
        except (OSError, subprocess.SubprocessError, SystemExit) as exc:
            raise RunnerLiveTestError("EXECUTION_FAILURE", f"candidate server image build failed: {exc}") from exc
        runner_mount = "/run/revocompute-candidate-runners"
        isolated_server_dir = Path(self.state.server_dir()) / "live-tests" / task_id
        command = [
            *detect_compose_cmd(), *self.state.compose_args(), "--env-file", self.state.env_file,
            "run", "--rm", "--no-deps", "-T",
            "-v", f"{request_path}:/run/revocompute-live/request.json:ro",
            "-v", f"{self.repo_root}:/run/revocompute-live/fixtures:ro",
            "-v", f"{self.artifact.resolve()}:/run/revocompute-live/artifact.sif:ro",
            "-v", f"{self.family.root.parent}:{runner_mount}:ro",
            "-e", f"SERVER_DIR={isolated_server_dir}",
            "-e", f"DB_PATH={isolated_server_dir}/live-test.sqlite3",
            "-e", f"MANAGE_DB_PATH={self.state.get('MANAGE_DB_PATH') or Path(self.state.server_dir()) / 'manage.sqlite'}",
            "-e", f"RUNNERS_DIR={runner_mount}",
            "-e", "REVOCOMPUTE_IMAGE_DIR=/run/revocompute-live",
            "-e", f"REVOCOMPUTE_RUNTIME_ARTIFACT_OVERRIDES={json.dumps({self.family.name: str(self.artifact.resolve())}, sort_keys=True)}",
            "-e", f"ENABLED_TASKRUNNERS={self.family.name}",
            "-e", "REVOCOMPUTE_LIVE_FIXTURES=/run/revocompute-live/fixtures",
            "worker", "python", "-m", "revocompute.live_test_executor", "/run/revocompute-live/request.json",
        ]
        result = run_cmd(command, env=self.state.exported(), check=False, capture=True)
        if result.returncode != 0:
            raise RunnerLiveTestError("EXECUTION_FAILURE", (result.stderr or result.stdout or "worker execution failed")[-2000:])
        try:
            output = (result.stdout or "").strip()
            evidence = json.loads(output.splitlines()[-1]) if output else json.loads(result_path.read_text(encoding="utf-8"))
        except (IndexError, json.JSONDecodeError) as exc:
            raise RunnerLiveTestError("EXECUTION_FAILURE", f"Worker returned no structured evidence: {exc}") from exc
        if not isinstance(evidence, dict):
            raise RunnerLiveTestError("EXECUTION_FAILURE", "Worker execution evidence is not an object")
        return evidence

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
            **{key: task[key] for key in ("execution_uid", "execution_gid", "scheduler_user", "slurm_jobs") if key in task},
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
    # Prepare the one-off worker image once for the complete invocation.  The
    # scientific candidate is the exact SIF; the server image is merely the
    # orchestration boundary and must not be rebuilt lazily for each family.
    if build:
        prepare_live_test_server_image(state)
    passed = True
    for family in selected:
        report = RunnerLiveTestWorker(state, family, collection=collection, task=task).run(build=build)
        passed = passed and report.passed
    # A successful case writes a new receipt, so the immutable admission
    # snapshot must be refreshed before the CLI returns.  Otherwise
    # runner-status can report READY while the API keeps rejecting submissions
    # from an older published attestation until the next full restart.
    from revocompute_ctl.readiness import load_instance_families, write_submission_attestation

    if passed:
        write_submission_attestation(state, load_instance_families(state))
    return passed


def prepare_live_test_server_image(state) -> None:
    """Build the one-off live-test worker image exactly once per invocation."""
    if getattr(state, "_runner_live_server_image_prepared", False):
        return
    try:
        uid = state.get("RUNNER_UID") or "1000"
        gid = state.get("RUNNER_GID") or "1000"
        build_web_images(state, detect_compose_cmd(), [], uid, gid)
        setattr(state, "_runner_live_server_image_prepared", True)
    except (OSError, subprocess.SubprocessError, SystemExit) as exc:
        raise RunnerLiveTestError("EXECUTION_FAILURE", f"candidate server image build failed: {exc}") from exc


def _family_owns_task(family: RuntimeFamily, task: str) -> bool:
    if family.root is None:
        return False
    doc = yaml.safe_load((family.root / "plugin.yaml").read_text(encoding="utf-8")) or {}
    for ref in doc.get("tasks", ()):
        task_doc = yaml.safe_load((family.root / ref).read_text(encoding="utf-8")) or {}
        if str(task_doc.get("id") or Path(ref).parent.name) == task:
            return True
    return False


def receipt_valid_for_artifact(
    state, family: RuntimeFamily, artifact_path: str | Path, *, sif_sha256: str | None = None
) -> bool:
    """Return whether required smoke tests passed for the exact artifact identity."""
    worker = RunnerLiveTestWorker(state, family, artifact_path=artifact_path)
    artifact = worker.artifact
    if not artifact.is_file() or not worker.receipt_path.is_file():
        return False
    try:
        receipt = json.loads(worker.receipt_path.read_text(encoding="utf-8"))
        identity = worker._load_identity()
        provenance = _build_provenance(state, family)
        required = {case.id for case in identity.plan.select("smoke")}
        return receipt_matches(
            receipt,
            sif_sha256=sif_sha256 or sha256_file(artifact),
            build_provenance_digest=str(provenance["build_provenance_digest"]),
            test_definition_digest=identity.plan.digest,
            configuration_digest=identity.configuration_digest,
            required_case_ids=required,
            expected_execution_uid=int(state.get("RUNNER_UID")) if state.get("RUNNER_UID") else None,
            expected_execution_gid=int(state.get("RUNNER_GID")) if state.get("RUNNER_GID") else None,
            expected_scheduler_user=state.get("RUNNER_USERNAME") or None,
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


def candidate_receipt_valid(state, family: RuntimeFamily, *, sif_sha256: str | None = None) -> bool:
    """Return whether required smoke tests passed for the staged candidate."""
    return receipt_valid_for_artifact(state, family, f"{family.slurm_image}.next", sif_sha256=sif_sha256)


def active_receipt_valid(state, family: RuntimeFamily, *, sif_sha256: str | None = None) -> bool:
    """Return whether required smoke tests passed for the active SIF."""
    return receipt_valid_for_artifact(state, family, family.slurm_image, sif_sha256=sif_sha256)
