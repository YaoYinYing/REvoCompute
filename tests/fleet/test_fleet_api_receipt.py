# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations
import json
import sys
from pathlib import Path
import pytest
from revocompute_ctl.api_receipt import (
    ApiReceiptCaptureError,
    capture_api_receipt,
    receipt_path,
)
from revocompute_ctl.env import EnvState
from revocompute.api_receipt import (
    API_RECEIPT_KIND,
    API_RECEIPT_VERSION,
    ApiReceiptError,
    build_api_receipt,
    parse_api_receipt,
    receipt_failures,
    render_api_receipt_summary,
    tool_source_digest,
)
ROOT = Path(__file__).resolve().parents[2]


def test_checked_in_receipts_name_the_tool_that_produced_them():
    """A machine-check for the acceptance contract's tool-identity clause.

    Each checked-in receipt must carry its collector source digest, and both
    receipts were produced by the same tool, so the digests agree. This turns
    "the receipt was produced by the reviewed tool" into a fact the repository
    checks rather than prose a reader must trust.
    """
    receipts = sorted((ROOT / "docker" / "runners" / "gremlin_lh" / "receipts").glob("*.json"))
    assert receipts, "expected checked-in receipts"
    digests = {}
    for path in receipts:
        parsed = parse_api_receipt(json.loads(path.read_text(encoding="utf-8")))
        digest = parsed["tool"]["source_digest"]
        assert digest.startswith("sha256:")
        digests[path.name] = digest
    assert len(set(digests.values())) == 1, digests
    assert digests.values().__iter__().__next__() == tool_source_digest(
        ROOT / "revocompute" / "api_receipt.py",
        ROOT / "run" / "revocompute_ctl" / "api_receipt.py",
    )
