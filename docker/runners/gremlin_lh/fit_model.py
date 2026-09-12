# Copyright (C) 2024-2026 YaoYinYing
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

"""Headless transcription of the GREMLIN_LH notebook's reusable model-fitting path.

The upstream Beerware notice is retained in MODEL_AND_LICENSE.md. Interactive
paper-figure cells and network downloads are intentionally outside this task.
"""

import argparse
import csv
import json
import math
import string
from pathlib import Path
from typing import Any

import numpy as np


ALPHABET = "-ACDEFGHIKLMNPQRSTVWY"
GAP_INDEX = 0
UPSTREAM_COMMIT = "6b8a6beb426fd31bb10c3fdd398abd3355b782f9"


def _load_runtime_dependencies() -> None:
    """Load the SIF-owned numerical stack only for model fitting or plotting."""
    global jax, jnp, optax, plt
    if all(name in globals() for name in ("jax", "jnp", "optax", "plt")):
        return

    import jax as runtime_jax
    import jax.numpy as runtime_jnp
    import matplotlib as runtime_matplotlib
    import optax as runtime_optax

    runtime_matplotlib.use("Agg")
    import matplotlib.pyplot as runtime_plt

    jax = runtime_jax
    jnp = runtime_jnp
    optax = runtime_optax
    plt = runtime_plt


def parse_alignment(path: Path, a3m: bool = True) -> tuple[list[str], list[str]]:
    headers: list[str] = []
    sequences: list[list[str]] = []
    remove_insertions = str.maketrans("", "", string.ascii_lowercase + ".")
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(">"):
            header = line[1:].strip()
            if not header:
                raise ValueError(f"empty FASTA header at line {line_number}")
            headers.append(header)
            sequences.append([])
            continue
        if not sequences:
            raise ValueError("alignment must be FASTA/A3M with a header before sequence data")
        sequences[-1].append(line.translate(remove_insertions) if a3m else line.upper())

    aligned = ["".join(parts).upper() for parts in sequences]
    if len(aligned) < 2:
        raise ValueError("alignment must contain at least two sequences")
    if not aligned[0]:
        raise ValueError("alignment sequences cannot be empty")
    widths = {len(sequence) for sequence in aligned}
    if len(widths) != 1:
        raise ValueError(f"alignment rows have unequal widths: {sorted(widths)}")
    invalid = sorted(set("".join(aligned)) - set(ALPHABET))
    if invalid:
        raise ValueError(f"alignment contains unsupported residues: {''.join(invalid)}")
    if len(aligned[0]) > 512:
        raise ValueError("alignment width exceeds the production limit of 512 positions")
    return headers, aligned


def encode_alignment(sequences: list[str]) -> np.ndarray:
    residue_to_index = {residue: index for index, residue in enumerate(ALPHABET)}
    return np.asarray([[residue_to_index[residue] for residue in sequence] for sequence in sequences], dtype=np.int32)


def sequence_weights(one_hot: jax.Array, identity_cutoff: float, gap_cutoff: float) -> jax.Array:
    # Upstream placed '-' first in ALPHABET but indexed the final state as gap. Use
    # the explicit gap index here so the notebook's stated gap-cutoff semantics hold.
    nongap_columns = (jnp.mean(one_hot[:, :, GAP_INDEX], axis=0) < gap_cutoff).astype(jnp.float32)
    usable_positions = jnp.sum(nongap_columns)
    if float(usable_positions) == 0.0:
        raise ValueError("no alignment columns remain for sequence weighting at the requested gap cutoff")
    filtered = one_hot * nongap_columns[None, :, None]
    pairwise_identity = jnp.tensordot(filtered, filtered, axes=((1, 2), (1, 2))) / usable_positions
    return 1.0 / jnp.sum(pairwise_identity >= identity_cutoff, axis=-1)


def weighted_covariance(features: jax.Array, weights: jax.Array) -> jax.Array:
    denominator = jnp.sum(weights) - jnp.sqrt(jnp.mean(weights))
    mean = jnp.sum(features * weights[:, None], axis=0, keepdims=True) / denominator
    centered = (features - mean) * jnp.sqrt(weights[:, None])
    return centered.T @ centered / denominator


def inverse_covariance_initialization(one_hot: jax.Array, weights: jax.Array) -> jax.Array:
    rows, width, states = one_hot.shape
    features = jnp.reshape(one_hot, (rows, width * states))
    covariance = weighted_covariance(features, weights)
    covariance += (4.5 / jnp.sqrt(jnp.sum(weights))) * jnp.eye(width * states)
    return -jnp.reshape(jnp.linalg.inv(covariance), (width, states, width, states))


def normalize_couplings(couplings: jax.Array) -> jax.Array:
    width = couplings.shape[0]
    upper = jnp.ones((width, width)) - jnp.tril(jnp.ones((width, width)))
    couplings = couplings * upper[:, None, :, None]
    couplings = (couplings + couplings.transpose((2, 3, 0, 1))) / 2.0
    return couplings - jnp.mean(couplings, axis=(1, 3), keepdims=True)


def lh_penalty(couplings: jax.Array, exact: bool) -> jax.Array:
    raw = jnp.sqrt(jnp.sum(jnp.square(couplings), axis=(1, 3)) + 1e-8)
    if exact:
        dominant = jnp.linalg.eigvalsh(raw)[-1]
    else:
        vector = jnp.sum(raw, axis=0)
        dominant = jnp.einsum("i,ij,j->", vector, raw, vector) / (1e-8 + jnp.sum(jnp.square(vector)))
    return jnp.square(dominant) / 2.0


def regularization(
    couplings: jax.Array,
    neff: jax.Array,
    mode: str,
    lambda_l2: float,
    lambda_lh: float,
    lambda_lb: float,
    exact_lh_eigenvalue: bool,
) -> jax.Array:
    width, states = couplings.shape[:2]
    scale = width * states / jnp.sqrt(neff) / jnp.sqrt(1000.0)
    if mode == "L2":
        return 0.5 * lambda_l2 * jnp.sum(jnp.square(couplings)) * scale
    if mode == "LH":
        return 0.5 * lambda_lh * lh_penalty(couplings, exact_lh_eigenvalue) * scale
    block_norms = jnp.sqrt(jnp.sum(jnp.square(couplings), axis=(1, 3)) + 1e-8)
    return lambda_lb * jnp.sum(block_norms) * scale


def notebook_adam(learning_rate: float) -> optax.GradientTransformation:
    """Notebook optimizer: one scalar second moment per parameter tensor, no bias correction."""

    def initialize(params: dict[str, jax.Array]) -> tuple[Any, Any]:
        first = jax.tree_util.tree_map(jnp.zeros_like, params)
        second = jax.tree_util.tree_map(lambda value: jnp.zeros((), dtype=value.dtype), params)
        return first, second

    def update(updates: Any, state: tuple[Any, Any], params: Any = None) -> tuple[Any, tuple[Any, Any]]:
        del params
        first, second = state
        new_first = jax.tree_util.tree_map(lambda moment, gradient: 0.9 * moment + 0.1 * gradient, first, updates)
        new_second = jax.tree_util.tree_map(
            lambda moment, gradient: 0.999 * moment + 0.001 * jnp.sum(jnp.square(gradient)), second, updates
        )
        scaled = jax.tree_util.tree_map(
            lambda moment, variance: -learning_rate * moment / (jnp.sqrt(variance) + 1e-8), new_first, new_second
        )
        return scaled, (new_first, new_second)

    return optax.GradientTransformation(initialize, update)


def fit_model(
    encoded: np.ndarray,
    *,
    regularization_mode: str,
    lambda_l2: float,
    lambda_lh: float,
    lambda_lb: float,
    iterations: int,
    batch_size: int,
    learning_rate: float,
    identity_cutoff: float,
    gap_cutoff: float,
    use_bias: bool,
    inverse_covariance_init: bool,
    exact_lh_eigenvalue: bool,
    seed: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[dict[str, float]]]:
    _load_runtime_dependencies()
    rows, width = encoded.shape
    batch_size = min(batch_size, rows)
    one_hot = jax.nn.one_hot(jnp.asarray(encoded), num_classes=len(ALPHABET))
    weights = sequence_weights(one_hot, identity_cutoff, gap_cutoff)
    neff = jnp.sum(weights)
    # The notebook's log(Neff) expression becomes zero for duplicate-only
    # alignments. Keep the prior scale while ensuring absent residues retain a
    # finite field value at the valid Neff == 1 boundary.
    pseudocount = jnp.maximum(0.01 * jnp.log(neff), jnp.finfo(one_hot.dtype).eps)
    fields = jnp.log(jnp.sum(one_hot.transpose((1, 0, 2)) * weights[None, :, None], axis=1) + pseudocount)
    fields -= jnp.mean(fields, axis=-1, keepdims=True)
    if not use_bias:
        fields = jnp.zeros((width, len(ALPHABET)), dtype=jnp.float32)
    if inverse_covariance_init:
        couplings = inverse_covariance_initialization(one_hot, weights)
    else:
        couplings = jnp.zeros((width, len(ALPHABET), width, len(ALPHABET)), dtype=jnp.float32)

    params: dict[str, jax.Array] = {"w": couplings}
    if use_bias:
        params["b"] = fields

    def loss_fn(current: dict[str, jax.Array], batch: jax.Array, batch_weights: jax.Array) -> tuple[jax.Array, jax.Array]:
        normalized = normalize_couplings(current["w"])
        logits = jnp.einsum("ijk,jklm->ilm", batch, normalized)
        if use_bias:
            logits += current["b"]
        predictions = jax.nn.softmax(logits, axis=-1)
        cross_entropy = -jnp.sum(batch * jnp.log(predictions + 1e-9), axis=-1)
        data_loss = jnp.sum(jnp.sum(cross_entropy, axis=-1) * batch_weights) / jnp.sum(batch_weights)
        reg = regularization(
            normalized, neff, regularization_mode, lambda_l2, lambda_lh, lambda_lb, exact_lh_eigenvalue
        )
        if use_bias:
            # The notebook uses integer floor division here; ordinary division
            # preserves its evident intended L2 field penalty.
            reg += 0.5 * lambda_l2 * jnp.sum(jnp.square(current["b"])) * width * len(ALPHABET) / jnp.sqrt(
                neff
            ) / jnp.sqrt(1000.0)
        return data_loss + reg, reg

    compiled_loss = jax.jit(loss_fn)
    optimizer = notebook_adam(learning_rate)
    opt_state = optimizer.init(params)
    rng = np.random.default_rng(seed)
    history: list[dict[str, float]] = []
    history_stride = max(1, iterations // 20)

    for iteration in range(1, iterations + 1):
        indices = rng.choice(rows, size=batch_size, replace=False)
        batch = one_hot[indices]
        batch_weights = weights[indices]
        (_, _), gradients = jax.value_and_grad(compiled_loss, has_aux=True)(params, batch, batch_weights)
        updates, opt_state = optimizer.update(gradients, opt_state, params)
        params = optax.apply_updates(params, updates)
        if iteration == 1 or iteration == iterations or iteration % history_stride == 0:
            total, reg = compiled_loss(params, one_hot, weights)
            history.append(
                {"iteration": iteration, "loss": float(total), "regularization": float(reg), "data_loss": float(total - reg)}
            )

    final_fields = params.get("b", fields)
    final_couplings = normalize_couplings(params["w"])
    return (
        np.asarray(final_fields),
        np.asarray(final_couplings),
        np.asarray(weights),
        history,
    )


def coupling_scores(couplings: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    raw = np.sqrt(np.sum(np.square(couplings), axis=(1, 3)) + 1e-8)
    np.fill_diagonal(raw, 0.0)
    total = float(np.sum(raw))
    if total == 0.0:
        apc = raw.copy()
    else:
        apc = raw - np.sum(raw, axis=0, keepdims=True) * np.sum(raw, axis=1, keepdims=True) / total
    np.fill_diagonal(apc, 0.0)
    return raw, apc


def sequence_statistics(encoded: np.ndarray, fields: np.ndarray, couplings: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    one_hot = np.eye(len(ALPHABET), dtype=np.float32)[encoded]
    logits = np.einsum("njk,jklm->nlm", one_hot, couplings) + fields
    logits -= np.max(logits, axis=-1, keepdims=True)
    probabilities = np.exp(logits)
    probabilities /= np.sum(probabilities, axis=-1, keepdims=True)
    pseudo_loss = np.sum(-np.sum(one_hot * np.log(probabilities + 1e-8), axis=-1), axis=-1)
    hamiltonian = -np.sum(one_hot * (np.einsum("njk,jklm->nlm", one_hot, couplings) + fields), axis=(1, 2))
    return pseudo_loss, hamiltonian


def write_matrix(path: Path, matrix: np.ndarray) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["position", *range(1, matrix.shape[1] + 1)])
        for index, row in enumerate(matrix, start=1):
            writer.writerow([index, *(f"{float(value):.8g}" for value in row)])


def query_position_map(query: str) -> list[int | None]:
    position = 0
    mapping: list[int | None] = []
    for residue in query:
        if residue == "-":
            mapping.append(None)
        else:
            position += 1
            mapping.append(position)
    return mapping


def write_results(
    output_dir: Path,
    headers: list[str],
    sequences: list[str],
    fields: np.ndarray,
    couplings: np.ndarray,
    weights: np.ndarray,
    history: list[dict[str, float]],
    parameters: dict[str, Any],
) -> None:
    _load_runtime_dependencies()
    output_dir.mkdir(parents=True, exist_ok=True)
    raw, apc = coupling_scores(couplings)
    pseudo_loss, hamiltonian = sequence_statistics(encode_alignment(sequences), fields, couplings)
    query_map = query_position_map(sequences[0])

    np.savez_compressed(
        output_dir / "potts_model.npz",
        fields=fields,
        couplings=couplings,
        alphabet=np.asarray(list(ALPHABET)),
        sequence_weights=weights,
    )
    write_matrix(output_dir / "coupling_raw.csv", raw)
    write_matrix(output_dir / "coupling_apc.csv", apc)

    with (output_dir / "coupling_pairs.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["alignment_i", "alignment_j", "query_i", "query_j", "query_residue_i", "query_residue_j", "raw_score", "apc_score"],
        )
        writer.writeheader()
        pairs = [(i, j) for i in range(len(query_map)) for j in range(i + 1, len(query_map))]
        for i, j in sorted(pairs, key=lambda pair: float(apc[pair]), reverse=True):
            writer.writerow(
                {
                    "alignment_i": i + 1,
                    "alignment_j": j + 1,
                    "query_i": query_map[i] or "",
                    "query_j": query_map[j] or "",
                    "query_residue_i": sequences[0][i],
                    "query_residue_j": sequences[0][j],
                    "raw_score": f"{float(raw[i, j]):.8g}",
                    "apc_score": f"{float(apc[i, j]):.8g}",
                }
            )

    pssm = np.mean(np.eye(len(ALPHABET), dtype=np.float32)[encode_alignment(sequences)], axis=0)
    with (output_dir / "position_frequencies.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["alignment_position", "query_position", "query_residue", *list(ALPHABET)])
        for index, row in enumerate(pssm):
            writer.writerow([index + 1, query_map[index] or "", sequences[0][index], *(f"{float(value):.8g}" for value in row)])

    with (output_dir / "sequence_scores.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["row", "header", "sequence_weight", "pseudo_likelihood_loss", "hamiltonian"])
        for index, header in enumerate(headers):
            writer.writerow([index + 1, header, f"{float(weights[index]):.8g}", f"{float(pseudo_loss[index]):.8g}", f"{float(hamiltonian[index]):.8g}"])

    with (output_dir / "training_history.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["iteration", "loss", "data_loss", "regularization"])
        writer.writeheader()
        writer.writerows(history)

    with (output_dir / "normalized_alignment.fasta").open("w", encoding="utf-8") as handle:
        for header, sequence in zip(headers, sequences, strict=True):
            handle.write(f">{header}\n{sequence}\n")

    summary = {
        "schema_version": 1,
        "method": "GREMLIN_LH",
        "upstream": {
            "repository": "https://github.com/sokrypton/GREMLIN_LH",
            "commit": UPSTREAM_COMMIT,
            "notebook": "GREMLIN_LH_outline_7.ipynb",
        },
        "alignment": {
            "sequence_count": len(sequences),
            "length": len(sequences[0]),
            "effective_sequence_count": float(np.sum(weights)),
            "alphabet": ALPHABET,
            "query_header": headers[0],
            "query_sequence": sequences[0],
        },
        "optimization": {
            "iterations": parameters["iterations"],
            "final_loss": history[-1]["loss"],
            "final_data_loss": history[-1]["data_loss"],
            "final_regularization": history[-1]["regularization"],
        },
        "parameters": parameters,
        "artifacts": {
            "potts_model": "potts_model.npz",
            "raw_matrix": "coupling_raw.csv",
            "apc_matrix": "coupling_apc.csv",
            "ranked_pairs": "coupling_pairs.csv",
            "position_frequencies": "position_frequencies.csv",
            "sequence_scores": "sequence_scores.csv",
            "training_history": "training_history.csv",
            "heatmap": "coupling_apc.png",
        },
        "citations": [
            {"doi": "10.1103/PRXLife.2.023005", "role": "GREMLIN_LH method"},
            {"doi": "10.1073/pnas.1314045110", "role": "GREMLIN coevolution model"},
        ],
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    figure, axis = plt.subplots(figsize=(6, 5), constrained_layout=True)
    image = axis.imshow(apc, cmap="coolwarm", origin="lower")
    axis.set_xlabel("Alignment position (one-based)")
    axis.set_ylabel("Alignment position (one-based)")
    axis.set_title("GREMLIN_LH APC-corrected coupling strength")
    figure.colorbar(image, ax=axis, label="APC score")
    figure.savefig(output_dir / "coupling_apc.png", dpi=180)
    plt.close(figure)


def parse_bool(value: str) -> bool:
    normalized = value.lower()
    if normalized not in {"true", "false"}:
        raise argparse.ArgumentTypeError("expected true or false")
    return normalized == "true"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--regularization", choices=("L2", "LH", "LB"), default="LH")
    parser.add_argument("--lambda-l2", type=float, default=0.01)
    parser.add_argument("--lambda-lh", type=float, default=0.1)
    parser.add_argument("--lambda-lb", type=float, default=0.005)
    parser.add_argument("--iterations", type=int, default=400)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--learning-rate", type=float, default=1.0)
    parser.add_argument("--identity-cutoff", type=float, default=0.8)
    parser.add_argument("--gap-cutoff", type=float, default=0.5)
    parser.add_argument("--use-bias", type=parse_bool, default=True)
    parser.add_argument("--inverse-covariance-init", type=parse_bool, default=False)
    parser.add_argument("--exact-lh-eigenvalue", type=parse_bool, default=False)
    parser.add_argument("--a3m", type=parse_bool, default=True)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    parameters = {
        "regularization": args.regularization,
        "lambda_l2": args.lambda_l2,
        "lambda_lh": args.lambda_lh,
        "lambda_lb": args.lambda_lb,
        "iterations": args.iterations,
        "batch_size": args.batch_size,
        "learning_rate": args.learning_rate,
        "identity_cutoff": args.identity_cutoff,
        "gap_cutoff": args.gap_cutoff,
        "use_bias": args.use_bias,
        "inverse_covariance_init": args.inverse_covariance_init,
        "exact_lh_eigenvalue": args.exact_lh_eigenvalue,
        "a3m": args.a3m,
        "seed": args.seed,
    }
    headers, sequences = parse_alignment(args.input, args.a3m)
    fields, couplings, weights, history = fit_model(
        encode_alignment(sequences),
        regularization_mode=args.regularization,
        lambda_l2=args.lambda_l2,
        lambda_lh=args.lambda_lh,
        lambda_lb=args.lambda_lb,
        iterations=args.iterations,
        batch_size=args.batch_size,
        learning_rate=args.learning_rate,
        identity_cutoff=args.identity_cutoff,
        gap_cutoff=args.gap_cutoff,
        use_bias=args.use_bias,
        inverse_covariance_init=args.inverse_covariance_init,
        exact_lh_eigenvalue=args.exact_lh_eigenvalue,
        seed=args.seed,
    )
    if not all(np.all(np.isfinite(array)) for array in (fields, couplings, weights)):
        raise RuntimeError("optimization produced non-finite model values")
    write_results(args.output_dir, headers, sequences, fields, couplings, weights, history, parameters)


if __name__ == "__main__":
    main()
