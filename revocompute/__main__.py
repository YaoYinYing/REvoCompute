# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Command-line entrypoint for REvoCompute maintenance commands."""

from __future__ import annotations

import sys

from revocompute.doctor import main as doctor_main


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] in {"-h", "--help"}:
        print("Usage: revocompute doctor [--config-root PATH] [--runner ID] [--task ID] [--strict] [--json]")
        return 0
    command, *rest = arguments
    if command == "doctor":
        return doctor_main(rest)
    print(f"Unknown command: {command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

