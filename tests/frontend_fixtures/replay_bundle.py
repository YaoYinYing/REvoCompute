# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""A bounded, sanitized replay bundle for one real Runner result.

The PR #38 fixture harness proves frontend behavior against deterministic
canonical API fixtures. A replay bundle is the complementary artifact: a
capture of one *real* completed Runner result, projected through the same
serve-time enrichment the Server applies, carrying the exact bytes the result
published so the production frontend can be driven against authentic output.

What a replay bundle proves: *the frontend renders the manifest and the artifact
bytes a real Runner published*. What it does not prove: that a Runner executed
here, that the scheduling was correct, or that the science is valid. Synthetic
fixtures own the state/behavior contract, a replay bundle owns the
compatibility-with-real-output contract, and the Runner's own acceptance and
scientific reference tests own correctness.

A bundle is deterministic and inspectable: it holds only what the frontend
reads, every byte is re-hashed from the source, and a payload that cannot be
checked in for size or encoding reasons keeps its hash and provenance with the
reason recorded rather than being silently dropped or truncated.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import quote

from . import builders

REPLAY_BUNDLE_VERSION = 1
REPLAY_BUNDLE_KIND = "real_runner_result_replay"

#: The privacy/robustness envelope a bundle is authored within. A payload at or
#: under the per-file budget may be checked in when it materially supports
#: browser acceptance; anything larger keeps hash/size/provenance only. The
#: bundle budget bounds the sum of checked-in payload bytes.
DEFAULT_MAX_PAYLOAD_BYTES = 262_144
DEFAULT_MAX_BUNDLE_BYTES = 1_048_576

#: Explicitly volatile fields normalized away before comparing two projections
#: of the same result. They are serve-time facts, not result identity.
VOLATILE_MANIFEST_FIELDS = ("filename", "message")

_TASK_ID = re.compile("[0-9a-fA-F]{32}")

# Media types for artifact paths whose payload the browser fetches directly.
_MEDIA_TYPE_BY_SUFFIX = {
    ".txt": "text/plain",
    ".log": "text/plain",
    ".stdout": "text/plain",
    ".err": "text/plain",
    ".a3m": "text/x-a3m",
    ".fasta": "text/x-fasta",
    ".fa": "text/x-fasta",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".json": "application/json",
    ".pdb": "chemical/x-pdb",
    ".cif": "chemical/x-cif",
    ".mmcif": "chemical/x-mmcif",
    ".png": "image/png",
    ".zip": "application/zip",
}


class ReplayBundleError(ValueError):
    """A replay bundle could not be captured, validated, or served faithfully."""


# ---------------------------------------------------------------------------
# Hashing and containment
# ---------------------------------------------------------------------------


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_relative(relative: str) -> str | None:
    """Return a normalized in-root relative path, or ``None`` when it escapes."""
    normalized = str(relative).replace("\\", "/")
    if not normalized or normalized.startswith("/"):
        return None
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return None
    return "/".join(parts)


def resolve_in_root(result_root: str | Path, relative: str) -> str | None:
    """Resolve ``relative`` under ``result_root``, or ``None`` when it escapes.

    Uses the Server's own canonical containment rule, so a bundle can never
    reference a path outside the result root it was captured from.
    """
    from revocompute.storage import path_is_within

    safe = _safe_relative(relative)
    if safe is None:
        return None
    root = os.path.realpath(result_root)
    physical = os.path.realpath(os.path.join(root, *safe.split("/")))
    if not path_is_within(root, physical):
        return None
    return physical


# ---------------------------------------------------------------------------
# Serve-time projection
# ---------------------------------------------------------------------------


def project_manifest_for_serve(
    manifest: Mapping[str, Any],
    *,
    task_id: str | None = None,
    status: str = "finished",
    error: str | None = None,
    archive: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project one published ResultManifest into the exact served response.

    This mirrors the full-access branch of ``revocompute.routes.get_results``:
    the serve-time envelope (``status``/``terminal``/``error``/``archive``), the
    per-artifact ``capability`` and ``url``/``table_url``/``ndarray_url``, the
    per-logical-file projection, and the storyboard ``entrypoint_url``. The
    on-disk record omits the envelope and the URL enrichment, so a capture
    re-derives them here to be self-contained: a replay serves the identical
    response a full-access deployment would.
    """
    from revocompute.task_runtime import artifact_capability

    task_id = str(task_id or manifest.get("task_id") or "").lower()
    payload = json.loads(json.dumps(dict(manifest)))
    payload.update(
        {
            "status": status,
            "terminal": True,
            "error": error if status == "failed" else None,
            "archive": dict(archive)
            if archive is not None
            else {
                "ready": False,
                "request_url": f"/compute/api/results/{task_id}/archive",
                "download_url": None,
            },
        }
    )
    for artifact in payload.get("artifacts", []):
        artifact.setdefault("capability", artifact_capability(artifact.get("preview"), artifact.get("logical_type")))
        encoded = quote(artifact["path"], safe="/")
        artifact["url"] = f"/compute/api/results/{task_id}/artifacts/{encoded}"
        if artifact["capability"] == "table":
            artifact["table_url"] = f"/compute/api/results/{task_id}/tables/{encoded}"
        if os.path.splitext(artifact["path"])[1].lower() in {".csv", ".json", ".npy", ".npz", ".tsv"}:
            artifact["ndarray_url"] = f"/compute/api/results/{task_id}/ndarrays/{encoded}"
    logical_files: dict[str, list[dict[str, Any]]] = {}
    for file_id, files in payload.get("result", {}).get("files", {}).items():
        logical_files[file_id] = []
        for index, artifact in enumerate(files):
            capability = artifact_capability(artifact.get("preview"), artifact.get("logical_type"))
            entry: dict[str, Any] = {
                "id": file_id,
                "name": os.path.basename(artifact["path"]),
                "media_type": artifact["media_type"],
                "size": artifact["size"],
                "role": artifact["role"],
                "cardinality": artifact["cardinality"],
                "viewer": artifact.get("logical_type") or artifact.get("preview") or "download",
                "preview": artifact.get("logical_type") or artifact.get("preview"),
                "capability": capability,
                "url": f"/compute/api/results/{task_id}/files/{file_id}?index={index}",
            }
            if artifact.get("confidence_encoding") == "plddt_bfactor":
                entry["confidence_encoding"] = "plddt_bfactor"
            if capability == "table":
                entry["table_url"] = f"/compute/api/results/{task_id}/tables/{quote(artifact['path'], safe='/')}"
            if os.path.splitext(artifact["path"])[1].lower() in {".csv", ".json", ".npy", ".npz", ".tsv"}:
                entry["ndarray_url"] = f"/compute/api/results/{task_id}/ndarrays/{quote(artifact['path'], safe='/')}"
            logical_files[file_id].append(entry)
    payload["result"] = {"files": logical_files}
    if payload.get("storyboard"):
        entrypoint = payload["storyboard"]["entrypoint"]
        payload["storyboard"]["entrypoint_url"] = f"/compute/api/results/{task_id}/storyboard/{entrypoint}"
    return payload


def required_view_sources(response: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    """The ``(view_id, source, path)`` triples the manifest declares as required.

    Derived from the manifest's own ``output_check`` checks: a check with
    ``required: true`` names a view and source whose declared path the result
    workspace cannot render without. A capture fails rather than persist a
    bundle whose required views have no resolvable bytes.
    """
    declared = response.get("output_check")
    checks = declared.get("checks") if isinstance(declared, Mapping) else None
    views = {view.get("id"): view for view in response.get("views", []) if isinstance(view, Mapping)}
    required: list[tuple[str, str, str]] = []
    for check in checks if isinstance(checks, list) else ():
        if not isinstance(check, Mapping) or not check.get("required"):
            continue
        view = views.get(check.get("view_id"))
        if view is None:
            continue
        paths = (view.get("sources") or {}).get(check.get("source"))
        for path in paths if isinstance(paths, list) else ():
            required.append((str(check.get("view_id")), str(check.get("source")), str(path)))
    return required


def normalize(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Drop explicitly volatile serve-time fields before comparing two manifests."""
    return {key: value for key, value in manifest.items() if key not in VOLATILE_MANIFEST_FIELDS}


# ---------------------------------------------------------------------------
# Sanitization
# ---------------------------------------------------------------------------

_SECRET_KEY = re.compile(r"(secret|password|token|credential|private.?key|api[_-]?key)", re.IGNORECASE)
_SECRET_VALUE = re.compile(
    r"(?:bearer\s+[a-z0-9._~+/=-]{24,}|eyj[a-z0-9_-]{16,}\.[a-z0-9_-]{16,}\.[a-z0-9_-]{16,}|rvk_[a-z0-9]{12,})",
    re.IGNORECASE,
)


def sanitize(value: Any) -> Any:
    """Return a copy of ``value`` with secret-bearing keys and values redacted.

    A bundle must never carry a credential or a private host detail. Key-name
    filtering removes a secret that travels under an obvious name; the value
    scan catches one that arrived under any other key. Deterministic: mappings
    are rebuilt in insertion order.
    """
    if isinstance(value, Mapping):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if _SECRET_KEY.search(str(key)):
                continue
            cleaned[str(key)] = sanitize(item)
        return cleaned
    if isinstance(value, (list, tuple)):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        return "[redacted]" if _SECRET_VALUE.search(value) else value
    return value


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------


def capture_replay_bundle(
    *,
    task_id: str,
    result_root: str | Path,
    task_row: Mapping[str, Any] | None = None,
    provenance: Mapping[str, Any] | None = None,
    display_name: str | None = None,
    max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES,
    max_bundle_bytes: int = DEFAULT_MAX_BUNDLE_BYTES,
) -> dict[str, Any]:
    """Capture one bounded, sanitized replay bundle from a canonical result root.

    Starts from a real completed result and reads through canonical ownership:
    the manifest's task identity must agree with the requested task (and its
    store row, when supplied), every payload is resolved only inside the result
    root and re-hashed from the bytes on disk, and every required view source
    must resolve. The result is deterministic for a fixed input.
    """
    if not _TASK_ID.fullmatch(str(task_id)):
        raise ReplayBundleError(f"invalid task id: {task_id!r}")
    task_id = str(task_id).lower()
    root = str(result_root)
    manifest_path = os.path.join(root, "manifest.json")
    if not os.path.isfile(manifest_path):
        raise ReplayBundleError(f"no published ResultManifest at {manifest_path}")
    try:
        with open(manifest_path, encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, ValueError) as exc:
        raise ReplayBundleError(f"ResultManifest is not readable JSON: {exc}") from exc
    if not isinstance(manifest, Mapping):
        raise ReplayBundleError("ResultManifest is not a JSON object")

    _verify_identity(manifest, task_id, task_row)
    response = project_manifest_for_serve(manifest, task_id=task_id)
    _validate_served(response)

    payloads: dict[str, dict[str, Any]] = {}
    excluded: list[dict[str, Any]] = []
    _capture_payloads(root, response, max_payload_bytes, max_bundle_bytes, payloads, excluded)
    storyboard_source = _capture_storyboard(root, response)

    bundle: dict[str, Any] = {
        "bundle_version": REPLAY_BUNDLE_VERSION,
        "kind": REPLAY_BUNDLE_KIND,
        "task": {
            "id": task_id,
            "type": response.get("task_type"),
            "display_name": _display_name(task_row) or display_name,
        },
        "provenance": sanitize(dict(provenance or {})),
        "response": sanitize(response),
        "logical_files": _logical_file_map(manifest),
        "payloads": payloads,
        "excluded": excluded,
        "storyboard": sanitize(storyboard_source) if storyboard_source is not None else None,
    }
    bundle["bundle_digest"] = bundle_digest(bundle)
    return bundle


def _verify_identity(manifest: Mapping[str, Any], task_id: str, task_row: Mapping[str, Any] | None) -> None:
    """The manifest must be the intended, terminal result of the requested task.

    The manifest is the sole artifact-identity source; the task row, when a
    caller can reach it, additionally proves the task is a finished success whose
    type agrees with the manifest, so a capture cannot persist a non-terminal or
    misidentified result.
    """
    if manifest.get("schema_version") != 3:
        raise ReplayBundleError(f"unsupported ResultManifest schema_version: {manifest.get('schema_version')!r}")
    if str(manifest.get("task_id") or "").lower() != task_id:
        raise ReplayBundleError("ResultManifest task identity disagrees with the requested task")
    if task_row is None:
        return
    if str(task_row.get("md5sum") or "").lower() != task_id:
        raise ReplayBundleError("task store row disagrees with the requested task identity")
    if str(task_row.get("status") or "") != "finished":
        raise ReplayBundleError(f"task is not a finished success: {task_row.get('status')!r}")
    if str(task_row.get("task_type") or "") != str(manifest.get("task_type") or ""):
        raise ReplayBundleError("task store and ResultManifest disagree on the task type")


def _display_name(task_row: Mapping[str, Any] | None) -> str | None:
    if task_row is None:
        return None
    return str(task_row.get("filename") or "") or None


def _logical_file_map(manifest: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """The logical-file identity the served manifest no longer carries.

    The Server's serve-time projection replaces ``result.files`` with resolved
    logical-file objects whose ``url`` (not their underlying path) is what the
    frontend follows. The bundle therefore keeps the published ``(path, sha256,
    size)`` map so a replay can resolve a logical-file identity to the exact
    captured artifact without inferring a role or a path from a name.
    """
    files = manifest.get("result")
    raw = files.get("files") if isinstance(files, Mapping) else None
    logical: dict[str, list[dict[str, Any]]] = {}
    for file_id in sorted(raw, key=str) if isinstance(raw, Mapping) else ():
        logical[str(file_id)] = [
            {"path": item.get("path"), "sha256": item.get("sha256"), "size": item.get("size")}
            for item in (raw[file_id] if isinstance(raw[file_id], list) else ())
            if isinstance(item, Mapping)
        ]
    return logical


def _validate_served(response: Mapping[str, Any]) -> None:
    try:
        builders.validate_payload("ResultManifest", response)
    except AssertionError as exc:
        raise ReplayBundleError(f"served ResultManifest violates the canonical contract: {exc}") from exc


def _capture_payloads(
    root: str,
    response: Mapping[str, Any],
    max_payload_bytes: int,
    max_bundle_bytes: int,
    payloads: dict[str, dict[str, Any]],
    excluded: list[dict[str, Any]],
) -> None:
    """Read, hash, and record each artifact payload the renderers fetch.

    A payload required by a declared view must resolve inside the result root
    and fit the per-file budget; a payload that is merely downloadable and too
    large (or not text) keeps its hash/size/provenance and is recorded as
    excluded with the reason, so an oversized model file never becomes a
    partial artifact.
    """
    required_paths = {path for _, _, path in required_view_sources(response)}
    candidates: list[tuple[str, bytes, Mapping[str, Any]]] = []
    for artifact in sorted(response.get("artifacts", []), key=lambda item: str(item.get("path"))):
        relative = _safe_relative(str(artifact.get("path") or ""))
        if relative is None:
            raise ReplayBundleError(f"artifact is not a safe relative path: {artifact.get('path')!r}")
        physical = resolve_in_root(root, relative)
        if physical is None or not os.path.isfile(physical):
            if relative in required_paths:
                raise ReplayBundleError(f"a required view source does not resolve: {relative}")
            continue
        data = Path(physical).read_bytes()
        digest = _sha256_hex(data)
        declared = str(artifact.get("sha256") or "")
        if declared and declared != digest:
            raise ReplayBundleError(f"artifact bytes disagree with the manifest sha256: {relative}")
        if len(data) > max_payload_bytes:
            if relative in required_paths:
                raise ReplayBundleError(f"a required view source exceeds the per-file payload budget: {relative}")
            excluded.append(_excluded(relative, len(data), digest, artifact, "exceeds the per-file payload budget"))
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            if relative in required_paths:
                raise ReplayBundleError(f"a required view source is not text and cannot be checked in: {relative}") from None
            excluded.append(_excluded(relative, len(data), digest, artifact, "binary payload is not checked in"))
            continue
        candidates.append((relative, text, artifact))

    # Enforce the bundle budget deterministically: the largest payloads drop out
    # first, each recorded with its own hash so nothing is lost silently. A
    # required view source is never dropped -- a replay that could not render a
    # declared view is a broken bundle, not a smaller one, so it fails instead.
    total = 0
    for relative, text, artifact in sorted(candidates, key=lambda item: (-len(item[1].encode("utf-8")), item[0])):
        data = text.encode("utf-8")
        if total + len(data) > max_bundle_bytes:
            if relative in required_paths:
                raise ReplayBundleError(f"a required view source exceeds the bundle payload budget: {relative}")
            excluded.append(_excluded(relative, len(data), _sha256_hex(data), artifact, "exceeds the bundle payload budget"))
            continue
        total += len(data)
        payloads[relative] = {
            "size": len(data),
            "sha256": _sha256_hex(data),
            "media_type": _media_type(artifact),
            "payload": text,
        }
    ordered = {path: payloads[path] for path in sorted(payloads)}
    payloads.clear()
    payloads.update(ordered)
    excluded.sort(key=lambda item: item["path"])


def _excluded(relative: str, size: int, digest: str, artifact: Mapping[str, Any], reason: str) -> dict[str, Any]:
    return {
        "path": relative,
        "size": size,
        "sha256": digest,
        "media_type": _media_type(artifact),
        "reason": reason,
    }


def _media_type(artifact: Mapping[str, Any]) -> str:
    declared = str(artifact.get("media_type") or "")
    if declared and declared != "application/octet-stream":
        return declared
    suffix = os.path.splitext(str(artifact.get("path") or ""))[1].lower()
    return _MEDIA_TYPE_BY_SUFFIX.get(suffix, "application/octet-stream")


def _capture_storyboard(root: str, response: Mapping[str, Any]) -> dict[str, Any] | None:
    declaration = response.get("storyboard")
    if not isinstance(declaration, Mapping):
        return None
    entrypoint = str(declaration.get("entrypoint") or "")
    if not entrypoint or _safe_relative(entrypoint) is None:
        raise ReplayBundleError(f"storyboard entrypoint is not a safe relative path: {entrypoint!r}")
    physical = os.path.join(root, "storyboard", *entrypoint.split("/"))
    if not os.path.isfile(physical):
        raise ReplayBundleError(f"the declared storyboard entrypoint does not resolve: {entrypoint}")
    source = Path(physical).read_text(encoding="utf-8")
    return {
        "entrypoint": entrypoint,
        "sha256": _sha256_hex(source.encode("utf-8")),
        "source": source,
    }


# ---------------------------------------------------------------------------
# Bundle identity, persistence, and validation
# ---------------------------------------------------------------------------


def bundle_digest(bundle: Mapping[str, Any]) -> str:
    """Content digest over the bundle body, excluding the digest itself."""
    from revocompute.live_tests import canonical_digest

    body = {key: value for key, value in bundle.items() if key != "bundle_digest"}
    return canonical_digest(body)


def write_bundle(path: str | Path, bundle: Mapping[str, Any]) -> Path:
    """Persist a bundle deterministically (sorted keys, trailing newline)."""
    from revocompute.live_tests import atomic_write_json

    destination = Path(path)
    atomic_write_json(destination, bundle)
    return destination


def load_bundle(source: str | Path | Mapping[str, Any]) -> dict[str, Any]:
    """Load and validate a replay bundle, failing loudly on drift or corruption.

    Raises :class:`ReplayBundleError` when the document is not a bundle this
    version understands, when its stored digest no longer recomputes, when the
    served manifest no longer satisfies the canonical contract, when a payload
    hash or size disagrees with its artifact, or when a required view source is
    missing from the captured payloads.
    """
    if isinstance(source, Mapping):
        document: Any = dict(source)
    else:
        try:
            with open(source, encoding="utf-8") as handle:
                document = json.load(handle)
        except (OSError, ValueError) as exc:
            raise ReplayBundleError(f"replay bundle is not readable JSON: {exc}") from exc
    if not isinstance(document, Mapping):
        raise ReplayBundleError("replay bundle must be a JSON object")
    if document.get("bundle_version") != REPLAY_BUNDLE_VERSION:
        raise ReplayBundleError(f"unsupported bundle_version: {document.get('bundle_version')!r}")
    if document.get("kind") != REPLAY_BUNDLE_KIND:
        raise ReplayBundleError(f"unexpected bundle kind: {document.get('kind')!r}")
    stored = document.get("bundle_digest")
    if not isinstance(stored, str) or stored != bundle_digest(document):
        raise ReplayBundleError("bundle_digest does not match the bundle contents")
    bundle = json.loads(json.dumps(document))
    task = bundle.get("task")
    if not isinstance(task, Mapping) or not _TASK_ID.fullmatch(str(task.get("id"))):
        raise ReplayBundleError("replay bundle has no valid task identity")
    response = bundle.get("response")
    if not isinstance(response, Mapping) or str(response.get("task_id") or "").lower() != str(task["id"]).lower():
        raise ReplayBundleError("replay bundle response disagrees with its task identity")
    if str(bundle.get("task", {}).get("type") or "") != str(response.get("task_type") or ""):
        raise ReplayBundleError("replay bundle task type disagrees with the ResultManifest")
    _validate_served(response)
    _verify_payloads(bundle)
    return bundle


def _verify_payloads(bundle: Mapping[str, Any]) -> None:
    response = bundle["response"]
    by_path = {str(artifact.get("path")): artifact for artifact in response.get("artifacts", [])}
    payloads = bundle.get("payloads") or {}
    if not isinstance(payloads, Mapping):
        raise ReplayBundleError("replay bundle payloads is not an object")
    for path, entry in payloads.items():
        if not isinstance(entry, Mapping):
            raise ReplayBundleError(f"replay payload {path!r} is not an object")
        data = str(entry.get("payload") or "").encode("utf-8")
        if _sha256_hex(data) != str(entry.get("sha256")):
            raise ReplayBundleError(f"replay payload {path!r} does not match its own sha256")
        artifact = by_path.get(path)
        if artifact is None:
            raise ReplayBundleError(f"replay payload {path!r} is not a declared artifact")
        if int(artifact.get("size") or -1) != len(data):
            raise ReplayBundleError(f"replay payload {path!r} disagrees with the manifest size")
        if str(artifact.get("sha256") or "") and str(artifact["sha256"]) != str(entry.get("sha256")):
            raise ReplayBundleError(f"replay payload {path!r} disagrees with the manifest sha256")
    excluded = {str(item.get("path")) for item in bundle.get("excluded") or () if isinstance(item, Mapping)}
    for _, _, path in required_view_sources(response):
        if path not in payloads:
            reason = "excluded" if path in excluded else "absent"
            raise ReplayBundleError(f"a required view source is not captured ({reason}): {path}")
    _verify_logical_files(bundle)
    storyboard = response.get("storyboard")
    if isinstance(storyboard, Mapping) and storyboard.get("entrypoint"):
        captured = bundle.get("storyboard")
        if not isinstance(captured, Mapping) or captured.get("entrypoint") != storyboard.get("entrypoint"):
            raise ReplayBundleError("the declared storyboard source is not captured")
        if not isinstance(captured.get("source"), str) or _sha256_hex(captured["source"].encode("utf-8")) != captured.get("sha256"):
            raise ReplayBundleError("the captured storyboard source does not match its own sha256")


def _verify_logical_files(bundle: Mapping[str, Any]) -> None:
    """Every published logical-file identity must map to a captured or recorded artifact.

    A logical-file identity the frontend cannot resolve to either captured bytes
    or an explicitly excluded artifact (with its hash) would render as a missing
    file with no provenance, so the bundle fails rather than serve a dangling
    Expected File Tree.
    """
    logical = bundle.get("logical_files") or {}
    if not isinstance(logical, Mapping):
        raise ReplayBundleError("replay bundle logical_files is not an object")
    payloads = bundle.get("payloads") or {}
    excluded = {str(item.get("path")) for item in bundle.get("excluded") or () if isinstance(item, Mapping)}
    for file_id, entries in logical.items():
        if not isinstance(entries, list) or not entries:
            raise ReplayBundleError(f"logical file {file_id!r} has no entries")
        for entry in entries:
            path = str(entry.get("path") or "") if isinstance(entry, Mapping) else ""
            if not path or (path not in payloads and path not in excluded):
                raise ReplayBundleError(f"logical file {file_id!r} resolves to an uncaptured artifact: {path!r}")
