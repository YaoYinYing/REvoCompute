# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Runner protocol v2 — read the task manifest (TASK_MANIFEST env path).

Usage: task_context.py param <name> [default]   # prints one param value
       task_context.py input <role>             # prints one role's sole path
       task_context.py inputs <role>            # prints one role's files as JSON

Kept old-Python compatible: the GREMLIN runner's conda environment is
Python 3.6, so no annotations, f-strings, or newer py3 syntax here.
"""

import json
import os
import sys

manifest = json.load(open(os.environ["TASK_MANIFEST"]))
command = sys.argv[1] if len(sys.argv) > 1 else ""

if command == "param":
    key = sys.argv[2] if len(sys.argv) > 2 else ""
    default = sys.argv[3] if len(sys.argv) > 3 else ""
    value = manifest.get("params", {}).get(key, default)
    print(str(value).lower() if isinstance(value, bool) else value)
elif command in ("input", "inputs"):
    role = sys.argv[2] if len(sys.argv) > 2 else ""
    files = manifest.get("inputs", {}).get(role)
    if not isinstance(files, list):
        sys.stderr.write("task_context.py: unknown input role {!r}\n".format(role))
        sys.exit(2)
    if command == "input":
        if len(files) != 1:
            sys.stderr.write("task_context.py: input role {!r} does not contain exactly one file\n".format(role))
            sys.exit(2)
        print(files[0]["path"])
    else:
        print(json.dumps(files))
else:
    sys.stderr.write(f"task_context.py: unknown command {command!r}\n")
    sys.exit(2)
