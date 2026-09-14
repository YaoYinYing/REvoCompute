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
class NamedFileRole:
    """One stable logical role for a bounded collection of typed files."""

    name: str
    title: str
    type: str
    formats: tuple[str, ...]
    minimum: int
    maximum: int
    description: str = ""

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
        unknown = set(definition) - {"title", "type", "formats", "cardinality", "description"}
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
        roles.append(
            factory(
                name=name,
                title=str(definition.get("title") or name.replace("_", " ").title()),
                type=logical_type,
                formats=tuple(formats),
                minimum=minimum,
                maximum=maximum,
                description=str(definition.get("description") or ""),
            )
        )
    return tuple(roles)
