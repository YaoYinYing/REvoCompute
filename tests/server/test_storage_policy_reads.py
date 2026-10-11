# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Every storage-policy read fails closed on a row it cannot interpret.

The three-valued quota policy is only as trustworthy as its reader: a stored
``allowance`` outside the encodable set is refused by
:func:`revocompute.storage_quota.policy_from_stored_allowance` rather than read as
a limit, because reading it would let external state decide admission.  That
refusal exists on the *write* path already; these cases prove every read that meets
the same row reports the same bounded refusal instead of an HTML 500 an operator
would have to debug from a traceback — including the submission-admission read, so
a submission is refused rather than admitted against a ceiling nobody can state.

The row is planted out of band because no admin request can produce it (the write
path validates first); that is exactly the "something else wrote this table" case
the reader fails closed on.
"""

from __future__ import annotations

import io

import pytest
from conftest import _admin_client_auth, _load_pssm_module, _test_client_auth
from sqlalchemy import text

#: The reader's own bounded wording, asserted rather than a status alone: a client
#: must be told *which* stored policy is unusable, and the message must stay
#: bounded rather than rendering stored bytes back.
REFUSAL = "not a recognisable policy"


def _plant_corrupt_policy(module, user_id: int) -> None:
    """Write an unencodable storage allowance, as a foreign writer would."""
    with module.task_store.engine.begin() as conn:
        rows = conn.execute(
            text("UPDATE resource_policies SET allowance = -2 WHERE subject_id = :uid AND unit = 'storage_byte'"),
            {"uid": user_id},
        )
        assert rows.rowcount == 1


def _storage_row(module, user_id: int) -> int | None:
    with module.task_store.engine.connect() as conn:
        return conn.execute(
            text("SELECT allowance FROM resource_policies WHERE subject_id = :uid AND unit = 'storage_byte'"),
            {"uid": user_id},
        ).scalar_one_or_none()


@pytest.fixture
def deployment(monkeypatch, tmp_path):
    """A real application whose tester subject holds one real storage policy."""
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678", "ENABLED_TASKRUNNERS": "cpu_runner"},
    )
    monkeypatch.setattr(
        module.run_compute_task, "apply_async", lambda *args, **kwargs: type("R", (), {"id": "celery"})()
    )
    # The client headers create the tester subject these cases read a policy for.
    module.user_headers = _test_client_auth(module)
    module.admin_headers = _admin_client_auth(module)
    user_id = int(module.app.config["user_db"].get_user_by_username("tester")["id"])
    module.client = module.app.test_client()
    module.user_id = user_id
    # One real policy through the real admin route, so the row under test is the
    # one the write path would have produced.
    response = module.client.put(
        f"/compute/api/auth/admin/users/{user_id}/storage-quota",
        headers=module.admin_headers,
        json={"state": "limited", "limit_bytes": 1024, "reason": "baseline", "idempotency_key": "baseline"},
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    return module


def _submit(module):
    """One otherwise-valid submission, so the admission read is what answers."""
    return module.client.post(
        "/compute/api/post",
        data={
            "task_type": "cpu_runner",
            "file": (io.BytesIO(b">sequence\nACDEFGHIK\n"), "sequence.fasta"),
            "input_roles": "sequence",
        },
        headers=module.user_headers,
    )


READS = [
    ("the user's own entitlement", "user", "/compute/api/resource-entitlement"),
    ("the operator's storage-quota read", "admin", "/storage-quota"),
    ("the operator's entitlement read", "admin", "/resource-entitlement"),
    ("the resource report for one subject", "admin", "/reports/resources"),
]


def _get(module, role: str, suffix: str):
    headers = module.admin_headers if role == "admin" else module.user_headers
    if suffix == "/storage-quota":
        return module.client.get(
            f"/compute/api/auth/admin/users/{module.user_id}/storage-quota", headers=headers
        )
    if suffix == "/resource-entitlement" and role == "admin":
        return module.client.get(
            f"/compute/api/auth/admin/users/{module.user_id}/resource-entitlement", headers=headers
        )
    if suffix == "/reports/resources":
        return module.client.get(
            f"/compute/api/auth/admin/reports/resources?subject={module.user_id}", headers=headers
        )
    return module.client.get(suffix, headers=headers)


@pytest.mark.parametrize(("label", "role", "suffix"), READS, ids=[item[0] for item in READS])
def test_a_stored_policy_no_reader_can_interpret_is_refused_not_a_500(deployment, label, role, suffix):
    assert _get(deployment, role, suffix).status_code == 200, label
    _plant_corrupt_policy(deployment, deployment.user_id)

    response = _get(deployment, role, suffix)

    assert response.status_code == 503, label
    assert response.is_json, label
    assert REFUSAL in response.get_json()["error"], label
    assert len(response.get_data(as_text=True)) < 500, label


def test_the_fleet_report_is_refused_when_any_subject_holds_an_unreadable_policy(deployment):
    """The roll sums every subject with the canonical reader, so one bad row stops it.

    A fleet report that skipped the subject would publish a total that hides a fact
    an operator has to act on.
    """
    deployment.task_store.ensure_data_lifecycle("a" * 32, user_id=deployment.user_id, logical_bytes=4096)
    assert deployment.client.get(
        "/compute/api/auth/admin/reports/resources", headers=deployment.admin_headers
    ).status_code == 200
    _plant_corrupt_policy(deployment, deployment.user_id)

    response = deployment.client.get(
        "/compute/api/auth/admin/reports/resources", headers=deployment.admin_headers
    )

    assert response.status_code == 503
    assert response.is_json and REFUSAL in response.get_json()["error"]


def test_submission_admission_refuses_rather_than_admitting_against_an_unreadable_ceiling(deployment):
    """Admission reads the same envelope, so it is refused rather than guessed.

    The alternative — treating the unreadable row as "no ceiling" — would admit work
    against a policy the deployment cannot state, which is exactly the external
    state deciding admission that the reader fails closed to prevent.
    """
    _plant_corrupt_policy(deployment, deployment.user_id)

    response = _submit(deployment)

    assert response.status_code == 503, response.get_data(as_text=True)
    assert response.is_json
    assert "not interpretable" in response.get_json()["error"]


def test_a_repair_request_reports_the_same_unreadable_policy(deployment):
    """The write path already refuses it; that refusal is the bounded one, not a 500.

    The row cannot be repaired through this API (the write reads the row it is
    replacing), so the operator is told what is wrong and repairs it out of band.
    """
    _plant_corrupt_policy(deployment, deployment.user_id)

    response = deployment.client.put(
        f"/compute/api/auth/admin/users/{deployment.user_id}/storage-quota",
        headers=deployment.admin_headers,
        json={"state": "limited", "limit_bytes": 2048, "reason": "repair", "idempotency_key": "repair"},
    )

    assert response.status_code == 409
    assert REFUSAL in response.get_json()["error"]
    assert _storage_row(deployment, deployment.user_id) == -2


def test_the_refusal_is_conditional_on_the_unreadable_row_and_clears_with_it(deployment):
    """A deployment with an encodable policy is served exactly as before."""
    _plant_corrupt_policy(deployment, deployment.user_id)
    assert _get(deployment, "admin", "/storage-quota").status_code == 503

    with deployment.task_store.engine.begin() as conn:
        conn.execute(
            text("UPDATE resource_policies SET allowance = 1024 WHERE subject_id = :uid AND unit = 'storage_byte'"),
            {"uid": deployment.user_id},
        )

    restored = _get(deployment, "admin", "/storage-quota")
    assert restored.status_code == 200
    assert restored.get_json()["soft_limit_bytes"] == 1024
