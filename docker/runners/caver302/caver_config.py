# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Render a CAVER 3.0.2 configuration and command line from typed parameters.

The owning ``task.yaml`` is the only place parameter names, defaults and help
text live; the server resolves them once and passes the values in ``task.json``.
This module is the security boundary around the CAVER process: it accepts only
an allowlisted key set, validates every value against the pinned upstream
constraint, and emits a fixed-order configuration file. No caller-supplied text
is ever copied into the file verbatim, and the process is started from an argv
list, never through a shell.
"""

from __future__ import annotations

import math
import re

from pdb_selection import StartPoint

FLOAT_PARAMETERS = {
    "probe_radius": "exclusive",
    "shell_radius": "exclusive",
    "shell_depth": "exclusive",
    "weighting_coefficient": "exclusive",
    "clustering_threshold": "nonnegative",
    "exclude_start_zone": "nonnegative",
    "exclude_end_zone": "nonnegative",
    "min_middle_zone": "nonnegative",
    "max_limiting_radius": "nonnegative",
    "cost_function_exponent": "nonnegative",
    "max_distance": "nonnegative",
    "desired_radius": "nonnegative",
    "automatic_shell_radius_bottleneck_multiplier": "exclusive",
    "starting_point_protection_radius": "nonnegative",
    "residue_contact_distance": "exclusive",
    "bottleneck_contact_distance": "exclusive",
}
INTEGER_PARAMETERS = {
    "first_frame": 1,
    "last_frame": 1,
    "time_sparsity": 1,
    "max_output_clusters": 1,
    "max_number_of_tunnels": 1,
}
ENUM_PARAMETERS = {
    "one_tunnel_in_snapshot": ("cheapest", "random", "no"),
}
BOOLEAN_PARAMETERS = {"automatic_shell_radius"}
NUMBER_OF_APPROXIMATING_BALLS = (4, 6, 8, 12, 20)
SEED_RANGE = (-2_147_483_648, 2_147_483_647)
TEXT_PARAMETERS = {"exclude_residue_ids", "exclude_residue_names", "exclude_atom_numbers"}

START_POINT_PARAMETERS = {
    "start_point_mode",
    "start_x",
    "start_y",
    "start_z",
    "start_chain",
    "start_residue_number",
    "start_atom_name",
    "start_altloc",
    "start_residue_name",
    "start_group",
}

#: Every parameter the Runner accepts. Anything else is a contract error.
ALLOWED_PARAMETERS = (
    set(FLOAT_PARAMETERS)
    | set(INTEGER_PARAMETERS)
    | set(ENUM_PARAMETERS)
    | BOOLEAN_PARAMETERS
    | TEXT_PARAMETERS
    | START_POINT_PARAMETERS
    | {"number_of_approximating_balls", "seed"}
)

#: CAVER's residue identifiers are a plain list (CHAIN:NUMBER or NUMBER); the
#: upstream parser never matches an insertion code, so one is a contract error.
_RESIDUE_ID = re.compile(r"^(?:[A-Za-z0-9]:)?[0-9]+$")
_RESIDUE_NAME = re.compile(r"^[A-Za-z0-9]{1,4}$")
_ATOM_NUMBER = re.compile(r"^[0-9]+(?:-[0-9]+)?$")
_JAVA_HEAP = re.compile(r"^[1-9][0-9]{0,4}[mMgG]$")


class ConfigError(ValueError):
    """The resolved parameters cannot produce a safe CAVER configuration."""


def _finite(value: object, name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ConfigError(f"{name} must be a finite number")
    return float(value)


def _number(params: dict[str, object], name: str) -> float:
    value = _finite(params.get(name), name)
    if FLOAT_PARAMETERS[name] == "exclusive" and value <= 0:
        raise ConfigError(f"{name} must be greater than zero")
    if FLOAT_PARAMETERS[name] == "nonnegative" and value < 0:
        raise ConfigError(f"{name} must not be negative")
    return value


def _integer(params: dict[str, object], name: str, minimum: int) -> int:
    value = params.get(name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigError(f"{name} must be an integer")
    if value < minimum:
        raise ConfigError(f"{name} must be at least {minimum}")
    return value


def _enum(params: dict[str, object], name: str) -> str:
    value = params.get(name)
    allowed = ENUM_PARAMETERS[name]
    if value not in allowed:
        raise ConfigError(f"{name} must be one of: {', '.join(allowed)}")
    return str(value)


def _boolean(params: dict[str, object], name: str) -> bool:
    value = params.get(name)
    if not isinstance(value, bool):
        raise ConfigError(f"{name} must be a boolean")
    return value


def _tokens(params: dict[str, object], name: str, pattern: re.Pattern[str]) -> str:
    """Validate a whitespace/comma separated token list and render it space-joined."""
    raw = params.get(name, "")
    if not isinstance(raw, str):
        raise ConfigError(f"{name} must be text")
    tokens = [token for token in re.split(r"[,\s]+", raw.strip()) if token]
    for token in tokens:
        if not pattern.fullmatch(token):
            raise ConfigError(f"{name} contains an invalid token: {token!r}")
    return " ".join(tokens)


def render_config(params: dict[str, object], start_point: StartPoint) -> str:
    """Render the allowlisted CAVER configuration in a fixed key order."""
    unknown = sorted(set(params) - ALLOWED_PARAMETERS)
    if unknown:
        raise ConfigError(f"unsupported CAVER parameters: {', '.join(unknown)}")
    if not start_point.directives:
        raise ConfigError("the resolved start point produced no CAVER directive")

    first_frame = _integer(params, "first_frame", 1)
    last_frame = _integer(params, "last_frame", 1)
    if last_frame < first_frame:
        raise ConfigError("last_frame must not be smaller than first_frame")

    def number_line(name: str) -> str:
        return f"{name} {_number(params, name):g}"

    lines = [
        "# Generated by the REvoCompute CAVER Runner from server-resolved parameters.",
        "load_tunnels no",
        "load_cluster_tree no",
        "stop_after never",
        f"time_sparsity {_integer(params, 'time_sparsity', 1)}",
        f"first_frame {first_frame}",
        f"last_frame {last_frame}",
    ]
    lines.extend(f"{directive} {value}" for directive, value in start_point.directives)
    lines.extend(number_line(name) for name in ("probe_radius", "shell_radius", "shell_depth"))
    # Only average-link clustering produces tunnel clusters; upstream's matrix
    # mode stops at the distance matrix and publishes no tables, so it is not
    # offered as a value that would always fail.
    lines.append("clustering average_link")
    lines.extend(number_line(name) for name in ("weighting_coefficient", "clustering_threshold"))
    lines.extend(number_line(name) for name in ("exclude_start_zone", "exclude_end_zone", "min_middle_zone"))
    lines += [
        "save_zones yes",
        f"one_tunnel_in_snapshot {_enum(params, 'one_tunnel_in_snapshot')}",
        f"max_output_clusters {_integer(params, 'max_output_clusters', 1)}",
        "save_dynamics_visualization no",
        "generate_summary yes",
        "generate_tunnel_characteristics yes",
        "generate_tunnel_profiles yes",
        "generate_histograms no",
        "generate_bottleneck_heat_map no",
        "generate_profile_heat_map no",
        # The Task's result contract publishes tunnel-lining and bottleneck
        # residues, so both are on even though upstream defaults them off.
        "compute_tunnel_residues yes",
        number_line("residue_contact_distance"),
        "compute_bottleneck_residues yes",
        number_line("bottleneck_contact_distance"),
    ]
    balls = params.get("number_of_approximating_balls")
    if balls not in NUMBER_OF_APPROXIMATING_BALLS:
        raise ConfigError(f"number_of_approximating_balls must be one of {NUMBER_OF_APPROXIMATING_BALLS}")
    lines += [
        f"number_of_approximating_balls {balls}",
        "add_central_sphere yes",
        f"max_number_of_tunnels {_integer(params, 'max_number_of_tunnels', 1)}",
        number_line("max_limiting_radius"),
        number_line("cost_function_exponent"),
        f"automatic_shell_radius {'yes' if _boolean(params, 'automatic_shell_radius') else 'no'}",
        number_line("automatic_shell_radius_bottleneck_multiplier"),
        number_line("starting_point_protection_radius"),
        number_line("max_distance"),
        number_line("desired_radius"),
        "generate_trajectory no",
        # Bounded inputs run without CAVER's disk-backed swap so a Task cannot
        # fill the scratch filesystem; provenance records the deviation.
        "swap no",
    ]
    for name, pattern in (
        ("exclude_residue_ids", _RESIDUE_ID),
        ("exclude_residue_names", _RESIDUE_NAME),
        ("exclude_atom_numbers", _ATOM_NUMBER),
    ):
        rendered = _tokens(params, name, pattern)
        if rendered:
            lines.append(f"{name} {rendered}")
    seed = params.get("seed")
    if not isinstance(seed, int) or isinstance(seed, bool) or not SEED_RANGE[0] <= seed <= SEED_RANGE[1]:
        raise ConfigError("seed must be a 32-bit signed integer")
    lines.append(f"seed {seed}")
    return "\n".join(lines) + "\n"


def build_command(
    *,
    java: str,
    heap: str,
    library_dir: str,
    jar: str,
    home: str,
    pdb_dir: str,
    config: str,
    output_dir: str,
    tmp_dir: str,
) -> list[str]:
    """Build the CAVER argv with a bounded heap and an isolated JVM temp directory."""
    if not _JAVA_HEAP.fullmatch(heap):
        raise ConfigError("Java heap must be a positive size such as 1200m or 4g")
    return [
        java,
        f"-Xmx{heap}",
        f"-Djava.io.tmpdir={tmp_dir}",
        "-cp",
        library_dir,
        "-jar",
        jar,
        "-home",
        home,
        "-pdb",
        pdb_dir,
        "-conf",
        config,
        "-out",
        output_dir,
    ]


__all__ = [
    "ALLOWED_PARAMETERS",
    "ConfigError",
    "build_command",
    "render_config",
]
