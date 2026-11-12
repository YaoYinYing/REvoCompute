# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import gzip
import io
import os
import time

import pytest

from revocompute.upload_encoding import (
    DecodeBudget,
    DecodeLimits,
    DecodedStream,
    UploadEncodingError,
    capability,
    parse_declarations,
    reconcile_stale_quarantine,
)

LIMITS = DecodeLimits(
    encoded_max_bytes=1024 * 1024,
    decoded_max_bytes=1024 * 1024,
    decoded_total_max_bytes=1024 * 1024,
)
PAYLOAD = b"ATOM      1  CA  ALA A   1\n" * 100


def _read(data: bytes, encoding: str = "gzip", limits: DecodeLimits = LIMITS) -> bytes:
    stream = DecodedStream(io.BytesIO(data), encoding, limits)
    chunks = []
    while chunk := stream.read(7):  # small reads exercise the refill path
        chunks.append(chunk)
    return b"".join(chunks)


def test_decode_yields_the_exact_original():
    assert _read(gzip.compress(PAYLOAD)) == PAYLOAD
    assert _read(PAYLOAD, "identity") == PAYLOAD


def test_an_encoded_body_must_be_declared():
    with pytest.raises(UploadEncodingError) as caught:
        _read(gzip.compress(PAYLOAD), "identity")
    assert caught.value.code == "input_encoding_conflict"


def test_a_corrupt_crc_is_refused():
    corrupted = bytearray(gzip.compress(PAYLOAD))
    corrupted[-8] ^= 0xFF  # the CRC32 field in the gzip trailer
    with pytest.raises(UploadEncodingError) as caught:
        _read(bytes(corrupted))
    assert caught.value.code == "input_encoding_invalid"


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (b"not gzip", "input_encoding_invalid"),
        (gzip.compress(PAYLOAD, mtime=0)[:-4], "input_encoding_invalid"),
        (gzip.compress(PAYLOAD, mtime=0) + b"x", "input_encoding_invalid"),
        (gzip.compress(gzip.compress(PAYLOAD, mtime=0), mtime=0), "input_encoding_invalid"),
    ],
)
def test_invalid_gzip_forms_are_refused(payload, code):
    with pytest.raises(UploadEncodingError) as caught:
        _read(payload)
    assert caught.value.code == code


def test_encoded_and_decoded_caps_are_independent():
    with pytest.raises(UploadEncodingError) as caught:
        _read(gzip.compress(PAYLOAD), limits=DecodeLimits(16, 1024 * 1024, 1024 * 1024))
    assert caught.value.code == "request_size_limit"

    with pytest.raises(UploadEncodingError) as caught:
        _read(gzip.compress(PAYLOAD), limits=DecodeLimits(1024 * 1024, 32, 1024 * 1024))
    assert caught.value.code == "input_file_size_limit"


def test_an_implausible_expansion_ratio_is_refused():
    with pytest.raises(UploadEncodingError) as caught:
        _read(gzip.compress(b"A" * 200_000))
    assert caught.value.code == "input_encoding_limit"


def test_declarations_are_one_per_part_and_identity_by_default():
    assert parse_declarations([], 3) == ["identity"] * 3
    assert parse_declarations(["gzip", "identity"], 2) == ["gzip", "identity"]
    assert parse_declarations(["gzip"], 1, part_content_encodings=["gzip"]) == ["gzip"]

    with pytest.raises(UploadEncodingError) as caught:
        parse_declarations(["gzip"], 2)
    assert caught.value.code == "input_encoding_declaration"

    with pytest.raises(UploadEncodingError) as caught:
        parse_declarations(["brotli"], 1)
    assert caught.value.code == "input_encoding_unsupported"

    with pytest.raises(UploadEncodingError) as caught:
        parse_declarations(["identity"], 1, part_content_encodings=["gzip"])
    assert caught.value.code == "input_encoding_conflict"

    with pytest.raises(UploadEncodingError) as caught:
        parse_declarations([], 1, request_content_encoding="gzip")
    assert caught.value.code == "input_encoding_unsupported"


def test_the_capability_is_versioned_and_explicit():
    assert capability() == {"version": 1, "supported": ["identity", "gzip"]}


def test_a_shared_budget_refuses_the_aggregate_before_yielding_the_overage():
    limits = DecodeLimits(1024 * 1024, 10_000, 1_000)
    budget = DecodeBudget(limits.decoded_total_max_bytes)
    first = DecodedStream(io.BytesIO(gzip.compress(b"A" * 600)), "gzip", limits, budget=budget)
    assert len(first.read(-1)) == 600
    second = DecodedStream(io.BytesIO(gzip.compress(b"C" * 600)), "gzip", limits, budget=budget)

    delivered = 0
    with pytest.raises(UploadEncodingError) as caught:
        while chunk := second.read(7):
            delivered += len(chunk)
    assert caught.value.code == "input_total_size_limit"
    # The second part's decoded chunk was refused before it could be yielded
    # for writing, so none of its overage reached the output file.
    assert delivered == 0


def test_stale_quarantine_is_swept_without_touching_live_or_unrelated_files(tmp_path):
    old = tmp_path / ".tmp_old_model.pdb"
    fresh = tmp_path / ".tmp_fresh_model.pdb"
    other = tmp_path / "durable.upload"
    for path in (old, fresh, other):
        path.write_bytes(b"x")
    past = time.time() - 7200
    os.utime(old, (past, past))
    os.utime(other, (past, past))

    removed = reconcile_stale_quarantine(tmp_path, max_age_seconds=3600)

    assert removed == 1
    assert not old.exists()
    assert fresh.exists()
    assert other.exists()
