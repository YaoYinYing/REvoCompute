#!/usr/bin/env python3
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shutil
from pathlib import Path
from typing import Any

VALID_RESIDUES = frozenset("ACDEFGHIKLMNPQRSTVWYBXZJUO-")
MODEL_NAME = "esm_msa1b_t12_100M_UR50S"
UPSTREAM_COMMIT = "6eedfcd5a0551bd1fecf9c51818be19f9e730e19"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_assets(root: Path, manifest_path: Path) -> tuple[Path, dict[str, Any]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("model") != MODEL_NAME or manifest.get("model_code", {}).get("revision") != UPSTREAM_COMMIT:
        raise ValueError("EvoSplit asset manifest does not match the pinned model and source revision")
    assets = manifest.get("assets")
    if not isinstance(assets, list) or len(assets) != 2:
        raise ValueError("EvoSplit asset manifest must inventory exactly two model files")
    model_path: Path | None = None
    for record in assets:
        relative = record.get("path")
        if not isinstance(relative, str) or not relative.startswith("checkpoints/"):
            raise ValueError("EvoSplit asset manifest contains an invalid path")
        path = root / relative
        if not path.is_file():
            raise FileNotFoundError(f"EvoSplit model asset is missing: {relative}")
        if path.stat().st_size != record.get("size"):
            raise ValueError(f"EvoSplit model asset has unexpected size: {relative}")
        if sha256(path) != record.get("sha256"):
            raise ValueError(f"EvoSplit model asset failed SHA-256 verification: {relative}")
        if relative.endswith(f"/{MODEL_NAME}.pt"):
            model_path = path
    if model_path is None:
        raise ValueError("EvoSplit asset manifest does not identify the model checkpoint")
    return model_path, manifest


def read_task_manifest(path: Path) -> tuple[Path, list[Path], dict[str, Any]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    files = document.get("files")
    params = document.get("params")
    if not isinstance(files, list) or not files:
        raise ValueError("Task manifest must contain an input alignment")
    if not isinstance(params, dict):
        raise ValueError("Task manifest must contain resolved EvoSplit parameters")
    paths = [Path(item["path"]).resolve() for item in files]
    if paths[0].suffix.lower() not in {".a3m", ".fasta", ".fa", ".fas"}:
        raise ValueError("The primary EvoSplit input must be an A3M or aligned FASTA file")
    references = paths[1:]
    if bool(params.get("supervised")):
        if len(references) != 2 or any(item.suffix.lower() not in {".pdb", ".cif"} for item in references):
            raise ValueError("Supervised EvoSplit requires exactly two PDB or mmCIF reference structures")
    elif references:
        raise ValueError("Reference structures require supervised mode")
    return paths[0], references, params


def _normalize_a3m(sequence: str) -> str:
    normalized = "".join(char for char in sequence if not char.islower() and char not in ".*").upper()
    if not normalized or set(normalized) - VALID_RESIDUES:
        raise ValueError("Alignment contains an empty sequence or unsupported residue symbols")
    return normalized


def read_alignment(path: Path, gap_cutoff: float) -> tuple[list[str], list[str], int]:
    names: list[str] = []
    sequences: list[str] = []
    header: str | None = None
    chunks: list[str] = []

    def append_record() -> None:
        if header is None:
            return
        sequence = _normalize_a3m("".join(chunks))
        if not sequences or sequence.count("-") / len(sequence) < gap_cutoff:
            if header not in names:
                names.append(header)
                sequences.append(sequence)

    with path.open(encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith(">"):
                append_record()
                header = line[1:].split()[0]
                if not header:
                    raise ValueError("Alignment contains a blank FASTA identifier")
                chunks = []
            elif header is None:
                raise ValueError("Alignment sequence data appears before its FASTA header")
            else:
                chunks.append(line)
    append_record()
    if len(sequences) < 3:
        raise ValueError("EvoSplit requires at least three retained alignment rows")
    widths = {len(sequence) for sequence in sequences}
    if len(widths) != 1:
        raise ValueError("All retained EvoSplit alignment rows must have equal match-state length")
    if sequences[0].count("-"):
        raise ValueError("The query alignment row must not contain gaps")
    return names, sequences, len(sequences)


def select_diverse(names: list[str], sequences: list[str], limit: int) -> tuple[list[str], list[str]]:
    if len(sequences) <= limit:
        return names, sequences
    selected = [0]
    remaining = set(range(1, len(sequences)))
    while len(selected) < limit:
        next_index = max(
            remaining,
            key=lambda candidate: (
                min(sum(a != b for a, b in zip(sequences[candidate], sequences[current])) for current in selected),
                -candidate,
            ),
        )
        selected.append(next_index)
        remaining.remove(next_index)
    return [names[index] for index in selected], [sequences[index] for index in selected]


def write_alignment(path: Path, names: list[str], sequences: list[str]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for name, sequence in zip(names, sequences):
            handle.write(f">{name}\n{sequence}\n")


def write_contact_plot(path: Path, contacts) -> None:
    import matplotlib.pyplot as plt

    figure, axis = plt.subplots(figsize=(5, 4))
    image = axis.imshow(contacts, origin="lower", cmap="Blues", vmin=0, vmax=1)
    axis.set_xlabel("Query residue position")
    axis.set_ylabel("Query residue position")
    figure.colorbar(image, ax=axis, label="Contact probability")
    figure.tight_layout()
    figure.savefig(path, dpi=160)
    plt.close(figure)


def _apc(values):
    row = values.sum(-1, keepdim=True)
    column = values.sum(-2, keepdim=True)
    total = values.sum((-1, -2), keepdim=True)
    return values - row * column / total.clamp_min(1e-12)


def extract_attention_features(results: dict[str, Any], alphabet: Any, top_l: float):
    import numpy as np
    import torch

    contacts = results["contacts"].float().cpu()[0]
    row_attention = results["row_attentions"].float().cpu()[:, -1]
    all_attention = results["row_attentions_all"].float().cpu()
    if alphabet.prepend_bos:
        row_attention = row_attention[..., 1:, 1:]
        all_attention = all_attention[:, 0, :, 1:, 1:]
    else:
        all_attention = all_attention[:, 0]
    length = contacts.shape[-1]
    diagonal_mask = torch.ones((length, length)) - torch.eye(length)
    row_attention = _apc(row_attention + row_attention.transpose(-1, -2)) * diagonal_mask
    all_attention = _apc(all_attention + all_attention.transpose(-1, -2)) * diagonal_mask
    aggregate = row_attention.sum(dim=(0, 1))
    keep = max(1, min(aggregate.numel(), math.floor(top_l * length)))
    threshold_indices = torch.topk(aggregate.flatten(), keep).indices
    mask = torch.zeros_like(aggregate).flatten()
    mask[threshold_indices] = 1
    mask = mask.reshape(length, length)
    weighted = torch.clamp_min(all_attention * mask, 0).sum(dim=1)
    upper = np.triu_indices(length, k=1)
    features = weighted.numpy()[:, upper[0], upper[1]]
    return contacts.numpy(), features, weighted.numpy()


def infer_features(names: list[str], sequences: list[str], model_path: Path, top_l: float):
    import torch
    from evosplit.esm import pretrained

    if not torch.cuda.is_available():
        raise RuntimeError("EvoSplit requires a CUDA accelerator")
    model, alphabet = pretrained.load_model_and_alphabet_local(str(model_path))
    converter = alphabet.get_batch_converter()
    _, _, tokens = converter(list(zip(names, sequences)))
    model = model.eval().cuda()
    with torch.no_grad():
        results = model(tokens.cuda(), repr_layers=[11], return_contacts=True, row_att_all=True)
    return extract_attention_features(results, alphabet, top_l)


def cluster(features, method: str, mean_cluster_size: int, epsilon: float, min_samples: int, seed: int):
    import numpy as np
    from sklearn.cluster import DBSCAN, KMeans

    samples = features[1:]
    if method == "kmeans":
        count = max(2, math.floor(len(features) / mean_cluster_size))
        count = min(count, len(samples))
        labels = KMeans(n_clusters=count, random_state=seed, n_init=10).fit_predict(samples)
    else:
        labels = DBSCAN(eps=epsilon, min_samples=min_samples).fit_predict(samples)
    clusters = sorted(int(value) for value in np.unique(labels) if value >= 0)
    if not clusters:
        raise ValueError("EvoSplit clustering produced no populated clusters; adjust clustering controls")
    return labels, clusters


def _structure_contacts(path: Path, chain_id: str, query: str, cutoff: float):
    import numpy as np
    from Bio.Align import PairwiseAligner
    from Bio.PDB import MMCIFParser, PDBParser

    parser = MMCIFParser(QUIET=True) if path.suffix.lower() == ".cif" else PDBParser(QUIET=True)
    model = parser.get_structure("reference", str(path))[0]
    chains = [model[chain_id]] if chain_id else list(model.get_chains())[:1]
    residues = [residue for chain in chains for residue in chain if residue.id[0] == " " and "CA" in residue]
    residue_names = {
        "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C", "GLN": "Q", "GLU": "E",
        "GLY": "G", "HIS": "H", "ILE": "I", "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F",
        "PRO": "P", "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
    }
    sequence = "".join(residue_names.get(residue.resname, "X") for residue in residues)
    if not sequence:
        raise ValueError(f"Reference structure has no protein residues: {path.name}")
    aligner = PairwiseAligner()
    aligner.mode = "global"
    aligner.match_score = 2
    aligner.mismatch_score = -1
    aligner.open_gap_score = -10
    aligner.extend_gap_score = -0.5
    alignment = aligner.align(query, sequence)[0]
    contacts = np.zeros((len(query), len(query)), dtype=np.float32)
    mapped: dict[int, int] = {}
    for query_index, structure_index in zip(*alignment.indices):
        if query_index >= 0 and structure_index >= 0:
            mapped[int(query_index)] = int(structure_index)
    for query_i, structure_i in mapped.items():
        residue_i = residues[structure_i]
        atom_i = residue_i["CB"] if residue_i.resname != "GLY" and "CB" in residue_i else residue_i["CA"]
        for query_j, structure_j in mapped.items():
            residue_j = residues[structure_j]
            atom_j = residue_j["CB"] if residue_j.resname != "GLY" and "CB" in residue_j else residue_j["CA"]
            contacts[query_i, query_j] = float(atom_i - atom_j) <= cutoff
    return contacts


def supervised_assignments(weighted, references: list[Path], params: dict[str, Any]):
    import numpy as np

    query = params.pop("_query")
    contact_maps = [
        _structure_contacts(
            references[index],
            str(params[f"reference_chain_{index + 1}"]),
            query,
            float(params["contact_cutoff"]),
        )
        for index in range(2)
    ]
    scores = np.column_stack(
        [(weighted * contacts).sum(axis=(1, 2)) / max(float(contacts.sum()), 1.0) for contacts in contact_maps]
    )
    return scores, np.argmax(scores, axis=1)


def run(task_manifest: Path, output_dir: Path, asset_root: Path, asset_manifest: Path) -> None:
    import numpy as np

    alignment_path, references, params = read_task_manifest(task_manifest)
    model_path, assets = validate_assets(asset_root, asset_manifest)
    names, sequences, input_depth = read_alignment(alignment_path, float(params["gap_cutoff"]))
    names, sequences = select_diverse(names, sequences, int(params["max_msa_depth"]))
    output_dir.mkdir(parents=True, exist_ok=True)
    write_alignment(output_dir / "processed_alignment.a3m", names, sequences)
    contacts, features, weighted = infer_features(names, sequences, model_path, float(params["top_l"]))
    labels, clusters = cluster(
        features,
        str(params["cluster_method"]),
        int(params["mean_cluster_size"]),
        float(params["dbscan_epsilon"]),
        int(params["dbscan_min_samples"]),
        int(params["seed"]),
    )

    cluster_dir = output_dir / "clusters"
    cluster_dir.mkdir()
    assignments = [-1, *(int(value) for value in labels)]
    for label in clusters:
        indices = [0, *(index + 1 for index, value in enumerate(labels) if int(value) == label)]
        write_alignment(
            cluster_dir / f"cluster_{label}.a3m",
            [names[index] for index in indices],
            [sequences[index] for index in indices],
        )

    supervised_scores = None
    if references:
        supervised_params = dict(params)
        supervised_params["_query"] = sequences[0]
        supervised_scores, supervised_labels = supervised_assignments(weighted, references, supervised_params)
        supervised_dir = output_dir / "supervised_clusters"
        supervised_dir.mkdir()
        for label in (0, 1):
            indices = sorted({0, *(index for index, value in enumerate(supervised_labels) if int(value) == label)})
            write_alignment(
                supervised_dir / f"reference_{label + 1}.a3m",
                [names[index] for index in indices],
                [sequences[index] for index in indices],
            )

    with (output_dir / "sequence_assignments.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["sequence_index", "sequence_id", "unsupervised_cluster", "reference_1_score", "reference_2_score"]
        )
        for index, (name, label) in enumerate(zip(names, assignments)):
            scores = (
                ("", "")
                if supervised_scores is None
                else tuple(f"{value:.8g}" for value in supervised_scores[index])
            )
            writer.writerow([index, name, "query" if index == 0 else label, *scores])
    np.savetxt(output_dir / "contact_probabilities.csv", contacts, delimiter=",", fmt="%.8g")
    write_contact_plot(output_dir / "contact_probabilities.png", contacts)
    shutil.copy2(asset_manifest, output_dir / "evosplit-model-assets.json")
    summary = {
        "upstream_commit": UPSTREAM_COMMIT,
        "model": MODEL_NAME,
        "input_alignment": alignment_path.name,
        "input_depth_after_gap_filter": input_depth,
        "analyzed_depth": len(sequences),
        "alignment_length": len(sequences[0]),
        "cluster_method": params["cluster_method"],
        "cluster_count": len(clusters),
        "unclustered_sequences": int(sum(int(value) < 0 for value in labels)),
        "supervised": bool(references),
        "asset_sha256": {record["path"]: record["sha256"] for record in assets["assets"]},
        "parameters": params,
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline EvoSplit MSA clustering")
    parser.add_argument("--task-manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--asset-root", required=True, type=Path)
    parser.add_argument("--asset-manifest", required=True, type=Path)
    args = parser.parse_args()
    run(args.task_manifest, args.output_dir, args.asset_root, args.asset_manifest)


if __name__ == "__main__":
    main()
