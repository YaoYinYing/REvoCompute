# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Deployment validation and build helpers for runner-family plugins."""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

import yaml
from revocompute_ctl import SERVER_ROOT
from revocompute_ctl.compose import run_cmd

if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from revocompute.access_control import load_policy_documents, resolve_policy  # noqa: E402
from revocompute.plugins import PluginManager  # noqa: E402
from revocompute.live_tests import atomic_write_json, canonical_digest, sha256_file  # noqa: E402

_SAFE_FAMILY_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


@dataclass(frozen=True)
class RuntimeFamily:
    name: str
    version: str
    definition: str
    image_artifact: str
    slurm_image: str
    entrypoint: tuple[str, ...] = ()
    build_inputs: tuple[str, ...] = ()
    root: Path | None = None


class RegistryError(Exception):
    """Validation failed; the message is already user-facing."""


def load_plugin_families(runners_dir: str | os.PathLike[str]) -> list[RuntimeFamily]:
    """Load deployable runtime families from the server-instance plugin tree."""
    root = Path(runners_dir)
    manager = PluginManager()
    try:
        manifests = manager.discover(root)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"Invalid runner plugin configuration: {exc}", file=sys.stderr)
        raise RegistryError from exc
    families: list[RuntimeFamily] = []
    for manifest in manifests:
        runtime = manifest.runtime
        if not isinstance(runtime, dict):
            print(f"Runner plugin {manifest.id} runtime must be a mapping", file=sys.stderr)
            raise RegistryError
        image_artifact = str(runtime.get("image_artifact") or "")
        slurm_image = str(runtime.get("slurm_image") or image_artifact)
        definition = str(runtime.get("definition") or f"{manifest.id}.def")
        entrypoint = runtime.get("entrypoint", ())
        build_inputs = runtime.get("build_inputs", [])
        if (
            not image_artifact
            or not slurm_image
            or Path(image_artifact).is_absolute()
            or ".." in Path(image_artifact).parts
            or (not Path(slurm_image).is_absolute() and ".." in Path(slurm_image).parts)
            or Path(definition).is_absolute()
            or ".." in Path(definition).parts
            or not isinstance(entrypoint, list)
            or any(not isinstance(item, str) or not item for item in entrypoint)
            or not isinstance(build_inputs, list)
            or any(not isinstance(item, str) for item in build_inputs)
        ):
            print(f"Runner plugin {manifest.id} has invalid runtime assets", file=sys.stderr)
            raise RegistryError
        for build_input in build_inputs:
            path = Path(build_input)
            if path.is_absolute() or ".." in path.parts:
                print(f"Runner plugin {manifest.id} has unsafe build input: {build_input}", file=sys.stderr)
                raise RegistryError
        families.append(
            RuntimeFamily(
                manifest.id,
                manifest.version,
                definition,
                image_artifact,
                slurm_image,
                tuple(entrypoint),
                tuple(build_inputs),
                manifest.path,
            )
        )
    return families


def deployment_plugin_root(state) -> Path:
    """Return the runner tree used by deployment validation.

    Prepared instances use the materialized tree.  Dry-run validation happens
    before materialization, so it intentionally falls back to the checked-out
    source tree without consulting the retired task registry.
    """
    materialized = Path(state.server_dir()) / "docker" / "runners"
    # Once setup has created the instance tree, an empty directory is a valid
    # zero-runner snapshot and must remain authoritative.
    if materialized.is_dir():
        return materialized
    source_override = state.get("RUNNER_SOURCE_ROOT")
    source = Path(source_override) if source_override else Path(SERVER_ROOT) / "docker" / "runners"
    if source.is_dir() and any(source.glob("*/plugin.yaml")):
        return source
    raise RegistryError(f"Runner plugin tree is missing: {materialized}")


def validate_plugin_policies(runners_dir: str | os.PathLike[str], policy_root: str | os.PathLike[str]) -> None:
    """Validate policy documents and runtime policy references in plugins."""
    try:
        policies = load_policy_documents(policy_root)
        manifests = PluginManager().discover(runners_dir)
        for manifest in manifests:
            # Policy documents travel with their owning runner family.  Keep
            # the deployment-level directory as an overlay for operator policies.
            for policy_id, policy in load_policy_documents(manifest.path / "policies").items():
                declared = manifest.contributions.get("access_policies")
                if declared is not None and policy_id not in declared:
                    raise ValueError(
                        f"Runner plugin {manifest.id} policy {policy_id!r} is not declared as an access-policy contribution"
                    )
                # Identical legacy copies are tolerated during one deploy
                # transition; divergent definitions remain an error.
                if policy_id in policies and policies[policy_id] != policy:
                    raise ValueError(f"Duplicate access policy identifier: {policy_id!r}")
                policies[policy_id] = policy
            runtime = manifest.runtime
            if not isinstance(runtime, dict) or runtime.get("access_policy") is None:
                continue
            resolve_policy(str(runtime["access_policy"]), policies)
    except (OSError, ValueError, yaml.YAMLError, KeyError) as exc:
        raise RegistryError(f"Invalid Runner access policy configuration: {exc}") from exc


def validate_runtime_files(state) -> list[RuntimeFamily]:
    """Port of validate_runtime_files() — every family, artifact, and runner
    YAML check, with the pinned messages."""
    config_root = state.config_dir()
    plugin_root = deployment_plugin_root(state)
    validate_plugin_policies(plugin_root, Path(config_root) / "access_policies")
    manifests = PluginManager().discover(plugin_root)
    families = load_plugin_families(plugin_root)
    # SERVER_DIR points at the live server data tree; runner SIFs are kept in
    # its sibling images directory so deployments can share the image store
    # without coupling plugin manifests to one host path.
    image_dir = Path(state.server_dir()).parent / "images"
    families = [
        replace(family, slurm_image=str(image_dir / family.slurm_image))
        if not Path(family.slurm_image).is_absolute()
        else family
        for family in families
    ]
    family_roots = {manifest.id: manifest.path for manifest in manifests}

    known: set[str] = set()
    for family in families:
        if not _SAFE_FAMILY_NAME.match(family.name):
            print(f"Runtime family name is not safe for Compose: {family.name}", file=sys.stderr)
            raise RegistryError
        known.add(family.name)
        if not runner_enabled(state, family.name):
            continue
        for relative_path in (family.definition,):
            if (
                relative_path.startswith("/")
                or relative_path == ".."
                or relative_path.startswith("../")
                or "/../" in relative_path
                or relative_path.endswith("/..")
                or "\\" in relative_path
            ):
                print(f"Runtime family {family.name} has unsafe build path: {relative_path}", file=sys.stderr)
                raise RegistryError
            family_root = family_roots[family.name]
            if not (family_root / relative_path).is_file():
                print(
                    f"Runtime family {family.name} is missing build artifact: {family_root / relative_path}",
                    file=sys.stderr,
                )
                raise RegistryError
        if state.use_slurm() and not family.slurm_image.startswith("/"):
            print(f"SLURM runtime family {family.name} must declare an absolute slurm_image", file=sys.stderr)
            raise RegistryError

        for build_input in family.build_inputs:
            build_path = plugin_root / build_input
            if not build_path.is_file() or not build_path.resolve().is_relative_to(plugin_root.resolve()):
                print(f"Runtime family {family.name} is missing build input: {build_path}", file=sys.stderr)
                raise RegistryError
        definition_text = (family_roots[family.name] / family.definition).read_text(encoding="utf-8")
        bootstrap = _first_directive_value(definition_text, "Bootstrap:")
        if not bootstrap or bootstrap == "docker-daemon":
            print(
                f"Runtime family {family.name} definition must build directly from an upstream source",
                file=sys.stderr,
            )
            raise RegistryError

    requested = {name for name in state.get("ENABLED_TASKRUNNERS").split(",") if name}
    unknown = requested - known
    if unknown:
        print(f"Unknown runner selection: {', '.join(sorted(unknown))}", file=sys.stderr)
        raise RegistryError
    return families


def _first_directive_value(text: str, directive: str) -> str:
    for line in text.splitlines():
        if line.split(" ", 1)[0] == directive:
            return line.split(":", 1)[1].strip()
    return ""


# -- enabled-runner selection ------------------------------------------------


def expand_enabled_runners(state, families: list[RuntimeFamily]) -> None:
    """Normalize empty ENABLED_TASKRUNNERS ("build all") into an explicit
    list so a failed runner can be dropped from it for the rest of the run."""
    if state.get("ENABLED_TASKRUNNERS"):
        return
    state.runtime["ENABLED_TASKRUNNERS"] = ",".join(family.name for family in families)


def runner_enabled(state, name: str) -> bool:
    enabled = state.get("ENABLED_TASKRUNNERS")
    if not enabled:
        return True
    return name in enabled.split(",")


def drop_enabled_runner(state, target: str) -> None:
    remaining = [name for name in state.get("ENABLED_TASKRUNNERS").split(",") if name and name != target]
    state.runtime["ENABLED_TASKRUNNERS"] = ",".join(remaining)


# -- SLURM images ------------------------------------------------------------


def staged_sif_path(family: RuntimeFamily) -> str:
    """The activation target: a freshly staged .next when present, else the
    deployed SIF."""
    staged = f"{family.slurm_image}.next"
    return staged if Path(staged).is_file() else family.slurm_image


def validate_slurm_images(state, families: list[RuntimeFamily]) -> None:
    missing = 0
    for family in families:
        if not runner_enabled(state, family.name):
            continue
        target = staged_sif_path(family)
        if not Path(target).is_file():
            print(f"[SLURM] Missing SIF image: {family.slurm_image}", file=sys.stderr)
            print(
                "        Build it:  apptainer build --fakeroot "
                f"{family.slurm_image} {state.server_root()}/{family.definition}",
                file=sys.stderr,
            )
            missing += 1
        else:
            print(f"[SLURM] Found SIF image: {family.slurm_image}")
    if missing:
        print(
            f"[SLURM] {missing} SIF image(s) missing. Rerun with --build-sif to auto-build, or build manually.",
            file=sys.stderr,
        )
        raise RegistryError


def _docker_tag(image: str, suffix: str = "latest") -> str:
    repository = image.rsplit("/", 1)[-1]
    return f"{image}:{suffix}" if ":" not in repository and "@" not in image else image


def _sif_digest_manifest(family: RuntimeFamily) -> Path:
    return Path(family.slurm_image).parent / "digest" / "image-sif.json"


def _apptainer_version(state) -> str:
    result = run_cmd(["apptainer", "--version"], env=state.exported(), check=False, capture=True)
    return (result.stdout or result.stderr or "").strip()


def _definition_path(family: RuntimeFamily) -> Path:
    if family.root is None:
        raise RegistryError(f"Runtime family {family.name} has no source root")
    return family.root / family.definition


def _build_provenance(state, family: RuntimeFamily) -> dict[str, object]:
    if family.root is None:
        raise RegistryError(f"Runtime family {family.name} has no source root")
    runner_root = family.root.parent
    inputs = []
    for relative in family.build_inputs:
        path = (runner_root / relative).resolve()
        if not path.is_file() or not path.is_relative_to(runner_root.resolve()):
            raise RegistryError(f"Runtime family {family.name} build input is unavailable: {relative}")
        inputs.append({"path": relative, "sha256": sha256_file(path)})
    definition = _definition_path(family)
    identity = {
        "runner_family": family.name,
        "family_version": family.version,
        "definition": family.definition,
        "definition_sha256": sha256_file(definition),
        "build_inputs": inputs,
        "apptainer_version": _apptainer_version(state),
    }
    return {**identity, "build_provenance_digest": canonical_digest(identity)}


def _read_sif_manifest(family: RuntimeFamily) -> dict[str, dict[str, str]]:
    try:
        data = json.loads(_sif_digest_manifest(family).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _record_sif_manifest(state, family: RuntimeFamily, sif_path: str) -> None:
    manifest = _sif_digest_manifest(family)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    data = _read_sif_manifest(family)
    data[family.name] = {
        **_build_provenance(state, family),
        "sif_sha256": sha256_file(sif_path),
        "build_timestamp": datetime.now(timezone.utc).isoformat(),
    }
    atomic_write_json(manifest, data)


def _sif_manifest_matches(state, family: RuntimeFamily, sif_path: str) -> bool:
    entry = _read_sif_manifest(family).get(family.name) or {}
    provenance = _build_provenance(state, family)
    return entry.get("build_provenance_digest") == provenance["build_provenance_digest"] and entry.get(
        "sif_sha256"
    ) == sha256_file(sif_path)


def sif_stale(state, family: RuntimeFamily, path: str | None = None) -> bool:
    """True unless provenance proves the SIF matches all declared direct-build inputs."""
    path = path or family.slurm_image
    if not Path(path).is_file():
        return True
    return not _sif_manifest_matches(state, family, path)


def build_slurm_images(state, families: list[RuntimeFamily], *, fail_on_error: bool = False) -> int:
    """Stage SIFs as ``<sif>.next`` for missing or stale families only;
    promotion moves them into place only after exact-hash live acceptance."""
    import shutil

    if not shutil.which("apptainer"):
        print("[SLURM] apptainer not found on PATH; cannot build requested SIF images.", file=sys.stderr)
        raise RegistryError

    expand_enabled_runners(state, families)
    built = 0
    for family in families:
        if not runner_enabled(state, family.name):
            continue
        def_file = _definition_path(family)
        if not def_file.is_file():
            print(f"[SLURM] No .def file for runtime family '{family.name}': {def_file}", file=sys.stderr)
            drop_enabled_runner(state, family.name)
            continue
        staged = f"{family.slurm_image}.next"
        if Path(staged).is_file():
            if not sif_stale(state, family, staged):
                continue
            os.remove(staged)
        if not sif_stale(state, family):
            print(f"[SLURM] SIF image unchanged: {family.slurm_image} — skipping.")
            continue
        print(f"[SLURM] Building {staged} from {def_file}...")
        Path(staged).parent.mkdir(parents=True, exist_ok=True)
        staging = f"{staged}.build"
        if os.path.lexists(staging):
            os.remove(staging)
        result = run_cmd(
            ["apptainer", "build", "--fakeroot", staging, str(def_file)],
            env=state.exported(),
            check=False,
            cwd=family.root.parent if family.root is not None else None,
        )
        if result.returncode != 0:
            if os.path.isfile(staging):
                os.remove(staging)
            print(f"[SLURM] Build failed for {family.name} — disabled for this restart.", file=sys.stderr)
            drop_enabled_runner(state, family.name)
            if fail_on_error:
                raise RegistryError(f"Direct SIF build failed for {family.name}")
        else:
            os.replace(staging, staged)
            _record_sif_manifest(state, family, staged)
            built += 1
    if built:
        print(f"[SLURM] Built {built} SIF image(s).")
    return built


# -- prepared activation -----------------------------------------------------


def validate_prepared_images(state, families: list[RuntimeFamily]) -> None:
    required = [
        state.get("SERVER_IMAGE") or "revodesign-revocompute-server:latest",
        "nginx:1.28-alpine",
        "redis:7.2-alpine",
    ]
    for family in families:
        if runner_enabled(state, family.name):
            staged = Path(f"{family.slurm_image}.next")
            if state.use_slurm():
                if staged.is_file():
                    valid = _sif_manifest_matches(state, family, str(staged))
                elif Path(family.slurm_image).is_file():
                    valid = not sif_stale(state, family)
                else:
                    valid = False
                if not valid:
                    print(f"Prepared SIF provenance is invalid: {family.name}", file=sys.stderr)
                    raise RegistryError
                if staged.is_file():
                    from revocompute_ctl.live_test import candidate_receipt_valid

                    if not candidate_receipt_valid(state, family):
                        print(
                            f"Prepared SIF has no valid exact-hash live-test receipt: {family.name}",
                            file=sys.stderr,
                        )
                        raise RegistryError(f"Prepared SIF has no valid exact-hash live-test receipt: {family.name}")
    for image in required:
        result = run_cmd(["docker", "image", "inspect", image], env=state.exported(), check=False, capture=True)
        if result.returncode != 0:
            print(f"Prepared Docker image is missing: {image}", file=sys.stderr)
            raise RegistryError


def validate_compose_model(state, compose_cmd: tuple[str, ...]) -> None:
    run_cmd(
        [*compose_cmd, *state.compose_args(), "--env-file", state.env_file, "config", "--quiet"],
        env=state.exported(),
    )
