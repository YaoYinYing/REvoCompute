# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""HTTP behavior for single-request bounded result projections."""

from __future__ import annotations

import json
import os
from pathlib import Path
import uuid

import numpy as np
import pytest

from conftest import _load_pssm_module, _test_client_auth, _upsert_task_for_user


def _finished_task(module, tmp_path, files: dict[str, object]) -> str:
    md5sum = uuid.uuid4().hex
    result_dir = tmp_path / md5sum
    result_dir.mkdir()
    for name, value in files.items():
        path = result_dir / name
        if path.suffix == ".json":
            path.write_text(json.dumps(value), encoding="utf-8")
        elif isinstance(value, dict):
            np.savez(path, **value)
        elif isinstance(value, np.ndarray):
            np.save(path, value)
        else:
            path.write_text(str(value), encoding="utf-8")
    _upsert_task_for_user(
        module,
        md5sum,
        filename="input.fasta",
        file_path=result_dir / "input.fasta",
        result_dir=result_dir,
        username="tester",
    )
    module.task_runtime._finalize_results_manifest(
        module.task_store.get_task(md5sum), execution_state="completed", finished_at=1_700_000_000
    )
    return md5sum


def test_ndarray_api_returns_complete_numeric_projections_for_json_csv_npy_and_npz(monkeypatch, tmp_path) -> None:
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    client = module.app.test_client()
    headers = _test_client_auth(module)
    md5sum = _finished_task(
        module,
        tmp_path,
        {
            "confidence.npy": np.array([[1.5, 2.5], [np.nan, 4.5]], dtype=np.float32),
            "confidence.npz": {
                "pae": np.arange(9, dtype=np.float32).reshape(3, 3),
                "plddt": np.array([91, 82], dtype=np.int16),
            },
            "confidence.json": {"pae": [[1.5, 2.5], [None, 4.5]], "plddt": [0.91, 0.82], "ptm": 0.76},
            "legacy-pae.json": [{"predicted_aligned_error": [[1.0, 2.0], [2.0, 1.0]]}],
            "confidence.csv": "token_index,plddt\n1,0.91\n2,\n3,0.73\n",
        },
    )

    npy = client.get(
        f"/compute/api/results/{md5sum}/ndarrays/confidence.npy?max_elements=4", headers=headers
    )
    npz = client.get(
        f"/compute/api/results/{md5sum}/ndarrays/confidence.npz?key=pae&max_elements=9", headers=headers
    )
    json_matrix = client.get(
        f"/compute/api/results/{md5sum}/ndarrays/confidence.json?key=pae&max_elements=4", headers=headers
    )
    csv_column = client.get(
        f"/compute/api/results/{md5sum}/ndarrays/confidence.csv?key=plddt&max_elements=3", headers=headers
    )
    json_scalar = client.get(
        f"/compute/api/results/{md5sum}/ndarrays/confidence.json?key=ptm&max_elements=1", headers=headers
    )
    nested_json_matrix = client.get(
        f"/compute/api/results/{md5sum}/ndarrays/legacy-pae.json?key=0.predicted_aligned_error&max_elements=4",
        headers=headers,
    )
    manifest = client.get(f"/compute/api/results/{md5sum}", headers=headers).get_json()
    artifacts = {artifact["path"]: artifact for artifact in manifest["artifacts"]}

    assert npy.status_code == 200
    assert artifacts["confidence.npy"]["ndarray_url"].endswith("/ndarrays/confidence.npy")
    assert artifacts["confidence.npz"]["ndarray_url"].endswith("/ndarrays/confidence.npz")
    assert artifacts["confidence.json"]["ndarray_url"].endswith("/ndarrays/confidence.json")
    assert artifacts["confidence.csv"]["ndarray_url"].endswith("/ndarrays/confidence.csv")
    assert npy.get_json() == {
        "data": [1.5, 2.5, None, 4.5],
        "dtype": "<f4",
        "kind": "numeric",
        "key": None,
        "shape": [2, 2],
        "total_elements": 4,
    }
    assert npz.status_code == 200
    assert npz.get_json() == {
        "data": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0],
        "dtype": "<f4",
        "kind": "numeric",
        "key": "pae",
        "shape": [3, 3],
        "total_elements": 9,
    }
    assert json_matrix.status_code == 200
    assert json_matrix.get_json() == {
        "data": [1.5, 2.5, None, 4.5],
        "dtype": "<f8",
        "kind": "numeric",
        "key": "pae",
        "shape": [2, 2],
        "total_elements": 4,
    }
    assert csv_column.status_code == 200
    assert csv_column.get_json() == {
        "data": [0.91, None, 0.73],
        "dtype": "<f8",
        "kind": "numeric",
        "key": "plddt",
        "shape": [3],
        "total_elements": 3,
    }
    assert json_scalar.get_json() == {
        "data": [0.76],
        "dtype": "<f8",
        "kind": "numeric",
        "key": "ptm",
        "shape": [],
        "total_elements": 1,
    }
    assert nested_json_matrix.get_json() == {
        "data": [1.0, 2.0, 2.0, 1.0],
        "dtype": "<f8",
        "kind": "numeric",
        "key": "0.predicted_aligned_error",
        "shape": [2, 2],
        "total_elements": 4,
    }


def test_ndarray_api_rejects_unsafe_queries_non_numeric_data_and_wrong_formats(monkeypatch, tmp_path) -> None:
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    client = module.app.test_client()
    headers = _test_client_auth(module)
    md5sum = _finished_task(
        module,
        tmp_path,
        {
            "object.npy": np.array([{"unsafe": True}], dtype=object),
            "arrays.npz": {"scores": np.arange(3, dtype=np.float64)},
            "objects.npz": {"payload": np.array([{"unsafe": True}], dtype=object)},
            "arrays.json": {
                "ragged": [[1, 2], [3]],
                "cube": [[[1]]],
                "labels": ["A", "B"],
                "scalar": 1,
            },
            "notes.txt": "not an array",
            "bad.csv": "token_index,plddt\n1,good\n",
        },
    )
    base = f"/compute/api/results/{md5sum}/ndarrays"

    for url in (
        f"{base}/arrays.npz",
        f"{base}/arrays.npz?key=../scores",
        f"{base}/arrays.npz?key=missing",
        f"{base}/arrays.npz?key=scores&max_elements=2",
        f"{base}/arrays.npz?key=scores&max_elements=0",
        f"{base}/arrays.npz?key=scores&max_elements=3&max_elements=3",
        f"{base}/arrays.npz?key=scores&max_elements=3&unknown=1",
        f"{base}/object.npy?max_elements=1",
        f"{base}/objects.npz?key=payload&max_elements=1",
        f"{base}/arrays.json",
        f"{base}/arrays.json?key=../ragged",
        f"{base}/arrays.json?key=0..ragged",
        f"{base}/arrays.json?key=missing",
        f"{base}/arrays.json?key=ragged",
        f"{base}/arrays.json?key=cube",
        f"{base}/arrays.json?key=labels",
        f"{base}/arrays.json?key=scalar",
        f"{base}/notes.txt",
        f"{base}/bad.csv",
        f"{base}/bad.csv?key=../plddt",
        f"{base}/bad.csv?key=missing",
        f"{base}/bad.csv?key=plddt",
        f"{base}/arrays.npz?key=scores&kind=categorical&max_elements=3",
        f"{base}/object.npy?kind=categorical&max_elements=1",
    ):
        assert client.get(url, headers=headers).status_code == 400, url


def test_ndarray_api_preserves_manifest_and_task_access_boundaries(monkeypatch, tmp_path) -> None:
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    client = module.app.test_client()
    owner_headers = _test_client_auth(module)
    other_headers = _test_client_auth(module, username="other", password="password2")
    md5sum = _finished_task(
        module,
        tmp_path,
        {
            "published.npy": np.arange(4, dtype=np.uint8),
            "published.json": {"values": [1, 2, 3]},
            "published.csv": "token_index,plddt\n1,0.8\n",
        },
    )
    result_dir = module.app.config["storage_resolver"].get_task_root(module.task_store.get_task(md5sum))
    np.save(f"{result_dir}/late.npy", np.arange(2, dtype=np.uint8))
    (Path(result_dir) / "late.json").write_text('{"values":[1]}', encoding="utf-8")
    (Path(result_dir) / "late.csv").write_text("plddt\n0.8\n", encoding="utf-8")

    published = f"/compute/api/results/{md5sum}/ndarrays/published.npy?max_elements=4"
    published_json = f"/compute/api/results/{md5sum}/ndarrays/published.json?key=values&max_elements=3"
    unpublished = f"/compute/api/results/{md5sum}/ndarrays/late.npy?max_elements=2"
    unpublished_json = f"/compute/api/results/{md5sum}/ndarrays/late.json?key=values&max_elements=1"
    published_csv = f"/compute/api/results/{md5sum}/ndarrays/published.csv?key=plddt&max_elements=1"
    unpublished_csv = f"/compute/api/results/{md5sum}/ndarrays/late.csv?key=plddt&max_elements=1"

    assert client.get(published, headers=owner_headers).status_code == 200
    json_response = client.get(published_json, headers=owner_headers)
    assert json_response.status_code == 200
    assert json_response.get_json()["shape"] == [3]
    assert client.get(unpublished, headers=owner_headers).status_code == 404
    assert client.get(unpublished_json, headers=owner_headers).status_code == 404
    assert client.get(published_csv, headers=owner_headers).status_code == 200
    assert client.get(unpublished_csv, headers=owner_headers).status_code == 404
    assert client.get(published, headers=other_headers).status_code == 404
    assert client.get(published).status_code == 404
    assert client.get(published_json, headers=other_headers).status_code == 404


def test_json_projection_enforces_artifact_and_element_limits(monkeypatch, tmp_path) -> None:
    from revocompute import ndarray

    path = tmp_path / "values.json"
    path.write_text('{"values":[1,2,3]}', encoding="utf-8")
    monkeypatch.setattr(ndarray, "MAX_JSON_FILE_BYTES", 8)
    with pytest.raises(ndarray.ArrayAccessError, match="artifact exceeds"):
        ndarray.read_array_projection(path.open("rb"), name=str(path), key="values", kind="numeric", max_elements=3)

    monkeypatch.setattr(ndarray, "MAX_JSON_FILE_BYTES", 1024)
    monkeypatch.setattr(ndarray, "MAX_JSON_ARRAY_ELEMENTS", 2)
    with pytest.raises(ndarray.ArrayAccessError, match="element limit"):
        ndarray.read_array_projection(path.open("rb"), name=str(path), key="values", kind="numeric", max_elements=3)


def test_csv_projection_enforces_source_row_and_column_limits(monkeypatch, tmp_path) -> None:
    from revocompute import ndarray

    path = tmp_path / "values.csv"
    path.write_text("token_index,plddt\n1,0.8\n2,0.7\n", encoding="utf-8")
    monkeypatch.setattr(ndarray, "MAX_CSV_FILE_BYTES", 8)
    with pytest.raises(ndarray.ArrayAccessError, match="artifact exceeds"):
        ndarray.read_array_projection(path.open("rb"), name=str(path), key="plddt", kind="numeric", max_elements=2)

    monkeypatch.setattr(ndarray, "MAX_CSV_FILE_BYTES", 1024)
    monkeypatch.setattr(ndarray, "MAX_CSV_ROWS", 1)
    with pytest.raises(ndarray.ArrayAccessError, match="row limit"):
        ndarray.read_array_projection(path.open("rb"), name=str(path), key="plddt", kind="numeric", max_elements=2)

    monkeypatch.setattr(ndarray, "MAX_CSV_ROWS", 10)
    monkeypatch.setattr(ndarray, "MAX_CSV_COLUMNS", 1)
    with pytest.raises(ndarray.ArrayAccessError, match="column limit"):
        ndarray.read_array_projection(path.open("rb"), name=str(path), key="plddt", kind="numeric", max_elements=2)


def test_categorical_projection_supports_only_bounded_json_and_csv_vectors(monkeypatch, tmp_path) -> None:
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    client = module.app.test_client()
    headers = _test_client_auth(module)
    md5sum = _finished_task(
        module,
        tmp_path,
        {
            "chains.json": {"token_chain_ids": ["A", "A", "ligand-1"]},
            "chains.csv": "token,chain\n1,A\n2,B\n",
            "chains.npy": np.array([1, 2], dtype=np.int8),
            "chains.npz": {"chain": np.array([1, 2], dtype=np.int8)},
        },
    )
    base = f"/compute/api/results/{md5sum}/ndarrays"

    json_response = client.get(
        f"{base}/chains.json?key=token_chain_ids&kind=categorical&max_elements=3", headers=headers
    )
    csv_response = client.get(f"{base}/chains.csv?key=chain&kind=categorical&max_elements=2", headers=headers)

    assert json_response.get_json() == {
        "data": ["A", "A", "ligand-1"],
        "dtype": "string",
        "kind": "categorical",
        "key": "token_chain_ids",
        "shape": [3],
        "total_elements": 3,
    }
    assert csv_response.get_json()["data"] == ["A", "B"]
    assert client.get(f"{base}/chains.npy?kind=categorical&max_elements=2", headers=headers).status_code == 400
    assert client.get(
        f"{base}/chains.npz?key=chain&kind=categorical&max_elements=2", headers=headers
    ).status_code == 400


def test_categorical_projection_rejects_element_cell_and_aggregate_byte_overflow(monkeypatch, tmp_path) -> None:
    from revocompute import ndarray

    path = tmp_path / "chains.json"
    path.write_text(json.dumps({"chains": ["AB", "CD"]}), encoding="utf-8")
    with pytest.raises(ndarray.ArrayAccessError, match="requested element limit"):
        ndarray.read_array_projection(path.open("rb"), name=str(path), key="chains", kind="categorical", max_elements=1)
    monkeypatch.setattr(ndarray, "MAX_STRING_CELL_BYTES", 1)
    with pytest.raises(ndarray.ArrayAccessError, match="cell exceeds"):
        ndarray.read_array_projection(path.open("rb"), name=str(path), key="chains", kind="categorical", max_elements=2)
    monkeypatch.setattr(ndarray, "MAX_STRING_CELL_BYTES", 8)
    monkeypatch.setattr(ndarray, "MAX_STRING_TOTAL_BYTES", 3)
    with pytest.raises(ndarray.ArrayAccessError, match="byte limit"):
        ndarray.read_array_projection(path.open("rb"), name=str(path), key="chains", kind="categorical", max_elements=2)


def test_a_replaced_array_cannot_be_projected_from_the_reopened_pathname(monkeypatch, tmp_path) -> None:
    """The projection reads the verified descriptor, not a later pathname.

    The file is replaced with different but *valid* array bytes immediately after
    publication identity is verified, which is the window a pathname reader would
    lose to; the response must still describe the original artifact.
    """
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    client = module.app.test_client()
    headers = _test_client_auth(module)
    original = np.array([1.0, 2.0, 3.0], dtype=np.float32)
    md5sum = _finished_task(module, tmp_path, {"confidence.npy": original})
    task = module.task_store.get_task(md5sum)
    artifact_path = Path(module.app.config["storage_resolver"].get_task_root(task)) / "confidence.npy"

    resolver = module.app.config["storage_resolver"]
    resolve = resolver.resolve_artifact

    def replace_after_verify(task_arg, relative_path):
        resolved = resolve(task_arg, relative_path)
        swapped = artifact_path.with_suffix(".swapped.npy")
        np.save(swapped, np.array([9.0, 9.0, 9.0], dtype=np.float32))
        os.replace(swapped, artifact_path)
        return resolved

    monkeypatch.setattr(resolver, "resolve_artifact", replace_after_verify)

    response = client.get(
        f"/compute/api/results/{md5sum}/ndarrays/confidence.npy?max_elements=3", headers=headers
    )

    assert response.status_code == 200
    assert response.get_json()["data"] == [1.0, 2.0, 3.0]


def test_an_array_replaced_before_resolution_is_refused(monkeypatch, tmp_path) -> None:
    """Bytes that no longer match the manifest identity are never projected."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    client = module.app.test_client()
    headers = _test_client_auth(module)
    md5sum = _finished_task(module, tmp_path, {"confidence.npy": np.array([1.0, 2.0, 3.0], dtype=np.float32)})
    task = module.task_store.get_task(md5sum)
    artifact_path = Path(module.app.config["storage_resolver"].get_task_root(task)) / "confidence.npy"
    swapped = artifact_path.with_suffix(".swapped.npy")
    np.save(swapped, np.array([9.0, 9.0, 9.0], dtype=np.float32))
    os.replace(swapped, artifact_path)

    response = client.get(
        f"/compute/api/results/{md5sum}/ndarrays/confidence.npy?max_elements=3", headers=headers
    )

    assert response.status_code == 404


def test_a_linked_or_replaced_manifest_fails_the_logical_file_route_closed(monkeypatch, tmp_path) -> None:
    """The /files/ route consumes the canonical verified manifest reader.

    A manifest that is a symlink, a hard link, or oversized is refused rather
    than read through a plain pathname open.
    """
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    client = module.app.test_client()
    headers = _test_client_auth(module)
    md5sum = _finished_task(module, tmp_path, {"confidence.json": {"plddt": [0.9, 0.8]}})
    task = module.task_store.get_task(md5sum)
    manifest_path = Path(module.app.config["storage_resolver"].get_manifest_path(task))
    url = f"/compute/api/results/{md5sum}/files/confidence?index=0"

    assert client.get(url, headers=headers).status_code in {200, 404}
    published = manifest_path.read_bytes()

    outside = tmp_path / "other-manifest.json"
    outside.write_bytes(published)
    manifest_path.unlink()
    manifest_path.symlink_to(outside)
    assert client.get(url, headers=headers).status_code == 404

    manifest_path.unlink()
    manifest_path.write_bytes(published)
    hard = tmp_path / "hard-manifest.json"
    hard.write_bytes(published)
    manifest_path.unlink()
    manifest_path.hardlink_to(hard)
    assert client.get(url, headers=headers).status_code == 404
