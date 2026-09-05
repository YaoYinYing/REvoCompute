# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
RUNNERS = ROOT / "docker/runners"


def test_runners_are_direct_sifs_while_server_remains_compose_deployed():
    assert not list(RUNNERS.glob("*/Dockerfile"))
    manifests = sorted(RUNNERS.glob("*/plugin.yaml"))
    assert manifests
    for path in manifests:
        runtime = yaml.safe_load(path.read_text(encoding="utf-8"))["runtime"]
        assert "docker_image" not in runtime
        assert "dockerfile" not in runtime
        definition = path.parent / runtime["definition"]
        text = definition.read_text(encoding="utf-8")
        assert text.startswith("Bootstrap: ")
        assert not text.startswith("Bootstrap: docker-daemon")
        # A floating upstream tag makes the SIF non-reproducible even when all
        # repository inputs are unchanged.  Direct SIF recipes must pin the
        # upstream OCI base by digest or an immutable version tag.
        first_directive = next(
            line for line in text.splitlines() if line.startswith("From:")
        )
        base = first_directive.split(":", 1)[1].strip()
        assert base and base.lower() not in {"latest", "", "none"}
        assert "%test" in text
        assert text.count("%post") == 1
        assert text.count("%runscript") == 1
        assert (path.parent / "test.yaml").is_file()
        files_section = text.split("%files", 1)[1].split("\n%", 1)[0]
        sources = {line.split()[0] for line in files_section.splitlines() if line.strip()}
        build_inputs = set(runtime["build_inputs"])
        assert all(
            source in build_inputs
            or any(item.startswith(source.rstrip("/") + "/") for item in build_inputs)
            or any(source.startswith(item.rstrip("/") + "/") for item in build_inputs)
            for source in sources
        )

        test_doc = yaml.safe_load((path.parent / "test.yaml").read_text(encoding="utf-8"))
        assert test_doc["version"] == 1
        smoke_cases = test_doc["collections"]["smoke"]["cases"]
        assert smoke_cases
        task_ids = {
            str(yaml.safe_load((path.parent / task).read_text(encoding="utf-8"))["id"])
            for task in yaml.safe_load(path.read_text(encoding="utf-8"))["tasks"]
        }
        assert task_ids <= {str(case["task"]) for case in smoke_cases}
        for case in smoke_cases:
            for fixture in case["input"]["files"]:
                assert (ROOT / fixture).is_file(), fixture

    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    assert {"redis", "web", "worker", "gateway", "maintenance"} <= set(compose["services"])
    assert compose["services"]["web"]["build"]["dockerfile"] == "docker/server/Dockerfile"


def test_ci_cannot_issue_target_cluster_receipts():
    workflow = (ROOT / ".github/workflows/tests.yml").read_text(encoding="utf-8")
    assert "DockerRunnerCompatibility" not in workflow
    assert "live-test --" not in workflow
    assert "receipts/" not in workflow
