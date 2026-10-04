# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Machine-generated production API acceptance receipts.

A receipt records what a completed production API submission observably was:
the revision that served it, the admitted input/parameter snapshot, the Slurm
job that executed it, the public API lifecycle, the published ResultManifest
and its artifacts, and the factual observables those artifacts carry.

Every fact is derived from canonical state -- the task store row, the published
manifest.json bytes, the runner-written Slurm accounting, and the deploy stamp
-- never restated from prose, and every published artifact is re-hashed from
the bytes actually on disk. An inconsistent or incomplete observation is
recorded as a problem and never reported as complete.

This module is pure. It resolves, hashes, and serializes. The operator command
that authenticates, submits, and reads the live host is
run/revocompute_ctl/api_receipt.py.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from revocompute.live_tests import canonical_digest, sanitized_mapping, sha256_file
from revocompute.storage import path_is_within

API_RECEIPT_VERSION = 1
API_RECEIPT_KIND = "production_api_acceptance"

#: A receipt is an acceptance record for a task that reached a settled success.
TERMINAL_SUCCESS_STATUS = "finished"

#: Bounded projection of a published summary artifact.
_SUMMARY_MAX_LEAVES = 200
_SUMMARY_MAX_DEPTH = 8

_SHA256_HEX = re.compile("[0-9a-f]{64}")
_TASK_ID = re.compile("[a-fA-F0-9]{32}")

#: A receipt must never carry a credential, whatever the source. Key names that
#: match this are dropped by ``sanitized_mapping``; the value scan below catches
#: a secret that arrived undisguised.
_SECRET_VALUE = re.compile(
    r"(?:bearer\s+[a-z0-9._~+/=-]{24,}|eyj[a-z0-9_-]{16,}\.[a-z0-9_-]{16,}\.[a-z0-9_-]{16,})",
    re.IGNORECASE,
)


class ApiReceiptError(ValueError):
    """The requested task cannot produce a receipt at all."""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def iso_to_epoch(value: Any) -> float | None:
    """Parse one ISO-8601 timestamp into a POSIX epoch, or ``None``.

    Total: a malformed or absent timestamp is ``None``, never a raise, so the
    caller can record it as an inconsistency instead of losing the receipt.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text[-1] in "Zz":
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


def _sha256_hex(path: str | Path) -> str:
    return sha256_file(path).removeprefix("sha256:")


def _host_identity(base_url: str) -> dict[str, Any]:
    """Non-secret endpoint identity: the host, never a user or a credential."""
    host = urlsplit(base_url).hostname if base_url else ""
    return {"endpoint_host": host or ""}


def _scrub_secret_values(value: Any) -> tuple[Any, bool]:
    """Recursively redact credential-shaped string values.

    Key-name filtering removes a secret that travels under an obvious name; this
    catches one that arrived under any other key. Returns the cleaned value and
    whether anything was redacted.
    """
    if isinstance(value, Mapping):
        cleaned: dict[str, Any] = {}
        found = False
        for key, item in value.items():
            scrubbed, hit = _scrub_secret_values(item)
            cleaned[str(key)] = scrubbed
            found = found or hit
        return cleaned, found
    if isinstance(value, (list, tuple)):
        cleaned_list: list[Any] = []
        found = False
        for item in value:
            scrubbed, hit = _scrub_secret_values(item)
            cleaned_list.append(scrubbed)
            found = found or hit
        return cleaned_list, found
    if isinstance(value, str) and _SECRET_VALUE.search(value):
        return "[redacted]", True
    return value, False


def _deployment_identity(
    stamp: Mapping[str, Any] | None, runtime_sif_sha256: str | None = None
) -> tuple[dict[str, Any], list[str]]:
    """Project the deploy stamp into the receipt's deployment identity.

    The stamp is the operator-owned record of what was deployed. A missing stamp
    is an inconsistency: the receipt could not observe a revision, so it must
    not be reported as complete. A dirty working tree is recorded as a fact, not
    a problem -- a localized deployment is dirty by construction and the field
    is what tells a reader the deployed tree is not exactly the commit.

    ``runtime_sif_sha256`` is the exact container image the task's Runner
    executed. It is supplied by the caller only when it hashed the promoted SIF
    itself, so it is a fact about the deployed artifact rather than a claim.
    """
    if not isinstance(stamp, Mapping) or not stamp.get("commit"):
        return {"available": False}, ["deployed revision is not observable: no deploy stamp"]
    return (
        {
            "available": True,
            "commit": stamp.get("commit"),
            "dirty": bool(stamp.get("dirty")),
            "mode": stamp.get("mode"),
            "stamped_at": stamp.get("stamped_at"),
            "image_digests": sanitized_mapping(stamp.get("digests") or {}),
            "sif_sha256s": sanitized_mapping(stamp.get("sif_sha256s") or {}),
            "runtime_sif_sha256": runtime_sif_sha256,
            "registry_sha256": stamp.get("registry_sha256"),
            "config_contract_sha256": stamp.get("config_contract_sha256"),
        },
        [],
    )


def _artifact_inventory(manifest: Mapping[str, Any], result_root: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Re-hash every published artifact against the manifest that declares it.

    The physical path is derived from the manifest's own relative path and must
    resolve inside the task result root; a path that escapes it, a missing file,
    or bytes whose size/sha256 disagree with the manifest is recorded as a
    problem. Nothing is silently omitted.
    """
    entries: list[dict[str, Any]] = []
    problems: list[str] = []
    raw = manifest.get("artifacts")
    for artifact in raw if isinstance(raw, list) else ():
        if not isinstance(artifact, Mapping):
            problems.append("manifest contains a non-object artifact entry")
            continue
        relative = str(artifact.get("path") or "").replace("\\", "/")
        parts = relative.split("/")
        if not relative or relative.startswith("/") or any(part in {"", ".", ".."} for part in parts):
            problems.append(f"artifact path is not a safe relative path: {relative!r}")
            continue
        physical = os.path.join(result_root, *parts)
        if not path_is_within(result_root, physical):
            problems.append(f"artifact escapes the task result root: {relative}")
            continue
        if os.path.islink(physical) or not os.path.isfile(physical):
            problems.append(f"published artifact is missing: {relative}")
            continue
        size = os.path.getsize(physical)
        digest = _sha256_hex(physical)
        entry = {
            "path": relative,
            "role": artifact.get("role"),
            "media_type": artifact.get("media_type"),
            "size": size,
            "sha256": digest,
        }
        declared = str(artifact.get("sha256") or "")
        if declared and declared != digest:
            problems.append(f"artifact sha256 disagrees with the manifest: {relative}")
        if artifact.get("size") is not None and int(artifact["size"]) != size:
            problems.append(f"artifact size disagrees with the manifest: {relative}")
        entries.append(entry)
    entries.sort(key=lambda item: item["path"])
    return entries, problems


def _logical_result(manifest: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    files = manifest.get("result")
    raw = files.get("files") if isinstance(files, Mapping) else None
    if not isinstance(raw, Mapping):
        return {}
    logical: dict[str, list[dict[str, Any]]] = {}
    for file_id in sorted(raw, key=str):
        items = raw[file_id]
        logical[str(file_id)] = [
            {
                "path": item.get("path"),
                "role": item.get("role"),
                "cardinality": item.get("cardinality"),
                "logical_type": item.get("logical_type"),
                "size": item.get("size"),
                "sha256": item.get("sha256"),
            }
            for item in (items if isinstance(items, list) else ())
            if isinstance(item, Mapping)
        ]
    return logical


def _result_views(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = manifest.get("views")
    views: list[dict[str, Any]] = []
    for view in raw if isinstance(raw, list) else ():
        if not isinstance(view, Mapping):
            continue
        views.append(
            {
                "id": view.get("id"),
                "plugin": view.get("plugin"),
                "role": view.get("role"),
                "title": view.get("title"),
                "sources": sanitized_mapping(view.get("sources") or {}),
            }
        )
    return views


def _flatten_summary(node: Any, prefix: str = "", depth: int = 0, out: dict[str, Any] | None = None) -> dict[str, Any]:
    """Flatten a published summary's scalar leaves into dotted observables.

    Bounded in both depth and leaf count: a fitted coupling tensor is not a
    factual summary observable and must never be copied into a receipt.
    """
    result = {} if out is None else out
    if len(result) >= _SUMMARY_MAX_LEAVES or depth > _SUMMARY_MAX_DEPTH:
        return result
    if isinstance(node, Mapping):
        for key in sorted(node, key=str):
            if len(result) >= _SUMMARY_MAX_LEAVES:
                break
            _flatten_summary(node[key], f"{prefix}.{key}" if prefix else str(key), depth + 1, result)
    elif isinstance(node, (list, tuple)):
        scalars = [item for item in node if isinstance(item, (str, int, float, bool)) or item is None]
        if scalars and len(scalars) == len(node) and len(node) <= 16:
            result[prefix] = scalars
    elif isinstance(node, (str, int, float, bool)) or node is None:
        result[prefix] = node
    return result


def _published_summary(
    manifest: Mapping[str, Any], result_root: str
) -> tuple[str | None, dict[str, Any], list[str]]:
    """Read the task's published summary artifact, if the manifest names one.

    The summary is located through the manifest's own logical-file projection
    (a logical id ``summary``) or, failing that, the single artifact whose
    basename is ``summary.json``. It is never guessed from the Runner name.
    """
    problems: list[str] = []
    logical = manifest.get("result")
    files = logical.get("files") if isinstance(logical, Mapping) else None
    candidates: list[str] = []
    if isinstance(files, Mapping) and isinstance(files.get("summary"), list):
        candidates = [str(item.get("path")) for item in files["summary"] if isinstance(item, Mapping)]
    if not candidates:
        artifacts = manifest.get("artifacts")
        candidates = [
            str(item.get("path"))
            for item in (artifacts if isinstance(artifacts, list) else ())
            if isinstance(item, Mapping) and os.path.basename(str(item.get("path") or "")) == "summary.json"
        ]
    for relative in candidates:
        parts = str(relative).replace("\\", "/").split("/")
        if not relative or any(part in {"", ".", ".."} for part in parts) or str(relative).startswith("/"):
            continue
        physical = os.path.join(result_root, *parts)
        if not path_is_within(result_root, physical) or not os.path.isfile(physical):
            continue
        try:
            if os.path.getsize(physical) > 8 * 1024 * 1024:
                problems.append(f"summary artifact is larger than the bounded read: {relative}")
                return relative, {}, problems
            with open(physical, encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError):
            problems.append(f"summary artifact is not readable JSON: {relative}")
            return relative, {}, problems
        if not isinstance(payload, Mapping):
            problems.append(f"summary artifact is not a JSON object: {relative}")
            return relative, {}, problems
        return relative, _flatten_summary(payload), problems
    return None, {}, problems


def _lifecycle(run: Mapping[str, Any], task_row: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Derive the observed lifecycle from the manifest's own run record."""
    problems: list[str] = []
    submitted = iso_to_epoch(run.get("submitted_at"))
    started = iso_to_epoch(run.get("started_at"))
    finished = iso_to_epoch(run.get("finished_at"))
    if submitted is None:
        problems.append("lifecycle submitted_at is malformed or absent")
    if started is None:
        problems.append("lifecycle started_at is malformed or absent")
    if finished is None:
        problems.append("lifecycle finished_at is malformed or absent")
    intervals: dict[str, float] = {}
    for name, begin, end in (
        ("queue_seconds", submitted, started),
        ("execution_seconds", started, finished),
        ("observed_seconds", submitted, finished),
    ):
        if begin is None or end is None:
            continue
        span = round(end - begin, 6)
        if span < 0:
            problems.append(f"negative lifecycle interval: {name}")
            continue
        intervals[name] = span
    return (
        {
            "submitted_at": run.get("submitted_at"),
            "started_at": run.get("started_at"),
            "finished_at": run.get("finished_at"),
            "walltime_seconds": run.get("walltime_seconds"),
            "status": task_row.get("status"),
            "intervals": intervals,
        },
        problems,
    )


def _scheduler(task_row: Mapping[str, Any], resource_payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Scheduler identity and resource facts from the executor's own evidence."""
    payload = resource_payload if isinstance(resource_payload, Mapping) else {}
    return {
        "slurm_job_id": task_row.get("slurm_job_id"),
        "accounting_source": payload.get("source"),
        "exit_code": payload.get("exit_code"),
        "elapsed_seconds": payload.get("elapsed_seconds"),
        "max_rss_kib": payload.get("max_rss_kib"),
        "user_cpu_seconds": payload.get("user_cpu_seconds"),
        "system_cpu_seconds": payload.get("system_cpu_seconds"),
        "allocated_cpus_per_task": payload.get("allocated_cpus_per_task"),
        "allocated_tasks": payload.get("allocated_tasks"),
        "job_id_matches": (
            None
            if payload.get("job_id") is None
            else str(payload.get("job_id")) == str(task_row.get("slurm_job_id"))
        ),
    }


def _submission(run: Mapping[str, Any], manifest: Mapping[str, Any], task_row: Mapping[str, Any]) -> dict[str, Any]:
    """The admitted snapshot identity and the effective parameters as published."""
    method = run.get("method") if isinstance(run.get("method"), Mapping) else {}
    return {
        "task_id": manifest.get("task_id"),
        "task_type": manifest.get("task_type"),
        "method": {"id": method.get("id"), "name": method.get("name")},
        "inputs": sanitized_mapping(run.get("inputs") or []),
        "parameters": [
            {"name": item.get("name"), "value": item.get("value"), "unit": item.get("unit")}
            for item in (run.get("parameters") if isinstance(run.get("parameters"), list) else ())
            if isinstance(item, Mapping)
        ],
        "storage_key": task_row.get("storage_key"),
        "display_name": task_row.get("filename"),
    }


def build_api_receipt(
    *,
    task_id: str,
    manifest: Mapping[str, Any],
    task_row: Mapping[str, Any],
    result_root: str,
    deployment_stamp: Mapping[str, Any] | None = None,
    resource_payload: Mapping[str, Any] | None = None,
    runtime_sif_sha256: str | None = None,
    status_evidence: Mapping[str, Any] | None = None,
    base_url: str = "",
    captured_at: str | None = None,
) -> dict[str, Any]:
    """Assemble the canonical receipt for one completed production submission.

    Every field is derived from the supplied canonical state; ``problems`` lists
    each inconsistency found, and ``complete`` is true only when the list is
    empty. The caller persists the document unchanged.

    ``runtime_sif_sha256`` and ``status_evidence`` are optional already-observed
    facts the caller may supply when it can reach the live host; when absent the
    receipt simply omits them rather than inventing a value.
    """
    problems: list[str] = []
    if not _TASK_ID.fullmatch(str(task_id)):
        raise ApiReceiptError(f"invalid task id: {task_id!r}")
    task_id = str(task_id).lower()
    if manifest.get("schema_version") != 3:
        problems.append(f"unsupported ResultManifest schema_version: {manifest.get('schema_version')!r}")
    if str(manifest.get("task_id") or "") != task_id:
        problems.append("ResultManifest task identity disagrees with the requested task")
    status = str(task_row.get("status") or "")
    if status != TERMINAL_SUCCESS_STATUS:
        problems.append(f"task is not a finished success: {status or 'unknown'}")
    if str(task_row.get("task_type") or "") != str(manifest.get("task_type") or ""):
        problems.append("task store and ResultManifest disagree on the task type")

    deployment, deployment_problems = _deployment_identity(deployment_stamp, runtime_sif_sha256)
    problems.extend(deployment_problems)
    run = manifest.get("run") if isinstance(manifest.get("run"), Mapping) else {}
    lifecycle, lifecycle_problems = _lifecycle(run, task_row)
    problems.extend(lifecycle_problems)
    scheduler = _scheduler(task_row, resource_payload)
    if scheduler["exit_code"] is not None and int(scheduler["exit_code"]) != 0:
        problems.append(f"Slurm job exit code is nonzero: {scheduler['exit_code']}")
    if scheduler["job_id_matches"] is False:
        problems.append("scheduler accounting names a different job than the task row")
    artifacts, artifact_problems = _artifact_inventory(manifest, result_root)
    problems.extend(artifact_problems)
    if not artifacts:
        problems.append("the ResultManifest publishes no readable artifacts")
    summary_name, observables, summary_problems = _published_summary(manifest, result_root)
    problems.extend(summary_problems)

    output_check = manifest.get("output_check") if isinstance(manifest.get("output_check"), Mapping) else {}
    receipt: dict[str, Any] = {
        "receipt_version": API_RECEIPT_VERSION,
        "kind": API_RECEIPT_KIND,
        "captured_at": captured_at or _now_iso(),
        "task_id": task_id,
        "host": _host_identity(base_url),
        "deployment": deployment,
        "submission": _submission(run, manifest, task_row),
        "scheduler": scheduler,
        "lifecycle": lifecycle,
        "result": {
            "manifest_schema_version": manifest.get("schema_version"),
            "created_at": manifest.get("created_at"),
            "output_check": {
                "state": output_check.get("state"),
                "problems": list(output_check.get("problems") or []),
            },
            "views": _result_views(manifest),
            "logical_files": _logical_result(manifest),
            "artifacts": artifacts,
            "total_size": manifest.get("total_size"),
        },
        "observables": {"summary_artifact": summary_name, "summary": observables},
        "api_status_evidence": sanitized_mapping(status_evidence) if status_evidence else None,
        "problems": [],
        "complete": False,
    }
    receipt, redacted = _scrub_secret_values(sanitized_mapping(receipt))
    if redacted:
        problems.append("a credential-shaped value was detected and redacted")
    receipt["problems"] = sorted(set(problems))
    receipt["complete"] = not receipt["problems"]
    receipt["receipt_digest"] = _receipt_digest(receipt)
    return receipt


def _receipt_digest(receipt: Mapping[str, Any]) -> str:
    """Content digest over the receipt body, excluding volatile capture metadata."""
    body = {key: value for key, value in receipt.items() if key not in {"receipt_digest", "captured_at"}}
    return canonical_digest(body)


def parse_api_receipt(document: Any) -> dict[str, Any]:
    """Validate a persisted receipt document and return it unchanged.

    Raises :class:`ApiReceiptError` when the document is not a receipt this code
    understands, so a consumer never reads a shape it cannot reason about.
    """
    if not isinstance(document, Mapping):
        raise ApiReceiptError("receipt document must be a JSON object")
    if document.get("receipt_version") != API_RECEIPT_VERSION:
        raise ApiReceiptError(f"unsupported receipt_version: {document.get('receipt_version')!r}")
    if document.get("kind") != API_RECEIPT_KIND:
        raise ApiReceiptError(f"unexpected receipt kind: {document.get('kind')!r}")
    if not _TASK_ID.fullmatch(str(document.get("task_id"))):
        raise ApiReceiptError("receipt has no valid task_id")
    if not isinstance(document.get("complete"), bool):
        raise ApiReceiptError("receipt has no complete flag")
    result = document.get("result")
    artifacts = result.get("artifacts") if isinstance(result, Mapping) else None
    if not isinstance(artifacts, list):
        raise ApiReceiptError("receipt has no artifact inventory")
    for artifact in artifacts:
        if not isinstance(artifact, Mapping) or not _SHA256_HEX.fullmatch(str(artifact.get("sha256"))):
            raise ApiReceiptError("receipt contains an artifact without a sha256")
    return dict(document)


def render_api_receipt_summary(receipt: Mapping[str, Any]) -> str:
    """A one-screen human summary derived from the persisted receipt."""
    deployment = receipt.get("deployment") or {}
    scheduler = receipt.get("scheduler") or {}
    lifecycle = receipt.get("lifecycle") or {}
    result = receipt.get("result") or {}
    submission = receipt.get("submission") or {}
    observables = (receipt.get("observables") or {}).get("summary") or {}
    lines = [
        f"Production API acceptance receipt for task {receipt.get('task_id')} [{submission.get('task_type')}]",
        f"  deployed: {deployment.get('commit') or 'unknown'}"
        + (" (dirty)" if deployment.get("dirty") else "")
        + f"  mode={deployment.get('mode')}  stamped_at={deployment.get('stamped_at')}",
        f"  lifecycle: {lifecycle.get('submitted_at')} -> {lifecycle.get('finished_at')}"
        + f"  walltime={lifecycle.get('walltime_seconds')}s  status={lifecycle.get('status')}",
        f"  scheduler: job {scheduler.get('slurm_job_id')} exit={scheduler.get('exit_code')}"
        + f" elapsed={scheduler.get('elapsed_seconds')}s max_rss={scheduler.get('max_rss_kib')}KiB",
        f"  manifest: v{result.get('manifest_schema_version')}"
        + f" output_check={(result.get('output_check') or {}).get('state')}"
        + f" artifacts={len(result.get('artifacts') or [])} total_size={result.get('total_size')}",
    ]
    for key in sorted(observables):
        lines.append(f"  {key} = {observables[key]}")
    lines.append(f"  complete={receipt.get('complete')}")
    for problem in receipt.get("problems") or []:
        lines.append(f"  problem: {problem}")
    return "\n".join(lines)


def receipt_failures(receipt: Mapping[str, Any]) -> list[str]:
    """The reasons a receipt is not a complete acceptance, in stable order."""
    return [str(problem) for problem in receipt.get("problems") or []]

