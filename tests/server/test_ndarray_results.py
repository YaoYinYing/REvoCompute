# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""HTTP behavior for bounded numeric NPY/NPZ result access."""

from __future__ import annotations

import uuid

import numpy as np

from conftest import _load_pssm_module, _test_client_auth, _upsert_task_for_user


def _finished_task(module, tmp_path, files: dict[str, object]) -> str:
    md5sum = uuid.uuid4().hex
    result_dir = tmp_path / md5sum
    result_dir.mkdir()
    for name, value in files.items():
        path = result_dir / name
        if isinstance(value, dict):
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


def test_ndarray_api_returns_bounded_flat_slices_for_npy_and_selected_npz_key(monkeypatch, tmp_path) -> None:
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
        },
    )

    npy = client.get(
        f"/compute/api/results/{md5sum}/ndarrays/confidence.npy?offset=1&limit=2", headers=headers
    )
    npz = client.get(
        f"/compute/api/results/{md5sum}/ndarrays/confidence.npz?key=pae&offset=3&limit=4", headers=headers
    )
    manifest = client.get(f"/compute/api/results/{md5sum}", headers=headers).get_json()
    artifacts = {artifact["path"]: artifact for artifact in manifest["artifacts"]}

    assert npy.status_code == 200
    assert artifacts["confidence.npy"]["ndarray_url"].endswith("/ndarrays/confidence.npy")
    assert artifacts["confidence.npz"]["ndarray_url"].endswith("/ndarrays/confidence.npz")
    assert npy.get_json() == {
        "count": 2,
        "data": [2.5, None],
        "dtype": "<f4",
        "has_more": True,
        "key": None,
        "offset": 1,
        "shape": [2, 2],
        "total_elements": 4,
    }
    assert npz.status_code == 200
    assert npz.get_json() == {
        "count": 4,
        "data": [3.0, 4.0, 5.0, 6.0],
        "dtype": "<f4",
        "has_more": True,
        "key": "pae",
        "offset": 3,
        "shape": [3, 3],
        "total_elements": 9,
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
            "notes.txt": "not an array",
        },
    )
    base = f"/compute/api/results/{md5sum}/ndarrays"

    for url in (
        f"{base}/arrays.npz",
        f"{base}/arrays.npz?key=../scores",
        f"{base}/arrays.npz?key=missing",
        f"{base}/arrays.npz?key=scores&limit=16385",
        f"{base}/arrays.npz?key=scores&offset=-1",
        f"{base}/arrays.npz?key=scores&limit=1&limit=2",
        f"{base}/arrays.npz?key=scores&unknown=1",
        f"{base}/object.npy",
        f"{base}/objects.npz?key=payload",
        f"{base}/notes.txt",
    ):
        assert client.get(url, headers=headers).status_code == 400, url


def test_ndarray_api_preserves_manifest_and_task_access_boundaries(monkeypatch, tmp_path) -> None:
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    client = module.app.test_client()
    owner_headers = _test_client_auth(module)
    other_headers = _test_client_auth(module, username="other", password="password2")
    md5sum = _finished_task(module, tmp_path, {"published.npy": np.arange(4, dtype=np.uint8)})
    result_dir = module.app.config["storage_resolver"].get_task_root(module.task_store.get_task(md5sum))
    np.save(f"{result_dir}/late.npy", np.arange(2, dtype=np.uint8))

    published = f"/compute/api/results/{md5sum}/ndarrays/published.npy"
    unpublished = f"/compute/api/results/{md5sum}/ndarrays/late.npy"

    assert client.get(published, headers=owner_headers).status_code == 200
    assert client.get(unpublished, headers=owner_headers).status_code == 404
    assert client.get(published, headers=other_headers).status_code == 404
    assert client.get(published).status_code == 404
