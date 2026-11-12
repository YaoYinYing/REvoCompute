# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Declared per-file-part gzip uploads on the real submission boundary.

These drive the actual preflight/submission routes: the encoded wire part is
decoded before format validation, the admitted snapshot is the original bytes
with its original digest, and an invalid declaration or payload fails closed
with no durable Task, dispatch or quarantine left behind.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import conftest
from conftest import _load_pssm_module, _test_client_auth
from revocompute.task_types import TaskInputRole

REPO = Path(__file__).resolve().parents[2]
FASTA = (REPO / "tests/data/msa/2KL8.fasta").read_bytes()
# A legitimate but extremely repetitive protein FASTA: gzip saves more than the
# Server's advertised 200:1 decoded/encoded bound, so the browser must keep it
# identity while the Server must still refuse the compressed wire form.
REPETITIVE_FASTA = b">sample\n" + b"ACDEFGHIKLMNPQRSTVWY" * 4000 + b"\n"


def _module(monkeypatch, tmp_path, *, extra_env=None):
    environment = {"RUNNER_UID": "1234", "RUNNER_GID": "5678"}
    environment.update(extra_env or {})
    return _load_pssm_module(monkeypatch, tmp_path, environment)


def _recording_dispatch(module):
    queued: list[str] = []
    module.run_compute_task.apply_async = lambda *args, **kwargs: (
        queued.append(args[0] if args else (kwargs.get("args") or [None])[0]),
        SimpleNamespace(id="celery-test"),
    )[1]
    return queued


def _submit(module, *, payload=FASTA, filename="2KL8.fasta", encodings=None, endpoint="/compute/api/post"):
    data = {
        "task_type": "cpu_runner",
        "files": (io.BytesIO(payload), filename),
        "input_roles": "sequence",
    }
    if encodings is not None:
        data["file_encodings"] = encodings
    return module.app.test_client().post(
        endpoint,
        headers=_test_client_auth(module),
        data=data,
        content_type="multipart/form-data",
    )


def _assert_no_side_effects(module, queued):
    assert module.task_store.list_tasks() == []
    assert queued == []
    assert not list(Path(module.app.config["UPLOAD_FOLDER"]).glob(".tmp_*"))


def test_the_task_projection_advertises_the_versioned_encoding_contract(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)

    response = module.app.test_client().get(
        "/compute/api/types/cpu_runner", headers=_test_client_auth(module)
    )

    assert response.status_code == 200
    assert response.get_json()["file_encodings"] == {
        "version": 1,
        "supported": ["identity", "gzip"],
        "max_expansion_ratio": 200,
    }


def test_a_repetitive_legitimate_fasta_declared_as_gzip_is_still_refused(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    queued = _recording_dispatch(module)
    compressed = gzip.compress(REPETITIVE_FASTA, mtime=0)
    assert len(REPETITIVE_FASTA) > len(compressed) * 200

    response = _submit(module, payload=compressed, filename="sample.fasta", encodings="gzip")

    assert response.status_code == 400
    assert response.get_json()["details"][0]["code"] == "input_encoding_limit"
    _assert_no_side_effects(module, queued)


def test_the_same_repetitive_fasta_is_accepted_as_identity(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    queued = _recording_dispatch(module)

    response = _submit(module, payload=REPETITIVE_FASTA, filename="sample.fasta")

    assert response.status_code == 302, response.get_data(as_text=True)[:300]
    assert len(module.task_store.list_tasks()) == 1
    assert len(queued) == 1


def test_preflight_accepts_a_declared_gzip_part_and_names_the_original(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)

    response = _submit(
        module,
        payload=gzip.compress(FASTA),
        encodings="gzip",
        endpoint="/compute/api/preflight/cpu_runner",
    )

    assert response.status_code == 200, response.get_data(as_text=True)
    payload = response.get_json()
    assert payload["valid"] is True
    assert payload["inputs"] == [{"role": "sequence", "format": "fasta", "path": "2KL8.fasta"}]
    assert module.task_store.list_tasks() == []


def test_submission_snapshots_the_decoded_original_and_reuses_its_receipt(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    queued = _recording_dispatch(module)

    compressed = _submit(module, payload=gzip.compress(FASTA), encodings="gzip")
    assert compressed.status_code == 302, compressed.get_data(as_text=True)[:300]
    first_id = compressed.headers["Location"].rsplit("/", 1)[-1]
    task = module.task_store.get_task(first_id)
    snapshot_root = Path(module.app.config["storage_resolver"].get_input_root(task)) / "inputs"
    snapshot = snapshot_root / "sequence" / "2KL8.fasta"
    manifest = json.loads((snapshot_root / "task.json").read_text(encoding="utf-8"))
    entry = manifest["inputs"]["sequence"][0]

    # The immutable snapshot is the original scientific file, not the wire form.
    assert snapshot.read_bytes() == FASTA
    assert entry["sha256"] == hashlib.sha256(FASTA).hexdigest()
    assert entry["size"] == len(FASTA)
    assert entry["validation_receipt"]["sha256"] == hashlib.sha256(FASTA).hexdigest()

    # The same original bytes submitted as identity are the same Task request:
    # the transport encoding is not part of scientific identity.
    identity = _submit(module)
    assert identity.status_code == 202, identity.get_data(as_text=True)[:300]
    assert identity.get_json()["md5sum"] == first_id
    assert len(module.task_store.list_tasks()) == 1
    assert len(queued) == 1


@pytest.mark.parametrize(
    ("payload", "encodings", "code"),
    [
        (b"not-gzip", "gzip", "input_encoding_invalid"),
        (gzip.compress(FASTA, mtime=0)[:-4], "gzip", "input_encoding_invalid"),
        (gzip.compress(FASTA, mtime=0) + b"trailing", "gzip", "input_encoding_invalid"),
        (gzip.compress(gzip.compress(FASTA, mtime=0), mtime=0), "gzip", "input_encoding_invalid"),
        (gzip.compress(FASTA, mtime=0), "identity", "input_encoding_conflict"),
        (b"plain", "brotli", "input_encoding_unsupported"),
    ],
)
def test_invalid_encoding_declarations_and_payloads_fail_closed(
    monkeypatch, tmp_path, payload, encodings, code
):
    module = _module(monkeypatch, tmp_path)
    queued = _recording_dispatch(module)

    response = _submit(module, payload=payload, encodings=encodings)

    assert response.status_code == 400
    assert response.get_json()["details"][0]["code"] == code
    _assert_no_side_effects(module, queued)


def _multi_fasta_task(module):
    base, runner = module.task_runtime._get_task_type("cpu_runner")
    conftest._inject_task_type(
        module,
        replace(
            base,
            name="multi_fasta",
            inputs=(TaskInputRole("sequence", "Sequence", "protein_sequence", ("fasta",), 1, 2),),
            params=(),
        ),
        runner,
    )


def test_two_parts_cannot_bend_the_aggregate_decoded_total(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    _multi_fasta_task(module)
    module.app.config["MAX_INPUT_FILE_BYTES"] = 10_000
    module.app.config["MAX_INPUT_TOTAL_BYTES"] = 1_000
    queued = _recording_dispatch(module)
    first = b">one\n" + b"A" * 600 + b"\n"
    second = b">two\n" + b"C" * 600 + b"\n"

    response = module.app.test_client().post(
        "/compute/api/post",
        headers=_test_client_auth(module),
        data={
            "task_type": "multi_fasta",
            "files": [
                (io.BytesIO(gzip.compress(first)), "one.fasta"),
                (io.BytesIO(gzip.compress(second)), "two.fasta"),
            ],
            "input_roles": ["sequence", "sequence"],
            "file_encodings": ["gzip", "gzip"],
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert response.get_json()["details"][0]["code"] == "input_total_size_limit"
    _assert_no_side_effects(module, queued)


def test_a_corrupt_crc_is_refused_before_quarantine(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    queued = _recording_dispatch(module)
    corrupted = bytearray(gzip.compress(FASTA))
    corrupted[-8] ^= 0xFF

    response = _submit(module, payload=bytes(corrupted), encodings="gzip")

    assert response.status_code == 400
    assert response.get_json()["details"][0]["code"] == "input_encoding_invalid"
    _assert_no_side_effects(module, queued)


def test_an_expansion_bomb_is_refused_before_quarantine(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    queued = _recording_dispatch(module)

    response = _submit(module, payload=gzip.compress(b"A" * (2 * 1024 * 1024)), encodings="gzip")

    assert response.status_code == 400
    assert response.get_json()["details"][0]["code"] == "input_encoding_limit"
    _assert_no_side_effects(module, queued)


def test_the_decoded_total_limit_is_independent_of_the_encoded_body(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    module.app.config["MAX_INPUT_TOTAL_BYTES"] = 64
    queued = _recording_dispatch(module)

    response = _submit(module, payload=gzip.compress(FASTA), encodings="gzip")

    assert response.status_code == 400
    assert response.get_json()["details"][0]["code"] == "input_total_size_limit"
    _assert_no_side_effects(module, queued)


def test_declarations_must_be_one_per_part(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    queued = _recording_dispatch(module)

    response = _submit(module, payload=gzip.compress(FASTA), encodings=["gzip", "identity"])

    assert response.status_code == 400
    assert response.get_json()["details"][0]["code"] == "input_encoding_declaration"
    _assert_no_side_effects(module, queued)


def test_an_absent_declaration_keeps_existing_clients_identity(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    queued = _recording_dispatch(module)

    response = _submit(module)

    assert response.status_code == 302, response.get_data(as_text=True)[:300]
    assert len(module.task_store.list_tasks()) == 1
    assert len(queued) == 1


def test_a_whole_multipart_content_encoding_is_refused_before_parsing(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    queued = _recording_dispatch(module)

    response = module.app.test_client().post(
        "/compute/api/post",
        headers=_test_client_auth(module) | {"Content-Encoding": "gzip"},
        data={
            "task_type": "cpu_runner",
            "files": (io.BytesIO(gzip.compress(FASTA)), "2KL8.fasta"),
            "input_roles": "sequence",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert response.get_json()["details"][0]["code"] == "input_encoding_unsupported"
    _assert_no_side_effects(module, queued)


def test_a_compressed_part_is_not_reinterpreted_as_an_archive(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    queued = _recording_dispatch(module)

    # A gzip-declared part that decompresses to a ZIP is judged by the declared
    # role/format after decode, so it cannot become a ZIP input by transporting
    # a compressed container.
    response = _submit(module, payload=gzip.compress(b"PK\x03\x04not-a-fasta"), encodings="gzip")

    assert response.status_code == 400
    assert response.get_json()["details"][0]["code"] in {
        "input_format_invalid",
        "input_logical_type_invalid",
    }
    _assert_no_side_effects(module, queued)


def test_an_overlong_filename_is_still_refused_for_a_compressed_part(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    queued = _recording_dispatch(module)

    response = _submit(
        module, payload=gzip.compress(FASTA), filename=("a" * 300) + ".fasta", encodings="gzip"
    )

    assert response.status_code == 400
    assert response.get_json()["details"][0]["code"] == "input_path_invalid"
    _assert_no_side_effects(module, queued)
