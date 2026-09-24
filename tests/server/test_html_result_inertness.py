# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""HTML result artifacts are inert downloads, never executable active content."""

from __future__ import annotations

import uuid

from conftest import _load_pssm_module, _test_client_auth, _upsert_task_for_user

HTML_ARTIFACTS = ("report.html", "nested/analysis.htm", "viewer.xhtml")


def _finished_task_with_html_artifacts(module, tmp_path):
    md5sum = uuid.uuid4().hex
    result_dir = tmp_path / "html_results"
    (result_dir / "nested").mkdir(parents=True)
    for index, relative_path in enumerate(HTML_ARTIFACTS):
        target = result_dir / relative_path
        target.write_text(
            "<!doctype html><script>window.top.__escaped = true;</script>"
            f"<p>report {index}</p>",
            encoding="utf-8",
        )
    _upsert_task_for_user(
        module,
        md5sum,
        filename="input.pdb",
        file_path=result_dir / "input.pdb",
        result_dir=result_dir,
        username="tester",
        status="finished",
    )
    module.task_runtime._finalize_results_manifest(
        module.task_store.get_task(md5sum), execution_state="completed", finished_at=1_700_000_000
    )
    return md5sum


def test_html_artifacts_have_no_preview_and_download_as_sandboxed_attachments(monkeypatch, tmp_path):
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    client = module.app.test_client()
    auth_header = _test_client_auth(module)
    md5sum = _finished_task_with_html_artifacts(module, tmp_path)

    manifest = client.get(f"/compute/api/results/{md5sum}", headers=auth_header).get_json()
    artifacts = {artifact["path"]: artifact for artifact in manifest["artifacts"]}
    assert set(HTML_ARTIFACTS) <= set(artifacts)
    for relative_path in HTML_ARTIFACTS:
        # No preview kind is claimed for HTML, so no client-side viewer mounts it.
        assert artifacts[relative_path]["preview"] is None, relative_path

    url = artifacts[HTML_ARTIFACTS[0]]["url"]
    default = client.get(url, headers=auth_header)
    explicit_download = client.get(f"{url}?download=1", headers=auth_header)
    inline = client.get(f"{url}?download=0", headers=auth_header)

    # Untrusted runner HTML never renders same-origin: attachment by default,
    # and a sandboxed response even when a caller explicitly asks for inline.
    for response in (default, explicit_download, inline):
        assert response.status_code == 200
        assert response.headers["Content-Security-Policy"] == "sandbox"
    assert default.headers["Content-Disposition"].startswith("attachment;")
    assert explicit_download.headers["Content-Disposition"].startswith("attachment;")
    assert inline.headers["Content-Disposition"].startswith("inline;")
    assert "__escaped" in default.get_data(as_text=True)
