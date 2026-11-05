# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))

from revocompute import task_types  # noqa: E402
from revocompute.admission import RunnerReadinessStatus, resolve_submission_readiness  # noqa: E402
from revocompute.runner_host import ServerHostPaths  # noqa: E402
from revocompute.runner_readiness import evaluate_runner_readiness  # noqa: E402


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


def test_family_requires_gpu_and_declares_named_roles():
    with task_types.isolated_discovery(str(ROOT / 'docker' / 'runners'), enabled={'rfd4_proteina'}):
        task, _runner = task_types.get('rfd4_proteina')
        assert task.gpus is True
        roles = {role.name: role for role in task.inputs}
        assert set(roles) == {'condition', 'scaffold'}
        assert (roles['condition'].minimum, roles['condition'].maximum) == (1, 1)
        assert (roles['scaffold'].minimum, roles['scaffold'].maximum) == (0, 1)


def test_disabled_source_family_is_unknown_and_not_ready(tmp_path):
    row = evaluate_runner_readiness(_state(tmp_path, 'example'), 'rfd4_proteina')
    assert row.status is RunnerReadinessStatus.NOT_CONFIGURED
    assert row.reason_code == 'RUNNER_UNKNOWN'
    assert row.ready is False


def test_enabled_source_tree_without_sif_is_not_built(tmp_path):
    row = evaluate_runner_readiness(_state(tmp_path, 'rfd4_proteina'), 'rfd4_proteina')
    assert row.status is RunnerReadinessStatus.NOT_BUILT
    assert row.reason_code == 'SIF_MISSING'
    assert row.next_action == 'build-sif'
    assert row.ready is False


def test_source_only_family_has_no_admission_evidence(tmp_path):
    evidence = resolve_submission_readiness(tmp_path / 'server', 'rfd4_proteina')
    assert evidence.reason_code == 'RUNNER_UNAVAILABLE'
    assert evidence.accepts('rfd4_proteina') is False
