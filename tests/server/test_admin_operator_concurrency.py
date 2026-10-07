# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Level 2-5 security and concurrency cases for the Admin control plane.

These drive the *real* operator service through the *real* routes, with only the
host boundary faked (it is the expensive external operation the contract is not
about), so the cases exercise the paths the remaining levels name: a stale plan
rejected at the request boundary (TOCTOU), a second operator racing the same
Runner (lease conflict), an idempotent re-click, and a mutation flood bounded by
the endpoint's own rate limit and the operator queue.
"""

from __future__ import annotations

from conftest import _admin_client_auth, _load_pssm_module
from revocompute import operator_service as service_module
from revocompute.admission import RunnerReadinessStatus
from revocompute.operator_executor import ExecutorAvailability
from revocompute.operator_jobs import OperatorJobStore
from revocompute.operator_service import OperatorService
from revocompute.runner_host import ServerHostPaths
from revocompute.runner_readiness import RunnerReadiness


class _Result:
    def __init__(self, succeeded: bool = True):
        self.succeeded = succeeded
        self.log_text = "stage log"
        self.returncode = 0 if succeeded else 1


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
        receipt_valid=False,
        receipt_tested_at="2026-01-01T00:00:00Z",
    )


def _install(monkeypatch, tmp_path, *, hold_jobs: bool = True):
    """A real operator service behind the real routes, with a scripted host boundary."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    state = {"readiness": _readiness("demo", RunnerReadinessStatus.VALIDATION_STALE, "RUNTIME_BUNDLE_CHANGED")}

    monkeypatch.setattr(service_module, "evaluate_runner_readiness", lambda _host, family: state["readiness"])
    monkeypatch.setattr(
        service_module,
        "fleet_view",
        lambda _host, *, database=None, user_id=None: [
            {
                "runner_family": "demo",
                "readiness": {
                    "status": state["readiness"].status.value,
                    "reason_code": state["readiness"].reason_code,
                },
                "capacity": {"available": None, "reason": "capacity_unknown"},
                "access": {"restricted": False, "granted": True, "policy_id": None},
            }
        ],
    )
    monkeypatch.setattr(
        service_module, "availability",
        lambda _host: ExecutorAvailability(True, "operator_executor_available"),
    )
    integrity_calls: list[str] = []
    monkeypatch.setattr(
        service_module, "execute",
        lambda _host, *, action_id, runner_family, parameters=None: (integrity_calls.append(runner_family), _Result())[1],
    )
    host = ServerHostPaths(
        server=str(tmp_path / "server"), config=str(tmp_path / "config"), root=str(tmp_path)
    )
    service = OperatorService(
        host,
        store=OperatorJobStore(str(tmp_path / "server-operator-jobs.sqlite")),
        database=None,
        # Hold mutations at QUEUED so lease/queue behaviour is observable.
        scheduler=(lambda work: None) if hold_jobs else (lambda work: work()),
    )
    module.app.config["operator_service"] = service
    return module, service, state, integrity_calls


def _plan(client, headers, family="demo", action="runner.live_test"):
    response = client.post(f"/compute/api/auth/admin/runners/{family}/plan", headers=headers, json={"action": action})
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def test_a_stale_plan_digest_is_rejected_at_the_route(monkeypatch, tmp_path):
    """TOCTOU: evidence moves between plan and execute, so the execute is refused."""
    module, _service, state, integrity_calls = _install(monkeypatch, tmp_path)
    client = module.app.test_client()
    headers = _admin_client_auth(module)

    plan = _plan(client, headers)
    # Another administrator (or the CLI, or a new receipt) changes the evidence.
    state["readiness"] = _readiness("demo", RunnerReadinessStatus.VALIDATION_STALE, "RECEIPT_STALE")

    response = client.post(
        "/compute/api/auth/admin/runners/demo/actions",
        headers=headers,
        json={"action": "runner.live_test", "plan_digest": plan["plan_digest"]},
    )
    assert response.status_code == 409
    assert response.get_json()["code"] == "stale_plan"
    assert integrity_calls == []  # nothing ran


def test_a_second_administrator_cannot_race_the_same_runner(monkeypatch, tmp_path):
    """One exclusive lease per Runner family: the second mutation is refused."""
    module, _service, _state, integrity_calls = _install(monkeypatch, tmp_path)
    client = module.app.test_client()
    first = _admin_client_auth(module, username="admin_one")
    second = _admin_client_auth(module, username="admin_two")

    secured = client.post(
        "/compute/api/auth/admin/runners/demo/plan", headers=first, json={"action": "runner.live_test"}
    ).get_json()
    started = client.post(
        "/compute/api/auth/admin/runners/demo/actions",
        headers=first,
        json={"action": "runner.live_test", "plan_digest": secured["plan_digest"]},
    )
    assert started.status_code == 202

    contested = client.post(
        "/compute/api/auth/admin/runners/demo/actions",
        headers=second,
        json={"action": "runner.live_test", "plan_digest": secured["plan_digest"]},
    )
    assert contested.status_code == 409
    assert contested.get_json()["code"] == "operation_in_progress"
    assert integrity_calls == []  # the held job has not executed either


def test_a_repeated_click_does_not_duplicate_the_mutation(monkeypatch, tmp_path):
    """Idempotency: the same key returns the existing job instead of a second one."""
    module, service, _state, _integrity_calls = _install(monkeypatch, tmp_path)
    client = module.app.test_client()
    headers = _admin_client_auth(module)

    plan = _plan(client, headers)
    body = {"action": "runner.live_test", "plan_digest": plan["plan_digest"], "idempotency_key": "click-1"}
    first = client.post("/compute/api/auth/admin/runners/demo/actions", headers=headers, json=body)
    second = client.post("/compute/api/auth/admin/runners/demo/actions", headers=headers, json=body)

    assert first.status_code == 202 and first.get_json()["accepted"] is True
    assert second.status_code == 200 and second.get_json()["accepted"] is False
    assert second.get_json()["job"]["job_id"] == first.get_json()["job"]["job_id"]
    assert len(service.jobs()) == 1


def test_a_mutation_flood_is_bounded_not_unbounded(monkeypatch, tmp_path):
    """A flood of distinct mutations is bounded by the endpoint's own controls.

    Two independent bounds apply: the endpoint's request rate limit and the
    bounded operator queue.  Either way the control plane never runs unbounded
    work and never surfaces an unhandled error.
    """
    module, service, _state, _integrity_calls = _install(monkeypatch, tmp_path, hold_jobs=False)
    client = module.app.test_client()
    headers = _admin_client_auth(module)

    outcomes: list[int] = []
    for index in range(60):
        plan = _plan(client, headers)
        response = client.post(
            "/compute/api/auth/admin/runners/demo/actions",
            headers=headers,
            json={"action": "runner.live_test", "plan_digest": plan["plan_digest"], "idempotency_key": f"flood-{index}"},
        )
        outcomes.append(response.status_code)

    # Every response is one of the control plane's own bounded outcomes; a flood
    # never produces a server error or an unbounded amount of accepted work.
    assert all(status in {200, 202, 409, 429} for status in outcomes), outcomes
    assert outcomes.count(202) + outcomes.count(200) <= 30
    assert 429 in outcomes  # the endpoint's rate bound engaged
    assert len(service.jobs(limit=200)) <= 64  # the operator queue bound held
