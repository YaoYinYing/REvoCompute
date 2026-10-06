# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Resource-constrained worker for approved Core input parsers."""

from __future__ import annotations

import errno
import json
import os
import resource
import signal
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from revocompute.input_validators.common import ISOLATED_RESOURCE_SENTINEL
from revocompute.input_validators.isolated_validation import ISOLATED_RLIMITS


def _deny_network(*_args, **_kwargs):
    raise OSError("Network access is disabled during input validation")


def _apply_restrictions() -> None:
    os.umask(0o077)
    for resource_id, limit in ISOLATED_RLIMITS:
        resource.setrlimit(resource_id, (limit, limit))
    socket.socket = _deny_network
    socket.create_connection = _deny_network


def _resource_limit_reached(_signum=None, _frame=None):
    """Turn a resource-limit fatal signal into the bounded sentinel response.

    Under ``RLIMIT_AS`` an allocation failure very often surfaces as the kernel
    or CPython's fatal-error handler raising SIGSEGV/SIGABRT/SIGBUS rather than
    as a catchable ``MemoryError``, so the exception handlers below never see it.
    Converting those signals into an ``OSError`` here lets the normal path report
    the sentinel instead of dying with an opaque exit status.
    """
    raise OSError(errno.ENOMEM, "input parser resource limit reached")


def _install_resource_signal_handlers() -> None:
    for signum in (signal.SIGSEGV, signal.SIGABRT, signal.SIGBUS):
        try:
            signal.signal(signum, _resource_limit_reached)
        except (ValueError, OSError):  # not settable on this platform/thread
            continue


def _validate(format_name: str, path: str) -> str | None:
    if format_name not in {"yaml", "yml"}:
        raise ValueError("Unsupported isolated parser")
    from revocompute.input_validators.structured_data import validate_yaml

    return validate_yaml(path)


def _run(format_name: str, path: str) -> tuple[int, dict[str, object]]:
    """Validate one input, mapping a resource limit to the bounded sentinel.

    A resource limit is a normal validation failure, not an isolation crash: the
    parent classifies the sentinel as ``validator_resource_limit`` so a caller
    never has to read prose to tell a hostile input from a malformed one.  The
    OSError case covers what the signal handler raises; MemoryError and
    RecursionError cover the in-band allocation and depth failures.
    """
    try:
        return 0, {"error": _validate(format_name, path)}
    except (MemoryError, RecursionError, OSError):
        return 0, {"error": ISOLATED_RESOURCE_SENTINEL}


def main() -> int:
    if len(sys.argv) != 3:
        return 2
    _apply_restrictions()
    _install_resource_signal_handlers()
    status, payload = _run(sys.argv[1], sys.argv[2])
    if status != 0:
        return status
    sys.stdout.write(json.dumps(payload, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
