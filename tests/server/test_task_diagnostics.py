# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

import pytest
from conftest import _admin_client_auth, _load_pssm_module, _test_client_auth, _upsert_task_for_user
from jsonschema import Draft202012Validator
from revocompute.execution_diagnostics import STATUS_PATH, bounded_log, safe_diagnostic_text, scheduler_failure
from revocompute.storage import publish_result_text


@pytest.fixture
def task_context(monkeypatch, tmp_path):
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    owner = _test_client_auth(module)
    other = _test_client_auth(module, username="other")
    admin = _admin_client_auth(module)
    task_id = uuid.uuid4().hex
    root = tmp_path / "result"
    root.mkdir()
    _upsert_task_for_user(
        module,
        task_id,
        filename="input.fasta",
        file_path=tmp_path / "input.fasta",
        result_dir=root,
        username="tester",
        status="failed",
        run_stage="fit",
    )
    task = module.task_store.get_task(task_id)
    root = Path(module.app.config["storage_resolver"].get_task_root(task))
    return module, module.app.test_client(), task_id, root, owner, other, admin


def publish_evidence(context, *, record=None, reason="nonzero_exit", exit_code=2):
    module, _client, task_id, root, *_ = context
    value = record or {
        "source": "slurm_adapter",
        "schema_version": 1,
        "task_id": task_id,
        "logs": {
            "stderr": "optimizer stopped\nAPI_TOKEN=diagnostic-token\nfile /srv/private/model.py\n",
            "stdout": "stage started\n",
        },
    }
    payload = json.dumps(value)
    publish_result_text(str(root), STATUS_PATH, payload)
    module.task_store.record_task_diagnostics(
        task_id,
        {
            "reason_code": reason,
            "exit_code": exit_code,
            "record_sha256": hashlib.sha256(payload.encode()).hexdigest(),
        },
    )
    module.task_runtime._finalize_failed_results(
        module.task_store.get_task(task_id), "Execution failed", finished_at=1.0
    )


def test_owned_diagnostics_are_bounded_redacted_and_schema_valid(task_context):
    module, client, task_id, root, owner, other, admin = task_context
    publish_evidence(task_context)
    url = f"/compute/api/tasks/{task_id}/diagnostics"
    response = client.get(url, headers=owner)
    assert response.status_code == 200
    evidence = response.json
    assert evidence["reason_code"] == "nonzero_exit"
    assert evidence["exit_code"] == 2
    assert evidence["exit_code_source"] == "srun"
    assert evidence["stage"] == "fit"
    assert [log["stream"] for log in evidence["logs"]] == ["stderr", "stdout"]
    assert "diagnostic-token" not in response.text
    assert "/srv/private" not in response.text
    assert all("text" not in item for item in evidence["logs"])
    spec = json.loads(Path(module.app.static_folder, "openapi.json").read_text())
    Draft202012Validator({"$ref": "#/components/schemas/TaskDiagnostics", "components": spec["components"]}).validate(
        evidence
    )
    for headers in (None, other):
        assert client.get(url, headers=headers).status_code == 404
        assert client.get(url + "/stderr", headers=headers).status_code == 404
    assert client.get(url, headers=admin).status_code == 200
    downloaded = client.get(evidence["logs"][0]["download_url"], headers=owner)
    assert downloaded.status_code == 200
    assert "attachment" in downloaded.headers["Content-Disposition"]
    assert downloaded.headers["Cache-Control"] == "private, no-store"
    assert "diagnostic-token" not in downloaded.text
    assert len(downloaded.data) <= 64 * 1024
    assert client.get(url + "/allocation_receipt.json", headers=owner).status_code == 404


def test_runner_record_cannot_supply_an_authoritative_failure_classification(task_context):
    module, client, task_id, root, owner, *_ = task_context
    publish_evidence(
        task_context,
        record={
            "source": "slurm_adapter",
            "schema_version": 1,
            "task_id": task_id,
            "reason_code": "out_of_memory",
            "exit_code": 137,
            "logs": {"stderr": "out of memory\n"},
        },
    )
    evidence = client.get(f"/compute/api/tasks/{task_id}/diagnostics", headers=owner).json
    assert evidence["reason_code"] == "nonzero_exit"
    assert evidence["exit_code"] == 2
    module.task_store.record_task_diagnostics(task_id, {})
    evidence = client.get(f"/compute/api/tasks/{task_id}/diagnostics", headers=owner).json
    assert evidence["reason_code"] is None
    assert evidence["exit_code"] is None
    assert evidence["logs"] == []


def test_modified_evidence_file_is_not_served(task_context):
    module, client, task_id, root, owner, *_ = task_context
    publish_evidence(task_context)
    (root / STATUS_PATH).write_text("private rewritten bytes")
    evidence = client.get(f"/compute/api/tasks/{task_id}/diagnostics", headers=owner).json
    assert evidence["logs"] == []
    assert evidence["reason_code"] == "nonzero_exit"


def test_confirmed_metadata_survives_unavailable_publication(task_context):
    module, client, task_id, root, owner, *_ = task_context
    module.task_store.record_task_diagnostics(task_id, {"reason_code": "publication_failed", "exit_code": 0})
    response = client.get(f"/compute/api/tasks/{task_id}/diagnostics", headers=owner)
    assert response.json["reason_code"] == "publication_failed"
    assert response.json["exit_code"] == 0
    assert response.json["logs"] == []


def test_diagnostic_evidence_does_not_survive_task_deletion_or_reappear_from_late_capture(task_context):
    module, client, task_id, root, owner, *_ = task_context
    publish_evidence(task_context)
    module.task_store.delete_task(task_id)
    module.task_store.record_task_diagnostics(task_id, {"reason_code": "timeout"})
    assert module.task_store.get_task_diagnostics(task_id) is None
    assert client.get(f"/compute/api/tasks/{task_id}/diagnostics", headers=owner).status_code == 404


def test_linked_output_namespace_cannot_redirect_server_evidence_writes(tmp_path):
    root, outside = tmp_path / "result", tmp_path / "private"
    root.mkdir()
    outside.mkdir()
    (outside / "target").write_text("original")
    (root / "execution").symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        publish_result_text(str(root), "execution/target", "replacement")
    assert (outside / "target").read_text() == "original"


def test_server_evidence_write_replaces_a_final_symlink_instead_of_following_it(tmp_path):
    root = tmp_path / "result"
    root.mkdir()
    outside = tmp_path / "private"
    outside.write_text("private")
    (root / "evidence").symlink_to(outside)
    publish_result_text(str(root), "evidence", "safe evidence")
    assert outside.read_text() == "private"
    assert (root / "evidence").read_text() == "safe evidence"
    assert not (root / "evidence").is_symlink()


def test_scheduler_classification_needs_matching_authoritative_identity():
    assert scheduler_failure("JobId=42 JobState=OUT_OF_MEMORY", "42")["reason_code"] == "out_of_memory"
    assert scheduler_failure("JobId=43 JobState=OUT_OF_MEMORY", "42") == {}
    assert scheduler_failure("exit 137; stderr says out of memory", "42") == {}
    assert scheduler_failure("JobId=42 JobState=RUNNING", "42") == {}


@pytest.mark.parametrize(
    "text",
    [
        "Authorization: Bearer diagnostic-credential",
        "API_TOKEN=diagnostic-credential",
        'password="diagnostic-credential"',
        '{"token":"diagnostic-credential"}',
        "https://user:diagnostic-credential@service.internal/api?token=other",
        "Traceback /srv/private/task.py:12",
        "-----BEGIN PRIVATE KEY-----\ndiagnostic-credential\n-----END PRIVATE KEY-----",
    ],
)
def test_diagnostic_context_is_not_a_user_facing_failure_explanation(text):
    sanitized = safe_diagnostic_text(text)
    assert "diagnostic-credential" not in sanitized
    assert "/srv/private" not in sanitized
    assert "service.internal" not in sanitized


def test_invisible_format_controls_cannot_reorder_the_retained_excerpt(task_context):
    module, client, task_id, root, owner, *_ = task_context
    # Arabic letter mark, zero-width joiners, soft hyphen: every Unicode Cf
    # character is invisible, so each one can reorder or conceal the text it sits in.
    assert safe_diagnostic_text("a\u061cb\u200cc\u200dd\u00ade\n") == "abcde\n"
    publish_evidence(
        task_context,
        record={
            "source": "slurm_adapter",
            "schema_version": 1,
            "task_id": task_id,
            # A right-to-left override plus zero-width/BOM characters would let a
            # log line display different text than it contains.
            "logs": {"stderr": "safe \u202eevil\u202c\u200f\ufeff text\n"},
        },
    )
    evidence = client.get(f"/compute/api/tasks/{task_id}/diagnostics", headers=owner).json
    assert evidence["logs"][0]["preview"] == "safe evil text\n"
    downloaded = client.get(evidence["logs"][0]["download_url"], headers=owner)
    assert downloaded.text == "safe evil text\n"


def test_log_bounds_preserve_utf8_and_only_complete_lines():
    tail, truncated = bounded_log("first\n" + "αβγ\n" * 10000, limit=8192)
    assert truncated
    assert len(tail.encode()) <= 8192
    assert not tail.startswith("�")


def test_expired_data_hides_diagnostics_and_rejects_late_capture(task_context):
    from sqlalchemy import update

    module, client, task_id, root, owner, *_ = task_context
    publish_evidence(task_context)
    store = module.task_store
    with store.engine.begin() as connection:
        connection.execute(
            update(store.data_lifecycle_table)
            .where(store.data_lifecycle_table.c.task_id == task_id)
            .values(state="PURGED")
        )
    before = store.get_task_diagnostics(task_id)
    store.record_task_diagnostics(task_id, {"reason_code": "timeout"})
    assert store.get_task_diagnostics(task_id) == before
    evidence = client.get(f"/compute/api/tasks/{task_id}/diagnostics", headers=owner).json
    assert evidence["availability"] == "expired"
    assert evidence["logs"] == []
    assert evidence["reason_code"] is None
    assert client.get(f"/compute/api/tasks/{task_id}/diagnostics/stderr", headers=owner).status_code == 404


@pytest.mark.browser
@pytest.mark.parametrize("published", [True, False])
def test_real_api_failure_evidence_from_dashboard_and_result(task_context, page, tmp_path, monkeypatch, published):
    """Real Flask/storage/authorization plus the production bundle; no Slurm claim."""
    import shutil
    import threading
    from playwright.sync_api import expect
    from werkzeug.serving import make_server

    module, client, task_id, root, owner, *_ = task_context
    bundle = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    assert (bundle / "index.html").is_file(), "Build the production frontend before browser acceptance"
    static_root = tmp_path / "browser-static"
    shutil.copytree(bundle, static_root / "app")
    monkeypatch.setattr(module.app, "static_folder", str(static_root))
    if published:
        (root / "partial.txt").write_text("Retained partial scientific output")
        publish_evidence(task_context)
    else:
        module.task_store.record_task_diagnostics(task_id, {"reason_code": "publication_failed", "exit_code": 0})
    server = make_server("127.0.0.1", 0, module.app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    login = page.context.request.post(
        f"{origin}/compute/api/auth/login",
        data={"username": "tester", "password": "password"},
    )
    assert login.status == 200
    try:
        page.goto(f"{origin}/compute/dashboard")
        action = page.get_by_role("button", name="View error", exact=True)
        expect(action).to_be_visible()
        for layout in ("compact", "table", "detailed"):
            page.locator(f'[data-layout="{layout}"]').first.click()
            expect(action).to_be_visible()
        action.focus()
        page.keyboard.press("Enter")
        panel = page.get_by_role("dialog").locator(".task-diagnostics")
        expect(panel).to_contain_text("nonzero_exit" if published else "publication_failed")
        expect(panel).to_contain_text("2 (srun)" if published else "0 (srun)")
        expect(panel).not_to_contain_text("diagnostic-token")
        page.keyboard.press("Escape")
        expect(page.get_by_role("dialog")).not_to_be_visible()
        expect(action).to_be_focused()
        page.goto(f"{origin}/compute/results/{task_id}")
        panel = page.locator(".task-diagnostics")
        expect(panel).to_be_visible()
        page.get_by_role("button", name="View error", exact=True).click()
        expect(panel).to_be_focused()
        expect(page.locator(".app-sidebar")).to_have_count(1)
        if published:
            page.get_by_role("button", name="Open Files and diagnostics", exact=True).click()
            expect(page.locator("dialog.result-rail")).to_be_visible()
            page.keyboard.press("Escape")
            expect(page.get_by_role("button", name="Open Files and diagnostics", exact=True)).to_be_focused()
            page.get_by_role("button", name="Open Files and diagnostics", exact=True).click()
            page.locator('[data-artifact-path="partial.txt"]').click()
            expect(page.locator(".result-preview")).to_contain_text("Retained partial scientific output")
        expect(panel).to_contain_text("nonzero_exit" if published else "publication_failed")
        for width in (1440, 1024, 390):
            page.set_viewport_size({"width": width, "height": 900})
            assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
            assert panel.locator("dd").first.evaluate("el => parseFloat(getComputedStyle(el).fontSize)") >= 14
        if published:
            expect(panel.locator("pre").first).to_contain_text("optimizer stopped")
            with page.expect_download() as downloaded:
                panel.get_by_role("link", name="Download bounded stderr excerpt").click()
            assert downloaded.value.failure() is None
            assert "diagnostic-token" not in Path(downloaded.value.path()).read_text()
        else:
            expect(panel).to_contain_text("No readable diagnostic-log preview")
        page.screenshot(path=str(tmp_path / f"failure-evidence-{published}.png"), full_page=True)
        if published:
            page.set_viewport_size({"width": 1440, "height": 1000})
            page.screenshot(path=str(tmp_path / "failure-evidence-desktop.png"), full_page=True)
            page.evaluate("document.documentElement.style.zoom = '2'")
            assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
            page.evaluate("document.documentElement.style.zoom = ''")
            page.evaluate(
                "localStorage.setItem('revocompute-theme', 'dark'); localStorage.setItem('revocompute-locale', 'zh-CN')"
            )
            page.reload()
            expect(page.locator(".task-diagnostics h3")).to_have_text("失败证据")
            expect(page.locator(".task-diagnostics pre").first).to_contain_text("optimizer stopped")
            page.screenshot(path=str(tmp_path / "failure-evidence-dark-zh.png"), full_page=True)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_private_scheduler_context_is_redacted():
    text = safe_diagnostic_text(
        "srun: error: compute-12: killed\nNodeList=compute-[12-13] host=service.internal ip=10.4.5.6"
    )
    assert "compute-12" not in text
    assert "compute-[12-13]" not in text
    assert "service.internal" not in text
    assert "10.4.5.6" not in text


def test_workflow_submission_failure_cannot_inherit_previous_stage_evidence(task_context, monkeypatch):
    from types import SimpleNamespace
    from test_slurm_runner import _FakeSrunProcess, _make_entities, _make_runner, _make_task_type
    from revocompute.job.runners.slurm_runner import SlurmJob
    from revocompute.resource_policy import resolve_resources
    from revocompute.task_types import WorkflowStage

    module, client, task_id, root, owner, *_ = task_context
    runtime = module.task_runtime
    stages = (
        WorkflowStage("pipeline.first", "First", False, (), ("first",)),
        WorkflowStage("pipeline.second", "Second", False, (), ("second",)),
    )
    tt = _make_task_type(workflow=stages, stage_markers={"first": "First", "second": "Second"})
    policy = resolve_resources(
        lambda field: None, lambda field: None, requires_gpu=False, allowed_queues=(), default_timeout_seconds=60,
    )
    enabled = [True]
    jobs = []
    (root / "result.txt").write_text("stage one scientific result")
    module.task_store.update_task(task_id, status="queued", run_stage="first")

    def create(task_id, stage_tt, runner, entities, output_dir, callback, **kwargs):
        job = SlurmJob(
            task_id, stage_tt, runner, entities, output_dir, callback,
            manage_db=SimpleNamespace(slurm_enabled=lambda: enabled[0]), task_store=module.task_store,
            resource_policy=policy,
        )
        original_poll = job.poll

        def poll():
            result = original_poll()
            evidence = module.task_store.get_task_diagnostics(task_id)
            assert evidence["exit_code"] == 0
            assert evidence["record_sha256"]
            enabled[0] = False
            return result

        job.poll = poll
        jobs.append(job)
        return job

    monkeypatch.setattr(runtime, "_create_job", create)
    monkeypatch.setattr(
        "revocompute.job.runners.slurm_runner.subprocess.Popen",
        lambda *args, **kwargs: _FakeSrunProcess(stdout="REVODESIGN_JOB_ID=42\nfirst stage log\n"),
    )
    task = module.task_store.get_task(task_id)
    with pytest.raises(RuntimeError, match="SLURM is disabled"):
        runtime._run_compute_workflow(
            task_id, task, tt, _make_runner(), _make_entities(), str(root),
            {stage.name: policy for stage in stages}, lambda stage: None,
        )
    # A completed adapter can be asked to capture again, e.g. by late cancellation.
    current_attempt = module.task_store.get_task_diagnostics(task_id)
    jobs[0]._persist_output()
    # Also cover a capture already past its early ownership read when stage two starts.
    jobs[0]._persist_execution_evidence()
    assert module.task_store.get_task_diagnostics(task_id) == current_attempt
    runtime._record_failure(task_id, task, 1.0, "first", "SLURM is disabled")
    payload = client.get(f"/compute/api/tasks/{task_id}/diagnostics", headers=owner).json
    assert payload["exit_code"] is None
    assert payload["exit_code_source"] is None
    assert payload["stage"] == "second"
    assert payload["logs"] == []


@pytest.mark.parametrize("fault", [None, "metadata", "publication"])
def test_diagnostic_failures_preserve_terminal_ownership_accounting_and_cleanup(task_context, monkeypatch, fault):
    """Publication is best effort after allocation settlement; it cannot own execution."""
    import time

    module, client, task_id, root, owner, *_ = task_context
    store = module.task_store
    runtime = module.task_runtime
    store.update_task(task_id, status="running")
    task = store.get_task(task_id)
    user_id = task["submitted_by_user_id"]
    started = time.time() - 10
    decision = store.reserve_compute_admission(user_id=user_id, task_id=task_id, at=started)
    assert decision["allowed"]
    store.record_allocation_start(
        slurm_job_id="diagnostic-fault-job", task_id=task_id, user_id=user_id, stage_id="fit",
        gpu_count=1, cpu_cores=1, started_at=started,
    )
    store.settle_allocation_elapsed("diagnostic-fault-job", elapsed_seconds=5, finished_at=started + 5)
    allocations = store.list_task_allocations(task_id)
    reservations = store.list_task_reservations(task_id)
    ledger = store.list_compute_ledger(user_id)
    assert allocations and reservations and ledger
    input_root = Path(module.app.config["storage_resolver"].get_input_root(task))
    for directory in ("inputs", "scratch", "prepared"):
        (input_root / directory).mkdir(parents=True, exist_ok=True)
        (input_root / directory / "sample.txt").write_text(directory)

    def refuse(*args, **kwargs):
        raise OSError("diagnostic storage unavailable")

    if fault == "metadata":
        monkeypatch.setattr(store, "record_task_diagnostics", refuse)
    elif fault == "publication":
        monkeypatch.setattr(runtime, "publish_result_text", refuse)
    runtime._record_failure(task_id, task, started, "fit", "Execution failed")
    after = store.get_task(task_id)
    assert after["status"] == "failed"
    assert after["error"] == "Execution failed"
    assert after["walltime"] == after["finished_at"] - started
    assert (after["username"], after["submitted_by_user_id"], after["storage_key"]) == (
        task["username"], user_id, task["storage_key"],
    )
    assert store.list_task_allocations(task_id) == allocations
    assert store.list_task_reservations(task_id) == reservations
    assert store.list_compute_ledger(user_id) == ledger
    assert (input_root / "inputs" / "sample.txt").read_text() == "inputs"
    assert not (input_root / "scratch").exists()
    assert not (input_root / "prepared").exists()
    assert client.get(f"/compute/api/tasks/{task_id}/diagnostics", headers=owner).status_code == 200


@pytest.mark.browser
def test_retained_excerpt_reads_and_searches_without_leaving_the_panel(task_context, page, tmp_path, monkeypatch):
    """Real Flask/storage/authorization plus the production bundle; no Slurm claim."""
    import shutil
    import threading
    from playwright.sync_api import expect
    from werkzeug.serving import make_server

    module, _client, task_id, _root, _owner, *_ = task_context
    bundle = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    assert (bundle / "index.html").is_file(), "Build the production frontend before browser acceptance"
    static_root = tmp_path / "browser-static"
    shutil.copytree(bundle, static_root / "app")
    monkeypatch.setattr(module.app, "static_folder", str(static_root))

    # Longer than the 8 KiB preview so the retained excerpt is offered: the early
    # marker is only reachable through the full bounded excerpt.
    early = "EARLY-MARKER " + "a" * 200 + "\n"
    body = "".join(f"progress step {index}\n" for index in range(3000))
    stderr = early + body + "API_TOKEN=diagnostic-token\nLATE-MARKER\n"
    publish_evidence(
        task_context,
        record={"source": "slurm_adapter", "schema_version": 1, "task_id": task_id, "logs": {"stderr": stderr}},
    )

    server = make_server("127.0.0.1", 0, module.app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    login = page.context.request.post(
        f"{origin}/compute/api/auth/login", data={"username": "tester", "password": "password"},
    )
    assert login.status == 200
    try:
        page.goto(f"{origin}/compute/results/{task_id}")
        panel = page.locator(".task-diagnostics")
        expect(panel).to_be_visible()
        expect(panel.locator("pre").first).not_to_contain_text("EARLY-MARKER")
        opener = panel.get_by_role("button", name="Read full retained excerpt", exact=True)
        expect(opener).to_be_visible()
        opener.focus()
        page.keyboard.press("Enter")
        toggle = panel.get_by_role("button", name="Hide retained excerpt", exact=True)
        expect(toggle).to_have_attribute("aria-expanded", "true")
        expect(toggle).to_be_focused()
        lines = panel.locator(".task-diagnostic-lines")
        expect(lines).to_be_visible()
        expect(lines).to_contain_text("EARLY-MARKER")
        expect(lines).to_contain_text("LATE-MARKER")
        expect(lines).not_to_contain_text("diagnostic-token")
        expect(panel.locator(".task-diagnostic-gutter").first).to_have_text("1")

        search = panel.get_by_label("Search this excerpt")
        search.fill("early-marker")
        expect(panel.locator(".task-diagnostic-search-status")).to_have_text("Match 1 of 1")
        expect(panel.locator("mark")).to_have_count(1)
        search.fill("progress step")
        expect(panel.locator(".task-diagnostic-search-status")).to_contain_text("Match 1 of 1000+")
        page.keyboard.press("Enter")
        expect(panel.locator(".task-diagnostic-search-status")).to_contain_text("Match 2 of 1000+")
        page.keyboard.press("Shift+Enter")
        expect(panel.locator(".task-diagnostic-search-status")).to_contain_text("Match 1 of 1000+")
        page.keyboard.press("Escape")
        expect(search).to_have_value("")
        expect(panel.locator("mark")).to_have_count(0)

        for width in (1440, 390):
            page.set_viewport_size({"width": width, "height": 900})
            assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
        # Screenshot the viewport, not the page: the excerpt can be many thousands
        # of lines tall, past Chromium's capture limit.
        page.set_viewport_size({"width": 1440, "height": 1000})
        panel.scroll_into_view_if_needed()
        page.screenshot(path=str(tmp_path / "retained-excerpt-desktop.png"))
        page.set_viewport_size({"width": 390, "height": 900})
        page.locator(".task-diagnostic-lines").scroll_into_view_if_needed()
        page.screenshot(path=str(tmp_path / "retained-excerpt-mobile.png"))

        # The toggle restores the bounded preview without a second request.
        toggle.click()
        expect(panel.get_by_role("button", name="Read full retained excerpt", exact=True)).to_have_attribute(
            "aria-expanded", "false"
        )
        expect(panel.locator("pre").first).to_be_visible()
    finally:
        server.shutdown()
        thread.join(timeout=5)
