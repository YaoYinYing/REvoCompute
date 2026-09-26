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
from typing import Any

from revocompute.job import ExecutionBuilder, ExecutionPlan, Job, JobState
from revocompute.job._stages import extract_stage_from_log_line
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
_RESOURCE_BEGIN = "REVODESIGN_RESOURCE_BEGIN"
_RESOURCE_LINE = "REVODESIGN_RESOURCE:"
_RESOURCE_END = "REVODESIGN_RESOURCE_END"
#: Runner-protocol bookkeeping lines.  They are captured durably (observations
#: in the database, progress/outcome on the task row), so the human-readable
#: capture log keeps only the runner's own diagnostics instead of repeating
#: every structured line.
_PROTOCOL_PREFIXES = (PROGRESS_PREFIX, OBSERVATION_PREFIX, TASK_OUTCOME_PREFIX)


class SlurmJob(Job):
    """A compute job submitted via SLURM + Apptainer.

    ``submit()`` launches ``srun`` via ``subprocess.Popen`` and returns the
    real SLURM job id only when it is captured from the allocation wrapper's
    first stdout line or an ``srun`` stderr banner. ``poll()`` waits for the
    process to exit and returns ``COMPLETED`` or ``FAILED`` based on the exit
    code.
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
        allocation_started_callback: Any = None,
        allocation_finished_callback: Any = None,
        task_store: Any = None,
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
        self._allocation_tracking_started = False
        self._allocation_finished_notified = False
        self._allocation_started_callback = allocation_started_callback
        self._allocation_finished_callback = allocation_finished_callback
        self._job_id_event = threading.Event()
        self._resolved_resource_policy = resource_policy
        if scratch_backend not in {"disk", "ram"}:
            raise ValueError("scratch_backend must be 'disk' or 'ram'")
        self.scratch_backend = scratch_backend
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
        self._allocation_started = time.monotonic()
        self._allocation_started_at = time.time()
        try:
            if self._allocation_started_callback is not None:
                self._allocation_started_callback(
                    self._slurm_job_id, self._allocation_started_at
                )
                self._allocation_tracking_started = True
                self._approve_allocation()
        except Exception:
            self.cancel()
            self._remove_wrapper_script()
            raise
        emit_event("slurm.allocation.granted", **self._event_fields())

        logging.info(
            "SLURM job %s (srun pid %s) started for task %s",
            self._job_id,
            self._process.pid,
            self.task_id,
        )
        return self._job_id

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
        with open(self._allocation_approval_path, "x", encoding="utf-8"):
            pass

    @property
    def _allocation_approval_path(self) -> str:
        return os.path.join(self.output_dir, f".allocation-approved-{self.task_id[:8]}")

    def _remove_allocation_approval(self) -> None:
        try:
            os.unlink(self._allocation_approval_path)
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
        """Create private task-backed scratch before the allocation starts."""
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
        return f"{os.path.normpath(self.output_dir)}.allocation"

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
            # The allocation carries the authoritative job id; publish it on
            # stdout first so the runner never depends on srun's stderr
            # banner (which SLURM 19.05 does not always print in time).
            'echo "REVODESIGN_JOB_ID=${SLURM_JOB_ID}"',
        ]
        if self._allocation_started_callback is not None:
            lines.extend(
                [
                    f"approval={_sh_quote(self._allocation_approval_path)}",
                    'for _ in {1..300}; do test -f "$approval" && break; sleep 0.1; done',
                    'test -f "$approval"',
                    'rm -f -- "$approval"',
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
                "cleanup_resource_capture() {",
                '  if [[ -n "${gpu_monitor_pid:-}" ]]; then',
                '    kill "${gpu_monitor_pid}" 2>/dev/null || true',
                '    wait "${gpu_monitor_pid}" 2>/dev/null || true',
                "  fi",
                '  rm -f -- "${resource_capture_dir}/resource" "${resource_capture_dir}/time" '
                '"${resource_capture_dir}/gpu"',
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
                "if [[ -x /usr/bin/time ]]; then",
                "  if /usr/bin/time -f 'elapsed_seconds=%e\\nuser_cpu_seconds=%U\\n"
                f"system_cpu_seconds=%S\\nmax_rss_kib=%M' -o {resource_time_path} {cmd}; then",
                "    runner_status=0",
                "  else",
                "    runner_status=$?",
                "  fi",
                "else",
                f"  if {cmd}; then runner_status=0; else runner_status=$?; fi",
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
            if line.startswith("REVODESIGN_JOB_ID=") and self._slurm_job_id is None:
                candidate = line.split("=", 1)[1].strip()
                if candidate.isdigit():
                    self._slurm_job_id = candidate
                    self._job_id_event.set()
                    if markers and self.stage_callback:
                        # The allocation is live before the scientific tool
                        # prints its first marker.  Emit the first declared
                        # stage as a liveness signal so queued tasks become
                        # running as soon as the wrapper starts.
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


def _sanitize_name(s: str) -> str:
    """SLURM job names: alphanumeric, underscore, hyphen only."""
    return "".join(c if c.isalnum() or c in "_-" else "_" for c in (s or "unknown")) or "unknown"


def _sh_quote(s: str) -> str:
    return "'" + s.replace("'", "'\"'\"'") + "'"
