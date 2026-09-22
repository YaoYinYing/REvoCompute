# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Flatten ColabFold interface confidence for the result protocol.

ColabFold 1.6.3 writes ``ipsae``/``pdockq2`` as per-chain-pair dictionaries
inside ``*_scores_rank_*.json``. Relation views need a flat document, so this
keeps the single best-scoring interface and leaves every raw value in the
upstream scores files.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

OUTPUT_NAME = "interface_scores.json"


def normalize(output_dir: Path) -> bool:
    best: dict[str, object] | None = None
    for scores_path in sorted(output_dir.glob("*_scores_rank_*.json")):
        scores = json.loads(scores_path.read_text(encoding="utf-8"))
        ipsae = scores.get("ipsae")
        if not isinstance(ipsae, dict) or not ipsae:
            continue
        pdockq2 = scores.get("pdockq2")
        pdockq2 = pdockq2 if isinstance(pdockq2, dict) else {}
        for interface, value in ipsae.items():
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            if best is None or value > best["ipsae"]:
                best = {
                    "interface": interface,
                    "ipsae": value,
                    "scores_file": scores_path.name,
                }
                if isinstance(pdockq2.get(interface), (int, float)):
                    best["pdockq2"] = pdockq2[interface]
    if best is None:
        return False
    (output_dir / OUTPUT_NAME).write_text(
        json.dumps(best, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return True


if __name__ == "__main__":
    normalize(Path(sys.argv[1]))
