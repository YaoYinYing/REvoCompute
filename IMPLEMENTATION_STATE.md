# GREMLIN_LH Scientific Reference Runner — Implementation State

`TODO.md` is the design contract for this work. This file is the execution/
progress truth; the acceptance commands and the real Slurm/browser receipt are
the machine-verifiable truth.

## Starting point

- Starting SHA: `87aeb191fb1a2dafcf4d8019afd6f5fdf59be941` (PR35, == `origin/main`).
- Branch: `scientific/gremlin-lh-reference-runner`.
- The frontend/backend presentation architecture (PR32–PR35) is canonical and is
  not re-opened.
- Production fork `/opt/revocompute` has two local DB-path edits
  (`docker-compose.slurm.yml`, `runners/pssm_gremlin/runner.yaml`) that are
  deployment localization and are **never** part of this change.

## Source evidence gathered (audit basis)

Offline copies in `~/revocompute-handoff-309/references/` (not repo artifacts):

| Source | Identity |
| --- | --- |
| Wang et al., PRX Life 2, 023005 (2024) | full article + Methods |
| Kamisetty et al., PNAS 110, 15674–15679 (2013) | PMC3785744 full text |
| PNAS correction | 10.1073/pnas.1319550110 (PMC3831956): Fig. 1C/E and legend corrected |
| Pinned notebook | `sokrypton/GREMLIN_LH` @ `6b8a6beb...`, blob `79cc0fdaba25ff1a6d6cb12ab2a2ebc8358c2c17` (git hash-object verified) |

Verified notebook facts (cell indices in the pinned blob):

- cell 7: `alphabet = "-ACDEFGHIKLMNPQRSTVWY"` (gap first); commented-out older
  alphabet `"ARNDCQEGHILKMFPSTWYV-"` has gap **last**.
- cell 8: `get_mtx` = raw Frobenius norm (no `1e-8`) + APC on the raw matrix.
- cell 11: `jax_weights` reads `x_msa[:, :, -1]` for the "gap" plane. With the
  current gap-first alphabet this is **tyrosine**, not gap — a stale index left
  over from the gap-last alphabet. Intent (parameter name `gap_cutoff`,
  docstring) is gap. → REvoCompute's explicit `GAP_INDEX` correction is sound.
- cell 11: `compute_loss_bias` field penalty uses `n_total * states //
  jnp.sqrt(neff)` (floor division) while every other term uses `/`. Typo.
  → REvoCompute's ordinary-division correction is sound.
- cell 11: `jax_apc` uses `+1e-8` under the sqrt (differs from `get_mtx`).
- cell 11: `jax_inv_cov` returns `-reshape(inv)`; reg scale `n_total*states/
  sqrt(neff)/sqrt(1000)`; `reg_LH` power-iter by default.
- cell 11: `custom_adam(b1=.9,b2=.999,eps=1e-8,b_fix=False)` — scalar second
  moment per tensor, **no** bias correction.
- cell 13: `GREMLIN(...)` recomputes weights internally (`jax_weights(msa)`),
  ignoring any supplied `msa_weights`; symmetrization masks the strictly-upper
  triangle; mean-centers over (1,3).
- cell 14: `get_Hamiltonian_loss` → per-row CE loss; `H = -sum(msa*VW,(1,2))`.

Paper facts that drive result semantics:

- §II.B/C: `M_ij = sqrt(sum_ab W_ia,jb^2)`; `C = M - pᵀp/Σpᵢ` ≈ `M - λ₁v₁ᵀv₁`.
- LH = `½γλ₁²`, a spectral penalty on the dominant eigenmode; the paper's thesis
  is that **LH removes the need for APC** — the raw matrix of an LH model
  approaches the L2+APC precision, so for an LH model the *raw* coupling matrix
  is the primary contact-oriented object; APC is a legacy post-correction kept
  for comparison. LB is group-sparse block-L1.
- The Hamiltonian is a statistical MRF energy, **not** a thermodynamic free
  energy; correlations with stability are empirical and system-specific.

## Completion checklist

### Science and traceability

- [x] `docker/runners/gremlin_lh/SCIENTIFIC_TRACEABILITY.md` exists and maps
      every scientifically meaningful operation literature → notebook →
      REvoCompute → artifact → manifest/view → test.
- [x] Every current implementation deviation is classified (EXACT_TRANSCRIPTION
      / EXPLICIT_CORRECTION / RUNTIME_ADAPTATION / PRODUCTION_DEFAULT /
      NUMERICAL_GUARD / SCIENTIFIC_DEVIATION / UNKNOWN).
- [x] The two documented corrections are re-evaluated against the notebook
      (evidence: stale gap-last index; floor-division typo) — retained as
      EXPLICIT_CORRECTION with the notebook expression quoted.
- [x] Golden 2KL8 provenance recorded (origin, rows/width, sha256, parameters,
      preprocessing) and a reproducible reference-generation procedure exists.
- [x] Raw/APC hierarchy decided from the literature (raw primary for LH; APC
      comparison) and reflected in task.yaml + Storyboard + copy.
- [x] Profile called a profile/frequency table, never a PSSM.
- [x] Coupling copy qualified: statistical dependence, not proof of contact.
- [x] Citations (Wang 2024, Kamisetty 2013, PNAS correction) in provenance/docs,
      not cluttering the normal result surface.

### Platform boundary

- [x] `task_finished` is not published as a result artifact; fixed at the
      producer/publication boundary, no filename branch in generic frontend code.
- [x] Artifact roles are scientifically intentional (no meaningful science under
      "Other files"); `coupling_apc.png`, weights, profile, model metadata, MRF,
      sequence scores classified by an explicit judgment, and the declaration
      reaches every published file (not only view sources).
- [x] Dead `evidence-bundle`-style no-preview tabs eliminated or justified.

### Generic matrix rendering

- [x] `ResultView.plugin == matrix` actually renders through `PairMatrix`.
- [x] No `runner === "gremlin_lh"` branch anywhere in generic frontend code; the
      view renderer dispatches on the declared `plugin` only.
- [x] Bounded loading, negative/zero values, diverging scale centered at 0,
      light/dark theme, resize, keyboard selection, graceful fallback.
- [x] Independent frontend/browser tests with synthetic matrices.

### Storyboard

- [x] GREMLIN_LH Storyboard is a scientific narrative, not a download launcher.
- [x] It composes existing primitives; no second CSV/matrix/table parser.

### Real acceptance

- [ ] Runner → Slurm → Apptainer → ResultManifest → browser golden run recorded
      (task id, git SHA, SIF identity, input SHA, parameters, walltime, status).
- [ ] Browser acceptance: matrix is a matrix; storyboard loads; roles sane; light
      & dark; narrow viewport; no console/CSP errors; screenshots captured.
- [ ] Scientific acceptance report written.
- [ ] Exact-head CI green.

## Active phase

Phase 1 — audit complete locally; implementation delegated to four disjoint
workstreams. No production code changed yet.
