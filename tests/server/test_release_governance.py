# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""One editable version source, rejected mirror drift, and the release tag gate.

Every case uses a throwaway repository under the test sandbox. No network is
involved, and the OpenAPI mirror assertion proves ``sync`` changes only the
``info.version`` value rather than reformatting the hand-maintained document.
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from revocompute import release_governance as governance
from revocompute.version_info import parse_changelog

UV_LOCK_TEXT = """version = 1
revision = 3
requires-python = ">=3.12"

[[package]]
name = "revocompute"
version = "0.1.0"
source = { editable = "." }
"""

OPENAPI_TEXT = """{
  "openapi": "3.1.0",
  "info": {
    "title": "REvoCompute API",
    "version": "0.1.0",
    "description": "Hand-maintained style: inline objects below stay inline.",
    "x-inline": {"kept": true}
  },
  "paths": {}
}
"""


def _pyproject(version: str) -> str:
    return f"""[build-system]
requires = ["setuptools>=64"]

[project]
name = "revocompute"
version = "{version}"
requires-python = ">=3.12"
"""


def _write_repo(root: Path, version: str = "0.1.0", *, changelog_date: str | None = None) -> Path:
    (root / "frontend").mkdir(parents=True)
    (root / "revocompute" / "static").mkdir(parents=True)
    (root / "pyproject.toml").write_text(_pyproject(version), encoding="utf-8")
    (root / "frontend" / "package.json").write_text(
        json.dumps({"name": "@revocompute/frontend", "version": version}, indent=2) + "\n",
        encoding="utf-8",
    )
    (root / "frontend" / "package-lock.json").write_text(
        json.dumps(
            {
                "name": "@revocompute/frontend",
                "version": version,
                "lockfileVersion": 3,
                "requires": True,
                "packages": {"": {"name": "@revocompute/frontend", "version": version}},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "revocompute" / "static" / "openapi.json").write_text(
        OPENAPI_TEXT.replace('"0.1.0"', f'"{version}"'), encoding="utf-8"
    )
    (root / "uv.lock").write_text(
        UV_LOCK_TEXT.replace('"0.1.0"', f'"{version}"'), encoding="utf-8"
    )
    dated = f" - {changelog_date}" if changelog_date else ""
    (root / "CHANGELOG.md").write_text(
        "# Changelog\n\n"
        "## [Unreleased]\n\n"
        "### Added\n- A pending change.\n\n"
        f"## [{version}]{dated}\n\n"
        "### Added\n- A released change.\n",
        encoding="utf-8",
    )
    return root


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)


def _commit_repo(root: Path) -> str:
    assert _git(root, "init", "-q").returncode == 0
    assert _git(root, "config", "user.email", "test@example.invalid").returncode == 0
    assert _git(root, "config", "user.name", "Release Test").returncode == 0
    assert _git(root, "add", "-A").returncode == 0
    assert _git(root, "commit", "-qm", "baseline").returncode == 0
    return _git(root, "rev-parse", "HEAD").stdout.strip()


def test_check_accepts_a_consistent_repository(tmp_path):
    root = _write_repo(tmp_path)
    assert governance.check(root) == []


@pytest.mark.parametrize(
    ("relative", "mutate", "needle"),
    [
        ("frontend/package.json", lambda data: data.update(version="0.2.0"), "frontend/package.json"),
        (
            "frontend/package-lock.json",
            lambda data: data.update(version="0.2.0"),
            "frontend/package-lock.json",
        ),
        (
            "frontend/package-lock.json",
            lambda data: data["packages"][""].update(version="0.2.0"),
            "packages[''].version",
        ),
    ],
)
def test_check_rejects_each_json_mirror_drift(tmp_path, relative, mutate, needle):
    root = _write_repo(tmp_path)
    path = root / relative
    data = json.loads(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    drifts = governance.check(root)

    assert len(drifts) == 1
    assert needle in drifts[0]


def test_check_rejects_openapi_version_drift(tmp_path):
    root = _write_repo(tmp_path)
    path = root / "revocompute" / "static" / "openapi.json"
    path.write_text(OPENAPI_TEXT.replace('"0.1.0"', '"0.2.0"'), encoding="utf-8")

    assert governance.check(root) == [
        "revocompute/static/openapi.json: info.version '0.2.0' != '0.1.0'"
    ]


def test_check_rejects_uv_lock_drift(tmp_path):
    root = _write_repo(tmp_path)
    path = root / "uv.lock"
    path.write_text(
        UV_LOCK_TEXT.replace('name = "revocompute"\nversion = "0.1.0"', 'name = "revocompute"\nversion = "0.2.0"'),
        encoding="utf-8",
    )

    assert governance.check(root) == ["uv.lock: revocompute version '0.2.0' != '0.1.0'"]


@pytest.mark.parametrize("version", ["0.1", "1", "01.2.3", "1.2.3.4", "v1.2.3", "1.2.3+build"])
def test_check_rejects_invalid_semver(tmp_path, version):
    root = _write_repo(tmp_path, version)
    drifts = governance.check(root)
    assert len(drifts) == 1
    assert "not valid SemVer" in drifts[0]


def test_sync_repairs_every_mirror_without_reformatting_openapi(tmp_path):
    root = _write_repo(tmp_path)
    (root / "pyproject.toml").write_text(_pyproject("1.2.3"), encoding="utf-8")
    before = (root / "revocompute" / "static" / "openapi.json").read_text(encoding="utf-8")

    uv_before = (root / "uv.lock").read_text(encoding="utf-8")
    changed = governance.sync(root)

    assert set(changed) == {
        "frontend/package.json",
        "frontend/package-lock.json",
        "revocompute/static/openapi.json",
        "uv.lock",
    }
    assert governance.check(root) == []
    after = (root / "revocompute" / "static" / "openapi.json").read_text(encoding="utf-8")
    assert after == before.replace('"version": "0.1.0"', '"version": "1.2.3"', 1)
    assert json.loads(after)["info"]["version"] == "1.2.3"
    uv_after = (root / "uv.lock").read_text(encoding="utf-8")
    assert uv_after == uv_before.replace(
        'name = "revocompute"\nversion = "0.1.0"',
        'name = "revocompute"\nversion = "1.2.3"',
        1,
    )
    assert governance.sync(root) == []


def test_tag_gate_accepts_a_product_tag_at_the_tested_commit(tmp_path):
    root = _write_repo(tmp_path, "1.2.3", changelog_date="2026-11-12")
    sha = _commit_repo(root)
    assert _git(root, "tag", "v1.2.3").returncode == 0

    assert governance.verify_tag(root, "v1.2.3", sha) == []


def test_tag_gate_rejects_evidence_tags(tmp_path):
    root = _write_repo(tmp_path, "1.2.3", changelog_date="2026-11-12")
    _commit_repo(root)
    assert _git(root, "tag", "pr-1-evidence").returncode == 0

    errors = governance.verify_tag(root, "pr-1-evidence", None)

    assert errors and "not a product version tag" in errors[0]


def test_tag_gate_rejects_a_wrong_commit(tmp_path):
    root = _write_repo(tmp_path, "1.2.3", changelog_date="2026-11-12")
    sha = _commit_repo(root)
    assert _git(root, "tag", "v1.2.3").returncode == 0

    errors = governance.verify_tag(root, "v1.2.3", "b" * 40)

    assert errors and "not the supplied commit" in errors[0]
    assert sha != "b" * 40


def test_tag_gate_rejects_a_version_mismatch(tmp_path):
    root = _write_repo(tmp_path, "1.2.3", changelog_date="2026-11-12")
    sha = _commit_repo(root)
    assert _git(root, "tag", "v1.2.4").returncode == 0

    errors = governance.verify_tag(root, "v1.2.4", sha)

    assert errors and "Tag version 1.2.4" in errors[0]


def test_tag_gate_requires_a_dated_changelog_section(tmp_path):
    root = _write_repo(tmp_path, "1.2.3")
    sha = _commit_repo(root)
    assert _git(root, "tag", "v1.2.3").returncode == 0

    errors = governance.verify_tag(root, "v1.2.3", sha)

    assert errors and "no dated section" in errors[0]


def test_prepare_release_refuses_a_dirty_tree(tmp_path):
    root = _write_repo(tmp_path, "1.2.3", changelog_date=datetime.now(timezone.utc).date().isoformat())
    sha = _commit_repo(root)
    (root / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")

    with pytest.raises(governance.ReleaseError, match="dirty"):
        governance.prepare_release(root, "1.3.0", sha)


def test_prepare_release_refuses_a_wrong_tested_commit(tmp_path):
    root = _write_repo(tmp_path, "1.2.3", changelog_date=datetime.now(timezone.utc).date().isoformat())
    _commit_repo(root)

    with pytest.raises(governance.ReleaseError, match="not the tested commit"):
        governance.prepare_release(root, "1.3.0", "b" * 40)


def test_prepare_release_refuses_an_existing_tag(tmp_path):
    root = _write_repo(tmp_path, "1.2.3", changelog_date=datetime.now(timezone.utc).date().isoformat())
    sha = _commit_repo(root)
    assert _git(root, "tag", "v1.2.3").returncode == 0

    with pytest.raises(governance.ReleaseError, match="already exists"):
        governance.prepare_release(root, "1.2.3", sha)


def test_prepare_release_updates_sources_without_committing_or_tagging(tmp_path):
    today = datetime.now(timezone.utc).date().isoformat()
    root = _write_repo(tmp_path, "1.2.3", changelog_date=today)
    (root / "CHANGELOG.md").write_text(
        (root / "CHANGELOG.md").read_text(encoding="utf-8")
        + f"\n## [1.3.0] - {today}\n\n### Added\n- The next release.\n",
        encoding="utf-8",
    )
    sha = _commit_repo(root)

    changed = governance.prepare_release(root, "1.3.0", sha)

    assert "pyproject.toml" in changed
    assert governance.check(root) == []
    assert _git(root, "rev-parse", "HEAD").stdout.strip() == sha
    assert _git(root, "tag", "--list").stdout.strip() == ""


def test_changelog_parser_bounds_sections_categories_and_items():
    long_text = "x" * 900
    sections = []
    for index in range(60):
        categories = []
        for category in range(15):
            items = "\n".join(f"  - item {category}-{number} {long_text}" for number in range(210))
            categories.append(f"### Category {category}\n{items}")
        sections.append(f"## [0.{index}.0] - 2026-11-{index % 28 + 1:02d}\n" + "\n".join(categories))
    payload = parse_changelog("\n\n".join(sections))

    assert payload["truncated"] is True
    assert len(payload["sections"]) <= 50
    total = 0
    for section in payload["sections"]:
        assert len(section["categories"]) <= 12
        for category in section["categories"]:
            assert len(category["items"]) <= 200
            for item in category["items"]:
                assert len(item["text"]) <= 500
                assert item["depth"] in {0, 1}
                total += 1
    assert total <= 1000


def test_changelog_parser_recognizes_kinds_and_flattens_markdown():
    payload = parse_changelog(
        "# Changelog\n\n"
        "## [Unreleased]\n\n"
        "### Added\n- See [the guide](https://example.invalid/guide) for `details`.\n\n"
        "## [0.1.0+2890609] - 2026-11-12\n\n"
        "### Changed\n- Baseline.\n\n"
        "## [1.0.0] - 2026-12-01\n\n"
        "### Fixed\n- Released.\n"
    )

    kinds = [section["kind"] for section in payload["sections"]]
    assert kinds == ["unreleased", "development-snapshot", "release"]
    first = payload["sections"][0]["categories"][0]["items"][0]["text"]
    assert first == "See the guide for details."
    assert not re.search(r"\[|\]\(|`", first)


def test_tag_gate_reads_the_tagged_tree_not_the_working_tree(tmp_path):
    root = _write_repo(tmp_path, "1.2.3", changelog_date="2026-11-12")
    sha = _commit_repo(root)
    assert _git(root, "tag", "v1.2.3").returncode == 0
    # A dirty tree after the tag must not change what the tag validates.
    (root / "pyproject.toml").write_text(_pyproject("9.9.9"), encoding="utf-8")
    (root / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")

    assert governance.verify_tag(root, "v1.2.3", sha) == []


def test_tag_gate_can_validate_a_prospective_tag_before_creation(tmp_path):
    root = _write_repo(tmp_path, "1.2.3", changelog_date="2026-11-12")
    sha = _commit_repo(root)

    assert _git(root, "tag", "--list").stdout.strip() == ""
    assert governance.verify_tag(root, "v1.2.3", sha) == []


def test_tag_gate_requires_the_commit_when_the_tag_does_not_exist(tmp_path):
    root = _write_repo(tmp_path, "1.2.3", changelog_date="2026-11-12")
    _commit_repo(root)

    errors = governance.verify_tag(root, "v1.2.3", None)

    assert errors and "does not exist" in errors[0]


def test_build_identity_records_clean_and_dirty_trees_honestly(tmp_path):
    from revocompute_ctl.build import collect_build_identity

    root = _write_repo(tmp_path, "0.1.0")
    sha = _commit_repo(root)

    clean = collect_build_identity(str(root))
    assert clean["REVOCOMPUTE_BUILD_GIT_SHA"] == sha
    assert clean["REVOCOMPUTE_BUILD_ID"].startswith(f"{sha[:7]}-")
    assert clean["REVOCOMPUTE_BASE_VERSION"] == "0.1.0"
    assert clean["REVOCOMPUTE_RELEASE_CHANNEL"] == "development"
    assert clean["REVOCOMPUTE_BUILD_TIME"].endswith("Z")

    (root / "CHANGELOG.md").write_text("# Uncommitted change\n", encoding="utf-8")
    dirty = collect_build_identity(str(root))
    assert dirty["REVOCOMPUTE_BUILD_GIT_SHA"] == ""
    assert dirty["REVOCOMPUTE_BUILD_ID"] == ""
    assert dirty["REVOCOMPUTE_BUILD_TIME"]

    with pytest.raises(RuntimeError, match="release build requires a clean working tree"):
        collect_build_identity(str(root), "release")


def test_build_identity_without_git_records_no_revision(tmp_path, monkeypatch):
    from revocompute_ctl.build import collect_build_identity

    root = _write_repo(tmp_path, "0.1.0")
    _commit_repo(root)
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))

    identity = collect_build_identity(str(root))

    assert identity["REVOCOMPUTE_BUILD_GIT_SHA"] == ""
    assert identity["REVOCOMPUTE_BUILD_ID"] == ""
    with pytest.raises(RuntimeError, match="release build requires a clean working tree"):
        collect_build_identity(str(root), "release")


def test_tag_gate_validates_an_existing_tag_from_a_later_head(tmp_path):
    root = _write_repo(tmp_path, "1.2.3", changelog_date="2026-11-12")
    first = _commit_repo(root)
    assert _git(root, "tag", "v1.2.3").returncode == 0
    (root / "README.md").write_text("later work\n", encoding="utf-8")
    assert _git(root, "add", "-A").returncode == 0
    assert _git(root, "commit", "-qm", "later").returncode == 0

    assert _git(root, "rev-parse", "HEAD").stdout.strip() != first
    assert governance.verify_tag(root, "v1.2.3") == []

    errors = governance.verify_tag(root, "v1.2.3", _git(root, "rev-parse", "HEAD").stdout.strip())
    assert errors and "not the supplied commit" in errors[0]


def test_tag_gate_resolves_an_annotated_tag_object_sha(tmp_path):
    root = _write_repo(tmp_path, "1.2.3", changelog_date="2026-11-12")
    sha = _commit_repo(root)
    assert _git(root, "tag", "-a", "v1.2.3", "-m", "release").returncode == 0
    tag_object = _git(root, "rev-parse", "v1.2.3").stdout.strip()
    assert tag_object != sha

    assert governance.verify_tag(root, "v1.2.3", tag_object) == []


def test_prepare_release_accepts_a_past_dated_section(tmp_path):
    yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
    root = _write_repo(tmp_path, "1.2.3", changelog_date=yesterday)
    (root / "CHANGELOG.md").write_text(
        (root / "CHANGELOG.md").read_text(encoding="utf-8")
        + f"\n## [1.3.0] - {yesterday}\n\n### Added\n- Cut across midnight.\n",
        encoding="utf-8",
    )
    sha = _commit_repo(root)

    changed = governance.prepare_release(root, "1.3.0", sha)

    assert "pyproject.toml" in changed
    assert governance.check(root) == []


def test_changelog_parser_caps_section_version_and_category_name():
    payload = parse_changelog("## [" + "v" * 300 + "]\n### " + "c" * 300 + "\n- item\n")
    section = payload["sections"][0]
    assert len(section["version"]) == 200
    assert len(section["categories"][0]["name"]) == 200
