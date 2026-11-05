from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))

from revocompute import task_types  # noqa: E402


def test_family_requires_gpu_and_declares_named_roles():
    task_types.discover_plugins(str(ROOT / 'docker' / 'runners'), enabled={'rfd4_proteina'})
    task, _runner = task_types.get('rfd4_proteina')
    assert task.gpus is True
    roles = {role.name: role for role in task.inputs}
    assert set(roles) == {'condition', 'scaffold'}
    assert (roles['condition'].minimum, roles['condition'].maximum) == (1, 1)
    assert (roles['scaffold'].minimum, roles['scaffold'].maximum) == (0, 1)
