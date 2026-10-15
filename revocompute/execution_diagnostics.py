# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Bounded execution evidence; scheduler facts are separate from log context."""
from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable, Iterator, Mapping
from typing import Any

STATUS_PATH = "execution/slurm-status.execution.json"
MAX_LOG_BYTES = 64 * 1024
MAX_RECORD_BYTES = 264 * 1024
PREVIEW_BYTES = 8 * 1024
REASONS = {
    "timeout": "Execution exceeded its time limit.",
    "out_of_memory": "The scheduler reported an out-of-memory termination.",
    "allocation_failed": "The scheduler reported an allocation failure.",
    "nonzero_exit": "The execution process exited unsuccessfully.",
    "missing_result": "Execution exited successfully but produced no non-empty result artifact.",
    "submission_failed": "The allocation request could not be submitted.",
    "job_id_unavailable": "The allocation request returned no usable scheduler job identity.",
    "allocation_unrecorded": "Execution was stopped because its allocation could not be recorded safely.",
    "admission_failed": "Execution admission failed before the scientific command was released.",
    "execution_exception": "Execution ended unexpectedly.",
    "publication_failed": "Execution results could not be published safely.",
    "runner_validation_failed": "Runner output validation failed.",
}
_SECRET_KEY = re.compile(r"secret|password|passwd|token|credential|api.?key|authorization|private.?key", re.I)
_CONTROL = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SECRET_ASSIGNMENT = re.compile(
    r"(?im)([\w.-]*(?:secret|password|passwd|token|credential|api.?key|authorization)[\w.-]*[\"']?\s*[=:]\s*)"
    r"(?:\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s,;]+)"
)
_BEARER = re.compile(r"(?i)\b(Bearer|Basic)\s+[^\s,;]+")
_PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.S)
_URL = re.compile(r"\b(?:https?|ssh|redis|postgres(?:ql)?|mysql)://[^\s<>]+", re.I)
_HOST_PATH = re.compile(r"(?<![\w:])(?:/[\w.@+~%-]+){2,}(?:/[^\s\"'<>]*)?|[A-Za-z]:\\[^\r\n\"'<>]+")
_HOST_DETAIL = re.compile(r"(?im)(\b(?:NodeList|BatchHost|Cluster|AllocNode:Sid)=)\S+|(?<=srun: error: )[^\s:]+:")
_PRIVATE_NETWORK = re.compile(
    r"\b(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}"
    r"|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}|[\w.-]+\.(?:internal|local|cluster))\b",
    re.I,
)
_LOG_PATH = re.compile(r"execution/slurm-[^/]+\.(stdout|stderr)\.log\Z")


def safe_diagnostic_text(value: Any, *, secret_values: tuple[str, ...] = ()) -> str:
    """Redact known credentials, credential syntax, URLs and private path context."""
    text = _CONTROL.sub("", str(value or ""))
    known = set(secret_values)
    known.update(str(v) for k, v in os.environ.items() if _SECRET_KEY.search(k) and v)
    for secret in sorted(known, key=len, reverse=True):
        if secret:
            text = text.replace(secret, "[redacted]")
    text = _PRIVATE_KEY.sub("[private key redacted]", text)
    text = _BEARER.sub(lambda m: m[1] + " [redacted]", text)
    text = _SECRET_ASSIGNMENT.sub(lambda m: m[1] + "[redacted]", text)
    text = _URL.sub("[service URL redacted]", text)
    text = _HOST_PATH.sub("[path redacted]", text)
    text = _HOST_DETAIL.sub("[host detail redacted]", text)
    text = _PRIVATE_NETWORK.sub("[private network redacted]", text)
    return _CONTROL.sub("", text)


def redacted_log_lines(lines: Iterable[str], *, secret_values: tuple[str, ...] = ()) -> Iterator[str]:
    """Retain log context while withholding credentials and private host details."""
    known = (*secret_values, *(str(v) for k, v in os.environ.items() if _SECRET_KEY.search(k) and v))
    pieces = tuple(piece for secret in known for piece in secret.splitlines() if piece)
    private_key = False
    for line in lines:
        if "-----BEGIN " in line and "PRIVATE KEY-----" in line:
            private_key = True
            yield "[private key redacted]\n"
        if private_key:
            if "-----END " in line and "PRIVATE KEY-----" in line:
                private_key = False
            continue
        yield safe_diagnostic_text(line, secret_values=pieces)


def bounded_log(value: str, *, limit: int = MAX_LOG_BYTES) -> tuple[str, bool]:
    encoded = value.encode("utf-8")
    if len(encoded) <= limit:
        return value, False
    # Keep complete final lines. Starting halfway through a credential assignment
    # would remove the context a redactor needs to identify it.
    tail = encoded[-limit:].decode("utf-8", errors="replace")
    return tail.partition("\n")[2], True


def scheduler_failure(output: str, job_id: str) -> dict[str, str]:
    """Accept a terminal scheduler classification only for the requested job."""
    fields = dict(token.split("=", 1) for token in output.split() if "=" in token)
    if fields.get("JobId") != job_id:
        return {}
    state = fields.get("JobState", "").split("+", 1)[0]
    reasons = {
        "OUT_OF_MEMORY": "out_of_memory",
        "TIMEOUT": "timeout",
        "DEADLINE": "timeout",
        "NODE_FAIL": "allocation_failed",
        "BOOT_FAIL": "allocation_failed",
        "PREEMPTED": "allocation_failed",
        "REVOKED": "allocation_failed",
    }
    return {"reason_code": reasons[state], "scheduler_state": state} if state in reasons else {}


def _record(
    storage: Any, task: dict[str, Any], manifest: dict[str, Any], evidence: dict[str, Any]
) -> dict[str, Any] | None:
    declared = next((a for a in manifest.get("artifacts", []) if a.get("path") == STATUS_PATH), None)
    if not declared or declared.get("role") != "diagnostic" or not 0 < declared.get("size", 0) <= MAX_RECORD_BYTES:
        return None
    resolved = storage.open_verified_artifact(task, STATUS_PATH, manifest)
    if not resolved:
        return None
    with resolved["verified_stream"] as stream:
        if resolved["sha256"] != evidence.get("record_sha256"):
            return None
        try:
            value = json.loads(stream.read(MAX_RECORD_BYTES + 1))
        except (ValueError, UnicodeError):
            return None
    if (
        not isinstance(value, dict)
        or value.get("source") != "slurm_adapter"
        or value.get("schema_version") != 1
        or value.get("task_id") != task["md5sum"]
    ):
        return None
    return value


def diagnostic_payload(
    storage: Any, task: dict[str, Any], *, data_owned: bool, evidence: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Read only finalized, identity-verified evidence; never host allocation files."""
    payload = {
        "task_id": task["md5sum"],
        "availability": "unavailable",
        "summary": "Diagnostic evidence is unavailable.",
        "reason_code": None,
        "exit_code": None,
        "exit_code_source": None,
        "scheduler_state": None,
        "stage": safe_diagnostic_text(task.get("run_stage"))[:255] or None,
        "logs": [],
    }
    if not data_owned:
        return {**payload, "availability": "expired", "summary": "Task diagnostic data is no longer retained."}
    if task.get("status") != "failed":
        return payload
    payload["summary"] = (
        safe_diagnostic_text(task.get("error"))[:2000] or "Task failed. Diagnostic evidence is unavailable."
    )
    evidence = evidence or {}
    if not payload["stage"]:
        payload["stage"] = safe_diagnostic_text(evidence.get("stage_id"))[:255] or None
    reason = evidence.get("reason_code")
    if reason not in REASONS:
        reason = None
    if reason:
        payload.update(reason_code=reason, summary=REASONS[reason], availability="available")
    exit_code = evidence.get("exit_code")
    if isinstance(exit_code, int) and not isinstance(exit_code, bool):
        payload.update(exit_code=exit_code, exit_code_source="srun", availability="available")
    if evidence.get("scheduler_state") in {
        "OUT_OF_MEMORY",
        "TIMEOUT",
        "DEADLINE",
        "NODE_FAIL",
        "BOOT_FAIL",
        "PREEMPTED",
        "REVOKED",
    }:
        payload["scheduler_state"] = evidence["scheduler_state"]
    manifest = storage.load_manifest(task)
    if manifest is None:
        return payload
    record = _record(storage, task, manifest, evidence) or {}
    logs = record.get("logs")
    if not isinstance(logs, Mapping):
        logs = _legacy_logs(storage, task, manifest)
    for stream_name in ("stderr", "stdout"):
        value = logs.get(stream_name)
        if not isinstance(value, str) or not value:
            continue
        # Redact before trimming; an arbitrarily long secret must never be cut
        # into a fragment that no longer matches the complete known value.
        safe, truncated = bounded_log(safe_diagnostic_text(value))
        preview, preview_truncated = bounded_log(safe, limit=PREVIEW_BYTES)
        payload["logs"].append(
            {
                "stream": stream_name,
                "preview": preview,
                "truncated": truncated or preview_truncated,
                "download_url": f"/compute/api/tasks/{task['md5sum']}/diagnostics/{stream_name}",
                "text": safe,
            }
        )
    if payload["logs"]:
        payload["availability"] = "available"
    return payload


def _legacy_logs(storage: Any, task: dict[str, Any], manifest: dict[str, Any]) -> dict[str, str]:
    """Bounded fallback for historical results without an adapter evidence record."""
    logs = {"stdout": "", "stderr": ""}
    artifacts = [
        a
        for a in manifest.get("artifacts", [])
        if a.get("role") == "diagnostic" and _LOG_PATH.fullmatch(a.get("path", ""))
    ]
    for artifact in artifacts[-8:]:
        # Verification copies the complete artifact; decline a large historical
        # log rather than making a small preview perform unbounded disk work.
        if not 0 < artifact.get("size", 0) <= MAX_RECORD_BYTES:
            continue
        resolved = storage.open_verified_artifact(task, artifact["path"], manifest)
        if resolved:
            with resolved["verified_stream"] as stream:
                text = stream.read(MAX_RECORD_BYTES + 1).decode("utf-8", errors="replace")
            stream_name = _LOG_PATH.fullmatch(artifact["path"])[1]
            logs[stream_name] += text + "\n"
    return logs
