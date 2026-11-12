# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Bounded per-file-part decoding for declared multipart upload encodings.

A client may gzip one uploaded *file payload* and declare it positionally in
``file_encodings``.  The multipart envelope, the file name and the role stay
unmodified, so the ordinary parser, role authorization and logical format
validation all see the decoded original bytes.  This module is the one trust
path for that decode: the Task submission/preflight quarantine and the Tool
call boundary both wrap an uploaded part through :class:`DecodedStream` before
they hash, validate or admit it.

The limits are independent by design.  The request body cap bounds the encoded
wire body, the decoded caps bound the original bytes a part may claim, and the
expansion ratio bounds how much work one small encoded part may cause.  A
compressed part is never interpreted as a ZIP archive or as a different
scientific format: only its decoded bytes reach the format validator.
"""

from __future__ import annotations

import os
import stat
import time
import zlib
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any, BinaryIO

IDENTITY = "identity"
GZIP = "gzip"
SUPPORTED_ENCODINGS = (IDENTITY, GZIP)
DECLARATION_FIELD = "file_encodings"

#: The per-file-part contract version the Server advertises.  A client that
#: does not know it sends no declaration at all and is treated as ``identity``.
CONTRACT_VERSION = 1

#: A real scientific text file compresses a few times over; 200 leaves ample
#: room for unusually repetitive structures while refusing a tiny encoded part
#: that claims an implausibly large original.
MAX_EXPANSION_RATIO = 200

#: Decoding is CPU-bounded by the decoded cap already; this deadline stops a
#: pathological stream from holding a request worker open regardless.
DECODE_DEADLINE_SECONDS = 60.0

_READ_CHUNK = 65536
_GZIP_MAGIC = b"\x1f\x8b"


class UploadEncodingError(ValueError):
    """A declared encoding or encoded payload failed the transport contract.

    ``code`` is the bounded ingress reason code the route reports, so the
    browser, preflight projection and operational events all name the same
    decision instead of scraping prose.
    """

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class DecodeLimits:
    """Independent bounds for one decoded upload part.

    ``encoded_max_bytes`` bounds the transport representation of this part,
    ``decoded_max_bytes`` the original it may expand to, and
    ``decoded_total_max_bytes`` is enforced by the caller across parts (a
    single part cannot know what its siblings already consumed).
    """

    encoded_max_bytes: int
    decoded_max_bytes: int
    decoded_total_max_bytes: int
    max_expansion_ratio: int = MAX_EXPANSION_RATIO
    deadline_seconds: float = DECODE_DEADLINE_SECONDS


def capability() -> dict[str, Any]:
    """The versioned server capability a client negotiates before encoding."""
    return {"version": CONTRACT_VERSION, "supported": list(SUPPORTED_ENCODINGS)}


def parse_declarations(
    values: Sequence[str],
    part_count: int,
    *,
    request_content_encoding: str | None = None,
    part_content_encodings: Sequence[str | None] = (),
) -> list[str]:
    """Return one encoding per file part, or refuse the request.

    An absent ``file_encodings`` field keeps every existing API/agent client
    fully compatible: the parts are ``identity``.  A present field must name
    exactly one supported encoding per part, in the same order as ``files``.
    """
    request_encoding = (request_content_encoding or "").strip().lower()
    if request_encoding and request_encoding != IDENTITY:
        raise UploadEncodingError(
            "input_encoding_unsupported",
            f"Whole-multipart Content-Encoding {request_encoding!r} is not supported; "
            f"encode individual file parts and declare {DECLARATION_FIELD} instead.",
        )
    if not values:
        declarations = [IDENTITY] * part_count
    else:
        if len(values) != part_count:
            raise UploadEncodingError(
                "input_encoding_declaration",
                f"{DECLARATION_FIELD} must declare exactly one encoding per uploaded file; "
                f"received {len(values)} for {part_count} file(s).",
            )
        declarations = [str(value).strip().lower() for value in values]
        unsupported = next((value for value in declarations if value not in SUPPORTED_ENCODINGS), None)
        if unsupported is not None:
            raise UploadEncodingError(
                "input_encoding_unsupported",
                f"Unsupported file encoding {unsupported!r}.",
            )
    headers = list(part_content_encodings)
    if not headers:
        return declarations
    if len(headers) != part_count:
        # Defensive: the caller always passes one header entry per part.
        raise UploadEncodingError("input_encoding_conflict", "Part encoding headers are inconsistent.")
    for declaration, header in zip(declarations, headers, strict=True):
        part_encoding = (header or "").strip().lower()
        if part_encoding and part_encoding != declaration:
            raise UploadEncodingError(
                "input_encoding_conflict",
                f"File part Content-Encoding {part_encoding!r} conflicts with its declared encoding "
                f"{declaration!r}.",
            )
    return declarations


def _gzip_chunks(stream: BinaryIO, limits: DecodeLimits) -> Iterator[bytes]:
    decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
    encoded_bytes = 0
    decoded_bytes = 0
    head = b""
    deadline = time.monotonic() + limits.deadline_seconds
    while True:
        raw = stream.read(_READ_CHUNK)
        if not raw:
            break
        encoded_bytes += len(raw)
        if encoded_bytes > limits.encoded_max_bytes:
            raise UploadEncodingError(
                "request_size_limit",
                f"Encoded input exceeds the {limits.encoded_max_bytes} byte limit.",
            )
        pending = raw
        while pending:
            try:
                output = decompressor.decompress(pending, _READ_CHUNK)
            except zlib.error as exc:
                raise UploadEncodingError(
                    "input_encoding_invalid", "Compressed input failed gzip validation."
                ) from exc
            if output:
                decoded_bytes += len(output)
                if decoded_bytes > limits.decoded_max_bytes:
                    raise UploadEncodingError(
                        "input_file_size_limit",
                        f"Decoded input exceeds the {limits.decoded_max_bytes} byte limit.",
                    )
                if encoded_bytes and decoded_bytes > encoded_bytes * limits.max_expansion_ratio:
                    raise UploadEncodingError(
                        "input_encoding_limit",
                        "Compressed input expands beyond the permitted ratio.",
                    )
                if len(head) < 2:
                    head = (head + output)[:2]
                    if head == _GZIP_MAGIC:
                        raise UploadEncodingError(
                            "input_encoding_invalid",
                            "Compressed input contains a nested compressed member.",
                        )
                yield output
            pending = decompressor.unconsumed_tail
            if time.monotonic() > deadline:
                raise UploadEncodingError(
                    "input_encoding_limit", "Compressed input took too long to decode."
                )
            if decompressor.eof:
                # A gzip member is the whole encoding: a concatenated trailing
                # member, trailing garbage and unconsumed input are all refused
                # rather than silently ignored or decoded twice.
                if decompressor.unused_data or stream.read(1):
                    raise UploadEncodingError(
                        "input_encoding_invalid",
                        "Compressed input has trailing data after the gzip member.",
                    )
                return
        if decompressor.eof:
            if decompressor.unused_data or stream.read(1):
                raise UploadEncodingError(
                    "input_encoding_invalid", "Compressed input has trailing data after the gzip member."
                )
            return
    if not decompressor.eof:
        raise UploadEncodingError("input_encoding_invalid", "Compressed input is truncated.")
    # An empty decoded payload is left for the format validator to refuse; the
    # transport contract only proves the gzip member was complete and exact.


def _identity_chunks(stream: BinaryIO, limits: DecodeLimits) -> Iterator[bytes]:
    encoded_bytes = 0
    head = b""
    deadline = time.monotonic() + limits.deadline_seconds
    while chunk := stream.read(_READ_CHUNK):
        encoded_bytes += len(chunk)
        if encoded_bytes > limits.encoded_max_bytes:
            raise UploadEncodingError(
                "request_size_limit",
                f"Encoded input exceeds the {limits.encoded_max_bytes} byte limit.",
            )
        if len(head) < 2:
            head = (head + chunk)[:2]
            # An encoded body must be declared, otherwise a compressed payload
            # would reach the format validator disguised as the scientific file
            # the client named.
            if head == _GZIP_MAGIC:
                raise UploadEncodingError(
                    "input_encoding_conflict",
                    f"Compressed payload must declare {GZIP!r} in {DECLARATION_FIELD}.",
                )
        if time.monotonic() > deadline:
            raise UploadEncodingError("input_encoding_limit", "Input took too long to read.")
        yield chunk


def _chunks(stream: BinaryIO, encoding: str, limits: DecodeLimits) -> Iterator[bytes]:
    if encoding == IDENTITY:
        return _identity_chunks(stream, limits)
    if encoding == GZIP:
        return _gzip_chunks(stream, limits)
    raise UploadEncodingError("input_encoding_unsupported", f"Unsupported file encoding {encoding!r}.")


class DecodedStream:
    """A bounded file-like view of one declared file part.

    Reads yield the original bytes for a ``gzip`` part and the wire bytes for
    an ``identity`` part.  Both pass the same encoded cap, so a caller cannot
    bypass admission by choosing either declaration.
    """

    def __init__(self, stream: BinaryIO, encoding: str, limits: DecodeLimits):
        self._chunks = _chunks(stream, encoding, limits)
        self._buffer = bytearray()
        self._done = False

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            while not self._done:
                self._fill()
            size = len(self._buffer)
        while len(self._buffer) < size and not self._done:
            self._fill()
        output = bytes(self._buffer[:size])
        del self._buffer[:size]
        return output

    def _fill(self) -> None:
        try:
            self._buffer.extend(next(self._chunks))
        except StopIteration:
            self._done = True


def reconcile_stale_quarantine(
    folder: str | os.PathLike[str],
    *,
    max_age_seconds: float = 3600.0,
    now: float | None = None,
) -> int:
    """Remove quarantine files a crashed request could not clean up.

    A normal success, rejection, timeout or client disconnect removes its own
    ``.tmp_`` files in the request's ``finally``.  A process death skips that,
    so startup sweeps files older than *max_age_seconds*; the age guard keeps
    the sweep clear of concurrent workers still writing their own files.
    """
    cutoff = (time.time() if now is None else now) - max_age_seconds
    removed = 0
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                if not entry.name.startswith(".tmp_"):
                    continue
                try:
                    info = entry.stat(follow_symlinks=False)
                    if stat.S_ISREG(info.st_mode) and info.st_mtime < cutoff:
                        os.remove(entry.path)
                        removed += 1
                except FileNotFoundError:
                    continue
    except FileNotFoundError:
        return 0
    return removed
