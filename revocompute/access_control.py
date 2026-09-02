# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Declarative Runner access policies and centralized admission checks."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

import yaml

_IDENTIFIER = re.compile(r"[a-z][a-z0-9_-]{1,63}$")


@dataclass(frozen=True)
class AccessPolicy:
    id: str
    label: str
    description: str
    requires: tuple[str, ...]
    requestable: bool
    notice: dict[str, str] | None = None
    license: dict[str, str] | None = None


_policies: dict[str, AccessPolicy] = {}


def valid_identifier(value: Any) -> bool:
    return isinstance(value, str) and bool(_IDENTIFIER.fullmatch(value))


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Access policy {field} must be non-empty text")
    return value.strip()


def _optional_metadata(value: Any, field: str) -> dict[str, str] | None:
    if value is None:
        return None
    allowed = {"title", "summary"} if field == "notice" else {"name", "url"}
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError(f"Access policy {field} has unknown fields")
    result = {key: _required_text(item, f"{field}.{key}") for key, item in value.items()}
    if field == "license" and "url" in result and not result["url"].startswith(("https://", "http://")):
        raise ValueError("Access policy license.url must use http or https")
    return result


def load_policies(directory: str) -> None:
    """Load strictly validated policy YAML files from *directory*."""
    loaded: dict[str, AccessPolicy] = {}
    if not os.path.isdir(directory):
        _policies.clear()
        return
    for filename in sorted(os.listdir(directory)):
        if not filename.endswith((".yaml", ".yml")):
            continue
        path = os.path.join(directory, filename)
        with open(path, encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)  # skipcq: PTC-W6004 -- operator-owned configuration
        allowed = {"id", "label", "description", "requires", "match", "requestable", "notice", "license"}
        if not isinstance(raw, dict) or set(raw) - allowed:
            raise ValueError(f"Access policy {filename!r} has unknown keys")
        missing = {"id", "label", "description", "requires", "match", "requestable"} - set(raw)
        if missing:
            raise ValueError(f"Access policy {filename!r} is missing fields: {sorted(missing)}")
        policy_id = raw["id"]
        requires = raw["requires"]
        if not valid_identifier(policy_id):
            raise ValueError(f"Invalid access policy identifier: {policy_id!r}")
        if policy_id in loaded:
            raise ValueError(f"Duplicate access policy identifier: {policy_id!r}")
        if (
            not isinstance(requires, list)
            or not requires
            or not all(valid_identifier(item) for item in requires)
            or len(requires) != len(set(requires))
        ):
            raise ValueError(f"Access policy {policy_id!r} requires valid, unique entitlement identifiers")
        if raw["match"] != "all":
            raise ValueError(f"Access policy {policy_id!r} match must be 'all'")
        if not isinstance(raw["requestable"], bool):
            raise ValueError(f"Access policy {policy_id!r} requestable must be a boolean")
        loaded[policy_id] = AccessPolicy(
            id=policy_id,
            label=_required_text(raw["label"], f"{policy_id}.label"),
            description=_required_text(raw["description"], f"{policy_id}.description"),
            requires=tuple(requires),
            requestable=raw["requestable"],
            notice=_optional_metadata(raw.get("notice"), "notice"),
            license=_optional_metadata(raw.get("license"), "license"),
        )
    _policies.clear()
    _policies.update(loaded)


def get_policy(policy_id: str) -> AccessPolicy:
    try:
        return _policies[policy_id]
    except KeyError:
        raise KeyError(f"Unknown access policy: {policy_id!r}") from None


def list_policies() -> list[AccessPolicy]:
    return list(_policies.values())


def declared_entitlements(*, requestable_only: bool = False) -> set[str]:
    return {
        entitlement
        for policy in _policies.values()
        if not requestable_only or policy.requestable
        for entitlement in policy.requires
    }


def policy_state(policy: AccessPolicy, database: Any, user_id: int | None) -> dict[str, Any]:
    effective = database.get_effective_entitlements(user_id) if user_id is not None else set()
    pending = database.get_pending_access_requests(user_id) if user_id is not None else []
    pending_ids = {item["entitlement"] for item in pending}
    missing = [item for item in policy.requires if item not in effective]
    pending_missing = [item for item in missing if item in pending_ids]
    requestable_missing = [item for item in missing if item not in pending_ids] if policy.requestable else []
    return {
        "restricted": True,
        "policy_id": policy.id,
        "label": policy.label,
        "description": policy.description,
        "requires": list(policy.requires),
        "requestable": policy.requestable,
        "granted": not missing,
        "request_status": "pending" if pending_missing else None,
        "missing_entitlements": missing,
        "requestable_entitlements": requestable_missing,
        "notice": policy.notice,
        "license": policy.license,
    }


def authorize(policy: AccessPolicy | None, database: Any, user_id: int) -> tuple[bool, dict[str, Any] | None]:
    if policy is None:
        return True, None
    missing = [item for item in policy.requires if not database.has_entitlement(user_id, item)]
    if not missing:
        return True, None
    return False, {
        "error": "Runner access required",
        "policy_id": policy.id,
        "requestable": policy.requestable,
    }
