# GREMLIN_LH scientific traceability

This is the audit trail for the GREMLIN_LH Runner: every scientifically
meaningful operation is tied to its literature position, its exact line in the
pinned upstream notebook, this Runner's implementation, the durable artifact it
produces, the result view that presents it, and the test that would catch a
regression. It also records every current difference from upstream and how that
difference is classified.

It deliberately does **not** restate parameter defaults or help text: the owning
`tasks/gremlin_lh_fit/task.yaml` is the sole authority for those, and
`tests/data/gremlin_lh/upstream_reference.json` is the frozen numerical receipt.

## 1. Sources

| Source | Identity |
| --- | --- |
| Method paper | Wang H., Feng S., Tsuboyama K., Liu S., Rocklin G. J., Ovchinnikov S., *Disentanglement of Evolutionary Constraints in Statistical Models of Proteins*, PRX Life **2**, 023005 (2024). DOI 10.1103/PRXLife.2.023005 |
| Model lineage | Kamisetty H., Ovchinnikov S., Baker D., PNAS **110**, 15674–15679 (2013). DOI 10.1073/pnas.1314045110 |
| Correction | Correction for Kamisetty et al., PNAS **110**, 18734 (2013). DOI 10.1073/pnas.1319550110 |
| Upstream code | <https://github.com/sokrypton/GREMLIN_LH> |
| Pinned commit | `6b8a6beb426fd31bb10c3fdd398abd3355b782f9` (recorded at intake; no tags or releases) |
| Pinned notebook | `GREMLIN_LH_outline_7.ipynb`, git blob `79cc0fdaba25ff1a6d6cb12ab2a2ebc8358c2c17`, SHA-256 `7f4638aeb835689717a7b497d182cee3bac24128add71a3a7c1c542ddc50c3dc` |
| License | Beerware notice embedded in notebook cell 2, reproduced in `MODEL_AND_LICENSE.md`. No repository-level license file at the pinned revision |

Notebook cells are cited by index in the pinned blob. The indices used below are:
cell 2 (license), cell 7 (`parse_fasta`, `parse_aln`, `alphabet`, `mk_msa`),
cell 8 (`get_mtx`, `get_pssm`, `get_pair_pssm`), cell 11 (`jax_cov`,
`jax_weights`, `jax_apc`, `jax_inv_cov`, `reg_LH`, `compute_loss*`,
`compute_reg`, `custom_adam`), cell 13 (`GREMLIN`), cell 14
(`get_Hamiltonian_loss`, `get_Hamiltonian`); cells 23 and 59 are figure cells
used only for the arguments cited.

## 2. Traceability table

| Scientific concept | Literature position | Notebook implementation | REvoCompute implementation | Durable artifact | ResultManifest / ResultView | Acceptance test |
| --- | --- | --- | --- | --- | --- | --- |
| Alignment parsing (match-state rows; A3M insertions removed, deletion gaps kept) | PNAS Methods "HHsuite": alignment filtered before fitting | cell 7 `parse_fasta(..., a3m=True)` strips lowercase letters only | `fit_model.parse_alignment` (strips `ascii_lowercase` + `.`) | `query.fasta`, `alignment/filtered_alignment.a3m` | view `filtered_alignment`; role `evidence` | `test_runner.py::test_alignment_parser_removes_a3m_insertions_and_preserves_gap`, `::test_alignment_parser_removes_a3m_insertion_dots` |
| Alphabet and state order (gap first, K = 21) | Fig. 1 caption: "K is the number of amino acids plus an aligned gap" | cell 7 `alphabet = "-ACDEFGHIKLMNPQRSTVWY"`; a commented-out `"ARNDCQEGHILKMFPSTWYV-"` keeps the gap last | `fit_model.ALPHABET` | `model/gremlin_mrf.npz` `alphabet`; `model/metadata.json` `alphabet` | MRF is on disk, not a view | `test_runner.py::test_smoke_run_preserves_the_durable_mrf_model` |
| Gap state identity | — | cell 7 places gap first; cell 11 indexes `x_msa[:, :, -1]` (see deviation D1) | `fit_model.GAP_INDEX = 0` | npz `gap_index`; `metadata.json` `gap_index`, `arrays.alphabet.description` | — | same as above; `test_upstream_equivalence.py::test_receipt_records_the_documented_deviations` |
| Sequence identity weighting | PNAS Methods "Sequence Reweighting"; PRX Life §II.A | cell 11 `jax_weights(x_msa, w_lam=0.8, gap_cutoff=0.5)`: mask columns with mean gap plane < cutoff, pairwise identity over usable columns, `1/sum(identity >= w_lam)` | `fit_model.sequence_weights` | `alignment/sequence_weights.tsv`; npz `sequence_weights` | storyboard section 2 | `test_upstream_equivalence.py::test_upstream_compatible_weights_and_neff_match_reference` (exact in practice) |
| Gap-cutoff bookkeeping (which columns the weighting dropped) | paper lineage: columns with heavy gaps are filtered before fitting (PNAS Methods "HHsuite") | cell 11 masks columns with `mean(gap plane) < gap_cutoff`; the notebook emits no statistics file | `fit_model.write_alignment_artifacts` (`columns_excluded_by_gap_cutoff`) | `alignment/statistics.json` | view `fit_summary` field "Columns excluded from weighting" | `test_runner.py::test_smoke_run_summary_is_internally_consistent`; equivalence receipt |
| Effective sequence count Neff | PRX Life §II.C and Methods B: hyperparameter scales with "the inverse of the square root of effective sequences" | cell 13 `neff = jnp.sum(msa_weights)` | `fit_model.fit_model` (`neff = jnp.sum(weights)`) | `alignment/statistics.json` `effective_sequence_count` | view `fit_summary` field "Effective rows" | equivalence weights/Neff test |
| One-hot encoding | PRX Life §II.A "characters … are one-hot encoded" | cell 7 `mk_msa` / cell 13 `jax.nn.one_hot(msa, num_classes=states)` | `fit_model.encode_alignment` + `jax.nn.one_hot` | npz `couplings`/`fields` implicitly | — | `test_runner.py::test_smoke_run_preserves_the_durable_mrf_model` |
| One-body fields (conservation/entropy term `b`, L×K) | PRX Life §II.A: `H = b_lk + Σ X W`; Fig. 1 caption: L×K "capturing conservation and positional entropy" | cell 13 `initialize_bias`: `pc = 0.01*log(neff)`, `b = log(Σ_n weights·X + pc)`, mean-centered over states | `fit_model.fit_model` (field init) | npz `fields`; `model/metadata.json` `arrays.fields` | MRF via Files & diagnostics / storyboard | `test_upstream_equivalence.py::test_upstream_compatible_fields_and_couplings_match_reference` |
| Pairwise couplings (two-body term `W`, L×K×L×K) | PRX Life §II.A; Eq. (2) | cell 13 `initialize_weights` + `symmetrize_and_normalize` | `fit_model.inverse_covariance_initialization`, `normalize_couplings` | npz `couplings`; `metadata.json` `arrays.couplings` | MRF | equivalence fields/couplings test (blocks, L2 norm, max abs) |
| Pseudo-likelihood objective | PRX Life Eq. (1); PNAS Methods "The GREMLIN Learning Algorithm" | cell 11 `compute_loss_bias`: per-row categorical cross-entropy of the softmax over states, weighted by `msa_weights/neff` | `fit_model.fit_model.loss_fn` | `model/training_history.csv` (`data_loss`); `model/metadata.json` `method` | diagnostic | `test_runner.py::test_smoke_run_produces_the_declared_artifact_tree` |
| Coupling initialization (regularized inverse covariance + λI) | DCA/PSICOV inverse-covariance lineage, PNAS Results | cell 11 `jax_inv_cov(lam_w=4.5)`; cell 13 `Inv_init=True` default | `fit_model.inverse_covariance_initialization` | initial state only; post-fit couplings in npz | parameter echoed in `summary.json`/`metadata.json` | equivalence receipt uses the upstream-compatible setting (`inverse_covariance_init: true`) |
| Optimizer | PRX Life Methods C: "the Adam optimizer is employed" | cell 11 `custom_adam(b1=.9, b2=.999, eps=1e-8, b_fix=False)` — one scalar second moment per tensor, no bias correction | `fit_model.notebook_adam` | `model/training_history.csv` | diagnostic | `test_runner.py::test_smoke_run_summary_is_internally_consistent`, equivalence receipt |
| L2 / LH / LB coupling penalties | PRX Life §II.B/C, Eqs. (6)–(8), Methods B | cell 11 `compute_reg_L2/LH/LB`, each scaled by `L·K/√Neff/√1000` | `fit_model.regularization` | `training_history.csv` `regularization`; `summary.json` `model.regularization` | `fit_summary` "Final loss" | `test_runner.py::test_smoke_run_summary_is_internally_consistent` |
| LH spectral term (dominant eigenmode of the raw matrix) | PRX Life §II.C: `LH = ½γλ₁²`; Eq. (5) `λ₁ ≈ pMpᵀ/ppᵀ`; Eq. (6) | cell 11 `reg_LH(w, power_iter=True)`: `raw = √(Σ W² + 1e-8)`, power-iteration estimate by default, `eigvalsh` when disabled, then `λ²/2` | `fit_model.lh_penalty(couplings, exact)` | `training_history.csv` | parameter `exact_lh_eigenvalue` in `summary.json` | equivalence receipt (`exact_lh_eigenvalue: false`) |
| Gauge: upper-triangle masking, symmetrization, mean centering | — | cell 13 `symmetrize_and_normalize` (mask strictly upper, symmetrize, subtract mean over axes (1,3)) | `fit_model.normalize_couplings` | npz `couplings` | MRF | equivalence blocks test |
| Raw Frobenius coupling matrix `M` | PRX Life Eq. (2) `M_ij = √(Σ_ab W_ia,jb²)`; body text §I: the tensor is "reduced to an `L×L` matrix by taking the norm of each `K×K` matrix" (the Fig. 1 caption only says "condensed") | cell 8 `get_mtx`: `raw = √(Σ W²)`, diagonal zeroed, APC over the raw matrix | `fit_model.coupling_scores` | `couplings/raw_scores.csv` | **view `raw_couplings` (primary)** | `test_runner.py::test_coupling_scores_reproduce_the_upstream_apc_definition`; equivalence raw-matrix test |
| APC-corrected matrix `C` | PRX Life Eq. (3) `C = M − pᵀp/Σpᵢ`; Eq. (4) `C ≈ M − λ₁v₁ᵀv₁`; PNAS Methods "Entropy Correction via APC" | cell 8 `get_mtx` `ap`; cell 11 `jax_apc` (adds `1e-8` under the sqrt) | `fit_model.coupling_scores` | `couplings/apc_scores.csv` | **view `apc_couplings` (evidence, comparison)** | same two tests; equivalence APC test |
| Dominant eigenmode / share of first mode | PRX Life §II.B, Eq. (4), §II.C, Fig. S1C (≈90 % of `M` at 20 000 sequences dominated by the first mode) | cell 23 `get_first_eig`; cell 24 records it per training fraction | **not implemented** — a paper-analysis quantity, not a model output | — | — | — (documented as out of scope) |
| Hamiltonian `H` (statistical MRF energy) | PRX Life §II.A `H_nlk = b_lk + Σ X W`, Methods; PNAS Eq. (2) | cell 14 `get_Hamiltonian_loss(..., return_H=True)`: `H = −Σ msa·VW` | `fit_model.sequence_statistics` (`hamiltonian`) | `model/sequence_scores.tsv` | storyboard "per-sequence scores" | `test_upstream_equivalence.py::test_upstream_compatible_sequence_scores_match_reference` |
| Per-sequence pseudo-likelihood loss | PRX Life Eq. (1) | cell 14 `get_Hamiltonian_loss` (default) | `fit_model.sequence_statistics` (`pseudo_loss`) | `model/sequence_scores.tsv` | storyboard | same test |
| Per-position state frequencies (profile) | — | cell 8 `get_pssm`; cell 11 `get_H` computes per-position frequencies for entropy | `fit_model.write_profile_artifacts` | `profiles/profile.tsv` | storyboard section 3 | `test_runner.py::test_smoke_run_profile_and_couplings_have_correct_indexing` |
| Ranked residue pairs | PNAS Results: predictions "ranked … based on these values"; Methods "Entropy Correction via APC" | notebook ranks by score only inside figure helpers (`get_acc`, cells 15/59) | `fit_model.write_coupling_artifacts` (upper triangle sorted by APC score, raw score alongside) | `couplings/pairwise_scores.tsv` | view `ranked_pairs` (entity-table) | `test_runner.py::test_smoke_run_profile_and_couplings_have_correct_indexing` |

## 3. Deviation register

Every current difference between the pinned notebook and this Runner. The
classification vocabulary is fixed: `EXACT_TRANSCRIPTION`, `EXPLICIT_CORRECTION`,
`RUNTIME_ADAPTATION`, `PRODUCTION_DEFAULT`, `NUMERICAL_GUARD`,
`SCIENTIFIC_DEVIATION`, `UNKNOWN`.

### D1 — Explicit gap state in sequence weighting — `EXPLICIT_CORRECTION`

- Notebook (cell 11): `x_nongap = (jnp.mean(x_msa[:, :, -1], axis=0) < gap_cutoff).astype(jnp.float32)`
- Runner (`fit_model.sequence_weights`): `nongap_columns = (jnp.mean(one_hot[:, :, GAP_INDEX], axis=0) < gap_cutoff)…` with `GAP_INDEX = 0`.
- Why: cell 7 defines `alphabet = "-ACDEFGHIKLMNPQRSTVWY"` (gap first) and its own commented-out predecessor `"ARNDCQEGHILKMFPSTWYV-"` (gap last). Index `-1` was correct under the gap-last alphabet and is stale after the switch: with the current alphabet, plane `-1` is **tyrosine**, so the notebook masks columns by tyrosine frequency while the parameter is named `gap_cutoff` and the function's docstring says gap. The Runner's named `GAP_INDEX` restores the stated semantics.
- Literature position: the papers do not specify this routine; PRX Life §II.A only states that the alignment is the input to the MRF. The papers therefore cannot arbitrate the index — the notebook's naming and its own prior alphabet variant do.
- Evidence of impact: on the 2KL8 reference case the correction changes Neff from 3.3333 to 2.8667 and changes sequence weights, which changes the fitted model. The receipt keeps the uncorrected values in `pinned_uncorrected`.
- Honest limit: the *author's intent* is inferred from the parameter name, the docstring, and the stale-alphabet history; the notebook never states which plane it means in a comment. The inference is strong but is an inference.

### D2 — Ordinary division in the field L2 penalty — `EXPLICIT_CORRECTION`

- Notebook (cell 11, `compute_loss_bias`): `reg_b = 0.5 * lambda_L2 * jnp.sum(jnp.square(params['b'])) * n_total * states // jnp.sqrt(neff) / jnp.sqrt(1000)`.
- Runner (`fit_model.fit_model.loss_fn`): the same expression with `/` throughout.
- Why the division is the intended formula: every sibling penalty in the same cell (`compute_reg_L2/LH/LB` and this function's own coupling term) divides by `sqrt(neff)·sqrt(1000)`. PNAS Methods "Regularization and Priors" describes an L2/Gaussian prior with a scalar weight `λ`; it says nothing about a floor.
- What the floor actually does. Operator precedence makes `//` the *second* operation, so it applies to the whole data-dependent product `0.5·λ·Σb²·L·K` — not to the factor `L·K/√Neff/√1000`:
  `0.5·λ·Σb²·L·K // √Neff / √1000`.
  At the reference state (`L = 79`, `K = 21`, `Neff = 2.8666668`, `Σb² ≈ 3.0 × 10³`) the product is ≈ 2.51 × 10⁴, so the floored quantity is 14797 and the resulting penalty factor is 30.9587, against the exact 30.9854 — a ratio of 0.99914, i.e. the two forms differ by under 0.1 %. (A quoted "30.985 becomes 30" is wrong: nothing rounds the factor to an integer.)
- The mechanism that makes this a *correction* rather than a rounding tidy-up. Because the floor is applied to a traced, data-dependent quantity, the notebook's `reg_b` is piecewise constant in `b`, so `∂reg_b/∂b ≡ 0` wherever `b` sits inside a integer cell of the product. At the reference state (both at the initialized fields and at the fitted fields) the notebook's field L2 penalty therefore contributes **no gradient at all**: the term exists in the loss value but is inert, and `reg_L2` in that function regularizes only the couplings. Restoring ordinary division restores a smooth, non-zero gradient (`max|∂reg_b/∂b| ≈ 1.66` at the initialized fields). The one-body fields then no longer need to be pinned by the coupling loss alone: turning the correction on with the gap plane fixed changes the fitted fields by up to 9.2 in the reference case — a leading-order change in the model, and the direct consequence of a regularization term the notebook contributes nothing to.
- Evidence of impact (measured on the 2KL8 case, each variant run through the
  checked-in transcription of the notebook's own code, reference seed 0):
  | variant | Neff | ΣW² | max abs field |
  | --- | --- | --- | --- |
  | both corrections (expected) | 2.8667 | 155.78 | 0.33 |
  | no corrections (pinned) | 3.3333 | 70.29 | 9.46 |
  | gap plane only (D1 only) | 2.8667 | 63.20 | 9.39 |
  | ordinary division only (D2 only) | 3.3333 | 167.52 | 0.38 |
  The field magnitude column isolates the effect: D2 alone collapses the field scale from 9.46 to 0.38, while D1 alone leaves it at 9.39. Applying D2 alone moves the fitted fields by up to 9.2 and the coupling tensor by up to 0.91 relative to the pinned fit; D1 alone moves them by 0.32 and 0.12. D2 is the dominant deviation on this case.
- Literature position: as above — the sibling terms and the PNAS prior definition support ordinary division; neither paper defines an integer floor.
- Classification justification: `EXPLICIT_CORRECTION`. The intended formula is stated by the sibling terms and the literature's regularization definition; the correction restores a penalty term the notebook's floor renders gradient-free; and the uncorrected values stay visible in the receipt's `pinned_uncorrected` section rather than being silently absorbed (see D16 for what that section does and does not isolate).

### D3 — Coupling initialization: zero vs regularized inverse covariance — `PRODUCTION_DEFAULT`

- Notebook: cell 13 `GREMLIN(..., Inv_init=True)` — the regularized inverse covariance, `jax_inv_cov(msa, msa_weights, lam_w=4.5)`.
- Runner: `inverse_covariance_init` defaults to `false` (zeros) and the upstream initialization is exposed as a Task parameter.
- Why: the notebook's `jax_inv_cov` inverts an `L·K × L·K` matrix (at the 512-position production width that is 10 752² ≈ 1.16 × 10⁸ entries — gigabytes) before the first optimizer step. Zero initialization keeps the default profile inside a bounded time/memory envelope. The scientific acceptance test runs the upstream-compatible setting, so the upstream path stays exercised.
- Literature: the papers do not prescribe the initialization; DCA/PSICOV use the inverse covariance as the *estimator*, while GREMLIN's own objective is pseudolikelihood optimization, so initialization is an optimization choice, not a model definition.
- Consequence, stated honestly: this is a genuinely different starting point and can reach a different optimum at the same iteration count. Both ends are recorded: `summary.json` echoes the effective value, and the equivalence receipt pins `inverse_covariance_init: true`.
- Related exactness: the Runner's `inverse_covariance_initialization` is a literal transcription (`denominator = Σw − √mean(w)`, `+ (4.5/√Σw)·I`, `−reshape(inv)`), so with the flag enabled the upstream path is exact apart from float ordering.

### D4 — Mini-batch clamping — `RUNTIME_ADAPTATION`

- Notebook (cell 13): `idx = np.random.choice(nrow, size=batch_size, replace=False)` — raises when `batch_size > nrow`.
- Runner: `batch_size = min(batch_size, rows)`.
- Why: a server Task must fit a small alignment with every row rather than fail on a sampling detail. At or below the row count the behaviour is identical to the notebook.
- Literature: silent.

### D5 — Field pseudocount floor — `NUMERICAL_GUARD`

- Notebook (cell 13, `initialize_bias`): `pc = 0.01 * jnp.log(neff)`; with a duplicate-only alignment `neff = 1` and `pc = 0`.
- Runner: `pseudocount = jnp.maximum(0.01 * jnp.log(neff), finfo(dtype).eps)`.
- Why: keeps the field log finite at the `Neff == 1` boundary the Runner explicitly admits (it clamps the batch instead of failing). At `Neff` large enough for the log to dominate, the two agree exactly.
- Literature: silent. Tested by `test_runner.py::test_identical_alignment_rows_produce_finite_model_values`.

### D6 — Deterministic seed and a different NumPy RNG — `RUNTIME_ADAPTATION`

- Notebook (cell 13): the global legacy NumPy RNG (`np.random.choice`), unseeded unless the caller seeds it.
- Runner: `np.random.default_rng(seed)` (PCG64) with a declared `seed` parameter.
- Why: reproducibility is a platform requirement. This is not merely "the same draws with a fixed seed": the legacy `RandomState` and `default_rng` are different algorithms, so they take a different row ordering for the same seed. Because the receipt uses full-batch sampling (batch = row count), the reference is independent of the ordering and the two agree to the documented tolerance; for sub-batch runs the trajectories legitimately differ. The generator's provenance note records this explicitly.
- Literature: silent.

### D7 — Configurable weighting thresholds — `RUNTIME_ADAPTATION` (parameterization)

- Notebook (cell 13): `jax_weights` is called with its own defaults `w_lam=0.8`, `gap_cutoff=0.5`, and any caller-supplied `msa_weights` is ignored.
- Runner: `identity_cutoff` (the notebook's `w_lam`) and `gap_cutoff` are Task parameters and are always passed through; weights are likewise recomputed internally from the one-hot MSA. The upstream values remain the defaults, so default behaviour matches.
- Literature: PNAS Methods describes 90 %-identity filtering of the alignment upstream of GREMLIN; PRX Life does not specify the weighting threshold. Neither paper fixes the constant, so exposing it is a platform decision, not a scientific one.

### D8 — Approximate vs exact LH eigenvalue — `PRODUCTION_DEFAULT` (exposed)

- Notebook (cell 11): `reg_LH(w, power_iter=True)` — one-step power iteration by default, exact `eigvalsh` when `power_iter=False`. The notebook's `GREMLIN` default and every contact-prediction cell use the power estimate.
- Runner: `exact_lh_eigenvalue` defaults to `false` (the power estimate) and selects `eigvalsh` when enabled. Default matches upstream.
- Literature: PRX Life §II.C states only that `λ₁` can be approximated by the power iteration method. No paper position requires one over the other; the parameter exposes the notebook's own alternative.

### D9 — Adam transcription — `EXACT_TRANSCRIPTION`

- Notebook (cell 11): `custom_adam(lr, b1=0.9, b2=0.999, eps=1e-8, b_fix=False)`. With `b_fix=False` the update is `−lr·m / (√v + eps)` where `v` is a **single scalar per parameter tensor** (`v = b2·v + (1−b2)·sum(grad²)`), and no bias correction is applied.
- Runner (`fit_model.notebook_adam`): first moment elementwise; second moment `zeros((), dtype)` per tensor updated by `jnp.sum(jnp.square(gradient))`; update `−lr·m/(√v + 1e-8)`; no bias correction. `learning_rate` is the notebook's `lr`.
- Why classified exact: the Runner reproduces the unusual parts deliberately (scalar second moment, no `m̂`/`v̂`), rather than substituting `optax.adam`. The `learning_rate` help text says so.

### D10 — Penalty scaling by L, K and Neff — `EXACT_TRANSCRIPTION`

- Notebook: `0.5 * lambda · penalty * n_total * states // sqrt(neff) / sqrt(1000)` with `n_total = ncol = L` and `states = K`.
- Runner: the field penalty is written as the same expression, renamed only in D2 (`0.5 * lambda_l2 * sum(b²) * width * len(ALPHABET) / sqrt(neff) / sqrt(1000)`); the three coupling penalties precompute `scale = width * states / jnp.sqrt(neff) / jnp.sqrt(1000)` and multiply, i.e. `0.5 * lambda · penalty · scale`.
- Why classified exact: the two forms are algebraically identical. The coupling path merely regroups the scalar multiplications (`(A·L)·K` vs `A·(L·K)`), which is not bit-identical in float32 but is float-equivalent; the equivalence test's measured agreement (≤ 5.8 × 10⁻⁵ on the coupling matrices, well inside the 2 × 10⁻³ bound) confirms it.
- Consequence for D2: because the notebook's `//` binds the whole `0.5·λ·Σb²·L·K` product rather than the factor after it, the floor is applied to a data-dependent quantity; see D2 for the resulting operator-precedence arithmetic and the gradient that vanishes as a result.

### D11 — `get_mtx` vs `jax_apc`'s `+1e-8` — `NUMERICAL_GUARD`

- Notebook has **two** raw-matrix routines that differ: cell 8 `get_mtx` computes `raw = √(Σ W²)` with **no** epsilon and takes APC over that raw matrix; cell 11 `jax_apc` computes `√(Σ W² + 1e-8)` and takes APC over the epsilon-corrected matrix. Off-diagonal entries therefore differ at the `1e-8` under the square root.
- Runner (`fit_model.coupling_scores`): follows the `jax_apc` form (`+ 1e-8`), and both reference variants reproduce the receipt within 3.2 × 10⁻⁴, i.e. the two upstream routines are numerically indistinguishable at data precision on the reference case.
- Classification rationale: the epsilon only exists to keep the square-root gradient finite; it does not change any reported value beyond float32 noise. Also note that using `jax_apc` keeps the reported diagnostic matrix consistent with the *training* objective, which minimizes the `jax_apc`-style raw matrix — the more defensible of the two upstream variants.
- Literature: PRX Life Eq. (2) defines `M` with no epsilon; the epsilon is a numerical device.

### D12 — Input validation and bounded envelopes — `PRODUCTION_DEFAULT`

- Runner-only, with no notebook counterpart: reject fewer than two rows, unequal widths, unsupported residues, empty/headless sequences, and width > 512; raise on non-finite model values; cap iterations through the Task schema.
- Why: a server Runner must fail closed on input it cannot model. Upstream `mk_msa` crashes unhelpfully on a multicharacter symbol (a three-letter code such as `ALA` produces an inhomogeneous array error), and accepts a `.` insertion dot as "unknown" and maps it to the last alphabet state (tyrosine in this build) instead of removing it as A3M insertion context. The Runner validates the former and removes the latter.
- Literature: silent; the papers assume a curated alignment.
- Related reporting detail: `alignment/statistics.json` counts excluded columns with the same `>= gap_cutoff` predicate `sequence_weights` uses to exclude them, so the reported count and the weighting agree exactly (a column at exactly the cutoff is excluded by both). The field is named `columns_excluded_by_gap_cutoff` rather than "columns above the gap cutoff" because the value is scoped to similarity weighting: excluded columns are still one-hot encoded and still contribute to the pseudo-likelihood objective, so the number is not a count of columns left out of the model.

### D13 — Profile and diagnostic presentation choices — `PRODUCTION_DEFAULT`

- `profiles/profile.tsv` reports observed per-position state frequencies plus entropy and gap fraction. Upstream computes the same frequencies in `get_pssm`/`get_H` for figures but emits no such file.
- `plots/coupling_apc.png` renders the APC matrix (the comparison view), while the primary view is the raw matrix. A plot is not a scientific conclusion, so it is classified `diagnostic` and the interactive matrices are the scientific surface.
- `couplings/pairwise_scores.tsv` ranks the upper triangle by APC score. Upstream defines no exported ranking rule; ordering by APC is the presentation choice that matches the paper's contact-prediction ablation, and the raw score is kept in the same row so either reading is available.
- The Runner's `sequence_statistics` subtracts the per-position max before exponentiating; cell 14 uses `jax.nn.softmax`, which is already max-stabilized. Mathematically identical — a defensive no-op, not a deviation in value.

### D14 — Exact upstream commit cannot be re-derived offline — `UNKNOWN` (provenance limitation)

- The notebook **blob** hash is verifiable from the pinned file alone and is the hash that actually pins the transcribed source. The **commit** `6b8a6beb…` was recorded at intake and cannot be recomputed from the blob offline (git needs the history). The receipt therefore records both, marks the blob as the authoritative pin, and the generator re-derives the blob hash but not the commit. The classification is `UNKNOWN` because no available source can confirm or refute the commit claim offline — not because the value is doubted.
- Consequence, stated honestly: a future reader who wants commit-level provenance must fetch the repository; nothing in this Runner depends on it beyond the recorded citation.

### D15 — Stated-but-unresolvable items

- Whether the notebook's `w_lam` was ever intended as a *cutoff on identity fraction* vs a distance: the notebook calls it a weight threshold, and the paper's lineage (PNAS Methods) describes 90 %-identity filtering, which is a different operation (dropping rows vs reweighting them). The Runner keeps the notebook's reweighting semantics. The literature does not disambiguate, because PNAS applies identity filtering *before* GREMLIN while the notebook applies similarity reweighting *inside* it; both are defensible and the Runner follows the notebook. **`UNKNOWN`** as to upstream intent for the constant's meaning; the implemented semantics are the notebook's.
- Whether `n_total` in the notebook's regularizers is meant to be the column count or the row count: the notebook passes `ncol` at every call site, and the paper says only that the hyperparameter correlates with "the number of states, the inverse of the square root of effective sequences, and the length of the protein". No conflict; recorded because the parameter name is misleading.

### D16 — Domain of the corrections, and what the receipt's baselines isolate

Both corrections are stated for the fitted model and are applied unconditionally,
in every regularization mode, in both the equivalence receipt and the Runner:

- D2 (ordinary division) is not mode-specific: it is the field `b` penalty inside
  `compute_loss_bias`, which runs whenever one-body fields are enabled,
  independently of L2/LH/LB. The receipt pins LH, so it exercises the field penalty
  under LH as well as under the coupling term.
- D1 (gap plane) affects `jax_weights`, which runs before any regularization and
  therefore affects all three modes identically.

What each receipt baseline isolates (corrected after review):

- `pinned_uncorrected` is the **unmodified notebook**: it differs from `expected`
  by **both** corrections, not by D1 alone. On the reference case D2 is the
  dominant contributor to the difference — the pinned-vs-expected field magnitude
  and coupling norm *both* track D2 (fields 9.46 → 0.33 and ΣW² 70.3 → 155.8 going
  from pinned to expected, driven by D2; D1 alone leaves the fields at 9.39), and
  all ten `top_apc_pairs` change between pinned and expected.
- `d1_only` is emitted alongside it: the notebook with the gap plane corrected and
  the division still floored. This isolates D1 (Neff 2.8667, weights equal to
  `expected`, fields still O(9.4)) from D2 (fields collapse to O(0.3)). Together
  the three sections make a D1-only revert and a D2-only revert each observable.
- The equivalence test asserts on `pinned_uncorrected` (a D1+D2 blend) **and** on
  `d1_only` (D1 in isolation), so neither correction can be reverted silently.

## 4. Decision: raw vs APC result hierarchy (TODO §9)

**Decision: the raw Frobenius matrix is the primary scientific view; the APC
matrix is a declared comparison view; both are real `matrix` views; exactly one
view is `primary`.**

Evidence:

- PRX Life §II.D ("Unsupervised and supervised contact prediction", p. 5) and
  Fig. 4(a): "an increase in the weight of LH regularization results in the
  convergence of performance between the 'raw' and 'APC' matrices, approaching
  the precision of the L2 regularized 'APC' matrix", and "the LH regularizer
  eliminates the need for the APC while maintaining the contact precision of the
  MRF model". The paper's central claim is about the **raw** LH matrix, so for an
  LH fit the raw matrix is the object the method is arguing about.
- PRX Life §I: the `L×L` matrix is the coevolution tensor *"reduced ... by taking
  the norm of each `K×K` matrix"* (body text, immediately before the discussion of
  the APC), and APC is a *post-correction* applied at that reduced-matrix level;
  the paper's motivation is that correcting inside the model makes the
  post-correction unnecessary. (The Fig. 1 caption's own wording is only that the
  tensor is "condensed into an `L×L` matrix"; the norm statement is the body text,
  and the definition is Eq. (2).)
- The paper is explicit that APC is still useful for comparison and as the
  baseline: §II.D compares raw and APC at every regularization weight, and the
  L2 baseline is drawn with and without APC. Removing the APC artifact would
  remove the comparison the argument depends on.

**The convergence claim is the paper's, not a property of any one run.** PRX Life
states it for LH weights in the paper's tuned range on its 1k–20k-sequence MSAs;
it is an asymptotic benchmark result, not something this Runner's default output
guarantees. On the reference case the correction is materially non-trivial:
`‖AP term‖ / ‖raw‖ ≈ 0.45` over the off-diagonal entries (the removed term is
still comparable to the matrix it corrects, even though the correction itself
removes only ~11 % of the raw off-diagonal L2 norm — ~21 % of the squared norm).
That the *top-10 upper-
triangle pairs* agree 10/10 between raw and APC on this tiny case is a
consequence of its small size and its sharply separated strongest pairs — a
6-row alignment is far from the regime the paper's convergence claim describes,
so the number should not be read as the claim holding here. The decision to make
raw primary rests on the paper's argument about the method, with APC retained as
the comparison the argument is measured against.

Consequence for presentation: the primary view is `raw_couplings`
(`couplings/raw_scores.csv`), the comparison view is `apc_couplings`
(`couplings/apc_scores.csv`), both `direction: higher` and
`row_labels_column: position`. Their **colour scales differ, deliberately**:

- The raw matrix is `M_ij = √(Σ_ab W_ia,jb²)` — a Frobenius norm, so every entry
  is `≥ 0`. It is declared `scale: sequential` (low → high); a diverging scale
  centred at zero would invent a meaningful sign the quantity does not have.
- The APC matrix is `C_ij = M_ij − (Σ_k M_ik)(Σ_k M_kj)/Σ_kl M_kl`, which is
  signed after the correction. It is declared `scale: diverging`, `center: 0`,
  so its sign is encoded honestly around the zero the correction acts on.

Raw and APC therefore must **not** share one visual scale semantics: the same
quantity before and after a signed correction does not have the same sign domain.
The decision about which is primary is a statement about *this runner's default
regularization* (LH) and is recorded here rather than hard-coded in the frontend:
for an L2 run the same argument would favor the APC matrix, and the Task
parameter is what selects the regime — the docs, not the browser, carry that
nuance. The scale choice is likewise declared per view in `task.yaml`, not
branched on the Runner name in generic rendering code.

The dead `evidence-bundle` view (which rendered "No inline preview is
available") was removed per TODO §20. Its three durable files remain published
and reachable: `model/gremlin_mrf.npz` and `model/metadata.json` through Files &
diagnostics and the storyboard's model section, and `profiles/profile.tsv`
through the storyboard's profile section.

## 5. Artifact role map (TODO §14, §21)

Roles are declared once, in `expected_files.yaml`, and projected by the Server.
The judgement per file:

| File | Role | Reasoning |
| --- | --- | --- |
| `summary.json` | `provenance` | Run metadata and parameter echo; it describes the run, not the science. |
| `query.fasta` | `artifact` | Transport/input echo of the submitted first row; not independently derived. |
| `alignment/filtered_alignment.a3m` | `evidence` | The alignment that was actually modeled; the input to every scientific number. |
| `alignment/statistics.json` | `provenance` | Counts, Neff, gap statistics, parameter echo — provenance for the fit. |
| `alignment/sequence_weights.tsv` | `evidence` | Per-row phylogenetic weights are a scientific preprocessing result, not just bookkeeping. |
| `model/gremlin_mrf.npz` | `evidence` | The durable fitted model (fields + couplings); the primary reusable scientific object. |
| `model/metadata.json` | `provenance` | Shapes, array descriptions, upstream pin — makes the NPZ interpretable without the code. |
| `model/training_history.csv` | `diagnostic` | Optimization history; it shows that fitting converged, it is not a conclusion. |
| `model/sequence_scores.tsv` | `evidence` | Per-sequence pseudo-likelihood loss and Hamiltonian — a real derived quantity (used by the paper's ranking and design arguments). |
| `profiles/profile.tsv` | `evidence` | Observed per-position state frequencies and entropy — a scientific observation. |
| `couplings/pairwise_scores.tsv` | `evidence` | Ranked residue pairs; the per-pair scientific result. |
| `couplings/raw_scores.csv` | `evidence` | Raw Frobenius matrix; also the primary view's source. |
| `couplings/apc_scores.csv` | `evidence` | APC matrix; the declared comparison view's source. |
| `plots/coupling_apc.png` | `diagnostic` | A static rendering of the APC matrix; the interactive matrix views supersede it as the scientific surface. |

Nothing scientifically meaningful is left in "Other files": the only `artifact`
entry is the query echo, and the two `diagnostic` entries are the optimization
history and the plot.

## 6. Scientific golden case and receipt (TODO §10–§12)

Case: `tests/data/msa/2KL8.i90c75_aln.a3m`.

- Provenance: a six-row homolog set for the de novo designed 2KL8 protein,
  produced by the mock/mimic pipeline documented in `tests/data/msa/README.md`
  (it is the A3M asset that pipeline consumes; the UniRef-derived headers and the
  `synthetic construct` taxids are the pipeline's own placeholder metadata, not
  a claim about real UniRef records). It is the alignment the legacy
  `pssm_gremlin` family and the mock HHblits database are built around, so it is
  the repository's canonical small real-shaped MSA.
- sha256 `b099f030c2bca669ce75961104a625d8aad4f3bd49a71ad5a07fa97d32df113f`;
  6 rows × 79 columns; 18 amino-acid states plus the deletion gap; no insertion
  letters, no dots, no query gaps.
- Preprocessing: `parse_alignment(a3m=True)` is a no-op on this file beyond
  validation (nothing to strip), so the modeled alignment equals the file.
- Parameters: pinned in the receipt (`parameters`) — LH, upstream
  inverse-covariance initialization, 50 full-batch Adam steps, seed 0. Full-batch
  sampling is what makes the reference independent of the RNG algorithm (D6).
- Fit for purpose: it exercises the real path (gaps present in homologs, non-zero
  Neff gap between the pinned and corrected weighting, three coupling blocks that
  are not artifacts of one pair), it is cheap, and it is already the repository's
  reference MSA. The paper's hundreds-of-proteins benchmarks are deliberately not
  reproduced (TODO §10).

Receipt: `tests/data/gremlin_lh/upstream_reference.json`, regenerated by
`tests/data/gremlin_lh/generate_upstream_reference.py`. The generator:

- refuses any notebook whose git blob hash and file SHA-256 are not the pinned
  pair, *before* it reads a single cell, so a wrong or edited `--upstream` can
  never reach a computation;
- rebuilds the notebook's module state from
  `tests/data/gremlin_lh/upstream_notebook_reference.py`, a **checked-in literal
  transcription** of the pinned cells, and derives every observable from that
  transcription's own functions (`GREMLIN`, `jax_apc`, `get_Hamiltonian_loss`),
  so a Runner regression appears as a receipt mismatch instead of being absorbed
  by a shared helper. No cell content from `--upstream` is executed;
- proves the transcription is the pinned notebook's own source (each function's
  text must appear verbatim in its cell) and aborts otherwise, so a drift in
  either the notebook pin or the transcription stops generation;
- expresses the two corrections as **explicit parameters whose default is the
  pinned behaviour** (`gap_plane_index`, `field_penalty_floor`), so one
  transcription produces all three recorded variants with no textual
  substitution of source at run time;
- derives the notebook blob hash with `git hash-object` (no network) and records
  the file SHA-256, input SHA-256, dependency versions, parameters, and seed;
- emits two comparison baselines beside `expected`: `pinned_uncorrected` (the
  unmodified notebook, both corrections absent) and `d1_only` (gap plane
  corrected, field penalty still floored). Together they make a revert of either
  correction observable; see D16.

Observables captured: full `sequence_weights`, `neff`, full one-body `fields`,
three `couplings_blocks`, `couplings_l2`, `couplings_max_abs`, full `raw_scores`
and `apc_scores` matrices, per-sequence `sequence_pseudo_loss` and
`sequence_hamiltonian`, and the top-10 APC pairs with their (index_i, index_j,
raw, apc) identities.

### Tolerances and their reasons

| Quantity | Tolerance | Reason |
| --- | --- | --- |
| sequence weights, Neff | exact (1e-6 / 1e-5 on the sum) | Algorithmic: identical arithmetic in both implementations, no optimizer involved. Any drift is a real bug. |
| fields, W blocks, raw, APC | 2e-3 absolute | The upstream receipt and the Runner reach the same fixed point through a different float32 reduction order (JAX/optax's vectorized update and the notebook's Python loop accumulate the same full-batch gradients differently). The reference fit is order-*insensitive*: at full batch both draw the same six rows, and varying the seed moves the result by ≤ 6e-5 — so this is reduction noise, not sampling. The measured agreement on the current stack is two orders of magnitude tighter: ≤ 3.8e-6 (fields), ≤ 9.1e-6 (W blocks), ≤ 5.8e-5 (raw/APC). 2e-3 bounds legitimate float32 accumulation while staying far below any scientific signal. |
| `couplings_l2`, `couplings_max_abs` | 1e-3 relative | Aggregates over 2.7 M entries amplify per-entry float32 noise; the measured relative deviation is ≤ 6.8e-6. |
| per-sequence pseudo-loss, Hamiltonian | 5e-2 absolute | Largest absolute quantity in the receipt (|H| ≈ 376), so it carries the largest absolute float32 noise. The measured deviation is ≤ 5.5e-4. |
| APC ranking | top pair exact; ≥ n−2 set overlap among the top 10 | Two APC scores that are tied at float32 precision can swap order; the strongest pair is unambiguous. |

The tolerances are deliberately *not* widened to make CI pass: the current
implementation passes them with 20–100× margin.

## 7. Citation provenance

Result runs carry both citations in `summary.json` (and the Task's
`citations`), and the Server publishes them as `citations.bib` (role:
`provenance`). The Storyboard does not repeat bibliography in the normal result
surface.

- Wang H. et al., PRX Life **2**, 023005 (2024) — the LH spectral regularizer and
  the raw-matrix/APC argument.
- Kamisetty H., Ovchinnikov S., Baker D., PNAS **110**, 15674–15679 (2013) — the
  GREMLIN pseudolikelihood model and the APC correction.

**Correction notice.** The 2013 PNAS paper was corrected: *Correction for
Kamisetty et al.*, PNAS **110**(46), 18734 (2013), DOI 10.1073/pnas.1319550110,
PMCID PMC3831956. The correction replaced **Fig. 1 C and E and the corresponding
legend**; the published replacement clarifies the comparison panels (MIc in
panel C, and the average-accuracy / fraction-of-targets legend in panel E). The
correction does not touch the model definition, the pseudolikelihood objective,
or the APC equation that this Runner transcribes — those are unaffected — but a
reader who cites the paper's contact-prediction comparison figures must cite the
corrected version. The method/lineage citation used by this Runner is the
corrected record.

## 8. Interpretation boundaries (TODO §8, §22)

- A coupling score is a **statistical dependence in the fitted model**. It is not
  by itself proof of a physical contact, a causal interaction, or functional
  coupling; the contact-oriented reading (Frobenius norm of the `K×K` block,
  ranked pairs) is a downstream use of these scores.
- `profiles/profile.tsv` is a **profile / per-position state-frequency table**
  (observed frequencies, consensus, entropy, gap fraction). It is not a PSSM:
  no background distribution and no log-odds scoring are defined for it.
- The Hamiltonian in `model/sequence_scores.tsv` is the model's **statistical MRF
  energy**, not a thermodynamic free energy.
- PRX Life §II.E reports *empirical* correlations between the Hamiltonian and
  measured stability for specific designed datasets, and §II.G reports
  qualitative interpretability for specific proteins. Those are system-specific
  results. Nothing here supports a stability, fitness, or functional claim about
  any particular run of this Runner.

## 9. How this record is kept true

```bash
# Regenerate the receipt from the pinned notebook (maintainer only; not CI).
.venv/bin/python tests/data/gremlin_lh/generate_upstream_reference.py \
    --upstream /path/to/GREMLIN_LH_outline_7.ipynb

# Fast protocol contract plus Runner-owned logic (needs jax/optax/matplotlib).
.venv/bin/python -m pytest tests/runners/gremlin_lh -q

# Generic family contract.
.venv/bin/python -m revocompute doctor --config-root docker/runners --runner gremlin_lh --strict
```

`test_upstream_equivalence.py` is the scientific acceptance: it runs the
Runner's real fitting code with the receipt's parameters and compares every
receipt observable. If it fails, the code — or this record — is wrong; the
tolerance table above is not to be loosened to accommodate a regression.
