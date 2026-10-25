# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Validate a payload against the canonical OpenAPI components.

The OpenAPI document is the published contract for the browser-facing API. A
replay bundle carries a served ResultManifest, so the bundle loader checks it
against the same component the Server publishes instead of trusting the bytes it
was handed. The frontend fixture harness imports this function too, so a fixture
and a replay bundle cannot disagree about what the contract is.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_SPEC_PATH = Path(__file__).resolve().parent / "static" / "openapi.json"


@lru_cache(maxsize=1)
def openapi_spec() -> dict[str, Any]:
    return json.loads(_SPEC_PATH.read_text(encoding="utf-8"))


class ContractViolation(AssertionError):
    """A payload does not satisfy the published OpenAPI component."""


def validate_openapi_payload(schema_name: str, payload: object) -> None:
    """Raise :class:`ContractViolation` naming the first contract violation."""
    from jsonschema import Draft202012Validator

    spec = openapi_spec()
    validator = Draft202012Validator(
        {"$ref": f"#/components/schemas/{schema_name}", "components": spec["components"]},
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )
    errors = sorted(validator.iter_errors(payload), key=lambda error: list(error.absolute_path))
    if errors:
        first = errors[0]
        location = "/".join(str(part) for part in first.absolute_path) or "<root>"
        raise ContractViolation(
            f"{schema_name} payload violates the canonical contract at {location}: {first.message}"
        )
