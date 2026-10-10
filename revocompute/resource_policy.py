# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Typed resource policy shared by admin configuration and job launchers."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from revocompute.resource_ledger import resource_class_for_gres


class ResourceValidationError(ValueError):
    """A resource setting cannot be represented safely or consistently."""


class QueueResolutionError(ResourceValidationError):
    """The resolved partition is not one of this deployment's queues.

    A typed subclass rather than a message a caller has to recognise: the
    placement layer reports a bounded reason code for a refusal, and classifying
    one by matching text would make the code depend on wording that is free to
    change.  The type is the contract; the message is for a human.
    """


class AcceleratorClassUnavailableError(ResourceValidationError):
    """Accelerator work has no execution class on this deployment.

    Same reasoning as :class:`QueueResolutionError`: it is the *kind* of refusal
    that determines whether the bounded reason is a queue problem or an
    accelerator problem, so the kind is carried by the type.
    """


class ExecutionClassMismatchError(ResourceValidationError):
    """The partition the request names is not the class that work belongs to.

    A third kind, because the refusal is neither "that queue does not exist" nor
    "this deployment has no accelerator class": both sides are configured and they
    disagree, which is the case an operator must fix by changing one of them.
    """


_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_CONSTRAINT_RE = re.compile(r"^(?!-)[A-Za-z0-9_.&|*+!()\[\]-]{1,256}$")
_MEMORY_RE = re.compile(r"^[1-9][0-9]*(?:[KMGTP])?$", re.IGNORECASE)
_TIME_RE = re.compile(r"^(?:[0-9]+-)?(?:[0-9]{1,2}):[0-5][0-9]:[0-5][0-9]$")
_GRES_RE = re.compile(r"^gpu:(?:(?:[A-Za-z][A-Za-z0-9_.-]*):)?[1-9][0-9]*$")
#: One entry of an execution-class declaration: ``cpu=normal``, ``a100=gpu``.
_CLASS_ENTRY_RE = re.compile(r"^(?P<key>[A-Za-z][A-Za-z0-9_.-]{0,63})=(?P<queue>[A-Za-z0-9][A-Za-z0-9_.-]{0,63})$")
_BOOL_TRUE = {"true", "1", "yes", "on"}
_BOOL_FALSE = {"false", "0", "no", "off"}

CANONICAL_TASK_FIELDS = (
    "enabled",
    "cpus",
    "memory",
    "max_runtime_seconds",
    "slurm_partition",
    "slurm_gres",
    "slurm_time",
    "slurm_nodes",
    "slurm_ntasks",
    "slurm_qos",
    "slurm_account",
    "slurm_constraint",
    "slurm_exclusive",
)

GLOBAL_RESOURCE_KEYS = {
    "cpus",
    "memory",
    "max_runtime_seconds",
    "slurm_partition",
    "slurm_gres",
    "slurm_time",
    "slurm_nodes",
    "slurm_ntasks",
    "slurm_qos",
    "slurm_account",
    "slurm_constraint",
    "slurm_exclusive",
    "slurm_enabled",
    "slurm_allowed_queues",
    "slurm_execution_classes",
}


def _positive_int(value: Any, field: str, maximum: int | None = None) -> int:
    if isinstance(value, bool):
        raise ResourceValidationError(f"{field} must be a positive integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ResourceValidationError(f"{field} must be a positive integer") from exc
    if str(value).strip() != str(result) or result < 1 or (maximum is not None and result > maximum):
        suffix = f" at most {maximum}" if maximum is not None else ""
        raise ResourceValidationError(f"{field} must be a positive integer{suffix}")
    return result


def _boolean(value: Any, field: str) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in _BOOL_TRUE:
        return True
    if normalized in _BOOL_FALSE:
        return False
    raise ResourceValidationError(f"{field} must be true or false")


def _name(value: Any, field: str) -> str:
    normalized = str(value).strip()
    if not _NAME_RE.fullmatch(normalized):
        raise ResourceValidationError(f"{field} contains unsupported characters")
    return normalized


def normalize_resource_value(field: str, value: Any) -> Any:
    """Validate and normalize one persisted task/global resource value."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if field == "cpus":
        return _positive_int(value, field, 1024)
    if field in {"slurm_nodes", "slurm_ntasks"}:
        return _positive_int(value, field, 128)
    if field in {"max_runtime_seconds"}:
        return _positive_int(value, field, 31 * 24 * 60 * 60)
    if field == "memory":
        normalized = str(value).strip().upper()
        if not _MEMORY_RE.fullmatch(normalized):
            raise ResourceValidationError(f"{field} must look like 4000M or 16G")
        return normalized
    if field == "slurm_time":
        normalized = str(value).strip()
        if not _TIME_RE.fullmatch(normalized):
            raise ResourceValidationError(f"{field} must use [days-]HH:MM:SS")
        return normalized
    if field == "slurm_gres":
        normalized = str(value).strip()
        if not _GRES_RE.fullmatch(normalized):
            raise ResourceValidationError(f"{field} must look like gpu:1 or gpu:a100:1")
        return normalized
    if field in {"enabled", "slurm_exclusive", "slurm_enabled"}:
        return _boolean(value, field)
    if field == "slurm_allowed_queues":
        values = value if isinstance(value, (list, tuple)) else str(value).split(",")
        normalized_values = []
        for item in values:
            if not isinstance(item, str):
                raise ResourceValidationError("slurm_allowed_queues entries must be strings")
            if item.strip():
                normalized_values.append(_name(item, "slurm_allowed_queues"))
        return tuple(dict.fromkeys(normalized_values))
    if field == "slurm_execution_classes":
        # Two accepted spellings, because this normalizer is applied both to a raw
        # admin value and to an already-normalized one: a string (or list of
        # strings) spells ``key=queue`` entries, and a sequence of ``(key, queue)``
        # pairs is the same value already parsed.  Normalizing is therefore
        # idempotent, which is what lets a reader and a writer share one function.
        if isinstance(value, (list, tuple)) and all(
            isinstance(item, (list, tuple)) and len(item) == 2 for item in value
        ):
            declared: list[tuple[str, str]] = []
            for key, queue in value:
                match = _CLASS_ENTRY_RE.fullmatch(f"{key}={queue}")
                if match is None:
                    raise ResourceValidationError(
                        "slurm_execution_classes entries must look like cpu=normal or a100=gpu"
                    )
                declared.append((match.group("key"), match.group("queue")))
            return tuple(dict.fromkeys(declared))
        entries = value if isinstance(value, (list, tuple)) else str(value).split(";")
        declared = []
        for item in entries:
            entry = item.strip() if isinstance(item, str) else None
            if not entry:
                continue
            match = _CLASS_ENTRY_RE.fullmatch(entry)
            if match is None:
                raise ResourceValidationError(
                    "slurm_execution_classes entries must look like cpu=normal or a100=gpu"
                )
            declared.append((match.group("key"), match.group("queue")))
        return tuple(dict.fromkeys(declared))
    if field == "slurm_constraint":
        normalized = str(value).strip()
        if not _CONSTRAINT_RE.fullmatch(normalized):
            raise ResourceValidationError("slurm_constraint contains unsupported characters")
        return normalized
    if field in {"slurm_partition", "slurm_qos", "slurm_account"}:
        return _name(value, field)
    raise ResourceValidationError(f"Unknown resource field: {field}")


def serialize_resource_value(field: str, value: Any) -> str | None:
    """The persisted spelling of one already-normalized resource value.

    The exact inverse of :func:`normalize_resource_value`: reading back what this
    wrote yields the same value, so the configuration store has one spelling of a
    composite value rather than a reader and a writer that each invent their own.
    A tuple of ``(key, queue)`` pairs therefore serializes as ``cpu=normal;a100=gpu``
    — the form its reader parses — instead of the tuple's ``repr``, which no
    reader would accept.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if field == "slurm_execution_classes":
        return ";".join(f"{key}={queue}" for key, queue in value)
    if isinstance(value, tuple):
        return ",".join(value)
    return str(value)


def policy_revision_namespace(
    lookup_task: Callable[[str], Any],
    lookup_global: Callable[[str], Any],
) -> dict[str, Any]:
    """The policy values a decision read, in the form that produced it.

    Every key that can change a resolution is included, and each is put through
    :func:`normalize_resource_value` — the same function the resolver applies — so
    two spellings of one policy value produce one revision.  A digest over the raw
    stored strings would call ``"4"`` and ``4`` different policies, and a digest
    over an incomplete key set would report the same revision for two policies that
    resolve a stage differently, which is exactly the question a recorded decision
    has to answer months later.
    """
    return {
        "task": {
            key: normalize_resource_value(key, lookup_task(key))
            for key in sorted(CANONICAL_TASK_FIELDS)
        },
        "global": {
            key: normalize_resource_value(key, lookup_global(key))
            for key in sorted(GLOBAL_RESOURCE_KEYS)
        },
    }


def seconds_to_slurm_time(seconds: int) -> str:
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    value = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{days}-{value}" if days else value


def slurm_time_to_seconds(value: str) -> int:
    normalized = normalize_resource_value("slurm_time", value)
    days = 0
    clock = normalized
    if "-" in normalized:
        raw_days, clock = normalized.split("-", 1)
        days = int(raw_days)
    hours, minutes, seconds = (int(part) for part in clock.split(":"))
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


@dataclass(frozen=True)
class ResolvedResources:
    cpus: int
    memory: str
    max_runtime_seconds: int
    partition: str | None
    gres: str | None
    nodes: int
    ntasks: int
    qos: str | None
    account: str | None
    constraint: str | None
    exclusive: bool
    requires_gpu: bool
    sources: dict[str, str]

    @property
    def slurm_time(self) -> str:
        return seconds_to_slurm_time(self.max_runtime_seconds)

    def public_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["slurm_time"] = self.slurm_time
        payload.pop("sources", None)
        return payload

    @classmethod
    def from_snapshot(cls, payload: dict[str, Any]) -> ResolvedResources:
        """Validate a submission-time policy snapshot before job launch."""
        required = {"cpus", "memory", "max_runtime_seconds", "nodes", "ntasks", "requires_gpu"}
        missing = sorted(required - set(payload))
        if missing:
            raise ResourceValidationError(f"Resource snapshot is missing: {', '.join(missing)}")
        requires_gpu = _boolean(payload.get("requires_gpu", False), "requires_gpu")
        max_runtime = normalize_resource_value("max_runtime_seconds", payload.get("max_runtime_seconds"))
        declared_time = payload.get("slurm_time")
        if declared_time and slurm_time_to_seconds(str(declared_time)) != max_runtime:
            raise ResourceValidationError("Resource snapshot time fields are inconsistent")
        gres = normalize_resource_value("slurm_gres", payload.get("gres"))
        if requires_gpu and not gres:
            raise ResourceValidationError("GPU resource snapshot has no GRES")
        if not requires_gpu and gres:
            raise ResourceValidationError("CPU resource snapshot unexpectedly requests GPU GRES")
        return cls(
            cpus=normalize_resource_value("cpus", payload.get("cpus")),
            memory=normalize_resource_value("memory", payload.get("memory")),
            max_runtime_seconds=max_runtime,
            partition=normalize_resource_value("slurm_partition", payload.get("partition")),
            gres=gres,
            nodes=normalize_resource_value("slurm_nodes", payload.get("nodes")),
            ntasks=normalize_resource_value("slurm_ntasks", payload.get("ntasks")),
            qos=normalize_resource_value("slurm_qos", payload.get("qos")),
            account=normalize_resource_value("slurm_account", payload.get("account")),
            constraint=normalize_resource_value("slurm_constraint", payload.get("constraint")),
            exclusive=_boolean(payload.get("exclusive", False), "slurm_exclusive"),
            requires_gpu=requires_gpu,
            sources={"snapshot": "submission"},
        )


@dataclass(frozen=True, slots=True)
class ResourcePolicyValues:
    """Read-only persisted values exposed through the production resolver interface.

    The interface is the same one the admin configuration database presents, so a
    caller that plans a submission — the web submission path, deployment live
    acceptance — resolves through one protocol and never learns which process it
    runs in.
    """

    global_values: Mapping[str, Any]
    task_values: Mapping[str, Mapping[str, Any]]

    def resolve_task_resources(
        self,
        tool: str,
        *,
        requires_gpu: bool,
        default_timeout_seconds: int | None,
    ) -> ResolvedResources:
        task = self.task_values.get(tool, {})
        return resolve_resources(
            task.get,
            self.global_values.get,
            requires_gpu=requires_gpu,
            allowed_queues=self.slurm_allowed_queues(),
            default_timeout_seconds=default_timeout_seconds,
        )

    def task_type_get(self, tool: str) -> Mapping[str, Any]:
        return self.task_values.get(tool, {})

    def resource_all(self) -> Mapping[str, Any]:
        return self.global_values

    def slurm_allowed_queues(self) -> tuple[str, ...]:
        normalized = normalize_resource_value("slurm_allowed_queues", self.global_values.get("slurm_allowed_queues"))
        return tuple(normalized or ())


def resolve_resources(
    lookup_task: Callable[[str], Any],
    lookup_global: Callable[[str], Any],
    *,
    requires_gpu: bool,
    allowed_queues: list[str] | tuple[str, ...],
    default_timeout_seconds: int | None,
) -> ResolvedResources:
    """Resolve per-task, global, legacy, and safe defaults exactly once."""
    sources: dict[str, str] = {}

    def first(field: str, candidates: list[tuple[str, str]], default: Any) -> Any:
        for source, key in candidates:
            raw = lookup_task(key) if source == "task" else lookup_global(key)
            if raw is not None and str(raw).strip() != "":
                sources[field] = f"{source}:{key}"
                return normalize_resource_value(key, raw)
        sources[field] = "default"
        return default

    cpus = first("cpus", [("task", "cpus"), ("global", "cpus")], 1)
    memory = first("memory", [("task", "memory"), ("global", "memory")], "4G")

    configured_runtime = first(
        "max_runtime_seconds",
        [("task", "max_runtime_seconds"), ("global", "max_runtime_seconds")],
        default_timeout_seconds or 86400,
    )
    configured_time = first(
        "slurm_time",
        [("task", "slurm_time"), ("global", "slurm_time")],
        None,
    )
    if configured_time is not None:
        configured_runtime = min(configured_runtime, slurm_time_to_seconds(configured_time))
        sources["max_runtime_seconds"] += "+slurm_time"

    # The deployment's declared execution classes are the canonical mapping from a
    # semantic requirement to a local partition, and the deployment's own partition
    # vocabulary: what ``cpu=normal`` declares is *both* "CPU work goes to normal"
    # *and* "normal is a queue this deployment runs work on".  Reading them here,
    # once, is what keeps a class mapping and a queue allowlist from becoming two
    # vocabularies that can disagree.
    classes = normalize_resource_value("slurm_execution_classes", lookup_global("slurm_execution_classes")) or ()
    by_key = {key: queue for key, queue in classes}
    known_queues = tuple(dict.fromkeys((*allowed_queues, *(queue for _, queue in classes))))

    # The device class this deployment configures for accelerator work, read from
    # the configured GRES rather than from a second declaration: a requirement that
    # names ``a100`` and a configured ``gpu:a100:1`` are one statement about this
    # deployment, not two that must be kept in step.
    configured_gres = (
        first("gres", [("task", "slurm_gres"), ("global", "slurm_gres")], None) if requires_gpu else None
    )
    device_class = resource_class_for_gres(configured_gres) if configured_gres else ""

    # A resource class is the deployment's own statement about which local queue a
    # given kind of work belongs on, so it is the most specific partition statement
    # available: an explicit per-Task partition (an operator overriding one Task) is
    # more specific still, and the blanket global partition is less specific than
    # either.  Declaring no classes leaves the pre-existing resolution exactly as it
    # was, so a deployment that never used the feature cannot be reconfigured by it.
    class_key: str | None = None
    class_queue: str | None = None
    if classes:
        if not requires_gpu:
            class_key = "cpu"
        elif device_class:
            class_key = device_class
        else:
            # An accelerator request that names no device class belongs on an
            # accelerator class, never the CPU class, which holds no device at all.
            class_key = next((key for key, _queue in classes if key != "cpu"), None)
        class_queue = by_key.get(class_key) if class_key is not None else None

    partition = None
    requested_partition = lookup_task("slurm_partition")
    if requested_partition is not None and str(requested_partition).strip() != "":
        partition = normalize_resource_value("slurm_partition", requested_partition)
        sources["partition"] = "task:slurm_partition"
    elif class_queue is not None:
        partition = class_queue
        sources["partition"] = f"execution_class:{class_key}"
    else:
        # Slurm treats an absent partition as the cluster's default partition, which
        # is a host fact this deployment does not own and may not even have.  Naming
        # one of the deployment's own queues instead is what keeps a submission from
        # silently landing wherever the cluster's default happens to point today.
        configured_partition = lookup_global("slurm_partition")
        if configured_partition is not None and str(configured_partition).strip() != "":
            partition = normalize_resource_value("slurm_partition", configured_partition)
            sources["partition"] = "global:slurm_partition"
        elif known_queues:
            partition = known_queues[0]
            sources["partition"] = "allowed_queues:first"
    if partition is not None and known_queues and partition not in known_queues:
        raise QueueResolutionError(f"Partition {partition!r} is not in the configured allowed queue list")
    if requires_gpu and classes and class_queue is None:
        # The deployment declares execution classes and none of them is an
        # accelerator class: refusing here is what keeps accelerator work off a CPU
        # queue instead of letting the partition default decide.
        raise AcceleratorClassUnavailableError(
            "This deployment declares no accelerator execution class for accelerator work"
        )
    if requested_partition is not None and class_queue is not None and partition != class_queue:
        # The class the work belongs to and the partition the request insists on are
        # both explicit, and they disagree: refusing is the only answer that does not
        # silently place work somewhere other than what the deployment declared.
        raise ExecutionClassMismatchError(
            f"Partition {partition!r} is not this deployment's execution class for "
            f"{class_key} ({class_queue!r})"
        )

    gres = None
    if requires_gpu:
        # An accelerator request resolves to a concrete typed request: the one the
        # configuration names, else the class the requirement declared, else Slurm's
        # untyped device request.  Whether the resolved request is compatible with what
        # the stage declared is decided once, by the placement verifier, which owns
        # that reason vocabulary - resolution's job is only to route the request.
        fallback_gres = configured_gres or (f"gpu:{device_class}:1" if device_class else "gpu:1")
        gres = first("gres", [("task", "slurm_gres"), ("global", "slurm_gres")], fallback_gres)

    elif lookup_task("slurm_gres") not in {None, ""}:
        raise ResourceValidationError("CPU-only task has a per-task GPU GRES override")
    else:
        sources["gres"] = "not-required"

    return ResolvedResources(
        cpus=cpus,
        memory=memory,
        max_runtime_seconds=configured_runtime,
        partition=partition,
        gres=gres,
        nodes=first("nodes", [("task", "slurm_nodes"), ("global", "slurm_nodes")], 1),
        ntasks=first("ntasks", [("task", "slurm_ntasks"), ("global", "slurm_ntasks")], 1),
        qos=first("qos", [("task", "slurm_qos"), ("global", "slurm_qos")], None),
        account=first("account", [("task", "slurm_account"), ("global", "slurm_account")], None),
        constraint=first("constraint", [("task", "slurm_constraint"), ("global", "slurm_constraint")], None),
        exclusive=first("exclusive", [("task", "slurm_exclusive"), ("global", "slurm_exclusive")], False),
        requires_gpu=requires_gpu,
        sources=sources,
    )
