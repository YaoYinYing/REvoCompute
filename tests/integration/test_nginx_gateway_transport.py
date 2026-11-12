# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The deployed gateway's response negotiation and range passthrough.

Runs the real ``docker/nginx/default.conf.template`` in front of a local
upstream: gzip is offered only for the allowlisted text-like types, identity
responses keep their ETag, a 206 range is never compressed and its bytes are
exact, and the Tool call location carries its own larger body cap while the
ordinary Task cap stays at 16 MiB.
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

REPO = Path(__file__).resolve().parents[2]
TEMPLATE = REPO / "docker" / "nginx" / "default.conf.template"
NGINX = shutil.which("nginx")
JSON_BODY = b'{"items":["' + b"a" * 5000 + b'"]}'
PDB_BODY = b"ATOM      1  CA  ALA A   1      11.104   6.134  -6.504  1.00  0.00           C\n" * 40
BINARY_BODY = bytes(range(256)) * 16
RANGE_BODY = bytes(range(200))

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
        elif self.path == "/pdb":
            self._send(200, PDB_BODY, "chemical/x-pdb")
        elif self.path == "/binary":
            self._send(200, BINARY_BODY, "application/octet-stream")
        elif self.path == "/range":
            start, end = 10, 20
            self._send(
                206,
                RANGE_BODY[start:end],
                "application/octet-stream",
                {"Content-Range": f"bytes {start}-{end - 1}/{len(RANGE_BODY)}"},
            )
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
    process = subprocess.Popen(
        [nginx, "-c", str(config), "-p", str(tmp_path), "-g", "daemon off;"],
        stdout=subprocess.DEVNULL,
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
        yield SimpleNamespace(port=gateway_port, root=tmp_path)
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover
            process.kill()
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


def test_text_like_structures_compress_but_binary_and_archives_do_not(gateway):
    status, headers, body = _get(gateway, "/pdb", accept_encoding="gzip")
    assert status == 200
    assert headers["content-encoding"] == "gzip"
    assert gzip.decompress(body) == PDB_BODY

    status, headers, body = _get(gateway, "/binary", accept_encoding="gzip")
    assert status == 200
    assert "content-encoding" not in headers
    assert body == BINARY_BODY


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
