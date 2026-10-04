# GREMLIN_LH scientific acceptance

This record closes the literature-grounding work for the `gremlin_lh` Runner. It
states what the model is, what a real production run produced, where the output
agrees with the pinned upstream notebook, where it intentionally differs, and
what the result must **not** be read to say. The traceability argument, every
deviation, and the citation provenance are in
[`SCIENTIFIC_TRACEABILITY.md`](SCIENTIFIC_TRACEABILITY.md); this file is the
acceptance summary and the receipt of the live run.

## 1. What was modeled

The Runner is a faithful transcription of `sokrypton/GREMLIN_LH`
(`GREMLIN_LH_outline_7.ipynb` @ `6b8a6beb426fd31bb10c3fdd398abd3355b782f9`) and
the method of:

- Wang et al., *PRX Life* **2**, 023005 (2024), 10.1103/PRXLife.2.023005 —
  the LH (sparse spectral) regularizer, the reduced coupling matrix
  `M_ij = √(Σ_ab W_ia,jb²)`, and the APC definition.
- Kamisetty, Ovchinnikov & Baker, *PNAS* **110**, 15674–15679 (2013),
  10.1073/pnas.1314045110 — the pseudolikelihood MRF and the APC.
  (Corrected by 10.1073/pnas.1319550110; the correction touches Fig. 1C/E and its
  legend only, not the model, objective, or APC equation used here.)

Fitted object: an `L×K`-field, `L×K×L×K`-coupling Potts/MRF on the one-hot MSA,
optimized by the notebook's `custom_adam` (scalar second moment, no bias
correction) under one of L2 / LH / LB regularization. `Neff` is the sum of
sequence identity weights.

## 2. Two acceptance cases (do not conflate them)

The live-test declaration (`test.yaml`) publishes two collections, and they prove
different things:

| Collection | Case | Alignment | Proves |
| --- | --- | --- | --- |
| `smoke` | `minimal-gremlin-lh-fit` | `tests/data/msa/gremlin_lh_tiny.a3m` (8×8) | runtime path: dispatch, Slurm, Apptainer, result publication, matrix rendering, storyboard loading, browser behavior |
| `scientific` | `gremlin-lh-2kl8-upstream-profile` | `tests/data/msa/2KL8.i90c75_aln.a3m` (6×79) | the scientific golden case: a real-shaped homolog set at the exact pinned upstream profile, directly comparable to the frozen receipt |

The 8×8 case is a **runtime/smoke acceptance**; it does not probe scientific
agreement. The 6×79 case is the **scientific golden case**. Neither substitutes
for the other.

### 2a. Runtime smoke acceptance (live receipt)

Run through the production path on `lab309-westlake` — the real Server dispatch,
a real Slurm allocation, and the real Apptainer image — not a local harness:

| Field | Value |
| --- | --- |
| Runner family / task | `gremlin_lh` / `gremlin_lh_fit` |
| Collection / case | `smoke` / `minimal-gremlin-lh-fit` |
| Slurm job | `7250` (`COMPLETED`), scheduler user `revodesign`, uid/gid `129/137` |
| Walltime (Slurm `Elapsed`) | `00:00:14`; controller-reported case duration `20.6 s` |
| Peak RSS / CPU | `347 980 KiB` (~340 MiB); user `14.35 s`, system `1.68 s`, 1 CPU |
| Exit code | `0`, task status `finished` |
| ResultManifest | `schema_version` **3** |
| Output check | **19/19 passed**, no problems |
| SIF | `gremlin_lh_v1.sif`, sha256 `2c5838108eadf76ee72853120bf27aed3f188d5fb0bf1601348e93ca722c2260` |
| Runtime bundle | sha256 `94708514f6ac3b2cda7a39bec6b67822c15b49993614217c74c1b59341796f41` |
| Input | `tests/data/msa/gremlin_lh_tiny.a3m`, sha256 `18f2d308…486e6d3` (8×8 a3m) |
| Parameters | `regularization=LH, iterations=2, batch_size=4, inverse_covariance_init=false, seed=7` |
| Receipt | `/mnt/hdd/revocompute/images/live-tests/gremlin_lh/1791038069667371136-smoke.json` |

Published views (`view.plugin`, dispatched without any runner-name branch):
`matrix` (**primary**, "Coupling strength (raw Frobenius)"), `matrix`
(evidence, APC), `entity-table` (ranked pairs), `alignment`, `scalar-summary`.
Artifact roles on the published surface: the raw matrix is `primary`; the APC
matrix, weights, profile, MRF, and sequence scores are `evidence`; the model
metadata, summary, statistics, and citation file are `provenance`; the training
history, coupling plot, and Slurm logs are `diagnostic`. `Neff` for this case is
`2.0833`.

The primary raw view carries a **sequential** colour scale (its entries are a
Frobenius norm, `M_ij = √(Σ_ab W_ia,jb²) ≥ 0`); the APC view keeps a **diverging**
scale centred at zero (APC scores are signed after the correction). The two
deliberately do not share one visual scale semantics.

### 2b. Scientific golden acceptance (live receipt)

The same production path, now on the real-shaped **2KL8** alignment at the exact
profile the frozen receipt records (§3), so this run is directly comparable to
the pinned notebook rather than to a toy input:

| Field | Value |
| --- | --- |
| Runner family / task | `gremlin_lh` / `gremlin_lh_fit` |
| Collection / case | `scientific` / `gremlin-lh-2kl8-upstream-profile` |
| Slurm job | `7933` (`COMPLETED`), scheduler user `revodesign`, uid/gid `129/137` |
| Walltime (Slurm `Elapsed`) | `23.49 s`; controller-reported case duration `30.4 s` (family run `39.4 s`) |
| Peak RSS / CPU | `478 132 KiB` (~467 MiB); user `25.52 s`, system `2.01 s`, 1 CPU |
| Exit code | `0`, task status `finished` |
| ResultManifest | `schema_version` **3** |
| Output check | **19/19 passed**, no problems |
| SIF | `gremlin_lh_v1.sif`, sha256 `2c5838108eadf76ee72853120bf27aed3f188d5fb0bf1601348e93ca722c2260` |
| Runtime bundle | sha256 `94708514f6ac3b2cda7a39bec6b67822c15b49993614217c74c1b59341796f41` |
| Build provenance digest | sha256 `cafadcf89ff18fd9a5d35507ba9caa51900659d335337c8760ed8cfe60d1c5e0` |
| Test-definition digest | sha256 `b59551874cc925643eabd20cb23d97d11e27ab30fe98c2cd5f725a94f63ec834` |
| Configuration digest | sha256 `aae346a5ee6828e10c96720fe4d2eb395b2e988b4d2da8f3de40f69e50e509d7` |
| Apptainer | `1.5.4` |
| Input | `tests/data/msa/2KL8.i90c75_aln.a3m`, sha256 `b099f030c2bca669ce75961104a625d8aad4f3bd49a71ad5a07fa97d32df113f` (6×79 a3m) |
| Parameters | the pinned upstream profile: `regularization=LH, lambda_l2=0.01, lambda_lh=0.1, lambda_lb=0.005, iterations=50, batch_size=6, learning_rate=1.0, identity_cutoff=0.8, gap_cutoff=0.5, use_bias=true, inverse_covariance_init=true, exact_lh_eigenvalue=false, seed=0` |
| Receipt | `/mnt/hdd/revocompute/images/live-tests/gremlin_lh/1791048636166142206-scientific.json` |
| Task id | `5cffb82db52978a42508a79794df703f` |

The published `summary.json` from this run reports the pinned-profile result:
`alignment_length=79`, `sequence_count=6`, `effective_sequence_count=2.8667`
(matching the frozen receipt's `expected.neff`), `columns_excluded_by_gap_cutoff=3`,
`regularization=LH`, `iterations=50`, `final_data_loss=16.284`,
`final_loss=42.962`. That the live Neff equals the receipt's `expected` Neff — and
not its `pinned_uncorrected` value — is the D1 gap-plane correction showing up in
a real production run, not only in the equivalence test.

The browser acceptance (`tests/test_playwright_gremlin_golden_acceptance.py`)
now serves **this** run's manifest, artifacts, and storyboard, so the rendered
matrix, storyboard, and role grouping are verified against the scientific golden
case rather than the smoke case.

## 3. Where it matches the pinned notebook

The reference receipt (`tests/data/gremlin_lh/upstream_reference.json`,
schema_version 2) is regenerated from a checked-in literal transcription of the
pinned notebook's own cells (`tests/data/gremlin_lh/upstream_notebook_reference.py`,
guarded against the pinned notebook's source), so its observables are upstream
behaviour rather than a shared-helper echo. On the
2KL8 receipt case (79 columns, 6 rows, 50 full-batch steps, seed 0) the Runner
agrees within tolerance — measured `20–100×` tighter than the assertions:

- sequence weights / `Neff`: algorithmic, exact to `1e-6`;
- one-body fields, `W` blocks, raw and APC matrices: ≤ `5.8e-5` (bound `2e-3`);
- per-sequence pseudo-likelihood and Hamiltonian: within bound.

The residual is float32 reduction order (JAX/optax's vectorized update vs the
notebook's loop), not sampling: at full batch both draw the same rows and the
fit is seed-insensitive to ≤ `6e-5`.

## 4. Where it intentionally differs (both disclosed, both checkable)

Two changes, both classified `EXPLICIT_CORRECTION` and both carried in the
receipt so neither can be reverted silently:

1. **Explicit gap plane (D1).** The notebook's `jax_weights` reads
   `x_msa[:, :, -1]` for the gap plane. Under the current gap-first alphabet
   (`-ACDEFGHIKLMNPQRSTVWY`) that plane is **tyrosine**, not gap — a stale index
   from the retired gap-last alphabet. The Runner uses a named `GAP_INDEX`. This
   changes `Neff` on gap-containing alignments, so the receipt keeps the
   uncorrected values beside the corrected ones (`pinned_uncorrected.neff =
   3.3333` vs `expected.neff = 2.8667`).
2. **Ordinary division in the field L2 penalty (D2).** The notebook's
   `//` binds the whole data-dependent product, so its field penalty is
   piecewise-constant in `b` and contributes **no gradient** (`∂reg_b/∂b ≡ 0`);
   every sibling term divides normally and the papers define an L2 prior with a
   scalar weight. The Runner divides, restoring the term. The receipt emits
   `d1_only` specifically so D1 and D2 are independently observable.

`pinned_uncorrected` is the unmodified notebook — a **D1+D2 blend**, dominated by
D2 on this case — and is documented as such; it does not isolate D1.

## 5. What this result must not be read to say

- Coupling strength is **statistical dependence in the fitted model**, not proof
  of a physical contact, causal interaction, or functional coupling. The
  contact-oriented reading is a downstream use of these scores.
- The profile is a per-position residue frequency table, **not a PSSM**.
- The Hamiltonian is the model's **statistical MRF energy**, not a thermodynamic
  free energy.
- The paper's raw-vs-APC convergence ("LH removes the need for APC") is its
  **asymptotic benchmark** for tuned LH weights on 1k–20k-sequence alignments —
  not a property of any particular run. On the tiny 2KL8 reference case the APC
  term is still material (`‖AP term‖/‖raw‖ ≈ 0.45`), so the corrected matrix
  remains a genuinely distinct comparison view.
- The paper's stability correlations are **empirical and system-specific**; this
  Run makes no stability claim.

## 6. Scientific golden-case provenance

Both acceptance cases are the **mock/mimic pipeline's** alignments, not real
UniRef records with a shared phylogeny; each exercises the model end-to-end and
pins its numbers, and neither is a benchmark of contact precision.

- The **runtime/smoke case** (§2a) is an 8-row, 8-column a3m built for 2KL8; it
  proves the runtime path, not agreement.
- The **scientific golden case** (§2b) is the 6-row, 79-column
  `2KL8.i90c75_aln.a3m`, the Run's real-shaped homolog set, run at the exact
  pinned upstream profile so its result is directly comparable to the frozen
  receipt (§3). It is *not* the tiny case.

Contact-precision reproduction on the papers' real 1k–20k-sequence alignments is
explicitly out of scope for this work (the goal forbids reproducing the papers'
benchmark datasets).

## 7. How to re-verify

```bash
# Runner + upstream-equivalence tests (needs the pinned jax/optax/matplotlib stack).
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m pytest tests/runners/gremlin_lh -q

# Regenerate the receipt from the pinned notebook (maintainer only; not CI):
.venv/bin/python tests/data/gremlin_lh/generate_upstream_reference.py \
  --upstream ~/revocompute-handoff-309/references/GREMLIN_LH_outline_7.ipynb

# Real path on the target host (as the deployment account, from a neutral cwd).
# The smoke collection is the default; select the scientific golden case with
# --collection scientific.
bash run/restart.sh live-test --runner gremlin_lh --use-proxy
bash run/restart.sh live-test --runner gremlin_lh --collection scientific --use-proxy
```

Browser and semantic acceptance of the published ResultManifest (the matrix
renders through `PairMatrix`, the storyboard narrative loads, roles are sane, and
no console/CSP errors) is covered by the browser test suite and recorded
alongside this run.

## 8. Production submission (live, post-merge)

Beyond the harness-driven live test, the merged Runner was exercised once through
the **public API on the production host** — the same path a real user takes: an
authenticated `POST /compute/api/post` with the 2KL8 alignment bound to the
`alignment` role at the pinned upstream profile.

| Field | Value |
| --- | --- |
| Deployed revision | `main` @ `c82ea79` (the PR #37 merge), `/opt/revocompute` |
| Server image | `revodesign-revocompute-server`, digest `sha256:b80ad5783803…` |
| Submission | `POST /compute/api/post`, user `tester`, role `alignment` = `2KL8.i90c75_aln.a3m` |
| Task id | `944ed43af62ead9f5c9560bae1ccd897` |
| Lifecycle | `pending` → `running` → `finished` (terminal, no error); API-observed lifecycle `23.6 s` (`submitted_at` `03:24:09.730Z`, `finished_at` `03:24:33.471Z`, `run.walltime_seconds` `23.61`) |
| Slurm job | `10304`, exit `0`, elapsed `23.42 s`, `max_rss` `486944 KiB`, 1 CPU |
| ResultManifest | `schema_version` **3** |
| Input | `2KL8.i90c75_aln.a3m`, a 6-sequence × 79-position a3m (`sequence_count=6`, `alignment_length=79`), the scientific golden case |
| Parameters | the pinned upstream profile (`LH, 0.01, 0.1, 0.005, 50, 6, 1.0, 0.8, 0.5, true, true, false, seed 0`) |
| Views | `matrix`/primary "Coupling strength (raw Frobenius)", `matrix`/evidence APC, `entity-table`, `alignment`, `scalar-summary` |
| `summary.json` | `alignment_length=79`, `sequence_count=6`, `effective_sequence_count=2.8667`, `columns_excluded_by_gap_cutoff=3`, `final_loss=42.9618`, `iterations=50`, `regularization=LH` |

The compared **summary observables** match the `scientific` live-test receipt
(§2b): the same Neff (`2.8667`), the same `final_loss` (`42.962`), the same
excluded-column count, and the same pinned parameters. That is evidence the
deployed path reproduced those summary figures. It is **not** an artifact-level
equivalence check — the fitted fields, couplings, raw/APC matrices, and
per-sequence outputs were not compared element-wise against the §2b run — so this
record stops at consistent summary observables rather than asserting the whole
result is bit-identical. What it does prove end-to-end is admission (readiness
gate passed on the promoted SIF), Slurm execution, publication, and the declared
view surface over the real production API.

This table is the human summary of that submission. Its machine-generated
counterpart — the deployment, admitted snapshot, Slurm job, API lifecycle,
ResultManifest, and re-hashed artifact inventory, all derived from the running
deployment's own state — is captured with
`bash run/restart.sh api-receipt --task <task-id>` and documented in
[Production API Acceptance Receipts](../../../docs/operator-guide/api-receipts.md).
Where the two ever disagree, the receipt is authoritative: it is re-hashed from
the published bytes, while this table is prose.
