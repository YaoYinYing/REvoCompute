# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Replay-backed result scenarios for the demo playground.

A demo deployment must show authentic result rendering without executing a
Runner or touching a production result store. It does that by loading a small,
deployment-local index of the replay bundles the repository already keeps for
its browser replay tests, validating each through the canonical bundle loader,
and serving the bundle's own served manifest and captured bytes through
demo-scoped routes.

The bundle format, its digest, its payload identity, and its provenance rules
are owned by :mod:`revocompute.replay_bundle`; this module is a consumer. It
never reads a result directory, never invents a manifest, and never executes
Storyboard code carried by an archive.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from revocompute.replay import ReplayBundle
from revocompute.replay_bundle import ReplayBundleError, load_bundle

REPLAY_INDEX_VERSION = 1
REPLAY_INDEX_NAME = "index.json"
DEMO_REPLAYS_SUBDIR = Path("demo") / "replays"

PROVENANCE_RECORDED_VERIFIED = "recorded_verified"
PROVENANCE_RECORDED_LEGACY = "recorded_legacy"
PROVENANCE_SYNTHETIC = "synthetic"

_STORYBOARD_LIMITATION = "Demo replay does not execute Storyboard code carried by a recorded result."


class DemoReplayError(ValueError):
    """A demo replay index or bundle cannot be served faithfully."""


@dataclass(frozen=True, slots=True)
class DemoReplayScenario:
    id: str
    title: str
    summary: str
    task_type: str
    provenance: str
    capture_source: str
    bundle_digest: str
    bundle: ReplayBundle

    @property
    def task_id(self) -> str:
        return self.bundle.task_id

    def served_manifest(self) -> dict[str, Any]:
        """The bundle's served manifest, pointed at the demo's own routes.

        The captured manifest names the deployment routes that produced it. A
        demo serves the same shape, so every route under the captured Task is
        re-pointed at this scenario's demo routes. A Storyboard declaration is
        replaced with ``None``: the demo does not execute archived code, and the
        limitation is recorded rather than shown as an available renderer.
        """
        manifest = self.bundle.served_manifest()
        if manifest is None:  # pragma: no cover - the bundle is bound to its own id
            raise DemoReplayError("replay bundle lost its own manifest")
        prefix = f"/compute/api/results/{self.task_id}"
        target = f"/compute/api/demo/replays/{self.id}"
        rewritten = _rewrite_routes(manifest, prefix, target)
        rewritten["storyboard"] = None
        limitations = [str(item) for item in rewritten.get("limitations") or []]
        if _STORYBOARD_LIMITATION not in limitations:
            limitations.append(_STORYBOARD_LIMITATION)
        rewritten["limitations"] = limitations
        return rewritten

    def summary_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "task_type": self.task_type,
            "provenance": {
                "kind": self.provenance,
                "label": _provenance_label(self.provenance),
                "capture_source": self.capture_source,
            },
            "bundle_digest": self.bundle_digest,
            "task": {
                "id": self.task_id,
                "type": self.bundle.bundle.get("task", {}).get("type"),
                "display_name": self.bundle.bundle.get("task", {}).get("display_name"),
            },
        }


def _provenance_label(kind: str) -> str:
    if kind == PROVENANCE_RECORDED_VERIFIED:
        return "Recorded result · verified provenance"
    if kind == PROVENANCE_SYNTHETIC:
        return "Synthetic scenario · labeled fixture"
    return "Recorded result · legacy capture, provenance not machine-verified"


def _provenance_kind(bundle: dict[str, Any]) -> str:
    capture = bundle.get("provenance", {}).get("capture", {})
    mode = capture.get("mode") if isinstance(capture, dict) else None
    if mode == "reproduced_real_result":
        return PROVENANCE_RECORDED_VERIFIED
    if mode == "synthetic":
        return PROVENANCE_SYNTHETIC
    return PROVENANCE_RECORDED_LEGACY


def _capture_source(bundle: dict[str, Any]) -> str:
    capture = bundle.get("provenance", {}).get("capture", {})
    source = capture.get("captured_from") if isinstance(capture, dict) else None
    return str(source or "unspecified")


def _rewrite_routes(value: Any, prefix: str, target: str) -> Any:
    if isinstance(value, dict):
        return {key: _rewrite_routes(item, prefix, target) for key, item in value.items()}
    if isinstance(value, list):
        return [_rewrite_routes(item, prefix, target) for item in value]
    if isinstance(value, str) and value.startswith(prefix):
        return f"{target}{value[len(prefix):]}"
    return value


def _safe_bundle_path(root: Path, relative: str) -> Path:
    normalized = str(relative).replace("\\", "/")
    if not normalized or normalized.startswith("/") or any(part in {"", ".", ".."} for part in normalized.split("/")):
        raise DemoReplayError(f"replay bundle path is not a safe relative path: {relative!r}")
    candidate = (root / normalized).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise DemoReplayError(f"replay bundle path escapes the replay root: {relative!r}")
    return candidate


def load_demo_replays(root: str | os.PathLike[str]) -> dict[str, DemoReplayScenario]:
    """Load and validate every scenario named by the demo replay index.

    Fails closed: an unreadable index, an unknown version, a duplicate id, a
    bundle outside the root, or a bundle that does not validate aborts demo
    startup rather than serving a partial or fabricated catalog.
    """
    base = Path(root)
    index_path = base / REPLAY_INDEX_NAME
    try:
        document = json.loads(index_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DemoReplayError(f"demo replay index is missing: {index_path}") from exc
    except (OSError, ValueError) as exc:
        raise DemoReplayError(f"demo replay index is not readable JSON: {exc}") from exc
    if not isinstance(document, dict) or document.get("version") != REPLAY_INDEX_VERSION:
        raise DemoReplayError("demo replay index must be version 1")
    entries = document.get("scenarios")
    if not isinstance(entries, list) or not entries:
        raise DemoReplayError("demo replay index declares no scenarios")

    scenarios: dict[str, DemoReplayScenario] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise DemoReplayError("a demo replay scenario must be an object")
        scenario_id = str(entry.get("id") or "").strip()
        if not scenario_id or not scenario_id.replace("-", "").replace("_", "").isalnum():
            raise DemoReplayError(f"invalid replay scenario id: {scenario_id!r}")
        if scenario_id in scenarios:
            raise DemoReplayError(f"duplicate replay scenario id: {scenario_id!r}")
        bundle_path = _safe_bundle_path(base, str(entry.get("bundle") or ""))
        try:
            bundle = load_bundle(bundle_path)
            replay = ReplayBundle(bundle)
        except ReplayBundleError as exc:
            raise DemoReplayError(f"replay scenario {scenario_id!r} is invalid: {exc}") from exc
        task = bundle.get("task", {}) if isinstance(bundle.get("task"), dict) else {}
        declared_type = str(entry.get("task_type") or task.get("type") or "")
        if not declared_type or str(task.get("type")) != declared_type:
            raise DemoReplayError(
                f"replay scenario {scenario_id!r} declares task type {declared_type!r} "
                f"but its bundle captures {task.get('type')!r}"
            )
        scenarios[scenario_id] = DemoReplayScenario(
            id=scenario_id,
            title=str(entry.get("title") or task.get("display_name") or scenario_id),
            summary=str(entry.get("summary") or ""),
            task_type=declared_type,
            provenance=_provenance_kind(bundle),
            capture_source=_capture_source(bundle),
            bundle_digest=str(bundle.get("bundle_digest") or ""),
            bundle=replay,
        )
    return scenarios


def replay_root(server_dir: str) -> Path:
    return Path(server_dir) / DEMO_REPLAYS_SUBDIR
