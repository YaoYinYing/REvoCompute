# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Round-5 checks: a long input basename must not 500, and the preflight route
must actually be rate limited."""

from __future__ import annotations

import io
import os

from conftest import _load_pssm_module, _test_client_auth, _task_owner


def _module(monkeypatch, tmp_path):
    return _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678", "ENABLED_TASKRUNNERS": "pythia_ddg"},
    )


def test_a_long_input_basename_is_rejected_not_500(monkeypatch, tmp_path):
    """The quarantine temp name adds a 21-byte prefix to a basename that is not
    length-bounded, so a ~240-byte name overflows NAME_MAX and the OSError used
    to reach Flask as an unhandled 500."""
    module = _module(monkeypatch, tmp_path)
    client = module.app.test_client()
    auth_header = _test_client_auth(module)
    name = "a" * 240 + ".pdb"
    print("\nfinal component length:", len(name) + len(".tmp_0123456789abcdef_"))
    response = client.post(
        "/compute/api/preflight/pythia_ddg",
        data={
            "task_type": "pythia_ddg",
            "files": (io.BytesIO(b"ATOM      1  N   ALA A   1\n"), name),
            "input_roles": "structure",
        },
        headers=auth_header,
        content_type="multipart/form-data",
    )
    print("status:", response.status_code)
    assert response.status_code == 400, response.get_data()[:200]
    assert "input_path_invalid" in response.get_data(as_text=True)


def test_preflight_is_rate_limited(monkeypatch, tmp_path):
    """The route calls the decorated `_rate_limited_preflight`, so the
    preflight bucket does bind.  This pins that contract so the decorator
    cannot be dropped from the helper in a refactor (which would silently
    remove the limit)."""
    module = _module(monkeypatch, tmp_path)
    client = module.app.test_client()
    auth_header = _test_client_auth(module)
    codes = []
    for _ in range(31):
        response = client.post(
            "/compute/api/preflight/pythia_ddg",
            data={
                "task_type": "pythia_ddg",
                "files": (io.BytesIO(b"ATOM      1  N   ALA A   1\n"), "x.pdb"),
                "input_roles": "structure",
            },
            headers=auth_header,
            content_type="multipart/form-data",
        )
        codes.append(response.status_code)
    print("\npreflight codes:", codes.count(200), "x2xx,", codes.count(429), "x429")
    assert 429 in codes, codes


def test_a_deep_but_legal_path_is_rejected_not_500(monkeypatch, tmp_path):
    """Bounding each component is not enough: the snapshot copy joins them all.

    ~20 legal 200-byte components overflow PATH_MAX in `_prepare_task_record`,
    which is the same unhandled OSError class as a single over-long basename.
    """
    module = _module(monkeypatch, tmp_path)
    client = module.app.test_client()
    auth_header = _test_client_auth(module)
    deep = "/".join(["a" * 200] * 25)
    response = client.post(
        "/compute/api/preflight/pythia_ddg",
        data={
            "task_type": "pythia_ddg",
            "files": (io.BytesIO(b"ATOM      1  N   ALA A   1\n"), "s.pdb"),
            "input_roles": "structure",
            "input_paths": deep + "/s.pdb",
        },
        headers=auth_header,
        content_type="multipart/form-data",
    )
    print("\ndeep path components:", 26, "status:", response.status_code)
    assert response.status_code == 400, response.get_data()[:200]
