# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Runner deployment snapshots preserve runtime assets and exclude owned test trees."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from revocompute.runner_registry import load_plugin_families
from revocompute_ctl.env import EnvState
from revocompute_ctl.steps import materialize_runner_families


@pytest.fixture
def runner_source(tmp_path):
    source = tmp_path / "source"
    files = {
        "common/runtime/task.py": "shared runtime",
        "common/runtime/tests/runtime.dat": "nested shared runtime bytes",
        "common/fixtures/runtime.dat": "shared fixture runtime bytes",
        "common/references/runtime.dat": "shared reference runtime bytes",
        "common/tests/fast/test_runtime.py": "raise RuntimeError('never deploy')",
        "common/tests/scientific/test_runtime.py": "raise RuntimeError('never deploy')",
        "demo/demo.def": "Bootstrap: docker\nFrom: scratch\n",
        "demo/run.sh": "#!/bin/sh\n",
        "demo/tasks/example/task.yaml": "id: example\n",
        "demo/references/runtime.json": "reference runtime bytes",
        "demo/fixtures/build.dat": "fixture build bytes",
        "demo/goldens/build.dat": "golden build bytes",
        "demo/assets/tests/runtime.dat": "nested tests runtime bytes",
        "demo/fake_modules/runtime.py": "legitimate runtime module",
        "demo/reference_generation/runtime.py": "legitimate runtime utility",
        "demo/workspace/frontend.js": "export default {};",
        "demo/workspace/theme.css": "body {}",
        "demo/workspace/schema.json": "{}",
        "demo/workspace/backend.py": "def prepare(): pass",
        "demo/policies/access.yaml": "policies: {}\n",
        "demo/tests/fast/test_wrapper.py": "raise RuntimeError('never deploy')",
        "demo/tests/scientific/test_acceptance.py": "raise RuntimeError('never deploy')",
        "demo/tests/references/expected.json": "scientific golden",
        "demo/tests/fake_modules/upstream.py": "fake upstream",
        "demo/tests/reference_generation/regenerate.py": "regenerator",
    }
    for relative, contents in files.items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
    manifest = {
        "id": "demo",
        "version": "1",
        "tasks": ["tasks/example/task.yaml"],
        "access_policies": ["policies/access.yaml"],
        "contributions": {
            "input_workspace_plugins": [{
                "id": "workspace",
                "module": "workspace/frontend.js",
                "styles": ["workspace/theme.css"],
                "configuration_schema": "workspace/schema.json",
                "backend": {"prepare": "workspace/backend.py:prepare"},
            }],
        },
        "runtime": {
            "definition": "demo.def",
            "image_artifact": "demo.sif",
            "entrypoint": ["/bin/sh", "/opt/revocompute/runtime/demo/run.sh"],
            "build_inputs": ["demo/fixtures/build.dat", "demo/goldens/build.dat"],
            "runtime_overlay": ["common/runtime", "demo/run.sh", "demo/references", "demo/assets"],
        },
    }
    (source / "demo" / "plugin.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    state = EnvState(
        str(tmp_path / "server.env"),
        values={
            "SERVER_DIR": str(tmp_path / "server"),
            "RUNNER_SOURCE_ROOT": str(source),
            "ENABLED_TASKRUNNERS": "demo",
        },
    )
    return source, state, manifest


def test_snapshot_excludes_only_family_root_test_namespace(runner_source):
    source, state, _manifest = runner_source
    target = Path(state.server_dir()) / "docker" / "runners"
    stale = target / "demo" / "tests" / "stale.py"
    stale.parent.mkdir(parents=True)
    stale.write_text("old leaked test", encoding="utf-8")

    materialize_runner_families(state)

    expected = {
        path.relative_to(source): path.read_bytes()
        for path in source.rglob("*")
        if path.is_file()
        and not any(path.is_relative_to(source / family / "tests") for family in ("demo", "common"))
    }
    actual = {path.relative_to(target): path.read_bytes() for path in target.rglob("*") if path.is_file()}
    assert actual == expected
    assert not (target / "demo" / "tests").exists()
    assert not (target / "common" / "tests").exists()
    assert load_plugin_families(target)[0].name == "demo"


@pytest.mark.parametrize(
    ("field", "declaration"),
    [
        ("build_inputs", ["demo/tests/fake_modules/upstream.py"]),
        ("runtime_overlay", ["demo/tests/references"]),
        ("runtime_overlay", ["demo"]),
        ("runtime_overlay", ["common/tests/fast"]),
        ("runtime_overlay", ["common"]),
        ("build_inputs", ["common/tests/fast/test_runtime.py"]),
        ("definition", "tests/reference_generation/regenerate.py"),
        ("tasks", ["tests/references/expected.json"]),
        ("access_policies", ["tests/references/expected.json"]),
        ("workspace_module", "tests/fake_modules/upstream.py"),
        ("workspace_styles", ["tests/references/expected.json"]),
        ("workspace_configuration_schema", "tests/references/expected.json"),
        ("workspace_backend", {"prepare": "tests/fake_modules/upstream.py:prepare"}),
    ],
)
def test_test_namespace_cannot_be_declared_as_deployment_input(runner_source, field, declaration):
    source, state, manifest = runner_source
    if field.startswith("workspace_"):
        manifest["contributions"]["input_workspace_plugins"][0][field.removeprefix("workspace_")] = declaration
    elif field in {"tasks", "access_policies"}:
        manifest[field] = declaration
    else:
        manifest["runtime"][field] = declaration
    (source / "demo" / "plugin.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    target = Path(state.server_dir()) / "docker" / "runners"
    target.mkdir(parents=True)
    current = target / "current.txt"
    current.write_bytes(b"previous deployment")

    with pytest.raises(ValueError, match="test-only namespace"):
        materialize_runner_families(state)

    assert current.read_bytes() == b"previous deployment"


@pytest.mark.parametrize(
    ("alias", "destination"),
    [
        ("demo/assets/alias", "demo/tests"),
        ("demo/assets/alias.py", "common/tests/fast/test_runtime.py"),
        ("common/alias", "demo/tests"),
        ("demo/alias", "common"),
    ],
)
def test_symlink_alias_cannot_copy_excluded_tests(runner_source, alias, destination):
    source, state, _manifest = runner_source
    (source / alias).symlink_to(source / destination)
    target = Path(state.server_dir()) / "docker" / "runners"
    target.mkdir(parents=True)
    current = target / "current.txt"
    current.write_bytes(b"previous deployment")

    with pytest.raises(ValueError, match="test-only namespace"):
        materialize_runner_families(state)

    assert current.read_bytes() == b"previous deployment"
