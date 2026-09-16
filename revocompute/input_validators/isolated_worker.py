# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Resource-constrained worker for approved Core input parsers."""

from __future__ import annotations

import json
import os
import resource
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

_CPU_SECONDS = 2
_ADDRESS_SPACE_BYTES = 256 * 1024 * 1024
_OUTPUT_FILE_BYTES = 1024 * 1024
_OPEN_FILE_LIMIT = 32


def _deny_network(*_args, **_kwargs):
    raise OSError("Network access is disabled during input validation")


def _apply_restrictions() -> None:
    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CPU, (_CPU_SECONDS, _CPU_SECONDS))
    resource.setrlimit(resource.RLIMIT_AS, (_ADDRESS_SPACE_BYTES, _ADDRESS_SPACE_BYTES))
    resource.setrlimit(resource.RLIMIT_FSIZE, (_OUTPUT_FILE_BYTES, _OUTPUT_FILE_BYTES))
    resource.setrlimit(resource.RLIMIT_NOFILE, (_OPEN_FILE_LIMIT, _OPEN_FILE_LIMIT))
    socket.socket = _deny_network
    socket.create_connection = _deny_network


def _validate(format_name: str, path: str) -> str | None:
    if format_name not in {"yaml", "yml"}:
        raise ValueError("Unsupported isolated parser")
    from revocompute.input_validators.structured_data import validate_yaml

    return validate_yaml(path)


def main() -> int:
    if len(sys.argv) != 3:
        return 2
    _apply_restrictions()
    try:
        error = _validate(sys.argv[1], sys.argv[2])
        response = json.dumps({"error": error}, separators=(",", ":"))
    except BaseException:
        return 1
    sys.stdout.write(response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
