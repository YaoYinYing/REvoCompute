# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Generic workspace contribution invocation."""
from __future__ import annotations
from typing import Any, Callable

class WorkspaceValidationError(ValueError):
    """A user-correctable workspace normalization or validation failure."""

def validate_selected_residues(value: Any) -> None:
    """Validate authored residue identity without assigning scientific meaning."""
    if not isinstance(value, dict) or "selected_residues" not in value:
        return
    residues = value["selected_residues"]
    if not isinstance(residues, list):
        raise WorkspaceValidationError("Selected residues must be a list")
    addresses: dict[tuple[str, int, str], tuple[str, bool]] = {}
    for index, residue in enumerate(residues):
        if not isinstance(residue, dict):
            raise WorkspaceValidationError(f"Selected residue {index + 1} must be an object")
        chain_value, number = residue.get("auth_chain"), residue.get("auth_seq_id")
        insertion_value, name, hetero = (
            residue.get("insertion_code"), residue.get("residue_name"), residue.get("hetero")
        )
        if not isinstance(chain_value, str) or not chain_value.strip():
            raise WorkspaceValidationError(f"Selected residue {index + 1} needs a non-empty authored chain")
        if isinstance(number, bool) or not isinstance(number, int):
            raise WorkspaceValidationError(f"Selected residue {index + 1} needs an integer authored residue number")
        if insertion_value is not None and not isinstance(insertion_value, str):
            raise WorkspaceValidationError(f"Selected residue {index + 1} has an invalid insertion code")
        if not isinstance(name, str) or not name.strip():
            raise WorkspaceValidationError(f"Selected residue {index + 1} needs an authored residue name")
        if not isinstance(hetero, bool):
            raise WorkspaceValidationError(f"Selected residue {index + 1} needs a boolean hetero flag")
        # Whitespace in the authored address is not a distinct residue: key on
        # the stripped chain/insertion so "A " and "A" cannot both be admitted.
        address = (chain_value.strip(), number, (insertion_value or "").strip())
        identity = (name.strip(), hetero)
        if address in addresses:
            if addresses[address] != identity:
                raise WorkspaceValidationError(
                    "The molecular selection names conflicting identities at one authored address"
                )
            raise WorkspaceValidationError("The molecular selection contains an ambiguous duplicate residue")
        addresses[address] = identity

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

def validate_capability(
    validator: Callable[[dict[str, Any], dict[str, tuple[str, ...]]], Any],
    normalized: dict[str, Any],
    input_paths: dict[str, tuple[str, ...]],
) -> None:
    """Invoke an optional trusted runner-owned validator."""
    try:
        validator(normalized, input_paths)
    except WorkspaceValidationError:
        raise
    except (TypeError, ValueError) as exc:
        raise WorkspaceValidationError(str(exc)) from exc
