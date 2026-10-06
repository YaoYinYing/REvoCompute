# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The Admin operator service: plan-revalidate, lease, run, and record.

The Web layer reaches the control core only through this service, so these cases
drive the real service with a fake host boundary (the executor is the expensive
external operation the contract is not about).  They prove stale plans fail
closed, a mutation reserves its lease before running, requested intent is kept
beside effective actions, and a failed operation never produces a false READY.
"""

from __future__ import annotations

import pytest
from revocompute import operator_service as service_module
from revocompute.admission import RunnerReadinessStatus
from revocompute.operator_executor import ExecutorUnavailable, UnsupportedOperation
from revocompute.operator_jobs import OperatorConflictError, OperatorJobError, OperatorJobStatus, OperatorJobStore
from revocompute.operator_plan import StalePlanError
from revocompute.operator_service import OperatorService, OperatorServiceError
from revocompute.runner_host import ServerHostPaths
from revocompute.runner_readiness import RunnerReadiness


class _Result:
    def __init__(self, succeeded: bool, log_text: str = "ok"):
        self.succeeded = succeeded
        self.log_text = log_text
        self.returncode = 0 if succeeded else 1


@pytest.fixture
def host(tmp_path) -> ServerHostPaths:
    return ServerHostPaths(server=str(tmp_path / "server"), config=str(tmp_path / "config"), root=str(tmp_path))


def _readiness(family: str, status: RunnerReadinessStatus, reason: str) -> RunnerReadiness:
    return RunnerReadiness(
        runner_family=family,
        status=status,
        reason_code=reason,
        message=reason,
        doctor_ok=True,
        sif_path=f"/images/{family}.sif",
        sif_exists=True,
        sif_sha256="sha256:sif",
        build_provenance_current=True,
        build_provenance_digest="sha256:build",
        runtime_bundle_sha256="sha256:bundle",
        receipt_exists=True,
        receipt_valid=status is RunnerReadinessStatus.READY,
        receipt_tested_at="2026-01-01T00:00:00Z",
    )


def _service(monkeypatch, host, *, status=RunnerReadinessStatus.VALIDATION_STALE, reason="RUNTIME_BUNDLE_CHANGED",
             executor_available=True, results=None, scheduler=None):
    """A service whose readiness evaluator, fleet view, and host boundary are scripted fakes."""
    state = {"readiness": _readiness("demo", status, reason)}

    monkeypatch.setattr(service_module, "evaluate_runner_readiness", lambda _host, family: state["readiness"])
    monkeypatch.setattr(
        service_module,
        "fleet_view",
        lambda _host, *, database=None, user_id=None: [
            {
                "runner_family": "demo",
                "readiness": {"status": state["readiness"].status.value, "reason_code": state["readiness"].reason_code},
                "capacity": {"available": None, "reason": "capacity_unknown"},
                "access": {"restricted": False, "granted": True, "policy_id": None},
            }
        ],
    )
    from revocompute.operator_executor import ExecutorAvailability

    monkeypatch.setattr(
        service_module, "availability",
        lambda _host: ExecutorAvailability(executor_available, "operator_executor_" + ("available" if executor_available else "unavailable")),
    )
    queue = list(results or [True])

    def fake_execute(_host, *, action_id, runner_family, parameters=None):
        calls.append(action_id)
        outcome = queue.pop(0) if queue else True
        if isinstance(outcome, Exception):
            raise outcome
        return _Result(bool(outcome), log_text="stage log")

    calls: list[str] = []
    monkeypatch.setattr(service_module, "execute", fake_execute)
    # A per-test store inside the test's own tmp tree, never the shared /tmp.
    store = OperatorJobStore(host.server_dir() + "-operator-jobs.sqlite")
    return OperatorService(host, store=store, scheduler=scheduler or (lambda work: work())), state, calls


def _submit(service, *, action="runner.live_test", digest=None, key=None, actor=1):
    plan = service.plan(action, "demo")
    return service.submit(
        action,
        "demo",
        plan_digest=digest if digest is not None else plan.plan_digest,
        actor_user_id=actor,
        actor_username=f"admin{actor}",
        idempotency_key=key,
    )


def test_a_stale_plan_digest_is_rejected_before_any_execution(monkeypatch, host):
    service, _state, calls = _service(monkeypatch, host)
    with pytest.raises(StalePlanError, match="review the new plan"):
        _submit(service, digest="sha256:" + "0" * 8)
    assert calls == []
    assert service.jobs() == []


def test_a_plan_whose_evidence_moved_is_rejected(monkeypatch, host):
    service, state, calls = _service(monkeypatch, host)
    plan = service.plan("runner.live_test", "demo")
    # A new receipt / runtime bundle lands between planning and execution.
    state["readiness"] = _readiness("demo", RunnerReadinessStatus.VALIDATION_STALE, "RECEIPT_STALE")
    with pytest.raises(StalePlanError):
        service.submit(
            "runner.live_test", "demo", plan_digest=plan.plan_digest, actor_user_id=1, actor_username="admin1"
        )
    assert calls == []


def test_a_mutation_reserves_a_job_and_records_intent_beside_effective_actions(monkeypatch, host):
    service, _state, calls = _service(monkeypatch, host)
    outcome = _submit(service)
    assert outcome.created is True
    assert calls == ["runner.live_test"]

    job = service.job(outcome.job["job_id"])
    assert job["status"] == OperatorJobStatus.SUCCEEDED.value
    assert job["effect"]["requested_intent"] == "runner.live_test"
    assert job["effect"]["effective_actions"] == ["live_test"]
    assert job["effect"]["before"]["status"] == "VALIDATION_STALE"
    assert job["effect"]["after"]["status"] == "VALIDATION_STALE"  # receipt not actually written by the fake


def test_a_failed_operation_records_the_failure_and_never_a_false_ready(monkeypatch, host):
    service, _state, _calls = _service(monkeypatch, host, results=[False])
    outcome = _submit(service)

    job = service.job(outcome.job["job_id"])
    assert job["status"] == OperatorJobStatus.FAILED.value
    assert job["failure_category"] == "operation_failed"
    assert job["effect"]["effective_actions"] == ["live_test"]  # partial progress is recorded
    assert job["result"]["status"] != "READY"


def test_an_operation_the_host_cannot_run_is_refused_not_approximated(monkeypatch, host):
    service, _state, calls = _service(monkeypatch, host, status=RunnerReadinessStatus.NOT_BUILT, reason="SIF_MISSING")
    # repair on a missing SIF plans build + live_test, and build has no host command.
    plan = service.plan("runner.repair", "demo")
    assert plan.effective_actions == ("build", "live_test")
    with pytest.raises(UnsupportedOperation):
        service.submit(
            "runner.repair", "demo", plan_digest=plan.plan_digest, actor_user_id=1, actor_username="admin1"
        )
    assert calls == []


def test_an_unavailable_executor_fails_closed_without_a_job(monkeypatch, host):
    service, _state, calls = _service(monkeypatch, host, executor_available=False)
    with pytest.raises(ExecutorUnavailable):
        _submit(service)
    assert calls == []
    assert service.jobs() == []


def test_executor_loss_during_execution_marks_the_job_failed(monkeypatch, host):
    service, _state, _calls = _service(monkeypatch, host, results=[ExecutorUnavailable("gone")])
    outcome = _submit(service)
    job = service.job(outcome.job["job_id"])
    assert job["status"] == OperatorJobStatus.FAILED.value
    assert job["failure_category"] == "executor_unavailable"


def test_a_second_conflicting_mutation_is_rejected_while_the_first_holds_the_lease(monkeypatch, host):
    service, _state, _calls = _service(monkeypatch, host, scheduler=lambda work: None)  # holds the job at QUEUED
    first = _submit(service, key="one")
    assert first.created is True
    with pytest.raises(OperatorConflictError):
        _submit(service, key="two", actor=2)


def test_an_idempotent_retry_returns_the_same_job_without_re_executing(monkeypatch, host):
    service, _state, calls = _service(monkeypatch, host)
    first = _submit(service, key="same")
    second = _submit(service, key="same")
    assert second.created is False
    assert second.job["job_id"] == first.job["job_id"]
    assert calls == ["runner.live_test"]  # the second click did not re-run the host operation


def test_a_read_action_runs_inline_without_a_durable_job(monkeypatch, host):
    service, _state, calls = _service(monkeypatch, host)
    outcome = _submit(service, action="runner.status")
    assert outcome.job["job_id"] is None
    assert outcome.job["status"] == OperatorJobStatus.SUCCEEDED.value
    assert calls == ["runner.status"]
    assert service.jobs() == []  # status refreshes do not bury the history


def test_cancellation_only_touches_the_operators_own_job(monkeypatch, host):
    service, _state, _calls = _service(monkeypatch, host, scheduler=lambda work: None)
    mine = _submit(service, key="a", actor=1)
    with pytest.raises(OperatorServiceError, match="Only the requesting operator"):
        service.cancel(mine.job["job_id"], actor_user_id=2)
    cancelled = service.cancel(mine.job["job_id"], actor_user_id=1)
    assert cancelled["status"] == OperatorJobStatus.CANCELLED.value


def test_reconciliation_terminalizes_orphans_and_never_retries(monkeypatch, host):
    service, _state, calls = _service(monkeypatch, host, scheduler=lambda work: None)
    outcome = _submit(service)  # holds at QUEUED; the caller drives it to RUNNING
    service.store.transition(
        outcome.job["job_id"], expected=(OperatorJobStatus.QUEUED,), new_status=OperatorJobStatus.RUNNING
    )
    reconciled = service.reconcile()
    assert reconciled == [outcome.job["job_id"]]
    job = service.job(outcome.job["job_id"])
    assert job["status"] == OperatorJobStatus.FAILED.value
    assert job["failure_category"] == "orphaned_executor_restart"
    assert calls == []  # reconciliation terminalizes the record; it never executes


def test_available_actions_are_state_aware(monkeypatch, host):
    service, _state, _calls = _service(monkeypatch, host)
    actions = {action["id"]: action for action in service.available_actions("demo")}
    assert actions["runner.live_test"]["available"] is True
    assert actions["runner.live_test"]["plan"]["effective_actions"] == ["live_test"]
    # A repair of a stale validation reuses the SIF and is offered.
    assert actions["runner.repair"]["available"] is True
    assert actions["runner.repair"]["plan"]["effective_actions"] == ["live_test"]


def test_detail_reports_unknown_families_as_not_found(monkeypatch, host):
    service, _state, _calls = _service(monkeypatch, host)
    from revocompute.operator_service import OperatorNotFound

    with pytest.raises(OperatorNotFound):
        service.detail("absent", user_id=1)
