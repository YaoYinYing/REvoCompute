#!/usr/bin/env python3
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""BioEmu2 adapter for equilibrium sampling, structure prediction, and propagation.

The Task manifest selects the mode; the adapter never infers it from a filename.
Equilibrium and structure prediction share the sequence-to-system construction
upstream's Python API does not do for us:

* ``equilibrium`` and ``structure`` build the ``System`` from the Task's named
  ``sequence`` role and call upstream's matching sampling entry point;
* ``propagate`` runs upstream's own ``bioemu2 propagate`` command against the
  named ``starting_structure`` CIF, with an optional explicit ``system`` YAML
  when the CIF's inferred system would not be the submitted molecule.

Everything else -- MSA acquisition, embedding, denoising, physicality checking,
``samples.xtc``/``topology.cif``/``system.yaml``/``physicality.json`` -- is
upstream writing into the output directory. An optional parameter the manifest
did not resolve is not passed, so upstream's own preset applies rather than a
copy of its default kept here.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path

#: The protein alphabet BioEmu2's ``Protein`` entity accepts. Stricter than the
#: server's ``validate_fasta`` alphabet, which also admits the ambiguity codes
#: B, Z, J, and O and the stop/gap spells -- none of which names a residue
#: BioEmu2 can sample. The Task input role declares this stricter set.
PROTEIN_CHARS = frozenset("ACDEFGHIKLMNPQRSTVWYX")

#: Propagation outputs upstream refuses to overwrite. Clearing exactly these
#: before the call keeps a re-run in the same directory deterministic without
#: deleting anything the Server published.
PROPAGATION_OUTPUTS = ("samples.xtc", "physicality.json")

#: Upstream fetches public CCD components on the first cache miss with a single
#: ``requests.get`` and no retry, so one transient TLS/connection failure fails
#: the Task. The propagation path resolves those components only after the
#: model is loaded; warming the same cache first bounds that failure without
#: touching upstream. The cache is task-local by upstream's default, so every
#: Task gets these attempts rather than sharing mutable cache state between
#: concurrent Runners.
CCD_FETCH_ATTEMPTS = 3
CCD_FETCH_BACKOFF_SECONDS = 2.0

#: Upstream's ligand steering loads the Boltz-1 CCD dictionary through
#: ``huggingface_hub``, which under ``HF_HUB_OFFLINE=1`` only checks its local
#: cache. The dictionary is mounted read-only, so the adapter exposes it to that
#: lookup through a task-local cache instead of downloading it.
STEERING_CCD_REVISION = "7c1d83b779e4c65ecc37dfdf0c6b2788076f31e1"
_STEERING_CCD_REPO = "models--boltz-community--boltz-1"

#: mmCIF categories whose molecular meaning upstream's CIF inference does not
#: preserve: explicit connections are ignored and branched entities omitted.
#: Either would propagate a structure other than the one submitted, so the
#: Runner refuses unless the submission declares the matching system YAML.
_INFERENCE_LOSS_CATEGORIES = (
    ("_struct_conn", "explicit _struct_conn connections"),
    ("_pdbx_entity_branch", "branched entities"),
    ("_pdbx_entity_branch_list", "branched entity monomers"),
    ("_pdbx_entity_branch_link", "branched entity links"),
)


def query_sequence(path: Path) -> str:
    """Return the single protein sequence of a Task FASTA ``sequence`` file.

    Raises ``ValueError`` for anything but exactly one headed, non-empty record:
    a second ``>`` (even with an empty header) would otherwise fuse two proteins
    into one chain and sample the wrong molecule without any error.
    """
    records = 0
    residues: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(">"):
            records += 1
            if records > 1:
                raise ValueError("BioEmu2 takes exactly one protein sequence")
            if not line[1:].strip():
                raise ValueError(f"{path.name} has an empty FASTA header")
            continue
        residues.append("".join(line.split()).upper())
    if not records or not residues:
        raise ValueError(f"{path.name} holds no FASTA sequence")
    sequence = "".join(residues)
    invalid = sorted(set(sequence) - PROTEIN_CHARS)
    if invalid:
        raise ValueError(f"BioEmu2 cannot sample residues {', '.join(invalid)}")
    return sequence


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


def _cif_tokens(text: str) -> Iterator[str]:
    """Yield lowercase unquoted CIF data names and values.

    Data names are whitespace-delimited tokens, not line prefixes: a legal
    ``loop_`` may put several on one line. Comments, quoted values, and
    semicolon text fields cannot carry a data name, so they are skipped.
    """
    in_text_field = False
    for line in text.splitlines():
        if in_text_field:
            in_text_field = not line.startswith(";")
            continue
        if line.startswith(";"):
            in_text_field = True
            continue
        index = 0
        while index < len(line):
            char = line[index]
            if char.isspace():
                index += 1
                continue
            if char == "#":
                break
            if char in "'\"":
                quote = char
                index += 1
                while index < len(line) and not (
                    line[index] == quote
                    and (index + 1 == len(line) or line[index + 1].isspace())
                ):
                    index += 1
                index += 1
                continue
            start = index
            while index < len(line) and not line[index].isspace():
                index += 1
            yield line[start:index].lower()


def inference_losses(cif_path: Path) -> list[str]:
    """The features upstream's CIF inference would silently omit."""
    found: list[str] = []
    text = cif_path.read_text(encoding="utf-8", errors="replace").lstrip("﻿")
    for token in _cif_tokens(text):
        for category, label in _INFERENCE_LOSS_CATEGORIES:
            if token.startswith(category + ".") and label not in found:
                found.append(label)
    return found


def require_exact_system(cif_path: Path, system_path: Path | None) -> None:
    """Refuse an inferred system that would not be the submitted molecule.

    A declared system YAML makes the molecular definition explicit, and upstream
    still compares every starting atom and its order against it.  Without one,
    upstream drops or ignores these records with only a warning, so the Runner
    states the limitation before any model work starts.
    """
    if system_path is not None:
        return
    losses = inference_losses(cif_path)
    if losses:
        raise ValueError(
            "BioEmu2 cannot reproduce this starting CIF exactly: it contains "
            + ", ".join(losses)
            + ", which CIF inference does not import. Provide the matching BioEmu2 system "
            "YAML as the 'system' input, or use a simple protein system."
        )


def sampling_kwargs(params: dict) -> dict:
    """The resolved task parameters that tune upstream sampling."""
    kwargs: dict = {"num_samples": int(params["num_samples"])}
    for key in ("sampler", "physicality_mode", "batch_size", "num_steps", "seed"):
        if params.get(key) is not None:
            kwargs[key] = params[key]
    return kwargs


def physicality_summary(path: Path) -> str:
    """One log line for the per-frame physicality outcome upstream wrote.

    A rejected ensemble is a result with a stated limitation, not a failure, so
    this only reports: the counts and rejection reasons must be readable without
    opening ``physicality.json``.
    """
    frames = json.loads(path.read_text(encoding="utf-8"))
    statuses = Counter(str(frame.get("status")) for frame in frames)
    reasons = Counter(str(frame.get("reason") or "unspecified") for frame in frames if frame.get("status") == "rejected")
    summary = f"BioEmu2 physicality: {statuses.get('passed', 0)}/{len(frames)} frames accepted"
    if reasons:
        summary += " (" + ", ".join(f"{reason}: {count}" for reason, count in sorted(reasons.items())) + ")"
    for status in ("rejected", "not_checked"):
        if statuses.get(status):
            summary += f", {statuses[status]} {status.replace('_', ' ')}"
    return summary


def sample(manifest: dict, output_dir: Path, checkpoint: Path, mode: str) -> None:
    """Run upstream's equilibrium sampler or folded-structure predictor."""
    import bioemu2

    sequence = query_sequence(input_path(manifest, "sequence"))
    system = bioemu2.System.from_description(proteins=[sequence])
    model = bioemu2.load_model(checkpoint_path=checkpoint)
    entry_point = bioemu2.sample_equilibrium if mode == "equilibrium" else bioemu2.predict_structure
    entry_point(system, model=model, output_dir=output_dir, **sampling_kwargs(manifest["params"]))
    (output_dir / "sequence.fasta").write_text(f">input\n{sequence}\n", encoding="utf-8")


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


def propagation_ccd_codes(starting_structure: Path, declared_system: Path | None) -> list[str]:
    """The CCD components upstream's ``propagate`` will resolve for this Task.

    Resolving the same ``System`` from the same inputs keeps this list identical
    to the command's. Upstream's validation rejects invalid codes before any
    request, so a missing component reaches the fetch as a 404, not a typo.
    """
    from bioemu2 import System
    from bioemu2.data_interface import load_system_and_contacts

    if declared_system is not None:
        system, _contacts = load_system_and_contacts(declared_system)
    else:
        system = System.from_cif(starting_structure)
    return _ccd_codes_in(system.model_dump())


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
    raised immediately. A connection, TLS, timeout, 429, or 5xx failure is
    retried with exponential backoff up to *attempts* total; the final error
    names the component, URL, and attempt count.
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


def configure_steering_cache(
    scratch: Path, source: str | None = None, *, required: bool = False
) -> Path | None:
    """Expose the mounted steering dictionary to upstream's offline HF lookup.

    ``huggingface_hub`` resolves a cached file under ``HF_HOME`` before it
    attempts a network request. A task-local cache entry made from the verified
    read-only asset keeps the lookup offline and leaves no mutable shared state.
    Propagation requires the dictionary: without it the CLI fails only after
    loading the model, with an offline cache error from upstream.
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


def propagate(manifest: dict, output_dir: Path, checkpoint: Path) -> None:
    """Run upstream's ``bioemu2 propagate`` command from one starting CIF.

    Without a ``system`` input the upstream command infers the molecular system
    from ``--x0-cif``; that inference ignores explicit connections and branched
    entities, so those structures are refused unless the submission supplies the
    matching system YAML. Its CCD components are fetched into upstream's cache
    first, because upstream resolves them only after loading the model and does
    not retry a transient request. It saves one independent endpoint per
    requested sample at a single lag and refuses to overwrite its own coordinate
    and physicality files, so only those are cleared before the call; every
    other output is upstream's to replace.
    """
    starting_structure = input_path(manifest, "starting_structure")
    declared_system = optional_input_path(manifest, "system")
    require_exact_system(starting_structure, declared_system)
    prefetch_ccd(propagation_ccd_codes(starting_structure, declared_system))
    params = manifest["params"]
    for name in PROPAGATION_OUTPUTS:
        (output_dir / name).unlink(missing_ok=True)
    for stale in output_dir.glob("samples_*.xtc"):
        stale.unlink()

    command = [
        os.environ.get("BIOEMU2_CLI", "bioemu2"),
        "propagate",
        "--x0-cif",
        str(starting_structure),
        *(["--system", str(declared_system)] if declared_system is not None else []),
        "--checkpoint-path",
        str(checkpoint),
        "--out",
        str(output_dir),
        "--num-samples",
        str(int(params["num_samples"])),
        "--lag-time-ns",
        f"{float(params['lag_time_ns']):g}",
    ]
    optional_flags = (
        ("--seed", "seed"),
        ("--num-steps", "num_steps"),
        ("--batch-size", "batch_size"),
        ("--sampler", "sampler"),
    )
    for flag, key in optional_flags:
        if params.get(key) is not None:
            command += [flag, str(params[key])]
    if params.get("physicality_mode") is not None:
        command += ["--physicality-filter", str(params["physicality_mode"])]
    print(
        "BioEmu2 propagation system: "
        + ("declared system YAML" if declared_system is not None else "inferred from the starting CIF")
    )
    subprocess.run(command, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--checkpoint-dir", required=True, type=Path)
    parser.add_argument("--mode", required=True, choices=("equilibrium", "structure", "propagate"))
    args = parser.parse_args()

    manifest = json.loads(args.task_manifest.read_text(encoding="utf-8"))
    checkpoint = args.checkpoint_dir / "checkpoint.ckpt"
    if not checkpoint.is_file():
        raise SystemExit(f"BioEmu2 checkpoint not found: {checkpoint}")

    # Keep the raw ColabFold response in task-local scratch: a cache in the
    # weight namespace would be mutable shared state. Every mode queries the
    # hosted MMseqs2 service for the system's alignment.
    scratch = Path(tempfile.mkdtemp(prefix="revodesign-bioemu2."))
    os.environ["BIOEMU2_MSA_CACHE"] = str(scratch / "colabfold_msa")
    try:
        if args.mode == "propagate":
            configure_steering_cache(scratch, required=True)
            propagate(manifest, args.output_dir, checkpoint)
        else:
            sample(manifest, args.output_dir, checkpoint, args.mode)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    print(physicality_summary(args.output_dir / "physicality.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
