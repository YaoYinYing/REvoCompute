#!/usr/bin/env python3
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Regenerate the bounded fpocket parser fixture from a raw fpocket run tree.

This is a fixture-preparation tool, not a test and not a scientific reference:
the fixture it writes (``1SUO_out/``) exists so the normalizer's parsing is
exercised against real upstream output, not a hand-written imitation.  It keeps
the global descriptor file and the per-pocket geometry/contact files for a small
named set of pockets, and drops the rest as fixture bulk.

Usage (maintainer only)::

    python docker/runners/fpocket/tests/fast/fixtures/shrink_fixture.py --run-dir <raw 1SUO_out> \
        --output docker/runners/fpocket/tests/fast/fixtures/1SUO_out --pockets 1 2
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def shrink(run_dir: Path, output: Path, pockets: tuple[int, ...]) -> list[str]:
    info_files = list(run_dir.glob("*_info.txt"))
    if len(info_files) != 1:
        raise SystemExit(f"expected exactly one *_info.txt in {run_dir}, found {len(info_files)}")
    info_file = info_files[0]
    stem = info_file.name[: -len("_info.txt")]
    output.mkdir(parents=True, exist_ok=True)
    shutil.copy(info_file, output / info_file.name)
    pocket_dir = output / "pockets"
    pocket_dir.mkdir(exist_ok=True)
    kept: list[str] = [info_file.name]
    for index in pockets:
        for name in (f"pocket{index}_vert.pqr", f"pocket{index}_atm.pdb"):
            shutil.copy(run_dir / "pockets" / name, pocket_dir / name)
            kept.append(f"pockets/{name}")
    return kept


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pockets", type=int, nargs="+", required=True)
    args = parser.parse_args()
    if not args.run_dir.is_dir():
        raise SystemExit(f"run directory not found: {args.run_dir}")
    kept = shrink(args.run_dir, args.output, tuple(args.pockets))
    print(f"kept {len(kept)} files under {args.output}: {', '.join(kept)}")


if __name__ == "__main__":
    main()
