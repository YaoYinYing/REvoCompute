# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Server-resolved parameter values shared by the Runner's fast tests.

The owning ``task.yaml`` is the only production source of defaults; this module
exists so several tests can exercise rendering and orchestration with one
complete parameter set.
"""

from __future__ import annotations

BASE_PARAMS = {
    "probe_radius": 0.9,
    "shell_radius": 3,
    "shell_depth": 4,
    "clustering": "average_link",
    "weighting_coefficient": 1,
    "clustering_threshold": 2.0,
    "exclude_start_zone": 2,
    "exclude_end_zone": 0,
    "min_middle_zone": 5,
    "one_tunnel_in_snapshot": "cheapest",
    "max_output_clusters": 999,
    "max_number_of_tunnels": 10000,
    "max_limiting_radius": 100,
    "cost_function_exponent": 2,
    "number_of_approximating_balls": 12,
    "automatic_shell_radius": False,
    "automatic_shell_radius_bottleneck_multiplier": 2,
    "starting_point_protection_radius": 4,
    "max_distance": 3,
    "desired_radius": 5,
    "first_frame": 1,
    "last_frame": 100000,
    "time_sparsity": 1,
    "seed": 1,
    "exclude_residue_ids": "",
    "exclude_residue_names": "",
    "exclude_atom_numbers": "",
    "residue_contact_distance": 3.0,
    "bottleneck_contact_distance": 3.0,
}
