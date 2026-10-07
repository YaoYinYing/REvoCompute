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
  Each item carries two bounded evidence accumulators beside its state:
  ``resource_events`` (the normalized observations the server's estimator
  ingests) and ``recovery`` (one requested-versus-effective record per attempt,
  with the scientific-impact class of the action, so an adaptive-OOM step is
  auditable per item without scheduler logs).
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
import sys
import time
import traceback

SCHEMA_VERSION = 1
MANIFEST_NAME = "work_items.json"
TMP_DIR_NAME = ".tmp"

#: Work-item states (see docs/runner-guide/persistent-execution.md).
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

#: Execution-only adjustment keys that describe the *effective execution shape*
#: an attempt performs, so they belong in an observation's ``features.parameters``
#: (a fallback that sets one is a materially different workload to the estimator).
#: ``sample_group_size`` is absent because it is projected into
#: ``features.concurrent_samples``, which is the quantity memory is keyed on.
MATERIAL_FEATURE_KEYS = frozenset({"kernel_backend", "cpu_offload", "chunk_size", "token_budget"})

#: Parameter roles (see docs/runner-guide/persistent-execution.md). Every
#: parameter a Runner exposes carries exactly one role, which is what lets the
#: batch-equivalence comparator and the recovery audit agree on what
#: "the same effective scientific parameters" means:
#:
#: ``scientific``    governs what the model computes, so it is part of the
#:                   effective scientific parameter set a comparison holds fixed;
#: ``resource_only`` governs how the requested computation is executed, so an
#:                   adaptation that changes only these cannot change the result;
#: ``recovery``      the declared ladder itself (``stage``, ``fallback_plans``),
#:                   owned by the manifest and validated by the server;
#: ``provenance``    identity and bookkeeping no execution changes.
SCIENTIFIC = "scientific"
RESOURCE_ONLY = "resource_only"
RECOVERY = "recovery"
PROVENANCE = "provenance"
PARAMETER_ROLES = (SCIENTIFIC, RESOURCE_ONLY, RECOVERY, PROVENANCE)

#: Scientific-impact class of an automatic recovery action (see
#: docs/runner-guide/persistent-execution.md). ``resource_only`` is expected
#: not to change the result; ``numerical_backend`` may change floating
#: behavior; ``scientific_output`` changes the scientific
#: result itself — a different stochastic stream per sample, or a different
#: requested computation; ``unsafe`` is an action the lifecycle must never be
#: able to take automatically — a plan naming a scientific parameter.
NUMERICAL_BACKEND = "numerical_backend"
SCIENTIFIC_OUTPUT = "scientific_output"
UNSAFE = "unsafe"
RECOVERY_ACTION_CLASSES = (RESOURCE_ONLY, NUMERICAL_BACKEND, SCIENTIFIC_OUTPUT, UNSAFE)
#: Ordered by scientific impact; a plan changing several controls carries the
#: most impactful class of any of them.
_ACTION_RANK = {RESOURCE_ONLY: 0, NUMERICAL_BACKEND: 1, SCIENTIFIC_OUTPUT: 2, UNSAFE: 3}

#: The class of each execution-only adjustment the shared lifecycle understands,
#: so a recovery action is classified by one vocabulary wherever it is described.
#:
#: ``sample_group_size`` is ``scientific_output``, *not* ``resource_only``: it
#: changes how many samples are drawn simultaneously, and the samples inside one
#: group share that group's stochastic stream — so the same requested samples
#: come out with *different coordinates* under a different grouping (ESMFold 2
#: says so explicitly; SimpleFold re-seeds per group). The requested sample count
#: and per-sample seed declaration are untouched (see ``resolve_sample_plan``),
#: which is what makes the split inspectable, but the split is a scientific-output
#: change and is reported as one rather than as a neutral resource knob that would
#: imply baseline equivalence.
ADJUSTMENT_ACTIONS = {
    "sample_group_size": SCIENTIFIC_OUTPUT,
    "batch_size": RESOURCE_ONLY,
    "token_budget": RESOURCE_ONLY,
    "chunk_size": RESOURCE_ONLY,
    "cpu_offload": RESOURCE_ONLY,
    "cache_clear": RESOURCE_ONLY,
    "kernel_backend": NUMERICAL_BACKEND,
}

#: Bound on the per-attempt records kept in one item's recovery provenance.
RECOVERY_MAX_ATTEMPTS = 32

_FAILED_STATES = (FAILED_INPUT, FAILED_RESOURCE, FAILED_RUNTIME)


def classify_adjustments(adjustments: dict | None) -> str:
    """The scientific-impact class of one attempt's resource adjustments.

    The empty default path is not a recovery action, so it classifies as ``""``.
    A key outside the shared execution-only vocabulary classifies ``unsafe``:
    automatic recovery must never change a scientific parameter, so a plan that
    names one is an action the lifecycle must not be able to take.
    """
    adjustments = dict(adjustments or {})
    if not adjustments:
        return ""
    return max(
        (ADJUSTMENT_ACTIONS.get(str(key), UNSAFE) for key in adjustments),
        key=lambda name: _ACTION_RANK[name],
    )


def unsafe_adjustment_keys(adjustments: dict | None) -> list[str]:
    """The adjustment keys that name a scientific parameter, in stable order.

    These are keys outside the execution-only vocabulary: a plan naming one is
    refused at the runner boundary, so it can never mutate the scientific
    execution even if a malformed declaration or an injected plan reaches the
    runner. The server rejects such a plan first, but the runner fails closed on
    its own rather than trusting that it did.
    """
    return sorted(str(key) for key in dict(adjustments or {}) if ADJUSTMENT_ACTIONS.get(str(key), UNSAFE) == UNSAFE)


class WorkItemError(Exception):
    """An item failure classified so the task outcome can be derived.

    ``peaks`` carries the ``(peak_allocated_mb, peak_reserved_mb,
    peak_process_mb)`` a plugin measured before it failed, so an OOM row keeps
    its censored-bound evidence instead of being replaced by the post-failure
    residency.
    """

    def __init__(self, state: str, message: str, *, error_class: str = "", peaks=None) -> None:
        super().__init__(message)
        if state not in _FAILED_STATES:
            raise ValueError(f"Unclassified work-item failure state: {state!r}")
        self.state = state
        #: The runner's own classification (``CUDA_OOM``, ...), carried into the
        #: observation so a resource row names the failure the plugin reported
        #: rather than the exception wrapper this lifecycle raised.
        self.error_class = error_class
        self.peaks = tuple(peaks or (0, 0, 0))


class FatalTaskError(Exception):
    """A failure of the task as a whole; no work item can run."""


class TooEarlyError(Exception):
    """An attempt failed before the work item itself ran.

    The device could not be measured, so no plan has been tried and none can be
    blamed: the item fails as a runtime fault and the ladder is not walked for
    it. Only the item fails — the remaining items still get their turn.
    """


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
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        return None
    if any(not isinstance(entry, dict) for entry in payload["items"]):
        return None
    return payload


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


def new_manifest(task_id: str, runner: str, items: list[dict], *, snapshot_id: str = "") -> dict:
    return {
        "version": SCHEMA_VERSION,
        "task_id": task_id,
        "runner": runner,
        # The immutable input snapshot this manifest was built from. A resume
        # refuses a manifest whose snapshot differs, so identical item names with
        # changed content cannot silently publish new input as a committed result.
        "input_snapshot": str(snapshot_id or ""),
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
                "recovery": [],
            }
            for item in items
        ],
    }


def count(manifest: dict, states) -> int:
    if isinstance(states, str):
        states = (states,)
    return sum(1 for entry in manifest["items"] if entry["status"] in states)


def derive_outcome(manifest: dict) -> str:
    """Derive the task outcome from item states.

    See docs/runner-guide/persistent-execution.md for the state-to-outcome table.
    """
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
    """Stable execution order for the normalized work items.

    The first implementation is deliberately not a batcher. Persistent *serial*
    execution — load the runtime once, process items continuously — is the
    optimization target. For sequence workloads the queue orders by decreasing
    length so the longest item runs first: a long-tail OOM surfaces while the
    queue still has room to adapt, instead of failing the last item after hours
    of work. Items of comparable length stay adjacent so the runtime sees
    similar shapes in sequence.

    The queue only *orders*; it never drops a work item, and the original input
    order stays authoritative in the manifest.
    """

    #: Membership in a length bucket is a ratio of the previous boundary.
    DEFAULT_RATIOS = (1.5, 2.0)

    def __init__(self, *, ratios: tuple[float, ...] | None = None) -> None:
        self.ratios = tuple(ratios or self.DEFAULT_RATIOS)

    @classmethod
    def from_policy(cls, policy: dict | None) -> ExecutionQueue:
        policy = policy or {}
        return cls(ratios=policy.get("ratios"))

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
    names one of the runner's own declared fallbacks, whose ``adjustments`` stay
    within the execution-only vocabulary — validated on the server, which rejects
    any adjustment that names a requested scientific parameter. A fallback can
    still change the *result* (a sample grouping changes which stream draws each
    sample); ``classify_adjustments`` says how strongly, and the item's recorded
    effective parameter set makes the divergence explicit.
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
    attempt order and, per resource profile, the plans already known to fail for
    that profile plus the workload scale above which proactive avoidance applies.
    This class only enforces that sequence within a finite budget:

    * attempt 0 is always the default path unless ``avoid`` has profile-scoped
      evidence that the default fails for this item's scale;
    * a retry after a *real* OOM follows the declared order, skipping plans that
      already failed for this item, plans the evidence says are unsafe, and plans
      whose effective execution is a no-op (see
      :meth:`PersistentTask._active_order`);
    * ``observe`` changes no execution at all: no proactive skip, and *no*
      reactive fallback after a real OOM — the item is ``FAILED_RESOURCE``;
    * ``recover`` leaves the default path untouched and, after a real OOM, walks
      the declared fallbacks in order;
    * ``avoid`` adds proactive skipping of a profile-scoped known-failing plan or
      scale, on top of every ``recover`` behaviour;
    * the budget covers every declared plan in ``recover``/``avoid``, so a plan
      can never be declared and then be unreachable there; an operator's larger
      ``max_item_attempts`` raises it further. When the budget or the plans run
      out the item is ``FAILED_RESOURCE``. ``observe`` never walks the ladder at
      all — see the stage rules above — so its budget floor is inert.

    ``plans`` maps a label to its declared adjustments. An order entry the
    runner does not declare is skipped rather than guessed, so a malformed
    guidance block degrades to bounded recovery instead of undefined behaviour.

    The server cannot know the allocated GPU at submission time, so guidance
    carries one ``profiles`` block per exact ``(model revision, runtime
    fingerprint, device model, total VRAM)`` and the runner selects the block
    matching its own ``model_revision``, ``runtime_fingerprint``, and the device
    it was actually allocated. Anything else — an unknown device, a changed
    runtime, a different model revision — gets the default path plus bounded
    reactive recovery and never borrows another profile's threshold.
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
        declared_order = [str(plan["label"]) for plan in adaptation.get("fallback_plans") or [] if plan.get("label")]
        # ``plan_order`` is the attempt order the server sends; it may only
        # restrict the declared ladder, and an entry the runner does not declare
        # is skipped rather than guessed, so a malformed block degrades to
        # bounded recovery. Without one the declared ladder is the order.
        ordered = [str(label) for label in guidance.get("plan_order") or []] or ["", *declared_order]
        self.order = [label for label in ordered if label == "" or label in self.plans] or [""]
        self.profiles = [entry for entry in guidance.get("profiles") or [] if isinstance(entry, dict)]
        # Nothing is bound until the runtime identity is known (see bind_identity).
        self.known_failing: set[str] = set()
        self.avoid_at_or_above = None
        # In ``recover``/``avoid`` every declared plan must be reachable:
        # declaring one and never trying it is a silent no-op, which is what the
        # rest of this design refuses to allow. The budget is therefore a *floor*
        # of the default path plus each declared plan once; an operator's larger
        # budget raises it further, and a smaller one cannot make a plan
        # unreachable. (The server projects the key from `ExecutionSettings`,
        # whose own default is 1, so this floor is also what a manifest that
        # declares plans but no budget gets.) ``observe`` walks no ladder, so the
        # floor is inert there by design.
        declared = len([label for label in self.order if label]) or len(self.plans)
        self.max_attempts = max(int(execution.get("max_item_attempts") or 0), declared + 1)
        self.skipped: list[str] = []

    def bind_identity(self, model_revision: str, runtime_fingerprint: str, device: dict | None) -> None:
        """Select the guidance block for the runtime the runner actually loaded.

        The block must describe the executing revision, runtime, and allocated
        device together: a stale runtime or a different model revision on the
        same GPU must not receive the evidence. A block binds only when its
        model revision, runtime fingerprint, device model, and VRAM total all
        equal the runner's, so an 80 GB card is never given a 40 GB card's
        evidence and neither is another revision on the same card. With no match
        — an unknown device, a CPU-only image, a different revision, or an empty
        guidance block — the profile-scoped facts stay empty and only the
        default path plus bounded reactive recovery apply.
        """
        self.known_failing = set()
        self.avoid_at_or_above = None
        device = device or {}
        for profile in self.profiles:
            if str(profile.get("model_revision") or "") != str(model_revision or ""):
                continue
            if str(profile.get("runtime_fingerprint") or "") != str(runtime_fingerprint or ""):
                continue
            if str(profile.get("device_model") or "") != str(device.get("model") or ""):
                continue
            if int(profile.get("total_vram_mb") or 0) != int(device.get("total_vram_mb") or 0):
                continue
            self.known_failing = {str(label) for label in profile.get("known_failing_plans") or []}
            threshold = profile.get("avoid_scale_at_or_above")
            self.avoid_at_or_above = None if threshold is None else int(threshold)
            return

    def plan_for(self, attempt: int, failed: list[str], *, order: list[str] | None = None, scale: int = 0) -> Plan:
        """Choose the plan for a zero-based attempt number.

        ``order`` is the item's active ladder — the declared plans minus the ones
        that are a no-op for this item — computed once by the caller so a skipped
        no-op consumes no attempt.
        """
        ladder = self.order if order is None else order
        if attempt <= 0:
            if self._avoid_default(scale):
                first = self._first_allowed(ladder, failed)
                if first is not None:
                    self.skipped.append("")
                    return first
            return Plan("", {}, True, "default execution path")
        if attempt >= self.max_attempts:
            return Plan("", {}, False, "retry budget exhausted; item is FAILED_RESOURCE")
        if self.stage == "observe":
            # OBSERVE collects observations only: a real OOM is recorded and the
            # item fails. Changing to a fallback here would be the execution
            # change the stage exists to forbid.
            return Plan("", {}, False, "observe records the failure without retrying; item is FAILED_RESOURCE")
        candidate = self._first_allowed(ladder, failed)
        if candidate is None:
            return Plan("", {}, False, "all runner-declared fallbacks exhausted; item is FAILED_RESOURCE")
        return candidate

    def _first_allowed(self, ladder: list[str], failed: list[str]) -> Plan | None:
        for label in ladder:
            if label == "" or label in failed or label in self.known_failing:
                continue
            return Plan(label, self.plans[label], True, "bounded OOM recovery")
        return None

    def _avoid_default(self, scale: int) -> bool:
        """Whether this profile's evidence says the workload is a known failure."""
        if self.stage != "avoid":
            return False
        if "" in self.known_failing:
            return True
        return bool(self.avoid_at_or_above and scale >= int(self.avoid_at_or_above))


def active_plan_order(payload: dict, sequence: PlanSequence, effective_key) -> list[str]:
    """The declared ladder minus plans that are a no-op for this work item.

    A plan whose effective execution equals the default's, or an earlier plan's,
    would consume a retry without changing what ran, so it is dropped before
    execution rather than attempted. The default path stays first.
    """
    keys: list[str] = []
    active: list[str] = []
    for label in sequence.order:
        key = effective_key(payload, sequence.plans.get(label, {}))
        if label and key in keys:
            continue
        keys.append(key)
        active.append(label)
    return active


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
    _discard_tree(temporary)
    os.makedirs(temporary, exist_ok=True)
    return temporary


def discard_item_staging(output_dir: str, name: str) -> None:
    """Remove an attempt's staging tree *and* the container once it is empty.

    A staging tree left behind is not merely untidy: its files sit inside the
    result directory, so an artifact selector that spans the tree would publish
    a failed item's partial output as a result. Removing the empty ``.tmp``
    container too keeps a completed task's result directory free of the
    staging namespace entirely.
    """
    temporary = item_tmp_dir(output_dir, name)
    _discard_tree(temporary)
    try:
        os.rmdir(os.path.dirname(temporary))
    except OSError:
        pass


def _discard_tree(path: str) -> None:
    """Remove *path* if it is a directory, or unlink it if it is a stray file."""
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path, ignore_errors=True)
    elif os.path.lexists(path):
        try:
            os.unlink(path)
        except OSError:
            pass


def sweep_staging(output_dir: str) -> None:
    """Remove the staging namespace once the task is finished.

    Every attempt removes its own tree, so this covers only trees a previous,
    killed worker left behind. A leftover tree is not just untidy: it lives
    inside the result directory, where a selector spanning the tree could
    publish a failed item's partial output as a result.
    """
    staging_root = os.path.join(output_dir, TMP_DIR_NAME)
    if os.path.isdir(staging_root) and not os.path.islink(staging_root):
        shutil.rmtree(staging_root, ignore_errors=True)
    elif os.path.lexists(staging_root):
        try:
            os.unlink(staging_root)
        except OSError:
            pass


def commit_item(output_dir: str, name: str) -> str:
    """Atomically promote a validated item directory into its final location.

    The commit is a rename, so a reader never sees a partial directory as a
    completed result. The temp tree is created as a sibling of the destination
    and verified to be inside this task's output root, so the one destructive
    step renames only a directory the runner just built.

    A destination that already exists is not an error: the runner writes the
    manifest *after* the rename, so a worker that dies in that window leaves a
    committed directory with the item still marked ``RUNNING``. On resume the
    item runs again, and treating that state as a collision would fail
    permanently an item whose result is already published. The existing
    directory is authoritative — it was produced by the same deterministic work
    item — so it is kept and the fresh staging tree is discarded.
    """
    temporary = item_tmp_dir(output_dir, name)
    destination = item_dir(output_dir, name)
    if not os.path.isdir(temporary):
        raise WorkItemError(FAILED_RUNTIME, f"work item {name!r} produced no staged output directory")
    _require_child(output_dir, temporary)
    _require_child(output_dir, destination)
    if os.path.isdir(destination):
        shutil.rmtree(temporary, ignore_errors=True)
    elif os.path.exists(destination):
        raise WorkItemError(FAILED_RUNTIME, f"work item {name!r} output path is not a directory")
    else:
        os.replace(temporary, destination)
    try:
        os.rmdir(os.path.dirname(temporary))
    except OSError:
        pass
    return destination


def _require_child(output_dir: str, path: str) -> None:
    """Refuse a work-item path that escapes this task's output root.

    The item name is normalized from a user-supplied identifier, so this is the
    last check that the one destructive rename cannot leave the task directory
    even if normalization is ever changed.
    """
    root = os.path.realpath(output_dir)
    target = os.path.realpath(path)
    if target != root and not target.startswith(root + os.sep):
        raise WorkItemError(FAILED_RUNTIME, f"work item path escapes the task output directory: {path!r}")


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
        # The immutable input snapshot this task executes against. Recorded in the
        # durable manifest, so a resume can verify it is the same snapshot rather
        # than trusting that identical item names mean identical inputs.
        self.input_sha256 = str(config.get("input_sha256") or "")
        self.snapshot_id = self.input_sha256 or self.task_id
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
        #: Plans refused at the runner boundary because they name a scientific
        #: parameter. Recorded, never executed (see ``_active_order``).
        self.refused_unsafe_plans: list[str] = []

    # -- lifecycle ----------------------------------------------------------

    def initialize_runtime(self) -> None:
        """Load model weights / CUDA context / indexes — once per task."""
        self.runtime = self.plugin.initialize_runtime(self.execution)
        self.available_mb = int(self.plugin.available_vram_mb(self.runtime) or 0)
        # The allocated device, model revision, and runtime fingerprint are only
        # knowable and reliable now, so this is where the guidance block for
        # them is selected. Before this call no profile-scoped avoidance exists,
        # which is also what an unknown device must get.
        self.plans.bind_identity(
            str(self.plugin.model_revision),
            str(self.plugin.runtime_fingerprint),
            self.plugin.device_profile(self.runtime),
        )

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
        """Run one attempt and record its observation; raises on failure."""
        # Measurement precedes execution, so a plugin whose measurement hook
        # itself raises (a dead CUDA context on a real device) is reporting that
        # the attempt could not run. ``TooEarlyError`` makes that a *runtime*
        # fault with no fallback retry: another execution plan cannot fix an
        # unreadable device, and re-running would spend the ladder on it.
        try:
            baseline_mb = int(self.plugin.runtime_usage(self.runtime)[0])
            # Free memory *before* the item runs: this is what the workload had
            # to fit in, so a row whose peak exceeds it is another process's
            # doing, not this workload's demand.
            available_mb = int(self.plugin.available_vram_mb(self.runtime) or 0)
        except Exception as error:
            raise TooEarlyError(f"{type(error).__name__}: {error}") from error
        started = time.time()
        try:
            peak_allocated_mb, peak_reserved_mb, peak_process_mb = self._execute(entry, item, plan)
        except Exception:
            discard_item_staging(self.output_dir, entry["name"])
            raise
        finished = time.time()
        entry["status"] = SUCCEEDED
        entry["started_at"] = started
        entry["finished_at"] = finished
        entry["error"] = None
        try:
            return self._observation(
                entry,
                item,
                plan,
                outcome=OUTCOME_SUCCESS,
                baseline_mb=baseline_mb,
                peak_allocated_mb=peak_allocated_mb,
                peak_reserved_mb=peak_reserved_mb,
                peak_process_mb=peak_process_mb,
                available_mb=available_mb,
                error_class="",
                runtime_seconds=round(finished - started, 3),
            )
        except Exception:
            # The item is committed, so its measurement is bookkeeping: a failed
            # read (a context that died after inference) must not rewrite a
            # published result as a runtime failure.
            traceback.print_exc()
            return None

    def _observation(self, entry: dict, item: dict, plan: Plan, **fields) -> dict:
        """Build, record, and publish one normalized resource observation.

        Only raw facts are recorded — the device, the baseline, the memory free
        before the item, the three measured peaks, and the *effective* execution
        shape. Observation quality is derived server-side; the runner has already
        reported more than one quantity a naive comparison would confuse, so it
        does not label the row itself.
        """
        try:
            self._record_attempt(entry, item, plan)
        except Exception:
            # The recovery record is evidence, not state: a failure to write it
            # must not cost the observation (or rewrite a published result).
            traceback.print_exc()
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
            "available_mb": int(fields.pop("available_mb", 0) or self.plugin.available_vram_mb(self.runtime) or 0),
            "outcome": fields.pop("outcome"),
            "error_class": str(fields.pop("error_class", "")),
            "runtime_seconds": float(fields.pop("runtime_seconds", 0.0)),
            "plan_label": str(plan.label or ""),
            # The scientific-impact class of this attempt's recovery action: how
            # the server and a reviewer tell a resource-only rung from a
            # numerical-backend one, and that no rung names a scientific change.
            "action": classify_adjustments(plan.adjustments),
            "created_at": time.time(),
        }
        entry.setdefault("resource_events", []).append(observation)
        print("REVODESIGN_OBSERVATION:" + json.dumps(observation, sort_keys=True), flush=True)
        return observation

    def _record_attempt(self, entry: dict, item: dict, plan: Plan) -> None:
        """Append one attempt's recovery-provenance record to the item.

        This is the audit trail `Recovery provenance` in
        docs/runner-guide/persistent-execution.md needs, kept beside the item it
        describes rather than in a second store. Per attempt it names the plan
        and its scientific-impact class, the resource-only settings applied, and
        the *effective* scientific parameter set — so a reviewer sees whether the
        requested parameters survived recovery by comparing it with the item's
        ``parameters``, and never has to infer a scientific change from logs.
        The measured evidence (device, peaks, outcome) stays in ``resource_events``
        at the same attempt index, which this record references by number instead
        of duplicating.
        """
        adjustments = dict(plan.adjustments or {})
        entry.setdefault("recovery", []).append(
            {
                "attempt": entry["attempts"],
                "plan_label": str(plan.label or ""),
                "action": classify_adjustments(adjustments),
                # The settings applied that are resource-only by vocabulary. A
                # key classified otherwise (a backend, or an unsafe scientific
                # one) is never filed here: it belongs to the effective set, where
                # its divergence from the request is the disclosure.
                "resources": {
                    str(key): value
                    for key, value in adjustments.items()
                    if ADJUSTMENT_ACTIONS.get(str(key)) == RESOURCE_ONLY
                },
                "effective_parameters": self._effective_parameters(item["payload"], adjustments),
            }
        )
        # Bounded like every other per-item accumulator: a runaway retry must not
        # grow the durable manifest without limit.
        records = entry["recovery"]
        if len(records) > RECOVERY_MAX_ATTEMPTS:
            del records[: len(records) - RECOVERY_MAX_ATTEMPTS]

    def _effective_parameters(self, payload: dict, adjustments: dict) -> dict:
        """The effective *scientific* parameter set one attempt executes.

        A plugin that resolves its own plan implements ``effective_parameters``;
        otherwise the declared requested set is the effective set, which is
        exactly true for a family whose resource adjustments cannot reach a
        scientific parameter.
        """
        hook = getattr(self.plugin, "effective_parameters", None)
        if hook is not None:
            return {str(key): value for key, value in dict(hook(payload, adjustments) or {}).items()}
        return {str(key): value for key, value in dict(payload.get("requested_parameters") or {}).items()}

    def _scale(self, payload: dict) -> int:
        """Workload size proxy in *requested* units (the server's ``requested_scale``).

        The avoidance threshold the server publishes is computed from a request's
        declared shape, because the runner must compare an item against it before
        any plan has run. Both sides therefore multiply the same four requested
        quantities — declared batch size included — and the comparison is between
        the same unit.
        """
        return (
            int(payload.get("length") or 0)
            * int(payload.get("sequence_count") or 1)
            * int(payload.get("sample_count") or 1)
            * int(self.execution.get("batch_size") or 1)
        )

    def _features(self, payload: dict, adjustments: dict) -> dict:
        """The effective execution shape of one attempt.

        ``sample_count`` is the requested multiplicity and stays provenance.
        ``concurrent_samples`` is how many samples this attempt drew
        simultaneously, which is what the memory shape is keyed on. Material
        execution-only settings the attempt actually applied are carried in
        ``parameters``, omitting any the plan did not set.
        """
        adjustments = dict(adjustments or {})
        requested = int(payload.get("sample_count") or 1)
        group = adjustments.get("sample_group_size")
        concurrent = requested if group is None else min(requested, max(1, int(group)))
        parameters = {key: value for key, value in adjustments.items() if key in MATERIAL_FEATURE_KEYS}
        return {
            "runner": self.runner,
            "model_revision": str(self.plugin.model_revision),
            "runtime_fingerprint": str(self.plugin.runtime_fingerprint),
            "sequence_length": int(payload.get("length") or 1),
            "sequence_count": int(payload.get("sequence_count") or 1),
            "batch_size": int(adjustments.get("batch_size") or self.execution.get("batch_size", 1)),
            "sample_count": int(payload.get("sample_count") or 1),
            "concurrent_samples": max(1, concurrent),
            "parameters": parameters,
        }

    def _effective_key(self, payload: dict, adjustments: dict) -> str:
        """Canonical key of the execution a plan actually performs for one item.

        A plugin that knows its own plan resolution implements
        ``effective_plan_key``; otherwise the sorted adjustments JSON is the
        canonical string, which is enough for a family whose plans map one-to-one
        onto executions.
        """
        hook = getattr(self.plugin, "effective_plan_key", None)
        if hook is None:
            return json.dumps(dict(adjustments or {}), sort_keys=True)
        return str(hook(payload, adjustments))

    def _active_order(self, payload: dict) -> list[str]:
        """The declared ladder minus plans this runner must not execute.

        Two kinds of plan are dropped before the ladder is walked. A plan that is
        a no-op for this work item would consume an attempt without changing the
        execution. A plan that names a *scientific* parameter is refused: the
        server rejects such a declaration, but the runner fails closed on its own
        too, so an injected or malformed plan can never mutate the scientific
        execution. Refusals are recorded so the task summary says what was
        declined rather than dropping it silently.
        """
        refused = [
            label
            for label in self.plans.order
            if label and unsafe_adjustment_keys(self.plans.plans.get(label))
        ]
        if refused:
            for label in refused:
                if label not in self.refused_unsafe_plans:
                    self.refused_unsafe_plans.append(label)
            self.plans.order = [label for label in self.plans.order if label not in refused]
        return active_plan_order(payload, self.plans, self._effective_key)

    # -- bounded recovery ---------------------------------------------------

    def process_entry(self, manifest: dict, index: int) -> None:
        entry = manifest["items"][index]
        item = self.items[index]
        if entry["status"] == SUCCEEDED:
            return  # resume: never recompute committed work
        failed: list[str] = []
        # The item's ladder is fixed before the first attempt: plans that are a
        # no-op for this item are dropped, so they can never consume an attempt.
        order = self._active_order(item["payload"])
        scale = self._scale(item["payload"])
        while entry["attempts"] < self.plans.max_attempts:
            plan = self.plans.plan_for(entry["attempts"], failed, order=order, scale=scale)
            if not plan.allowed:
                self._fail(entry, FAILED_RESOURCE, plan.reason)
                write_work_items(self.output_dir, manifest)
                return
            entry["attempts"] += 1
            entry["status"] = RUNNING
            write_work_items(self.output_dir, manifest)
            try:
                self.attempt_item(entry, item, plan)
            except TooEarlyError as error:
                # Nothing ran, so this attempt cannot be re-planned into a
                # different execution: fail the item as a runtime fault.
                self._fail(entry, FAILED_RUNTIME, str(error))
                write_work_items(self.output_dir, manifest)
                return
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
                try:
                    self._observe_failure(entry, item, plan, error)
                except Exception:
                    # The failed attempt's observation is evidence, not state: a
                    # dead context must not stop the item from being failed and
                    # the remaining items from running.
                    traceback.print_exc()
                # An exception that reaches here was never classified as a
                # recoverable resource failure — the plugin reports those as an
                # OOM outcome, handled above. So it is a runtime fault and
                # consumes no fallback attempt: retrying a validation,
                # filesystem, or model bug under a smaller plan only repeats it.
                self._fail(entry, FAILED_RUNTIME, f"{type(error).__name__}: {error}")
                if _looks_like_cuda_fault(error) and self.runtime_restarts < int(
                    self.execution.get("max_runtime_restarts", 1)
                ):
                    # Last-resort recovery: the CUDA context is unhealthy, so
                    # rebuild it. The item itself is failed — its allocation is
                    # gone — but the *remaining* items resume against a healthy
                    # runtime instead of all failing with it. A context that
                    # cannot even be rebuilt restarts nothing, so it leaves the
                    # remaining items on the exhausted runtime rather than
                    # aborting a task whose other items may still succeed.
                    try:
                        self.restart_runtime()
                    except Exception:
                        traceback.print_exc()
                write_work_items(self.output_dir, manifest)
                return
            write_work_items(self.output_dir, manifest)
            return
        # The loop's own guard is what normally ends the item: `plan_for` refuses
        # a retry once the budget is reached, and refusing consumes no attempt, so
        # this line only catches a plan that was allowed but never recorded as
        # failed — unreachable today, kept because a retry must always be finite.
        self._fail(entry, FAILED_RESOURCE, "retry budget exhausted")
        write_work_items(self.output_dir, manifest)

    def _observe_failure(self, entry: dict, item: dict, plan: Plan, error: Exception) -> None:
        """Record a failed attempt, keeping whatever the plugin did measure.

        An OOM row is a censored constraint — the evidence that this workload
        needs more than the device had — so the peaks the plugin reported are
        preserved rather than replaced by the post-failure residency.
        """
        state = getattr(error, "state", FAILED_RUNTIME)
        peak_allocated, peak_reserved, process_peak = getattr(error, "peaks", (0, 0, 0))
        self._observation(
            entry,
            item,
            plan,
            outcome=OUTCOME_OOM if state == FAILED_RESOURCE else OUTCOME_ERROR,
            peak_allocated_mb=peak_allocated,
            peak_reserved_mb=peak_reserved,
            peak_process_mb=process_peak,
            error_class=getattr(error, "error_class", "") or type(error).__name__,
        )

    def _execute(self, entry: dict, item: dict, plan: Plan) -> tuple[int, int, int]:
        """Run, validate, and commit one item, or raise a classified failure.

        A plugin reports a bounded failure by outcome, so the retry decision is
        explicit rather than inferred from an exception type; the peaks it
        measured travel with the error so the observation stays informative.

        On success the peaks are *returned*: the plugin measured them with the
        framework's own high-water counters, which is the only witness to what
        the workload actually demanded. Re-reading a current-residency figure
        afterwards would report the post-inference allocator state, so a
        successful row would claim the workload grew by nothing.
        """
        staging = reset_item_staging(self.output_dir, entry["name"])
        outcome, peak_allocated, peak_reserved, process_peak, error_class = self.plugin.run_item(
            self.runtime, item["payload"], plan.adjustments, staging, self.execution
        )
        if outcome != OUTCOME_SUCCESS:
            raise WorkItemError(
                FAILED_RESOURCE if outcome == OUTCOME_OOM else FAILED_RUNTIME,
                error_class or f"work item {outcome}",
                error_class=error_class,
                peaks=(peak_allocated, peak_reserved, process_peak),
            )
        self.plugin.validate_item(staging, item["payload"], plan.adjustments)
        commit_item(self.output_dir, entry["name"])
        return peak_allocated, peak_reserved, process_peak

    @staticmethod
    def _fail(entry: dict, state: str, message: str) -> None:
        entry["status"] = state
        entry["error"] = message
        entry["finished_at"] = time.time()

    # -- task level ---------------------------------------------------------

    def _resumed_manifest(self) -> dict:
        """The durable manifest to resume, or a fresh one for a different task.

        Resume is safe only against the *same immutable input snapshot*: a
        resumed worker must not skip a committed item when the input has changed,
        or the old result would silently bind to the new input. Comparing the
        item names alone is not enough for that — two FASTA files with the same
        record headers but different sequences normalize to the same names — so
        the recorded snapshot identity is compared too. Anything else (a missing
        manifest, a different task, different items, or a different snapshot) is
        a fresh run, which recomputes every item rather than trusting stale state.
        """
        manifest = read_work_items(self.output_dir)
        if manifest is None:
            return new_manifest(self.task_id, self.runner, self.items, snapshot_id=self.snapshot_id)
        if str(manifest.get("task_id") or "") != self.task_id:
            return new_manifest(self.task_id, self.runner, self.items, snapshot_id=self.snapshot_id)
        if [entry["name"] for entry in manifest["items"]] != [item["name"] for item in self.items]:
            return new_manifest(self.task_id, self.runner, self.items, snapshot_id=self.snapshot_id)
        # A manifest written before snapshot identity was recorded carries no
        # identity; resuming it cannot be verified, so it is rebuilt.
        if str(manifest.get("input_snapshot") or "") != self.snapshot_id:
            return new_manifest(self.task_id, self.runner, self.items, snapshot_id=self.snapshot_id)
        return manifest

    def run(self) -> dict:
        os.makedirs(self.output_dir, exist_ok=True)
        self.items = normalize_items(list(self.config["items"]))
        manifest = self._resumed_manifest()
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
            # A plan refused for naming a scientific parameter is recorded, so
            # the task summary shows what automatic recovery declined to run.
            if self.refused_unsafe_plans:
                manifest["refused_unsafe_plans"] = list(dict.fromkeys(self.refused_unsafe_plans))
            write_work_items(self.output_dir, manifest)
        finally:
            self.finalize()
        sweep_staging(self.output_dir)
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


def exit_code_for(manifest: dict) -> int:
    """The family entrypoint's process status for a completed task.

    A task that produced no successful work item is a failed task, and the
    process must say so: the wrapper's exit code is what decides
    ``tasks.status``, so returning 0 here would publish FAILED as ``finished``
    and leave a consumer that reads only the status reporting a failed
    experiment as a success. ``PARTIAL_SUCCESS`` is a real result and stays 0 —
    the derived outcome is what distinguishes it.
    """
    outcome = str(manifest.get("outcome") or "")
    if outcome in (SUCCESS, PARTIAL_SUCCESS):
        return 0
    print(f"task outcome: {outcome or 'unknown'}", file=sys.stderr)
    return 1


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
                return OUTCOME_OOM, 1000, 1200, 900, "CUDA_OOM"
            if self.outcomes.get(payload["id"]) == "oom_default" and not adjustments:
                return OUTCOME_OOM, 1000, 1200, 900, "CUDA_OOM"
            if payload["id"] in self.oom_once:
                self.oom_once.discard(payload["id"])
                return OUTCOME_OOM, 1000, 1200, 900, "CUDA_OOM"
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
        # The OOM row kept the peaks the plugin measured, not the post-failure
        # residency: that is the censored bound the estimator learns from.
        oom_rows = [
            event
            for event in manifest["items"][1]["resource_events"]
            if event["outcome"] == OUTCOME_OOM
        ]
        assert oom_rows and oom_rows[0]["peak_reserved_mb"] == 1200, oom_rows
        # No runner-side quality label: raw facts only, quality is derived from
        # them server-side.
        assert "quality" not in oom_rows[0], oom_rows[0]

        # Resume: a second run must not reload the runtime or recompute anything.
        plugin.loads = 0
        resumed = PersistentTask(config, plugin, output_dir=root).run()
        assert plugin.loads == 0, "a fully committed task must not reload the runtime"
        assert resumed["outcome"] == SUCCESS

        # A committed directory with the manifest still saying RUNNING (a worker
        # died in the window between the rename and the manifest write) is
        # already complete: resume must keep it, not fail the item.
        text = work_items_path(root)
        with open(text, encoding="utf-8") as handle:
            stale = json.load(handle)
        stale["items"][0]["status"] = RUNNING
        stale["items"][0]["attempts"] = 1
        with open(text, "w", encoding="utf-8") as handle:
            json.dump(stale, handle)
        plugin.loads = 0
        recovered = PersistentTask(config, plugin, output_dir=root).run()
        assert recovered["items"][0]["status"] == SUCCEEDED, recovered["items"][0]
        assert recovered["outcome"] == SUCCESS

    # Every declared plan is reachable however small the manifest's declared
    # budget is: the budget is a floor of the default path plus each plan once.
    # A declared 2 (the server's own default is 1) must still try four plans.
    for declared_budget in ({}, {"max_item_attempts": 2}):
        three_plans = {
            **config,
            "execution": declared_budget,
            "resource_adaptation": {
                "stage": "recover",
                "fallback_plans": [
                    {"label": "one", "adjustments": {"sample_group_size": 1}},
                    {"label": "two", "adjustments": {"sample_group_size": 2}},
                    {"label": "three", "adjustments": {"sample_group_size": 3}},
                ],
            },
            "resource_guidance": {"plan_order": ["", "one", "two", "three"]},
        }
        plugin7 = FakePlugin()
        plugin7.always_oom = {"p0", "p1", "p2"}
        with tempfile.TemporaryDirectory() as root7:
            tried = []
            original = plugin7.run_item

            def recording(*args):
                tried.append(dict(args[2]))
                return original(*args)

            plugin7.run_item = recording
            result7 = PersistentTask(three_plans, plugin7, output_dir=root7).run()
            assert result7["outcome"] == FAILED
            attempts = [entry["attempts"] for entry in result7["items"]]
            assert attempts == [4, 4, 4], (declared_budget, attempts)
            # Every declared plan really ran: the last one is not stranded by
            # the manifest's cap.
            assert {size for adjustment in tried for size in adjustment.values()} >= {1, 2, 3}, declared_budget

    # A no-op plan consumes no attempt. Nothing in this item's payload carries a
    # requested sample count, so every declared plan is a distinct execution —
    # except a duplicate, which is dropped before the ladder is walked.
    duplicate_plans = {
        **config,
        "resource_adaptation": {
            "stage": "recover",
            "fallback_plans": [
                {"label": "split", "adjustments": {"batch_size": 1}},
                {"label": "same_as_split", "adjustments": {"batch_size": 1}},
            ],
        },
        "resource_guidance": {"plan_order": ["", "split", "same_as_split"]},
    }
    plugin9 = FakePlugin()
    plugin9.always_oom = {"p0"}
    with tempfile.TemporaryDirectory() as root9:
        result9 = PersistentTask(duplicate_plans, plugin9, output_dir=root9).run()
        entry9 = next(entry for entry in result9["items"] if entry["id"] == "p0")
        assert entry9["status"] == FAILED_RESOURCE
        assert entry9["attempts"] == 2, "a duplicate plan is a no-op, not an attempt"

    # An unknown device gets no profile-scoped avoidance: the guidance's blocks
    # name another device, so nothing is bound and the default path is unchanged.
    other_device = {
        **config,
        "resource_adaptation": {**config["resource_adaptation"], "stage": "avoid"},
        "resource_guidance": {
            "plan_order": ["", "split"],
            "profiles": [
                {
                    "model_revision": "m1",
                    "runtime_fingerprint": "fp",
                    "device_model": "H100-PCIE-80GB",
                    "total_vram_mb": 81559,
                    "known_failing_plans": [""],
                    "avoid_scale_at_or_above": 0,
                }
            ],
        },
    }
    with tempfile.TemporaryDirectory() as root10:
        manifest10 = PersistentTask(other_device, FakePlugin(), output_dir=root10).run()
        assert manifest10["outcome"] == SUCCESS
        assert manifest10["skipped_known_failure_plans"] == []

    # A successful row records the peaks the plugin measured, not the residency
    # left behind once inference finished.
    with tempfile.TemporaryDirectory() as root8:
        manifest8 = PersistentTask(config, FakePlugin(), output_dir=root8).run()
        assert manifest8["outcome"] == SUCCESS
        row = manifest8["items"][0]["resource_events"][0]
        assert (row["peak_allocated_mb"], row["peak_reserved_mb"], row["peak_process_mb"]) == (1000, 1200, 900), row
        assert row["baseline_mb"] == 100, row
        assert "quality" not in row, row

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

    # observe: collect observations only. A successful default run is never
    # modified and the *proactive* avoid path stays disabled — and a real OOM is
    # recorded and failed, with NO reactive fallback, because recovery is itself
    # an execution change the stage forbids.
    avoid_guidance = {
        "plan_order": ["", "split"],
        "profiles": [
            {
                "model_revision": "m1",
                "runtime_fingerprint": "fp",
                "device_model": "A100-PCIE-40GB",
                "total_vram_mb": 40960,
                "known_failing_plans": [""],
                "avoid_scale_at_or_above": 100,
            }
        ],
    }
    observe_config = {
        **config,
        "resource_adaptation": {**config["resource_adaptation"], "stage": "observe"},
        "resource_guidance": avoid_guidance,
    }
    plugin5 = FakePlugin()
    plugin5.oom_once.add("p1")
    with tempfile.TemporaryDirectory() as root5:
        observe_manifest = PersistentTask(observe_config, plugin5, output_dir=root5).run()
        assert observe_manifest["outcome"] == PARTIAL_SUCCESS, observe_manifest["outcome"]
        # Unchanged default path: nothing was avoided.
        assert observe_manifest["skipped_known_failure_plans"] == []
        attempts = {entry["id"]: entry["attempts"] for entry in observe_manifest["items"]}
        assert attempts == {"p0": 1, "p1": 1, "p2": 1}, attempts
        failed_entry = next(entry for entry in observe_manifest["items"] if entry["id"] == "p1")
        assert failed_entry["status"] == FAILED_RESOURCE
        assert "observe" in failed_entry["error"]

    # avoid: a profile-scoped known-failing default is skipped without repeating
    # it, and only the bound device's block may do that.
    avoid_config = {
        **config,
        "resource_adaptation": {**config["resource_adaptation"], "stage": "avoid"},
        "resource_guidance": avoid_guidance,
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
