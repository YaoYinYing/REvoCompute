# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Device-aware, CPU-only VRAM estimation and execution planning.

This is the implementation of the three responsibilities the Runner Protocol
separates:

``DeviceObserver``
    reports the dynamic device facts a prediction needs — which GPU is actually
    assigned and how much of it is free — and collects a normalized
    :class:`ResourceObservation` per execution attempt. Measurement happens
    where the GPU allocations live: inside the runner, using the framework that
    owns them. The server consumes the schema and never installs a framework to
    collect it; the collection code lives in the runner
    (``docker/runners/common/persistent_runner.py``, stdlib only), and this
    module owns the schema those rows are normalized into.

``VRAMEstimator``
    learns ``workload + execution configuration + device/runtime profile ->
    peak VRAM``. It never mutates runner parameters and never needs a GPU.

``ResourcePlanner``
    compares required against available memory and picks a semantically
    equivalent lower-memory plan from the options the *runner* declared.

This module is **server-side only**: runners measure with the framework that
owns their GPU allocations and enforce the plan order the server sends them
(``guidance_for``), so no runner image ships NumPy or a second estimator.

Design constraints (see ``TODO.md`` §7–§19 and §28):

* stdlib + NumPy only. No PyTorch/JAX/TF/Triton/Ray — this is system
  identification, not deep learning.
* the default execution path is authoritative and unchanged; the estimator only
  observes successful runs and is consulted after an actual OOM (``recover``)
  or to skip a well-characterized failure region (``avoid``).
* predictions carry an expected value, a conservative upper bound, and
  confidence/applicability; outside the learned domain the estimator says so
  and the planner falls back to heuristics rather than trusting extrapolation.
* memory is factored as ``runtime/model baseline + workload-dependent
  incremental``; the workload term is fitted per runner/model group, so a new
  GPU class starts from corrections to that runner's own fit rather than
  relearning from zero or borrowing another runner's coefficients.
* observations are keyed by device *class*, never by physical identity such as
  ``node01:gpu0``.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

SCHEMA_VERSION = 1

#: Rollout stages. ``observe`` never modifies a successful execution; ``recover``
#: consults the planner only after a real OOM; ``avoid`` additionally skips a
#: plan already established as unsafe for the same workload/device/runtime.
STAGES = ("observe", "recover", "avoid")

#: Observation outcomes. ``oom`` rows are censored constraints
#: (``required > available``) and are retained, never discarded as failures.
OUTCOME_SUCCESS = "success"
OUTCOME_OOM = "oom"
OUTCOME_ERROR = "error"

#: Observation quality. ``valid`` rows train the estimator; ``suspect`` rows are
#: kept for diagnostics and down-weighted; ``interference`` rows are excluded
#: from fitting because another process or the runtime, not the workload,
#: explains the reading.
QUALITY_VALID = "valid"
QUALITY_SUSPECT = "suspect"
QUALITY_INTERFERENCE = "interference"
QUALITIES = (QUALITY_VALID, QUALITY_SUSPECT, QUALITY_INTERFERENCE)
_QUALITY_WEIGHT = {QUALITY_VALID: 1.0, QUALITY_SUSPECT: 0.25, QUALITY_INTERFERENCE: 0.0}

#: Below this many applicable training rows a prediction is not trusted for a
#: proactive decision, and the planner uses conservative heuristics instead.
MIN_OBSERVATIONS = 4
#: Feature envelope slack: a workload this many times longer than anything
#: observed is extrapolation, however many rows exist.
EXTRAPOLATION_FACTOR = 4.0
#: Ridge strength, relative to the mean squared feature scale.
RIDGE = 1e-3

_PLAN_KEYS = frozenset({"label", "title", "adjustments"})
#: First vendor/model token that reads as a model family after the vendor/brand
#: words: ``A100``, ``H100``, ``V100``, ``T4``, ``L40S``, and the digit-first
#: ``4090``. Memory suffixes (``80GB``) never match, so they stay out of the
#: class key and remain the business of :attr:`DeviceProfile.vram_class`.
_MODEL_FAMILY = re.compile(r"[A-Za-z]+[0-9][A-Za-z0-9]*|[0-9]{3,}[A-Za-z]?[A-Za-z0-9]*")
#: Execution-only parameters a fallback may change. Anything the user selected
#: as science (sample count, recycles, model, seed, input content, MSA/template
#: usage) is absent by construction, so a runner cannot declare an adaptation
#: that changes the requested computation.
ADAPTATION_KEYS = frozenset(
    {
        "sample_group_size",
        "batch_size",
        "token_budget",
        "chunk_size",
        "cpu_offload",
        "kernel_backend",
        "cache_clear",
    }
)


class ResourceModelError(ValueError):
    """Raised for an invalid device profile, observation, or fallback plan."""


# ---------------------------------------------------------------------------
# Device
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DeviceProfile:
    """Stable properties of the device a job was actually allocated.

    Determined *after* Slurm allocation by the runner, never assumed at
    submission time. ``model`` is the vendor's device name (``A100-PCIE-40GB``),
    which is deliberately coarser than a physical GPU identity.
    """

    vendor: str
    model: str
    compute_capability: str
    total_vram_mb: int
    mig_profile: str = ""

    def __post_init__(self) -> None:
        if not self.vendor or not self.model:
            raise ResourceModelError("DeviceProfile requires a vendor and a model")
        if isinstance(self.total_vram_mb, bool) or self.total_vram_mb <= 0:
            raise ResourceModelError("DeviceProfile requires a positive total VRAM")

    @property
    def device_class(self) -> str:
        """Class key: equivalent devices share observations.

        The runtime's device name carries vendor/brand words, a model family,
        and often a form factor and memory size (``NVIDIA H100 PCIe``,
        ``NVIDIA H100 80GB HBM3``, ``A100-SXM4-80GB``). Only the family is the
        class: two SKUs of one family learn together instead of fragmenting the
        observation history, while :attr:`vram_class` and the profile key keep
        the memory size separate. A name that carries no family token (a bare
        ``GPU``, an arena tag) keeps its whole name rather than collapsing onto
        an unrelated class.
        """
        base = _MODEL_FAMILY.search(self.model)
        return f"{self.vendor}/{base.group() if base else self.model.strip() or 'unknown'}"

    @property
    def vram_class(self) -> str:
        # Round to the nearest 8 GiB so near-identical SKUs share a class.
        return f"{max(1, round(self.total_vram_mb / 8192)) * 8}GiB"

    @property
    def profile_key(self) -> str:
        return f"{self.device_class}|{self.vram_class}|cc{self.compute_capability}|mig={self.mig_profile or 'none'}"

    @classmethod
    def from_gpu_query(cls, name: str, total_vram_mb: int, compute_capability: str = "", mig_profile: str = "") -> DeviceProfile:
        """Build a profile from a runtime query, splitting a vendor-qualified name."""
        vendor = "nvidia"
        lowered = name.lower()
        for candidate in ("nvidia", "amd", "intel", "apple"):
            if candidate in lowered:
                vendor = candidate
                break
        return cls(
            vendor=vendor,
            model=name.strip() or "unknown",
            compute_capability=compute_capability.strip(),
            total_vram_mb=int(total_vram_mb),
            mig_profile=mig_profile,
        )


# ---------------------------------------------------------------------------
# Workload and observation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkloadFeatures:
    """The low-dimensional description a prediction is keyed on."""

    runner: str
    model_revision: str
    runtime_fingerprint: str
    sequence_length: int
    sequence_count: int = 1
    batch_size: int = 1
    sample_count: int = 1
    parameters: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.runner or not self.model_revision or not self.runtime_fingerprint:
            raise ResourceModelError("WorkloadFeatures requires runner, model_revision, and runtime_fingerprint")
        for name in ("sequence_length", "sequence_count", "batch_size", "sample_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or value < 1:
                raise ResourceModelError(f"WorkloadFeatures {name} must be a positive integer")

    def vector(self) -> np.ndarray:
        """Feature vector for the shared workload model."""
        return np.array(
            [
                1.0,
                math.log(self.sequence_length),
                math.log(self.sequence_count),
                math.log(self.batch_size),
                math.log(self.sample_count),
                math.log(self.sequence_length) ** 2,
            ],
            dtype=np.float64,
        )

    @property
    def scale(self) -> float:
        """A monotone size proxy used for envelope and neighbour checks."""
        return float(self.sequence_length * self.batch_size * self.sample_count * self.sequence_count)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> WorkloadFeatures:
        params = payload.get("parameters") or {}
        return cls(
            runner=str(payload["runner"]),
            model_revision=str(payload["model_revision"]),
            runtime_fingerprint=str(payload["runtime_fingerprint"]),
            sequence_length=int(payload["sequence_length"]),
            sequence_count=int(payload.get("sequence_count", 1)),
            batch_size=int(payload.get("batch_size", 1)),
            sample_count=int(payload.get("sample_count", 1)),
            parameters={str(k): float(v) for k, v in params.items()},
        )


def _model_group(features: WorkloadFeatures) -> str:
    """The estimator's grouping key: one runner/model pair.

    Shared workload behaviour is shared across *devices*, not across unrelated
    runners, so coefficients are fitted per group with the global fit as the
    cold-start fallback for a runner/model with too little evidence of its own.
    """
    return f"{features.runner}|{features.model_revision}"


@dataclass(frozen=True)
class ResourceObservation:
    """One normalized execution observation (the only thing a runner reports).

    ``baseline_mb`` is the memory resident after runtime/model initialization and
    before the workload ran; ``peak_*`` is the maximum during the workload. The
    pair is what lets the estimator factor residency from growth. ``available_mb``
    is the free device memory measured *before* the workload ran: recorded on an
    OOM so the row is usable as a censored constraint, and on success so a device
    that could not have satisfied the workload from its own free memory is
    recognized as having been occupied by another process.
    """

    runner: str
    model_revision: str
    runtime_fingerprint: str
    device: DeviceProfile
    features: WorkloadFeatures
    outcome: str
    baseline_mb: int
    peak_allocated_mb: int = 0
    peak_reserved_mb: int = 0
    peak_process_mb: int = 0
    available_mb: int = 0
    quality: str = QUALITY_VALID
    error_class: str = ""
    runtime_seconds: float = 0.0
    created_at: float = 0.0
    plan_label: str = ""
    note: str = ""

    def __post_init__(self) -> None:
        if self.outcome not in {OUTCOME_SUCCESS, OUTCOME_OOM, OUTCOME_ERROR}:
            raise ResourceModelError(f"Unknown observation outcome {self.outcome!r}")
        if self.quality not in QUALITIES:
            raise ResourceModelError(f"Unknown observation quality {self.quality!r}")
        for name in ("baseline_mb", "peak_allocated_mb", "peak_reserved_mb", "peak_process_mb", "available_mb"):
            if isinstance(getattr(self, name), bool) or getattr(self, name) < 0:
                raise ResourceModelError(f"Observation {name} must be a non-negative integer")

    @property
    def peak_mb(self) -> int:
        """The measured peak this row contributes: process peak when known."""
        return max(self.peak_process_mb, self.peak_reserved_mb, self.peak_allocated_mb, self.baseline_mb)

    @property
    def incremental_mb(self) -> int:
        return max(0, self.peak_mb - self.baseline_mb)

    @property
    def effective_quality(self) -> str:
        """Interference wins over a reporter's optimistic label.

        ``available_mb`` is the free memory at the start of the run, so a
        successful run whose incremental demand exceeds it could not have been
        satisfied by a device holding only that much: another process was
        holding memory, and the row is diagnostic only — training on it would
        teach "this workload needs more VRAM". A row with unknown
        (zero/unreported) availability stays ``valid``; a large legitimate run
        on an idle device is never demoted.
        """
        if self.outcome == OUTCOME_SUCCESS and self.available_mb and self.incremental_mb > self.available_mb:
            return QUALITY_INTERFERENCE
        return self.quality

    def to_dict(self) -> dict[str, Any]:
        return {
            "runner": self.runner,
            "model_revision": self.model_revision,
            "runtime_fingerprint": self.runtime_fingerprint,
            "device": asdict(self.device),
            "features": {
                **{k: v for k, v in asdict(self.features).items() if k != "parameters"},
                "parameters": dict(self.features.parameters),
            },
            "outcome": self.outcome,
            "baseline_mb": self.baseline_mb,
            "peak_allocated_mb": self.peak_allocated_mb,
            "peak_reserved_mb": self.peak_reserved_mb,
            "peak_process_mb": self.peak_process_mb,
            "available_mb": self.available_mb,
            "quality": self.quality,
            "error_class": self.error_class,
            "runtime_seconds": self.runtime_seconds,
            "created_at": self.created_at,
            "plan_label": self.plan_label,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ResourceObservation:
        return cls(
            runner=str(payload["runner"]),
            model_revision=str(payload["model_revision"]),
            runtime_fingerprint=str(payload["runtime_fingerprint"]),
            device=DeviceProfile(**payload["device"]),
            features=WorkloadFeatures.from_mapping(payload["features"]),
            outcome=str(payload["outcome"]),
            baseline_mb=int(payload.get("baseline_mb", 0)),
            peak_allocated_mb=int(payload.get("peak_allocated_mb", 0)),
            peak_reserved_mb=int(payload.get("peak_reserved_mb", 0)),
            peak_process_mb=int(payload.get("peak_process_mb", 0)),
            available_mb=int(payload.get("available_mb", 0)),
            quality=str(payload.get("quality", QUALITY_VALID)),
            error_class=str(payload.get("error_class", "")),
            runtime_seconds=float(payload.get("runtime_seconds", 0.0)),
            created_at=float(payload.get("created_at", 0.0)),
            plan_label=str(payload.get("plan_label", "")),
            note=str(payload.get("note", "")),
        )


# ---------------------------------------------------------------------------
# Prediction
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VramPrediction:
    """A prediction with the confidence context a planner needs."""

    expected_mb: int
    upper_bound_mb: int
    confidence: float
    applicable: bool
    source: str
    basis: Mapping[str, Any] = field(default_factory=dict)

    def fits(self, available_mb: int, *, margin: float = 1.0) -> bool:
        return self.upper_bound_mb * margin <= available_mb

    def explain(self) -> str:
        return (
            f"{self.source}: expected {self.expected_mb} MiB, upper bound {self.upper_bound_mb} MiB, "
            f"confidence {self.confidence:.2f}, applicable={self.applicable}"
        )


# ---------------------------------------------------------------------------
# Estimator
# ---------------------------------------------------------------------------


class VRAMEstimator:
    """``predicted_total = baseline + shared_workload + device_correction``.

    All fitting is ordinary least squares on a handful of log features plus a
    per-device-class residual mean. The workload term is shared across device
    classes for one runner/model, falling back to the global fit when that
    runner/model has too little evidence to fit its own; the baseline and the
    residual are scoped the same way. It is CPU-only, has no training loop, and
    serializes to plain JSON so offline experimentation never forces a framework
    into the server runtime.
    """

    def __init__(self, observations: Iterable[ResourceObservation] = (), *, stage: str = "observe") -> None:
        if stage not in STAGES:
            raise ResourceModelError(f"Unknown rollout stage {stage!r}")
        self.stage = stage
        self._rows: list[ResourceObservation] = []
        self._coefficients: np.ndarray | None = None
        self._coefficients_by_group: dict[str, np.ndarray] = {}
        self._baselines: dict[str, float] = {}
        self._residuals: dict[str, float] = {}
        self._observed_scale: dict[str, float] = {}
        for observation in observations:
            self.observe(observation)

    # -- ingest -------------------------------------------------------------

    @property
    def observations(self) -> Sequence[ResourceObservation]:
        return tuple(self._rows)

    def observe(self, observation: ResourceObservation) -> None:
        """Record one observation and refit. Contaminated rows stay diagnostic.

        Refitting is O(n) in the row count and only happens on ingest, which is
        once per work item — negligible beside structure prediction.
        """
        self._rows.append(observation)
        self._refit()

    def _training_rows(self, *, fingerprint: str | None = None) -> list[tuple[ResourceObservation, float]]:
        rows: list[tuple[ResourceObservation, float]] = []
        for observation in self._rows:
            weight = _QUALITY_WEIGHT[observation.effective_quality]
            if weight <= 0 or observation.outcome != OUTCOME_SUCCESS:
                continue
            if fingerprint is not None and observation.runtime_fingerprint != fingerprint:
                # A materially changed runtime demotes old rows to a weaker
                # prior instead of discarding them: fingerprint mismatches are
                # still evidence, just not equally authoritative.
                weight *= 0.1
            rows.append((observation, weight))
        return rows

    def _refit(self) -> None:
        baselines: dict[str, list[float]] = {}
        for observation in self._rows:
            weight = _QUALITY_WEIGHT[observation.effective_quality]
            if weight <= 0 or observation.outcome != OUTCOME_SUCCESS:
                continue
            baselines.setdefault(_model_group(observation.features), []).append(float(observation.baseline_mb))
        self._baselines = {key: float(np.median(values)) for key, values in baselines.items()}

        rows = self._training_rows()
        self._coefficients = self._fit(rows)
        # A runner/model group is fitted on its own rows so an unrelated
        # runner's evidence cannot move its prediction; a group below the
        # fitting floor keeps no entry and predicts from the global cold-start
        # fit instead.
        self._coefficients_by_group = {}
        groups: dict[str, list[tuple[ResourceObservation, float]]] = {}
        for row, weight in rows:
            groups.setdefault(_model_group(row.features), []).append((row, weight))
        for key, group_rows in groups.items():
            coefficients = self._fit(group_rows)
            if coefficients is not None:
                self._coefficients_by_group[key] = coefficients
        self._residuals = self._derive_residuals(rows)
        scales: dict[str, float] = {}
        for row, _ in rows:
            key = self._profile_bucket(row.features, row.device)
            scales[key] = max(scales.get(key, 0.0), row.features.scale)
        self._observed_scale = scales

    @staticmethod
    def _fit(rows: Sequence[tuple[ResourceObservation, float]]) -> np.ndarray | None:
        if len(rows) < 3:
            return None
        design = np.vstack([row.features.vector() for row, _ in rows])
        target = np.array([float(row.incremental_mb) for row, _ in rows], dtype=np.float64)
        weights = np.array([weight for _, weight in rows], dtype=np.float64)
        design_w = design * weights[:, None]
        target_w = target * weights
        ridge = np.eye(design.shape[1]) * RIDGE * float(np.mean(design_w**2) + 1.0)
        ridge[0, 0] = 0.0
        try:
            return np.linalg.lstsq(design_w.T @ design_w + ridge, design_w.T @ target_w, rcond=None)[0]
        except np.linalg.LinAlgError:
            return None

    def _derive_residuals(self, rows: Sequence[tuple[ResourceObservation, float]]) -> dict[str, float]:
        """Residual per device class *within* one runner/model group.

        The coefficient used is the group's own fit, so two runners sharing a
        device class never leak their residual into each other; a row whose
        group has no fit falls back to the global coefficients like its
        prediction does.
        """
        grouped: dict[str, list[float]] = {}
        for row, _ in rows:
            coefficients = self._coefficients_by_group.get(_model_group(row.features), self._coefficients)
            if coefficients is None:
                continue
            fitted = float(row.features.vector() @ coefficients)
            key = f"{_model_group(row.features)}|{row.device.device_class}"
            grouped.setdefault(key, []).append(float(row.incremental_mb) - fitted)
        return {key: float(np.median(values)) for key, values in grouped.items()}

    @staticmethod
    def _profile_bucket(features: WorkloadFeatures, device: DeviceProfile) -> str:
        return f"{_model_group(features)}|{device.device_class}"

    def _observed_max(self, features: WorkloadFeatures, device: DeviceProfile) -> tuple[float, str]:
        """Largest observed workload scale for this request, and where it came from.

        The profile bucket is device-class specific. When the requested class is
        unobserved, the largest scale across the whole runner/model group is the
        shared-domain envelope, so a new device class of a known runner is
        bounded by what that runner was seen to do. Zero means nothing was ever
        observed for this runner/model and no envelope exists.
        """
        bucket = self._profile_bucket(features, device)
        if bucket in self._observed_scale:
            return self._observed_scale[bucket], device.device_class
        prefix = f"{_model_group(features)}|"
        group_max = max((scale for key, scale in self._observed_scale.items() if key.startswith(prefix)), default=0.0)
        return group_max, "runner_shared"

    def _coefficients_for(self, features: WorkloadFeatures) -> np.ndarray | None:
        """The group fit when the group has one, else the global cold-start fit."""
        return self._coefficients_by_group.get(_model_group(features), self._coefficients)

    # -- inference ----------------------------------------------------------

    def predict(
        self,
        features: WorkloadFeatures,
        device: DeviceProfile,
        *,
        runtime_fingerprint: str | None = None,
    ) -> VramPrediction:
        """Estimate peak VRAM, or say ``applicable=False`` when extrapolating.

        Applicability and confidence come only from rows that match both the
        request's runtime fingerprint and its runner/model group; mismatched
        rows stay in the fit as a weaker prior, so a materially changed runtime
        demotes the history instead of hiding it, and an unrelated runner's
        evidence cannot vouch for a prediction. Unknown and out-of-envelope
        requests are refused rather than guessed at.
        """
        fingerprint = runtime_fingerprint or features.runtime_fingerprint
        group = _model_group(features)
        rows = self._training_rows(fingerprint=fingerprint)
        group_rows = [row for row, _ in rows if _model_group(row.features) == group]
        matched = sum(1 for row in group_rows if row.runtime_fingerprint == fingerprint)
        basis: dict[str, Any] = {
            "observations": len(group_rows),
            "matching_observations": matched,
            "device_class": device.device_class,
        }
        if not rows:
            return VramPrediction(-1, -1, 0.0, False, "no_observations", basis)
        if not group_rows:
            # Every usable row belongs to another runner/model: the shared fit
            # could be consulted, but nothing here vouches for this request's
            # residency, envelope, or runtime, so no value is published.
            return VramPrediction(-1, -1, 0.0, False, "no_observations", basis)

        baseline = self._baselines.get(group)
        if baseline is None:
            return VramPrediction(-1, -1, 0.0, False, "unknown_model_revision", basis)

        scale = features.scale
        observed_max, scope = self._observed_max(features, device)
        basis["observed_max_scale"] = observed_max
        # No envelope at all (zero) also fails this: any real workload is above it.
        if scale > observed_max * EXTRAPOLATION_FACTOR:
            basis["observed_scope"] = scope
            return VramPrediction(-1, -1, 0.0, False, "extrapolation", basis)

        coefficients = self._coefficients_for(features)
        if coefficients is None:
            # Too few rows to fit growth: use the observed maximum increment for
            # this runner on any device class as a conservative heuristic.
            increments = [float(row.incremental_mb) for row, _ in rows]
            expected = baseline + float(np.median(increments))
            upper = baseline + float(np.max(increments))
            return VramPrediction(
                int(expected), int(upper), 0.3, False, "heuristic_median", {**basis, "rows": len(increments)}
            )

        shared = float(features.vector() @ coefficients)
        correction = self._residuals.get(f"{group}|{device.device_class}", 0.0)
        residual_spread = [
            float(row.incremental_mb) - float(row.features.vector() @ self._coefficients_for(row.features))
            for row, _ in rows
            if self._coefficients_for(row.features) is not None
        ]
        spread = float(np.percentile(np.abs(residual_spread), 90)) if residual_spread else 0.0
        expected = max(0.0, baseline + shared + correction)
        # Conservative upper bound: the expected value plus the learned spread,
        # and never below the largest increment ever observed for this workload
        # shape family within the same runner/model group.
        upper = expected + spread
        same_shape = [float(row.incremental_mb) for row, _ in rows if _model_group(row.features) == group]
        if same_shape:
            upper = max(upper, baseline + float(np.max(same_shape)))
        confidence = min(1.0, matched / (MIN_OBSERVATIONS * 4.0))
        applicable = matched >= MIN_OBSERVATIONS
        basis.update({"shared_mb": round(shared, 1), "correction_mb": round(correction, 1), "baseline_mb": round(baseline, 1)})
        return VramPrediction(int(expected), int(upper), confidence, applicable, "fitted", basis)

    # -- known-failure memory ----------------------------------------------

    def known_failure_envelope(self, features: WorkloadFeatures, device: DeviceProfile) -> int | None:
        """Smallest observed OOM workload scale for this profile, if any.

        Returns ``None`` when no OOM has been attributed to this runner/model on
        this device class. The planner uses it to skip a configuration already
        established as unsafe rather than deliberately reproducing it.
        """
        scales = [
            observation.features.scale
            for observation in self._rows
            if observation.outcome == OUTCOME_OOM
            and observation.features.runner == features.runner
            and observation.features.model_revision == features.model_revision
            and observation.device.device_class == device.device_class
        ]
        return int(min(scales)) if scales else None

    # -- persistence --------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "stage": self.stage,
            "coefficients": None if self._coefficients is None else [float(v) for v in self._coefficients],
            "baselines": dict(self._baselines),
            "residuals": dict(self._residuals),
            "observations": [observation.to_dict() for observation in self._rows],
        }

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(self.to_dict(), handle, ensure_ascii=True, indent=2, sort_keys=True)
            handle.write("\n")

    @classmethod
    def load(cls, path: str) -> VRAMEstimator:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise ResourceModelError("Unsupported resource-model state version")
        estimator = cls(
            (ResourceObservation.from_dict(row) for row in payload.get("observations", [])),
            stage=str(payload.get("stage", "observe")),
        )
        return estimator


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FallbackPlan:
    """One runner-declared, semantics-preserving lower-memory configuration."""

    label: str
    adjustments: Mapping[str, Any]
    title: str = ""

    def __post_init__(self) -> None:
        if not self.label or not self.adjustments:
            raise ResourceModelError("FallbackPlan requires a label and adjustments")
        unknown = set(self.adjustments) - ADAPTATION_KEYS
        if unknown:
            raise ResourceModelError(
                f"FallbackPlan {self.label!r} changes non-resource parameter(s): {sorted(unknown)}"
            )

    @classmethod
    def parse_all(cls, raw: Any) -> tuple[FallbackPlan, ...]:
        if raw is None:
            return ()
        if not isinstance(raw, list):
            raise ResourceModelError("resource_adaptation.fallback_plans must be a list")
        plans: list[FallbackPlan] = []
        for entry in raw:
            if not isinstance(entry, Mapping) or set(entry) - _PLAN_KEYS:
                raise ResourceModelError("FallbackPlan has unknown fields")
            adjustments = entry.get("adjustments")
            if not isinstance(adjustments, Mapping):
                raise ResourceModelError("FallbackPlan adjustments must be a mapping")
            plans.append(
                cls(label=str(entry.get("label", "")), title=str(entry.get("title", "")), adjustments=dict(adjustments))
            )
        if len({plan.label for plan in plans}) != len(plans):
            raise ResourceModelError("FallbackPlan labels must be unique")
        return tuple(plans)


@dataclass(frozen=True)
class PlannerDecision:
    """Why a plan was allowed, adapted, or rejected — traceable by construction."""

    action: str  # "allow" | "adapt" | "reject"
    plan_label: str
    adjustments: Mapping[str, Any]
    reason: str
    prediction: VramPrediction | None = None

    @property
    def allowed(self) -> bool:
        return self.action != "reject"

    @property
    def label(self) -> str:
        return self.plan_label

    def explain(self) -> str:
        detail = f" [{self.prediction.explain()}]" if self.prediction is not None else ""
        return f"{self.action} {self.plan_label or 'default'}: {self.reason}{detail}"


class ResourcePlanner:
    """Chooses among runner-declared plans; never invents an adaptation.

    The estimator predicts; this decides. It holds no runner-name knowledge:
    ``fallback_plans`` comes from the owning manifest.
    """

    def __init__(
        self,
        estimator: VRAMEstimator,
        fallback_plans: Sequence[FallbackPlan] = (),
        *,
        stage: str = "observe",
        safety_margin: float = 1.1,
    ) -> None:
        if stage not in STAGES:
            raise ResourceModelError(f"Unknown rollout stage {stage!r}")
        self.estimator = estimator
        self.fallback_plans = tuple(fallback_plans)
        self.stage = stage
        self.safety_margin = safety_margin

    def skipped_plans(
        self,
        features: WorkloadFeatures,
        device: DeviceProfile,
        available_mb: int,
    ) -> tuple[str, ...]:
        """Plans already established as unsafe for this profile (``avoid`` stage).

        Only the boundary is known: the profile has an OOM below this workload's
        scale, so the default path and every fallback share that region and the
        runner starts at the first unfailed plan. Retention is all-or-nothing
        because the estimator does not model how a specific adjustment shrinks
        the workload. ``available_mb`` is accepted for interface stability with
        :meth:`decide` and deliberately unused beyond the known-positive check.
        """
        if self.stage != "avoid" or available_mb <= 0:
            return ()
        envelope = self.estimator.known_failure_envelope(features, device)
        if envelope is None or features.scale < envelope:
            return ()
        return ("", *(plan.label for plan in self.fallback_plans))

    def decide(
        self,
        features: WorkloadFeatures,
        device: DeviceProfile,
        available_mb: int,
        *,
        attempt: int = 0,
        failed_plans: Sequence[str] = (),
    ) -> PlannerDecision:
        """Pick the plan for the next attempt.

        ``attempt == 0`` is the default path. In ``observe`` it is always the
        default, unchanged, whatever the estimator believes — the normal
        execution path stays authoritative. Later attempts walk the runner's
        declared fallbacks in order and never exceed the bounded budget.
        """
        default = PlannerDecision("allow", "", {}, "default execution path")
        if attempt == 0:
            if self.stage == "avoid":
                skipped = self.skipped_plans(features, device, available_mb)
                if "" in skipped:
                    replacement = self._first_unfailed(failed_plans)
                    if replacement is not None:
                        return PlannerDecision(
                            "adapt",
                            replacement.label,
                            replacement.adjustments,
                            "known OOM region for this profile; avoiding the default",
                        )
            return default
        if self.stage == "observe":
            return PlannerDecision("reject", "", {}, "observation-only rollout; no adaptation attempted")

        if attempt > len(self.fallback_plans):
            # Bounded: the budget is the runner's declared plan count, so a
            # caller that forgets to record a failure still cannot loop.
            return PlannerDecision(
                "reject", "", {}, "retry budget exhausted; item is FAILED_RESOURCE"
            )
        plan = self._first_unfailed(failed_plans)
        if plan is None:
            return PlannerDecision(
                "reject", "", {}, "all runner-declared fallbacks exhausted; item is FAILED_RESOURCE"
            )
        prediction = self._predict(features, device)
        if prediction is not None and available_mb > 0 and prediction.applicable and not prediction.fits(
            available_mb, margin=self.safety_margin
        ):
            # The prediction says even the fallback is too large; nothing safer
            # exists, so report the rejection with its basis rather than looping.
            return PlannerDecision(
                "reject", plan.label, plan.adjustments, "conservative bound still exceeds available VRAM", prediction
            )
        reason = "bounded OOM recovery"
        if prediction is not None and not prediction.applicable:
            reason = "bounded OOM recovery using conservative heuristics (prediction not applicable)"
        return PlannerDecision("adapt", plan.label, plan.adjustments, reason, prediction)

    def _predict(self, features: WorkloadFeatures, device: DeviceProfile) -> VramPrediction | None:
        try:
            return self.estimator.predict(features, device)
        except ResourceModelError:
            return None

    def _first_unfailed(self, failed_plans: Sequence[str]) -> FallbackPlan | None:
        return next((plan for plan in self.fallback_plans if plan.label not in failed_plans), None)


def guidance_for(
    plans: Sequence[FallbackPlan],
    observations: Iterable[ResourceObservation],
    *,
    stage: str = STAGES[0],
) -> dict[str, Any]:
    """Project learned evidence into the attempt guidance a runner enforces.

    The runner never imports this module, so the result is the *whole* interface
    between the server's model and the runner's execution: an attempt order, the
    plans already established as unsafe, and the workload scale at which the
    default path is skipped. Everything not derivable from stored evidence stays
    empty, and a runner that ignores the block behaves exactly as before.

    A plan is treated as known-failing only on one-sided evidence — it has an
    OOM row for this profile and no success row — because "established unsafe"
    is exactly that, while a plan that has also succeeded is uncertain. Nothing
    is published until the profile has :data:`MIN_OBSERVATIONS` usable successes,
    since below that the evidence cannot speak for the profile at all. OOM rows
    are censored constraints, so even one of them is a real boundary; the scale
    threshold lets the runner apply it per work item, which is the only place
    the item's size is known.
    """
    if stage not in STAGES:
        stage = STAGES[0]
    guidance: dict[str, Any] = {
        "stage": stage,
        "plan_order": ["", *(plan.label for plan in plans)],
        "known_failing_plans": [],
        "avoid_scale_at_or_above": None,
    }
    if stage != "avoid":
        return guidance

    rows = [row for row in observations if isinstance(row, ResourceObservation)]
    successes = sum(
        1 for row in rows if row.outcome == OUTCOME_SUCCESS and row.effective_quality != QUALITY_INTERFERENCE
    )
    if successes < MIN_OBSERVATIONS:
        return guidance
    oom_labels = {row.plan_label for row in rows if row.outcome == OUTCOME_OOM}
    safe_labels = {row.plan_label for row in rows if row.outcome == OUTCOME_SUCCESS}
    guidance["known_failing_plans"] = sorted(oom_labels - safe_labels)
    scales = [row.features.scale for row in rows if row.outcome == OUTCOME_OOM]
    if scales:
        guidance["avoid_scale_at_or_above"] = int(min(scales))
    return guidance


def _self_check() -> None:
    """Smallest runnable check: fit, predict, censor, and bound a fallback."""
    device = DeviceProfile("nvidia", "A100-PCIE-40GB", "8.0", 40960)
    other = DeviceProfile("nvidia", "H100-PCIE-80GB", "9.0", 81559)
    rows = []
    for length, peak in ((100, 14000), (300, 18000), (600, 26000), (1200, 44000)):
        features = WorkloadFeatures("esmfold2", "fast", "fp-1", length)
        rows.append(
            ResourceObservation(
                runner="esmfold2",
                model_revision="fast",
                runtime_fingerprint="fp-1",
                device=device,
                features=features,
                outcome=OUTCOME_SUCCESS,
                baseline_mb=8000,
                peak_reserved_mb=peak,
            )
        )
    estimator = VRAMEstimator(rows)
    prediction = estimator.predict(WorkloadFeatures("esmfold2", "fast", "fp-1", 900), device)
    assert prediction.applicable and prediction.expected_mb > 0, prediction.explain()
    assert prediction.upper_bound_mb >= prediction.expected_mb
    # A new device class starts from the shared model, not from zero.
    shared = estimator.predict(WorkloadFeatures("esmfold2", "fast", "fp-1", 900), other)
    assert shared.applicable and shared.expected_mb > 0, shared.explain()
    # Out-of-distribution asks are refused rather than extrapolated.
    assert not estimator.predict(WorkloadFeatures("esmfold2", "fast", "fp-1", 100_000), device).applicable
    # A device class with no same-runner evidence at all is refused, not guessed.
    assert not estimator.predict(WorkloadFeatures("otherfold", "fast", "fp-1", 100_000), device).applicable
    unseen = DeviceProfile("amd", "MI300", "9.0", 192000)
    assert estimator.predict(WorkloadFeatures("esmfold2", "fast", "fp-1", 900), unseen).applicable
    # A changed runtime demotes old rows to a weaker prior instead of hiding
    # them, and cannot confer applicability: the mismatched ask is not trusted.
    demoted = estimator.predict(WorkloadFeatures("esmfold2", "fast", "fp-2", 900), device)
    assert not demoted.applicable and demoted.confidence < prediction.confidence, demoted.explain()
    # Evidence from an unrelated runner/model cannot move this runner's answer.
    foreign = [
        ResourceObservation(
            runner="other",
            model_revision="slow",
            runtime_fingerprint="fp-1",
            device=device,
            features=WorkloadFeatures("other", "slow", "fp-1", length),
            outcome=OUTCOME_SUCCESS,
            baseline_mb=40000,
            peak_reserved_mb=90000,
        )
        for length in (100, 300, 600, 1200, 100, 300, 600, 1200, 100, 300)
    ]
    blended = VRAMEstimator([*rows, *foreign]).predict(WorkloadFeatures("esmfold2", "fast", "fp-1", 900), device)
    assert abs(blended.expected_mb - prediction.expected_mb) < 2000, blended.explain()
    # Confirmed device names reduce to one class per family.
    assert DeviceProfile("nvidia", "NVIDIA H100 PCIe", "9.0", 81559).device_class == DeviceProfile(
        "nvidia", "NVIDIA H100 NVL", "9.0", 94200
    ).device_class

    plans = FallbackPlan.parse_all(
        [{"label": "split", "adjustments": {"sample_group_size": 1}}, {"label": "offload", "adjustments": {"cpu_offload": True}}]
    )
    planner = ResourcePlanner(estimator, plans, stage="recover")
    assert planner.decide(WorkloadFeatures("esmfold2", "fast", "fp-1", 100_000), device, 40000).action == "allow"
    assert planner.decide(WorkloadFeatures("esmfold2", "fast", "fp-1", 100_000), device, 40000, attempt=1).plan_label == "split"
    second = planner.decide(WorkloadFeatures("esmfold2", "fast", "fp-1", 100_000), device, 40000, attempt=2, failed_plans=("split",))
    assert second.plan_label == "offload", second.explain()
    exhausted = planner.decide(WorkloadFeatures("esmfold2", "fast", "fp-1", 100), device, 40000, attempt=3, failed_plans=("split", "offload"))
    assert exhausted.action == "reject" and not exhausted.allowed, exhausted.explain()

    # A fallback may not silently change science.
    try:
        FallbackPlan.parse_all([{"label": "bad", "adjustments": {"num_samples": 2}}])
    except ResourceModelError:
        pass
    else:  # pragma: no cover - regression guard
        raise AssertionError("scientific parameter adaptation must be rejected")

    # Interference is recognized from device availability, not learned as demand.
    noisy = ResourceObservation(
        runner="esmfold2",
        model_revision="fast",
        runtime_fingerprint="fp-1",
        device=device,
        features=WorkloadFeatures("esmfold2", "fast", "fp-1", 900),
        outcome=OUTCOME_SUCCESS,
        baseline_mb=8000,
        peak_reserved_mb=39000,
        available_mb=20000,
    )
    assert noisy.effective_quality == QUALITY_INTERFERENCE
    assert not VRAMEstimator([noisy]).predict(WorkloadFeatures("esmfold2", "fast", "fp-1", 900), device).applicable

    # Guidance is the whole runner interface: observe publishes nothing, avoid
    # publishes the boundary the runner applies per work item.
    observing = guidance_for(plans, rows, stage="observe")
    assert observing["plan_order"] == ["", "split", "offload"]
    assert observing["known_failing_plans"] == [] and observing["avoid_scale_at_or_above"] is None
    censored = ResourceObservation(
        runner="esmfold2",
        model_revision="fast",
        runtime_fingerprint="fp-1",
        device=device,
        features=WorkloadFeatures("esmfold2", "fast", "fp-1", 1500),
        outcome=OUTCOME_OOM,
        baseline_mb=8000,
        peak_reserved_mb=44000,
        available_mb=40960,
    )
    avoiding = guidance_for(plans, [*rows, censored], stage="avoid")
    # The default plan also succeeded at smaller scales, so it is not
    # established as failing — the boundary belongs to the scale threshold.
    assert avoiding["known_failing_plans"] == []
    assert avoiding["avoid_scale_at_or_above"] == 1500
    never_succeeded = ResourceObservation(
        runner="esmfold2",
        model_revision="fast",
        runtime_fingerprint="fp-1",
        device=device,
        features=WorkloadFeatures("esmfold2", "fast", "fp-1", 900),
        outcome=OUTCOME_OOM,
        baseline_mb=8000,
        peak_reserved_mb=44000,
        available_mb=20000,
        plan_label="split",
    )
    failing = guidance_for(plans, [*rows, never_succeeded], stage="avoid")
    assert failing["known_failing_plans"] == ["split"], failing
    assert failing["avoid_scale_at_or_above"] == 900
    assert guidance_for(plans, rows, stage="avoid")["avoid_scale_at_or_above"] is None

    # A prediction that fits the free memory neither rejects nor adapts away
    # from the plan; one that cannot fit even at the last fallback is refused
    # with the bound as its reason.
    forgiving = ResourcePlanner(estimator, plans, stage="recover")
    fits = forgiving.decide(WorkloadFeatures("esmfold2", "fast", "fp-1", 900), device, 1_000_000, attempt=1)
    assert fits.action == "adapt" and fits.plan_label == "split", fits.explain()
    too_small = forgiving.decide(WorkloadFeatures("esmfold2", "fast", "fp-1", 900), device, 12000, attempt=1)
    assert too_small.action == "reject" and "exceeds available VRAM" in too_small.reason, too_small.explain()


if __name__ == "__main__":  # pragma: no cover - runnable self-check
    _self_check()
    print("resource_model self-check passed")
