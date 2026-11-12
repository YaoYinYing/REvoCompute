# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Expiring, revocable artifact download links.

Every assertion drives the real HTTP surface: issuance is authorized as the
Task owner, the bearer URL is a capability for exactly one published artifact,
and each retrieval rechecks the stored grant, the canonical Task, the current
publication and the issuing owner's access.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import sqlalchemy as sa

from conftest import _test_client_auth, _upsert_task_for_user
from revocompute import artifact_links

_CONTENT = b">specimen\nACDEFGHIK\n"


def _published_task(module, tmp_path, files: dict[str, bytes] | None = None) -> tuple[str, Path]:
    """Create a finished Task whose finalized manifest publishes *files*."""
    # The owner identity exists (and is verified) before the Task, as it does in
    # production; the helper only verifies a user it created.
    _test_client_auth(module)
    task_id = uuid.uuid4().hex
    staging = tmp_path / f"staging-{task_id}"
    staging.mkdir()
    _upsert_task_for_user(
        module,
        task_id,
        filename="input.fasta",
        file_path=staging / "input.fasta",
        result_dir=staging,
        username="tester",
    )
    task = module.task_store.get_task(task_id)
    root = Path(module.app.config["storage_resolver"].get_task_root(task))
    for name, content in (files or {"result.txt": _CONTENT}).items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    module.task_runtime._finalize_results_manifest(task, execution_state="completed", finished_at=1_700_000_000)
    return task_id, root


def _issue(client, headers, task_id: str, path: str = "result.txt", **body):
    return client.post(
        f"/compute/api/results/{task_id}/download-links",
        headers=headers,
        json={"path": path, **body},
    )


def _token_of(response) -> str:
    url = response.get_json()["download_url"]
    return urlsplit(url).path.rsplit("/", 1)[-1]


def _owner_user_id(module, username: str = "tester") -> int:
    return int(module.app.config["user_db"].get_user_by_username(username)["id"])


# ---------------------------------------------------------------------------
# Issuance authorization and token identity
# ---------------------------------------------------------------------------


def test_issuance_requires_authentication_and_task_access(monkeypatch, tmp_path) -> None:
    module = _load(monkeypatch, tmp_path)
    task_id, _root = _published_task(module, tmp_path)
    owner = _test_client_auth(module)
    other = _test_client_auth(module, username="intruder")

    anonymous = module.app.test_client().post(
        f"/compute/api/results/{task_id}/download-links", json={"path": "result.txt"}
    )
    foreign = _issue(module.app.test_client(), other, task_id)

    assert anonymous.status_code == 401
    assert foreign.status_code == 404
    assert _issue(module.app.test_client(), owner, task_id).status_code == 201


def test_issuance_binds_only_a_published_declared_artifact(monkeypatch, tmp_path) -> None:
    module = _load(monkeypatch, tmp_path)
    task_id, root = _published_task(module, tmp_path, {"result.txt": _CONTENT})
    headers = _test_client_auth(module)
    client = module.app.test_client()
    (root / "outside.txt").write_bytes(b"not declared")

    for path in ("undeclared.txt", "../outside.txt", "/etc/passwd", ""):
        assert _issue(client, headers, task_id, path=path).status_code in {400, 404}, path

    response = _issue(client, headers, task_id)
    payload = response.get_json()
    assert response.status_code == 201
    assert payload["path"] == "result.txt"
    assert payload["sha256"] == hashlib.sha256(_CONTENT).hexdigest()
    assert payload["size"] == len(_CONTENT)
    assert payload["scope"] == "read-bytes"
    assert payload["download_url"].startswith("/compute/api/artifact-downloads/")
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"


def test_the_token_appears_only_in_the_returned_url(monkeypatch, tmp_path) -> None:
    module = _load(monkeypatch, tmp_path)
    task_id, _root = _published_task(module, tmp_path)
    response = _issue(module.app.test_client(), _test_client_auth(module), task_id)
    token = _token_of(response)

    body = response.get_data(as_text=True)
    assert body.count(token) == 1
    assert token not in json.dumps({k: v for k, v in response.get_json().items() if k != "download_url"})
    # The stored grant carries only the token id's hash, never the token or id.
    grants = _all_grants(module)
    assert len(grants) == 1
    assert token not in json.dumps(grants)
    assert response.get_json()["id"] not in json.dumps(grants)


def test_issuing_does_not_change_the_published_artifact(monkeypatch, tmp_path) -> None:
    module = _load(monkeypatch, tmp_path)
    task_id, root = _published_task(module, tmp_path)
    before = (root / "result.txt").read_bytes()
    manifest_before = json.loads((root / "manifest.json").read_bytes())

    _issue(module.app.test_client(), _test_client_auth(module), task_id)

    assert (root / "result.txt").read_bytes() == before
    assert json.loads((root / "manifest.json").read_bytes()) == manifest_before


# ---------------------------------------------------------------------------
# Bearer retrieval: unauthenticated, bound, and rechecked every request
# ---------------------------------------------------------------------------


def test_an_active_link_serves_only_its_bound_artifact_without_a_session(monkeypatch, tmp_path) -> None:
    module = _load(monkeypatch, tmp_path)
    task_id, _root = _published_task(module, tmp_path)
    issued = _issue(module.app.test_client(), _test_client_auth(module), task_id)
    url = issued.get_json()["download_url"]

    response = module.app.test_client().get(url)

    assert response.status_code == 200
    assert response.data == _CONTENT
    assert response.headers["Content-Disposition"].startswith("attachment")
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Cache-Control"] == "private, no-store, no-transform"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["ETag"] == f'"{hashlib.sha256(_CONTENT).hexdigest()}"'
    # A full representation is identity-encoded and untransformable, so a
    # response compressor cannot replace the strong validator (#150 boundary).
    assert response.headers["Content-Encoding"] == "identity"
    assert "no-transform" in response.headers["Cache-Control"]


def test_the_link_is_not_a_session_credential_and_authorizes_no_other_surface(monkeypatch, tmp_path) -> None:
    module = _load(monkeypatch, tmp_path)
    task_id, _root = _published_task(module, tmp_path)
    token = _token_of(_issue(module.app.test_client(), _test_client_auth(module), task_id))
    client = module.app.test_client()

    assert client.get(
        "/compute/api/results", headers={"Authorization": f"Bearer {token}"}
    ).status_code in {401, 403, 404}
    assert client.get(
        f"/compute/api/results/{task_id}", headers={"Authorization": f"Bearer {token}"}
    ).status_code == 404
    # The token route accepts no write method.
    assert client.post(f"/compute/api/artifact-downloads/{token}").status_code == 405


def test_mutated_or_malformed_tokens_are_indistinguishable_from_missing_ones(monkeypatch, tmp_path) -> None:
    module = _load(monkeypatch, tmp_path)
    task_id, _root = _published_task(module, tmp_path)
    token = _token_of(_issue(module.app.test_client(), _test_client_auth(module), task_id))
    client = module.app.test_client()

    middle = len(token) // 2
    forged = token[:middle] + ("A" if token[middle] != "A" else "B") + token[middle + 1 :]
    mutations = [
        token + "x",
        forged,
        token.rsplit(".", 1)[0] + ".invalid",
        "not-a-token",
        "a" * 200,
    ]
    bodies = set()
    for candidate in mutations:
        response = client.get(f"/compute/api/artifact-downloads/{candidate}")
        assert response.status_code == 404
        bodies.add(response.get_data(as_text=True))

    assert len(bodies) == 1
    assert all(token not in body for body in bodies)


def test_a_grant_bound_to_one_artifact_cannot_serve_another(monkeypatch, tmp_path) -> None:
    module = _load(monkeypatch, tmp_path)
    task_id, root = _published_task(
        module, tmp_path, {"result.txt": _CONTENT, "other.txt": b"other bytes\n"}
    )
    token = _token_of(_issue(module.app.test_client(), _test_client_auth(module), task_id, "result.txt"))
    # Rewriting the grant's binding is a server-state corruption the signed
    # payload must still catch: the token and the row no longer agree.
    with module.task_store.engine.begin() as conn:
        conn.execute(
            sa.update(module.task_store.artifact_download_links_table).values(artifact_path="other.txt")
        )

    assert module.app.test_client().get(f"/compute/api/artifact-downloads/{token}").status_code == 404


def test_a_republished_artifact_is_refused_when_its_digest_changes(monkeypatch, tmp_path) -> None:
    module = _load(monkeypatch, tmp_path)
    task_id, root = _published_task(module, tmp_path, {"result.txt": _CONTENT})
    token = _token_of(_issue(module.app.test_client(), _test_client_auth(module), task_id))

    (root / "result.txt").write_bytes(b">specimen\nACDEFGHIL\n")
    module.task_runtime._finalize_results_manifest(
        module.task_store.get_task(task_id), execution_state="completed", finished_at=1_700_000_001
    )

    assert module.app.test_client().get(f"/compute/api/artifact-downloads/{token}").status_code == 404


def test_a_replaced_file_without_republishing_is_refused(monkeypatch, tmp_path) -> None:
    module = _load(monkeypatch, tmp_path)
    task_id, root = _published_task(module, tmp_path, {"result.txt": _CONTENT})
    token = _token_of(_issue(module.app.test_client(), _test_client_auth(module), task_id))
    (root / "result.txt").write_bytes(b"replaced bytes that never matched the manifest\n")

    assert module.app.test_client().get(f"/compute/api/artifact-downloads/{token}").status_code == 404


def test_task_deletion_and_access_policy_changes_refuse_an_existing_link(monkeypatch, tmp_path) -> None:
    module = _load(monkeypatch, tmp_path)
    task_id, _root = _published_task(module, tmp_path)
    token = _token_of(_issue(module.app.test_client(), _test_client_auth(module), task_id))
    client = module.app.test_client()
    url = f"/compute/api/artifact-downloads/{token}"
    assert client.get(url).status_code == 200

    # Ownership is the access policy this deployment enforces for result reads.
    with module.task_store.engine.begin() as conn:
        conn.execute(sa.update(module.task_store.tasks_table).values(submitted_by_user_id=999_999))
    assert client.get(url).status_code == 404

    # Put ownership back, then delete the Task through the canonical store.
    with module.task_store.engine.begin() as conn:
        conn.execute(
            sa.update(module.task_store.tasks_table).values(submitted_by_user_id=_owner_user_id(module))
        )
    assert client.get(url).status_code == 200
    module.task_store.delete_task(task_id)
    assert client.get(url).status_code == 404


def test_expired_and_revoked_grants_are_refused(monkeypatch, tmp_path) -> None:
    module = _load(monkeypatch, tmp_path)
    task_id, _root = _published_task(module, tmp_path)
    headers = _test_client_auth(module)
    client = module.app.test_client()

    expired = _token_of(_issue(client, headers, task_id))
    with module.task_store.engine.begin() as conn:
        conn.execute(sa.update(module.task_store.artifact_download_links_table).values(expires_at=time.time() - 1))
    assert client.get(f"/compute/api/artifact-downloads/{expired}").status_code == 404

    revoked = _issue(client, headers, task_id).get_json()
    assert client.delete(
        f"/compute/api/results/{task_id}/download-links/{revoked['id']}", headers=headers
    ).status_code == 200
    assert client.get(revoked["download_url"]).status_code == 404


def test_all_grants_for_a_task_can_be_invalidated(monkeypatch, tmp_path) -> None:
    module = _load(monkeypatch, tmp_path)
    task_id, _root = _published_task(module, tmp_path)
    headers = _test_client_auth(module)
    client = module.app.test_client()
    first = _issue(client, headers, task_id).get_json()["download_url"]
    second = _issue(client, headers, task_id).get_json()["download_url"]

    response = client.delete(f"/compute/api/results/{task_id}/download-links", headers=headers)

    assert response.status_code == 200
    assert response.get_json()["revoked"] == 2
    assert client.get(first).status_code == 404
    assert client.get(second).status_code == 404


def test_a_foreign_user_cannot_revoke_another_users_link(monkeypatch, tmp_path) -> None:
    module = _load(monkeypatch, tmp_path)
    task_id, _root = _published_task(module, tmp_path)
    link = _issue(module.app.test_client(), _test_client_auth(module), task_id).get_json()
    intruder = _test_client_auth(module, username="intruder")

    response = module.app.test_client().delete(
        f"/compute/api/results/{task_id}/download-links/{link['id']}", headers=intruder
    )

    assert response.status_code == 404
    assert module.app.test_client().get(link["download_url"]).status_code == 200


# ---------------------------------------------------------------------------
# Exact-range contract on the bearer path
# ---------------------------------------------------------------------------


def test_head_and_single_ranges_return_exact_offsets(monkeypatch, tmp_path) -> None:
    module = _load(monkeypatch, tmp_path)
    content = bytes(range(256))
    task_id, _root = _published_task(module, tmp_path, {"result.bin": content})
    url = _issue(module.app.test_client(), _test_client_auth(module), task_id, "result.bin").get_json()["download_url"]
    client = module.app.test_client()

    head = client.head(url)
    assert head.status_code == 200
    assert head.data == b""
    assert head.headers["Content-Length"] == str(len(content))
    assert head.headers["Accept-Ranges"] == "bytes"

    cases = {
        "bytes=0-9": content[:10],
        "bytes=10-19": content[10:20],
        "bytes=-16": content[-16:],
        "bytes=240-": content[240:],
        "bytes=0-0": content[:1],
    }
    for header, expected in cases.items():
        response = client.get(url, headers={"Range": header})
        assert response.status_code == 206, header
        assert response.data == expected, header
        start = content.index(expected)
        assert response.headers["Content-Range"] == f"bytes {start}-{start + len(expected) - 1}/{len(content)}"
        assert response.headers["Content-Length"] == str(len(expected))

    unsatisfiable = client.get(url, headers={"Range": f"bytes={len(content) + 1}-"})
    assert unsatisfiable.status_code == 416
    assert unsatisfiable.headers["Content-Range"] == f"bytes */{len(content)}"


def test_if_range_serves_the_full_representation_for_a_stale_validator(monkeypatch, tmp_path) -> None:
    module = _load(monkeypatch, tmp_path)
    task_id, _root = _published_task(module, tmp_path, {"result.txt": _CONTENT})
    url = _issue(module.app.test_client(), _test_client_auth(module), task_id).get_json()["download_url"]
    client = module.app.test_client()
    etag = client.head(url).headers["ETag"]
    # One strong validator covers the complete representation and every range;
    # the bearer route never degrades it to a weak, transformed validator.
    assert etag.startswith('"') and not etag.startswith("W/")
    assert client.get(url).headers["ETag"] == etag
    assert client.get(url, headers={"Range": "bytes=0-3"}).headers["ETag"] == etag

    fresh = client.get(url, headers={"Range": "bytes=0-3", "If-Range": etag})
    assert fresh.status_code == 206
    assert fresh.data == _CONTENT[:4]

    for stale in ('"not-the-published-digest"', f'W/{etag}', "Wed, 21 Oct 2015 07:28:00 GMT"):
        response = client.get(url, headers={"Range": "bytes=0-3", "If-Range": stale})
        assert response.status_code == 200, stale
        assert response.data == _CONTENT
        assert response.headers["ETag"] == etag


def test_if_range_requires_the_strong_published_validator(monkeypatch, tmp_path) -> None:
    module = _load(monkeypatch, tmp_path)
    content = bytes(range(256))
    task_id, _root = _published_task(module, tmp_path, {"result.bin": content})
    url = _issue(module.app.test_client(), _test_client_auth(module), task_id, "result.bin").get_json()[
        "download_url"
    ]
    client = module.app.test_client()

    full = client.get(url, headers={"Accept-Encoding": "gzip"})
    assert full.status_code == 200
    # The identity declaration keeps the full representation untransformable, so
    # a gateway compressor cannot replace the strong validator with a weak one.
    assert full.headers["Content-Encoding"] == "identity"
    strong = full.headers["ETag"]
    assert strong.startswith('"') and not strong.startswith("W/")
    assert full.data == content
    assert full.headers["Content-Length"] == str(len(content))

    matched = client.get(
        url, headers={"Accept-Encoding": "gzip", "Range": "bytes=32-47", "If-Range": strong}
    )
    assert matched.status_code == 206
    assert matched.data == content[32:48]
    assert matched.headers["Content-Range"] == "bytes 32-47/256"
    assert matched.headers["Content-Length"] == "16"
    assert matched.headers["ETag"] == strong

    # Only an exact strong match may resume a range.  A weak validator (the
    # form a compressor emits), a different publication and an HTTP date all
    # return the complete representation instead.
    stale = (
        f"W/{strong}",
        '"' + hashlib.sha256(b"another publication").hexdigest() + '"',
        "Wed, 21 Oct 2015 07:28:00 GMT",
    )
    for validator in stale:
        response = client.get(
            url,
            headers={"Accept-Encoding": "gzip", "Range": "bytes=32-47", "If-Range": validator},
        )
        assert response.status_code == 200, validator
        assert response.data == content, validator
        assert response.headers["Content-Encoding"] == "identity", validator
        assert response.headers["ETag"] == strong, validator


def test_a_wrong_scope_token_or_grant_is_refused(monkeypatch, tmp_path) -> None:
    module = _load(monkeypatch, tmp_path)
    task_id, _root = _published_task(module, tmp_path)
    owner = _owner_user_id(module)
    artifact = {
        "path": "result.txt",
        "sha256": hashlib.sha256(_CONTENT).hexdigest(),
        "size": len(_CONTENT),
    }
    link = artifact_links.issue_download_link(
        task_id=task_id, artifact=artifact, owner_user_id=owner, ttl_seconds=60
    )
    module.task_store.create_artifact_download_link(
        token_id_hash=link["token_id_hash"],
        task_id=task_id,
        artifact_path=artifact["path"],
        artifact_sha256=artifact["sha256"],
        artifact_size=artifact["size"],
        owner_user_id=owner,
        scope="write",
        issued_at=link["issued_at_epoch"],
        expires_at=link["expires_at_epoch"],
    )
    client = module.app.test_client()
    url = f"/compute/api/artifact-downloads/{link['token']}"

    # The stored grant's scope decides, whatever the signed claim says.
    assert client.get(url).status_code == 404

    with module.task_store.engine.begin() as conn:
        conn.execute(
            sa.update(module.task_store.artifact_download_links_table).values(
                scope=artifact_links.SCOPE
            )
        )
    wrong_scope = artifact_links._serializer().dumps({**link["payload"], "scope": "write"})
    assert client.get(f"/compute/api/artifact-downloads/{wrong_scope}").status_code == 404


def test_malformed_and_multipart_ranges_never_claim_what_is_not_served(monkeypatch, tmp_path) -> None:
    module = _load(monkeypatch, tmp_path)
    task_id, _root = _published_task(module, tmp_path, {"result.txt": _CONTENT})
    url = _issue(module.app.test_client(), _test_client_auth(module), task_id).get_json()["download_url"]
    client = module.app.test_client()

    for malformed in ("bytes=abc", "bytes=", "bytes=-0"):
        assert client.get(url, headers={"Range": malformed}).status_code == 416, malformed
    # A multi-range request is served as the complete representation; this
    # server does not implement multipart/byteranges and never says it did.
    multi = client.get(url, headers={"Range": "bytes=0-1,3-4"})
    assert multi.status_code == 200
    assert multi.data == _CONTENT
    assert "multipart/byteranges" not in multi.headers.get("Content-Type", "")


def test_parallel_independent_range_requests_all_return_their_own_bytes(monkeypatch, tmp_path) -> None:
    module = _load(monkeypatch, tmp_path)
    content = bytes(range(256))
    task_id, _root = _published_task(module, tmp_path, {"result.bin": content})
    url = _issue(module.app.test_client(), _test_client_auth(module), task_id, "result.bin").get_json()["download_url"]
    ranges = [(index, index + 15) for index in range(0, 256, 16)]

    def fetch(item: tuple[int, int]) -> tuple[int, int, int, bytes, str]:
        start, end = item
        response = module.app.test_client().get(url, headers={"Range": f"bytes={start}-{end}"})
        return start, end, response.status_code, response.data, response.headers.get("Content-Range", "")

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(fetch, ranges))

    for start, end, status, data, content_range in results:
        assert status == 206
        assert data == content[start : end + 1]
        assert content_range == f"bytes {start}-{end}/256"


def test_interrupted_transfer_does_not_extend_the_grant(monkeypatch, tmp_path) -> None:
    module = _load(monkeypatch, tmp_path)
    task_id, _root = _published_task(module, tmp_path)
    token = _token_of(_issue(module.app.test_client(), _test_client_auth(module), task_id))
    client = module.app.test_client()

    response = client.get(f"/compute/api/artifact-downloads/{token}")
    iterator = iter(response.response)
    first_chunk = next(iterator)
    assert first_chunk
    response.close()

    # Expiry is admission-time: the next request is refused even though a
    # previous response was cut short.
    with module.task_store.engine.begin() as conn:
        conn.execute(sa.update(module.task_store.artifact_download_links_table).values(expires_at=time.time() - 1))
    assert client.get(f"/compute/api/artifact-downloads/{token}").status_code == 404


def test_a_range_response_stays_identity_encoded_with_compression_enabled(monkeypatch, tmp_path) -> None:
    # #150 owns response compression.  Its middleware must skip 206 responses;
    # this asserts the contract the range path depends on: no Content-Encoding,
    # exact offsets and a Content-Length equal to the selected bytes.
    module = _load(monkeypatch, tmp_path)
    content = bytes(range(256))
    task_id, _root = _published_task(module, tmp_path, {"result.bin": content})
    url = _issue(module.app.test_client(), _test_client_auth(module), task_id, "result.bin").get_json()["download_url"]

    response = module.app.test_client().get(
        url, headers={"Range": "bytes=64-127", "Accept-Encoding": "gzip, br"}
    )
    full = module.app.test_client().get(url, headers={"Accept-Encoding": "gzip, br"})

    assert response.status_code == 206
    assert "Content-Encoding" not in response.headers
    assert response.data == content[64:128]
    assert response.headers["Content-Length"] == "64"
    assert full.status_code == 200
    assert full.headers["Content-Encoding"] == "identity"
    assert full.data == content
    assert full.headers["ETag"] == response.headers["ETag"]


# ---------------------------------------------------------------------------
# Token/URL hygiene and limits
# ---------------------------------------------------------------------------


def test_bearer_requests_log_a_redacted_path(monkeypatch, tmp_path) -> None:
    module = _load(monkeypatch, tmp_path)
    task_id, _root = _published_task(module, tmp_path)
    token = _token_of(_issue(module.app.test_client(), _test_client_auth(module), task_id))
    captured: list[dict] = []
    logged_paths: list[str] = []
    original_emit = module.emit_event
    original_redact = module.redacted_request_path

    def capture(event, **fields):
        captured.append({"event": event, **fields})
        return original_emit(event, **fields)

    def capture_redaction(path: str) -> str:
        logged_paths.append(original_redact(path))
        return original_redact(path)

    monkeypatch.setattr(module, "emit_event", capture)
    monkeypatch.setattr(module, "redacted_request_path", capture_redaction)

    module.app.test_client().get(f"/compute/api/artifact-downloads/{token}")

    assert token not in json.dumps(captured)
    assert logged_paths == ["/compute/api/artifact-downloads/[redacted]"]
    assert token not in logged_paths[0]
    assert artifact_links.redacted_request_path(f"/compute/api/artifact-downloads/{token}") == (
        "/compute/api/artifact-downloads/[redacted]"
    )
    assert artifact_links.redacted_request_path(f"/compute/api/results/{task_id}") == f"/compute/api/results/{task_id}"


def test_issuance_rate_limit_is_enforced(monkeypatch, tmp_path) -> None:
    module = _load(monkeypatch, tmp_path)
    task_id, _root = _published_task(module, tmp_path)
    headers = _test_client_auth(module)
    client = module.app.test_client()

    statuses = [_issue(client, headers, task_id).status_code for _ in range(31)]

    assert statuses[:30] == [201] * 30
    assert statuses[-1] == 429


def test_ttl_is_bounded_and_reported(monkeypatch, tmp_path) -> None:
    module = _load(monkeypatch, tmp_path)
    task_id, _root = _published_task(module, tmp_path)
    client = module.app.test_client()
    headers = _test_client_auth(module)

    accepted = _issue(client, headers, task_id, ttl_seconds=30)
    assert accepted.status_code == 201
    expires = accepted.get_json()["expires_at"]
    assert expires.endswith("Z")
    assert _issue(client, headers, task_id, ttl_seconds=0).status_code == 400
    assert _issue(client, headers, task_id, ttl_seconds=-1).status_code == 400
    assert _issue(client, headers, task_id, ttl_seconds=True).status_code == 400
    assert _issue(client, headers, task_id, ttl_seconds=10**9).status_code == 400
    unknown = client.post(
        f"/compute/api/results/{task_id}/download-links",
        headers=headers,
        json={"path": "result.txt", "admin": True},
    )
    assert unknown.status_code == 400


def test_expired_grants_are_retained_for_an_audit_window_then_cleaned(monkeypatch, tmp_path) -> None:
    module = _load(monkeypatch, tmp_path)
    task_id, _root = _published_task(module, tmp_path)
    client = module.app.test_client()
    headers = _test_client_auth(module)
    _issue(client, headers, task_id)
    retention = artifact_links.retention_seconds()
    with module.task_store.engine.begin() as conn:
        conn.execute(
            sa.update(module.task_store.artifact_download_links_table).values(
                expires_at=time.time() - retention - 60
            )
        )

    # A new issuance is the bounded cleanup point; the audit row must outlive
    # its own expiry by the retention window.
    assert _issue(client, headers, task_id).status_code == 201
    assert len(_all_grants(module)) == 1


def test_token_purpose_and_expiry_are_validated_independently(monkeypatch, tmp_path) -> None:
    module = _load(monkeypatch, tmp_path)
    now = 1_700_000_000
    link = artifact_links.issue_download_link(
        task_id="a" * 32,
        artifact={"path": "result.txt", "sha256": "b" * 64, "size": 10},
        owner_user_id=1,
        ttl_seconds=60,
        now=now,
    )

    assert artifact_links.validate_download_token(link["token"], now=now) is not None
    assert artifact_links.validate_download_token(link["token"], now=now + 61) is None
    # A session token and a link token never validate as each other.
    from revocompute.auth import generate_token

    assert artifact_links.validate_download_token(generate_token(1), now=now) is None
    assert artifact_links.validate_download_token(link["token"].replace(".", ".x"), now=now) is None


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _load(monkeypatch, tmp_path):
    from conftest import _load_pssm_module

    return _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})


def _all_grants(module) -> list[dict]:
    with module.task_store.engine.connect() as conn:
        rows = conn.execute(sa.select(module.task_store.artifact_download_links_table)).mappings()
        return [dict(row) for row in rows]
