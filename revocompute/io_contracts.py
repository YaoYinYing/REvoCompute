# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Generic named file-role contracts shared by Tasks and Tools."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, TypeVar

ROLE_ID_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
FORMAT_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9_+-]{0,31}\Z")


@dataclass(frozen=True)
class FileRolePresence:
    """A role's cardinality when one task parameter selects a value.

    The owning Task declares this because a JSON Schema parameter rule cannot
    see uploaded files: the schema validates ``params`` only. ``required_when``
    values make the role mandatory; ``forbidden_when`` values make it refuse any
    file. Values outside both sets keep the role's static cardinality.
    """

    parameter: str
    required_when: tuple[str, ...] = ()
    forbidden_when: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "parameter": self.parameter,
            "required_when": list(self.required_when),
            "forbidden_when": list(self.forbidden_when),
        }


@dataclass(frozen=True)
class NamedFileRole:
    """One stable logical role for a bounded collection of typed files."""

    name: str
    title: str
    type: str
    formats: tuple[str, ...]
    minimum: int
    maximum: int
    description: str = ""
    presence: FileRolePresence | None = None

    def cardinality(self, parameters: Mapping[str, Any]) -> tuple[int, int]:
        """The role's effective min/max for one resolved parameter object."""
        minimum, maximum = self.minimum, self.maximum
        if self.presence is None:
            return minimum, maximum
        value = parameters.get(self.presence.parameter)
        if value is None:
            return minimum, maximum
        selected = str(value)
        if selected in self.presence.required_when:
            minimum = max(minimum, 1)
        elif selected in self.presence.forbidden_when:
            maximum = 0
        return minimum, maximum

    @property
    def extensions(self) -> tuple[str, ...]:
        return tuple(f".{format_name}" for format_name in self.formats)


RoleT = TypeVar("RoleT", bound=NamedFileRole)


def load_named_file_roles(
    raw: Any,
    *,
    owner: str,
    collection: str,
    factory: Callable[..., RoleT] = NamedFileRole,
) -> tuple[RoleT, ...]:
    """Parse the shared named-role vocabulary without assigning domain semantics."""
    if not isinstance(raw, Mapping):
        raise ValueError(f"{owner} {collection} must be a mapping")
    roles: list[RoleT] = []
    for name, definition in raw.items():
        if not isinstance(name, str) or not ROLE_ID_PATTERN.fullmatch(name) or not isinstance(definition, Mapping):
            raise ValueError(f"{owner} contains an invalid {collection} role")
        unknown = set(definition) - {"title", "type", "formats", "cardinality", "description", "presence"}
        if unknown:
            raise ValueError(f"{owner} {collection} role {name!r} contains unknown fields: {sorted(unknown)}")
        logical_type = definition.get("type")
        formats = definition.get("formats")
        cardinality = definition.get("cardinality")
        if not isinstance(logical_type, str) or not ROLE_ID_PATTERN.fullmatch(logical_type):
            raise ValueError(f"{owner} {collection} role {name!r} must declare a logical type")
        if (
            not isinstance(formats, list)
            or not formats
            or not all(isinstance(value, str) and FORMAT_ID_PATTERN.fullmatch(value) for value in formats)
            or len(set(formats)) != len(formats)
        ):
            raise ValueError(f"{owner} {collection} role {name!r} formats must be unique format IDs")
        if not isinstance(cardinality, Mapping) or set(cardinality) != {"min", "max"}:
            raise ValueError(f"{owner} {collection} role {name!r} must declare min/max cardinality")
        minimum, maximum = cardinality["min"], cardinality["max"]
        if (
            not isinstance(minimum, int)
            or isinstance(minimum, bool)
            or not isinstance(maximum, int)
            or isinstance(maximum, bool)
            or minimum < 0
            or maximum < minimum
            or maximum < 1
        ):
            raise ValueError(f"{owner} {collection} role {name!r} has invalid cardinality")
        presence = _load_role_presence(definition.get("presence"), owner, collection, name)
        if presence is not None and presence.required_when and maximum < 1:
            raise ValueError(
                f"{owner} {collection} role {name!r} presence requires a file but its maximum is 0"
            )
        if presence is not None and presence.forbidden_when and minimum > 0:
            raise ValueError(
                f"{owner} {collection} role {name!r} presence forbids files but its minimum is {minimum}"
            )
        roles.append(
            factory(
                name=name,
                title=str(definition.get("title") or name.replace("_", " ").title()),
                type=logical_type,
                formats=tuple(formats),
                minimum=minimum,
                maximum=maximum,
                description=str(definition.get("description") or ""),
                presence=presence,
            )
        )
    return tuple(roles)


def _load_role_presence(
    raw: Any, owner: str, collection: str, role_name: str
) -> FileRolePresence | None:
    """Parse the optional parameter-conditioned cardinality of one role."""
    if raw is None:
        return None
    if not isinstance(raw, Mapping) or set(raw) != {"parameter", "required_when", "forbidden_when"}:
        raise ValueError(
            f"{owner} {collection} role {role_name!r} presence must declare "
            "parameter, required_when and forbidden_when"
        )
    parameter = raw["parameter"]
    if not isinstance(parameter, str) or not ROLE_ID_PATTERN.fullmatch(parameter):
        raise ValueError(f"{owner} {collection} role {role_name!r} presence parameter must be a parameter id")

    def values(field_name: str) -> tuple[str, ...]:
        raw_values = raw[field_name]
        if (
            not isinstance(raw_values, list)
            or not raw_values
            or not all(isinstance(item, str) and item for item in raw_values)
            or len(set(raw_values)) != len(raw_values)
        ):
            raise ValueError(
                f"{owner} {collection} role {role_name!r} presence {field_name} must be unique non-empty strings"
            )
        return tuple(raw_values)

    required_when = values("required_when")
    forbidden_when = values("forbidden_when")
    overlap = set(required_when) & set(forbidden_when)
    if overlap:
        raise ValueError(
            f"{owner} {collection} role {role_name!r} presence cannot require and forbid {sorted(overlap)}"
        )
    return FileRolePresence(parameter, required_when, forbidden_when)
