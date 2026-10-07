# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""SLURM + Apptainer job runner.

Uses ``srun`` for direct stdout/stderr capture and a temporary wrapper script
verifies the input
snapshot, exports ``APPTAINERENV_*`` environment variables, and invokes
Apptainer.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from revocompute.job import ExecutionBuilder, ExecutionPlan, Job, JobState
from revocompute.job._stages import extract_stage_from_log_line
from revocompute import runtime_bundle
from revocompute.operational_events import emit_event
from revocompute.resource_observations import (
    OBSERVATION_PREFIX,
    PROGRESS_PREFIX,
    TASK_OUTCOME_PREFIX,
    observe_lines,
    parse_progress_line,
    parse_task_outcome_line,
)
from revocompute.resource_policy import ResolvedResources, resolve_resources

_SLURM_JOB_ID_RE = re.compile(r"srun:\s+[Jj]ob\s+(\d+)")

#: Output contract of the allocation wrapper: two distinct facts, never one.
#:
#: ``REVODESIGN_JOB_ID=<id>`` names the scheduler job.  Inside the allocation
#: ``$SLURM_JOB_ID`` is set on the compute node, but srun also prints a
#: ``job <id> queued and waiting for resources`` banner on its *stderr* while
#: the request is still queued — so job identity is evidence that the scheduler
#: owns the request, not that anything is running.
#:
#: ``REVODESIGN_ALLOCATION_LIVE=<id>`` is printed only after the wrapper has
#: confirmed, from the scheduler's own state, that this job holds running
#: resources, so it is the one honest allocation-live signal.  Accounting and
#: the reservation consume hang off this line, never off the job-identity line:
#: a queue wait is not allocated time and must not be charged as any.
ALLOCATION_LIVE_PREFIX = "REVODESIGN_ALLOCATION_LIVE="
JOB_ID_PREFIX = "REVODESIGN_JOB_ID="

#: How long the wrapper waits for the scheduler to report its job RUNNING before
#: it gives up.  A request that never reaches RUNNING never held resources, so
#: the allocation fails instead of running unaccounted.
ALLOCATION_LIVE_POLLS = 600
ALLOCATION_LIVE_POLL_SECONDS = "0.5"
#: How long the wrapper waits for the server to release the scientific command
#: once the allocation is known to be running.  The release is the admission
#: decision: an allocation the balance cannot cover is stopped here, before the
#: task does any work.
ALLOCATION_RELEASE_POLLS = 600
ALLOCATION_RELEASE_POLL_SECONDS = "0.1"

_RESOURCE_BEGIN = "REVODESIGN_RESOURCE_BEGIN"
_RESOURCE_LINE = "REVODESIGN_RESOURCE:"
_RESOURCE_END = "REVODESIGN_RESOURCE_END"

#: The host-only namespace the allocation wrapper writes its compute-node receipt
#: into: one ``<task result root>.allocation/`` sibling per Task.  It is named
#: here, once, because two independent readers depend on the identical layout —
#: this adapter reads the receipt of the allocation it is running, and restart
#: reconciliation walks the namespace for receipts whose worker died before it
#: could adopt them.  A second spelling would silently disagree with the first.
ALLOCATION_DIR_SUFFIX = ".allocation"
ALLOCATION_RECEIPT_NAME = "allocation.receipt"

#: Hard ceiling for one Task's ephemeral scratch, in bytes.  Scratch is a
#: per-execution safety concern, never durable user quota: a runaway temporary
#: file must hit this wall instead of filling the host.  The allocation wrapper
#: enforces it on the compute node by measuring the workspace it already owns,
#: so the limit is host-local and a multi-node task is bounded per node.  The
#: override exists for hosts whose own scratch is smaller than the default.
TASK_SCRATCH_LIMIT_ENV = "TASK_SCRATCH_LIMIT_BYTES"
DEFAULT_TASK_SCRATCH_LIMIT_BYTES = 200 * 1024**3
#: How often the wrapper's capacity guard re-measures the scratch tree.  The
#: guard runs beside the task rather than waiting for the filesystem to fill.
TASK_SCRATCH_GUARD_SECONDS_ENV = "TASK_SCRATCH_GUARD_SECONDS"
DEFAULT_TASK_SCRATCH_GUARD_SECONDS = 5.0
#: Separates the allocation-wrapper resource envelope's own fields from the
#: fields the capacity guard contributes, so a guard that never observed the
#: scratch tree cannot be mistaken for one that measured zero bytes.
_SCRATCH_GUARD_PREFIX = "scratch_guard."

#: The capacity guard the allocation wrapper runs beside a task's scratch
#: directory.  It is a separate small program (its own process, signals, and
#: exit trap) rather than a shell function, so stopping it cannot disturb the
#: wrapper's own trap chain — a ``sleep`` inside a function would also delay
#: that trap.  It measures the task's bound workspace on a fixed interval and
#: stops once the measured usage passes the ceiling.
#:
#: Two consequences are deliberate.  It measures *disk usage*, so a sparse file
#: does not count (it does not fill the node).  And it measures only the task's
#: own directory, so no host filesystem state is ever attributed to a user.
#:
#: ``samples`` exists because unknown is not zero: a guard that never completed a
#: measurement reports ``samples=0``, so its peak is unknown rather than zero.
#:
#: It reports and terminates; it does not name the failure itself.  The wrapper
#: observes that it finished — which happens only when it passed the ceiling —
#: and the wrapper's single nonzero exit already marks the allocation failed.
_SCRATCH_GUARD_SCRIPT = r"""#!/bin/bash
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
#
# Task scratch capacity guard -- generated by the allocation wrapper.
set -uo pipefail

scratch_dir="${1:?scratch directory is required}"
limit_bytes="${2:?scratch limit in bytes is required}"
guard_seconds="${3:?guard interval is required}"
stop_file="${4:?stop file is required}"
result_file="${5:?result file is required}"


peak_kib=0
samples=0
exceeded=0

# Base units on the wire (bytes), so the server never has to know that this
# host happens to measure in blocks.
write_result() {
    {
        echo "peak_bytes=$(( peak_kib * 1024 ))"
        echo "samples=${samples}"
        echo "exceeded=${exceeded}"
    } >"${result_file}" 2>/dev/null || true
}

# A run that never completed a measurement writes nothing at all.  Reporting
# peak_bytes=0 for a scratch tree the guard never saw would be exactly the
# claim this guard exists to avoid: the caller reads an absent result as
# unknown, and unknown is not zero.
finish() {
    if (( samples > 0 )); then
        write_result
    fi
    exit 0
}

trap 'finish' TERM INT EXIT

while :; do
    # Measure before honouring a stop request: a stop must report the last
    # state it actually observed, and this ordering is what makes a completed
    # run always carry at least one measurement rather than a misleading zero.
    #
    # The wrapper removes the scratch directory after the task exits, which is
    # the guard's normal end: there is nothing left to measure.
    test -d "${scratch_dir}" || break
    # Sum the *allocated blocks of regular files* only.  ``du`` on the tree
    # would count the directory entries themselves, and an empty directory
    # occupies one filesystem block on ext4 — a task that wrote nothing would
    # be reported as having written 4096 bytes, and an empty scratch would not
    # read as zero.  Allocated blocks rather than apparent size keeps a sparse
    # file from counting as capacity it never used.
    # ``stat -c %b`` prints one file's allocated 512-byte blocks per line,
    # which needs no quoting of its own and cannot be confused with the
    # directory entries by accident.
    current_kib="$(find "${scratch_dir}" -type f -exec stat -c %b {} + 2>/dev/null |
        awk '{ total += $1 } END { print int(total / 2) }')" || current_kib=0
    case "${current_kib}" in (*[!0-9]*|"") current_kib=0 ;; esac
    samples=$((samples + 1))
    if (( current_kib > peak_kib )); then
        peak_kib="${current_kib}"
    fi
    # The wrapper stops the guard through a stop file rather than a signal, so
    # a stop never truncates the final measurement and never races the guard's
    # own startup (a signal delivered before the trap is installed would kill
    # the guard without writing its result at all).
    if [[ -e "${stop_file}" ]]; then
        break
    fi
    # Measured usage has passed the ceiling: record it and stop.  The
    # wrapper observes that the guard returned early and fails the
    # allocation, so the node is protected and the task is the thing that
    # ends.
    if (( peak_kib * 1024 > limit_bytes )); then
        exceeded=1
        write_result
        exit 0
    fi
    sleep "${guard_seconds}"
done
finish
"""


def render_scratch_guard_script() -> str:
    """The capacity-guard program the allocation wrapper starts beside a task."""
    return _SCRATCH_GUARD_SCRIPT


#: Runner-protocol bookkeeping lines.  They are captured durably (observations
#: in the database, progress/outcome on the task row), so the human-readable
#: capture log keeps only the runner's own diagnostics instead of repeating
#: every structured line.
_PROTOCOL_PREFIXES = (PROGRESS_PREFIX, OBSERVATION_PREFIX, TASK_OUTCOME_PREFIX)


class SlurmJob(Job):
    """A compute job submitted via SLURM + Apptainer.

    ``submit()`` launches ``srun`` and returns the scheduler job id as soon as
    job *identity* is known — from the wrapper's first stdout line or srun's
    stderr banner.  Identity is not execution: the request may still be queued,
    so ``poll()`` (or the wrapper's :data:`ALLOCATION_LIVE_PREFIX` line) is what
    reports that the allocation actually ran.
    """

    def __init__(
        self,
        task_id: str,
        tt: Any,
        runner: Any,
        entities: list[dict],
        output_dir: str,
        stage_callback: Any = None,
        manage_db: Any = None,
        username: str = "",
        resource_policy: ResolvedResources | None = None,
        scratch_backend: str = "disk",
        allocation_dispatched_callback: Any = None,
        allocation_started_callback: Any = None,
        allocation_finished_callback: Any = None,
        task_store: Any = None,
        runtime_bundle_root: str = "",
    ):
        super().__init__(task_id, tt, runner, entities, output_dir, stage_callback)
        self._db = manage_db
        # The task-row store, used to persist what the runner reports on stdout.
        # ``manage_db`` cannot serve that purpose: it is the admin configuration
        # database, not the one that owns the task row.
        self._task_store = task_store
        self._username = username
        self._process: subprocess.Popen | None = None
        self._stdout_lines: list[str] = []
        self._stderr_lines: list[str] = []
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._wrapper_script_path: str | None = None
        self._slurm_job_id: str | None = None
        self._allocation_started: float | None = None
        self._allocation_started_at: float | None = None
        # Wall-clock bounds on when the allocation could have begun, so the
        # ``poll()`` backstop can never stamp a start later than the real run.
        # ``_allocation_submitted_at`` is when srun was launched; the tighter
        # ``_wrapper_started_at`` is when the wrapper's own id line was read.
        self._allocation_submitted_at: float | None = None
        self._wrapper_started_at: float | None = None
        self._allocation_tracking_started = False
        self._allocation_finished_notified = False
        # Two separate facts, two separate gates: the request exists (job
        # identity known), and the allocation is running (the compute node
        # observed it holding resources).  Accounting hangs off the second only.
        self._dispatched_notified = False
        self._dispatch_recorded_executed = False
        self._dispatch_error: str | None = None
        self._allocation_live = False
        self._wrapper_started = False
        self._admission_error: Exception | None = None
        self._accounting_enabled = False
        self._allocation_dispatched_callback = allocation_dispatched_callback
        self._allocation_started_callback = allocation_started_callback
        self._allocation_finished_callback = allocation_finished_callback
        self._job_id_event = threading.Event()
        self._allocation_live_lock = threading.Lock()
        self._resolved_resource_policy = resource_policy
        if scratch_backend not in {"disk", "ram"}:
            raise ValueError("scratch_backend must be 'disk' or 'ram'")
        self.scratch_backend = scratch_backend
        # Deployment-owned Runtime Bundle store.  Resolved by the caller from
        # ``RUNTIME_BUNDLE_DIR``; never guessed from the task's output path,
        # which a second spelling of this location would disagree with.
        self.runtime_bundle_root = runtime_bundle_root
        self.execution_plan: ExecutionPlan = ExecutionBuilder.from_task(tt, runner)

    # -- Job ABC -------------------------------------------------------------

    def submit(self) -> str:
        if self._db is not None and not self._db.slurm_enabled():
            raise RuntimeError("SLURM is disabled — set slurm_enabled=true in admin config")

        emit_event("slurm.allocation.requested", **self._event_fields())
        try:
            self._prepare_scratch_dir()
            self._remove_allocation_approval()
            script_path = self._build_wrapper_script()
            # -u: the wrapper's stdout is a glibc-buffered pipe between the
            # allocation and slurmstepd; without it, stage markers (and the
            # REVODESIGN_JOB_ID line) sit in the buffer until job exit — or are
            # lost entirely when the job is killed, so run_stage never records
            # intermediates.  ntasks=1, so the task-zero caveat does not apply.
            cmd = ["srun", "-u"] + self._build_srun_args() + ["/bin/bash", script_path]
            logging.info("srun command: %s", " ".join(cmd))
            if self._allocation_submitted_at is None:
                # The earliest instant the allocation could have begun.  Used
                # only as a floor: the tighter wrapper-start stamp is preferred
                # whenever the wrapper's own id line was read.
                self._allocation_submitted_at = time.time()
            self._process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        except Exception:
            emit_event(
                "slurm.allocation.failed",
                level="ERROR",
                reason_code="submission_failed",
                **self._event_fields(),
            )
            self._remove_wrapper_script()
            self._cleanup_scratch_dir()
            raise

        # Background threads for live stdout/stderr capture.  The stdout
        # thread also parses REVODESIGN_STAGE: markers.
        self._stdout_lines, self._stderr_lines = [], []
        self._stdout_thread = threading.Thread(target=self._read_stdout, daemon=True)
        self._stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
        self._stdout_thread.start()
        self._stderr_thread.start()

        # Capture the real id from the allocation wrapper's first stdout line
        # or srun's stderr banner. Without it, the allocation cannot be safely
        # cancelled or recovered after a server restart.
        self._job_id_event.wait(timeout=5.0)
        if not self._slurm_job_id:
            self.cancel()
            if self._stdout_thread:
                self._stdout_thread.join(timeout=2)
            if self._stderr_thread:
                self._stderr_thread.join(timeout=2)
            self._remove_wrapper_script()
            detail = " ".join(line.strip() for line in self._stderr_lines if line.strip())
            suffix = f": {detail[-1000:]}" if detail else ""
            emit_event(
                "slurm.allocation.failed",
                level="ERROR",
                reason_code="job_id_unavailable",
                **self._event_fields(),
            )
            raise RuntimeError(f"SLURM submission did not return a scheduler job ID{suffix}")
        self._job_id = self._slurm_job_id
        # Snapshot before the callbacks run: each may block, and this is the only
        # stable answer to "does the wrapper gate on resource accounting?".
        accounting_enabled = (
            self._allocation_dispatched_callback is not None
            or self._allocation_started_callback is not None
        )
        self._accounting_enabled = accounting_enabled
        try:
            # Job identity is now known, so the scheduler owns the request.
            # ``_notify_dispatched`` writes the scheduler-owned reservation and,
            # when the wrapper's own id line was already read, the allocation
            # observation — one atomic store transition, so the request can never
            # be durably queued without the allocation its own job id proves.  A
            # failure tears the wrapper down instead of releasing it: the
            # scientific command must never run on an allocation whose fact was
            # not recorded.
            self._notify_dispatched()
            # Released to the wrapper here, so it can observe and report whether
            # the allocation is actually running.  This is not a grant: the
            # scientific command stays withheld until that report is admitted.
            if accounting_enabled:
                self._release_allocation_observation()
        except Exception as exc:
            # Keep the reason: the reader thread saw the wrapper's own id line,
            # so a persisted-fact failure is exactly the case ``poll()`` must
            # fail closed on if the process survives to reach it.
            self._dispatch_error = str(exc)
            self.cancel()
            self._remove_wrapper_script()
            raise
        self._allocation_started = time.monotonic()
        emit_event("slurm.allocation.granted", **self._event_fields())

        logging.info(
            "SLURM job %s (srun pid %s) submitted for task %s",
            self._job_id,
            self._process.pid,
            self.task_id,
        )
        return self._job_id

    def _notify_dispatched(self) -> None:
        """Announce that the scheduler owns the request, durably and once.

        Runs inside ``submit()`` while the wrapper is still held at its start
        gate, so when it returns the scheduler-owned reservation and the
        persisted job identity exist as one state — the pair a later
        reconciliation reads to decide whether a request can still be alive.

        Called twice on the identity-without-execution path, and that is the
        point: the srun stderr banner announces the request before anything is
        known to be running, and the wrapper's own stdout id line later proves it
        executed.  The identity announcement is idempotent per identity+evidence,
        but the execution evidence upgrades it — otherwise a queued banner would
        be the last word on a request whose wrapper really did occupy a node.

        The wrapper's own id line also means the compute node left a durable
        receipt, so the observation passed here carries the node's own start
        stamp and resource shape: the allocation is dated by the machine that
        held it, not by this process's clock.

        Receipt ownership moves monotonically: the file is read, never deleted up
        front, and it is removed only after the callback has returned — i.e. only
        once the canonical allocation fact (or the server-owned receipt that
        reconciliation folds into it) is durable.  A death anywhere before that
        leaves the file, so restart reconciliation still finds the claim.

        The callback persists the scheduler-owned reservation and, when the
        wrapper's own id line is the evidence, the allocation observation in the
        same store transition.  A failure therefore leaves neither half written:
        the flag is cleared and the exception propagates, so the caller (the
        reader thread or ``submit()``) tears the request down rather than letting
        the wrapper run an allocation that was never observed.
        """
        executed = self._wrapper_started
        if self._dispatched_notified and (self._dispatch_recorded_executed or not executed):
            return
        self._dispatched_notified = True
        self._dispatch_recorded_executed = executed
        if self._allocation_dispatched_callback is None:
            return
        receipt = None
        started_at = self._wrapper_started_at or time.time()
        if executed:
            receipt = self.read_allocation_receipt()
            if receipt is not None:
                started_at = receipt["observed_at"]
        try:
            adopted = self._allocation_dispatched_callback(
                self._slurm_job_id, started_at, executed, receipt
            )
        except Exception:
            # Cleared so a later observation retries instead of silently leaving
            # the request recorded as dispatched with nothing persisted.  The
            # receipt is untouched, so the retry still has it to adopt.
            self._dispatched_notified = False
            raise
        if receipt is not None and adopted is not False:
            # The callback committed to a durable successor for this claim — the
            # server-owned receipt row it wrote or the allocation fact it wrote
            # from it — so removing the file cannot lose the claim.  A callback
            # that explicitly declined the claim (``False``) leaves the file for
            # reconciliation instead.
            self.discard_allocation_receipt()

    def _notify_allocation_live(self) -> None:
        """Announce that the allocation is actually running, exactly once.

        The one entry point into allocation accounting: it consumes the Task's
        admission reservation and starts the clock that GPU- and CPU-core-seconds
        are measured against.  The wrapper's ``REVODESIGN_ALLOCATION_LIVE`` line
        reaches it through ``_read_stdout`` while the wrapper is still waiting on
        the release gate, so the release that follows is the same decision that
        recorded the allocation.  A run that never printed the line is accounted
        from ``poll()``, where the wrapper is known to have started on a node.

        The start instant is evidence, never a guess made now.  When the live
        line carries its own stamp that is used; otherwise the backstop uses the
        wall-clock floor already observed for this request — the moment the
        wrapper's id line was read, or failing that the moment srun was launched.
        Reading the clock here instead would stamp a start *after* a run that has
        already finished, charging a fully-used allocation as approximately
        zero.

        Idempotent and lock-guarded: the stdout thread and the polling thread can
        both arrive, and either report may be the one that survives.
        """
        with self._allocation_live_lock:
            if self._allocation_live:
                return
            self._allocation_live = True
            started_at = self._allocation_started_at
            if started_at is None:
                floor = self._wrapper_started_at or self._allocation_submitted_at
                started_at = time.time() if floor is None else floor
        if self._allocation_started_callback is not None:
            try:
                self._allocation_started_callback(self._slurm_job_id, started_at)
            except Exception as exc:
                # The grant was refused.  The allocation FACT was still recorded
                # — it is the scheduler's, not the policy's — so the wrapper must
                # not be released to run, and the resources it held until this
                # decision are settled at the end of the run like any other.
                self._admission_error = exc
                self._allocation_tracking_started = True
                return
        self._allocation_tracking_started = True
        if self._accounting_enabled:
            # The allocation is accounted for, so the scientific command may
            # run.  The release is this Task's admission grant; the wrapper has
            # already reported the allocation-live fact the grant answers.
            self._approve_allocation()

    @property
    def allocation_started(self) -> bool:
        """Whether this request produced a recorded allocation.

        ``False`` covers both a request that never left the scheduler's queue and
        one whose allocation-live moment was refused at admission: either way no
        allocation fact exists, so the Task's admission reservation must be given
        back rather than kept.
        """
        return self._allocation_live and self._admission_error is None

    @property
    def wrapper_executed(self) -> bool:
        """Whether the wrapper was observed executing on a compute node.

        This is the durable-evidence question, not the grant question: the
        wrapper printing its own ``$SLURM_JOB_ID`` proves an allocation was made
        even when admission then refused the command.  A caller deciding whether
        a reservation may be released must ask this, so a refused allocation is
        never downgraded to "nothing was allocated".
        """
        return self._wrapper_started

    def poll(self) -> JobState:
        if self._process is None:
            raise RuntimeError("poll() called before submit()")

        max_runtime = self._resolve_resources().max_runtime_seconds
        try:
            try:
                self._process.wait(timeout=max_runtime)
            except subprocess.TimeoutExpired:
                logging.error("SLURM job %s timed out after %d s", self._job_id, max_runtime)
                self._process.kill()
                self._process.wait()
                self._emit_terminal("slurm.allocation.failed", reason_code="timeout")
                return JobState.FAILED

            if self._stdout_thread:
                self._stdout_thread.join(timeout=10)
            if self._stderr_thread:
                self._stderr_thread.join(timeout=10)

            # The reader thread saw the wrapper's own id line but the process
            # died before the observation reached the store: the wrapper must not
            # run an allocation nothing recorded, so the job fails closed rather
            # than continue ungranted.  This never fires once the fact is
            # durable — it covers exactly the crash window a process-local flag
            # could not.
            if self._wrapper_started and not self._dispatched_notified:
                reason = self._dispatch_error or "the allocation observation could not be persisted"
                logging.error("SLURM job %s failed closed: %s", self._job_id, reason)
                self._emit_terminal("slurm.allocation.failed", reason_code="allocation_unrecorded")
                return JobState.FAILED

            # The wrapper itself started on a compute node — it printed its own
            # job id — but its allocation-live report never arrived, either
            # because the node's scheduler query is unavailable or because the
            # run was killed before it could report.  The wrapper running is
            # itself evidence the request left the queue, so the allocation it
            # held is accounted here; a request that never left the queue never
            # printed that line and still charges nothing.  The release is
            # written first, so a wrapper still waiting is never left to hit its
            # own bounded wait on an allocation that has already ended.
            if not self._allocation_live and self._wrapper_started:
                if self._accounting_enabled:
                    self._release_allocation_observation()
                self._notify_allocation_live()

            # An allocation the admission transition refused is not a grant: the
            # wrapper was never released, srun is expected to have exited
            # nonzero, and the refusal is the Task's failure rather than an
            # accounting detail to swallow.
            if self._admission_error is not None:
                raise self._admission_error

            # The wrapper is removed before any output is captured, so a task
            # that rewrote the running script cannot ship those bytes in the
            # download archive.
            self._remove_wrapper_script()
            self._save_output()

            exit_code = self._process.returncode
            if exit_code == 0:
                if not self._has_result_artifact():
                    logging.error(
                        "SLURM job %s exited successfully but produced no non-empty result artifacts",
                        self._job_id,
                    )
                    self._emit_terminal("slurm.allocation.failed", reason_code="missing_result")
                    return JobState.FAILED
                self._maybe_stage_callback(JobState.COMPLETED)
                self._emit_terminal("slurm.allocation.finished")
                return JobState.COMPLETED

            logging.error("SLURM job %s failed with exit code %s", self._job_id, exit_code)
            self._emit_terminal("slurm.allocation.failed", reason_code="nonzero_exit")
            return JobState.FAILED
        finally:
            # Ingest before the terminal event, and for every outcome: an OOM
            # row is the evidence the estimator exists to learn from, and a
            # failed run is where it appears.
            self._ingest_runner_protocol()
            self._notify_allocation_finished()
            self._remove_allocation_approval()
            self._remove_wrapper_script()
            self._cleanup_scratch_dir()

    def cancel(self) -> None:
        proc = self._process
        if proc is None or proc.poll() is not None:
            self._cleanup_scratch_dir()
            return
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        logging.info("srun process %s terminated for task %s", proc.pid, self.task_id)
        try:
            if self._slurm_job_id:
                self._emit_terminal("slurm.allocation.cancelled")
        finally:
            self._remove_allocation_approval()
            self._cleanup_scratch_dir()

    # -- srun arguments ------------------------------------------------------

    def _resolve_resources(self) -> ResolvedResources:
        if self._resolved_resource_policy is not None:
            return self._resolved_resource_policy
        if self._db is not None and hasattr(self._db, "resolve_task_resources"):
            resources = self._db.resolve_task_resources(
                self.tt.name,
                requires_gpu=self.tt.gpus,
                default_timeout_seconds=self.runner.max_runtime_seconds,
            )
        else:
            resources = resolve_resources(
                lambda _field: None,
                lambda _field: None,
                requires_gpu=self.tt.gpus,
                allowed_queues=(),
                default_timeout_seconds=self.runner.max_runtime_seconds,
            )
        self._resolved_resource_policy = resources
        return resources

    def _event_fields(self) -> dict[str, Any]:
        return {
            "task_id": str(self.task_id),
            "task_type": str(getattr(self.tt, "name", "")) or None,
            "runner_family": str(getattr(getattr(self.tt, "runtime", None), "name", "")) or None,
            "slurm_job_id": self._slurm_job_id,
        }

    def _emit_terminal(self, event: str, *, reason_code: str | None = None) -> None:
        duration_ms = None
        if self._allocation_started is not None:
            duration_ms = max(0, round((time.monotonic() - self._allocation_started) * 1000))
        emit_event(
            event,
            level="ERROR" if event == "slurm.allocation.failed" else "INFO",
            reason_code=reason_code,
            duration_ms=duration_ms,
            **self._event_fields(),
        )
        self._notify_allocation_finished()

    def _notify_allocation_finished(self) -> None:
        if self._allocation_finished_notified or not self._allocation_tracking_started:
            return
        if self._allocation_finished_callback is not None:
            try:
                self._allocation_finished_callback(self._slurm_job_id, time.time())
            except Exception:
                # The finish/settlement callback is accounting, not execution:
                # never let it escape poll() and fail an already-finished job.
                logging.exception(
                    "GPU allocation finish callback failed for Slurm job %s", self._slurm_job_id
                )
        self._allocation_finished_notified = True

    def _approve_allocation(self) -> None:
        """Release an accounted-for allocation to run its scientific command.

        The grant, not the start gate: the allocation has been recorded, so the
        Task is allowed to consume it.  Idempotent — the wrapper's own live line
        and the poll-side backstop can both arrive, and the wrapper consumes the
        file, so an existing one already means the grant stands.
        """
        self._write_release(self._allocation_grant_path)

    def _release_allocation_observation(self) -> None:
        """Release the wrapper to observe whether its allocation is running.

        This is *not* permission to run the task — it is what lets the wrapper
        report the allocation-live fact the admission decision answers.  It is
        written as soon as the scheduler owns the request, so the observation
        happens while the scientific command is still withheld.
        """
        self._write_release(self._allocation_release_path)

    @staticmethod
    def _write_release(path: str) -> None:
        try:
            with open(path, "x", encoding="utf-8"):
                pass
        except FileExistsError:
            pass

    @property
    def _allocation_release_path(self) -> str:
        """Host-to-wrapper gate: "observe whether this allocation is running"."""
        return os.path.join(self.output_dir, f".allocation-start-{self.task_id[:8]}")

    @property
    def _allocation_grant_path(self) -> str:
        """Host-to-wrapper gate: "run the scientific command for this allocation"."""
        return os.path.join(self.output_dir, f".allocation-approved-{self.task_id[:8]}")

    @property
    def _allocation_receipt_path(self) -> str:
        """A sibling of the other host-to-wrapper gate paths."""
        return self.allocation_receipt_path

    def read_allocation_receipt(self) -> dict[str, Any] | None:
        """Read the wrapper's compute-node receipt, if it left one.

        Returns ``None`` when there is no receipt, when it is unreadable, or when
        its schema does not match — a receipt that cannot be trusted as written
        is treated as absent rather than guessed at.  The values are parsed, not
        interpreted: corroborating the job id against the scheduler belongs to
        reconciliation, which has the scheduler.

        Reading is deliberately non-destructive.  The file is the only durable
        evidence a worker that dies before its own first write ever leaves, so it
        is read and then *adopted* — either by the live dispatch
        (:meth:`_notify_dispatched`) or, after a crash, by restart reconciliation
        — and removed only once that adoption is durable.  A malformed receipt is
        left exactly where it is, so an anomalous durable observation stays
        inspectable instead of vanishing.
        """
        path = self.allocation_receipt_path
        try:
            with open(path, encoding="utf-8") as handle:
                text = handle.read(4096)
        except OSError:
            return None
        return parse_allocation_receipt(text)

    def discard_allocation_receipt(self) -> None:
        """Remove the compute-node receipt once a durable successor exists.

        Ownership transfer is monotonic: the file may only be deleted after the
        server-owned receipt or the canonical allocation fact records the same
        claim, so there is never a transition from one durable representation to
        none.  Deletion is best-effort and idempotent — a missing file is already
        the desired state, and a failure merely leaves evidence behind for the
        next reconciliation, which adopts it again harmlessly.
        """
        try:
            os.unlink(self.allocation_receipt_path)
        except OSError:
            pass

    def _remove_allocation_approval(self) -> None:
        for path in (self._allocation_release_path, self._allocation_grant_path):
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass

    def _build_srun_args(self) -> list[str]:
        resources = self._resolve_resources()
        resolved = {
            "partition": resources.partition,
            "cpus-per-task": resources.cpus,
            "gres": resources.gres,
            "mem": resources.memory,
            "time": resources.slurm_time,
            "nodes": resources.nodes,
            "ntasks": resources.ntasks,
            "qos": resources.qos,
            "account": resources.account,
            "constraint": resources.constraint,
        }
        opts: list[str] = []
        for option, value in resolved.items():
            if value is None:
                continue
            opts.append(f"--{option}={value}")
        if resources.exclusive:
            opts.append("--exclusive")

        # The worker container's /app/server cwd does not exist on compute
        # nodes.  Use the task-specific shared output directory so slurmstepd
        # never falls back to /tmp and every job has an isolated valid cwd.
        opts.append(f"--chdir={self.output_dir}")
        opts.append(f"--job-name=revocomput_{_sanitize_name(self._username)}_{self.tt.name}_{self.task_id[:8]}")
        return opts

    # -- wrapper script ------------------------------------------------------

    def _prepare_scratch_dir(self) -> None:
        """Create private task-backed scratch before the allocation starts.

        This directory *is* the task's ephemeral workspace: the allocation
        wrapper binds it to the container's ``/tmp`` and the capacity guard
        measures it.  It is deliberately independent of durable storage
        entitlement — a pathological temporary file is a per-execution safety
        problem, not something a user's storage quota should pay for.
        """
        if self.scratch_backend == "ram":
            return
        # Input staging creates the task workspace in production.  Test and
        # recovery callers may render/submit against a synthetic snapshot that
        # is not present on this host; preserve that boundary and let srun
        # report the missing input as it did previously.
        if not os.path.isdir(self.task_workspace_root):
            return
        if os.path.lexists(self.scratch_dir):
            if os.path.isdir(self.scratch_dir) and not os.path.islink(self.scratch_dir):
                shutil.rmtree(self.scratch_dir)
            else:
                os.unlink(self.scratch_dir)
        os.makedirs(self.scratch_dir, mode=0o700, exist_ok=True)
        os.chmod(self.scratch_dir, 0o700)

    @property
    def scratch_limit_bytes(self) -> int:
        """The hard ceiling for this Task's ephemeral scratch, in bytes.

        Read by the allocation wrapper, which enforces it on the compute node:
        the guard belongs to the process that owns the workspace, not to the
        server that renders the allocation.
        """
        raw = os.environ.get(TASK_SCRATCH_LIMIT_ENV, "").strip()
        if raw:
            try:
                value = int(raw)
            except ValueError as exc:
                raise RuntimeError(f"{TASK_SCRATCH_LIMIT_ENV} must be an integer, got {raw!r}") from exc
            if value <= 0:
                raise RuntimeError(f"{TASK_SCRATCH_LIMIT_ENV} must be positive")
            return value
        return DEFAULT_TASK_SCRATCH_LIMIT_BYTES

    @property
    def scratch_guard_seconds(self) -> float:
        """How often the capacity guard re-measures the scratch tree."""
        raw = os.environ.get(TASK_SCRATCH_GUARD_SECONDS_ENV, "").strip()
        if raw:
            try:
                value = float(raw)
            except ValueError as exc:
                raise RuntimeError(f"{TASK_SCRATCH_GUARD_SECONDS_ENV} must be a number, got {raw!r}") from exc
            if value <= 0:
                raise RuntimeError(f"{TASK_SCRATCH_GUARD_SECONDS_ENV} must be positive")
            return value
        return DEFAULT_TASK_SCRATCH_GUARD_SECONDS

    def _cleanup_scratch_dir(self) -> None:
        if self.scratch_backend != "disk":
            return
        if os.path.isdir(self.scratch_dir):
            shutil.rmtree(self.scratch_dir, ignore_errors=True)

    @property
    def scratch_path(self) -> str:
        if self.scratch_backend == "ram":
            label = _sanitize_name(self.task_id)[:32]
            digest = hashlib.sha256(self.task_id.encode("utf-8")).hexdigest()[:16]
            return f"/dev/shm/revocompute/{label}-{digest}"
        return self.scratch_dir

    @property
    def allocation_dir(self) -> str:
        """Host-only directory that holds the allocation wrapper script.

        It must be outside every host path bind-mounted into the container —
        ``output_dir`` (``/workspace/outputs``), the input snapshot, the runner
        mounts, and scratch (``/tmp``).  Bash reads a running script
        incrementally, so a wrapper inside that writable view would let a task
        process rewrite the not-yet-executed tail, which bash then runs on the
        host as the worker uid, outside Apptainer and outside
        ``--net --network none``.  A sibling of the task output directory is
        never mounted and always exists, so ``srun`` still reads it on the
        compute node.
        """
        return allocation_dir_for(self.output_dir)

    @property
    def allocation_receipt_path(self) -> str:
        """Where the wrapper records that it is running, in the host-only dir.

        Deliberately the *same* never-bind-mounted sibling as the wrapper script:
        ``output_dir`` is mounted read-write into the container, so a receipt
        there would be forgeable by the task it describes.  A receipt in this
        directory can only be written by the wrapper running on the compute node
        as the worker uid, outside the container.
        """
        return os.path.join(self.allocation_dir, ALLOCATION_RECEIPT_NAME)
    def _build_wrapper_script(self) -> str:
        """Write the wrapper script into the host-only ``allocation_dir`` so
        the host-side ``srun`` process can read it while the container cannot.
        Returns the path as a string."""
        script = self._render_wrapper()
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.allocation_dir, mode=0o700, exist_ok=True)
        os.chmod(self.allocation_dir, 0o700)
        path = os.path.join(self.allocation_dir, f"_slurm_wrapper_{self.task_id[:8]}.sh")
        with open(path, "w") as f:
            f.write(script)
        os.chmod(path, 0o700)
        self._wrapper_script_path = path
        return path

    def _render_wrapper(self) -> str:
        lines = [
            "#!/bin/bash",
            "set -euo pipefail",
            "",
            # The allocation exists the moment the scheduler starts this script,
            # so the FIRST thing it does is take a durable receipt of that fact —
            # before any gate wait, any stdout line, and any scientific work.
            # The write is atomic (temp + fsync + rename), into the host-only
            # directory that is never bind-mounted into the container, so only
            # this wrapper (running as the worker uid on the compute node) can
            # author it and a worker that dies before its own first write still
            # leaves the evidence reconciliation needs.
            f"allocation_receipt={_sh_quote(self._allocation_receipt_path)}",
            'mkdir -p -- "$(dirname -- "${allocation_receipt}")"',
            'receipt_cpus="${SLURM_CPUS_PER_TASK:-}"',
            'case "${receipt_cpus}" in (*[!0-9]*|"") receipt_cpus=0 ;; esac',
            'receipt_gpus="${SLURM_GPUS_ON_NODE:-}"',
            'case "${receipt_gpus}" in (*[!0-9]*|"") receipt_gpus="${SLURM_JOB_GPUS:-${CUDA_VISIBLE_DEVICES:-}}" ;; esac',
            'case "${receipt_gpus}" in',
            '  ("NoDevFiles") receipt_gpus=0 ;;',
            '  (*[!0-9,]*) receipt_gpus=0 ;;',
            '  ("") receipt_gpus=0 ;;',
            '  (*) receipt_gpus="$(awk -F, \'{print NF}\' <<< "${receipt_gpus}")" ;;',
            "esac",
            'receipt_tmp="${allocation_receipt}.$$.tmp"',
            "{",
            "  printf 'schema_version=1\\n'",
            "  printf 'slurm_job_id=%s\\n' \"${SLURM_JOB_ID:-}\"",
            "  printf 'observed_at=%s\\n' \"$(date +%s)\"",
            "  printf 'cpus=%s\\n' \"${receipt_cpus}\"",
            "  printf 'gpus=%s\\n' \"${receipt_gpus}\"",
            "} > \"${receipt_tmp}\"",
            'sync "${receipt_tmp}"',
            'mv -f -- "${receipt_tmp}" "${allocation_receipt}"',
            "",
            # The allocation carries the authoritative job id; publish it on
            # stdout only AFTER the receipt is durable, so the receipt — not the
            # line — is what recovery keys on, and the line can never be the only
            # trace of a run.  This names the request; it is not evidence that
            # anything is running.
            f'echo "{JOB_ID_PREFIX}${{SLURM_JOB_ID}}"',
        ]
        if self._allocation_dispatched_callback is not None or self._allocation_started_callback is not None:
            lines.extend(
                [
                    # Two gates, because there are two different questions.  The
                    # start gate releases the wrapper to observe its own
                    # allocation; it is not permission to run the task.  The
                    # grant gate after the live line is the admission decision,
                    # and only then does the scientific command run.
                    f"start={_sh_quote(self._allocation_release_path)}",
                    'for _ in {1..300}; do test -f "$start" && break; sleep 0.1; done',
                    'test -f "$start"',
                    'rm -f -- "$start"',
                    "# -- allocation-live observation --",
                    # ``squeue`` answers from the scheduler's own state: a
                    # PENDING or CONFIGURING job has been allocated nothing yet,
                    # and charging it would charge queue latency as GPU- and
                    # CPU-seconds.  Only RUNNING is allocation-live, and only
                    # this line starts the accounting clock.
                    "allocation_live=0",
                    f"for _ in {{1..{ALLOCATION_LIVE_POLLS}}}; do",
                    '  state="$(squeue -h -j "${SLURM_JOB_ID}" -o "%T" 2>/dev/null | head -n 1)"',
                    '  case "${state}" in',
                    '    (RUNNING) allocation_live=1; break ;;',
                    # No answer yet: keep waiting for the state rather than
                    # reporting a job that has not been allocated anything as
                    # live.  A query that errors is retried for the same reason.
                    '    ("") ;;',
                    # A state was read and it is not RUNNING: this job has been
                    # allocated nothing and never will be, so stop waiting.
                    "    (*) break ;;",
                    "  esac",
                    f"  sleep {ALLOCATION_LIVE_POLL_SECONDS}",
                    "done",
                    'if [[ "${allocation_live}" != 1 ]]; then',
                    # The state was read and was not RUNNING (a queued job that
                    # can no longer run, or one already gone).  No allocation is
                    # ever accounted without this evidence, so one that never
                    # reached RUNNING is charged nothing.
                    '  echo "SLURM job ${SLURM_JOB_ID} did not reach RUNNING state" >&2',
                    "  exit 1",
                    "fi",
                    f'echo "{ALLOCATION_LIVE_PREFIX}${{SLURM_JOB_ID}}"',
                    "# -- admission grant --",
                    # Allocation-live is a fact about the scheduler, not a grant:
                    # the server makes the admission decision when it observes it,
                    # and an allocation the balance cannot cover is stopped here,
                    # before the task does any work.  The wait has a bound so a
                    # server that never answers cannot pin a node forever.
                    f"grant={_sh_quote(self._allocation_grant_path)}",
                    "released=0",
                    f"for _ in {{1..{ALLOCATION_RELEASE_POLLS}}}; do",
                    '  if test -f "$grant"; then released=1; break; fi',
                    f"  sleep {ALLOCATION_RELEASE_POLL_SECONDS}",
                    "done",
                    'if [[ "${released}" != 1 ]]; then',
                    '  echo "allocation was not released to run" >&2',
                    "  exit 1",
                    "fi",
                    'rm -f -- "$grant"',
                ]
            )
        if self.scratch_backend == "ram":
            lines.extend([
                "umask 077",
                "mkdir -p /dev/shm/revocompute",
                "chmod 700 /dev/shm/revocompute",
                "while IFS= read -r -d '' stale; do",
                '  stale_job_id=$(cat "$stale/.slurm-job-id" 2>/dev/null) || continue',
                '  case "$stale_job_id" in (*[!0-9]*|"") continue ;; esac',
                '  if running=$(squeue -h -j "$stale_job_id" -o "%i" 2>/dev/null); then',
                '    grep -Fxq "$stale_job_id" <<<"$running" || rm -rf -- "$stale"',
                "  fi",
                "done < <(find /dev/shm/revocompute -mindepth 1 -maxdepth 1 "
                "-type d -mmin +1440 -print0)",
                f"rm -rf -- {_sh_quote(self.scratch_path)}",
                f"mkdir -p {_sh_quote(self.scratch_path)}",
                f"chmod 700 {_sh_quote(self.scratch_path)}",
                f"printf '%s\\n' \"$SLURM_JOB_ID\" > {_sh_quote(self.scratch_path + '/.slurm-job-id')}",
                f'trap "rm -rf -- {self.scratch_path}" EXIT',
            ])
        self._render_input_staging(lines)
        lines.append("")
        self._render_apptainer_invocation(lines)
        return "\n".join(lines) + "\n"

    def _render_input_staging(self, lines: list[str]) -> None:
        lines.append("# -- immutable input snapshot verification --")
        for fe in self.file_entities:
            lines.append(f"test -f {_sh_quote(fe['snapshot_path'])}")
            checksum_record = f"{fe['hash']}  {fe['snapshot_path']}"
            lines.append(f"printf '%s\\n' {_sh_quote(checksum_record)} | sha256sum --check --status")

    def _pinned_runtime_bundle(self) -> str | None:
        """Resolve the task's pinned Runtime Bundle directory, or fail closed.

        The digest travels with the task in its immutable ``task.json``, so a
        queued task executes the bundle it was submitted under even after a
        deployment activates another one.  A declared bundle that no longer
        resolves is a hard error: mounting a *different* bundle would silently
        run code the task's receipt never validated.
        """
        try:
            manifest = json.loads(
                Path(self.input_snapshot_root, "task.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            manifest = None
        pinned = manifest.get("runtime_bundle_sha256") if isinstance(manifest, dict) else None
        if not isinstance(pinned, str) or not pinned:
            # A family that declares an overlay cannot execute without the
            # bundle: it would launch an entrypoint that is not mounted.  That
            # covers an unreadable manifest and a manifest written without a
            # pin, so neither can become a silent no-mount launch.
            if self.tt.runtime.runtime_overlay:
                raise RuntimeError(
                    f"Task {self.task_id!r} declares a runtime overlay but has no pinned runtime bundle"
                )
            return None
        resolved = runtime_bundle.resolve_pinned(self.runtime_bundle_root, pinned)
        if resolved is None:
            raise RuntimeError(
                f"Task {self.task_id!r} pins an unavailable runtime bundle: {pinned!r}"
            )
        return resolved

    def _render_apptainer_invocation(self, lines: list[str]) -> None:
        sif_image = self.execution_plan.image
        if not sif_image or sif_image == "<missing-image>":
            raise RuntimeError(f"Execution plan for task {self.task_id!r} has no slurm_image")

        bind_parts: list[str] = []
        bind_parts.append(
            f"--bind {_sh_quote(self.input_snapshot_root)}:{_sh_quote(self.virtual_workspace_root + '/inputs')}:ro"
        )
        bind_parts.append(f"--bind {_sh_quote(self.output_dir)}:{_sh_quote(self.virtual_workspace_root + '/outputs')}")
        for m in self.execution_plan.mounts:
            bind_parts.append(
                f"--bind {_sh_quote(str(m['source']))}:{_sh_quote(str(m['target']))}:{m.get('mode', 'ro')}"
            )
        # The Runtime Bundle is always read-only at one reserved container root.
        # Its source is the digest-pinned snapshot, never the runner checkout or
        # an operator mount, so it cannot be swapped under a running task.
        bundle = self._pinned_runtime_bundle()
        if bundle is not None:
            bind_parts.append(
                f"--bind {_sh_quote(str(bundle))}:{_sh_quote(runtime_bundle.RUNTIME_MOUNT_TARGET)}:ro"
            )
        # Bind task scratch last so every runner gets the same private /tmp,
        # regardless of any runtime-specific resource mounts.
        bind_parts.append(f"--bind {_sh_quote(self.scratch_path)}:/tmp")

        lines.append("# -- apptainer --")
        # APPTAINERENV_ prefixed vars are forwarded into the container.
        lines.append(f"export APPTAINERENV_TASK_ID={_sh_quote(self.task_id)}")
        lines.append(f"export APPTAINERENV_TASK_TYPE={_sh_quote(self.tt.name)}")
        for key, val in self.execution_plan.environment.items():
            lines.append(f"export APPTAINERENV_{key}={_sh_quote(val)}")

        # Keep threaded numerical libraries inside the allocation.  Without
        # this, PyTorch/OpenMP can observe all host CPUs even when Slurm grants
        # a smaller cpus-per-task value, causing silent overcommit.
        lines.extend(
            [
                'allocated_cpus="${SLURM_CPUS_PER_TASK:-1}"',
                'case "${allocated_cpus}" in (*[!0-9]*|""|0) allocated_cpus=1 ;; esac',
                'export APPTAINERENV_NPROC="${allocated_cpus}"',
                'export APPTAINERENV_OMP_NUM_THREADS="${allocated_cpus}"',
                'export APPTAINERENV_MKL_NUM_THREADS="${allocated_cpus}"',
                'export APPTAINERENV_OPENBLAS_NUM_THREADS="${allocated_cpus}"',
                'export APPTAINERENV_VECLIB_MAXIMUM_THREADS="${allocated_cpus}"',
                'export APPTAINERENV_NUMEXPR_NUM_THREADS="${allocated_cpus}"',
                'export APPTAINERENV_TF_NUM_INTRAOP_THREADS="${allocated_cpus}"',
                'export APPTAINERENV_TF_NUM_INTEROP_THREADS="${allocated_cpus}"',
            ]
        )

        # Runner protocol v2: task.json lives in the immutable input snapshot;
        # the environment carries only its backslash-free path.
        lines.append(
            "export APPTAINERENV_TASK_MANIFEST=" + _sh_quote(self.virtual_workspace_root + "/inputs/task.json")
        )
        gpu_flag = " --nv" if self.tt.gpus else ""
        if self.tt.gpus:
            # --cleanenv otherwise drops SLURM's selected GPU before OpenMM
            # starts inside the container, despite --nv binding its devices.
            lines.append('export APPTAINERENV_CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-}"')
        # --containall: private /dev,/proc,/sys and $HOME. /tmp is the
        # explicitly bound task scratch; host /tmp and other tasks stay hidden.
        # --cleanenv: host env is dropped; only the APPTAINERENV_* variables
        # exported above are forwarded. All required mounts are the explicit
        # --bind entries, so containment costs nothing for these images.
        # --no-home is explicit belt-and-braces over --containall's private
        # HOME, and mirrors the Tool runtime's flags.
        # Network is a *declared* capability: --containall does NOT create a
        # network namespace, so without an explicit flag a runner would inherit
        # the host namespace and reach the worker's Redis broker, the gateway,
        # and every other loopback service. A task that does not declare
        # requires_network gets loopback-only isolation. A task that does
        # declare it keeps the host namespace — an isolated egress namespace
        # needs a root/suid-configured bridge, which is a deployment choice
        # this adapter cannot assume.
        net_flag = "" if self.tt.requires_network else " --net --network none"
        # ExecutionPlan.command is authoritative: use exec so task-owned
        # entrypoints and arguments cannot be silently ignored by the adapter.
        command = " ".join(_sh_quote(part) for part in self.execution_plan.command)
        cmd = (
            f"apptainer exec{gpu_flag} --containall --cleanenv --no-home{net_flag} "
            f"{' '.join(bind_parts)} {_sh_quote(sif_image)} {command}"
        )
        for arg in self.execution_plan.arguments:
            # Task-owned plans may request scheduler-provided values without
            # making the infrastructure adapter aware of scientific runners.
            value = str(arg)
            if value == "${allocated_cpus}":
                cmd += ' "${allocated_cpus}"'
            else:
                cmd += f" {_sh_quote(value)}"
        cmd += f" -i {_sh_quote(self.virtual_workspace_root + '/inputs/task.json')}"
        cmd += f" -o {_sh_quote(self.virtual_workspace_root + '/outputs')}"
        resource_path = '"${resource_capture_dir}/resource"'
        resource_time_path = '"${resource_capture_dir}/time"'
        resource_gpu_path = '"${resource_capture_dir}/gpu"'
        lines.extend(
            [
                'resource_capture_dir="$(mktemp -d /tmp/revocompute-resource.XXXXXX)"',
                'chmod 700 "${resource_capture_dir}"',
                "# -- ephemeral scratch capacity guard --",
                # The guard runs beside the task, not inside it, and measures the
                # task's own bound workspace.  It is written here rather than
                # shipped as a file so it cannot be left behind by an interrupted
                # run and cannot be rewritten by the task: it lives in the host
                # capture directory, which is outside every mount the container
                # can see.
                f'scratch_guard_path={_sh_quote(self.scratch_path)}',
                f"scratch_guard_limit_bytes={self.scratch_limit_bytes}",
                f"scratch_guard_seconds={self.scratch_guard_seconds}",
                'scratch_guard_script="${resource_capture_dir}/scratch_guard.sh"',
                'scratch_guard_stop="${resource_capture_dir}/scratch_guard.stop"',
                'scratch_guard_result="${resource_capture_dir}/scratch_guard.result"',
                "scratch_guard_pid=''",
                "cat > \"${scratch_guard_script}\" <<'REVODESIGN_SCRATCH_GUARD'",
                *render_scratch_guard_script().splitlines(),
                "REVODESIGN_SCRATCH_GUARD",
                'chmod 700 "${scratch_guard_script}"',
                "start_scratch_guard() {",
                '  "${scratch_guard_script}" "${scratch_guard_path}" '
                '"${scratch_guard_limit_bytes}" "${scratch_guard_seconds}" '
                '"${scratch_guard_stop}" "${scratch_guard_result}" &',
                '  scratch_guard_pid="$!"',
                "}",
                "stop_scratch_guard() {",
                '  [[ -n "${scratch_guard_pid:-}" ]] || return 0',
                # The stop file is what makes the stop deterministic (the guard
                # may not have installed its trap yet); the signal is what makes
                # it immediate, so a normal stop does not wait a whole interval.
                '  touch "${scratch_guard_stop}" 2>/dev/null || true',
                '  kill "${scratch_guard_pid}" 2>/dev/null || true',
                '  wait "${scratch_guard_pid}" 2>/dev/null || true',
                "  scratch_guard_pid=''",
                "}",
                "cleanup_resource_capture() {",
                "  stop_scratch_guard",
                '  if [[ -n "${gpu_monitor_pid:-}" ]]; then',
                '    kill "${gpu_monitor_pid}" 2>/dev/null || true',
                '    wait "${gpu_monitor_pid}" 2>/dev/null || true',
                "  fi",
                '  rm -f -- "${resource_capture_dir}/resource" "${resource_capture_dir}/time" '
                '"${resource_capture_dir}/gpu" "${scratch_guard_script}" '
                '"${scratch_guard_stop}" "${scratch_guard_result}"',
                '  rmdir -- "${resource_capture_dir}" 2>/dev/null || true',
                "}",
                "trap cleanup_resource_capture EXIT",
            ]
        )
        if self.tt.gpus:
            lines.extend(
                [
                    "# -- allocation GPU observation --",
                    "sample_gpu_metrics() {",
                    "  local query_target sample memory utilization",
                    "  local max_memory='' max_utilization=''",
                    '  query_target="${SLURM_JOB_GPUS:-${CUDA_VISIBLE_DEVICES:-}}"',
                    '  [[ -n "${query_target}" ]] || return 0',
                    f"  if [[ -f {resource_gpu_path} ]]; then",
                    "    while IFS='=' read -r metric value; do",
                    '      case "${metric}" in',
                    '        gpu_memory_peak_mib) max_memory="${value}" ;;',
                    '        gpu_utilization_peak_percent) max_utilization="${value}" ;;',
                    "      esac",
                    f"    done < {resource_gpu_path}",
                    "  fi",
                    '  sample="$(nvidia-smi --id="${query_target}" '
                    '--query-gpu=memory.used,utilization.gpu --format=csv,noheader,nounits 2>/dev/null || true)"',
                    "  while IFS=',' read -r memory utilization; do",
                    '    memory="${memory//[[:space:]]/}"',
                    '    utilization="${utilization//[[:space:]]/}"',
                    '    case "${memory}" in (*[!0-9]*|\'\') ;; (*)',
                    '      if [[ -z "${max_memory}" || ${memory} -gt ${max_memory} ]]; then',
                    '        max_memory="${memory}"',
                    "      fi ;;",
                    "    esac",
                    '    case "${utilization}" in (*[!0-9]*|\'\') ;; (*)',
                    '      if [[ -z "${max_utilization}" || ${utilization} -gt ${max_utilization} ]]; then',
                    '        max_utilization="${utilization}"',
                    "      fi ;;",
                    "    esac",
                    '  done <<< "${sample}"',
                    '  if [[ -n "${max_memory}" && -n "${max_utilization}" ]]; then',
                    "    {",
                    '      printf \'gpu_memory_peak_mib=%s\\n\' "${max_memory}"',
                    '      printf \'gpu_utilization_peak_percent=%s\\n\' "${max_utilization}"',
                    f"    }} > {resource_gpu_path}",
                    "  fi",
                    "}",
                    "gpu_monitor_pid=''",
                    "if command -v nvidia-smi >/dev/null 2>&1; then",
                    "  sample_gpu_metrics",
                    "  (while :; do sleep 1; sample_gpu_metrics; done) &",
                    '  gpu_monitor_pid="$!"',
                    "fi",
                ]
            )
        lines.extend(
            [
                "# -- allocation resource observation --",
                'allocated_gpu_ids="${SLURM_JOB_GPUS:-${CUDA_VISIBLE_DEVICES:-}}"',
                'allocated_gpus_on_node="${SLURM_GPUS_ON_NODE:-}"',
                'if [[ -z "${allocated_gpus_on_node}" && -n "${allocated_gpu_ids}" '
                '&& "${allocated_gpu_ids}" != "NoDevFiles" ]]; then',
                '  allocated_gpus_on_node="$(awk -F, \'{print NF}\' <<< "${allocated_gpu_ids}")"',
                "fi",
                "start_scratch_guard",
                "if [[ -x /usr/bin/time ]]; then",
                "  time_prefix=(/usr/bin/time -f 'elapsed_seconds=%e\\nuser_cpu_seconds=%U\\n"
                f"system_cpu_seconds=%S\\nmax_rss_kib=%M' -o {resource_time_path})",
                "else",
                "  time_prefix=()",
                "fi",
                # The task runs in its own process group (job control), so the
                # capacity guard can stop the entire task tree — apptainer and
                # every process it started — without signalling the wrapper
                # itself, which would take this script down before it can report
                # what it measured.
                "set -m",
                f'"${{time_prefix[@]}}" {cmd} &',
                'runner_pid="$!"',
                "set +m",
                "runner_status=0",
                'while kill -0 "${runner_pid}" 2>/dev/null; do',
                '  if ! kill -0 "${scratch_guard_pid}" 2>/dev/null; then',
                "    # The guard finished before the task: measured scratch passed the",
                "    # ceiling.  Stopping the whole task tree is the point of the",
                "    # guard; the allocation then ends nonzero, so the failure is the",
                "    # task's and the node keeps its capacity.",
                '    kill -TERM -- "-${runner_pid}" 2>/dev/null || true',
                "    break",
                "  fi",
                "  sleep 0.2",
                "done",
                'if wait "${runner_pid}"; then runner_status=0; else runner_status=$?; fi',
                # A task that had already exited zero exactly as the guard
                # tripped must still fail: it ran past its ceiling.
                'if [[ -f "${scratch_guard_result}" ]] && grep -qx "exceeded=1" '
                '"${scratch_guard_result}" && (( runner_status == 0 )); then',
                "  runner_status=1",
                "fi",
                *(
                    [
                        'if [[ -n "${gpu_monitor_pid}" ]]; then',
                        '  kill "${gpu_monitor_pid}" 2>/dev/null || true',
                        '  wait "${gpu_monitor_pid}" 2>/dev/null || true',
                        "  gpu_monitor_pid=''",
                        "  sample_gpu_metrics",
                        "fi",
                    ]
                    if self.tt.gpus
                    else []
                ),
                # The guard is stopped before the envelope is written so the
                # facts it reports are final.
                "stop_scratch_guard",
                "{",
                "  printf 'schema_version=1\\n'",
                "  printf 'source=allocation_wrapper\\n'",
                "  printf 'job_id=%s\\n' \"${SLURM_JOB_ID:-}\"",
                "  printf 'allocated_cpus_per_task=%s\\n' \"${SLURM_CPUS_PER_TASK:-}\"",
                "  printf 'allocated_tasks=%s\\n' \"${SLURM_NTASKS:-1}\"",
                "  printf 'allocated_gpus_on_node=%s\\n' \"${allocated_gpus_on_node}\"",
                "  printf 'allocated_gpu_ids=%s\\n' \"${allocated_gpu_ids}\"",
                "  printf 'visible_gpu_devices=%s\\n' \"${CUDA_VISIBLE_DEVICES:-}\"",
                "  printf 'exit_code=%s\\n' \"$runner_status\"",
                # The capacity guard's own measurement, reported only when it
                # completed one: a guard that never sampled emits nothing, which
                # the server reads as unknown rather than as zero bytes.
                '  if [[ -f "${scratch_guard_result}" ]]; then',
                '    while IFS=\'=\' read -r scratch_metric scratch_value; do',
                '      case "${scratch_metric}" in',
                "        (peak_bytes|samples|exceeded) "
                f"printf '{_SCRATCH_GUARD_PREFIX}%s=%s\\n' \"${{scratch_metric}}\" \"${{scratch_value}}\" ;;",
                "      esac",
                '    done < "${scratch_guard_result}"',
                "  fi",
                f"  test ! -f {resource_time_path} || cat {resource_time_path}",
                *([f"  test ! -f {resource_gpu_path} || cat {resource_gpu_path}"] if self.tt.gpus else []),
                f"}} > {resource_path}",
                f"rm -f -- {resource_time_path} {resource_gpu_path}",
                # The leading newline terminates any upstream line that ended
                # without one (a progress bar's ANSI reset, for example), so
                # the marker always begins its own line.
                f"printf '\\n%s\\n' {_sh_quote(_RESOURCE_BEGIN)}",
                f"while IFS= read -r resource_line; do printf '%s%s\\n' {_sh_quote(_RESOURCE_LINE)} "
                f'"$resource_line"; done < {resource_path}',
                f"printf '%s\\n' {_sh_quote(_RESOURCE_END)}",
                "exit \"$runner_status\"",
            ]
        )

    # -- output capture ------------------------------------------------------

    def _read_stdout(self) -> None:
        stream = self._process.stdout
        last_stage: str | None = None
        markers = self.tt.stage_markers

        def emit_stage(stage: str) -> None:
            nonlocal last_stage
            if stage == last_stage:
                return
            last_stage = stage
            try:
                self.stage_callback(stage)
            except Exception:  # surface, never mask status updates
                logging.exception("Stage callback failed for task %s", self.task_id)

        for line in iter(stream.readline, ""):
            self._stdout_lines.append(line)
            if line.startswith(JOB_ID_PREFIX):
                candidate = line.split("=", 1)[1].strip()
                if candidate.isdigit():
                    # The wrapper prints this line itself, so it is evidence the
                    # request reached a compute node and started — which a queued
                    # srun stderr banner never is.  Recorded independently of the
                    # job-id race: the stderr banner may already have supplied
                    # the identity, and that must not hide the fact that the
                    # wrapper itself ran.  ``_wrapper_started_at`` is the start
                    # stamp the ``poll()`` backstop uses on a host with no
                    # scheduler query.
                    if self._slurm_job_id is None:
                        self._slurm_job_id = candidate
                        self._job_id_event.set()
                    self._wrapper_started = True
                    if self._wrapper_started_at is None:
                        self._wrapper_started_at = time.time()
                    # Persist the execution fact NOW, from the thread that saw it,
                    # rather than deferring to ``submit()``: a process death
                    # between this observation and the scheduler-owned reservation
                    # transition must not be able to erase the fact that the
                    # wrapper occupied a node.  ``submit()`` holds the wrapper at
                    # its start gate — and, for any allocation beyond the first
                    # workflow stage, at the gate that waits on the scheduler-owned
                    # reservation — so a failure here must STOP the wrapper rather
                    # than let it run an allocation whose fact was never written.
                    # It propagates to ``submit()``, which tears the job down.
                    self._notify_dispatched()
            elif line.startswith(ALLOCATION_LIVE_PREFIX):
                # The wrapper observed its own job in RUNNING state on the
                # compute node.  This — not job identity — is what starts
                # allocation accounting, and it is the signal the wrapper waits
                # on before it releases the scientific command.
                live = line.split("=", 1)[1].strip()
                if live.isdigit():
                    self._allocation_started_at = time.time()
                    self._notify_allocation_live()
                    if markers and self.stage_callback:
                        # The allocation is now genuinely running, before the
                        # scientific tool has printed its first marker.  Emit the
                        # first declared stage as a liveness signal so the Task
                        # reads as running from the moment it holds resources.
                        emit_stage(next(iter(markers)))
            if markers and self.stage_callback:
                stage = extract_stage_from_log_line(line, markers)
                if stage:
                    emit_stage(stage)
        stream.close()

    def _read_stderr(self) -> None:
        stream = self._process.stderr
        try:
            for line in iter(stream.readline, ""):
                self._stderr_lines.append(line)
                match = _SLURM_JOB_ID_RE.search(line)
                if match and self._slurm_job_id is None:
                    self._slurm_job_id = match.group(1)
                    self._job_id_event.set()
        finally:
            if self._slurm_job_id is None:
                self._job_id_event.set()  # no banner seen — stop the wait
            stream.close()

    def _save_output(self) -> None:
        # Keep scheduler diagnostics in a clearly named, previewable namespace
        # instead of ambiguous ``slurm_srun-32.out`` files at the result root.
        execution_dir = os.path.join(self.output_dir, "execution")
        os.makedirs(execution_dir, exist_ok=True)
        username = _sanitize_name(self._username or "unknown-user")
        task_name = _sanitize_name(getattr(self.tt, "name", "unknown-task"))
        task_id = _sanitize_name(self.task_id)
        out_path = os.path.join(execution_dir, f"slurm-{username}-{task_name}-{task_id}.stdout.log")
        err_path = os.path.join(execution_dir, f"slurm-{username}-{task_name}-{task_id}.stderr.log")
        try:
            with open(out_path, "w") as f:
                f.writelines(line for line in self._stdout_lines if not self._is_captured_protocol_line(line))
            with open(err_path, "w") as f:
                f.writelines(self._stderr_lines)
            self._save_resource_observation(execution_dir, username, task_name, task_id)
        except OSError as exc:
            logging.warning("Could not save SLURM output for %s: %s", self._job_id, exc)

    @staticmethod
    def _is_captured_protocol_line(line: str) -> bool:
        """Whether a stdout line is captured elsewhere than the text log.

        The resource-capture envelope is stripped exactly as it always was.  The
        runner-protocol lines go with it: their payloads are already durable as
        rows, so repeating them in the log is duplication rather than
        diagnostics.  Stage markers stay — they are the runner's own narrative
        of a long allocation and the log is where a user reads it.
        """
        stripped = line.rstrip("\n")
        if stripped.startswith((_RESOURCE_BEGIN, _RESOURCE_LINE, _RESOURCE_END)):
            return True
        return stripped.startswith(_PROTOCOL_PREFIXES)

    def _ingest_runner_protocol(self) -> None:
        """Persist progress, task outcome, and observations from captured stdout.

        Idempotent by construction: the store dedupes an observation by its
        attempt identity, and progress/outcome are last-write-wins snapshots, so
        a poll that re-reads the same lines stores nothing new.  ``_task_store``
        is the CLAIMED store: unlike ``_db`` (the admin-manage database) it is
        the one that owns the task row this job is executing.

        Total, and that is load-bearing: ``poll()`` calls this from its
        ``finally``, before the allocation settlement and scratch cleanup that
        must run for the job to end.  A parse bug must therefore degrade this
        ingest to a logged no-op, never skip that cleanup.
        """
        try:
            self._ingest_runner_protocol_lines()
        except Exception:
            logging.exception("Could not ingest runner protocol for task %s", self.task_id)

    def _ingest_runner_protocol_lines(self) -> None:
        task_store = self._task_store
        if task_store is None:
            return
        progress = None
        outcome = None
        for line in self._stdout_lines:
            progress_payload = parse_progress_line(line)
            if progress_payload is not None:
                progress = progress_payload
            outcome_payload = parse_task_outcome_line(line)
            if outcome_payload is not None:
                outcome = outcome_payload
        try:
            if progress is not None or outcome is not None:
                task_store.record_task_progress(self.task_id, progress=progress, outcome=outcome)
        except Exception:  # progress reporting must not fail a completed job
            logging.exception("Could not record execution progress for task %s", self.task_id)
        try:
            task = task_store.get_task(self.task_id) or {"md5sum": self.task_id}
        except Exception:
            task = {"md5sum": self.task_id}
        try:
            observe_lines(self._stdout_lines, task=task, store=task_store)
        except Exception:
            logging.exception("Could not ingest resource observations for task %s", self.task_id)

    @property
    def _resource_capture_path(self) -> str:
        return os.path.join(self.scratch_path, f".resource-{_sanitize_name(self.task_id)}")

    def _save_resource_observation(
        self,
        execution_dir: str,
        username: str,
        task_name: str,
        task_id: str,
    ) -> None:
        allowed = {
            "schema_version",
            "source",
            "job_id",
            "allocated_cpus_per_task",
            "allocated_tasks",
            "allocated_gpus_on_node",
            "allocated_gpu_ids",
            "visible_gpu_devices",
            "exit_code",
            "elapsed_seconds",
            "user_cpu_seconds",
            "system_cpu_seconds",
            "max_rss_kib",
            "gpu_memory_peak_mib",
            "gpu_utilization_peak_percent",
            # Ephemeral scratch capacity, measured by the guard.  Reported by
            # the wrapper only when the guard completed a measurement, so a
            # missing pair means "unknown", never "zero bytes used".
            f"{_SCRATCH_GUARD_PREFIX}peak_bytes",
            f"{_SCRATCH_GUARD_PREFIX}samples",
            f"{_SCRATCH_GUARD_PREFIX}exceeded",
        }
        lines = self._resource_capture_text()
        if lines is None:
            return
        if len(lines) > 8192:
            logging.warning("Discarding oversized resource observation for SLURM job %s", self._job_id)
            return
        values = {}
        for line in lines.splitlines():
            key, separator, value = line.partition("=")
            if not separator or key not in allowed or key in values or len(value) > 512:
                logging.warning("Discarding invalid resource observation for SLURM job %s", self._job_id)
                return
            values[key] = value
        required = {
            "schema_version",
            "source",
            "job_id",
            "allocated_cpus_per_task",
            "allocated_tasks",
            "exit_code",
        }
        if (
            not required.issubset(values)
            or values["schema_version"] != "1"
            or values["source"] != "allocation_wrapper"
        ):
            return
        numeric_types = {
            "schema_version": int,
            "allocated_cpus_per_task": int,
            "allocated_tasks": int,
            "exit_code": int,
            "elapsed_seconds": float,
            "user_cpu_seconds": float,
            "system_cpu_seconds": float,
            "max_rss_kib": int,
            "gpu_memory_peak_mib": int,
            "gpu_utilization_peak_percent": int,
            f"{_SCRATCH_GUARD_PREFIX}peak_bytes": int,
            f"{_SCRATCH_GUARD_PREFIX}samples": int,
            f"{_SCRATCH_GUARD_PREFIX}exceeded": int,
        }
        payload: dict[str, Any] = {}
        try:
            for key, value in values.items():
                payload[key] = numeric_types[key](value) if key in numeric_types and value else value
        except ValueError:
            logging.warning("Discarding non-numeric resource observation for SLURM job %s", self._job_id)
            return
        destination = os.path.join(
            execution_dir,
            f"slurm-{username}-{task_name}-{task_id}.resource.json",
        )
        with open(destination, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=True, indent=2, sort_keys=True)
            handle.write("\n")

    def _resource_capture_text(self) -> str | None:
        try:
            with open(self._resource_capture_path, encoding="utf-8") as handle:
                return handle.read(8193)
        except OSError:
            pass
        stripped = [line.rstrip("\r\n") for line in self._stdout_lines]
        try:
            end = len(stripped) - 1 - stripped[::-1].index(_RESOURCE_END)
            begin = end - 1 - stripped[:end][::-1].index(_RESOURCE_BEGIN)
        except ValueError:
            return None
        block = stripped[begin + 1 : end]
        if not block or any(not line.startswith(_RESOURCE_LINE) for line in block):
            return None
        return "\n".join(line.removeprefix(_RESOURCE_LINE) for line in block) + "\n"

    def _has_result_artifact(self) -> bool:
        """Return true when the task produced a real, non-empty result file.

        SLURM capture logs and completion sentinels are operational files.  They
        cannot by themselves prove that a scientific tool succeeded—some tools
        catch inference errors and still exit zero.  The allocation wrapper lives
        outside ``output_dir`` in ``allocation_dir``, so it is not scanned here.
        """
        for root, _dirs, files in os.walk(self.output_dir):
            for filename in files:
                if filename == "task_finished":
                    continue
                if filename.startswith("_slurm_wrapper_"):
                    # The wrapper lives outside output_dir now; a stale copy
                    # left by an older revision or an interrupted cleanup is
                    # still not a scientific result.
                    continue
                if self._is_execution_log(os.path.join(root, filename)):
                    continue
                path = os.path.join(root, filename)
                try:
                    if not os.path.islink(path) and os.path.isfile(path) and os.path.getsize(path) > 0:
                        return True
                except OSError:
                    continue
        return False

    def _is_execution_log(self, path: str) -> bool:
        relative = os.path.relpath(path, self.output_dir).replace(os.sep, "/")
        filename = os.path.basename(relative)
        return (
            relative.startswith("execution/slurm-")
            and filename.startswith("slurm-")
            and filename.endswith((".stdout.log", ".stderr.log", ".resource.json"))
        )

    def _maybe_stage_callback(self, state: JobState) -> None:
        if state == JobState.COMPLETED and self.stage_callback and self.tt.stage_markers:
            stages = list(self.tt.stage_markers.items())
            if stages:
                self.stage_callback(stages[-1][0])

    def _remove_wrapper_script(self) -> None:
        """Delete the internal wrapper script so internal paths never leak
        into the user download archive, and drop the now-empty host-only
        directory: nothing in the results tree owns it, so leaving it behind
        would accumulate one directory per task.

        Called *before* ``_save_output`` so the archive cannot carry a file the
        task container could have rewritten while bash was still reading it.

        The host-only directory is dropped only once it is empty.  A surviving
        ``allocation.receipt`` therefore keeps the directory alive on purpose: it
        is the one durable record of an allocation whose worker died before it
        adopted the claim, and restart reconciliation must be able to find it.
        """
        path = self._wrapper_script_path
        if path and os.path.exists(path):
            try:
                os.unlink(path)
            except OSError:
                pass
        if path and os.path.dirname(path) == self.allocation_dir:
            try:
                os.rmdir(self.allocation_dir)
            except OSError:
                pass


def parse_allocation_receipt(text: str) -> dict[str, Any] | None:
    """Parse the exact byte format the wrapper writes into an allocation receipt.

    The one reader of the wrapper's receipt schema, shared by the worker that is
    running the allocation and by restart reconciliation, which walks the
    host-only namespace after a crash.  A receipt that is truncated, carries an
    unknown schema, names a non-numeric job id, or reports a nonsensical shape
    returns ``None`` — it is treated as absent rather than coerced into a
    plausible allocation.  The values are parsed, never interpreted:
    corroborating the job id against the scheduler belongs to the caller that has
    the scheduler.
    """
    fields: dict[str, str] = {}
    for line in text.splitlines():
        key, separator, value = line.partition("=")
        if not separator or key in fields:
            continue
        fields[key] = value.strip()
    job_id = fields.get("slurm_job_id", "")
    if fields.get("schema_version") != "1" or not job_id.isdigit():
        return None
    try:
        observed_at = float(fields.get("observed_at", ""))
        cpus = int(fields.get("cpus", "0"))
        gpus = int(fields.get("gpus", "0"))
    except ValueError:
        return None
    if observed_at <= 0 or cpus < 0 or gpus < 0:
        return None
    return {
        "slurm_job_id": job_id,
        "observed_at": observed_at,
        "cpus": cpus,
        "gpus": gpus,
    }


def allocation_dir_for(output_dir: str) -> str:
    """The host-only allocation directory for the Task rooted at *output_dir*.

    Derived from the result path rather than stored, because restart
    reconciliation has only a Task row: the layout and the runner must agree on
    one spelling, and this is it.
    """
    return f"{os.path.normpath(output_dir)}{ALLOCATION_DIR_SUFFIX}"


def surviving_allocation_receipts(results_root: str) -> list[dict[str, Any]]:
    """Every compute-node receipt still on disk under *results_root*.

    Restart reconciliation's view of the host-only allocation namespace.  The
    results tree is laid out ``<results_root>/users/<storage key>/tasks/<task
    id>`` with the allocation directory as the ``<task id>.allocation`` sibling,
    so a bounded three-level walk finds every Task that ever ran here.

    A receipt is returned only when it parses: the entry stays on disk so an
    operator can inspect an anomalous one, and a receipt this pass cannot adopt
    is never deleted.  The caller corroborates each claim against the scheduler
    before anything is recorded.
    """
    base = os.path.abspath(results_root)
    users_root = os.path.join(base, "users")
    found: list[dict[str, Any]] = []
    if not os.path.isdir(users_root):
        return found
    for user_entry in sorted(os.scandir(users_root), key=lambda entry: entry.name):
        if not user_entry.is_dir(follow_symlinks=False):
            continue
        tasks_root = os.path.join(user_entry.path, "tasks")
        if not os.path.isdir(tasks_root):
            continue
        for allocation_entry in sorted(os.scandir(tasks_root), key=lambda entry: entry.name):
            # The allocation directory is a sibling of the Task's result
            # directory and is named after it, so the Task id is the name with
            # the suffix removed.  Anything else under ``tasks`` is a result
            # directory and is skipped.
            if not allocation_entry.is_dir(follow_symlinks=False):
                continue
            task_id = allocation_entry.name
            if not task_id.endswith(ALLOCATION_DIR_SUFFIX):
                continue
            task_id = task_id[: -len(ALLOCATION_DIR_SUFFIX)]
            if not task_id:
                continue
            receipt_path = os.path.join(allocation_entry.path, ALLOCATION_RECEIPT_NAME)
            try:
                with open(receipt_path, encoding="utf-8") as handle:
                    text = handle.read(4096)
            except OSError:
                continue
            receipt = parse_allocation_receipt(text)
            if receipt is None:
                continue
            receipt["task_id"] = task_id
            receipt["receipt_path"] = receipt_path
            found.append(receipt)
    return found


def _sanitize_name(s: str) -> str:
    """SLURM job names: alphanumeric, underscore, hyphen only."""
    return "".join(c if c.isalnum() or c in "_-" else "_" for c in (s or "unknown")) or "unknown"


def _sh_quote(s: str) -> str:
    return "'" + s.replace("'", "'\"'\"'") + "'"
