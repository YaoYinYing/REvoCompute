# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The deployed gateway's response negotiation and range passthrough.

Runs the real ``docker/nginx/default.conf.template`` in front of a local
upstream whose content types come from the Server's own
``media_type_for_path`` projection, so the allowlist is exercised against the
types live artifacts actually carry. gzip is offered only for the projected
text-like types, identity responses keep their ETag, and a 206 range is never
compressed and stays byte-exact. Bearer download paths are logged with their
token segment redacted, and that one route's gateway error messages are
suppressed because the error log has no redaction hook.

Caveat: this runs the host's nginx binary, not the pinned
``nginx:1.28-alpine`` image used by Compose. The Docker/Compose gate exercises
the deployed binary; this test protects the template's negotiation and range
semantics on whatever nginx the development host provides.
"""

from __future__ import annotations

import gzip
import http.client
import shutil
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from revocompute.media_types import media_type_for_path

REPO = Path(__file__).resolve().parents[2]
TEMPLATE = REPO / "docker" / "nginx" / "default.conf.template"
NGINX = shutil.which("nginx")
JSON_BODY = b'{"items":["' + b"a" * 5000 + b'"]}'
PDB_BODY = b"ATOM      1  CA  ALA A   1      11.104   6.134  -6.504  1.00  0.00           C\n" * 40
CIF_BODY = (b"data_bench\n#\nloop_\n_atom_site.id\n" + b"ATOM 1 CA ALA A 1 0.0 0.0 0.0\n" * 40)
GRO_BODY = b"    1ALA      CA    1   0.000   0.000   0.000\n" * 40
FASTA_BODY = b">model\n" + b"ACDEFGHIKLMNPQRSTVWY\n" * 80
CSV_BODY = b"id,score\n" + b"1,0.5\n" * 300
BINARY_BODY = bytes(range(256)) * 16
ZIP_BODY = b"PK\x03\x04" + b"\x00" * 200
PNG_BODY = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200
RANGE_BODY = bytes(range(200))

#: Projected path, file name and payload. The handler asks the Server's own
#: projection for the content type, so a type missing from the nginx allowlist
#: fails the compression assertion rather than being hidden by a literal.
SCIENCE = {
    "/pdb": ("model.pdb", PDB_BODY),
    "/cif": ("model.cif", CIF_BODY),
    "/mmcif": ("model.mmcif", CIF_BODY),
    "/gro": ("model.gro", GRO_BODY),
    "/fasta": ("model.fasta", FASTA_BODY),
    "/csv": ("table.csv", CSV_BODY),
    "/xtc": ("trajectory.xtc", BINARY_BODY),
    "/dcd": ("trajectory.dcd", BINARY_BODY),
    "/zip": ("results.zip", ZIP_BODY),
    "/png": ("plot.png", PNG_BODY),
}
COMPRESSIBLE = ("/pdb", "/cif", "/mmcif", "/gro", "/fasta", "/csv")
INCOMPRESSIBLE = ("/xtc", "/dcd", "/zip", "/png")

BEARER_VALID = "dummy-valid-token-000000000001"
BEARER_EXPIRED = "dummy-expired-token-00000000001"
BEARER_TAMPERED = "dummy-tampered-token-0000000001"
BEARER_TOKENS = (BEARER_VALID, BEARER_EXPIRED, BEARER_TAMPERED)


def _bearer_spellings(token: str) -> tuple[str, ...]:
    """Every spelling that can carry the bearer path or a hidden marker."""
    return (
        f"/compute/api/artifact-downloads/{token}",
        f"/Compute/api/artifact-downloads/{token}",
        f"/compute/api//artifact-downloads/{token}",
        f"/compute/api/./artifact-downloads/{token}",
        f"/compute/api/x/../artifact-downloads/{token}",
        f"/compute/api/artifact-downloads%2F{token}",
        f"/compute/api/artifact-downloads%252F{token}",
        f"/compute/api/artifact-downloads/{token}%00",
        f"/compute/api/%61rtifact-downloads/{token}",
        f"/compute/api/%2561rtifact-downloads/{token}",
        f"/compute/api/artifact-downloads/{token}/../../other",
        f"/compute/api/artifact-downloads/{token}/%2e%2e/%2e%2e/other",
        f"//compute/api/artifact-downloads/{token}",
    )


BEARER_PATHS = tuple(path for token in BEARER_TOKENS for path in _bearer_spellings(token))

pytestmark = pytest.mark.skipif(
    not (TEMPLATE.is_file() and NGINX),
    reason="requires the nginx binary and the deployed template",
)


class _Upstream(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):  # keep pytest output clean
        return

    def _send(self, status, body, content_type, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("ETag", '"upstream-v1"')
        self.send_header("Cache-Control", "private, no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):
        if self.path == "/json":
            self._send(200, JSON_BODY, "application/json")
        elif self.path in SCIENCE:
            name, body = SCIENCE[self.path]
            self._send(200, body, media_type_for_path(name))
        elif self.path == "/binary":
            self._send(200, BINARY_BODY, "application/octet-stream")
        elif self.path == "/range":
            start, end = 10, 20
            self._send(
                206,
                RANGE_BODY[start:end],
                media_type_for_path("model.pdb"),
                {"Content-Range": f"bytes {start}-{end - 1}/{len(RANGE_BODY)}"},
            )
        elif self.path.startswith("/compute/api/artifact-downloads/"):
            token = self.path.rsplit("/", 1)[-1]
            self._send(200 if token == BEARER_VALID else 404, b"artifact bytes\n", "text/plain")
        else:
            self._send(500, b"<html>error</html>", "text/html")

    do_HEAD = do_GET


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture()
def gateway(tmp_path):
    nginx = NGINX
    upstream_port = _free_port()
    gateway_port = _free_port()
    upstream = ThreadingHTTPServer(("127.0.0.1", upstream_port), _Upstream)
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()

    mime_types = tmp_path / "mime.types"
    mime_types.write_text(
        "types { text/html html; application/json json; text/plain txt; "
        "chemical/x-pdb pdb; application/octet-stream bin; }\n",
        encoding="utf-8",
    )
    rendered = TEMPLATE.read_text(encoding="utf-8")
    rendered = (
        rendered.replace("${UPSTREAM_PORT}", str(upstream_port))
        .replace("${TOOL_CLIENT_MAX_BODY_SIZE}", "17m")
        .replace("http://web:", "http://127.0.0.1:")
        .replace("include /etc/nginx/mime.types;", f"include {mime_types};")
        .replace("pid /tmp/nginx.pid;", f"pid {tmp_path / 'nginx.pid'};")
        .replace("listen 8080;", f"listen {gateway_port};")
        .replace("error_log /dev/stderr warn;", f"error_log {tmp_path / 'error.log'} warn;")
        .replace("/srv/deployment/.maintenance", f"{tmp_path / '.maintenance'}")
        .replace("root /usr/share/nginx/html;", f"root {REPO / 'docker' / 'nginx'};")
        .replace("client_body_temp_path /tmp/client_temp;", f"client_body_temp_path {tmp_path / 'client'};")
        .replace("proxy_temp_path /tmp/proxy_temp;", f"proxy_temp_path {tmp_path / 'proxy'};")
        .replace("fastcgi_temp_path /tmp/fastcgi_temp;", f"fastcgi_temp_path {tmp_path / 'fastcgi'};")
        .replace("uwsgi_temp_path /tmp/uwsgi_temp;", f"uwsgi_temp_path {tmp_path / 'uwsgi'};")
        .replace("scgi_temp_path /tmp/scgi_temp;", f"scgi_temp_path {tmp_path / 'scgi'};")
    )
    config = tmp_path / "nginx.conf"
    config.write_text(rendered, encoding="utf-8")
    access_log = tmp_path / "access.log"
    access_handle = access_log.open("wb")
    process = subprocess.Popen(
        [nginx, "-c", str(config), "-p", str(tmp_path), "-g", "daemon off;"],
        stdout=access_handle,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", gateway_port), timeout=0.2):
                    break
            except OSError:
                if process.poll() is not None:
                    raise AssertionError(process.stderr.read().decode(errors="replace"))
                time.sleep(0.05)
        else:  # pragma: no cover - startup failure
            raise AssertionError(process.stderr.read().decode(errors="replace"))
        yield SimpleNamespace(
            port=gateway_port,
            root=tmp_path,
            access_log=access_log,
            error_log=tmp_path / "error.log",
            upstream=upstream,
        )
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover
            process.kill()
        access_handle.close()
        upstream.shutdown()
        upstream.server_close()


def _get(gateway, path: str, *, accept_encoding: str | None = None, method: str = "GET"):
    connection = http.client.HTTPConnection("127.0.0.1", gateway.port, timeout=10)
    headers = {}
    if accept_encoding is not None:
        headers["Accept-Encoding"] = accept_encoding
    connection.request(method, path, headers=headers)
    response = connection.getresponse()
    body = response.read()
    result = (response.status, {key.lower(): value for key, value in response.getheaders()}, body)
    connection.close()
    return result


def _wait_for_text(path: Path, needle: str, *, timeout: float = 5) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
        if needle in text:
            return text
        time.sleep(0.05)
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def test_bearer_tokens_are_redacted_from_the_access_log(gateway):
    for path in BEARER_PATHS:
        _get(gateway, path)
    _get(gateway, "/normal-log-line")

    log = _wait_for_text(gateway.access_log, "GET /normal-log-line")

    for token in BEARER_TOKENS:
        assert token not in log
    assert '"GET /compute/api/artifact-downloads/[redacted] HTTP/1.1"' in log
    # Ordinary requests are still logged with their real request line.
    assert '"GET /normal-log-line HTTP/1.1"' in log


def test_bearer_tokens_are_absent_from_the_gateway_error_log(gateway):
    gateway.upstream.shutdown()
    gateway.upstream.server_close()

    # Include the double-encoded, NUL, hidden-marker and dot-segment forms that
    # the access-log map has to recognize in the raw or normalized URI.
    for token in BEARER_TOKENS:
        for spelling in (
            f"/compute/api/artifact-downloads/{token}/../../other",
            f"/compute/api/artifact-downloads/{token}/%2e%2e/%2e%2e/other",
        ):
            # The raw-line guard rejects these before any upstream can log them.
            assert _get(gateway, spelling)[0] == 400, spelling
        for spelling in (
            f"/compute/api/artifact-downloads%252F{token}",
            f"/compute/api/artifact-downloads/{token}%00",
            f"/compute/api/%2561rtifact-downloads/{token}",
        ):
            _get(gateway, spelling)
    # A dot-free bearer request still reaches the closed upstream, and a normal
    # path still produces an unredacted error line.
    assert _get(gateway, f"/compute/api/artifact-downloads/{BEARER_VALID}")[0] == 502
    assert _get(gateway, "/normal-after-upstream-failure")[0] == 502

    log = _wait_for_text(gateway.error_log, "/normal-after-upstream-failure")

    for token in BEARER_TOKENS:
        assert token not in log
    assert "/normal-after-upstream-failure" in log
    assert "/artifact-downloads/" not in log


def test_gzip_is_negotiated_for_json_and_identity_keeps_its_etag(gateway):
    status, headers, body = _get(gateway, "/json", accept_encoding="gzip")
    assert status == 200
    assert headers["content-encoding"] == "gzip"
    assert "accept-encoding" in headers["vary"].lower()
    # The compressed representation is weakly equivalent to the identity one:
    # nginx weakens the strong upstream ETag instead of reusing it for bytes it
    # changed, so a conditional client never validates the wrong representation.
    assert headers["etag"] == 'W/"upstream-v1"'
    assert headers["cache-control"] == "private, no-store"
    assert gzip.decompress(body) == JSON_BODY

    status, headers, body = _get(gateway, "/json")
    assert status == 200
    assert "content-encoding" not in headers
    assert headers["etag"] == '"upstream-v1"'
    assert body == JSON_BODY


@pytest.mark.parametrize("path", COMPRESSIBLE)
def test_projected_text_like_types_compress(gateway, path):
    _name, expected = SCIENCE[path]
    status, headers, body = _get(gateway, path, accept_encoding="gzip")
    assert status == 200
    assert headers["content-encoding"] == "gzip"
    assert gzip.decompress(body) == expected


@pytest.mark.parametrize("path", INCOMPRESSIBLE)
def test_binary_and_archive_types_are_not_compressed(gateway, path):
    _name, expected = SCIENCE[path]
    status, headers, body = _get(gateway, path, accept_encoding="gzip")
    assert status == 200
    assert "content-encoding" not in headers
    assert body == expected


def test_a_206_range_is_never_compressed_and_stays_byte_exact(gateway):
    status, headers, body = _get(gateway, "/range", accept_encoding="gzip")

    assert status == 206
    assert "content-encoding" not in headers
    assert headers["content-range"] == f"bytes 10-19/{len(RANGE_BODY)}"
    assert body == RANGE_BODY[10:20]


def test_error_responses_and_head_are_not_body_compressed(gateway):
    status, headers, body = _get(gateway, "/missing", accept_encoding="gzip")
    assert status == 500
    assert "content-encoding" not in headers

    status, headers, body = _get(gateway, "/json", accept_encoding="gzip", method="HEAD")
    assert status == 200
    assert body == b""


def test_the_maintenance_503_page_is_served_uncompressed(gateway):
    (gateway.root / ".maintenance").write_text("", encoding="utf-8")

    status, headers, body = _get(gateway, "/json", accept_encoding="gzip")

    assert status == 503
    assert "content-encoding" not in headers
    assert headers["retry-after"] == "120"
    assert b"Compute workspace temporarily paused" in body
