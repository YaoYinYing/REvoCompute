# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Generic workspace contribution invocation."""
from __future__ import annotations
from typing import Any, Callable

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
