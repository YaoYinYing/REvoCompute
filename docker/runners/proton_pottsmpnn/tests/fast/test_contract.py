from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))

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
