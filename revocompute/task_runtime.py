# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Celery and compute task runtime.

This module is intentionally independent of Flask authentication.  Importing it
may initialize the shared task store and task directories, but never imports or
opens the user database.
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import mimetypes
import os
import re
import shutil
import signal
import stat
import subprocess
import threading
import time
import zipfile
from dataclasses import replace
from datetime import datetime, timezone
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

from celery import Celery
from revocompute.admission import resolve_submission_readiness
from revocompute.config import ComputeConfig, ensure_directories, env_csv, env_int, env_path
from revocompute.db import GPUAuthorizationUnavailableError, GPUCreditUnavailableError, TaskDatabase
from revocompute.infrastructure import (
    InfrastructureComponent,
    _gpu_inventory_probe,
    _slurm_controller_probe,
    _slurm_submission_probe,
    publish_worker_probe_snapshot,
)
from revocompute.job import Job, JobState
from revocompute.job.runners.slurm_runner import SlurmJob
from revocompute.ingress_security import (
    ARTIFACT_CAPACITY_GUARD,
    ARTIFACT_PUBLICATION_REJECTED,
    ValidationReceipt,
    snapshot_mismatch_reason,
)
from revocompute.input_validators.isolated_validation import VALIDATOR_RESOURCE_LIMIT_ERROR
from revocompute.manage_db import ManageDatabase  # noqa: E402
from revocompute.operational_events import emit_event
from revocompute import resource_ledger as rloan
from revocompute.resource_ledger import AdmissionReason, EvidenceSource, LedgerReason, ReservationReason
from revocompute.resource_observations import work_items_projection
from revocompute.resource_policy import ResolvedResources, ResourceValidationError
from revocompute.result_projection import artifact_capability
from revocompute.result_storyboard import (
    ResultContractError,
    declared_file_roles,
    expected_file_tree,
    resolve_expected_files,
    storyboard_declaration,
)
from revocompute.storage import (
    PUBLICATION_AVAILABLE,
    PUBLICATION_QUARANTINE_STATES,
    ArtifactIdentityError,
    ResultPublicationError,
    StorageResolver,
)
from revocompute.citations import citations_bibtex
from revocompute.task_types import default_task_type, get as _get_task_type
from revocompute.task_types import discover_plugins as _discover_plugins

CONFIG = ComputeConfig.from_env()
_manage_db = ManageDatabase(CONFIG.manage_db_path)

_redis_password = os.environ.get("REDIS_PASSWORD", "")
_redis_auth = f":{_redis_password}@" if _redis_password else ""
redis_url = os.environ.get("REDIS_URL", f"redis://{_redis_auth}localhost:6379/0")
celery = Celery(
    "revocompute",
    broker=os.environ.get("BROKER_URL", redis_url),
    backend=os.environ.get("RESULT_BACKEND", redis_url),
)
celery.conf.broker_connection_retry_on_startup = True

task_store = TaskDatabase(CONFIG.db_path)
ensure_directories(CONFIG.upload_folder, CONFIG.workspace_folder, CONFIG.results_folder)

# Discover deployed runner-family plugins — shared by web and worker processes.
_enabled_runners = set(env_csv("ENABLED_TASKRUNNERS", ""))
_discover_plugins(CONFIG.runners_dir, _enabled_runners)


def _get_job_executor() -> str:
    """Return the server-selected executor.

    Kept as a small seam for tests and older callers; the value is no longer
    loaded from the task registry.
    """
    return CONFIG.job_executor

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_TASK_ID_PATTERN = re.compile(r"[a-fA-F0-9]{32}$")
_ROOT_MOUNT_DIRECTORY = env_path("RUNNER_HOST_ROOT", os.path.dirname(CONFIG.server_dir))
ROOT_MOUNT_DIRECTORY = _ROOT_MOUNT_DIRECTORY

# ---------------------------------------------------------------------------
# Path utilities
# ---------------------------------------------------------------------------


def _path_is_within(base_dir: str, candidate: str) -> bool:
    """Lexical + symlink-aware containment.

    The lexical check is fast and works for not-yet-existing paths.  The
    second check resolves the base and the deepest existing ancestor of the
    candidate (`lexists` so a dangling symlink is caught too), so a symlink
    planted inside the base cannot point the real target outside it.
    """
    base_abs = os.path.abspath(base_dir)
    target_abs = os.path.abspath(candidate)
    try:
        if os.path.commonpath([base_abs, target_abs]) != base_abs:
            return False
    except ValueError:
        return False

    probe = target_abs
    tail_parts: list[str] = []
    while probe and not os.path.lexists(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        tail_parts.append(os.path.basename(probe))
        probe = parent
    resolved_target = os.path.realpath(os.path.join(probe, *reversed(tail_parts)))
    resolved_base = os.path.realpath(base_abs)
    try:
        return os.path.commonpath([resolved_base, resolved_target]) == resolved_base
    except ValueError:
        return False


def _safe_join(base_dir: str, *parts: str) -> str:
    candidate = os.path.abspath(os.path.join(base_dir, *parts))
    if not _path_is_within(base_dir, candidate):
        raise ValueError(f"Path escapes configured base directory: {candidate}")
    return candidate


def _normalize_task_id(raw_task_id: Any) -> str | None:
    task_id = str(raw_task_id or "").strip().lower()
    if not _TASK_ID_PATTERN.fullmatch(task_id):
        return None
    return task_id


def _sanitize_for_log(value: str, max_len: int = 4096) -> str:
    cleaned = _CONTROL_CHARS.sub(" ", value)
    cleaned = " ".join(cleaned.split())
    if len(cleaned) > max_len:
        return cleaned[: max_len - 3] + "..."
    return cleaned


def _local_user_identity() -> str:
    """Return username/group and uid/gid using in-process identity APIs."""
    import grp
    import pwd

    uid_num = os.getuid()
    gid_num = os.getgid()
    try:
        username = pwd.getpwuid(uid_num).pw_name
    except KeyError:
        username = str(uid_num)
    try:
        groupname = grp.getgrgid(gid_num).gr_name
    except KeyError:
        groupname = str(gid_num)
    return _sanitize_for_log(f"{username}:{groupname}-{uid_num}:{gid_num}", max_len=256)


# ---------------------------------------------------------------------------
# Task zip path — generic (not GREMLIN-specific)
# ---------------------------------------------------------------------------


def _task_zip_path(task: Any) -> str:
    if isinstance(task, str):
        stored = task_store.get_task(task)
        if stored is None:
            raise ValueError(f"Unknown task id for result archive: {task!r}")
        return _storage().get_archive_path(stored)
    else:
        return _storage().get_archive_path(task)


def _task_result_dir(task: dict[str, Any]) -> str:
    """Resolve the authoritative output root from the task scope."""
    return _storage().get_task_root(task)


def _storage() -> StorageResolver:
    """Build from current config so tests and controlled reloads stay isolated.

    The Task store is bound here because it owns the finalized-manifest
    publication anchor: a reader that could not reach it would be unable to
    verify that a manifest is the one Core published, and would refuse every
    publication.
    """
    return StorageResolver(CONFIG.results_folder, CONFIG.workspace_folder, task_store)


# Stream a verified artifact into the ZIP in bounded chunks: a scientific result
# can be gigabytes wide, so it is never held in memory to be archived.
_ARCHIVE_CHUNK_BYTES = 1024 * 1024
# The ZIP format stores MS-DOS timestamps, whose epoch is 1980; an older mtime
# (a restored archive, a clock-skewed runner host) must not fail the archive.
_ZIP_EPOCH = 315_532_800


def _write_manifest_entry(archive: zipfile.ZipFile, manifest_bytes: bytes) -> None:
    """Write the already-verified manifest bytes into the ZIP as ``manifest.json``.

    The bytes are the ones read from the verified descriptor that selected the
    artifact entries, so the archived manifest and the archive contents can
    never describe two different publications.
    """
    info = zipfile.ZipInfo("manifest.json", date_time=time.localtime()[0:6])
    info.compress_type = zipfile.ZIP_DEFLATED
    info.file_size = len(manifest_bytes)
    with archive.open(info, "w") as destination:
        destination.write(manifest_bytes)


def _write_verified_artifact(
    archive: zipfile.ZipFile, storage: StorageResolver, task: dict, manifest: dict, artifact: dict
) -> None:
    """Add one manifest-declared artifact from its verified open descriptor.

    The bytes reaching the ZIP are streamed from the same descriptor the
    published-artifact identity contract was checked on, so a file swapped after
    manifest finalization -- a new inode, a symlink, a hard-link substitute --
    cannot land in the download: ``open_verified_artifact`` refuses it before a
    byte is copied.
    """
    relative_path = artifact.get("path", "")
    resolved = storage.resolve_declared_artifact(task, relative_path, manifest)
    if resolved is None:
        # A path the manifest never declared -- an undeclared file, an escaping
        # relative path, a malformed entry -- is not a publication, so it is
        # refused here exactly like a swapped one.
        raise FileNotFoundError(f"Published result artifact is unavailable: {relative_path}")
    path, declared = resolved
    try:
        handle, _digest = storage.open_verified_artifact(path, declared)
    except (ArtifactIdentityError, OSError, ValueError) as exc:
        raise FileNotFoundError(f"Published result artifact is unavailable: {relative_path}") from exc
    with handle:
        status = os.fstat(handle.fileno())
        info = zipfile.ZipInfo(relative_path, date_time=time.localtime(max(status.st_mtime, _ZIP_EPOCH))[:6])
        info.compress_type = zipfile.ZIP_DEFLATED
        info.file_size = status.st_size
        # ``file_size`` is the verified size, so ``ZipFile`` can decide the ZIP64
        # format up front instead of striding the artifact through memory.
        with archive.open(info, "w") as destination:
            shutil.copyfileobj(handle, destination, _ARCHIVE_CHUNK_BYTES)


def _virtual_upload_path(filename: str) -> str:
    safe_name = os.path.basename(filename or "unknown")
    return f"/srv/REvoDesign/compute/upload/{safe_name}"


# ---------------------------------------------------------------------------
# Stage tracking
# ---------------------------------------------------------------------------


def _live_work_items(task: dict[str, Any]) -> dict[str, Any] | None:
    """Per-item detail from the runner's durable manifest, while it runs.

    The runner writes ``work_items.json`` into the same host result directory
    the worker sees, so the live view needs no extra channel.  Only a running
    task is read — a finalized task has the projection in its results manifest —
    and a missing or half-written file is simply "no detail yet".
    """
    if task.get("status") != "running":
        return None
    try:
        return work_items_projection(_task_result_dir(task))
    except Exception:
        # One task's unreadable manifest must not fail the dashboard (or every
        # admin's dashboard) nor the results-finalization path; the recorded
        # progress below is the fallback.
        logging.warning("Could not read live work items for task %s", task.get("md5sum"))
        return None


def _build_running_trace(task: dict[str, Any]) -> str:
    """Build a human-readable running trace from task stage markers."""
    if task.get("status") != "running":
        return ""
    task_type_name = task.get("task_type") or default_task_type()
    try:
        tt, _ = _get_task_type(task_type_name)
    except KeyError:
        return ""
    stages = list(tt.stage_markers.items())
    if not stages:
        return ""
    current_stage = str(task.get("run_stage") or stages[0][0]).strip().lower()
    stage_keys = [s[0] for s in stages]
    try:
        current_index = stage_keys.index(current_stage)
    except ValueError:
        current_index = 0
    lines: list[str] = []
    for index, (_, label) in enumerate(stages):
        if index < current_index:
            marker = "done"
        elif index == current_index:
            marker = "running"
        else:
            marker = "pending"
        lines.append(f"{label} [{marker}]")
    return "\n".join(lines)


def _progress_summary(task: dict[str, Any]) -> dict[str, Any] | None:
    """Per-item progress for one task, from the live manifest or the report.

    The runner's own ``REVODESIGN_PROGRESS`` line is the fallback: it survives
    the point where a result directory stops being readable, and for a failed
    allocation it is the only progress that ever existed.
    """
    live = _live_work_items(task)
    if live is not None:
        return {"progress": live.get("progress"), "outcome": live.get("outcome")}
    try:
        recorded = _task_execution_progress(task)
    except Exception:
        return None
    return recorded


def _task_execution_progress(task: dict[str, Any]) -> dict[str, Any] | None:
    """The runner's own last progress/outcome snapshot, recorded at poll time.

    The durable counterpart to the live manifest: it survives a result
    directory that is no longer readable and is the only progress a failed
    allocation ever produced.
    """
    recorded = task_store.get_task_progress(str(task.get("md5sum") or ""))
    if not recorded:
        return None
    return {"progress": recorded.get("progress") or None, "outcome": recorded.get("outcome") or None}


# ---------------------------------------------------------------------------
# Error sanitization
# ---------------------------------------------------------------------------


def _sanitize_task_error(task: dict[str, Any], error: Any) -> str | None:
    """Redact internal filesystem paths from errors exposed to clients."""
    if error is None:
        return None
    message = str(error)
    file_path = str(task.get("file_path") or "")
    if file_path:
        message = message.replace(file_path, _virtual_upload_path(task.get("filename", "unknown.fasta")))
    try:
        result_dir = _task_result_dir(task)
    except ValueError:
        result_dir = ""
    if result_dir and result_dir in message:
        message = message.replace(result_dir, "<result_dir>")
    if CONFIG.server_dir and CONFIG.server_dir in message:
        message = message.replace(CONFIG.server_dir, "<server_dir>")
    return message


# ---------------------------------------------------------------------------
# Job dispatch (Slurm / Apptainer)
# ---------------------------------------------------------------------------


def _create_job(
    task_id: str,
    tt,
    runner,
    entities: list[dict],
    output_dir: str,
    stage_callback=None,
    username: str = "",
    resource_policy: ResolvedResources | None = None,
    allocation_dispatched_callback=None,
    allocation_started_callback=None,
    allocation_finished_callback=None,
) -> Job:
    """Create the production Slurm/Apptainer job adapter."""
    return SlurmJob(
        task_id,
        tt,
        runner,
        entities,
        output_dir,
        stage_callback=stage_callback,
        manage_db=_manage_db,
        # The task-row store: the job writes runner-reported progress,
        # outcome, and resource observations into it.
        task_store=task_store,
        resource_policy=resource_policy,
        scratch_backend=CONFIG.scratch_backend,
        # The deployment's Runtime Bundle store, so the adapter resolves the
        # task's pinned digest exactly where the submission path recorded it.
        runtime_bundle_root=CONFIG.runtime_bundle_root,
        allocation_dispatched_callback=allocation_dispatched_callback,
        allocation_started_callback=allocation_started_callback,
        allocation_finished_callback=allocation_finished_callback,
    )


def _gpu_count(resource_policy: ResolvedResources) -> int:
    if not resource_policy.requires_gpu:
        return 0
    return rloan.units_for_gres(resource_policy.gres)


def _compute_allocation_callbacks(
    *,
    task_id: str,
    user_id: int,
    stage_id: str,
    resource_policy: ResolvedResources,
    required_entitlements: tuple[str, ...] = (),
    runner_family: str = "",
) -> tuple[Any, Any, Any]:
    """The three resource-accounting edges of one Slurm allocation.

    ``dispatched`` fires once the scheduler accepted the request: the Task's
    admission reservation stops being a pre-dispatch hold and becomes a
    scheduler-owned commitment, so a long queue wait can never free entitlement
    the request is about to consume.

    ``started`` fires when the allocation is observably running: it records the
    allocation the balance is actually charged for (which releases the
    reservation — the allocation, not the reservation, is the charge) and lets
    the wrapper proceed.

    ``finished`` settles.  Settlement always happens for an allocation that
    started, whatever the outcome: a failed or cancelled allocation consumed its
    CPUs and GPUs for the time they were held, so its measured elapsed time is a
    real charge and only *unknown* evidence stays unsettled.
    """
    gpu_count = _gpu_count(resource_policy)
    cpu_cores = max(1, int(resource_policy.cpus or 0))

    def dispatched(slurm_job_id: str, _dispatched_at: float) -> None:
        if user_id <= 0:
            return
        # The scheduler identity is persisted as part of this same transition,
        # so a queued reservation always carries the request's own name: a
        # maintenance pass reading it can never conclude "no request exists"
        # during the window before the Task row is updated.
        task_store.record_reservation_dispatch(task_id=task_id, slurm_job_id=str(slurm_job_id))

    def started(slurm_job_id: str, started_at: float) -> None:
        try:
            if runner_family and not resolve_submission_readiness(CONFIG.server_dir, runner_family).ready:
                raise GPUAuthorizationUnavailableError("Runner readiness is unavailable")
            # The quota decision is made *by* this call, inside one transaction
            # that also consumes the Task's own reservation and records the
            # allocation.  There is deliberately no separate entitlement read
            # here: a bare read cannot see that the hold which admitted this Task
            # is the Task's own authority, and would refuse it for holding the
            # final entitlement.
            entitlement = task_store.record_allocation_start(
                user_id=user_id,
                task_id=task_id,
                stage_id=stage_id,
                slurm_job_id=slurm_job_id,
                gpu_count=gpu_count,
                cpu_cores=cpu_cores,
                started_at=started_at,
                required_entitlements=required_entitlements,
                gres=resource_policy.gres or "",
            )
        except (GPUAuthorizationUnavailableError, GPUCreditUnavailableError) as exc:
            reason_code = AdmissionReason.COMPUTE_EXHAUSTED.value
            if isinstance(exc, GPUAuthorizationUnavailableError):
                reason_code = (
                    AdmissionReason.RUNNER_READINESS_UNAVAILABLE.value
                    if str(exc) == "Runner readiness is unavailable"
                    else AdmissionReason.AUTHORIZATION_UNAVAILABLE.value
                )
            emit_event(
                "resource.admission.denied",
                level="WARNING",
                reason_code=reason_code,
                task_id=task_id,
                stage_id=stage_id,
                slurm_job_id=slurm_job_id,
                user_id=user_id,
                gpu_count=gpu_count,
                gpu_seconds=0,
            )
            raise
        emit_event(
            "resource.admission.checked",
            task_id=task_id,
            stage_id=stage_id,
            slurm_job_id=slurm_job_id,
            user_id=user_id,
            gpu_count=gpu_count,
            gpu_seconds=max(0, int(entitlement.get("remaining_gpu_seconds") or 0)),
        )
        emit_event(
            "resource.allocation.started",
            task_id=task_id,
            stage_id=stage_id,
            slurm_job_id=slurm_job_id,
            user_id=user_id,
            gpu_count=gpu_count,
        )

    def finished(slurm_job_id: str, finished_at: float) -> None:
        # Settlement is a post-allocation accounting step, not part of the
        # scientific outcome: a temporary accounting failure must never rewrite
        # a completed Runner as a failed Task.  Keep the allocation recoverable
        # for reconciliation and surface it as evidence instead.
        try:
            allocation = task_store.settle_allocation(
                slurm_job_id, finished_at=finished_at
            )
        except Exception:
            logging.exception("GPU allocation settlement failed for Slurm job %s", slurm_job_id)
            try:
                task_store.mark_allocation_for_review(slurm_job_id)
            except Exception:
                logging.exception(
                    "Could not mark GPU allocation %s for review after settlement failure",
                    slurm_job_id,
                )
            emit_event(
                "resource.allocation.settlement_failed",
                level="ERROR",
                reason_code=LedgerReason.ACTUAL_ALLOCATION.value,
                task_id=task_id,
                stage_id=stage_id,
                slurm_job_id=slurm_job_id,
                user_id=user_id,
                gpu_count=gpu_count,
            )
            return
        emit_event(
            "resource.allocation.settled",
            task_id=task_id,
            stage_id=stage_id,
            slurm_job_id=slurm_job_id,
            user_id=user_id,
            gpu_count=gpu_count,
            gpu_seconds=int(allocation["quantity"] or 0),
        )

    return dispatched, started, finished


def _run_compute_job(
    task_id: str,
    tt,
    runner,
    entities: list[dict],
    output_dir: str,
    stage_callback=None,
    username: str = "",
    resource_policy: ResolvedResources | None = None,
) -> JobState:
    """Submit and poll through the production Slurm adapter."""
    dispatched_callback = started_callback = finished_callback = None
    stored_task = task_store.get_task(task_id) or {}
    submitted_by_user_id = int(stored_task.get("submitted_by_user_id") or 0)
    if resource_policy is not None and submitted_by_user_id > 0:
        # No entitlement read here: the decision belongs to the atomic
        # allocation-start transition, which knows whether this Task holds a
        # reservation of its own (the workflow and re-dispatch cases do not).
        dispatched_callback, started_callback, finished_callback = _compute_allocation_callbacks(
            task_id=task_id,
            user_id=submitted_by_user_id,
            stage_id=tt.name,
            resource_policy=resource_policy,
            required_entitlements=(tt.runtime.access_policy.requires if tt.runtime.access_policy else ()),
            runner_family=tt.runtime.name,
        )
    job = _create_job(
        task_id,
        tt,
        runner,
        entities,
        output_dir,
        stage_callback,
        username=username,
        resource_policy=resource_policy,
        allocation_dispatched_callback=dispatched_callback,
        allocation_started_callback=started_callback,
        allocation_finished_callback=finished_callback,
    )
    jid = job.submit()
    # Persist the job handle so cancel can stop the running process even
    # after a server restart (Celery/Redis state is ephemeral).
    if jid:
        if isinstance(job, SlurmJob):
            task_store.update_task(task_id, slurm_job_id=jid)
    state = job.poll()
    if isinstance(job, SlurmJob) and not job.allocation_started:
        # The request never held a running allocation: it was queued and then
        # cancelled, rejected, or lost.  No allocation was ever recorded for it,
        # so its scheduler-owned reservation would otherwise stay committed
        # forever.  Release it now.  A request that did run had its reservation
        # consumed by the allocation start, so this release is a no-op there.
        task_store.release_reservation(
            task_id=task_id, reason_code=ReservationReason.RELEASED.value, at=time.time()
        )
    return state


def _workflow_state(task: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = task.get("workflow_state")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _run_compute_workflow(
    task_id: str,
    task: dict[str, Any],
    tt,
    runner,
    entities: list[dict],
    output_dir: str,
    resource_policies: dict[str, ResolvedResources],
    stage_callback,
) -> JobState:
    """Run an ordered workflow through the existing one-allocation Job API."""
    state = _workflow_state(task)
    for stage in tt.workflow:
        previous = state.get(stage.name, {})
        if previous.get("status") == "completed":
            continue
        policy = resource_policies.get(stage.name)
        if policy is None:
            raise ResourceValidationError(f"Workflow stage {stage.name!r} has no resource snapshot")
        markers = {name: tt.stage_markers[name] for name in stage.stage_markers}
        stage_tt = replace(
            tt,
            name=stage.name.replace(".", "-"),
            runner_args=stage.runner_args,
            gpus=stage.requires_gpu,
            requires_network=stage.requires_network,
            stage_markers=markers,
            workflow=(),
        )
        first_marker = next(iter(markers))
        if not task_store.update_task(task_id, status="queued", run_stage=first_marker):
            return JobState.CANCELLED
        dispatched_callback = started_callback = finished_callback = None
        user_id = int(task.get("submitted_by_user_id") or 0)
        if user_id > 0:
            # A workflow stage has no reservation of its own after the first
            # one consumed the Task's single submission hold, so its allocation
            # start is admitted on the balance that is actually left — decided
            # atomically with the allocation itself, not by a read here.
            dispatched_callback, started_callback, finished_callback = _compute_allocation_callbacks(
                task_id=task_id,
                user_id=user_id,
                stage_id=stage.name,
                resource_policy=policy,
                required_entitlements=(tt.runtime.access_policy.requires if tt.runtime.access_policy else ()),
                runner_family=tt.runtime.name,
            )
        job = _create_job(
            task_id,
            stage_tt,
            runner,
            entities,
            output_dir,
            stage_callback,
            username=task.get("username", ""),
            resource_policy=policy,
            allocation_dispatched_callback=dispatched_callback,
            allocation_started_callback=started_callback,
            allocation_finished_callback=finished_callback,
        )
        jid = job.submit()
        state[stage.name] = {"status": "running", "job_id": jid, "started_at": time.time()}
        handles = {"workflow_state": json.dumps(state, sort_keys=True)}
        if isinstance(job, SlurmJob):
            handles["slurm_job_id"] = jid
        if not task_store.update_task(task_id, **handles):
            job.cancel()
            return JobState.CANCELLED
        result = job.poll()
        if isinstance(job, SlurmJob) and not job.allocation_started:
            # This stage never held a running allocation, so no allocation fact
            # exists for it and the Task's scheduler-owned reservation (if it is
            # still the one from the first stage) must go back rather than stay
            # committed with nothing left to consume it.
            task_store.release_reservation(
                task_id=task_id, reason_code=ReservationReason.RELEASED.value, at=time.time()
            )
        state[stage.name].update(status=result.value, finished_at=time.time())
        task_store.update_task(
            task_id,
            workflow_state=json.dumps(state, sort_keys=True),
            slurm_job_id=None,
            container_id=None,
        )
        if result != JobState.COMPLETED:
            return result
    return JobState.COMPLETED


# ---------------------------------------------------------------------------
# Result finalization and optional archive cache
# ---------------------------------------------------------------------------


_TEXT_PREVIEW_EXTENSIONS = {
    ".a3m",
    ".aln",
    ".bib",
    ".bibtex",
    ".csv",
    ".fa",
    ".faa",
    ".fasta",
    ".json",
    ".log",
    ".md",
    ".mrf",
    ".pdb",
    ".sto",
    ".tsv",
    ".txt",
    ".yaml",
    ".yml",
}
_STRUCTURE_PREVIEW_EXTENSIONS = {".cif", ".mmcif", ".pdb"}
_IMAGE_PREVIEW_EXTENSIONS = {".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"}


# PTC-W6004: internal utility — callers pass server-built snapshot paths only
def _sha256_file(path: str) -> str:  # skipcq: PTC-W6004
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _preview_kind(relative_path: str) -> str | None:
    extension = os.path.splitext(relative_path)[1].lower()
    if extension in _STRUCTURE_PREVIEW_EXTENSIONS:
        return "structure"
    if extension in _IMAGE_PREVIEW_EXTENSIONS:
        return "image"
    if extension in {".csv", ".tsv"}:
        return "table"
    if extension in _TEXT_PREVIEW_EXTENSIONS:
        return "text"
    return None


def _iso_timestamp(value: Any) -> str | None:
    try:
        return datetime.fromtimestamp(float(value)).astimezone().isoformat() if value is not None else None
    except (TypeError, ValueError, OSError):
        return None


def _public_run_record(task: dict[str, Any], task_type: Any, finished_at: float) -> dict[str, Any]:
    raw_form = task.get("input_form")
    try:
        form = json.loads(raw_form) if isinstance(raw_form, str) else raw_form
    except (json.JSONDecodeError, TypeError):
        form = {}
    form = form if isinstance(form, dict) else {}
    entities = form.get("entities") if isinstance(form.get("entities"), list) else []
    params_by_name = {parameter.name: parameter for parameter in task_type.params} if task_type else {}
    inputs = [
        {
            "role": str(entity.get("role") or ""),
            "path": str(entity.get("relative_path") or entity.get("verified_value") or ""),
            "sha256": str(entity.get("hash") or ""),
            "format": str(entity.get("format") or ""),
            "logical_type": str(entity.get("logical_type") or ""),
        }
        for entity in entities
        if entity.get("type") == "file" and (entity.get("relative_path") or entity.get("verified_value"))
    ]
    parameters = []
    for entity in entities:
        if entity.get("type") == "file" or not entity.get("name"):
            continue
        definition = params_by_name.get(entity["name"])
        parameters.append(
            {
                "name": entity["name"],
                "label": (
                    definition.label or entity["name"].replace("_", " ").title()
                    if definition
                    else entity["name"].replace("_", " ").title()
                ),
                "value": entity.get("verified_value", entity.get("value")),
                "unit": definition.unit if definition else "",
            }
        )
    started_at = task.get("started_at")
    walltime = (
        max(finished_at - float(started_at), 0.0) if isinstance(started_at, (int, float)) else task.get("walltime")
    )
    return {
        "method": {
            "id": task.get("task_type") or default_task_type(),
            "name": task_type.display_name if task_type else task.get("task_type") or default_task_type(),
            "summary": task_type.summary if task_type else "",
            "output_summary": task_type.output_summary if task_type else "",
        },
        "inputs": inputs,
        "parameters": parameters,
        "submitted_at": form.get("submitted_at") or _iso_timestamp(task.get("uploaded_at")),
        "started_at": _iso_timestamp(started_at),
        "finished_at": _iso_timestamp(finished_at),
        "walltime_seconds": walltime,
        "citations": (
            [citation.projection() for citation in task_type.citations]
            if task_type
            else []
        ),
    }


# The runner's own completion sentinel.  Every runner family writes it as the
# terminal ``task_finished`` path segment when (and only when) its work
# succeeded, and ``slurm_runner._has_result_artifact`` already ignores it when
# deciding whether an allocation produced a real result — so it is operational
# state, not a scientific artifact, and must not be published to users.  The
# match is on the terminal path segment, exactly as ``_has_result_artifact``
# matches the basename, because the sentinel lives at a family-chosen depth; a
# file that merely contains the string is still published.  No frontend code
# may special-case this name.  ``task_failed.txt`` is different: the server
# writes that report itself for failed runs, so it stays published as a
# diagnostic.
_COMPLETION_SENTINEL = "task_finished"

# Publication capacity guards.  Runner output is an untrusted filesystem
# namespace, so the manifest the Server registers is bounded in both entry count
# and aggregate bytes rather than assumed to be a scientific result set.  The
# limits are server-owned configuration (``ComputeConfig.max_published_*``), not
# module constants, so a deployment that ships a genuinely larger family raises
# them instead of having its manifest silently truncated.
def _published_artifact_limit() -> int:
    return CONFIG.max_published_artifacts


def _published_byte_limit() -> int:
    return CONFIG.max_published_bytes


#: How many refused result entries are named individually in the output check
#: before the rest are summarized as a count.  The manifest is the durable
#: record, so it must describe that a tree was refused without becoming one
#: entry per hostile file.
_MAX_RECORDED_REFUSALS = 20


def _publishable_artifact(path: str, relative_path: str) -> tuple[dict[str, Any] | None, str | None]:
    """Return ``(artifact_record, reason)`` for one candidate under the result root.

    Publication never follows a link and never registers a non-regular file.
    The record's size and digest are taken from one descriptor opened with
    ``O_NOFOLLOW`` and verified ``fstat``-regular, so the bytes hashed are the
    bytes the manifest names: a swap between the type check and the read cannot
    substitute a different inode.
    """
    try:
        info = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        return None, f"unreadable ({exc.__class__.__name__})"
    if stat.S_ISLNK(info.st_mode):
        return None, "symbolic link"
    if not stat.S_ISREG(info.st_mode):
        return None, "special file"
    if info.st_nlink != 1:
        return None, "hard link"
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        return None, f"unreadable ({exc.__class__.__name__})"
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            return None, "not a private regular file"
        digest = hashlib.sha256()
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        return None, f"unreadable ({exc.__class__.__name__})"
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    preview = _preview_kind(relative_path)
    return (
        {
            "path": relative_path,
            "size": opened.st_size,
            "sha256": digest.hexdigest(),
            "media_type": mimetypes.guess_type(relative_path)[0] or "application/octet-stream",
            "preview": preview,
            "capability": artifact_capability(preview),
            "role": _default_artifact_role(relative_path),
        },
        None,
    )


def _revalidate_blob(fe: dict[str, Any], physical_path: str) -> str | None:
    """Re-run the canonical Core boundary on one input's bytes.

    This is the actual admission decision for the bytes about to execute.  It is
    run for every input — a row that predates receipts and a row that carries one
    alike — so a forged or stale receipt can never stand in for real validation.
    Returns a bounded reason code when the bytes do not validate.
    """
    from revocompute.input_validators import validate_input_file, validate_logical_input

    logical_type = str(fe.get("logical_type") or "file")
    format_name = str(fe.get("format") or "")
    relative_path = str(fe.get("relative_path") or fe.get("value") or "")
    error = validate_input_file(physical_path, relative_path, logical_type=logical_type)
    if error is None:
        error = validate_logical_input(physical_path, format_name, logical_type)
    if error is not None:
        logging.error("Input failed Core revalidation before dispatch: %s", error)
        return VALIDATOR_RESOURCE_LIMIT_ERROR if error == VALIDATOR_RESOURCE_LIMIT_ERROR else "input_snapshot_mismatch"
    return None


def _verify_snapshot(fe: dict[str, Any], snapshot_path: str, receipt: Any) -> str | None:
    """Prove the snapshot is a Core-admitted byte stream, or return a reason code.

    Two independent checks, and revalidation is mandatory rather than skipped:
    the receipt (when present) proves the snapshot is the exact immutable byte
    stream admission recorded, and the canonical boundary is re-run on those
    bytes so a forged or stale receipt cannot substitute a decision for real
    validation.  This is what lets ``_derive_task_id`` trust a duplicate
    submission as reproducible: the id is only reusable when the bytes and the
    boundary that admitted them are the same.
    """
    receipt_reason = snapshot_mismatch_reason(receipt, snapshot_path) if isinstance(receipt, dict) else None
    if receipt_reason is not None:
        return receipt_reason
    return _revalidate_blob(fe, snapshot_path)


def _default_artifact_role(relative_path: str) -> str:
    basename = os.path.basename(relative_path)
    if relative_path == "citations.bib" or relative_path.startswith("debug/"):
        return "provenance"
    if (
        relative_path.startswith(("execution/", "log/"))
        or basename == "task_failed.txt"
        or (basename.startswith(".") and basename.endswith("-complete"))
        or relative_path.endswith((".stderr.log", ".stdout.log", ".err"))
    ):
        return "diagnostic"
    return "artifact"


def _json_path(value: Any, path: str) -> Any:
    for part in path.split(".") if path else ():
        if isinstance(value, list) and part.isdigit():
            index = int(part)
            if index >= len(value):
                raise KeyError(path)
            value = value[index]
        elif isinstance(value, dict) and part in value:
            value = value[part]
        else:
            raise KeyError(path)
    return value


def _validate_scientific_view(
    definition: Any,
    sources: dict[str, list[str]],
    result_dir: str,
) -> list[str]:
    """Check resolved files against the declared protocol, without task-name branches."""
    problems: list[str] = []
    singular = {
        "alignment": ("alignment",),
    }.get(definition.plugin, ())
    for source in singular:
        if len(sources.get(source, [])) != 1:
            problems.append(f"{definition.title}: {source} source must resolve to exactly one artifact")
    if problems:
        return problems

    if definition.plugin == "entity-table":
        tables = sources.get("table", [])
        structures = sources.get("structure", [])
        if len(tables) != 1:
            problems.append(f"{definition.title}: table source must resolve to exactly one artifact")
        if len(structures) > 1:
            problems.append(f"{definition.title}: structure source must resolve to at most one artifact")
        if len(tables) == 1:
            delimiter = "\t" if tables[0].lower().endswith(".tsv") else ","
            try:
                with open(_safe_join(result_dir, *tables[0].split("/")), newline="", encoding="utf-8") as handle:
                    columns = next(csv.reader(handle, delimiter=delimiter), [])
            except (OSError, UnicodeError, csv.Error):
                columns = []
            required_columns = set(definition.mapping.get("key_columns", []))
            required_columns.update(definition.mapping.get("evidence_columns", []))
            required_columns.update(
                definition.mapping[key]
                for key in ("label_column", "chain_column", "residue_column")
                if definition.mapping.get(key)
            )
            missing = sorted(required_columns - set(columns))
            if missing:
                problems.append(f"{definition.title}: table is missing columns {', '.join(missing)}")
        return problems

    if definition.plugin == "trajectory":
        topologies = sources.get("topology", [])
        coordinates = sources.get("coordinates", [])
        if definition.mapping["association"] == "single" and (len(topologies) != 1 or len(coordinates) != 1):
            problems.append(
                f"{definition.title}: single association requires exactly one topology and coordinate artifact"
            )
        elif definition.mapping["association"] == "stem-prefix":
            stems = [os.path.splitext(os.path.basename(path))[0] for path in topologies]
            for path in coordinates:
                name = os.path.basename(path)
                if not any(name.startswith(f"{stem}_") for stem in stems):
                    problems.append(f"{definition.title}: coordinate {path} has no declared topology association")
        expected_suffix = f".{definition.mapping['coordinate_format']}"
        if any(not path.lower().endswith(expected_suffix) for path in coordinates):
            problems.append(f"{definition.title}: coordinate format does not match the declared artifacts")
        return problems

    paths = sources.get("series", []) if definition.plugin == "metric-series" else sources.get("matrices", [])
    if definition.plugin == "scalar-summary":
        paths = sources["data"]
    if definition.plugin not in {"metric-series", "matrix", "scalar-summary"}:
        return problems
    for relative_path in paths:
        path = _safe_join(result_dir, *relative_path.split("/"))
        try:
            if definition.mapping.get("format") == "csv":
                with open(path, newline="", encoding="utf-8") as handle:
                    columns = next(csv.reader(handle), [])
                required = set(definition.mapping.get("value_columns", []))
                required.add(definition.mapping.get("x_column") or definition.mapping.get("row_labels_column"))
                missing = sorted(column for column in required if column and column not in columns)
                if missing:
                    problems.append(f"{definition.title}: data is missing columns {', '.join(missing)}")
                continue
            if os.path.getsize(path) > 8 * 1024 * 1024:
                problems.append(f"{definition.title}: JSON source exceeds the 8 MiB scientific-view limit")
                continue
            with open(path, encoding="utf-8") as handle:
                payload = json.load(handle)
            if definition.plugin == "scalar-summary":
                values = [
                    (_json_path(payload, field["path"]), field)
                    for field in definition.mapping["fields"]
                ]
                if any(
                    isinstance(value, (dict, list)) or (value is None and not field.get("nullable", False))
                    for value, field in values
                ):
                    raise ValueError("scalar fields must resolve to values")
            else:
                values = _json_path(payload, definition.mapping["value_path"])
                if not isinstance(values, list) or (
                    definition.plugin == "matrix" and values and not all(isinstance(row, list) for row in values)
                ):
                    raise ValueError("declared numeric data has the wrong shape")
        except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            problems.append(f"{definition.title}: declared data mapping could not be resolved")
    return problems


def _resolve_result_views(
    task_type: Any,
    artifacts: list[dict[str, Any]],
    result_dir: str,
    declared_roles: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    declared_roles = declared_roles or {}
    views: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    problems: list[str] = []
    # A runner's declared role covers every file it published, not only the ones
    # that happen to be a source of a declared view — otherwise its evidence,
    # provenance, and diagnostic files fall back to the generic default and land
    # among unrelated "other files".  Applying it first gives the precedence:
    # the primary view below still owns ``primary``, and a declaration never
    # downgrades an already-published provenance/diagnostic artifact to
    # evidence.
    for artifact in artifacts:
        declared = declared_roles.get(artifact["path"])
        if not declared:
            continue
        if declared == "evidence" and artifact["role"] in {"provenance", "diagnostic"}:
            continue
        artifact["role"] = declared
    if task_type is None or not task_type.result_workspace:
        return views, checks, problems
    paths = [artifact["path"] for artifact in artifacts]
    artifact_by_path = {artifact["path"]: artifact for artifact in artifacts}
    for definition in task_type.result_workspace:
        resolved_sources: dict[str, list[str]] = {}
        for source_name, selectors in definition.sources.items():
            matches: list[str] = []
            for selector in selectors:
                selected = (
                    [path for path in paths if fnmatchcase(path, selector.value)]
                    if selector.is_glob
                    else [selector.value] if selector.value in artifact_by_path else []
                )
                if len(selected) > 500:
                    problems.append(f"{definition.title}: {source_name} matched more than 500 artifacts")
                    selected = selected[:500]
                nonempty = [path for path in selected if artifact_by_path[path]["size"] > 0]
                status = "passed" if nonempty or not selector.required else "failed"
                checks.append(
                    {
                        "view_id": definition.id,
                        "source": source_name,
                        "required": selector.required,
                        "status": status,
                        "matched": len(nonempty),
                    }
                )
                if selector.required and not nonempty:
                    problems.append(f"{definition.title}: required {source_name} output is missing or empty")
                matches.extend(nonempty)
            resolved_sources[source_name] = list(dict.fromkeys(matches))
        problems.extend(_validate_scientific_view(definition, resolved_sources, result_dir))
        view = {
            "id": definition.id,
            "plugin": definition.plugin,
            "role": definition.role,
            "title": definition.title,
            "description": definition.description,
            "sources": resolved_sources,
            "mapping": definition.mapping,
        }
        views.append(view)
        confidence_encoding = definition.mapping.get("confidence_encoding")
        if confidence_encoding:
            for path in resolved_sources.get("candidates", ()):
                artifact_by_path[path]["confidence_encoding"] = confidence_encoding
        artifact_role = "primary" if definition.role == "primary" else "evidence"
        for source_name, source_paths in resolved_sources.items():
            role = "evidence" if source_name == "supporting" else artifact_role
            for path in source_paths:
                artifact = artifact_by_path[path]
                # Final published role precedence: the primary view owns
                # ``primary``; an artifact already published as provenance or
                # diagnostic is never downgraded to evidence; otherwise the
                # runner's own ``role:`` declaration in expected_files.yaml
                # wins over plain view membership, and the server's default
                # classification is the last resort.
                if role == "primary":
                    artifact["role"] = "primary"
                    continue
                resolved_role = declared_roles.get(path) or role
                if artifact["role"] in {"provenance", "diagnostic", "primary"}:
                    continue
                artifact["role"] = resolved_role
    return views, checks, list(dict.fromkeys(problems))


def _anchor_result_manifest(task: dict[str, Any], payload: bytes, *, published_at: float) -> None:
    """Record the finalized manifest's identity in server-owned state.

    This is the one piece of publication identity that does not live under the
    result root.  ``StorageResolver`` reads it back on every manifest read, so a
    replacement manifest -- a valid single-link regular JSON file that declares
    its own artifacts, sizes, and digests -- cannot redefine the published
    namespace: the anchor describes what Core published, and the replacement
    does not match it.

    Anchoring is part of publication, not a best-effort side effect of it: a
    manifest without this record is one Core's own reader refuses, so a
    persistence failure is raised as :class:`ResultPublicationError` and the
    caller publishes nothing.  Swallowing it would leave a finished task and a
    ``manifest.published`` event asserting a publication that no consumer can
    read.
    """
    try:
        task_store.record_result_publication(
            str(task["md5sum"]),
            manifest_sha256=hashlib.sha256(payload).hexdigest(),
            manifest_size=len(payload),
            published_at=published_at,
        )
    except Exception as exc:  # pylint: disable=broad-except
        raise ResultPublicationError(
            f"result manifest anchor could not be recorded for task {task.get('md5sum')}: {exc}"
        ) from exc


def _finalize_results_manifest(
    task: dict[str, Any],
    *,
    execution_state: str,
    finished_at: float,
) -> dict[str, Any]:
    """Atomically publish the immutable scientific result record for a task."""
    if execution_state not in {"completed", "failed"}:
        raise ValueError("execution_state must be completed or failed")
    if not _data_still_owned(str(task["md5sum"])):
        # The data lifecycle moved on while this worker was finishing: the Task's
        # durable data was already deleted, or its deletion is in flight.  A
        # worker that re-created ``manifest.json`` here would re-materialize the
        # tree a purge had just removed and charge the subject for it, defeating
        # the deletion the user — or an Admin — authorized.  The execution
        # lifecycle and the data lifecycle are orthogonal, and this is the one
        # place they touch, so the durable row is authoritative.
        raise DataPurgedError(str(task["md5sum"]))
    result_dir = _task_result_dir(task)
    os.makedirs(result_dir, exist_ok=True)
    try:
        task_type, _ = _get_task_type(task.get("task_type") or default_task_type())
    except KeyError:
        task_type = None
    if task_type is not None and task_type.citations:
        with open(os.path.join(result_dir, "citations.bib"), "w", encoding="utf-8") as handle:
            handle.write(citations_bibtex(task_type.citations))
    artifacts: list[dict[str, Any]] = []
    publication_problems: list[str] = []
    publication_capacity_guard = False
    total_published_bytes = 0
    published_paths: set[str] = set()
    skipped_unpublishable = 0
    for root, dirs, files in os.walk(result_dir, followlinks=False):
        if publication_capacity_guard:
            # The tree is over capacity: stop walking rather than re-tripping
            # the guard once per remaining directory, which would grow the
            # manifest's ``problems`` list one entry at a time for an untrusted
            # tree.  The capacity problem is recorded once, below.
            break
        dirs[:] = sorted(directory for directory in dirs if not os.path.islink(os.path.join(root, directory)))
        for filename in sorted(files):
            path = os.path.join(root, filename)
            relative_path = os.path.relpath(path, result_dir).replace(os.sep, "/")
            if relative_path in {"manifest.json", ".manifest.json.tmp"}:
                continue
            if filename == _COMPLETION_SENTINEL:
                # The runner's execution sentinel is not a published artifact.
                continue
            if relative_path in published_paths:
                # Two walked paths cannot collide on one filesystem, but a
                # case-insensitive or otherwise aliasing mount could still hand
                # the manifest one logical path twice; the manifest is the
                # published namespace and must stay a set.
                publication_problems.append(f"Duplicate published artifact path: {relative_path}")
                continue
            record, reason = _publishable_artifact(path, relative_path)
            if record is None:
                # A symlink, hard link, special file, or unreadable entry is not
                # a publishable artifact.  It is excluded — never followed, never
                # downgraded to "publish whatever is there".  The first few are
                # named so the output check says which file was refused; the
                # remainder are counted, so an untrusted tree cannot grow the
                # manifest one detail entry per file.
                skipped_unpublishable += 1
                if len(publication_problems) < _MAX_RECORDED_REFUSALS:
                    publication_problems.append(
                        f"Rejected non-publishable result entry {relative_path}: {reason}"
                    )
                continue
            if len(artifacts) >= _published_artifact_limit():
                publication_capacity_guard = True
                break
            total_published_bytes += record["size"]
            if total_published_bytes > _published_byte_limit():
                publication_capacity_guard = True
                break
            published_paths.add(relative_path)
            artifacts.append(record)
    if publication_capacity_guard:
        # One bounded entry per guard, whether the ceiling is the artifact count
        # or the aggregate bytes; the walk above has already stopped.
        limit = (
            _published_artifact_limit()
            if len(artifacts) >= _published_artifact_limit()
            else _published_byte_limit()
        )
        publication_problems.append(f"Result tree exceeds the {limit} publication capacity limit")
    if skipped_unpublishable > _MAX_RECORDED_REFUSALS:
        remainder = skipped_unpublishable - _MAX_RECORDED_REFUSALS
        publication_problems.append(f"... and {remainder} further non-publishable result entries were refused")
    # The runner owns its files' presentation roles in expected_files.yaml.
    # Read that declaration first so view resolution can rank it, but resolve
    # the views before building the logical-file projection: view resolution
    # attaches task-declared annotations (such as a structure's confidence
    # encoding) that the logical-file copy must carry.
    tree: dict[str, dict[str, Any]] | None = None
    declared_roles: dict[str, str] = {}
    logical_files: dict[str, list[dict[str, Any]]] = {}
    storyboard = None
    checks: list[dict[str, Any]] = []
    problems: list[str] = []
    # Publication rejections are reported in the same bounded ``problems`` list
    # the output check already carries, so a refused symlink, hard link, special
    # file, or over-capacity tree fails the output check instead of disappearing.
    problems.extend(publication_problems)
    if task_type is not None:
        try:
            tree = expected_file_tree(task_type, CONFIG.server_dir)
            declared_roles = declared_file_roles(tree, [item["path"] for item in artifacts])
        except ResultContractError as exc:
            problems.append(f"Result contract is invalid: {exc}")
    views, view_checks, view_problems = _resolve_result_views(task_type, artifacts, result_dir, declared_roles)
    checks.extend(view_checks)
    problems.extend(view_problems)
    if tree is not None:
        try:
            logical_files, tree_checks, tree_problems = resolve_expected_files(tree, artifacts)
            checks.extend(tree_checks)
            problems.extend(tree_problems)
            declaration = storyboard_declaration(task_type, CONFIG.server_dir, set(tree))
            if declaration is not None:
                storyboard = declaration
        except ResultContractError as exc:
            problems.append(f"Result contract is invalid: {exc}")
    if execution_state == "failed":
        output_state = "not_assessed"
    elif task_type is None or (not task_type.result_workspace and not logical_files and not problems):
        output_state = "not_configured"
    else:
        output_state = "failed" if problems else "passed"
    manifest = {
        "schema_version": 3,
        "task_id": task["md5sum"],
        "task_type": task.get("task_type") or default_task_type(),
        "created_at": _iso_timestamp(finished_at),
        "run": _public_run_record(task, task_type, finished_at),
        "output_check": {"state": output_state, "checks": checks, "problems": problems},
        "limitations": list(task_type.considerations) if task_type else [],
        "artifacts": artifacts,
        "views": views,
        "result": {"files": logical_files},
        "storyboard": storyboard,
        "total_size": sum(item["size"] for item in artifacts),
    }
    # Per-item state is published only when the runner produced it; a single
    # input task keeps ``outcome`` null and carries no work-item list, which is
    # what "the task's own exit status is the outcome" means on the wire.
    try:
        per_item = work_items_projection(result_dir)
    except Exception:
        # A hostile or unexpected result tree must not leave a task without its
        # results manifest at all — the manifest is the durable record.
        logging.warning("Could not project work items for task %s", task.get("md5sum"))
        per_item = None
    if per_item is not None:
        manifest["outcome"] = per_item["outcome"]
        manifest["work_items"] = per_item["work_items"]
        manifest["progress"] = per_item["progress"]
    else:
        manifest["outcome"] = None
    # A PARTIAL_SUCCESS task is finalized exactly like any other: the task ran
    # to completion and published everything it has.  The standardized outcome
    # is a presentation/consumer vocabulary, not a new tasks.status.
    #
    # A rejected or over-capacity publication entry is already recorded in
    # ``problems``, so the output check reflects it: the manifest never claims a
    # passed result set that silently dropped files it could not safely publish,
    # and a tree with only refused entries still publishes a valid manifest (with
    # no artifacts) rather than degrading to "publish the unsafe tree".
    temporary = _safe_join(result_dir, ".manifest.json.tmp")
    destination = _safe_join(result_dir, "manifest.json")
    # One serialization, written once: the bytes anchored below are the exact
    # bytes published, not a second serialization that could differ from them.
    payload = json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    encoded = payload.encode("utf-8")
    with open(temporary, "w", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    # The manifest is self-describing — it declares its artifacts, their sizes,
    # and their digests — and it is written by the runner's Unix identity inside
    # the runner-owned result tree, so nothing *in* that tree can say whether the
    # file just published is the one Core finalized.  Anchoring the finalized
    # bytes in server-owned state is what makes that question answerable: every
    # later read of the manifest is checked against this record, so a
    # post-finalization replacement (which could otherwise declare its own sizes
    # and digests and thereby authorize its own publication) fails closed.
    #
    # The anchor is established BEFORE the bytes become visible at the canonical
    # path, and both happen before any publication is claimed.  The order matters
    # at the split point, and both directions are bounded and honest: an anchor
    # failure removes the candidate bytes, leaves no canonical manifest, no
    # event, and a task that is not finished; a crash between the two steps
    # leaves the anchor ahead of the bytes, which a reader reports as
    # ``manifest_missing`` (nothing published at the canonical path yet) or
    # ``anchor_mismatch`` (a re-publication whose bytes had not landed) -- never
    # as an available result, and never as an available result that is wrong.  A
    # later publication of the same task supersedes the abandoned anchor.
    try:
        _anchor_result_manifest(task, encoded, published_at=finished_at)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    os.replace(temporary, destination)
    _charge_logical_storage(task, manifest, result_dir)
    emit_event(
        "manifest.published",
        request_id=_task_request_id(task),
        task_id=str(task["md5sum"]),
        task_type=str(task.get("task_type") or default_task_type()),
        # The single owning vocabulary carries the publication outcome: a
        # rejected entry makes the published manifest's output check fail and
        # names that reason here, instead of a parallel event for the same fact.
        reason_code=(
            (ARTIFACT_CAPACITY_GUARD if publication_capacity_guard else ARTIFACT_PUBLICATION_REJECTED)
            if publication_problems
            else None
        ),
    )
    return manifest


def _abandon_published_result(task: dict[str, Any], result_dir: str) -> None:
    """Remove the result tree a purge authorized while this worker was finishing.

    The publishing worker rebuilt ``result_dir`` (and its execution directory,
    which lives under the results tree) after a purge had removed them.  Every
    byte it wrote is disposable — the completed computation, its Slurm stdout,
    and its observations are independent of these files — and the accepted
    deletion must not be undone by a worker that simply walked faster.  The walk
    is unprivileged because the worker owns the tree it just wrote.
    """
    for path in (result_dir, os.path.join(result_dir, "execution")):
        shutil.rmtree(path, ignore_errors=True)


def _charge_logical_storage(task: dict[str, Any], manifest: dict[str, Any], result_dir: str) -> None:
    """Charge the durable bytes one published Task logically owns.

    The ownership boundary is the published result, measured here once from the
    manifest's own artifacts rather than inferred later from a directory size:
    a shared read-only asset, a Runner SIF, or a deployment database is never a
    user's bytes, and a directory walk would charge them.  A failure to record
    it must not withdraw a completed scientific result, so this is total.

    The lifecycle is re-read here, immediately before the charge, because the
    walk above is the window where a purge can land: the guard at the top of
    :func:`_finalize_results_manifest` is true, the durable bytes are removed,
    and the publication that follows would re-create the tree and re-open a
    ``PURGED`` row as ``ACTIVE`` charged zero — a resurrected result with no
    owner.  A purge that wins that race is authoritative: this raises
    :class:`DataPurgedError`, and the caller ends the Task instead of publishing.
    """
    if not _data_still_owned(str(task["md5sum"])):
        _abandon_published_result(task, result_dir)
        raise DataPurgedError(str(task["md5sum"]))
    user_id = int(task.get("submitted_by_user_id") or 0)
    if user_id <= 0:
        return
    owned = sum(int(item.get("size") or 0) for item in manifest.get("artifacts", []))
    try:
        task_store.ensure_data_lifecycle(
            str(task["md5sum"]),
            user_id=user_id,
            logical_bytes=owned,
            at=time.time(),
        )
    except Exception:
        # Recording the charge is an accounting step, not part of the scientific
        # result: a failure here must not withdraw a completed publication, and
        # it must not be mistaken for the deletion race above, which is decided
        # by the durable row rather than by whether this call raised.
        logging.exception("Could not charge logical storage for task %s", task.get("md5sum"))
        return
    emit_event(
        "resource.storage.charged",
        request_id=_task_request_id(task),
        task_id=str(task["md5sum"]),
        user_id=user_id,
        storage_bytes=owned,
        reason_code=LedgerReason.STORAGE_CHARGED.value,
    )


def _build_results_archive(task: dict) -> str:
    """Build an optional ZIP from the artifacts published in the manifest.

    The ZIP is a publication path, so it consumes the same published-artifact
    identity contract as the ordinary artifact download: every entry comes from
    a verified open descriptor, never from a pathname that is re-opened after
    the check.  The manifest itself is read once from a verified descriptor and
    *those* bytes are the ones written into the ZIP, so the archived manifest
    can never describe a different manifest than the one that selected the
    entries.  A file replaced after the manifest was finalized therefore fails
    the whole archive closed instead of being smuggled into the download.
    """
    zip_filename = _task_zip_path(task)
    storage = _storage()
    manifest_bytes = storage.read_manifest_bytes(task)
    if manifest_bytes is None:
        raise FileNotFoundError("Result manifest is not finalized")
    try:
        manifest = json.loads(manifest_bytes)
    except json.JSONDecodeError as exc:
        raise FileNotFoundError("Result manifest is not finalized") from exc
    temporary_zip = f"{os.path.splitext(zip_filename)[0]}.tmp-{os.getpid()}-{time.time_ns()}.zip"
    try:
        with zipfile.ZipFile(temporary_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            _write_manifest_entry(archive, manifest_bytes)
            for artifact in manifest.get("artifacts", []):
                _write_verified_artifact(archive, storage, task, manifest, artifact)
        os.replace(temporary_zip, zip_filename)
    finally:
        if os.path.exists(temporary_zip):
            os.unlink(temporary_zip)
    return zip_filename


def _finalize_failed_results(task: dict, error: Any, *, finished_at: float) -> None:
    task_id = str(task.get("md5sum") or "")
    if task_id and not _data_still_owned(task_id):
        # A completed purge is authoritative over this worker's failure report.
        # Creating the tree first and letting publication refuse it would leave
        # an unpaid, unpublished ``task_failed.txt`` no charge accounts for, so
        # ownership is decided before anything is written.
        logging.info("Task %s data is no longer owned; skipping failure report", task_id)
        return
    try:
        result_dir = _task_result_dir(task)
    except ValueError:
        return
    try:
        os.makedirs(result_dir, exist_ok=True)
        report_path = os.path.join(result_dir, "task_failed.txt")
        message = _sanitize_task_error(task, error) or "Task failed."
        task_type_name = task.get("task_type") or default_task_type()
        with open(report_path, "w", encoding="utf-8") as handle:
            handle.write(f"REvoDesign {task_type_name} task failed\n")
            handle.write(f"Task ID: {task.get('md5sum', 'unknown')}\n")
            handle.write(f"Input: {task.get('filename', 'unknown')}\n\n")
            handle.write(message)
            handle.write("\n")
        _finalize_results_manifest(task, execution_state="failed", finished_at=finished_at)
    except Exception as exc:  # pylint: disable=broad-except
        logging.warning("Failed to finalize failed task %s: %s", task.get("md5sum"), exc)


# ---------------------------------------------------------------------------
# Formatting utilities
# ---------------------------------------------------------------------------


def format_times(timestamp):
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S") if timestamp else None


def format_walltime(seconds: Any) -> str:
    if seconds is None:
        return "-"
    try:
        total_seconds = max(int(float(seconds)), 0)
    except (TypeError, ValueError):
        return "-"
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


# ---------------------------------------------------------------------------
# Status helpers
# ---------------------------------------------------------------------------


class DataPurgedError(RuntimeError):
    """A result cannot be published because the Task's data lifecycle forbids it.

    ``ACTIVE`` and ``ARCHIVED`` are the states in which the Task still owns its
    durable data.  Every deletion-ward state — requested, purging, purged — and
    the error state of an interrupted purge mean the data is being removed or is
    already gone, so publishing a fresh manifest would resurrect a tree the
    deletion is responsible for.
    """


def _data_still_owned(task_id: str) -> bool:
    """Whether a Task may publish durable data right now.

    No lifecycle row is the normal case for a Task whose result has not been
    registered yet: the charge is created by the publication itself.  The check
    is therefore "no row, or a row in an owning state", read from the store that
    owns the row rather than inferred from the task's execution status.

    Only ``ACTIVE`` and ``ARCHIVED`` publish.  The deletion-ward states mean a
    removal is authorized or under way, and ``ERROR`` is an interrupted removal
    that a later pass retries, so none of them may re-materialize the tree.
    """
    record = task_store.get_data_lifecycle(task_id)
    if record is None:
        return True
    return str(record["state"]) in (
        rloan.DataLifecycleState.ACTIVE.value,
        rloan.DataLifecycleState.ARCHIVED.value,
    )


def _is_terminal_status(status: Any) -> bool:
    normalized = str(status or "").strip().lower()
    return normalized in {
        "deleted:finshed",
        "deleted:cancel",
        "deleting:finished",
        "deleting:cancel",
        "cleaned:finished",
        "cleaned:cancel",
        "cancelled",
    }


def _task_is_terminal(md5sum: str) -> bool:
    task = task_store.get_task(md5sum)
    return bool(task and _is_terminal_status(task.get("status")))


def _record_failure(md5sum: str, task: dict, start_time: float, run_stage: str, error_message: str) -> None:
    finish_time = time.time()
    if _task_is_terminal(md5sum):
        return
    _capture_debug_submission(task, _entities_from_input_form(task))
    _finalize_failed_results(task, error_message, finished_at=finish_time)
    task_store.update_task(
        md5sum,
        status="failed",
        finished_at=finish_time,
        walltime=finish_time - start_time,
        error=error_message,
        run_stage=run_stage,
    )
    _cleanup_task_workspace(task)


def _cleanup_task_workspace(task: dict[str, Any]) -> None:
    """Remove disposable preparation while retaining immutable original inputs."""
    try:
        workspace_dir = _storage().get_input_root(task)
    except ValueError:
        return
    for name in ("scratch", "prepared"):
        path = _safe_join(workspace_dir, name)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)


def _entities_from_input_form(task: dict[str, Any]) -> list[dict]:
    """Parse the file/param entities out of a task row's ``input_form`` blob."""
    raw_form = task.get("input_form")
    if not raw_form:
        return []
    try:
        parsed = json.loads(raw_form) if isinstance(raw_form, str) else raw_form
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(parsed, dict):
        return []
    entities = parsed.get("entities")
    return entities if isinstance(entities, list) else []


def _task_request_id(task: dict[str, Any]) -> str | None:
    raw_form = task.get("input_form")
    try:
        parsed = json.loads(raw_form) if isinstance(raw_form, str) else raw_form
    except (json.JSONDecodeError, TypeError):
        return None
    value = parsed.get("request_id") if isinstance(parsed, dict) else None
    return value if isinstance(value, str) and value else None


def _capture_debug_submission(task: dict[str, Any], entities: list[dict], params: dict | None = None) -> None:
    """Best-effort copy of the user's submission into the result dir so it
    survives workspace cleanup: the submission form as ``debug/submission.json``
    plus each input snapshot copied to its user-facing path under
    ``debug/inputs/``.  Any failure only logs a warning — debug capture must
    never fail a job finalization."""
    try:
        result_dir = _task_result_dir(task)
    except ValueError:
        return
    try:
        debug_dir = _safe_join(result_dir, "debug")
        inputs_dir = _safe_join(debug_dir, "inputs")
        os.makedirs(inputs_dir, exist_ok=True)

        raw_form = task.get("input_form")
        if isinstance(raw_form, str):
            try:
                raw_form = json.loads(raw_form)
            except json.JSONDecodeError:
                raw_form = None
        form = raw_form if isinstance(raw_form, dict) else {}

        # The DB record is the source of truth — same convention as
        # _execute_compute_task, where the Celery ``params`` argument is
        # ignored in favor of the input_form param entities.
        if params is None:
            params = {
                e["name"]: e.get("verified_value", e.get("value"))
                for e in entities
                if e.get("type") != "file" and e.get("name")
            }

        files: list[dict[str, Any]] = []
        for fe in [e for e in entities if e.get("type") == "file"]:
            role = str(fe.get("role") or "")
            relative_path = str(fe.get("relative_path") or "").replace("\\", "/")
            snapshot_path = str(fe.get("snapshot_path") or "")
            parts = relative_path.split("/")
            if not relative_path or relative_path.startswith("/") or any(part in {"", ".", ".."} for part in parts):
                logging.warning(
                    "Skipping debug capture for invalid input path %r in task %s",
                    relative_path,
                    task.get("md5sum"),
                )
                continue
            if (
                not _path_is_within(CONFIG.workspace_folder, snapshot_path)
                or os.path.islink(snapshot_path)
                or not os.path.isfile(snapshot_path)
            ):
                logging.warning(
                    "Skipping debug capture for invalid snapshot %r in task %s",
                    snapshot_path,
                    task.get("md5sum"),
                )
                continue
            destination = _safe_join(inputs_dir, role, *parts)
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            # Copy rather than hard link: the debug capture lands inside the
            # result tree, and the publication boundary refuses any result entry
            # whose link count is not one.  A hard link here would make every
            # captured input unpublishable and a symlink would be skipped.
            try:
                shutil.copyfile(snapshot_path, destination)
                os.chmod(destination, 0o440)
            except OSError as exc:
                logging.warning(
                    "Skipping debug capture copy for %r in task %s: %s",
                    relative_path,
                    task.get("md5sum"),
                    exc,
                )
                continue
            files.append(
                {
                    "role": str(fe.get("role") or ""),
                    "name": relative_path,
                    "size": os.path.getsize(destination),
                    "sha256": str(fe.get("hash") or ""),
                }
            )

        submission = {
            "task_type": task.get("task_type") or default_task_type(),
            "params": params,
            "username": str(task.get("username") or form.get("user") or ""),
            "submitted_at": form.get("submitted_at") or task.get("uploaded_at"),
            "inputs": files,
        }
        submission_path = _safe_join(debug_dir, "submission.json")
        with open(submission_path, "w", encoding="utf-8") as handle:
            json.dump(submission, handle, ensure_ascii=True, indent=2, sort_keys=True)
            handle.write("\n")
    except Exception as exc:  # pylint: disable=broad-except
        logging.warning("Failed to capture debug submission for task %s: %s", task.get("md5sum"), exc)


# ---------------------------------------------------------------------------
# Core task implementation (Celery-agnostic — called by both task wrappers)
# ---------------------------------------------------------------------------


def _execute_compute_task(
    md5sum: str,
    task_type: str | None = None,
    params: dict | None = None,
    request_id: str | None = None,
):
    """Core task logic — shared by legacy and generic Celery task wrappers.

    Reads entities from the task's ``input_form`` column.  The ``params``
    argument is retained for the Celery signature but is ignored in favor
    of the DB record.
    """
    task = task_store.get_task(md5sum)
    if not task:
        logging.error("Task %s missing from database", md5sum)
        return
    # Exactly-once dispatch: the compare-and-set claims the task for this one
    # execution.  A duplicated dispatch of the same id — a second worker, an
    # independent re-enqueue racing this run — loses the claim and returns
    # without launching anything and without re-preparing (and thus wiping)
    # the winner's snapshot.
    if not task_store.claim_task_execution(md5sum):
        logging.warning("Task %s is already claimed by another execution; skipping dispatch", md5sum)
        return

    task_type = task_type or task.get("task_type")
    try:
        tt, runner = _get_task_type(task_type)
    except KeyError:
        _record_failure(md5sum, task, time.time(), "", f"Unknown task type: {task_type!r}")
        return

    output_dir = _task_result_dir(task)

    # Parse entities from the input_form JSON blob
    raw_form = task.get("input_form")
    entities: list[dict] = []
    resource_policy: ResolvedResources | None = None
    resource_policies: dict[str, ResolvedResources] = {}
    if raw_form:
        try:
            parsed = json.loads(raw_form) if isinstance(raw_form, str) else raw_form
            request_id = request_id or parsed.get("request_id")
            entities = parsed.get("entities", [])
            snapshot_root = parsed.get("snapshot_root")
            stored_workspace_key = parsed.get("workspace_key")
            if isinstance(snapshot_root, str) and snapshot_root and isinstance(stored_workspace_key, str):
                entities.append(
                    {
                        "type": "workspace",
                        "workspace_root": os.path.dirname(snapshot_root),
                        "workspace_key": stored_workspace_key,
                    }
                )
            if parsed.get("resource_policy"):
                resource_policy = ResolvedResources.from_snapshot(parsed["resource_policy"])
            raw_policies = parsed.get("resource_policies", {})
            if not isinstance(raw_policies, dict):
                raise TypeError("resource_policies must be an object")
            resource_policies = {name: ResolvedResources.from_snapshot(policy) for name, policy in raw_policies.items()}
        except (json.JSONDecodeError, TypeError, ResourceValidationError):
            logging.warning("Task %s: input_form or resource policy is invalid.", md5sum)
            _record_failure(md5sum, task, time.time(), "", "Task input or resource policy is invalid")
            return

    # Verify file entities reference existing files
    for fe in [e for e in entities if e["type"] == "file"]:
        upload_file = os.path.join(CONFIG.upload_folder, f"{fe['hash']}.upload")
        if not os.path.lexists(upload_file):
            _record_failure(md5sum, task, time.time(), "", f"Uploaded input file not found: {upload_file}")
            logging.error("Uploaded file missing for task %s: %s", md5sum, upload_file)
            return
        snapshot_path = str(fe.get("snapshot_path") or "")
        if (
            not snapshot_path
            or not _path_is_within(CONFIG.workspace_folder, snapshot_path)
            or os.path.islink(snapshot_path)
            or not os.path.isfile(snapshot_path)
            or _sha256_file(snapshot_path) != fe["hash"]
        ):
            _record_failure(
                md5sum,
                task,
                time.time(),
                "",
                f"Immutable input snapshot is missing or changed: {fe.get('relative_path', 'unknown')}",
            )
            logging.error("Input snapshot verification failed for task %s", md5sum)
            return
        # The snapshot is the immutable byte stream the Runner consumes, so the
        # admission receipt names it.  A trusted receipt is necessary but not
        # sufficient: the snapshot is re-run through the same canonical Core
        # boundary execution would have applied, so a forged or stale receipt can
        # never substitute a decision for real validation, and a swap between
        # admission and execution is a failure rather than a silent substitution.
        receipt = fe.get("validation_receipt")
        reason = _verify_snapshot(fe, snapshot_path, receipt)
        if reason is not None:
            _record_failure(
                md5sum,
                task,
                time.time(),
                "",
                f"Immutable input snapshot is missing or changed: {fe.get('relative_path', 'unknown')}",
            )
            emit_event(
                "worker.task.failed",
                level="ERROR",
                request_id=request_id,
                task_id=md5sum,
                task_type=str(task_type),
                runner_family=tt.runtime.name,
                reason_code=reason,
            )
            logging.error("Input snapshot receipt verification failed for task %s", md5sum)
            return
        if not isinstance(receipt, dict):
            # Record the freshly proven decision on the execution description,
            # so downstream provenance names the boundary that admitted these
            # bytes even for a row that predates receipts.
            fe["validation_receipt"] = ValidationReceipt(
                sha256=str(fe["hash"]),
                size=int(fe.get("size") or os.path.getsize(snapshot_path)),
                format=str(fe.get("format") or ""),
                logical_type=str(fe.get("logical_type") or "file"),
                relative_path=str(fe.get("relative_path") or ""),
                role=str(fe.get("role") or ""),
            ).as_record()

    stages = list(tt.stage_markers.items())
    start_time = task.get("started_at") or time.time()
    current_stage = str(task.get("run_stage") or (stages[0][0] if stages else "")).strip().lower()

    is_slurm = _get_job_executor() == "slurm"
    initial_status = "queued" if is_slurm else "running"
    update_fields: dict[str, Any] = {
        "status": initial_status,
        "error": None,
        "local_user": _local_user_identity(),
        "run_stage": current_stage,
    }
    if not task.get("started_at"):
        update_fields["started_at"] = start_time
    task_store.update_task(md5sum, **update_fields)
    if task.get("request_headers"):
        logging.info("Request headers for task %s: %s", md5sum, _sanitize_for_log(task["request_headers"]))

    stage_state = {"current": current_stage, "first": True}
    runtime_event_fields = {
        "request_id": request_id,
        "task_id": md5sum,
        "task_type": str(task_type),
        "runner_family": tt.runtime.name,
    }

    def _on_stage_change(stage: str) -> None:
        if _task_is_terminal(md5sum):
            return
        stage_changed = stage != stage_state["current"]
        is_first = stage_state.get("first")
        logging.info("Stage callback for task %s: stage=%s changed=%s first=%s", md5sum, stage, stage_changed, is_first)
        if is_first:
            emit_event("runner.stage.started", stage_id=stage, **runtime_event_fields)
        elif stage_changed:
            emit_event("runner.stage.finished", stage_id=stage_state["current"], **runtime_event_fields)
            emit_event("runner.stage.started", stage_id=stage, **runtime_event_fields)
        else:
            emit_event("runner.stage.progress", stage_id=stage, **runtime_event_fields)
        stage_state["current"] = stage
        if is_first:
            stage_state["first"] = False
            task_store.update_task(md5sum, status="running", run_stage=stage)
        elif stage_changed:
            task_store.update_task(md5sum, run_stage=stage)

    try:
        job_kwargs = {
            "task_id": md5sum,
            "tt": tt,
            "runner": runner,
            "entities": entities,
            "output_dir": output_dir,
            "stage_callback": _on_stage_change,
            "username": task.get("username", ""),
        }
        if resource_policy is not None:
            job_kwargs["resource_policy"] = resource_policy
        if tt.workflow:
            final_state = _run_compute_workflow(
                md5sum,
                task,
                tt,
                runner,
                entities,
                output_dir,
                resource_policies,
                _on_stage_change,
            )
        else:
            final_state = _run_compute_job(**job_kwargs)
        if _task_is_terminal(md5sum):
            logging.info("Task %s was deleted during execution; skipping result packing and finalization.", md5sum)
            return

        if final_state == JobState.FAILED:
            emit_event(
                "runner.stage.failed",
                level="ERROR",
                stage_id=stage_state["current"],
                reason_code="allocation_failed",
                **runtime_event_fields,
            )
            _record_failure(
                md5sum,
                task,
                start_time,
                stage_state["current"],
                "SLURM job failed — check job logs for details",
            )
            return
        if final_state == JobState.CANCELLED:
            task_store.update_task(md5sum, status="cancelled", finished_at=time.time())
            _capture_debug_submission(task, entities, params)
            _cleanup_task_workspace(task)
            return

        final_stage = stage_state["current"] or (stages[-1][0] if stages else "")
        if final_stage:
            emit_event("runner.stage.finished", stage_id=final_stage, **runtime_event_fields)
        refreshed_task = task_store.get_task(md5sum) or task
        if _is_terminal_status(refreshed_task.get("status")):
            return
        _capture_debug_submission(task, entities, params)
        finish_time = time.time()
        try:
            _finalize_results_manifest(refreshed_task, execution_state="completed", finished_at=finish_time)
        except ResultPublicationError as exc:
            # The run finished, but its result could not be published as one
            # coherent transition.  The task is settled as failed rather than
            # finished: a finished row whose canonical result Core's own reader
            # refuses is exactly the state this boundary exists to prevent.
            _record_failure(md5sum, task, start_time, stage_state["current"], str(exc))
            logging.error("Publication failed for task %s: %s", md5sum, exc)
            return
        except DataPurgedError:
            # The user (or an Admin) deleted this Task's durable data while the
            # allocation was still finishing.  The deletion wins: the Task ends
            # without republishing a result tree the purge just removed, and the
            # lifecycle row keeps its own state instead of charging bytes back.
            logging.info("Task %s data was purged before finalization; not republishing results", md5sum)
            _cleanup_task_workspace(task)
            return
        refreshed_task = task_store.get_task(md5sum) or refreshed_task
        if _is_terminal_status(refreshed_task.get("status")):
            return
        task_store.update_task(
            md5sum,
            status="finished",
            finished_at=finish_time,
            walltime=finish_time - start_time,
            error=None,
            run_stage=final_stage,
        )
        _cleanup_task_workspace(task)
    except Exception as exc:  # pylint: disable=broad-except
        emit_event(
            "runner.stage.failed",
            level="ERROR",
            stage_id=stage_state["current"] or None,
            reason_code="unexpected_failure",
            **runtime_event_fields,
        )
        _record_failure(md5sum, task, start_time, stage_state["current"], str(exc))
        logging.exception("Unexpected failure while running task %s (type=%s)", md5sum, task_type)


# ---------------------------------------------------------------------------
# Orphaned compute-resource recovery after worker restart
#
# A managed stack shutdown sweeps SLURM jobs before stopping the worker, but
# an OOM, crash, or direct container restart bypasses that hook.  On worker
# startup, fail those orphaned records and best-effort cancel their allocation.
# ---------------------------------------------------------------------------


def _stop_orphaned_workflow_execution(task_id: str, slurm_job_id: str, container_id: str) -> str:
    """Stop a workflow allocation before another worker resumes its stage."""
    if slurm_job_id:
        if slurm_job_id.isdigit():
            scancel = shutil.which("scancel")
            if not scancel:
                return f"Cannot resume while SLURM job {slurm_job_id} cannot be cancelled"
            try:
                subprocess.run([scancel, slurm_job_id], timeout=10, check=True)
            except (OSError, subprocess.SubprocessError) as exc:
                return f"Could not cancel SLURM job {slurm_job_id}: {exc}"
        else:
            match = re.fullmatch(r"srun-([1-9][0-9]*)", slurm_job_id)
            if not match:
                return f"Cannot resume workflow with unknown SLURM handle {slurm_job_id!r}"
            pid = int(match.group(1))
            try:
                command = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ")
            except FileNotFoundError:
                command = b""
            except OSError as exc:
                return f"Could not inspect srun process {pid}: {exc}"
            if command:
                if b"srun" not in command or task_id[:8].encode("ascii") not in command:
                    return f"Refusing to stop unverified process {pid} for workflow recovery"
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                except OSError as exc:
                    return f"Could not stop srun process {pid}: {exc}"
                if not _wait_for_process_exit(pid, 10.0):
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    except OSError as exc:
                        return f"Could not kill srun process {pid}: {exc}"
                    if not _wait_for_process_exit(pid, 2.0):
                        return f"srun process {pid} did not exit after SIGKILL"

    if container_id:
        return "Cannot resume a legacy Docker workflow; Slurm is the only production executor"
    return ""


def _wait_for_process_exit(pid: int, timeout: float) -> bool:
    """Wait for a PID to disappear or become a reaped-ready zombie."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            state = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()[2]
        except FileNotFoundError:
            return True
        except (OSError, IndexError):
            state = ""
        if state == "Z":
            return True
        time.sleep(0.1)
    return False


_ACTIVE_SLURM_STATES = {"PENDING", "RUNNING", "CONFIGURING", "COMPLETING", "SUSPENDED"}
_TERMINAL_SLURM_STATES = {
    "BOOT_FAIL",
    "CANCELLED",
    "COMPLETED",
    "DEADLINE",
    "FAILED",
    "NODE_FAIL",
    "OUT_OF_MEMORY",
    "PREEMPTED",
    "REVOKED",
    "TIMEOUT",
}


def _parse_slurm_runtime(value: str) -> int | None:
    """Parse a Slurm ``RunTime``/``Elapsed`` value into whole seconds.

    Accepts ``SS``, ``MM:SS``, ``HH:MM:SS``, and ``D-HH:MM:SS``.  Anything
    unfamiliar, negative, or out of range returns ``None`` so the caller marks
    the allocation for review instead of guessing.
    """
    text = value.strip()
    if not text:
        return None
    days = 0
    if "-" in text:
        day_part, _, text = text.partition("-")
        try:
            days = int(day_part)
        except ValueError:
            return None
    parts = text.split(":")
    if not 1 <= len(parts) <= 3:
        return None
    try:
        numbers = [int(part) for part in parts]
    except ValueError:
        return None
    if any(number < 0 for number in numbers):
        return None
    if len(numbers) == 3:
        hours, minutes, seconds = numbers
    elif len(numbers) == 2:
        hours, minutes, seconds = 0, numbers[0], numbers[1]
    else:
        hours, minutes, seconds = 0, 0, numbers[0]
    if minutes >= 60 or seconds >= 60:
        return None
    return days * 86_400 + hours * 3_600 + minutes * 60 + seconds


def _parse_scontrol_job(output: str) -> tuple[str, int | None]:
    """Return ``(state, elapsed_seconds)`` from ``scontrol show job`` output."""
    fields: dict[str, str] = {}
    for token in output.replace("\n", " ").split():
        key, separator, value = token.partition("=")
        if separator and key not in fields:
            fields[key] = value
    state = fields.get("JobState", "").split("+")[0].strip().upper()
    elapsed = _parse_slurm_runtime(fields.get("RunTime", ""))
    if elapsed is None:
        elapsed = _parse_slurm_runtime(fields.get("Elapsed", ""))
    return state, elapsed


def _reconcile_slurm_allocations() -> dict[str, int]:
    """Settle lost finish callbacks from best-effort ``scontrol`` evidence.

    The target deployment runs without Slurm accounting storage, so recovery
    deliberately uses only the controller-retained ``scontrol show job`` state
    plus a trustworthy runtime.  No ``sacct``/SlurmDBD dependency, no estimate:
    anything ambiguous is left for manual review.
    """
    allocations = task_store.list_unsettled_allocations()
    result = {"settled": 0, "active": 0, "review": 0}
    scontrol = shutil.which("scontrol")
    # One scheduler question per Slurm job, not per accounting unit: a job's GPU
    # and CPU facts settle from the one authoritative elapsed duration that
    # question answers.
    job_ids = list(dict.fromkeys(str(allocation["slurm_job_id"]) for allocation in allocations))
    for job_id in job_ids:
        if not scontrol:
            task_store.mark_allocation_for_review(job_id)
            result["review"] += 1
            continue
        try:
            completed = subprocess.run(
                [scontrol, "show", "job", job_id],
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
        except (OSError, subprocess.SubprocessError):
            task_store.mark_allocation_for_review(job_id)
            result["review"] += 1
            continue
        state, elapsed_seconds = _parse_scontrol_job(completed.stdout)
        if state in _ACTIVE_SLURM_STATES:
            result["active"] += 1
            continue
        if state not in _TERMINAL_SLURM_STATES or elapsed_seconds is None:
            task_store.mark_allocation_for_review(job_id)
            result["review"] += 1
            continue
        settled = task_store.settle_allocation_elapsed(
            job_id,
            elapsed_seconds=elapsed_seconds,
            evidence_source=EvidenceSource.SLURM_LIVE.value,
        )
        emit_event(
            "resource.allocation.settled",
            task_id=str(settled["task_id"]),
            stage_id=str(settled["stage_id"]),
            slurm_job_id=job_id,
            user_id=int(settled["subject_id"]),
            gpu_count=int(settled["resource_count"]),
            gpu_seconds=int(settled["quantity"] or 0),
            reason_code=LedgerReason.SLURM_LIVE.value,
        )
        result["settled"] += 1
    return result


def _reclaim_abandoned_reservations(*, now: float | None = None) -> int:
    """Free scheduler-owned reservations whose Slurm request no longer exists.

    The complement of :func:`_reconcile_slurm_allocations`: that pass settles
    allocations that *did* start, this one releases the reservation of a Task
    whose request never produced an allocation and is provably gone from the
    scheduler.  Both are evidence-driven.  A reservation whose Job is still
    active in Slurm belongs to that Job and is left alone — that is the case a
    bare timeout used to get wrong — and an ambiguous answer (no scheduler, an
    unreadable state, or no scheduler identity on the row) leaves the reservation
    committed rather than guessing.  Capacity is therefore returned as soon as
    the request is knowably gone, and never merely because time passed.

    The scheduler identity is taken from the reservation row, which the
    held -> queued transition wrote atomically with the state change, not from
    ``tasks.slurm_job_id`` — that column is persisted separately and later, so
    reading it here would free a live request's entitlement during the dispatch
    window.  A missing identity is not evidence that no request exists, so it
    keeps its commitment.
    """
    timestamp = time.time() if now is None else now
    reservations = task_store.list_queued_reservations()
    if not reservations:
        return 0
    scontrol = shutil.which("scontrol")
    released = 0
    for reservation in reservations:
        task_id = str(reservation["task_id"])
        task = task_store.get_task(task_id)
        job_id = str(reservation.get("scheduler_job_id") or "").strip()
        if task is None:
            # The Task row is gone, so nothing can ever consume this claim and
            # no scheduler request it names belongs to a live Task.
            if task_store.reclaim_queued_reservation(
                task_id=task_id, reason_code=ReservationReason.TASK_DELETED.value, at=timestamp
            ):
                released += 1
            continue
        if not job_id or not job_id.isdigit():
            continue  # no scheduler identity: ambiguous, keep the commitment
        if not scontrol:
            continue  # ambiguous: keep the commitment rather than guess
        try:
            completed = subprocess.run(
                [scontrol, "show", "job", job_id],
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        state, _elapsed = _parse_scontrol_job(completed.stdout)
        if state in _ACTIVE_SLURM_STATES:
            continue
        if state not in _TERMINAL_SLURM_STATES:
            continue
        if task_store.reclaim_queued_reservation(
            task_id=task_id, reason_code=ReservationReason.RELEASED.value, at=timestamp
        ):
            released += 1
    return released


def _recover_orphaned_tasks() -> int:
    """Resolve compute records whose owning Celery worker disappeared."""
    handled = 0
    for task in task_store.list_tasks():
        if task.get("status") not in {"running", "queued"}:
            continue
        md5sum = task["md5sum"]
        slurm_job_id = str(task.get("slurm_job_id") or "").strip()
        container_id = str(task.get("container_id") or "")
        task_type = task.get("task_type") or default_task_type()
        try:
            workflow_task = bool(_get_task_type(task_type)[0].workflow)
        except KeyError:
            workflow_task = False
        if workflow_task:
            if not task_store.claim_task_recovery(md5sum, expected_status=str(task.get("status") or "")):
                continue
            stop_error = _stop_orphaned_workflow_execution(md5sum, slurm_job_id, container_id)
            if stop_error:
                task_store.update_task(md5sum, status="queued", error=stop_error)
                logging.error("Recovery left workflow %s queued: %s", md5sum, stop_error)
                handled += 1
                continue
            state = _workflow_state(task)
            for step in state.values():
                if step.get("status") == "running":
                    step["status"] = "interrupted"
            if not task_store.update_task(
                md5sum,
                status="pending",
                slurm_job_id=None,
                container_id=None,
                workflow_state=json.dumps(state, sort_keys=True),
                error=None,
            ):
                handled += 1
                continue
            try:
                resumed = run_compute_task.apply_async(args=[md5sum], kwargs={"task_type": task_type})
            except Exception as exc:  # pylint: disable=broad-except
                task_store.update_task(md5sum, status="queued", error=f"Workflow recovery enqueue failed: {exc}")
                logging.exception("Recovery could not enqueue workflow %s", md5sum)
            else:
                if not task_store.update_task(md5sum, celery_task_id=resumed.id):
                    resumed.revoke(terminate=True)
            handled += 1
            continue
        if slurm_job_id:
            cancellation_error = ""
            scancel = shutil.which("scancel")
            if scancel and slurm_job_id.isdigit():
                try:
                    subprocess.run([scancel, slurm_job_id], timeout=10, check=True)
                except (OSError, subprocess.SubprocessError) as exc:
                    cancellation_error = f"; scheduler cancellation could not be confirmed: {exc}"
                    logging.warning("Recovery could not cancel SLURM job %s for %s: %s", slurm_job_id, md5sum, exc)
            else:
                cancellation_error = "; scheduler cancellation could not be attempted"
            _record_failure(
                md5sum,
                task,
                task.get("started_at") or time.time(),
                str(task.get("run_stage") or ""),
                f"SLURM task lost its worker{cancellation_error}",
            )
            handled += 1
            continue
        if not container_id and task.get("status") == "running":
            _record_failure(
                md5sum,
                task,
                task.get("started_at") or time.time(),
                str(task.get("run_stage") or ""),
                "Compute task lost its worker before recording a resource handle",
            )
            handled += 1
            continue
        if container_id:
            _record_failure(md5sum, task, task.get("started_at") or time.time(), "", "Legacy container task cannot be recovered; Slurm is the only production executor")
            handled += 1
    return handled


def _finalize_after_poll(md5sum, task, tt, state):
    """Publish results or record failure after a recovered job completes."""
    if state == JobState.FAILED:
        _record_failure(md5sum, task, task.get("started_at") or time.time(), "", "Recovered compute job failed")
    elif state == JobState.CANCELLED:
        task_store.update_task(md5sum, status="cancelled", finished_at=time.time())
        _capture_debug_submission(task, _entities_from_input_form(task))
        _cleanup_task_workspace(task)
    else:
        refreshed = task_store.get_task(md5sum) or task
        if _is_terminal_status(refreshed.get("status")):
            return
        _capture_debug_submission(task, _entities_from_input_form(task))
        finish_time = time.time()
        try:
            _finalize_results_manifest(refreshed, execution_state="completed", finished_at=finish_time)
        except ResultPublicationError as exc:
            # Same rule as the live path: a recovered run whose publication
            # could not be established is recorded as failed, never as a
            # finished task with an unreadable result.
            _record_failure(md5sum, task, task.get("started_at") or finish_time, "", str(exc))
            logging.error("Publication failed for recovered task %s: %s", md5sum, exc)
            return
        except DataPurgedError:
            # Same rule on the recovery path: a purge that ran while the job was
            # being recovered is authoritative over this worker's result tree.
            logging.info("Task %s data was purged before recovery finalization", md5sum)
            _cleanup_task_workspace(task)
            return
        refreshed = task_store.get_task(md5sum) or refreshed
        if _is_terminal_status(refreshed.get("status")):
            return
        task_store.update_task(
            md5sum,
            status="finished",
            finished_at=finish_time,
            walltime=finish_time - (task.get("started_at") or finish_time),
            error=None,
            run_stage=list(tt.stage_markers.items())[-1][0] if tt.stage_markers else "",
        )
        _cleanup_task_workspace(task)


def _reconcile_result_publications() -> dict[str, int]:
    """Classify every terminal task's publication and report the quarantined ones.

    This is the rollout rule for results that predate the publication anchor, and
    the restart-side reconciliation for a publication that was interrupted: both
    surface as the same bounded state, resolved by the same reader every consumer
    uses.  It reports and never writes.

    It deliberately does not backfill an anchor.  A pre-anchor result was
    finalized by an authority that recorded no identity for the manifest, and the
    only bytes available today are the ones the runner's identity wrote in the
    result tree — the exact namespace the anchor exists to stop trusting.  So the
    manifest stays quarantined with its reason, and the trusted re-publication
    path is the ordinary one: a fresh run of the task, which publishes through
    the same single transition as everything else.  An operator reads the report
    with ``revocompute publications`` and decides which tasks to re-run.
    """
    storage = _storage()
    summary: dict[str, int] = {}
    for task in task_store.list_tasks():
        status = str(task.get("status") or "").strip().lower()
        if status not in {"finished", "failed"}:
            continue
        state = storage.publication_state(task)
        summary[state] = summary.get(state, 0) + 1
        if state in PUBLICATION_QUARANTINE_STATES:
            emit_event(
                "manifest.publication_quarantined",
                level="WARNING",
                task_id=str(task.get("md5sum")),
                task_type=str(task.get("task_type") or default_task_type()),
                # The publication state is the machine-readable reason: it says
                # whether the result predates the anchor (unanchored) or its bytes
                # changed after publication (anchor_mismatch), which are different
                # operator problems.
                reason_code=state,
            )
            logging.warning("Result for task %s is quarantined: %s", task.get("md5sum"), state)
    return summary


# One pulse per worker process.  Started from ``worker_ready``, which Celery
# emits on the parent process — never a prefork task slot.
_infrastructure_pulse_lock = threading.Lock()
_infrastructure_pulse_started = False


def collect_infrastructure_evidence() -> dict[str, Any]:
    """Probe the scheduler/GPU boundary and publish the snapshot the web reads."""
    checked_at = datetime.now(timezone.utc).isoformat()
    payload = {
        component.value: replace(probe(), checked_at=checked_at).as_dict()
        for component, probe in (
            (InfrastructureComponent.SLURM_CONTROLLER, _slurm_controller_probe),
            (InfrastructureComponent.SLURM_SUBMISSION, _slurm_submission_probe),
            (InfrastructureComponent.GPU_INVENTORY, _gpu_inventory_probe),
        )
    }
    publish_worker_probe_snapshot(os.path.join(CONFIG.server_dir, "readiness", "infrastructure.json"), payload)
    return payload


def _infrastructure_pulse(interval: float, stop: threading.Event) -> None:
    while not stop.wait(interval):
        try:
            if not _manage_db.slurm_enabled():
                continue  # re-read every pulse: SLURM can be enabled without a restart
            collect_infrastructure_evidence()
        except Exception:  # a failed pulse must never kill the worker process
            logging.exception("Infrastructure evidence pulse failed")


def start_infrastructure_pulse() -> None:
    """Refresh worker-published scheduler/GPU evidence on a timer.

    Admission reads the snapshot this publishes and calls it stale after
    ``INFRA_STALE_SECONDS``, so without a pulse every submission is refused
    within a minute of a restart.  The pulse deliberately does not go through
    the task queue: ``run_compute_task`` blocks in ``SlurmJob.poll()`` for the
    whole job, so a fully occupied worker pool would otherwise starve the
    probe and reintroduce exactly that refusal under normal load.

    ``INFRA_REFRESH_SECONDS`` keeps its documented meaning: a positive value is
    the pulse interval, ``0`` disables the automatic pulse (admin and
    force-refresh still work), and a negative value is a configuration error.
    Zero must disable rather than spin — the same interval feeds
    ``Event.wait``, where ``0`` returns immediately and would hammer the
    scheduler in an unbounded loop.
    """
    interval = env_int("INFRA_REFRESH_SECONDS", 15)
    if interval < 0:
        raise ValueError("INFRA_REFRESH_SECONDS must be zero or positive")
    global _infrastructure_pulse_started
    with _infrastructure_pulse_lock:
        if _infrastructure_pulse_started:
            return
        _infrastructure_pulse_started = True
    if interval == 0:
        logging.info("Infrastructure evidence pulse disabled (INFRA_REFRESH_SECONDS=0)")
        return
    threading.Thread(
        target=_infrastructure_pulse,
        args=(interval, threading.Event()),
        name="infrastructure-pulse",
        daemon=True,
    ).start()
    logging.info("Infrastructure evidence pulse started (every %d s)", interval)


try:
    from celery.signals import worker_ready

    @worker_ready.connect
    def _on_worker_ready(sender, **kwargs):
        try:
            probe_compute_infrastructure.run()
            count = _recover_orphaned_tasks()
            if count:
                logging.info("Handled %d orphaned task(s)", count)
            else:
                logging.info("Recovery: no orphaned tasks found")
            reconciliation = _reconcile_slurm_allocations()
            released = _reclaim_abandoned_reservations()
            if reconciliation["settled"] or reconciliation["review"] or released:
                logging.info(
                    "Allocation reconciliation: %s (%d abandoned reservation(s) released)",
                    reconciliation,
                    released,
                )
            publications = _reconcile_result_publications()
            unreadable = sum(
                count for state, count in publications.items() if state != PUBLICATION_AVAILABLE
            )
            if unreadable:
                logging.warning("Result publication states: %s", publications)
            else:
                logging.info("Result publication reconciliation: %s", publications)
        except Exception:  # boot-time recovery must never die silently
            logging.exception("Recovery pass failed")
        try:
            start_infrastructure_pulse()
        except Exception:  # the pulse must never die silently either
            logging.exception("Infrastructure evidence pulse failed to start")

except ImportError:
    pass  # celery.signals not available in all environments


# ---------------------------------------------------------------------------
# Celery task wrappers
# ---------------------------------------------------------------------------


@celery.task(name="probe_compute_infrastructure", max_retries=0)
def probe_compute_infrastructure():
    """Return bounded scheduler/GPU evidence from the worker-owned runtime boundary.

    Used for the boot pass and for admin-requested refreshes, which may
    legitimately wait on a task slot.  The continuous pulse does not route
    through this task; see ``start_infrastructure_pulse``.
    """
    return collect_infrastructure_evidence()


@celery.task(name="reconcile_slurm_allocations", max_retries=0)
def reconcile_slurm_allocations():
    """Reconcile durable unsettled allocations from worker-side Slurm evidence.

    Two evidence-driven passes, no wall-clock guesswork: settle the allocations
    the scheduler proves ran, then give back the entitlement of a queued request
    the scheduler proves no longer exists.
    """
    outcome = _reconcile_slurm_allocations()
    outcome["reservations_released"] = _reclaim_abandoned_reservations()
    return outcome


@celery.task(name="run_compute_task", bind=True, max_retries=0)
def run_compute_task(
    self,
    md5sum: str,
    task_type: str | None = None,
    params: dict | None = None,
    request_id: str | None = None,
):
    """Compute task — dispatched by task_type."""
    started = time.monotonic()
    task = task_store.get_task(md5sum) or {}
    request_id = request_id or _task_request_id(task)
    celery_task_id = str(getattr(self.request, "id", "") or task.get("celery_task_id") or "")
    event_fields = {
        "request_id": request_id,
        "task_id": md5sum,
        "task_type": task_type or task.get("task_type"),
        "celery_task_id": celery_task_id or None,
    }
    emit_event("worker.task.started", **event_fields)
    try:
        result = _execute_compute_task(md5sum, task_type, params, request_id)
    except Exception:
        emit_event(
            "worker.task.failed",
            level="ERROR",
            reason_code="unexpected_worker_failure",
            duration_ms=max(0, round((time.monotonic() - started) * 1000)),
            **event_fields,
        )
        raise
    refreshed = task_store.get_task(md5sum) or task
    status = str(refreshed.get("status") or "")
    finish_fields = {
        **event_fields,
        "stage_id": str(refreshed.get("run_stage") or "") or None,
        "slurm_job_id": str(refreshed.get("slurm_job_id") or "") or None,
        "duration_ms": max(0, round((time.monotonic() - started) * 1000)),
    }
    if status == "failed":
        emit_event("task.failed", level="ERROR", reason_code="task_execution_failed", **finish_fields)
        emit_event("worker.task.failed", level="ERROR", reason_code="task_execution_failed", **finish_fields)
    else:
        if status == "finished":
            emit_event("task.finished", **finish_fields)
        elif status == "cancelled":
            emit_event("task.cancelled", **finish_fields)
        emit_event("worker.task.finished", **finish_fields)
    return result


@celery.task(name="cancel_compute_resources", bind=True, max_retries=0)
def cancel_compute_resources(self, slurm_job_id: str | None = None, container_id: str | None = None):
    """Kill a task's compute resources from the worker, which is the only
    container with SLURM tooling (and the Docker socket) mounted.  The web
    process cannot scancel or docker-stop directly."""
    if slurm_job_id:
        scancel = shutil.which("scancel")
        if not scancel:
            logging.warning("scancel not found; cannot cancel SLURM job %s", slurm_job_id)
        else:
            try:
                subprocess.run([scancel, str(slurm_job_id)], timeout=10, check=True)
                logging.info("Cancelled SLURM job %s", slurm_job_id)
            except Exception as exc:  # pylint: disable=broad-except
                logging.warning("Failed to scancel SLURM job %s: %s", slurm_job_id, exc)
    if container_id:
        docker_executable = shutil.which("docker")
        if not docker_executable:
            logging.warning("docker not found; cannot stop container %s", container_id)
        else:
            try:
                subprocess.run([docker_executable, "stop", str(container_id)], timeout=15, check=True)
                logging.info("Stopped Docker container %s", container_id)
            except Exception as exc:  # pylint: disable=broad-except
                logging.warning("Failed to stop Docker container %s: %s", container_id, exc)


@celery.task(name="build_results_archive", bind=True, max_retries=0)
def build_results_archive(self, md5sum: str):
    """Create the full-task ZIP only after a user explicitly requests it."""
    task_id = _normalize_task_id(md5sum)
    task = task_store.get_task(task_id) if task_id else None
    if task is None or task.get("status") not in {"finished", "failed"}:
        raise ValueError("Task results are not ready")
    return _build_results_archive(task)
