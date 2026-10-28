# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Config and argv construction for the CAVER Runner.

These tests pin the two things a Runner must never get wrong when it drives a
third-party JAR: the generated configuration contains only allowlisted,
validated upstream keys, and the process is an argv list with a bounded heap.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
FAMILY = ROOT / "docker/runners/caver302"
sys.path.insert(0, str(FAMILY))

from caver_config import ConfigError, build_command, render_config  # noqa: E402
from caver_params import BASE_PARAMS  # noqa: E402
from pdb_selection import StartPoint  # noqa: E402


def point() -> StartPoint:
    return StartPoint(4.0, 4.0, 4.0, {}, (("starting_point_coordinates", "4.000 4.000 4.000"),))


def test_renders_only_allowlisted_keys_with_the_selected_start_point() -> None:
    text = render_config(dict(BASE_PARAMS), point())
    lines = text.splitlines()
    assert "starting_point_coordinates 4.000 4.000 4.000" in lines
    assert "probe_radius 0.9" in lines
    assert "shell_radius 3" in lines
    assert "clustering_threshold 2" in lines
    assert "compute_tunnel_residues yes" in lines
    assert "compute_bottleneck_residues yes" in lines
    assert "swap no" in lines
    assert "seed 1" in lines
    assert lines[-1] == "seed 1"
    assert not any(line.startswith(("exclude_residue", "exclude_atom")) for line in lines)


def test_renders_residue_directive_and_exclusion_lists() -> None:
    params = dict(BASE_PARAMS)
    params.update(
        {
            "exclude_residue_ids": "A:24B, 5-15",
            "exclude_residue_names": "HOH SO4",
            "exclude_atom_numbers": "6,3115-3140",
        }
    )
    residue = StartPoint(1.0, 2.0, 3.0, {}, (("starting_point_residue", "A:146"),))
    lines = render_config(params, residue).splitlines()
    assert "starting_point_residue A:146" in lines
    assert "exclude_residue_ids A:24B 5-15" in lines
    assert "exclude_residue_names HOH SO4" in lines
    assert "exclude_atom_numbers 6 3115-3140" in lines


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"surprise": 1}, "unsupported CAVER parameters"),
        ({"probe_radius": float("nan")}, "finite number"),
        ({"probe_radius": 0}, "greater than zero"),
        ({"clustering_threshold": -1}, "not be negative"),
        ({"clustering": "single_link"}, "must be one of"),
        ({"one_tunnel_in_snapshot": "every"}, "must be one of"),
        ({"first_frame": 0}, "at least 1"),
        ({"first_frame": 1.5}, "must be an integer"),
        ({"seed": 2**31}, "32-bit signed"),
        ({"number_of_approximating_balls": 7}, "must be one of"),
        ({"automatic_shell_radius": "yes"}, "must be a boolean"),
        ({"exclude_residue_ids": "A:1; rm -rf /"}, "invalid token"),
        ({"exclude_residue_names": "TOOLONGNAME"}, "invalid token"),
        ({"exclude_atom_numbers": "1-2-3"}, "invalid token"),
        ({"exclude_residue_ids": "line\nbreak"}, "invalid token"),
    ],
)
def test_rejects_unsafe_or_invalid_values(override: dict[str, object], message: str) -> None:
    params = {**BASE_PARAMS, **override}
    with pytest.raises(ConfigError, match=message):
        render_config(params, point())


def test_builds_an_argv_list_with_a_bounded_heap_and_isolated_temp() -> None:
    argv = build_command(
        java="java",
        heap="1200m",
        library_dir="/opt/caver302/caver/lib",
        jar="/opt/caver302/caver/caver.jar",
        home="/opt/caver302/caver",
        pdb_dir="/tmp/work/pdbs",
        config="/tmp/work/config.txt",
        output_dir="/tmp/work/caver_out",
        tmp_dir="/tmp/work/tmp",
    )
    assert argv == [
        "java",
        "-Xmx1200m",
        "-Djava.io.tmpdir=/tmp/work/tmp",
        "-cp",
        "/opt/caver302/caver/lib",
        "-jar",
        "/opt/caver302/caver/caver.jar",
        "-home",
        "/opt/caver302/caver",
        "-pdb",
        "/tmp/work/pdbs",
        "-conf",
        "/tmp/work/config.txt",
        "-out",
        "/tmp/work/caver_out",
    ]


@pytest.mark.parametrize("heap", ["0m", "abc", "4", "-1g", "4g; rm -rf /"])
def test_rejects_an_unbounded_or_injected_heap(heap: str) -> None:
    with pytest.raises(ConfigError, match="heap"):
        build_command(
            java="java",
            heap=heap,
            library_dir="/lib",
            jar="/caver.jar",
            home="/home",
            pdb_dir="/pdbs",
            config="/config.txt",
            output_dir="/out",
            tmp_dir="/tmp",
        )
