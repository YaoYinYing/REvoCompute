# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Executable collection receipts for the Server/Runner test-ownership split.

The split is only real if pytest collects the two lanes the way the policy
claims. Each receipt runs a bounded ``--collect-only`` over a lane's physical
targets and inspects the collected item set, so a regression that lets a
production Runner module into generic Server collection (or a scientific
acceptance module into the fast Runner contract lane) fails closed instead of
hiding behind an ``--ignore``/marker declaration.

Targets are the lane invocations themselves, not Makefile text: the Server lane
is the generic ``tests`` tree minus its one alternate boundary, and the fast
lane is the neutral testkit plus every ``docker/runners/*/tests/fast`` found by
``glob``.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# The generic Server lane, verbatim: the whole ``tests`` tree except the fleet
# boundary that owns its own collection. Fleet is the only other lane under
# ``tests``, so this scope is complete for proving no production Runner module is
# reachable from generic Server collection, and it stays bounded to a few seconds.
SERVER_TARGETS = ["tests", "--ignore=tests/fleet"]

# Gate the fast lane through the same plugin/import mode ``make runner-fast`` uses.
FAST_PLUGIN = "docker.runner_testkit.pytest_plugin"
TESTKIT_FAST = "docker/runner_testkit/tests/fast"


def _family_fast(root: Path) -> list[str]:
    """Every family's fast-contract directory, as the fast lane's Makefile globs."""
    return sorted(path.relative_to(root).as_posix() for path in root.glob("docker/runners/*/tests/fast"))


# Resolved at import: the autouse Server fence guards ``os.scandir`` while a test
# runs, and a directory glob on the production Runner root trips it.
FAMILY_FAST = _family_fast(ROOT)

# pytest exits 0 only for a clean collection; 5 (nothing collected) and any
# collection error are not receipts.
_PYTEST_OK = 0
# Fail-closed floors: a lane that collapses to a handful of items is a broken
# receipt, not a passing one.
_MIN_SERVER_ITEMS = 200
_MIN_FAST_ITEMS = 50

# The probe records what pytest really collected: each item's node id, the module
# it was imported from, and whether it carries the Runner scientific marker. It
# reads its output path from the environment so it loads into any lane without
# touching the lane's own conftest.
_PROBE_SOURCE = '''# pytest plugin: emit the real collected item set as a JSON receipt.
from __future__ import annotations

import json
import os
from pathlib import Path


def pytest_collection_modifyitems(config, items):
    records = []
    for item in items:
        module = getattr(item, "module", None)
        module_file = getattr(module, "__file__", None) or str(getattr(item, "path", "") or "")
        records.append({
            "nodeid": item.nodeid,
            "module": str(module_file),
            "scientific_acceptance": item.get_closest_marker("scientific_acceptance") is not None,
        })
    Path(os.environ["COLLECTION_RECEIPT_ITEMS"]).write_text(json.dumps(records), encoding="utf-8")
'''


# ── bounded collection probe ──────────────────────────────────────────────────


def _probe_environment(search_path: list[str], items_path: Path) -> dict[str, str]:
    """A nested-run environment that cannot inherit the outer xdist schedule."""
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("PYTEST_XDIST") and key != "PYTEST_CURRENT_TEST"
    }
    parts = [*search_path]
    if environment.get("PYTHONPATH"):
        parts.append(environment["PYTHONPATH"])
    environment["PYTHONPATH"] = os.pathsep.join(parts)
    environment["COLLECTION_RECEIPT_ITEMS"] = str(items_path)
    return environment


def _collect(root: Path, targets: list[str], *, runner_lane: bool = False) -> list[dict]:
    """Run one bounded ``--collect-only`` and return the collected item records."""
    with tempfile.TemporaryDirectory(prefix="collection-receipt-") as directory:
        workspace = Path(directory)
        (workspace / "collection_receipt_probe.py").write_text(_PROBE_SOURCE, encoding="utf-8")
        items_path = workspace / "collected-items.json"
        program = [sys.executable, "-m", "pytest", *targets, "--collect-only", "-q", "-p", "no:cacheprovider"]
        search_path = [str(workspace)]
        if runner_lane:
            program += ["-p", FAST_PLUGIN, "--import-mode=importlib"]
            search_path.insert(0, str(root))
        program += ["-p", "collection_receipt_probe"]
        result = subprocess.run(
            program, cwd=root, env=_probe_environment(search_path, items_path), capture_output=True, text=True
        )
        assert result.returncode == _PYTEST_OK, (
            f"collection receipt is not a clean run (exit {result.returncode}):\n{result.stdout}\n{result.stderr}"
        )
        assert items_path.is_file(), "the collection probe observed no collection"
        return json.loads(items_path.read_text(encoding="utf-8"))


# ── receipt predicates ────────────────────────────────────────────────────────


def _is_under(path: str, directory: str, root: Path = ROOT) -> bool:
    if not path:
        return False
    # Anchor both sides so a staged tree under a symlinked temp root still matches.
    candidate = Path(os.path.realpath(Path(path) if os.path.isabs(path) else root / path))
    boundary = Path(os.path.realpath(root / directory))
    return candidate == boundary or boundary in candidate.parents


def _within_tests_subdirectory(path: str, name: str) -> bool:
    """True for any path holding a ``tests/<name>`` pair (relative or absolute)."""
    parts = Path(os.path.normpath(path)).parts if path else ()
    return any(first == "tests" and second == name for first, second in zip(parts, parts[1:]))


def _collected_files(records: list[dict]) -> set[str]:
    return {record["nodeid"].split("::", 1)[0] for record in records}


def _runner_offenders(records: list[dict], root: Path = ROOT) -> list[dict]:
    """Items whose node id or imported module reaches into production Runner dirs."""
    return [
        record
        for record in records
        if _is_under(record["nodeid"].split("::", 1)[0], "docker/runners", root)
        or _is_under(record["module"], "docker/runners", root)
    ]


def _scientific_offenders(records: list[dict], root: Path = ROOT) -> list[dict]:
    """Items that are scientific acceptance by marker or by owning directory."""
    return [
        record
        for record in records
        if record["scientific_acceptance"]
        or _within_tests_subdirectory(record["module"], "scientific")
        or _within_tests_subdirectory(record["nodeid"].split("::", 1)[0], "scientific")
    ]


# ── the two lanes the project ships ───────────────────────────────────────────


def test_server_lane_collection_never_reaches_a_production_runner_module() -> None:
    """Generic Server collection must carry neither a Runner path nor science."""
    records = _collect(ROOT, SERVER_TARGETS)

    assert len(records) > _MIN_SERVER_ITEMS, f"Server lane collected only {len(records)} items"
    leaked = _runner_offenders(records)
    assert not leaked, f"Server lane reached production Runner tests: {leaked[:3]}"
    assert not _scientific_offenders(records), (
        f"Server lane carried scientific acceptance: {_scientific_offenders(records)[:3]}"
    )


def test_fast_lane_collection_stays_within_fast_contracts() -> None:
    """The fast contract lane is fast-only, and still reaches every family."""
    records = _collect(ROOT, [TESTKIT_FAST, *FAMILY_FAST], runner_lane=True)

    assert len(records) > _MIN_FAST_ITEMS, f"fast lane collected only {len(records)} items"
    files = _collected_files(records)
    non_fast = [item for item in files if not _within_tests_subdirectory(item, "fast")]
    assert not non_fast, f"fast lane collected a non-fast path: {non_fast[:3]}"
    assert not any(_within_tests_subdirectory(item, "scientific") for item in files)
    assert not _scientific_offenders(records)
    # The lane must still reach the neutral testkit and at least one family.
    assert any(_is_under(item, TESTKIT_FAST) for item in files), "fast lane lost the neutral testkit"
    assert any(_is_under(item, "docker/runners") for item in files), "fast lane collected no family contract"


# ── staged trees: the receipts must have teeth on a small, real fixture ───────


def _stage_toolkit(root: Path) -> None:
    """A miniature reproduction of the two lanes, with a Runner test to catch."""
    (root / "docker/runner_testkit/tests/fast").mkdir(parents=True)
    (root / "docker/runners/staged_family/tests/fast").mkdir(parents=True)
    (root / "docker/runners/staged_family/tests/scientific").mkdir(parents=True)
    (root / "tests").mkdir(parents=True)
    (root / "docker/runner_testkit/pytest_plugin.py").write_text(
        "from __future__ import annotations\n"
        "import sys\n"
        "from pathlib import Path\n\n"
        "ROOT = Path(__file__).resolve().parents[2]\n\n"
        "def pytest_configure(config):\n"
        "    paths = (ROOT, Path(__file__).resolve().parent,\n"
        "             *sorted((ROOT / 'docker/runners').glob('*/tests/fast')))\n"
        "    for path in paths:\n"
        "        if str(path) not in sys.path:\n"
        "            sys.path.insert(0, str(path))\n",
        encoding="utf-8",
    )
    (root / "tests/test_generic_server_contract.py").write_text(
        "def test_generic_server_contract():\n    assert True\n", encoding="utf-8"
    )
    (root / "docker/runner_testkit/tests/fast/test_testkit_contract.py").write_text(
        "def test_testkit_contract():\n    assert True\n", encoding="utf-8"
    )
    (root / "docker/runners/staged_family/tests/fast/test_staged_family_fast.py").write_text(
        "def test_staged_family_fast():\n    assert True\n", encoding="utf-8"
    )
    (root / "docker/runners/staged_family/tests/scientific/test_staged_family_scientific.py").write_text(
        "from __future__ import annotations\n\n"
        "import pytest\n\n"
        "pytestmark = pytest.mark.scientific_acceptance\n\n"
        "def test_staged_family_scientific():\n    assert True\n",
        encoding="utf-8",
    )


@pytest.fixture(scope="module")
def staged_toolkit(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("collection-receipt-toolkit")
    _stage_toolkit(root)
    return root


def test_staged_lane_receipts_hold_on_a_miniature_tree(staged_toolkit: Path) -> None:
    """A real collection over a miniature tree reproduces both lanes' verdicts."""
    server_records = _collect(staged_toolkit, ["tests"])
    assert server_records, "staged Server lane collected nothing"
    assert not _runner_offenders(server_records, staged_toolkit)

    fast_records = _collect(
        staged_toolkit, [TESTKIT_FAST, *_family_fast(staged_toolkit)], runner_lane=True
    )
    fast_files = _collected_files(fast_records)
    assert fast_records, "staged fast lane collected nothing"
    assert all(_within_tests_subdirectory(item, "fast") for item in fast_files)
    assert not _scientific_offenders(fast_records, staged_toolkit)

    # The staged scientific module is real and collectible, so its absence from
    # the fast lane above is a real exclusion, not an empty-tree artifact.
    scientific_records = _collect(staged_toolkit, ["docker/runners/staged_family/tests/scientific"])
    assert scientific_records, "the staged scientific module was not collectible"


def test_lane_receipt_flags_a_lane_that_collects_runner_modules(staged_toolkit: Path) -> None:
    """The receipt must fail, not pass, when a lane is wired to the Runner tree."""
    offenders = _runner_offenders(_collect(staged_toolkit, ["docker/runners"]), staged_toolkit)
    assert offenders, "a lane collecting Runner modules must be reported"
    assert all(_is_under(record["nodeid"].split("::", 1)[0], "docker/runners", staged_toolkit) for record in offenders)
