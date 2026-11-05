from __future__ import annotations

import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))

from revocompute.admission import RunnerReadinessStatus, resolve_submission_readiness  # noqa: E402
from revocompute.result_storyboard import expected_file_tree, resolve_expected_files  # noqa: E402
from revocompute.runner_host import ServerHostPaths  # noqa: E402
from revocompute.runner_readiness import evaluate_runner_readiness  # noqa: E402
from revocompute.task_types import isolated_discovery  # noqa: E402


def _state(tmp_path: Path, enabled: str) -> ServerHostPaths:
    return ServerHostPaths(
        server=str(tmp_path / 'server'),
        config=str(tmp_path / 'config'),
        root=str(ROOT),
        settings={
            'RUNNER_SOURCE_ROOT': str(ROOT / 'docker' / 'runners'),
            'ENABLED_TASKRUNNERS': enabled,
        },
    )


def test_disabled_source_family_is_unknown_and_not_ready(tmp_path):
    row = evaluate_runner_readiness(_state(tmp_path, 'example'), 'proton_pottsmpnn')
    assert row.status is RunnerReadinessStatus.NOT_CONFIGURED
    assert row.reason_code == 'RUNNER_UNKNOWN'
    assert row.ready is False


def test_enabled_source_tree_without_sif_is_not_built(tmp_path):
    row = evaluate_runner_readiness(_state(tmp_path, 'proton_pottsmpnn'), 'proton_pottsmpnn')
    assert row.status is RunnerReadinessStatus.NOT_BUILT
    assert row.reason_code == 'SIF_MISSING'
    assert row.next_action == 'build-sif'
    assert row.ready is False


def test_source_only_family_has_no_admission_evidence(tmp_path):
    evidence = resolve_submission_readiness(tmp_path / 'server', 'proton_pottsmpnn')
    assert evidence.reason_code == 'RUNNER_UNAVAILABLE'
    assert evidence.accepts('proton_pottsmpnn') is False


def _resolved_contract() -> tuple[object, dict]:
    with isolated_discovery(str(ROOT / 'docker' / 'runners'), {'proton_pottsmpnn'}) as manager:
        task = manager.contributions.resolve('tasks', 'proton_pottsmpnn')
        return task, expected_file_tree(task, str(ROOT))


def test_result_contract_selects_only_the_canonical_sequence_file():
    task, tree = _resolved_contract()
    artifacts = [
        {'path': 'candidates/designs.fa', 'size': 10},
        {'path': 'candidates/designs_states.fa', 'size': 10},
        {'path': 'design_scores.json', 'size': 10},
        {'path': 'task_config.json', 'size': 10},
    ]
    resolved, checks, problems = resolve_expected_files(tree, artifacts)

    assert problems == []
    assert all(check['status'] == 'passed' for check in checks)
    assert [entry['path'] for entry in resolved['candidates']] == ['candidates/designs.fa']
    primary = next(view for view in task.result_workspace if view.role == 'primary')
    assert [selector.value for selectors in primary.sources.values() for selector in selectors] == [
        'candidates/designs.fa'
    ]


def test_parameter_schema_encodes_the_state_pair_contract():
    task, _tree = _resolved_contract()
    validator = Draft202012Validator(task.schema)

    validator.validate({
        'binder_chain': 'B',
        'centres': [{'position': 0, 'state': 'ASP-P'}, {'position': -2, 'state': 'GLU-P'}],
        'states': ['ASP-P', 'ASP-D'],
    })
    for parameters in (
        {'binder_chain': 'B', 'centres': [{'position': 9, 'state': 'ASP-P'}], 'states': ['ASP-D', 'ASP-P']},
        {'binder_chain': 'B', 'centres': [{'position': 9, 'state': 'ASP-P'}], 'states': ['HIS-P', 'ASP-D']},
        {'binder_chain': 'B', 'centres': [{'position': 9, 'state': 'ASP-P'}], 'states': ['ASP-P', 'ASP-D'],
         'block_size': 3},
        {'binder_chain': 'B', 'centres': [{'position': -1000, 'state': 'ASP-P'}],
         'states': ['ASP-P', 'ASP-D']},
    ):
        with pytest.raises(ValidationError):
            validator.validate(parameters)
