# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""One build identity across the building host and a containerized server.

Build freshness is the deployment's change-impact contract: a SIF is current when
the definition, its declared build inputs, and *the Apptainer builder* all match
what the build recorded.  Only the host that actually builds can observe the
builder, and a containerized server ships no Apptainer -- so if that process
answers the freshness question on its own it contributes an empty builder, which
is not "unknown, therefore current" but a *different* builder.  The result is
every already-built SIF reading BUILD_STALE in the Admin API while the same SIF
is VALIDATION_STALE or READY on the CLI, and an operator sent to rebuild images
that are current.

These cases drive the real provenance, evidence, and staleness code with two
process views (a host that can observe Apptainer and a server that cannot) to
prove the controller's shared observation restores one identity.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from revocompute import runner_registry as registry
from revocompute.artifact_evidence import write_artifact_evidence
from revocompute.live_tests import sha256_file
from revocompute.runner_registry import RuntimeFamily
from revocompute_ctl import steps as steps_mod
from revocompute_ctl.env import EnvState


class _Process:
    """One process's environment view, as ``HostPaths`` exposes it to the registry.

    ``path`` is the PATH this process resolves executables with, and ``declared``
    is a shared builder observation this process's environment already carries
    (the container's ``REVODESIGN_APPTAINER_VERSION``); ``None`` means it falls
    back to the ambient environment, exactly as ``ServerHostPaths`` does.
    """

    def __init__(self, root: Path, *, path: str, declared: str | None = None) -> None:
        self._root = root
        self._path = path
        self._declared = declared

    def get(self, key: str, default: str = "") -> str:
        if key == "REVODESIGN_APPTAINER_VERSION":
            return os.environ.get(key, default) if self._declared is None else self._declared
        return default

    def server_dir(self) -> str:
        return str(self._root / "server")

    def config_dir(self) -> str:
        return str(self._root / "config")

    def server_root(self) -> str:
        return str(self._root)

    def exported(self) -> dict[str, str]:
        return {"PATH": self._path}

    def use_slurm(self) -> bool:
        return True


@pytest.fixture(autouse=True)
def _restore_shared_builder():
    """``record_apptainer_builder_version`` writes ``os.environ`` itself, so undo it."""
    before = os.environ.pop("REVODESIGN_APPTAINER_VERSION", None)
    yield
    if before is None:
        os.environ.pop("REVODESIGN_APPTAINER_VERSION", None)
    else:
        os.environ["REVODESIGN_APPTAINER_VERSION"] = before


def _builder_binary(root: Path, version: str) -> Path:
    """A directory holding an ``apptainer`` that reports ``version``."""
    bin_dir = root / "builder-bin"
    bin_dir.mkdir(exist_ok=True)
    binary = bin_dir / "apptainer"
    binary.write_text(f"#!/bin/sh\nprintf '%s\\n' {version!r}\n", encoding="utf-8")
    binary.chmod(0o755)
    return bin_dir


def _no_tools(root: Path) -> Path:
    """A PATH that holds no Apptainer, as a server container's PATH does."""
    path = root / "no-tools"
    path.mkdir(exist_ok=True)
    return path


def _family(root: Path) -> RuntimeFamily:
    family_root = root / "runners" / "demo"
    family_root.mkdir(parents=True)
    (family_root / "demo.def").write_text("Bootstrap: docker\nFrom: python:3.12-slim\n", encoding="utf-8")
    (family_root / "run.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    return RuntimeFamily(
        name="demo",
        version="1",
        definition="demo.def",
        image_artifact="demo.sif",
        slurm_image=str(root / "sifs" / "demo.sif"),
        build_inputs=("demo/run.sh",),
        root=family_root,
    )


def _record_a_build(state, family: RuntimeFamily) -> str:
    """Leave the build evidence a controller build would, and return its digest."""
    active = Path(family.slurm_image)
    active.parent.mkdir(parents=True, exist_ok=True)
    active.write_bytes(b"sif")
    provenance = registry._build_provenance(state, family)
    write_artifact_evidence(family, sha256_file(active), "build", provenance)
    return str(provenance["build_provenance_digest"])


def test_a_builder_blind_server_reads_a_current_sif_as_stale(tmp_path):
    """The defect: the same current SIF is BUILD_STALE from the server's view.

    The build recorded the builder the host observed; the server container cannot
    observe it and contributes the empty string, so its derived identity cannot
    match the recorded one and the SIF reads stale.
    """
    family = _family(tmp_path)
    controller = _Process(tmp_path, path=str(_builder_binary(tmp_path, "apptainer version 1.5.4")))
    recorded = _record_a_build(controller, family)

    server = _Process(tmp_path, path=str(_no_tools(tmp_path)))

    assert registry._build_provenance(server, family)["build_provenance_digest"] != recorded
    assert registry.sif_stale(server, family) is True


def test_sharing_the_observed_builder_restores_one_identity(tmp_path):
    """The fix: the controller's observation makes both processes agree.

    The builder is observed once on the building host and shared through the
    deployment environment, so a server process that cannot run Apptainer derives
    the recorded identity instead of its own empty-builder one.
    """
    family = _family(tmp_path)
    controller = _Process(tmp_path, path=str(_builder_binary(tmp_path, "apptainer version 1.5.4")))
    recorded = _record_a_build(controller, family)

    assert registry.record_apptainer_builder_version(controller) == "apptainer version 1.5.4"

    server = _Process(tmp_path, path=str(_no_tools(tmp_path)))
    assert registry._build_provenance(server, family)["build_provenance_digest"] == recorded
    assert registry.sif_stale(server, family) is False


def test_the_shared_observation_wins_and_an_unobservable_host_is_honest(tmp_path):
    """Precedence: a shared observation > this process's own Apptainer > empty.

    An empty answer is deliberately *not* treated as "current": a host with no
    Apptainer and no shared observation leaves freshness unprovable rather than
    guessing a builder, which is what keeps a non-HPC inspection from claiming
    an image is current.
    """
    local = _Process(tmp_path, path=str(_builder_binary(tmp_path, "apptainer version 1.4.0")))
    declared = _Process(tmp_path, path=str(_no_tools(tmp_path)), declared="apptainer version 1.5.4")
    blind = _Process(tmp_path, path=str(_no_tools(tmp_path)))

    assert registry._apptainer_version(declared) == "apptainer version 1.5.4"
    assert registry._apptainer_version(local) == "apptainer version 1.4.0"
    assert registry._apptainer_version(blind) == ""
    # Nothing is recorded from a host that cannot observe the builder: the shared
    # value must be a real observation, never a placeholder.
    assert registry.record_apptainer_builder_version(blind) == ""
    assert "REVODESIGN_APPTAINER_VERSION" not in os.environ

    assert registry.record_apptainer_builder_version(local) == "apptainer version 1.4.0"
    assert os.environ["REVODESIGN_APPTAINER_VERSION"] == "apptainer version 1.4.0"


def test_the_provenance_records_whether_the_builder_was_declared_or_observed(tmp_path):
    """A declared builder must never be recorded as this process's observation.

    The identity freshness is compared against is the declared value either way --
    that is what keeps the CLI and the container agreeing -- but the provenance
    must not claim to have observed a builder it did not run, or a mistyped pin
    reads back as a fact and a build on the wrong host is indistinguishable from
    the intended one.
    """
    family = _family(tmp_path)
    (Path(family.slurm_image).parent).mkdir(parents=True, exist_ok=True)
    Path(family.slurm_image).write_bytes(b"sif")

    observed = _Process(tmp_path, path=str(_builder_binary(tmp_path, "apptainer version 1.4.0")))
    declared = _Process(tmp_path, path=str(_builder_binary(tmp_path, "apptainer version 1.4.0")), declared="1.5.4-typo")
    blind = _Process(tmp_path, path=str(_no_tools(tmp_path)))

    assert registry._build_provenance(observed, family)["apptainer_version_source"] == "observed"
    assert registry._build_provenance(observed, family)["apptainer_version"] == "apptainer version 1.4.0"

    # The declared pin still *is* the identity (the controller's intended builder),
    # but the record says the value was declared rather than observed here.
    pinned = registry._build_provenance(declared, family)
    assert pinned["apptainer_version"] == "1.5.4-typo"
    assert pinned["apptainer_version_source"] == "declared"
    assert registry._build_provenance(blind, family)["apptainer_version_source"] == "observed"


def test_a_declared_builder_is_shared_without_being_reobserved(tmp_path, monkeypatch):
    """An already-declared builder is forwarded as-is, not re-probed on a host without one.

    The controller shares before any container exists; a later ``up`` that already
    carries the value must forward the same identity even on a host whose PATH no
    longer resolves Apptainer, rather than dropping to an empty builder.
    """
    env_file = tmp_path / "server.env"
    monkeypatch.setenv("PATH", str(_no_tools(tmp_path)))
    monkeypatch.setenv("REVODESIGN_APPTAINER_VERSION", "apptainer version 1.5.4")
    state = EnvState(str(env_file), values={"USE_SLURM": "1"})

    assert registry.record_apptainer_builder_version(state) == "apptainer version 1.5.4"
    assert state.exported()["REVODESIGN_APPTAINER_VERSION"] == "apptainer version 1.5.4"


def test_the_controller_forwards_its_observation_into_the_compose_environment(tmp_path, monkeypatch):
    """The observation must reach the containers, and only through the process env.

    ``EnvState.exported()`` is the environment the ``docker compose up`` subprocess
    is started with, so a value placed there is what the server containers
    inherit.  It is deliberately not written into the deployment env file, which
    is the operator's to pin.
    """
    bin_dir = _builder_binary(tmp_path, "apptainer version 1.5.4")
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    env_file = tmp_path / "server.env"
    state = EnvState(str(env_file), values={"USE_SLURM": "1"})

    steps_mod.share_apptainer_builder(state)

    assert os.environ["REVODESIGN_APPTAINER_VERSION"] == "apptainer version 1.5.4"
    assert state.exported()["REVODESIGN_APPTAINER_VERSION"] == "apptainer version 1.5.4"
    assert not env_file.exists()


@pytest.mark.parametrize(
    "path_window",
    [
        # A PATH that holds no Apptainer, as a server container's does.
        "/nonexistent",
        # The same condition with a directory that exists but holds no builder.
        "{empty}",
    ],
)
def test_an_unobservable_controller_records_nothing_and_warns(tmp_path, monkeypatch, capsys, path_window):
    """No shared value is invented where the controller cannot observe a builder.

    Sharing an unobserved builder would be a fabricated identity -- worse than no
    observation, because it would silently mark correctly-recorded images stale.
    The walk says so on stderr and leaves the variable unset, so build freshness
    stays honestly unprovable in that process.
    """
    monkeypatch.setenv("PATH", path_window.format(empty=_no_tools(tmp_path)))
    state = EnvState(str(tmp_path / "server.env"), values={"USE_SLURM": "1"})

    steps_mod.share_apptainer_builder(state)

    assert "REVODESIGN_APPTAINER_VERSION" not in os.environ
    assert "REVODESIGN_APPTAINER_VERSION" not in state.exported()
    assert "cannot be shared" in capsys.readouterr().err


def test_a_scheduler_less_controller_records_nothing(tmp_path, monkeypatch):
    """A deployment that builds no SIFs has no builder observation to share."""
    bin_dir = _builder_binary(tmp_path, "apptainer version 1.5.4")
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    state = EnvState(str(tmp_path / "server.env"), values={"REVOCOMPUTE_JOB_EXECUTOR": "docker"})

    steps_mod.share_apptainer_builder(state)

    assert "REVODESIGN_APPTAINER_VERSION" not in os.environ
