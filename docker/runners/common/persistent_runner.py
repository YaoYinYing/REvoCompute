# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Persistent multi-work-item Runner lifecycle, shared by participating families.

A task may contain many independent work items, a worker may die and restart,
and one item's failure must not fail the rest. This module owns that contract so
each family only supplies the science:

    initialize_runtime()               # load model/weights once per task
    run_item(item, plan, work_dir)     # one work item, into a private directory
    finalize()                         # release the runtime

The lifecycle this drives:

.. code-block:: text

    initialize_runtime -> commit -> [initialize_runtime -> commit]* -> finalize

``execute_task`` performs the orchestration: it resumes from the durable
manifest, runs the ``ExecutionQueue``, commits each item atomically, reports
resource observations, follows the server's fallback plan order within a bounded
budget, restarts an unhealthy CUDA context, and writes the task outcome. A
family's entrypoint is then a thin adapter::

    config = json.loads(args.work_items)
    execute_task(config, MyPlugin(), output_dir=args.output_dir)

Measurement happens here, where the GPU allocations live: ``run_item`` returns
the peak memory the runtime that owns the device reports, and the queue
publishes a normalized observation on stdout. The server consumes that schema
and owns the estimator — so this module is **standard library only** and must
stay that way. An image that ships without NumPy or a resource model still runs
every work item; only the guidance it receives gets less specific.

Durability rules:

* ``work_items.json`` is the authoritative per-item state and is written
  atomically beside the results, so a restarted worker resumes it directly.
* an item's artifacts are written to ``.tmp/<id>/`` and renamed into ``<id>/``
  only after validation, so a final directory always means "this item completed
  and its artifacts passed validation".
* item order in the file is the *original input order*; ``ExecutionQueue`` may
  choose a different execution order without changing what the user sees.
"""

from __future__ import annotations

import json
import os
import shutil
import time
import traceback

SCHEMA_VERSION = 1
MANIFEST_NAME = "work_items.json"
TMP_DIR_NAME = ".tmp"

#: Work-item states (``TODO.md`` §3).
PENDING = "PENDING"
RUNNING = "RUNNING"
SUCCEEDED = "SUCCEEDED"
FAILED_INPUT = "FAILED_INPUT"
FAILED_RESOURCE = "FAILED_RESOURCE"
FAILED_RUNTIME = "FAILED_RUNTIME"
CANCELLED = "CANCELLED"

#: Task outcomes derived from item states.
SUCCESS = "SUCCESS"
PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
FAILED = "FAILED"
CANCELLED_PARTIAL = "CANCELLED_PARTIAL"

#: Observation outcomes (wire vocabulary, shared with the server's schema).
OUTCOME_SUCCESS = "success"
OUTCOME_OOM = "oom"
OUTCOME_ERROR = "error"

#: Rollout stages, as declared by the runner's own manifest.
STAGES = ("observe", "recover", "avoid")

_FAILED_STATES = (FAILED_INPUT, FAILED_RESOURCE, FAILED_RUNTIME)


class WorkItemError(Exception):
    """An item failure classified so the task outcome can be derived."""

    def __init__(self, state: str, message: str, *, error_class: str = "") -> None:
        super().__init__(message)
        if state not in _FAILED_STATES:
            raise ValueError(f"Unclassified work-item failure state: {state!r}")
        self.state = state
        #: The runner's own classification (``CUDA_OOM``, ...), carried into the
        #: observation so a resource row names the failure the plugin reported
        #: rather than the exception wrapper this lifecycle raised.
        self.error_class = error_class


class FatalTaskError(Exception):
    """A failure of the task as a whole; no work item can run."""


# ---------------------------------------------------------------------------
# Work items and durable state
# ---------------------------------------------------------------------------


def normalize_items(raw_items: list[dict]) -> list[dict]:
    """Validate work items and return them in original input order.

    Identifiers are preserved as metadata and normalized into a safe path
    component; duplicates are rejected after normalization, so two distinct
    identifiers can never collide on one output directory.
    """
    items: list[dict] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_items):
        identifier = str(raw.get("id") or "").strip()
        if not identifier:
            raise FatalTaskError("Task contains a work item without an identifier")
        name = safe_item_name(identifier)
        if name in seen:
            raise FatalTaskError(f"Task contains duplicate work item identifiers after normalization: {identifier!r}")
        seen.add(name)
        items.append({"id": identifier, "name": name, "index": index, "payload": dict(raw)})
    if not items:
        raise FatalTaskError("Task contains no work items")
    return items


def safe_item_name(identifier: str) -> str:
    """Normalize an identifier into one safe path component."""
    cleaned = "".join(character if character.isalnum() or character in "._-" else "_" for character in identifier)
    return (cleaned.strip("._-") or "item")[:96]


def work_items_path(output_dir: str) -> str:
    return os.path.join(output_dir, MANIFEST_NAME)


def read_work_items(output_dir: str) -> dict | None:
    try:
        with open(work_items_path(output_dir), encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) and isinstance(payload.get("items"), list) else None


def write_work_items(output_dir: str, manifest: dict) -> None:
    """Atomically publish item state; the file is authoritative, not memory."""
    os.makedirs(output_dir, exist_ok=True)
    destination = work_items_path(output_dir)
    temporary = destination + f".tmp-{os.getpid()}"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=True, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, destination)


def new_manifest(task_id: str, runner: str, items: list[dict]) -> dict:
    return {
        "version": SCHEMA_VERSION,
        "task_id": task_id,
        "runner": runner,
        "created_at": time.time(),
        "outcome": None,
        "items": [
            {
                "id": item["id"],
                "name": item["name"],
                "order": item["index"],
                "status": PENDING,
                "attempts": 0,
                "output_path": f"{item['name']}/",
                "started_at": None,
                "finished_at": None,
                "error": None,
                "resource_events": [],
            }
            for item in items
        ],
    }


def count(manifest: dict, states) -> int:
    if isinstance(states, str):
        states = (states,)
    return sum(1 for entry in manifest["items"] if entry["status"] in states)


def derive_outcome(manifest: dict) -> str:
    """Derive the task outcome from item states (``TODO.md`` §3)."""
    succeeded = count(manifest, SUCCEEDED)
    failed = count(manifest, _FAILED_STATES)
    unfinished = count(manifest, (PENDING, RUNNING))
    cancelled = count(manifest, CANCELLED)
    if cancelled or unfinished:
        return CANCELLED_PARTIAL
    if failed == 0:
        return SUCCESS
    return PARTIAL_SUCCESS if succeeded else FAILED


def format_progress(manifest: dict, current: str | None = None) -> str:
    """Structured progress line, so stdout is not the only progress channel."""
    current_entry = next((entry for entry in manifest["items"] if entry["status"] == RUNNING), None)
    payload = {
        "total_items": len(manifest["items"]),
        "completed_items": count(manifest, SUCCEEDED),
        "failed_items": count(manifest, _FAILED_STATES),
        "pending_items": count(manifest, (PENDING, RUNNING)),
        "current_item": (current_entry or {}).get("id") if current_entry else current,
        "current_attempt": (current_entry or {}).get("attempts", 0) if current_entry else 0,
    }
    return "REVODESIGN_PROGRESS:" + json.dumps(payload, sort_keys=True)


# ---------------------------------------------------------------------------
# Execution queue
# ---------------------------------------------------------------------------


class ExecutionQueue:
    """Stable execution order plus already-learned resource constraints.

    The first implementation is deliberately not a batcher. Persistent *serial*
    execution — load the runtime once, process items continuously — is the
    optimization target. For sequence workloads the queue orders by decreasing
    length so the longest item runs first: a long-tail OOM surfaces while the
    queue still has room to adapt, instead of failing the last item after hours
    of work. Items of comparable length stay adjacent so the runtime sees
    similar shapes in sequence.

    ``constraints`` carries resource limits already learned for this
    runner/device profile; the queue only *orders* around them, it never drops a
    work item, and the original input order stays authoritative in the manifest.
    """

    #: Membership in a length bucket is a ratio of the previous boundary.
    DEFAULT_RATIOS = (1.5, 2.0)

    def __init__(self, *, ratios: tuple[float, ...] | None = None, constraints: dict | None = None) -> None:
        self.ratios = tuple(ratios or self.DEFAULT_RATIOS)
        self.constraints = dict(constraints or {})

    @classmethod
    def from_policy(cls, policy: dict | None) -> ExecutionQueue:
        policy = policy or {}
        return cls(ratios=policy.get("ratios"), constraints=dict(policy.get("constraints") or {}))

    def order(self, items: list[dict]) -> list[int]:
        """Return execution indices without mutating input order."""

        def length_of(item: dict) -> int:
            return int(item["payload"].get("length") or 0)

        def bucket_of(length: int) -> int:
            level = 0
            boundary = 1
            for ratio in self.ratios:
                boundary *= ratio
                if length <= boundary:
                    break
                level += 1
            return level

        # Longest bucket first, longest item first within a bucket; the original
        # index is the final tiebreak so the order is fully deterministic.
        return sorted(
            range(len(items)),
            key=lambda index: (-bucket_of(max(1, length_of(items[index]))), -length_of(items[index]), index),
        )


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------


class Plan:
    """One attempt's execution configuration.

    Label ``""`` is the default, upstream-parameter path. A non-empty label
    names one of the runner's own declared fallbacks, whose ``adjustments`` are
    resource-equivalent settings only — validated on the server, which rejects
    any adjustment that would change the requested computation.
    """

    __slots__ = ("label", "adjustments", "allowed", "reason")

    def __init__(self, label: str = "", adjustments: dict | None = None, allowed: bool = True, reason: str = "") -> None:
        self.label = label
        self.adjustments = dict(adjustments or {})
        self.allowed = allowed
        self.reason = reason

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        state = "allowed" if self.allowed else "rejected"
        return f"Plan({self.label or 'default'!r}, {state}, {self.reason!r})"


class PlanSequence:
    """Walks the server's plan order; never invents an adjustment.

    The server owns the learned model and sends ``resource_guidance``: the
    attempt order, plans already known to fail for this profile, and the stage.
    This class only enforces that sequence within a finite budget:

    * attempt 0 is always the default path, and in ``observe`` it is also the
      only path — a successful execution is never modified;
    * a later attempt follows the declared order, skipping known-failing plans;
    * when every declared plan is exhausted the item is ``FAILED_RESOURCE``.

    ``plans`` maps a label to its declared adjustments. An order entry the
    runner does not declare is skipped rather than guessed, so a malformed
    guidance block degrades to bounded recovery instead of undefined behaviour.
    """

    def __init__(self, adaptation: dict | None, guidance: dict | None, execution: dict) -> None:
        adaptation = adaptation or {}
        guidance = guidance or {}
        # The stage is declared once, by the owning manifest's
        # ``resource_adaptation``; the server's guidance carries only what it
        # has learned, so the rollout stage has a single owner.
        self.stage = str(adaptation.get("stage") or "observe")
        if self.stage not in STAGES:
            self.stage = "observe"
        self.plans: dict[str, dict] = {}
        for entry in adaptation.get("fallback_plans") or []:
            if isinstance(entry, dict) and entry.get("label"):
                self.plans[str(entry["label"])] = dict(entry.get("adjustments") or {})
        order = [str(label) for label in guidance.get("plan_order") or []]
        self.order = [label for label in order if label == "" or label in self.plans] or [""]
        self.known_failing = {str(label) for label in guidance.get("known_failing_plans") or []}
        self.avoid_at_or_above = guidance.get("avoid_scale_at_or_above")
        self.max_attempts = int(execution.get("max_item_attempts") or (len(self.order) + 1))
        self.skipped: list[str] = []

    def plan_for(self, attempt: int, failed: list[str], *, scale: int = 0) -> Plan:
        """Choose the plan for a zero-based attempt number."""
        if attempt <= 0:
            if self._avoid_default(scale):
                first = self._first_allowed(failed)
                if first is not None:
                    self.skipped.append("")
                    return first
            return Plan("", {}, True, "default execution path")
        if self.stage == "observe":
            return Plan("", {}, False, "observation-only rollout; no adaptation attempted")
        if attempt >= self.max_attempts:
            return Plan("", {}, False, "retry budget exhausted; item is FAILED_RESOURCE")
        candidate = self._first_allowed(failed)
        if candidate is None:
            return Plan("", {}, False, "all runner-declared fallbacks exhausted; item is FAILED_RESOURCE")
        return candidate

    def _first_allowed(self, failed: list[str]) -> Plan | None:
        for label in self.order:
            if label == "" or label in failed or label in self.known_failing:
                continue
            return Plan(label, self.plans[label], True, "bounded OOM recovery")
        return None

    def _avoid_default(self, scale: int) -> bool:
        """Whether the server has evidence this workload is a known failure."""
        if self.stage != "avoid":
            return False
        if "" in self.known_failing:
            return True
        return bool(self.avoid_at_or_above and scale >= int(self.avoid_at_or_above))


# ---------------------------------------------------------------------------
# Atomic per-item commit
# ---------------------------------------------------------------------------


def item_tmp_dir(output_dir: str, name: str) -> str:
    return os.path.join(output_dir, TMP_DIR_NAME, name)


def item_dir(output_dir: str, name: str) -> str:
    return os.path.join(output_dir, name)


def reset_item_staging(output_dir: str, name: str) -> str:
    """Prepare a private staging directory for one attempt."""
    temporary = item_tmp_dir(output_dir, name)
    shutil.rmtree(temporary, ignore_errors=True)
    os.makedirs(temporary, exist_ok=True)
    return temporary


def commit_item(output_dir: str, name: str) -> str:
    """Atomically promote a validated item directory into its final location.

    The commit is a rename, so a reader never sees a partial directory as a
    completed result. A committed destination is never overwritten: on resume a
    successful item is skipped before execution, so reaching this state means a
    different run owns that directory and the current one must not destroy it.
    """
    temporary = item_tmp_dir(output_dir, name)
    destination = item_dir(output_dir, name)
    if not os.path.isdir(temporary):
        raise WorkItemError(FAILED_RUNTIME, f"work item {name!r} produced no staged output directory")
    if os.path.exists(destination):
        raise WorkItemError(FAILED_RUNTIME, f"work item {name!r} would overwrite a committed result")
    os.replace(temporary, destination)
    try:
        os.rmdir(os.path.dirname(temporary))
    except OSError:
        pass
    return destination


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


class PersistentTask:
    """Drives ``initialize_runtime -> process item -> commit -> finalize``."""

    def __init__(self, config: dict, plugin, *, output_dir: str) -> None:
        self.config = config
        self.plugin = plugin
        self.output_dir = output_dir
        self.runner = str(config.get("runner") or getattr(plugin, "runner", "runner"))
        self.task_id = str(config.get("task_id") or "")
        self.execution = dict(config.get("execution") or {})
        self.queue = ExecutionQueue.from_policy(config.get("execution_queue"))
        self.plans = PlanSequence(
            config.get("resource_adaptation"),
            config.get("resource_guidance"),
            self.execution,
        )
        self.runtime = None
        self.available_mb = 0
        self.runtime_restarts = 0
        self.items: list[dict] = []

    # -- lifecycle ----------------------------------------------------------

    def initialize_runtime(self) -> None:
        """Load model weights / CUDA context / indexes — once per task."""
        self.runtime = self.plugin.initialize_runtime(self.execution)
        self.available_mb = int(self.plugin.available_vram_mb(self.runtime) or 0)

    def finalize(self) -> None:
        runtime, self.runtime = self.runtime, None
        if runtime is not None:
            try:
                self.plugin.finalize(runtime)
            except Exception:  # a teardown failure must not rewrite results
                traceback.print_exc()

    def restart_runtime(self) -> None:
        """Destroy and reload the runtime after an unrecoverable CUDA error."""
        self.finalize()
        self.runtime_restarts += 1
        self.initialize_runtime()

    # -- item execution -----------------------------------------------------

    def attempt_item(self, entry: dict, item: dict, plan: Plan) -> dict | None:
        """Run, validate, and commit one item. Returns the observation on success."""
        staging = reset_item_staging(self.output_dir, entry["name"])
        baseline_mb = int(self.plugin.runtime_usage(self.runtime)[0])
        started = time.time()
        try:
            outcome, peak_allocated, peak_reserved, process_peak, error_class = self.plugin.run_item(
                self.runtime, item["payload"], plan.adjustments, staging, self.execution
            )
            if outcome != OUTCOME_SUCCESS:
                # A plugin reports a bounded failure by outcome; classify it so
                # the outcome (and the retry decision) is explicit rather than
                # inferred from an exception type.
                state = FAILED_RESOURCE if outcome == OUTCOME_OOM else FAILED_RUNTIME
                raise WorkItemError(state, error_class or f"work item {outcome}", error_class=error_class)
            self.plugin.validate_item(staging, item["payload"], plan.adjustments)
            commit_item(self.output_dir, entry["name"])
        except Exception:
            shutil.rmtree(item_tmp_dir(self.output_dir, entry["name"]), ignore_errors=True)
            raise
        finished = time.time()
        entry["status"] = SUCCEEDED
        entry["started_at"] = started
        entry["finished_at"] = finished
        entry["error"] = None
        return self._observation(
            entry,
            item,
            plan,
            outcome=OUTCOME_SUCCESS,
            baseline_mb=baseline_mb,
            peak_allocated_mb=peak_allocated,
            peak_reserved_mb=peak_reserved,
            peak_process_mb=process_peak,
            error_class=error_class or "",
            runtime_seconds=round(finished - started, 3),
        )

    def _observation(self, entry: dict, item: dict, plan: Plan, **fields) -> dict:
        """Build, record, and publish one normalized resource observation."""
        peak, current, reserved = self.plugin.runtime_usage(self.runtime)
        observation = {
            "schema_version": SCHEMA_VERSION,
            "task_id": self.task_id,
            "work_item": entry["id"],
            "attempt": entry["attempts"],
            "runner": self.runner,
            "runner_version": str(getattr(self.plugin, "runner_version", "") or ""),
            "model_revision": str(self.plugin.model_revision),
            "runtime_fingerprint": str(self.plugin.runtime_fingerprint),
            "device": dict(self.plugin.device_profile(self.runtime)),
            "features": self._features(item["payload"], plan.adjustments),
            "baseline_mb": int(fields.pop("baseline_mb", peak) or peak),
            "peak_allocated_mb": int(fields.pop("peak_allocated_mb", current)),
            "peak_reserved_mb": int(fields.pop("peak_reserved_mb", reserved)),
            "peak_process_mb": int(fields.pop("peak_process_mb", peak)),
            "available_mb": int(self.plugin.available_vram_mb(self.runtime) or 0),
            "outcome": fields.pop("outcome"),
            "error_class": str(fields.pop("error_class", "")),
            "runtime_seconds": float(fields.pop("runtime_seconds", 0.0)),
            "plan_label": str(plan.label or ""),
            "created_at": time.time(),
        }
        # A successful run whose peak exceeds the device's free memory means
        # another process held memory during it; the row stays diagnostic and
        # the server must not learn it as increased workload demand.
        observation["quality"] = (
            "interference"
            if observation["outcome"] == OUTCOME_SUCCESS
            and observation["available_mb"]
            and observation["peak_process_mb"] > observation["available_mb"] * 1.05
            else "valid"
        )
        entry.setdefault("resource_events", []).append(observation)
        print("REVODESIGN_OBSERVATION:" + json.dumps(observation, sort_keys=True), flush=True)
        return observation

    @staticmethod
    def _scale(payload: dict) -> int:
        """Workload size proxy, matching the server estimator's feature scale."""
        return (
            int(payload.get("length") or 0)
            * int(payload.get("sequence_count") or 1)
            * int(payload.get("sample_count") or 1)
        )

    def _features(self, payload: dict, adjustments: dict) -> dict:
        return {
            "runner": self.runner,
            "model_revision": str(self.plugin.model_revision),
            "runtime_fingerprint": str(self.plugin.runtime_fingerprint),
            "sequence_length": int(payload.get("length") or 1),
            "sequence_count": int(payload.get("sequence_count") or 1),
            "batch_size": int(adjustments.get("batch_size") or self.execution.get("batch_size", 1)),
            "sample_count": int(payload.get("sample_count") or 1),
            "parameters": {},
        }

    # -- bounded recovery ---------------------------------------------------

    def process_entry(self, manifest: dict, index: int) -> None:
        entry = manifest["items"][index]
        item = self.items[index]
        if entry["status"] == SUCCEEDED:
            return  # resume: never recompute committed work
        failed: list[str] = []
        while entry["attempts"] < self.plans.max_attempts:
            plan = self.plans.plan_for(entry["attempts"], failed, scale=self._scale(item["payload"]))
            entry["attempts"] += 1
            entry["status"] = RUNNING
            write_work_items(self.output_dir, manifest)
            if not plan.allowed:
                self._fail(entry, FAILED_RESOURCE, plan.reason)
                write_work_items(self.output_dir, manifest)
                return
            try:
                self.attempt_item(entry, item, plan)
            except WorkItemError as error:
                self._observe_failure(entry, item, plan, error)
                if error.state == FAILED_RESOURCE and entry["attempts"] < self.plans.max_attempts:
                    failed.append(plan.label)
                    continue  # bounded retry with the next declared fallback
                self._fail(entry, error.state, str(error))
                write_work_items(self.output_dir, manifest)
                return
            except Exception as error:  # a surprising error must not take the task down
                traceback.print_exc()
                self._observe_failure(entry, item, plan, error)
                if _looks_like_cuda_fault(error) and self.runtime_restarts < int(
                    self.execution.get("max_runtime_restarts", 1)
                ):
                    # Last-resort recovery: the CUDA context is unhealthy, so
                    # rebuild it and let the remaining items resume.
                    self.restart_runtime()
                    self._fail(entry, FAILED_RUNTIME, f"{type(error).__name__}: {error}")
                    write_work_items(self.output_dir, manifest)
                    return
                state = FAILED_RUNTIME if _looks_like_cuda_fault(error) else FAILED_RESOURCE
                if state == FAILED_RESOURCE and entry["attempts"] < self.plans.max_attempts:
                    failed.append(plan.label)
                    continue
                self._fail(entry, state, f"{type(error).__name__}: {error}")
                write_work_items(self.output_dir, manifest)
                return
            write_work_items(self.output_dir, manifest)
            return
        self._fail(entry, FAILED_RESOURCE, "retry budget exhausted")
        write_work_items(self.output_dir, manifest)

    def _observe_failure(self, entry: dict, item: dict, plan: Plan, error: Exception) -> None:
        state = getattr(error, "state", FAILED_RUNTIME)
        self._observation(
            entry,
            item,
            plan,
            outcome=OUTCOME_OOM if state == FAILED_RESOURCE else OUTCOME_ERROR,
            error_class=getattr(error, "error_class", "") or type(error).__name__,
        )

    @staticmethod
    def _fail(entry: dict, state: str, message: str) -> None:
        entry["status"] = state
        entry["error"] = message
        entry["finished_at"] = time.time()

    # -- task level ---------------------------------------------------------

    def run(self) -> dict:
        os.makedirs(self.output_dir, exist_ok=True)
        self.items = normalize_items(list(self.config["items"]))
        manifest = read_work_items(self.output_dir)
        if manifest is None or [entry["name"] for entry in manifest["items"]] != [item["name"] for item in self.items]:
            manifest = new_manifest(self.task_id, self.runner, self.items)
        manifest["outcome"] = None
        write_work_items(self.output_dir, manifest)

        runtime_ready = False
        try:
            for index in self.queue.order(self.items):
                if manifest["items"][index]["status"] == SUCCEEDED:
                    continue
                if not runtime_ready:
                    print("REVODESIGN_STAGE:model_loading", flush=True)
                    self.initialize_runtime()
                    runtime_ready = True
                self.process_entry(manifest, index)
                write_work_items(self.output_dir, manifest)
                print(format_progress(manifest), flush=True)
            manifest["outcome"] = derive_outcome(manifest)
            manifest["skipped_known_failure_plans"] = list(dict.fromkeys(self.plans.skipped))
            write_work_items(self.output_dir, manifest)
        finally:
            self.finalize()
        self.plugin.finalize_task(self.output_dir, manifest)
        print(f"REVODESIGN_TASK_OUTCOME:{manifest['outcome']}", flush=True)
        return manifest


def _looks_like_cuda_fault(error: Exception) -> bool:
    name = type(error).__name__.lower()
    text = str(error).lower()
    return "cuda" in name or "illegal memory access" in text


def execute_task(config: dict, plugin, *, output_dir: str) -> dict:
    """Entrypoint for a family: run the persistent lifecycle over the work items."""
    return PersistentTask(config, plugin, output_dir=output_dir).run()


def _self_check() -> None:
    """Runtime-once, resume, partial success, atomic commit, bounded fallback."""
    import tempfile

    class FakePlugin:
        runner = "fake"
        runner_version = "1"
        model_revision = "m1"
        runtime_fingerprint = "fp"

        def __init__(self) -> None:
            self.loads = 0
            self.outcomes: dict[str, str] = {}
            self.oom_once: set[str] = set()
            self.always_oom: set[str] = set()

        def initialize_runtime(self, execution):
            self.loads += 1
            return {"loaded": self.loads}

        def finalize(self, runtime):
            pass

        def runtime_usage(self, runtime):
            return (100, 100, 120)

        def available_vram_mb(self, runtime):
            return 40000

        def device_profile(self, runtime):
            return {
                "vendor": "nvidia",
                "model": "A100-PCIE-40GB",
                "compute_capability": "8.0",
                "total_vram_mb": 40960,
                "mig_profile": "",
            }

        def run_item(self, runtime, payload, adjustments, work_dir, execution):
            if payload["id"] in self.always_oom:
                return OUTCOME_OOM, 0, 0, 0, "CUDA_OOM"
            if self.outcomes.get(payload["id"]) == "oom_default" and not adjustments:
                return OUTCOME_OOM, 0, 0, 0, "CUDA_OOM"
            if payload["id"] in self.oom_once:
                self.oom_once.discard(payload["id"])
                return OUTCOME_OOM, 0, 0, 0, "CUDA_OOM"
            if self.outcomes.get(payload["id"]) == "hard":
                raise WorkItemError(FAILED_INPUT, "bad input record")
            with open(os.path.join(work_dir, "result.txt"), "w", encoding="utf-8") as handle:
                handle.write(str(adjustments.get("batch_size", "1")))
            return OUTCOME_SUCCESS, 1000, 1200, 900, ""

        def validate_item(self, work_dir, payload, adjustments):
            assert os.path.isfile(os.path.join(work_dir, "result.txt"))

        def finalize_task(self, output_dir, manifest):
            pass

    items = [{"id": f"p{i}", "length": length} for i, length in enumerate((100, 3000, 250))]
    plugin = FakePlugin()
    plugin.oom_once.add("p1")
    config = {
        "task_id": "t1",
        "runner": "fake",
        "items": items,
        "execution": {"max_item_attempts": 2},
        "resource_adaptation": {
            "stage": "recover",
            "fallback_plans": [{"label": "split", "adjustments": {"batch_size": 1}}],
        },
        "resource_guidance": {"stage": "recover", "plan_order": ["", "split"]},
    }
    with tempfile.TemporaryDirectory() as root:
        manifest = PersistentTask(config, plugin, output_dir=root).run()
        assert plugin.loads == 1, "runtime must load once per task"
        assert manifest["outcome"] == SUCCESS, manifest["outcome"]
        # The manifest keeps original input order though the queue ran 3000 first.
        assert [entry["id"] for entry in manifest["items"]] == ["p0", "p1", "p2"]
        assert manifest["items"][1]["attempts"] == 2
        assert os.path.isfile(os.path.join(root, "p1", "result.txt"))
        assert not os.path.exists(os.path.join(root, TMP_DIR_NAME))

        # Resume: a second run must not reload the runtime or recompute anything.
        plugin.loads = 0
        resumed = PersistentTask(config, plugin, output_dir=root).run()
        assert plugin.loads == 0, "a fully committed task must not reload the runtime"
        assert resumed["outcome"] == SUCCESS

    plugin2 = FakePlugin()
    plugin2.outcomes["p0"] = "hard"
    with tempfile.TemporaryDirectory() as root2:
        result = PersistentTask(config, plugin2, output_dir=root2).run()
        assert result["outcome"] == PARTIAL_SUCCESS, result["outcome"]
        assert result["items"][0]["status"] == FAILED_INPUT, result["items"][0]["status"]
        assert result["items"][1]["status"] == SUCCEEDED
        assert os.path.isfile(os.path.join(root2, "p1", "result.txt")), "remaining items continue"

    # Atomic commit: an incomplete staging tree is never a published result.
    with tempfile.TemporaryDirectory() as root3:
        plugin3 = FakePlugin()
        plugin3.run_item = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("killed"))
        result3 = PersistentTask(config, plugin3, output_dir=root3).run()
        assert result3["outcome"] == FAILED, result3["outcome"]
        assert not os.path.exists(os.path.join(root3, "p0")), "a partial item must not be published"

    # Bounded: an item that OOMs under every fallback becomes FAILED_RESOURCE.
    plugin4 = FakePlugin()
    plugin4.always_oom = {f"p{i}" for i in range(3)}
    with tempfile.TemporaryDirectory() as root4:
        result4 = PersistentTask(config, plugin4, output_dir=root4).run()
        assert result4["outcome"] == FAILED, result4["outcome"]
        assert {entry["status"] for entry in result4["items"]} == {FAILED_RESOURCE}
        assert all(entry["attempts"] == 2 for entry in result4["items"]), "retry budget must be finite"

    # observe: a successful default run is never modified, and OOM is not retried
    # into a fallback the operator has not enabled.
    observe_config = {**config, "resource_adaptation": {"stage": "observe"}, "resource_guidance": {"stage": "observe"}}
    plugin5 = FakePlugin()
    with tempfile.TemporaryDirectory() as root5:
        observe_manifest = PersistentTask(observe_config, plugin5, output_dir=root5).run()
        assert observe_manifest["outcome"] == SUCCESS
        assert all(entry["attempts"] == 1 for entry in observe_manifest["items"])

    # avoid: a known-failing default is skipped without repeating it.
    avoid_config = {
        **config,
        "resource_adaptation": {**config["resource_adaptation"], "stage": "avoid"},
        "resource_guidance": {
            "plan_order": ["", "split"],
            "known_failing_plans": [""],
            "avoid_scale_at_or_above": 100,
        },
    }
    plugin6 = FakePlugin()
    plugin6.outcomes["p1"] = "oom_default"
    with tempfile.TemporaryDirectory() as root6:
        avoid_manifest = PersistentTask(avoid_config, plugin6, output_dir=root6).run()
        assert avoid_manifest["items"][1]["attempts"] == 1, "the known-failing default must be skipped"
        assert avoid_manifest["skipped_known_failure_plans"] == [""]
        assert avoid_manifest["outcome"] == SUCCESS


if __name__ == "__main__":  # pragma: no cover - runnable self-check
    _self_check()
    print("persistent_runner self-check passed")
