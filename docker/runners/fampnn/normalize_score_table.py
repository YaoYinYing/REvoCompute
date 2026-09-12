# Copyright (C) 2024-2026 YaoYinYing
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import csv
import sys
from pathlib import Path


path = Path(sys.argv[1])
rows = list(csv.reader(path.open(encoding="utf-8", newline="")))
if not rows or not rows[0] or rows[0][0]:
    raise SystemExit("FAMPNN score table has no unnamed residue index")
rows[0][0] = "residue"
with path.open("w", encoding="utf-8", newline="") as handle:
    csv.writer(handle).writerows(rows)
