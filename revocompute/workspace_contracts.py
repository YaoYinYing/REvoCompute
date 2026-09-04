# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Generic workspace contribution invocation."""
from __future__ import annotations
from typing import Any, Callable
from pathlib import Path
import importlib.util

_BACKENDS: dict[str, tuple[Callable[..., Any], Callable[..., Any] | None]] = {}

class WorkspaceValidationError(ValueError):
    """A user-correctable workspace normalization or validation failure."""

def normalize_capability(normalizer: Callable[[Any], dict[str, Any]], value: Any) -> dict[str, Any]:
    """Invoke a trusted runner-owned normalizer."""
    try:
        result = normalizer(value)
    except WorkspaceValidationError:
        raise
    except (TypeError, ValueError) as exc:
        raise WorkspaceValidationError(str(exc)) from exc
    if not isinstance(result, dict):
        raise WorkspaceValidationError("Workspace normalizer must return an object")
    return result

def validate_capability(validator: Callable[[dict[str, Any], str | None], Any], normalized: dict[str, Any], primary_path: str | None) -> None:
    """Invoke an optional trusted runner-owned validator."""
    try:
        validator(normalized, primary_path)
    except WorkspaceValidationError:
        raise
    except (TypeError, ValueError) as exc:
        raise WorkspaceValidationError(str(exc)) from exc
def register_backend(identifier: str, normalizer: Callable[..., Any], validator: Callable[..., Any] | None = None) -> None:
    _BACKENDS[identifier] = (normalizer, validator)

def backend(identifier: str) -> tuple[Callable[..., Any], Callable[..., Any] | None] | None:
    return _BACKENDS.get(identifier)

# Transitional import surface for callers that imported the old helpers. The
# implementation remains in the runner-owned contribution module.
def _runner_backend():
    path = Path(__file__).resolve().parents[1] / "docker/runners/placer-rfdiffusion/workspace/regions/backend.py"
    spec = importlib.util.spec_from_file_location("rfdiffusion_workspace_backend", path)
    if spec is None or spec.loader is None:
        raise ImportError("runner workspace backend unavailable")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module

def normalize_rfdiffusion(value: Any) -> dict[str, Any]:
    try:
        return _runner_backend().normalize_rfdiffusion(value)
    except ValueError as exc:
        raise WorkspaceValidationError(str(exc)) from exc

def validate_rfdiffusion_structure(normalized: dict[str, Any], primary_path: str | None) -> None:
    try:
        return _runner_backend().validate_rfdiffusion_structure(normalized, primary_path)
    except ValueError as exc:
        raise WorkspaceValidationError(str(exc)) from exc

def parse_contig(raw: str):
    return _runner_backend().parse_contig(raw)

def serialize_contig(segments):
    return _runner_backend().serialize_contig(segments)
