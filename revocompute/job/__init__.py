# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Abstract compute job interface.

Each runner backend (Docker, SLURM/Apptainer) implements the Job ABC so
``task_runtime.py`` can submit / poll / cancel without backend-specific
branching.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from dataclasses import dataclass, field
from collections.abc import Mapping, Sequence
from typing import Any


def _validate_workspace_path(value: str, field_name: str) -> None:
    """Reject paths that could escape the task workspace."""
    from pathlib import PurePosixPath

    path = PurePosixPath(value)
    if path.is_absolute() or not value or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"ExecutionPlan {field_name} contains unsafe path: {value!r}")


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    """Generic container execution contract produced by a task.

    Infrastructure adapters consume this object; it deliberately contains no
    scheduler or container-runtime behavior.
    """

    image: str
    command: tuple[str, ...]
    arguments: tuple[str, ...] = ()
    environment: Mapping[str, str] = field(default_factory=dict)
    mounts: tuple[Mapping[str, str], ...] = ()
    resources: Any = None
    outputs: tuple[str, ...] = ()
    workspace_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.image, str) or not self.image.strip():
            raise ValueError("ExecutionPlan image must be non-empty")
        if not self.command or any(not isinstance(part, str) or not part for part in self.command):
            raise ValueError("ExecutionPlan command must contain non-empty strings")
        sequence_fields = (
            ("arguments", self.arguments),
            ("outputs", self.outputs),
            ("workspace_paths", self.workspace_paths),
        )
        for field_name, values in sequence_fields:
            if not isinstance(values, Sequence) or any(not isinstance(value, str) or not value for value in values):
                raise ValueError(f"ExecutionPlan {field_name} must contain non-empty strings")
            if field_name in {"outputs", "workspace_paths"}:
                for value in values:
                    _validate_workspace_path(value, field_name)
        if not isinstance(self.environment, Mapping) or any(
            not isinstance(key, str) or not key or not isinstance(value, str)
            for key, value in self.environment.items()
        ):
            raise ValueError("ExecutionPlan environment must map names to strings")
        for mount in self.mounts:
            if not isinstance(mount, Mapping) or set(mount) - {"source", "target", "mode"}:
                raise ValueError("ExecutionPlan mounts must contain source, target, and optional mode")
            if not mount.get("source") or not mount.get("target"):
                raise ValueError("ExecutionPlan mount source and target must be non-empty")
            if mount.get("mode", "ro") not in {"ro", "rw"}:
                raise ValueError("ExecutionPlan mount mode must be 'ro' or 'rw'")


class ExecutionBuilder:
    """Build the scheduler-neutral plan consumed by execution adapters."""

    @staticmethod
    def from_task(task: Any, runner: Any, *, outputs: Sequence[str] = ()) -> ExecutionPlan:
        runtime = task.runtime
        command = tuple(runtime.entrypoint) or ("bash",)
        mounts = tuple(
            {"source": mount.host_path, "target": mount.container_path, "mode": mount.mode}
            for mount in getattr(runner, "mounts", ())
        )
        return ExecutionPlan(
            image=runtime.slurm_image or "<missing-image>",
            command=command,
            arguments=tuple(getattr(task, "runner_args", ())),
            environment=dict(getattr(runner, "env", {})),
            mounts=mounts,
            outputs=tuple(outputs),
        )


class JobState(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Job(ABC):
    """A compute job submitted to a backend (Docker, SLURM, …).

    Subclasses implement ``submit``, ``poll``, and ``cancel`` for their
    specific runtime.  The caller only needs to call ``submit()`` then
    ``poll()`` — the ABC handles the rest.
    """

    def __init__(
        self,
        task_id: str,
        tt: Any,  # TaskType (avoid circular import)
        runner: Any,  # RunnerConfig
        entities: list[dict],
        output_dir: str,
        stage_callback: Any = None,
    ):
        self.task_id = task_id
        self.tt = tt
        self.runner = runner
        self.entities = entities
        self.output_dir = output_dir
        self.stage_callback = stage_callback
        self._job_id: str | None = None

    # -- public API ----------------------------------------------------------

    @abstractmethod
    def submit(self) -> str:
        """Submit the job to the backend, return the backend job id."""
        ...

    @abstractmethod
    def poll(self) -> JobState:
        """Block until the job reaches a terminal state, return that state."""
        ...

    @abstractmethod
    def cancel(self) -> None:
        """Kill a running job."""
        ...

    # -- helpers -------------------------------------------------------------

    @property
    def job_id(self) -> str | None:
        return self._job_id

    @property
    def file_entities(self) -> list[dict]:
        return [e for e in self.entities if e["type"] == "file"]

    @property
    def param_entities(self) -> list[dict]:
        return [e for e in self.entities if e["type"] != "file"]

    @property
    def workspace_key(self) -> str:
        if not self.file_entities:
            raise RuntimeError("A compute job requires at least one input file")
        return str(self.file_entities[0]["workspace_key"])

    @property
    def virtual_workspace_root(self) -> str:
        return f"/mnt/revocompute/{self.workspace_key}"

    @property
    def input_snapshot_root(self) -> str:
        if not self.file_entities:
            raise RuntimeError("A compute job requires at least one input file")
        return str(self.file_entities[0]["snapshot_root"])
