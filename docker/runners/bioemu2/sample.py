#!/usr/bin/env python3
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""BioEmu2 adapter for the unified Task's equilibrium, structure-prediction,
and propagation modes.

The Task's ``mode`` parameter selects the upstream command; the adapter never
infers it from a filename. Every mode requires the named ``system`` YAML role,
which the pinned upstream parser validates, and ``propagate`` additionally
requires the named ``starting_structure`` mmCIF. The pinned ``propagate``
command compares the CIF atoms and their order against that system before it
loads the model and refuses a mismatch.

Two external assets are resolved before any model work:

* RCSB CCD component CIFs for every modified residue, branched entity, or CCD
  ligand in the system. Upstream fetches them on demand with a single request
  and no retry, so the adapter warms the same task-local cache first (#148).
* The Boltz-1 CCD dictionary read by upstream's ligand steering potentials.
  Any steered sampler (``edm_gd``, ``edm_fk``, ``edm_fkc``) consults it when the
  system declares a CCD ligand, in every mode; ``edm`` never does.

Everything else -- MSA acquisition, embedding, denoising, physicality checking,
``samples.xtc``/``topology.cif``/``system.yaml``/``physicality.json`` -- is
upstream writing into the output directory. An optional parameter the manifest
did not resolve is not passed, so upstream's own preset applies rather than a
copy of its default kept here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Callable, Iterable
from pathlib import Path

#: The upstream commands each Task mode runs.
MODE_COMMANDS = {
    "equilibrium": "sample-equilibrium",
    "structure_prediction": "predict-structure",
    "propagate": "propagate",
}

#: Samplers that build steering potentials and therefore consult the Boltz-1
#: CCD dictionary for a CCD-specified ligand. ``edm`` is unsteered.
STEERING_SAMPLERS = frozenset({"edm_gd", "edm_fk", "edm_fkc"})

#: Propagation outputs upstream refuses to overwrite. Clearing exactly these
#: before the call keeps a re-run in the same directory deterministic without
#: deleting anything the Server published.
PROPAGATION_OUTPUTS = ("samples.xtc", "physicality.json")

#: Upstream fetches public CCD components on the first cache miss with a single
#: ``requests.get`` and no retry, so one transient TLS/connection failure fails
#: the Task. Warming the same cache first bounds that failure without touching
#: upstream. The cache is task-local by upstream's default, so every Task gets
#: these attempts rather than sharing mutable cache state between concurrent
#: Runners.
CCD_FETCH_ATTEMPTS = 3
CCD_FETCH_BACKOFF_SECONDS = 2.0

#: Upstream's ligand steering loads the Boltz-1 CCD dictionary through
#: ``huggingface_hub``, which under ``HF_HUB_OFFLINE=1`` only checks its local
#: cache. The dictionary is mounted read-only, so the adapter exposes it to that
#: lookup through a task-local cache instead of downloading it.
STEERING_CCD_REVISION = "7c1d83b779e4c65ecc37dfdf0c6b2788076f31e1"
_STEERING_CCD_REPO = "models--boltz-community--boltz-1"


def input_path(manifest: dict, role: str) -> Path:
    """The sole file of a required input role in the immutable task manifest."""
    path = optional_input_path(manifest, role)
    if path is None:
        raise ValueError(f"input role {role!r} must hold exactly one file")
    return path


def optional_input_path(manifest: dict, role: str) -> Path | None:
    """The sole file of an optional input role, or ``None`` when it is absent."""
    files = manifest.get("inputs", {}).get(role)
    if files is None:
        return None
    if not isinstance(files, list):
        raise ValueError(f"input role {role!r} must hold at most one file")
    if not files:
        # The server declares every role in the immutable manifest and leaves
        # an unsubmitted optional role as an empty list.
        return None
    if len(files) != 1:
        raise ValueError(f"input role {role!r} must hold at most one file")
    return Path(files[0]["path"])


def load_system(system_path: Path) -> tuple[object, object]:
    """Parse the submitted system with the pinned upstream parser.

    ``load_system_and_contacts`` validates the complete scientific document,
    including entity syntax, chain IDs, modifications, bonds, and contacts.
    The Server validates only transport and the logical ``supporting_data``
    type, so this is the first scientific parse and it fails closed.
    """
    from bioemu2.data_interface import load_system_and_contacts

    return load_system_and_contacts(system_path)


def _ccd_codes_in(value: object) -> list[str]:
    """CCD codes named anywhere in a serialized system, in first-seen order."""
    codes: list[str] = []

    def visit(node: object) -> None:
        if isinstance(node, dict):
            code = node.get("ccd_code")
            if isinstance(code, str) and code:
                codes.append(code)
            for key, item in node.items():
                if key != "ccd_code":
                    visit(item)
        elif isinstance(node, (list, tuple)):
            for item in node:
                visit(item)

    visit(value)
    return list(dict.fromkeys(codes))


def system_ccd_codes(system: object) -> list[str]:
    """The RCSB CCD components upstream needs to build this system's topology."""
    return _ccd_codes_in(system.model_dump())


def steered_ligand_ccd_codes(system: object, sampler: str) -> list[str]:
    """The CCD ligand codes whose steering constraints this run will resolve.

    Mirrors upstream's ``ligand_ccd_codes_from_system``: only ``ligand``
    entities carrying an explicit CCD code participate. Modified residues and
    branched entities use the topology cache above but not the steering
    dictionary, and ``edm`` never builds steering potentials.
    """
    if sampler not in STEERING_SAMPLERS:
        return []
    entities = system.model_dump().get("entities", [])
    return [
        str(entity["ccd_code"])
        for entity in entities
        if entity.get("entity_type") == "ligand" and entity.get("ccd_code")
    ]


def _ccd_url(ccd_code: str) -> str:
    """Upstream's CCD download URL, imported so the diagnostic cannot drift."""
    from bioemu2.structure.templates import _CCD_URL

    return _CCD_URL.format(ccd_code=ccd_code)


def _fetch_ccd(ccd_code: str) -> None:
    """Populate upstream's on-disk CCD cache for one component code."""
    from bioemu2.structure.templates import _get_ccd_path

    _get_ccd_path(ccd_code)


def _transient_request_error(error: Exception) -> bool:
    """Whether a failed CCD request can be retried without changing its meaning."""
    import requests

    if isinstance(error, requests.exceptions.HTTPError):
        response = error.response
        return response is not None and (response.status_code == 429 or response.status_code >= 500)
    # SSLError is a ConnectionError subclass. ChunkedEncodingError reports a
    # connection dropped mid-body, so a fresh request may succeed. InvalidURL,
    # InvalidSchema, MissingSchema, and TooManyRedirects are permanent and must
    # not retry.
    return isinstance(
        error,
        (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.ChunkedEncodingError,
        ),
    )


def prefetch_ccd(
    ccd_codes: Iterable[str],
    fetch: Callable[[str], object] = _fetch_ccd,
    *,
    attempts: int = CCD_FETCH_ATTEMPTS,
    backoff: float = CCD_FETCH_BACKOFF_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Warm upstream's CCD cache, retrying only transient request failures.

    A missing component (404), an invalid code, or any other permanent error is
    raised immediately. A connection, TLS, timeout, a body dropped mid-transfer
    (`ChunkedEncodingError`), 429, or 5xx failure is retried with exponential
    backoff up to *attempts* total; the final error names the component, URL,
    and attempt count.
    """
    import requests

    for ccd_code in ccd_codes:
        url = _ccd_url(ccd_code)
        for attempt in range(1, attempts + 1):
            try:
                fetch(ccd_code)
            except requests.exceptions.RequestException as error:
                if not _transient_request_error(error):
                    raise RuntimeError(
                        f"BioEmu2 CCD component {ccd_code!r} could not be fetched from {url} "
                        f"(attempt 1 of {attempts}, not retried): {error}"
                    ) from error
                if attempt == attempts:
                    raise RuntimeError(
                        f"BioEmu2 CCD component {ccd_code!r} could not be fetched from {url} "
                        f"after {attempts} attempts: {error}"
                    ) from error
                print(
                    f"BioEmu2 CCD fetch for {ccd_code!r} failed "
                    f"(attempt {attempt}/{attempts}): {error}",
                    file=sys.stderr,
                )
                sleep(backoff * 2 ** (attempt - 1))
            except Exception as error:
                raise RuntimeError(
                    f"BioEmu2 CCD component {ccd_code!r} could not be prepared from {url} "
                    f"(attempt 1 of {attempts}, not retried): {error}"
                ) from error
            else:
                break


def verify_steering_asset(asset: Path, manifest: Path) -> None:
    """Refuse a missing or modified Boltz-1 CCD dictionary before model work."""
    if not asset.is_file():
        raise RuntimeError(f"BioEmu2 steering CCD dictionary is missing: {asset}")
    try:
        first_line = manifest.read_text(encoding="utf-8")
    except OSError as error:
        raise RuntimeError(f"BioEmu2 steering CCD manifest is unreadable: {manifest}") from error
    declared = next(
        (parts[0] for line in first_line.splitlines() if (parts := line.split()) and not parts[0].startswith("#")),
        "",
    )
    if not declared or len(declared) != 64 or any(char not in "0123456789abcdef" for char in declared):
        raise RuntimeError(f"BioEmu2 steering CCD identity is undeclared: {manifest}")
    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    if digest != declared:
        raise RuntimeError(f"BioEmu2 steering CCD integrity verification failed: {asset}")


def configure_steering_cache(
    scratch: Path, source: str | None = None, *, required: bool = False
) -> Path | None:
    """Expose the mounted steering dictionary to upstream's offline HF lookup.

    ``huggingface_hub`` resolves a cached file under ``HF_HOME`` before it
    attempts a network request. A task-local cache entry made from the verified
    read-only asset keeps the lookup offline and leaves no mutable shared state.
    """
    source = source if source is not None else os.environ.get("BIOEMU2_STEERING_CCD")
    if not source:
        if required:
            raise RuntimeError(
                "BioEmu2 steering CCD dictionary is not configured; set BIOEMU2_STEERING_CCD"
            )
        return None
    asset = Path(source)
    if not asset.is_file():
        raise RuntimeError(f"BioEmu2 steering CCD dictionary not found: {asset}")
    cache = scratch / "huggingface"
    repo = cache / "hub" / _STEERING_CCD_REPO
    snapshot = repo / "snapshots" / STEERING_CCD_REVISION
    snapshot.mkdir(parents=True)
    (snapshot / "ccd.pkl").symlink_to(asset)
    refs = repo / "refs"
    refs.mkdir()
    # ``try_to_load_from_cache`` reads this file verbatim, so it must not carry
    # a trailing newline.
    (refs / "main").write_text(STEERING_CCD_REVISION, encoding="utf-8")
    os.environ["HF_HOME"] = str(cache)
    print(f"BioEmu2 steering CCD: {asset}")
    return asset


def physicality_summary(path: Path) -> str:
    """One log line for the per-frame physicality outcome upstream wrote.

    A rejected ensemble is a result with a stated limitation, not a failure, so
    this only reports: the counts and rejection reasons must be readable without
    opening ``physicality.json``.
    """
    frames = json.loads(path.read_text(encoding="utf-8"))
    statuses = Counter(str(frame.get("status")) for frame in frames)
    reasons = Counter(
        str(frame.get("reason") or "unspecified")
        for frame in frames
        if frame.get("status") == "rejected"
    )
    summary = f"BioEmu2 physicality: {statuses.get('passed', 0)}/{len(frames)} frames accepted"
    if reasons:
        summary += " (" + ", ".join(f"{reason}: {count}" for reason, count in sorted(reasons.items())) + ")"
    for status in ("rejected", "not_checked"):
        if statuses.get(status):
            summary += f", {statuses[status]} {status.replace('_', ' ')}"
    return summary


def command_for_mode(mode: str, manifest: dict, system_path: Path, checkpoint: Path,
                     output_dir: Path, starting_structure: Path | None) -> list[str]:
    """Build the pinned upstream CLI command for one validated mode."""
    params = manifest["params"]
    command = [
        os.environ.get("BIOEMU2_CLI", "bioemu2"),
        MODE_COMMANDS[mode],
        "--system",
        str(system_path),
        "--checkpoint-path",
        str(checkpoint),
        "--out",
        str(output_dir),
        "--num-samples",
        str(int(params["num_samples"])),
        "--sampler",
        str(params.get("sampler") or "edm"),
    ]
    if params.get("physicality_mode") is not None:
        command += ["--physicality-filter", str(params["physicality_mode"])]
    optional_flags = (
        ("--seed", "seed"),
        ("--num-steps", "num_steps"),
        ("--batch-size", "batch_size"),
    )
    for flag, key in optional_flags:
        if params.get(key) is not None:
            command += [flag, str(params[key])]
    if mode == "propagate":
        if starting_structure is None:
            raise ValueError("propagate requires the 'starting_structure' input role")
        command += ["--x0-cif", str(starting_structure), "--lag-time-ns", f"{float(params['lag_time_ns']):g}"]
    return command


def run_mode(mode: str, manifest: dict, output_dir: Path, checkpoint: Path, scratch: Path) -> None:
    """Validate the system and run one upstream mode."""
    system_path = input_path(manifest, "system")
    system, _contacts = load_system(system_path)
    starting_structure = optional_input_path(manifest, "starting_structure")
    if mode != "propagate" and starting_structure is not None:
        raise ValueError(f"mode {mode!r} does not accept a starting_structure")
    if mode == "propagate":
        if starting_structure is None:
            raise ValueError("propagate requires the 'starting_structure' input role")
        for name in PROPAGATION_OUTPUTS:
            (output_dir / name).unlink(missing_ok=True)
        for stale in output_dir.glob("samples_*.xtc"):
            stale.unlink()
        print("BioEmu2 propagation: upstream compares the starting CIF atoms and order before model load")

    prefetch_ccd(system_ccd_codes(system))
    steering_codes = steered_ligand_ccd_codes(system, str(manifest["params"].get("sampler") or "edm"))
    if steering_codes:
        asset = os.environ.get("BIOEMU2_STEERING_CCD")
        manifest_path = os.environ.get("BIOEMU2_STEERING_CCD_MANIFEST")
        if not asset or not manifest_path:
            raise RuntimeError(
                "BioEmu2 steering CCD dictionary is not configured; set "
                "BIOEMU2_STEERING_CCD and BIOEMU2_STEERING_CCD_MANIFEST"
            )
        verify_steering_asset(Path(asset), Path(manifest_path))
        configure_steering_cache(scratch, required=True)

    subprocess.run(
        command_for_mode(mode, manifest, system_path, checkpoint, output_dir, starting_structure),
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--checkpoint-dir", required=True, type=Path)
    args = parser.parse_args()

    manifest = json.loads(args.task_manifest.read_text(encoding="utf-8"))
    checkpoint = args.checkpoint_dir / "checkpoint.ckpt"
    if not checkpoint.is_file():
        raise SystemExit(f"BioEmu2 checkpoint not found: {checkpoint}")
    mode = str(manifest.get("params", {}).get("mode") or "equilibrium")
    if mode not in MODE_COMMANDS:
        raise SystemExit(f"Unknown BioEmu2 mode: {mode}")

    # Keep the raw ColabFold response in task-local scratch: a cache in the
    # weight namespace would be mutable shared state. Every mode queries the
    # hosted MMseqs2 service for the system's alignment.
    scratch = Path(tempfile.mkdtemp(prefix="revodesign-bioemu2."))
    os.environ["BIOEMU2_MSA_CACHE"] = str(scratch / "colabfold_msa")
    try:
        run_mode(mode, manifest, args.output_dir, checkpoint, scratch)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    print(physicality_summary(args.output_dir / "physicality.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
