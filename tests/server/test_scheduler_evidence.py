# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
import time
from types import SimpleNamespace
import uuid

from conftest import _load_pssm_module


def test_prefetched_evidence_checks_its_deadline_when_the_busy_child_becomes_free(monkeypatch, tmp_path):
    """Broker expiry may pass before prefork buffers work behind a busy child."""
    from celery import Celery
    from celery.contrib.testing.worker import start_worker
    from celery.signals import task_received
    from revocompute import scheduler_evidence

    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    runtime = module.task_runtime
    reclaimed = tmp_path / "reclaimed"
    busy, release, executed, completed, received = (tmp_path / name for name in (
        "busy", "release", "executed", "completed", "received",
    ))
    prefix = f"evidence-prefork-{uuid.uuid4().hex}"
    app = Celery(prefix, broker="memory://", backend="cache+memory://", set_as_current=False)
    app.conf.update(task_default_queue=prefix, worker_prefetch_multiplier=4,
                    broker_transport_options={"polling_interval": 0.01})

    def reconcile():
        executed.write_text("scheduler queried")
        return {"settled": 1, "review": 0, "active": 0}

    monkeypatch.setattr(runtime, "_reconcile_slurm_allocations", reconcile)
    def reclaim():
        reclaimed.write_text("reservation evidence checked")
        return 0

    monkeypatch.setattr(runtime, "_reclaim_abandoned_reservations", reclaim)
    monkeypatch.setattr(scheduler_evidence, "SCHEDULER_EVIDENCE_WAIT_SECONDS", 1.0)

    def wait_for(path):
        deadline = time.monotonic() + 5
        while not path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert path.exists(), f"worker did not reach {path.name}"

    @app.task(name=f"{prefix}-occupy", shared=False, lazy=False)
    def occupy():
        busy.write_text("child occupied")
        wait_for(release)

    @app.task(name=scheduler_evidence.SCHEDULER_EVIDENCE_TASK, shared=False, lazy=False)
    def evidence(**kwargs):
        # Exercise the production worker body, then prove it returned normally.
        outcome = runtime.reconcile_slurm_allocations.run(**kwargs)
        completed.write_text(json.dumps(outcome))
        return outcome

    def record_received(sender=None, request=None, **_):
        if request and request.name == scheduler_evidence.SCHEDULER_EVIDENCE_TASK:
            received.write_text(json.dumps({"at": time.time(), "expires": request.expires.timestamp()}))

    task_received.connect(record_received, weak=False)
    try:
        with start_worker(app, perform_ping_check=False, pool="prefork", concurrency=1,
                          shutdown_timeout=10, loglevel="WARNING"):
            app.send_task(f"{prefix}-occupy")
            wait_for(busy)
            assert scheduler_evidence.fetch_scheduler_evidence(
                SimpleNamespace(list_unsettled_allocations=lambda: [1]), app=app,
            ) == {"settled": 0, "review": 1, "active": 0, "reservations_released": 0}
            wait_for(received)
            arrival = json.loads(received.read_text())
            assert arrival["at"] < arrival["expires"] < time.time()
            release.write_text("slot available after caller timed out")
            wait_for(completed)
            assert json.loads(completed.read_text()) is None
            assert not executed.exists()
            assert not reclaimed.exists()
            # Same prefork path, fresh deadline: scheduler work really executes.
            completed.unlink()
            app.send_task(scheduler_evidence.SCHEDULER_EVIDENCE_TASK,
                          kwargs={"evidence_deadline": time.time() + 5}, expires=5)
            wait_for(completed)
            assert executed.exists()
            assert reclaimed.exists()
            assert json.loads(completed.read_text()) == {
                "settled": 1, "review": 0, "active": 0, "reservations_released": 0,
            }
    finally:
        release.touch()
        task_received.disconnect(record_received)
        app.close()
