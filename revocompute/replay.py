# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Serve a validated replay bundle as the frontend-visible result surface.

The bundle captures bytes; this class turns them into the same bounded
sub-resources a real deployment serves — the ResultManifest response, task-scoped
artifact/download routes, a logical-file projection, paged table and numeric
projection routes, and the storyboard module. A request for a task other than the
one the bundle captures resolves to nothing, so the router returns the same 404 a
real Server would. It never fabricates bytes: every payload comes from the
capture, and it is served only when its bytes still match the captured sha256.
"""

from __future__ import annotations

import io
import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .ndarray import MAX_PROJECTION_ELEMENTS
from .replay_bundle import ReplayBundleError, load_bundle, payload_bytes
from .result_projection import (
    ResultPreviewError,
    read_bounded_array_projection,
    read_table_page,
)


class ReplayBundle:
    """A validated replay bundle bound to the task id it answers for."""

    def __init__(self, document: Mapping[str, Any], *, task_id: str | None = None) -> None:
        bundle = load_bundle(document)
        self.task_id = str(task_id or bundle["task"]["id"]).lower()
        if self.task_id != str(bundle["task"]["id"]).lower():
            raise ReplayBundleError("replay bundle is bound to a different task id")
        self.bundle = bundle
        self.manifest: dict[str, Any] = json.loads(json.dumps(bundle["response"]))
        self.provenance: dict[str, Any] = dict(bundle.get("provenance") or {})

    @classmethod
    def load(cls, path: str | Path, *, task_id: str | None = None) -> ReplayBundle:
        """Load, validate, and bind a bundle persisted by the capture path."""
        return cls(load_bundle(path), task_id=task_id)

    # -- manifest -----------------------------------------------------------

    def served_manifest(self, task_id: str | None = None) -> dict[str, Any] | None:
        """The exact ResultManifest response for ``task_id``, or ``None``."""
        if task_id is not None and task_id.lower() != self.task_id:
            return None
        return json.loads(json.dumps(self.manifest))

    # -- artifact and logical-file bytes ------------------------------------

    def payload(self, path: str | None) -> tuple[bytes, str] | None:
        """Return ``(bytes, media_type)`` for one captured artifact path."""
        if not path:
            return None
        entry = self.bundle.get("payloads", {}).get(path)
        if not isinstance(entry, Mapping):
            return None
        return payload_bytes(entry), str(entry.get("media_type") or "application/octet-stream")

    def logical_artifact_path(self, file_id: str, index: int) -> str | None:
        """Return the artifact path behind one logical file entry, or ``None``.

        Resolved from the captured logical-file map, never guessed from a name:
        the served manifest's logical entries carry only a ``url``, so the
        bundle keeps the published path/sha256/size identity separately.
        """
        entries = (self.bundle.get("logical_files") or {}).get(file_id, [])
        if not 0 <= index < len(entries):
            return None
        return str(entries[index]["path"])

    def storyboard_source(self, asset: str) -> str | None:
        captured = self.manifest.get("storyboard")
        if not isinstance(captured, Mapping) or asset != captured.get("entrypoint"):
            return None
        storyboard = self.bundle.get("storyboard")
        return storyboard.get("source") if isinstance(storyboard, Mapping) else None

    # -- bounded table and projection routes --------------------------------

    def declares_table(self, path: str) -> bool:
        """Whether the captured manifest declares ``path`` as a table artifact.

        The replay never infers a table from a file extension: the same
        manifest capability the live result route requires is what admits a
        recorded artifact to the paging route.
        """
        for artifact in self.manifest.get("artifacts") or []:
            if isinstance(artifact, Mapping) and artifact.get("path") == path:
                return artifact.get("capability") == "table" or artifact.get("preview") == "table"
        return False

    def table_page(
        self,
        path: str,
        *,
        offset: int = 0,
        limit: int = 100,
        matrix: bool = False,
        strict: bool = False,
    ) -> dict[str, Any] | None:
        """Page a captured table artifact through the Server's bounded reader.

        By default this is the recorded-bytes contract the replay fixture
        harness has always used: a captured payload is paged whatever the live
        route's current width/cell/page caps would say, and any refusal is
        ``None`` (the caller's 404) because a recorded result must remain
        renderable after the live caps tighten. ``strict=True`` is the live
        result route's contract -- the artifact must be manifest-declared as a
        table, the caps apply, and a refusal raises
        :class:`ResultPreviewError` so a demo route can answer the bounded 400.
        """
        body = self.payload(path)
        if body is None:
            return None
        try:
            return read_table_page(
                io.BytesIO(body[0]),
                name=path,
                offset=offset,
                limit=limit,
                matrix=matrix,
                declared_table=self.declares_table(path),
                bounded=strict,
            )
        except ResultPreviewError:
            if strict:
                raise
            return None

    def projection(
        self,
        path: str,
        *,
        kind: str = "numeric",
        key: str | None = None,
        max_elements: int = MAX_PROJECTION_ELEMENTS,
        strict: bool = False,
    ) -> dict[str, Any] | None:
        """Project a captured artifact through the Server's own bounded reader.

        Delegates to ``revocompute.ndarray.read_array_projection`` -- the function
        the ``GET .../ndarrays/<path>`` route serves through -- so a replayed
        projection has the Server's shape, dtype, null, and NPY/NPZ semantics
        rather than a harness approximation.

        By default a projection the live route would refuse (an unsafe path, an
        element/byte overflow, an unsupported artifact) is ``None`` (the
        caller's 404): a storyboard legitimately probes optional fields and
        handles an absent projection, and a recorded result must keep rendering
        after the live bounds tighten. ``strict=True`` raises
        :class:`ResultPreviewError` with the live route's message instead, which
        is what the demo route answers as a bounded 400.
        """
        body = self.payload(path)
        if body is None:
            return None
        with tempfile.NamedTemporaryFile(suffix=os.path.splitext(path)[1].lower()) as stream:
            stream.write(body[0])
            stream.flush()
            stream.seek(0)
            try:
                return read_bounded_array_projection(
                    stream, name=path, key=key, kind=kind, max_elements=max_elements
                )
            except ResultPreviewError:
                if strict:
                    raise
                return None

