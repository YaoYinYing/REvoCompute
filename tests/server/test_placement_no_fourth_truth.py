# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Adversarial regression for the no-fourth-truth boundary of PR #73.

Accounting records facts, policy changes entitlement, placement records the
historical decision, and Admin reports those facts.  That holds only if there is
exactly one resolver, one frozen snapshot per submission, and one recorded
decision: never a second ledger, a shadow scheduler, or a reader that re-derives
an answer it was supposed to remember.

Every case attacks a seam of that sentence on the real production path: the Task
is submitted through POST /compute/api/post, the deployment is configured through
the same ManageDatabase the admin config API writes, and the answers are read
through the real HTTP routes.  Where an answer must not be recomputed, the
resolver is armed to raise, so a recomputation fails loudly instead of quietly
agreeing by coincidence.  A failure here is a product defect, not a test bug.
"""

from __future__ import annotations

import io
import json
from types import SimpleNamespace

import pytest
from conftest import _admin_client_auth, _load_pssm_module, _test_client_auth
from revocompute import placement as placement_module
from revocompute import resource_policy
from revocompute.db import TaskDatabase
from revocompute.manage_db import ManageDatabase
from revocompute.placement import PLACED_CPU, PlacementDecision
from revocompute.resource_ledger import LedgerKind
from revocompute.resource_policy import ResolvedResources, resolve_resources

TASKS = "/compute/api/auth/admin/reports/tasks"
RESOURCES = "/compute/api/auth/admin/reports/resources"
INTEGRITY = "/compute/api/auth/admin/reports/integrity"
ACTIVITY = "/compute/api/auth/admin/reports/activity"
TASK_LIST = "/compute/api/tasks"
REPORTS = (TASKS, RESOURCES, INTEGRITY, ACTIVITY)
MAX_LIMIT = 200  # admin_reports.MAX_LIMIT, the canonical ceiling for a bounded read
GIB = 1024**3

# Map A is where the Task is submitted; map B moves CPU work to a different queue
# and drops the accelerator class, so a reader that re-resolved must answer
# differently.  Nothing below ever reads today's answer for the Task under test.
MOVE_A = {"classes": "cpu=normal;a100=gpu", "queues": ("normal", "gpu"), "gres": "gpu:a100:1"}
MOVE_B = {"classes": "cpu=other", "queues": ("other",), "gres": None}


def _point(manage: ManageDatabase, *, classes=None, queues=(), gres=None) -> None:
    """Re-point the deployment through the store the admin config API writes."""
    manage.resource_set("slurm_allowed_queues", list(queues))
    manage.resource_set("slurm_execution_classes", classes)
    manage.resource_set("slurm_gres", gres)


@pytest.fixture
def app(monkeypatch, tmp_path):
    """A real application with a live ManageDatabase, as a deployment runs it."""
    module = _load_pssm_module(
        monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"}
    )
    monkeypatch.setattr(
        module.run_compute_task, "apply_async", lambda *args, **kwargs: SimpleNamespace(id="celery")
    )
    _point(module.app.config["manage_db"], **MOVE_A)
    module.user_headers = _test_client_auth(module)
    user = module.app.config["user_db"].get_user_by_username("tester")
    module.app.config["user_db"].update_user(user["id"], allow_gpu_use=True, account_enabled=True)
    module.test_user = user
    return module


def _submit(module, *, task_type="cpu_runner"):
    """One real submission through POST /compute/api/post."""
    response = module.app.test_client().post(
        "/compute/api/post",
        headers=module.user_headers,
        data={
            "task_type": task_type,
            "files": (io.BytesIO(b">sequence\nACDEFGHIK\n"), "sequence.fasta"),
            "input_roles": "sequence",
        },
        content_type="multipart/form-data",
    )
    assert response.status_code in {200, 201, 202, 302}, response.get_data(as_text=True)


def _task_row(module) -> dict:
    tasks = module.task_store.list_tasks()
    assert len(tasks) == 1, tasks
    return tasks[0]


def _form(module) -> dict:
    return json.loads(_task_row(module)["input_form"])


def _write_form(module, form: dict) -> None:
    """Write a tampered record back through the real store, as an editor would."""
    module.task_store.update_task(_task_row(module)["md5sum"], input_form=json.dumps(form))


def _report_entry(module, *, path=TASKS, query="") -> dict:
    """One Task's row from an Admin report, read as an administrator."""
    response = module.app.test_client().get(f"{path}{query}", headers=_admin_client_auth(module))
    assert response.status_code == 200, response.get_data(as_text=True)
    return next(item for item in response.get_json()["tasks"] if item["task_id"] == _task_row(module)["md5sum"])


def _list_summary(module) -> dict:
    response = module.app.test_client().get(TASK_LIST, headers=module.user_headers)
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()["tasks"][0]


def _explode(*_args, **_kwargs):
    raise AssertionError("the resolver must not be called while reading a recorded decision")


def _arm_the_resolvers(monkeypatch, module) -> None:
    """Make any recomputation during a read an immediate, loud failure."""
    monkeypatch.setattr(ManageDatabase, "resolve_task_resources", _explode)
    monkeypatch.setattr(resource_policy, "resolve_resources", _explode)
    monkeypatch.setattr(placement_module, "resolve_submission_placement", _explode)
    monkeypatch.setattr(placement_module, "place_stage", _explode)
    monkeypatch.setattr(placement_module, "place_resolved", _explode)
    # Non-vacuity: the armed resolver really raises, so a read that used it would
    # fail here rather than quietly agreeing with the record a second time.
    with pytest.raises(AssertionError):
        module.app.config["manage_db"].resolve_task_resources(
            "cpu_runner", requires_gpu=False, default_timeout_seconds=60
        )


def _expected(recorded: dict) -> PlacementDecision:
    """The one canonical read: recorded decision joined to its frozen snapshot."""
    return PlacementDecision.from_record(
        recorded["placement_decision"], ResolvedResources.from_snapshot(recorded["resource_policy"])
    )


def _todays_answer(module) -> str:
    """What today's policy would place this work into, computed by the test alone."""
    resolved = module.app.config["manage_db"].resolve_task_resources(
        "cpu_runner", requires_gpu=False, default_timeout_seconds=3600
    )
    return placement_module.ExecutionClass.from_resolved(resolved).identifier


# --- 1. No resolver on read: one recorded decision, read as recorded ---


def test_a_recorded_placement_survives_a_policy_move_with_every_resolver_armed(app, monkeypatch):
    _submit(app)
    recorded = _form(app)
    assert recorded["placement_decision"]["execution_class"]["partition"] == "normal"

    _point(app.app.config["manage_db"], **MOVE_B)
    assert _todays_answer(app) == "cpu|other|none"
    _arm_the_resolvers(monkeypatch, app)

    placement = _report_entry(app)["placement"]
    expected = _expected(recorded)

    assert placement["state"] == "recorded"
    assert placement["execution_class_id"] == expected.execution_class.identifier == "cpu|normal|none"
    assert placement["reason_code"] == expected.reason_code == PLACED_CPU
    assert placement["policy_revision"] == expected.policy_revision
    assert placement["policy_revision"] == recorded["placement_decision"]["policy_revision"]


def test_the_task_list_and_the_resource_report_need_no_resolver_either(app, monkeypatch):
    _submit(app)
    recorded = _form(app)
    _point(app.app.config["manage_db"], **MOVE_B)
    _arm_the_resolvers(monkeypatch, app)

    assert _list_summary(app)["placement"] == _expected(recorded).execution_class.to_dict()

    response = app.app.test_client().get(
        f"{RESOURCES}?subject={app.test_user['id']}", headers=_admin_client_auth(app)
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.get_json()["canonical_envelope"]["subject_id"] == app.test_user["id"]


# --- 2. One answer: two readers of one Task cannot disagree ---


def test_the_report_and_the_task_list_agree_about_one_task_after_a_policy_move(app):
    _submit(app)
    recorded = _form(app)
    _point(app.app.config["manage_db"], **MOVE_B)
    assert _todays_answer(app) == "cpu|other|none"

    report_placement = _report_entry(app)["placement"]
    summary_placement = _list_summary(app)["placement"]

    assert report_placement["execution_class_id"] == summary_placement["id"] == "cpu|normal|none"
    assert report_placement["policy_revision"] == recorded["placement_decision"]["policy_revision"]


# --- 3. A tampered or partial record degrades, never 500s and never invents ---

# Each entry rewrites one Task's recording into a shape a later edit could leave.
_TAMPERED = {
    "snapshot_missing": lambda f: f.pop("resource_policy"),
    "snapshot_disagrees": lambda f: f["placement_decision"]["execution_class"].__setitem__(
        "partition", "elsewhere"
    ),
    "snapshot_garbage": lambda f: f.__setitem__("resource_policy", [["cpus", 1]]),
    "snapshot_inconsistent": lambda f: f["resource_policy"].__setitem__("slurm_time", "99:00:00"),
    "reason_unbounded": lambda f: f["placement_decision"].__setitem__("reason_code", "totally_fine"),
    "requirement_unparseable": lambda f: f["placement_decision"].__setitem__(
        "accelerator_requirement", {"class": "a100", "count": "many"}
    ),
    "decision_garbage": lambda f: f.__setitem__("placement_decision", "not-a-record"),
}


@pytest.mark.parametrize("tamper", sorted(_TAMPERED))
def test_a_tampered_record_degrades_to_unreadable_over_http(app, tamper):
    _submit(app)
    form = _form(app)
    _TAMPERED[tamper](form)
    _write_form(app, form)

    placement = _report_entry(app)["placement"]

    assert placement["state"] == "unreadable", tamper
    assert placement["execution_class_id"] is None, tamper
    assert placement["reason_code"] is None, tamper


def test_a_task_with_no_decision_reads_unrecorded_and_never_as_todays_class(app):
    _submit(app)
    form = _form(app)
    form.pop("placement_decision")
    form.pop("resource_policy")
    _write_form(app, form)

    placement = _report_entry(app)["placement"]

    assert placement["state"] == "unrecorded"
    assert placement["execution_class_id"] is None
    assert placement["policy_revision"] is None
    # Today's policy would name the CPU class, so this shows neither reader is
    # taking the absent decision's place with a guess.
    assert _todays_answer(app) == "cpu|normal|none"
    assert _list_summary(app)["placement"] is None


def test_a_workflow_records_one_decision_per_stage_and_keeps_it_when_the_class_is_gone(app):
    _submit(app, task_type="multistage_runner")
    form = _form(app)
    # A workflow's primary profile is not a stage, so it records no decision: one
    # per stage would otherwise place the same work twice.
    assert form["placement_decision"] is None and form["resource_policy"] is None
    assert len(form["placement_decisions"]) == len(form["resource_policies"]) == 2
    assert form["placement_decisions"]["multistage_runner.model"]["execution_class"]["partition"] == "gpu"

    # Map B has no accelerator class at all, so re-resolving that stage would
    # refuse outright rather than name a class.
    _point(app.app.config["manage_db"], **MOVE_B)
    stages = {item["stage"]: item for item in _report_entry(app)["placements"]}

    assert sorted(stages, key=str) == [None, "multistage_runner.features", "multistage_runner.model"]
    assert stages[None]["state"] == "unrecorded"
    assert stages["multistage_runner.features"]["execution_class_id"] == "cpu|normal|none"
    assert stages["multistage_runner.model"]["execution_class_id"] == "accelerator|gpu|a100x1"


# --- 4. Accounting is not policy: a quota change moves entitlement and nothing else ---


def _ledger_rows(store: TaskDatabase) -> int:
    """How many rows the append-only ledger holds, read straight from the table."""
    from sqlalchemy import func, select

    with store.engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(store.resource_ledger_table)).scalar_one()


def test_a_sequence_of_quota_changes_leaves_accounting_byte_for_byte_identical(tmp_path):
    store = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    try:
        store.ensure_data_lifecycle("a" * 32, user_id=7, logical_bytes=2 * GIB)
        before = {
            "bytes": store.logical_owned_bytes(7),
            "ledger": store.list_ledger(7, limit=200),
            "rows": _ledger_rows(store),
        }
        assert before["bytes"] == 2 * GIB and before["rows"] > 0
        # The only ledger fact is the ownership charge itself: a quota change is
        # policy, and must not append a row of any kind.
        assert {(r["kind"], r["unit"]) for r in before["ledger"]} == {
            (LedgerKind.STORAGE_USAGE.value, "storage_byte")
        }

        changes = (("limited", GIB, "q1"), ("unlimited", None, "q2"), ("limited", 0, "q3"), ("inherit", None, "q4"))
        seen: list[int | None] = []
        for index, (state, limit_bytes, key) in enumerate(changes):
            store.set_storage_quota(
                user_id=7, state=state, limit_bytes=limit_bytes, actor_user_id=3,
                reason=f"quota change {index}", idempotency_key=key, updated_at=2_000.0 + index,
            )
            seen.append(store.effective_storage_limit_bytes(7))
            assert store.logical_owned_bytes(7) == before["bytes"], state
            assert store.list_ledger(7, limit=200) == before["ledger"], state
            assert _ledger_rows(store) == before["rows"], state

        # The policy really did move through all three states, so the accounting
        # equality above is not vacuous: a reader saw each decision take effect.
        assert seen == [GIB, None, 0, store.storage_soft_limit_bytes]
        # The administrative act is still recorded, as policy, where it belongs.
        assert [r["operation"] for r in store.list_policy_audit(7, limit=10)] == [
            "clear_storage_quota",
            "set_storage_quota",
            "set_storage_quota",
            "set_storage_quota",
        ]
    finally:
        store.engine.dispose()


# --- 5. Unknown is never zero ---


def test_an_unmeasured_measurement_reports_unknown_and_then_the_measured_fact(app):
    client = app.app.test_client()
    admin = _admin_client_auth(app)
    user_id = app.test_user["id"]
    units = client.get(f"{RESOURCES}?subject={user_id}", headers=admin).get_json()["units"]

    assert [unit["unit"] for unit in units] == ["gpu_second", "cpu_core_second"]
    for unit in units:
        assert unit["state"] == "unmeasured", unit
        assert unit["measured"] is False
        assert unit["measurement"]["used"] is None
        assert unit["measurement"]["state"] == "unknown"
        # The allowance is policy and is still reported beside the withheld number.
        assert unit["allowance"] == unit["canonical"]["allowance"]

    # The control: once a real allocation fact exists the same read reports a
    # measurement, so "unmeasured" above is a withheld number, not a broken read.
    app.task_store.record_allocation_start(
        user_id=user_id, task_id="a" * 32, stage_id="model", slurm_job_id="9700",
        gpu_count=2, cpu_cores=1, started_at=1_000.0,
    )
    gpu = next(
        unit
        for unit in client.get(f"{RESOURCES}?subject={user_id}", headers=admin).get_json()["units"]
        if unit["unit"] == "gpu_second"
    )

    assert gpu["state"] == "measured" and gpu["measured"] is True
    # A live allocation definitely consumed something whose duration is not known
    # yet, so the recorded usage is a lower bound rather than a settled number.
    assert gpu["measurement"]["usage_complete"] is False
    assert gpu["measurement"]["unsettled_allocations"] == 1
    assert gpu["pressure"] == "unknown_unsettled"


def test_unmeasured_runtime_is_reported_as_no_total_rather_than_zero(app):
    _submit(app)
    entry = _report_entry(app)

    assert entry["walltime_seconds"] is None
    assert entry["run_seconds"] is None
    assert entry["queue_seconds"] is None
    assert entry["submitted_at"] is not None and entry["status"] == "pending"
    report = app.app.test_client().get(TASKS, headers=_admin_client_auth(app)).get_json()
    assert report["runtime"]["state"] == "unknown"
    assert report["runtime"]["total_seconds"] is None and report["runtime"]["measured"] == 0
    assert report["queue_latency"]["total_seconds"] is None

    # The control: once the store records a runtime, the same reader reports it.
    app.task_store.update_task(
        _task_row(app)["md5sum"], status="finished", started_at=1_000.0, finished_at=1_060.0, walltime=60.0
    )
    settled = _report_entry(app)

    assert settled["walltime_seconds"] == 60.0 and settled["run_seconds"] == 60.0


def test_the_report_projects_the_canonical_envelope_without_reshaping_a_field(app):
    client = app.app.test_client()
    canonical = client.get("/compute/api/resource-entitlement", headers=app.user_headers).get_json()
    report = client.get(f"{RESOURCES}?subject={app.test_user['id']}", headers=_admin_client_auth(app)).get_json()

    assert report["canonical_envelope"] == canonical
    for unit in report["units"]:
        expected = next(item for item in canonical["compute"] if item["unit"] == unit["unit"])
        assert unit["canonical"] == expected, unit["unit"]
        assert unit["allowance"] == expected["allowance"], unit["unit"]
    assert report["storage"]["effective_limit_bytes"] == canonical["storage"]["soft_limit_bytes"]


# --- 6. Placement is not a scheduler, and a report is not a writer ---


def test_the_placement_layer_exposes_no_way_to_touch_a_scheduler(monkeypatch, tmp_path):
    forbidden = ("submit", "cancel", "sbatch", "scancel", "squeue", "sinfo", "scontrol", "sacct")
    exposed = {name for name in vars(placement_module) if not name.startswith("_")}
    assert [name for name in exposed if any(token in name.lower() for token in forbidden)] == []
    assert not [name for name in exposed if name.endswith(("Job", "Launcher", "Scheduler"))]
    # One resolver, and it is the deployment's own: placement imports canonical
    # resolution rather than owning a second one.
    assert "resolve_resources" not in exposed
    assert {"resolve_submission_placement", "ResolvedResources"} <= exposed

    # And the behaviour: planning runs with process creation armed to explode, so
    # a planner that shelled out to probe a queue could not produce a plan.
    manage = ManageDatabase(str(tmp_path / "manage.sqlite3"))
    try:
        _point(manage, **MOVE_A)
        before = dict(manage.resource_all())
        monkeypatch.setattr(
            placement_module, "subprocess", SimpleNamespace(Popen=_explode, run=_explode), raising=False
        )
        monkeypatch.setattr(
            resource_policy, "subprocess", SimpleNamespace(Popen=_explode, run=_explode), raising=False
        )
        decision = placement_module.resolve_submission_placement(
            manage,
            SimpleNamespace(name="demo", gpus=False, workflow=(), accelerator_requirement=None),
            SimpleNamespace(max_runtime_seconds=3600),
        ).primary_decision

        assert decision.reason_code == PLACED_CPU
        assert decision.execution_class.identifier == "cpu|normal|none"
        assert dict(manage.resource_all()) == before
    finally:
        manage.close()


def _canonical_state(module) -> dict:
    """Every canonical store the reports compose, rendered as comparable text."""
    store = module.task_store
    rows = {
        "tasks": store.list_tasks(),
        "ledger": store.list_ledger(1, limit=200),
        "lifecycle": store.list_data_lifecycle(limit=500),
        "allocations": store.list_unsettled_allocations(),
        "reservations": store.list_reservations(limit=200),
    }
    return {name: [json.dumps(row, sort_keys=True, default=str) for row in items] for name, items in rows.items()}


def test_reading_the_reports_cannot_mutate_canonical_state(app):
    _submit(app)
    # A lifecycle row charging bytes for a Task that does not exist is drift the
    # integrity report must detect, name, and leave exactly where it found it.
    app.task_store.ensure_data_lifecycle("f" * 32, user_id=4242, logical_bytes=GIB)
    client = app.app.test_client()
    admin = _admin_client_auth(app)
    # The first canonical read materializes the period's grant fact once; a read
    # that wrote anything of its own would keep writing it on every call.
    client.get("/compute/api/resource-entitlement", headers=app.user_headers)

    detected = client.get(INTEGRITY, headers=admin)
    assert detected.status_code == 200 and detected.get_json()["state"] == "drift_detected"
    first = _canonical_state(app)

    for path in REPORTS:
        assert client.get(path, headers=admin).status_code == 200, path
    assert _canonical_state(app) == first


# --- 7. Bounded refusals and the administrator boundary ---


def test_every_report_route_requires_an_administrator(app):
    client = app.app.test_client()
    admin = _admin_client_auth(app)
    for path in REPORTS:
        assert client.get(path).status_code == 401, path
        assert client.get(path, headers=app.user_headers).status_code == 403, path
        assert client.get(path, headers=admin).status_code == 200, path


def test_the_page_size_is_bounded_and_an_unusable_one_is_refused(app):
    client = app.app.test_client()
    admin = _admin_client_auth(app)

    # A page above the ceiling is clamped, and the page says so rather than
    # reading as the whole fleet.
    clamped = client.get(f"{TASKS}?limit=100000", headers=admin).get_json()
    assert clamped["limit_ceiling"] == MAX_LIMIT
    assert clamped["window"]["limit"] == clamped["window"]["limit_ceiling"] == MAX_LIMIT

    not_a_number = client.get(f"{TASKS}?limit=all", headers=admin)
    assert not_a_number.status_code == 400
    error = not_a_number.get_json()["error"]
    assert "limit" in error and len(error) <= 120

    for query in ("?limit=0", "?limit=-1"):
        response = client.get(f"{TASKS}{query}", headers=admin)
        assert response.status_code == 400, query
        assert "limit" in response.get_json()["error"], query


# --- 8. One writer per fact: the decision is recorded once, beside its snapshot ---


def _snapshot_keys() -> set[str]:
    """The exact key set ResolvedResources persists, taken from the type."""
    return set(
        resolve_resources(
            lambda _field: None,
            lambda _field: None,
            requires_gpu=False,
            allowed_queues=(),
            default_timeout_seconds=60,
        ).public_dict()
    )


def test_a_single_stage_submission_records_exactly_one_decision_and_one_snapshot(app):
    _submit(app)
    form = _form(app)

    for key in ("placement_decision", "placement_decisions", "resource_policy", "resource_policies"):
        assert key in form, key
    assert isinstance(form["placement_decision"], dict) and isinstance(form["resource_policy"], dict)
    assert form["placement_decisions"] == {} and form["resource_policies"] == {}


def test_the_decision_does_not_restate_the_resolved_fields_it_was_derived_from(app):
    """Two halves of one decision: the class is named once, the request frozen once."""
    _submit(app)
    form = _form(app)
    record, snapshot = form["placement_decision"], form["resource_policy"]

    assert set(record) == {
        "stage",
        "requires_accelerator",
        "accelerator_requirement",
        "execution_class",
        "policy_revision",
        "reason_code",
        "reason",
    }
    assert set(record) & _snapshot_keys() == set()
    assert {"partition", "gres", "cpus", "device_class", "device_count"} & set(record) == set()

    # They meet by value only where the design intends: the join reconstructs one
    # decision, and neither half copies the other's fields.
    decision = PlacementDecision.from_record(record, ResolvedResources.from_snapshot(snapshot))
    assert decision.execution_class.to_dict() == record["execution_class"]
    assert decision.resources.public_dict() == snapshot
    assert (record["execution_class"]["partition"] or None) == snapshot["partition"]
