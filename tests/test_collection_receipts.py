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

The targets are not re-declared here: the receipt asks ``make`` to expand the
shipped lane variables (``SERVER_TESTS``, ``RUNNER_FAST_TESTS``, ``RUNNER_PYTEST``)
from the repository ``Makefile`` and runs exactly the argv they denote. Executing
the real build tool is what keeps the receipt honest — a Makefile-level change
that broadens the Server scope or drops the fast lane's gating changes the argv
this receipt collects, so the boundary is proven against the shipped policy
rather than a private copy of it.
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# The shipped lane definitions live in the Makefile; these are only the variable
# names whose expansion the receipt consumes.
SERVER_TESTS_VAR = "SERVER_TESTS"
RUNNER_FAST_TESTS_VAR = "RUNNER_FAST_TESTS"
RUNNER_PYTEST_VAR = "RUNNER_PYTEST"

# Runner-owned trees the generic Server lane must never reach: production family
# implementations, and the test namespace family tests move into when they leave
# the generic tree.
RUNNER_OWNED_DIRS = ("docker/runners", "tests/runners")

# The neutral testkit path. The fast lane's shipped targets already name it; this
# literal is only for staging the miniature fixture below.
TESTKIT_FAST = "docker/runner_testkit/tests/fast"

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


# ── resolving the shipped lanes ───────────────────────────────────────────────


def _make_expand(root: Path, variable: str) -> list[str]:
    """Ask ``make`` to expand one shipped lane variable into its argv tokens.

    Reading the Makefile textually would test a copy of the policy; running the
    real build tool against it executes the policy itself. ``make`` absent is a
    hard failure — the receipt cannot prove the boundary without the definition
    it is proving.
    """
    make = shutil.which("make")
    assert make is not None, "make is required to resolve the shipped test lanes but was not found on PATH"
    recipe = f'__receipt: ; @printf "%s\\n" "$({variable})"'
    result = subprocess.run(
        [make, "-s", "--no-print-directory", "-C", str(root), "--eval", recipe, "__receipt"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"make failed to expand the shipped {variable} (exit {result.returncode}):\n{result.stdout}\n{result.stderr}"
    )
    tokens = shlex.split(result.stdout)
    assert tokens, f"the shipped {variable} expanded to an empty lane"
    return tokens


def _runner_pytest_args(root: Path) -> list[str]:
    """The pytest options the shipped fast lane puts on its command line.

    ``RUNNER_PYTEST`` is a full program (``python -m pytest -p <plugin> ...``);
    the receipt supplies its own interpreter and probe plugin, so it takes only
    the options the lane puts after ``pytest`` — this is what carries the lane's
    testkit gating and import mode. Everything up to and including ``pytest`` is
    the interpreter/pytest invocation the receipt replaces.
    """
    program = _make_expand(root, RUNNER_PYTEST_VAR)
    pytest_at = next((index for index, token in enumerate(program) if token == "pytest"), None)
    assert pytest_at is not None, f"the shipped fast lane is not a pytest invocation: {program}"
    options = program[pytest_at + 1:]
    for index, token in enumerate(options):
        if token.startswith("-"):
            args = options[index:]
            break
    else:
        args = []
    assert any("runner_testkit" in token for token in args), (
        f"the shipped fast lane lost its neutral testkit gating: {program}"
    )
    return args


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


def _collect(root: Path, targets: list[str], *, runner_args: list[str] | None = None) -> list[dict]:
    """Run one bounded ``--collect-only`` and return the collected item records."""
    with tempfile.TemporaryDirectory(prefix="collection-receipt-") as directory:
        workspace = Path(directory)
        (workspace / "collection_receipt_probe.py").write_text(_PROBE_SOURCE, encoding="utf-8")
        items_path = workspace / "collected-items.json"
        program = [sys.executable, "-m", "pytest", *targets, "--collect-only", "-q", "-p", "no:cacheprovider"]
        search_path = [str(workspace)]
        if runner_args:
            program += runner_args
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
    """Items whose node id or imported module reaches into a Runner-owned tree."""
    return [
        record
        for record in records
        if any(
            _is_under(record["nodeid"].split("::", 1)[0], directory, root)
            or _is_under(record["module"], directory, root)
            for directory in RUNNER_OWNED_DIRS
        )
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
    """Generic Server collection, as the Makefile ships it, carries neither a Runner path nor science."""
    targets = _make_expand(ROOT, SERVER_TESTS_VAR)
    records = _collect(ROOT, targets)

    assert len(records) > _MIN_SERVER_ITEMS, f"Server lane collected only {len(records)} items"
    leaked = _runner_offenders(records)
    assert not leaked, f"Server lane reached Runner-owned tests: {leaked[:3]}"
    assert not _scientific_offenders(records), (
        f"Server lane carried scientific acceptance: {_scientific_offenders(records)[:3]}"
    )


def test_fast_lane_collection_stays_within_fast_contracts() -> None:
    """The fast contract lane the Makefile ships is fast-only, and still reaches every family."""
    targets = _make_expand(ROOT, RUNNER_FAST_TESTS_VAR)
    records = _collect(ROOT, targets, runner_args=_runner_pytest_args(ROOT))

    assert len(records) > _MIN_FAST_ITEMS, f"fast lane collected only {len(records)} items"
    files = _collected_files(records)
    non_fast = [item for item in files if not _within_tests_subdirectory(item, "fast")]
    assert not non_fast, f"fast lane collected a non-fast path: {non_fast[:3]}"
    assert not any(_within_tests_subdirectory(item, "scientific") for item in files)
    assert not _scientific_offenders(records)
    # The lane must still reach the neutral testkit and at least one family.
    assert any(_is_under(item, "docker/runner_testkit") for item in targets), "fast lane lost the neutral testkit"
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
        staged_toolkit,
        [TESTKIT_FAST, *(sorted(p.relative_to(staged_toolkit).as_posix()
                                 for p in staged_toolkit.glob("docker/runners/*/tests/fast")))],
        runner_args=["-p", "docker.runner_testkit.pytest_plugin", "--import-mode=importlib"],
    )
    fast_files = _collected_files(fast_records)
    assert fast_records, "staged fast lane collected nothing"
    assert all(_within_tests_subdirectory(item, "fast") for item in fast_files)
    assert not _scientific_offenders(fast_records, staged_toolkit)

    # The staged scientific module is real and collectible, so its absence from
    # the fast lane above is a real exclusion, not an empty-tree artifact.
    scientific_records = _collect(staged_toolkit, ["docker/runners/staged_family/tests/scientific"])
    assert scientific_records, "the staged scientific module was not collectible"


def test_lane_receipt_flags_a_lane_that_collects_runner_modules(staged_toolkit: Path, tmp_path: Path) -> None:
    """The receipt must fail, not pass, when a lane is wired to a Runner-owned tree."""
    offenders = _runner_offenders(_collect(staged_toolkit, ["docker/runners"]), staged_toolkit)
    assert offenders, "a lane collecting production Runner modules must be reported"
    assert all(_is_under(record["nodeid"].split("::", 1)[0], "docker/runners", staged_toolkit) for record in offenders)

    # A family test moved into the runner-owned test namespace is the same leak.
    (tmp_path / "tests/runners/staged_family").mkdir(parents=True)
    (tmp_path / "tests/runners/staged_family/test_x.py").write_text(
        "def test_x():\n    assert True\n", encoding="utf-8"
    )
    moved = _runner_offenders(_collect(tmp_path, ["tests"]), tmp_path)
    assert moved, "a lane collecting tests/runners modules must be reported"
