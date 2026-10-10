# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Behavioral counterexamples for the Server/Runner dependency checker."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("check_test_boundaries", ROOT / "tools/check_test_boundaries.py")
assert SPEC and SPEC.loader
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)

AUTHENTIC = frozenset({"pssm_gremlin_scenario", "gremlin_lh_runner", "replay_scenario", "production_receipt_pointer"})
GENERIC = frozenset({"controlled_scenario", "controlled_runner", "runner_scenario", "structure_scenario"})


def test_frontend_fixture_package_is_one_source_of_the_authentic_inventory() -> None:
    import frontend_fixtures

    declared = {helper.__name__ for helper in frontend_fixtures.AUTHENTIC_SCENARIOS}
    assert declared == AUTHENTIC
    assert checker.authentic_scenario_symbols(ROOT) == AUTHENTIC
    # The generic helpers stay synthetic, so they never join the fleet-only set.
    assert declared.isdisjoint(GENERIC)


@pytest.mark.parametrize("use", [
    'from frontend_fixtures import pssm_gremlin_scenario\nscenario = pssm_gremlin_scenario()',
    'from frontend_fixtures import pssm_gremlin_scenario as scenario\nscenario()',
    'import frontend_fixtures\nscenario = frontend_fixtures.pssm_gremlin_scenario()',
    'import frontend_fixtures as fixtures\nfixtures.pssm_gremlin_scenario()',
    'from frontend_fixtures import gremlin_lh_runner as runner\nrunner()',
    'import frontend_fixtures\nscenario = getattr(frontend_fixtures, "pssm_gremlin_scenario")()',
])
def test_a_generic_test_cannot_reach_an_authentic_scenario(use: str) -> None:
    assert checker.inspect_authentic_scenario_references(use, "tests/test_frontend_fixture_harness.py", AUTHENTIC)


def test_the_same_use_at_the_fleet_boundary_is_not_flagged(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(checker, "ROOT", tmp_path)
    family = tmp_path / "docker" / "runners" / "some_family"
    family.mkdir(parents=True)
    (family / "plugin.yaml").write_text("id: some_runtime\n", encoding="utf-8")
    fleet = tmp_path / "tests" / "fleet"
    fleet.mkdir(parents=True)
    monkeypatch.setattr(checker, "authentic_scenario_symbols", lambda root: AUTHENTIC)
    use = "from frontend_fixtures import pssm_gremlin_scenario\nscenario = pssm_gremlin_scenario()\n"
    (fleet / "test_named_frontend_scenario.py").write_text(use, encoding="utf-8")
    assert checker.check_repository(tmp_path) == []
    # The identical source under a generic path is a violation, so the exemption
    # is the fleet namespace, not the helper.
    (tmp_path / "tests" / "test_drift.py").write_text(use, encoding="utf-8")
    assert any("tests/test_drift.py" in violation for violation in checker.check_repository(tmp_path))


def test_a_generic_scenario_helper_stays_usable_from_a_generic_test() -> None:
    source = (
        "from frontend_fixtures import controlled_scenario, controlled_runner, mount_scenario, structure_scenario\n"
        "mount_scenario(page, controlled_scenario())\n"
        "mount_scenario(page, structure_scenario())\n"
        "import frontend_fixtures\nfrontend_fixtures.runner_scenario(controlled_runner())\n"
    )
    assert checker.inspect_authentic_scenario_references(
        source, "tests/test_playwright_runner_fixtures.py", AUTHENTIC
    ) == []


def test_the_helper_package_is_excluded_from_the_generic_scan() -> None:
    # The definition site and the fleet boundary are the two sanctioned
    # consumers, and both namespaces are excluded before the reference scan.
    assert checker.FLEET_BOUNDARY in checker.EXCLUDED_TEST_NAMESPACES
    assert "tests/frontend_fixtures/" in checker.EXCLUDED_TEST_NAMESPACES
    assert not "tests/test_frontend_fixture_harness.py".startswith(checker.EXCLUDED_TEST_NAMESPACES)


def test_named_boundary_files_still_cannot_reach_an_authentic_scenario(tmp_path: Path, monkeypatch) -> None:
    # The identity exemption a named boundary file gets does not extend to the
    # authentic-scenario rule: only ``tests/fleet`` may exercise a real scenario.
    monkeypatch.setattr(checker, "ROOT", tmp_path)
    family = tmp_path / "docker" / "runners" / "some_family"
    family.mkdir(parents=True)
    (family / "plugin.yaml").write_text("id: some_runtime\n", encoding="utf-8")
    data_dir = tmp_path / "tests" / "data"
    data_dir.mkdir(parents=True)
    monkeypatch.setattr(checker, "authentic_scenario_symbols", lambda root: AUTHENTIC)
    (data_dir / "test_data.py").write_text(
        "from frontend_fixtures import pssm_gremlin_scenario\nscenario = pssm_gremlin_scenario()\n", encoding="utf-8"
    )
    assert any(
        "tests/data/test_data.py" in violation and "authentic production-Runner scenario" in violation
        for violation in checker.check_repository(tmp_path)
    )


def test_an_empty_authentic_inventory_fails_closed(monkeypatch) -> None:
    # No declaration is no enforcement: the reference scan stays empty, and an
    # unavailable declaration must raise rather than silently drop the gate.
    assert checker.inspect_authentic_scenario_references(
        "from frontend_fixtures import pssm_gremlin_scenario", "tests/test_harness.py", frozenset()
    ) == []

    def _unavailable(name: str, *args: object, **kwargs: object) -> None:
        raise ImportError(f"no module named {name}")

    monkeypatch.setattr(checker.importlib, "import_module", _unavailable)
    with pytest.raises(ValueError, match="unavailable"):
        checker.authentic_scenario_symbols(ROOT)


def test_the_repository_gate_reports_generic_authentic_scenario_use(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(checker, "ROOT", tmp_path)
    family = tmp_path / "docker" / "runners" / "some_family"
    family.mkdir(parents=True)
    (family / "plugin.yaml").write_text("id: some_runtime\n", encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    monkeypatch.setattr(checker, "authentic_scenario_symbols", lambda root: AUTHENTIC)
    (tests_dir / "test_drift.py").write_text(
        "from frontend_fixtures import pssm_gremlin_scenario\nscenario = pssm_gremlin_scenario()\n", encoding="utf-8"
    )
    assert any(
        "authentic production-Runner scenario" in violation and "tests/test_drift.py" in violation
        for violation in checker.check_repository(tmp_path)
    )


@pytest.mark.parametrize("source", [
    'import docker.runners.new_family.adapter',
    'from docker.runner_testkit import runner_protocol',
    'importlib.import_module("docker.runners.new_family.adapter")',
    'family = "new_family"',
    'manifest = root / "docker/runners/new_family/plugin.yaml"',
    'endpoint = "/compute/api/types/new_family"',
])
def test_new_concrete_family_dependencies_are_rejected(source: str) -> None:
    assert checker.inspect_source(source, "tests/server/test_protocol.py", {"new_family"})


def test_comments_and_generic_protocol_vocabulary_are_allowed() -> None:
    source = '''"""new_family explains the motivating regression."""
# new_family is a motivating case only
role = "alignment"
name = manifest.id
root = Path("docker/runners")
'''
    assert checker.inspect_source(source, "tests/server/test_protocol.py", {"new_family"}) == []


def test_manifest_inventory_includes_added_families_and_task_ids(tmp_path: Path) -> None:
    family = tmp_path / "added_family"
    family.mkdir()
    (family / "plugin.yaml").write_text("id: added_runtime\ntasks: [task.yaml]\n", encoding="utf-8")
    (family / "task.yaml").write_text("id: added_task\n", encoding="utf-8")
    assert checker.runner_identities(tmp_path) == {"added_family", "added_runtime", "added_task"}


def test_empty_runner_inventory_cannot_authorize_a_boundary_receipt(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="inventory is empty"):
        checker.runner_identities(tmp_path)


def test_explicit_exception_is_value_and_path_scoped(monkeypatch) -> None:
    monkeypatch.setattr(checker, "VALUE_EXCEPTIONS", {"revocompute/routes.py": {"/legacy/demo_family"}})
    source = 'redirect("/legacy/demo_family")'
    assert checker.inspect_source(source, "revocompute/routes.py", {"demo_family"}) == []
    assert checker.inspect_source(source, "tests/server/test_protocol.py", {"demo_family"})
    assert checker.inspect_source('task_type = "demo_family"', "revocompute/routes.py", {"demo_family"})


@pytest.mark.parametrize("source", [
    'origin = "https://revocompute.example"',
    'origin = "https://example.invalid"',
    'email = "person@example.test"',
])
def test_reserved_documentation_hosts_are_not_runner_identities(source: str) -> None:
    assert checker.inspect_source(source, "tests/server/test_http.py", {"example"}) == []


def test_documentation_host_normalization_does_not_allow_runner_dependencies() -> None:
    assert checker.inspect_source('family = "example"', "tests/server/test_http.py", {"example"})
    assert checker.inspect_source('path = "docker/runners/example/plugin.yaml"', "tests/server/test_http.py", {"example"})


def test_server_test_namespace_cannot_carry_a_runner_testkit(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(checker, "ROOT", tmp_path)
    family = tmp_path / "docker" / "runners" / "some_family"
    family.mkdir(parents=True)
    (family / "plugin.yaml").write_text("id: some_runtime\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "runner_protocol.py").write_text("ROOT = 1\n", encoding="utf-8")
    assert "tests/runner_protocol.py: Runner testkit must live in docker/runner_testkit" in checker.check_repository(tmp_path)
