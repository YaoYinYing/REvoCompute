# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Bounded, privacy-safe JSON operational events."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EVENT_NAMES = frozenset(
    {
        "http.request.started",
        "http.request.finished",
        "http.request.failed",
        "preflight.started",
        "preflight.security_rejected",
        "preflight.contract_rejected",
        "preflight.admission_denied",
        "preflight.passed",
        "infrastructure.check.completed",
        "infrastructure.readiness.changed",
        "task.submission.started",
        "task.submitted",
        "task.cancelled",
        "task.failed",
        "task.finished",
        "worker.task.started",
        "worker.task.failed",
        "worker.task.finished",
        "slurm.allocation.requested",
        "slurm.allocation.granted",
        "slurm.allocation.finished",
        "slurm.allocation.failed",
        "slurm.allocation.cancelled",
        "runner.stage.started",
        "runner.stage.progress",
        "runner.stage.finished",
        "runner.stage.failed",
        "artifact.validation.started",
        "artifact.validation.failed",
        "manifest.published",
        "archive.requested",
        "archive.completed",
        "gpu.credit.checked",
        "gpu.credit.denied",
        "gpu.usage.started",
        "gpu.usage.settled",
        "gpu.credit.adjusted",
    }
)

_TEXT_FIELDS = frozenset(
    {
        "request_id",
        "task_id",
        "task_type",
        "runner_family",
        "stage_id",
        "celery_task_id",
        "slurm_job_id",
        "reason_code",
        "http_method",
        "http_route",
    }
)
_INTEGER_FIELDS = frozenset({"duration_ms", "http_status", "user_id", "gpu_count", "gpu_seconds"})
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
_LOGGER = logging.getLogger("revocompute.operational")
_HANDLER_LOCK = threading.Lock()


def build_event(event: str, *, level: str = "INFO", **fields: Any) -> dict[str, Any]:
    """Build one bounded envelope; undeclared fields fail closed."""
    if event not in EVENT_NAMES:
        raise ValueError(f"Unknown operational event: {event}")
    normalized_level = level.upper()
    if normalized_level not in _LEVELS:
        raise ValueError(f"Unknown operational event level: {level}")
    unknown = set(fields) - _TEXT_FIELDS - _INTEGER_FIELDS
    if unknown:
        raise TypeError(f"Unknown operational event field(s): {', '.join(sorted(unknown))}")
    payload: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": normalized_level,
        "event": event,
    }
    for name, value in fields.items():
        if value is None:
            continue
        if name in _TEXT_FIELDS:
            if not isinstance(value, str):
                raise TypeError(f"Operational event field {name} must be a string")
            payload[name] = _CONTROL_CHARS.sub("?", value)[:256]
        elif not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise TypeError(f"Operational event field {name} must be a non-negative integer")
        else:
            payload[name] = value
    return payload


def _configure_logger() -> None:
    log_dir = os.environ.get("LOG_DIR", "").strip()
    target = str(Path(log_dir).resolve() / "operational-events.log") if log_dir else ""
    with _HANDLER_LOCK:
        handlers = [handler for handler in _LOGGER.handlers if getattr(handler, "_revocompute_events", False)]
        for handler in handlers:
            if not target or getattr(handler, "baseFilename", "") != target:
                _LOGGER.removeHandler(handler)
                handler.close()
        if target and not any(getattr(handler, "baseFilename", "") == target for handler in _LOGGER.handlers):
            Path(target).parent.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(target, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(message)s"))
            handler._revocompute_events = True  # type: ignore[attr-defined]
            _LOGGER.addHandler(handler)
        _LOGGER.setLevel(logging.INFO)
        _LOGGER.propagate = not target


def emit_event(event: str, *, level: str = "INFO", **fields: Any) -> dict[str, Any]:
    """Append one JSON line and return the emitted payload for callers/tests."""
    payload = build_event(event, level=level, **fields)
    try:
        _configure_logger()
        _LOGGER.log(getattr(logging, payload["level"]), json.dumps(payload, separators=(",", ":"), sort_keys=True))
    except OSError:
        logging.getLogger(__name__).exception("Operational event output is unavailable")
    return payload
