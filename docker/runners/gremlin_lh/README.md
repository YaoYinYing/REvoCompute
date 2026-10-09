# GREMLIN_LH Runner

CPU-only REvoCompute family that fits a regularized Potts/MRF model (one-body
fields and pairwise couplings) to an **already aligned** protein MSA, and
publishes the model, the modeled alignment, a per-position profile, ranked
pairwise couplings, and the sequence scores derived from the fit.

This page is the orientation for the family. The scientific audit — every
operation tied to its literature position, notebook cell, implementation,
artifact, view, and test, plus the full deviation register — is
[`SCIENTIFIC_TRACEABILITY.md`](SCIENTIFIC_TRACEABILITY.md). The owning
`tasks/gremlin_lh_fit/task.yaml` is the sole authority for parameter names,
defaults, and help; this page deliberately does not repeat them.

The acceptance summary and the live production receipt (Slurm job, SIF and input
digests, walltime, and the "must not be read to say" boundaries) are in
[`SCIENTIFIC_ACCEPTANCE.md`](SCIENTIFIC_ACCEPTANCE.md).

## What the papers claim, and what this Runner does

**Paper semantics.** Wang et al., *PRX Life* **2**, 023005 (2024), reduce the
four-dimensional coupling tensor to an `L×L` contact-strength matrix by taking
the Frobenius norm of each `K×K` block, and show that the usual post-hoc
average-product correction (APC) to that matrix is approximately a removal of its
dominant eigenmode. They then add a spectral penalty on that eigenmode *inside*
the fit. Their reported result — measured on their own tuned LH weights and
1k–20k-sequence alignments — is that an LH-regularized model's **raw** matrix
approaches the contact precision of an L2 model *with* APC, so the correction is
no longer needed. That convergence is their asymptotic benchmark result, not a
guarantee for any particular run: on this Runner's tiny reference case the
correction is still material (see the interpretation section below). Kamisetty et al., *PNAS* **110**, 15674–15679 (2013),
supplies the underlying pseudolikelihood MRF and the APC definition. (That paper
was corrected in PNAS **110**, 18734 (2013) — Fig. 1C/E and its legend — which
does not affect the model, objective, or APC equation used here; see
`SCIENTIFIC_TRACEABILITY.md` §7.)

**Upstream notebook behaviour.** The scientific semantics belong to the upstream
notebook, not to this Runner. `fit_model.py` transcribes its reusable inference
path — `parse_fasta`/`mk_msa`, the gap-first 21-state alphabet, `jax_weights`,
`jax_cov`/`jax_inv_cov`, the two `L×L` matrix routines, `reg_LH`, the
scalar-second-moment Adam, the L2/LH/LB objectives, `GREMLIN`, and
`get_Hamiltonian_loss` — as a deterministic headless command. Interactive cells
that download benchmarks, call bmDCA, or draw paper figures are not runtime
entrypoints. The pinned source identities are recorded in
`MODEL_AND_LICENSE.md`.

**REvoCompute production behaviour.** The Runner adds what a server must have and
the notebook does not: named-role input resolution through the Runner protocol,
fail-closed validation, a bounded resource envelope, a durable model artifact,
declared result views, and provenance. Nothing in that list changes the science
of the default path.

## Deliberate differences from upstream

Full evidence, impact measurements, and classification are in
[`SCIENTIFIC_TRACEABILITY.md`](SCIENTIFIC_TRACEABILITY.md) §3. In short:

1. **Gap state (`EXPLICIT_CORRECTION`).** The notebook's weighting routine reads
   the *last* alphabet plane where its parameter name, its docstring, and its own
   earlier gap-last alphabet all mean the gap; with the current gap-first
   alphabet that plane is tyrosine. The Runner uses a named
   `GAP_INDEX`. This changes Neff on gap-containing alignments, which is why the
   reference receipt keeps the uncorrected values beside the corrected ones.
2. **Field L2 penalty (`EXPLICIT_CORRECTION`).** The notebook's `//` binds the
   whole data-dependent product `0.5·λ·Σb²·L·K`, so the field penalty becomes
   piecewise constant in `b` and its gradient vanishes: the notebook's field L2
   term is present in the loss value but **inert**. Every sibling term divides
   normally, and the papers define an L2 prior with a scalar weight. The Runner
   divides, restoring a real gradient; on the reference case that is a
   leading-order change (the field scale drops from ~9.4 to ~0.33).
3. **Inverse-covariance initialization (`PRODUCTION_DEFAULT`).** The notebook
   inverts an `L·K × L·K` matrix before the first step, which does not fit the
   production width envelope. The Runner defaults to zeros and exposes the
   upstream initialization as a Task parameter; the scientific acceptance test
   runs the upstream setting, so that path stays exercised.
4. **Mini-batch clamping (`RUNTIME_ADAPTATION`).** The notebook fails when the
   requested batch exceeds the row count; the Runner clamps to the row count.
5. **Deterministic seeding (`RUNTIME_ADAPTATION`).** The notebook uses the
   unseeded global legacy NumPy RNG; the Runner seeds a modern generator. These
   are different algorithms, so a seeded sub-batch run does not reproduce the
   notebook's row order; the reference case is full-batch, which is why the
   receipt is order-independent.
6. **Bounded numerical guards (`NUMERICAL_GUARD`).** A field-pseudocount floor at
   the `Neff == 1` boundary, and an `√(x + 1e-8)` in the raw-norm routine
   (matching the notebook's own `jax_apc`, not its `get_mtx`).

Upstream also hardcodes its weighting constants and ignores a caller-supplied
weight vector; the Runner surfaces those constants as Task parameters and always
recomputes the weights, as upstream does internally. At the upstream values the
default behaviour matches apart from the items above. No further scientific
behaviour is changed; anything else belongs in a separate scientific change.

## Workflow and artifacts

```text
alignment input (A3M or aligned FASTA)
        ↓ parse_alignment        strip A3M insertions, validate width/alphabet
        ↓ encode_alignment       one-hot over the 21-state alphabet
        ↓ sequence_weights       reweight phylogenetically similar rows
        ↓ fit_model              Adam optimization of fields + couplings
        ↓ coupling_scores        Frobenius norms, then APC correction
        ↓ sequence_statistics    pseudo-likelihood + Hamiltonian per row
        ↓ write_results          durable artifact tree
```

`expected_files.yaml` is the authoritative declaration of the tree. `run.sh`
stops on any failed stage and writes its completion sentinel only after every
declared artifact is present and non-empty, so a nominally successful fit that
produced nothing never publishes a result.

### The durable model artifact

`model/gremlin_mrf.npz` is the preserved model state: a compressed `.npz` (not a
pickle) holding the one-body fields, the symmetrized mean-centered couplings, the
alphabet, the per-row sequence weights, and the gap index. Upstream works with
NumPy/JAX arrays and defines no interchange format, so the Runner's own container
is the reproducible option. `model/metadata.json` describes the arrays, their
shapes, and the upstream pin, so the file is interpretable without reading
`fit_model.py`.

### Artifact roles

Roles are declared per file in `expected_files.yaml` and projected by the Server
into the result manifest, which is what groups the Files & diagnostics rail. The
judgement is the Runner's because the Runner is what knows what each file is; the
per-file reasoning is in `SCIENTIFIC_TRACEABILITY.md` §5.

| File | Role | One-line reason |
| --- | --- | --- |
| `summary.json` | provenance | Run metadata and parameter echo |
| `query.fasta` | artifact | Input echo, not derived |
| `alignment/filtered_alignment.a3m` | evidence | The alignment that was modeled |
| `alignment/statistics.json` | provenance | Counts, Neff, gap statistics, parameters |
| `alignment/sequence_weights.tsv` | evidence | Per-row phylogenetic weights |
| `model/gremlin_mrf.npz` | evidence | The durable fitted model |
| `model/metadata.json` | provenance | Array descriptions and upstream pin |
| `model/training_history.csv` | diagnostic | Optimization history, not a conclusion |
| `model/sequence_scores.tsv` | evidence | Per-sequence pseudo-likelihood and Hamiltonian |
| `profiles/profile.tsv` | evidence | Observed per-position state frequencies |
| `couplings/pairwise_scores.tsv` | evidence | Ranked residue pairs |
| `couplings/raw_scores.csv` | evidence | Raw coupling matrix (primary view source) |
| `couplings/apc_scores.csv` | evidence | APC coupling matrix (comparison view source) |
| `plots/coupling_apc.png` | diagnostic | Static rendering of the APC matrix |

The only `artifact` entry is the query echo, and no scientifically meaningful
output is left in the generic "Other files" group.

## Reading the result

**Hierarchy.** The primary result is the **raw** Frobenius coupling matrix, and
the **APC** matrix is a declared comparison view. Both render as interactive
matrices, but with **different colour scales**, because the two quantities have
different sign domains: the raw matrix is a Frobenius norm (`M_ij = √(Σ_ab
W_ia,jb²) ≥ 0`) and uses a *sequential* scale, while the APC matrix is signed
after the correction and uses a *diverging* scale centred on zero. This follows
the paper's thesis
(PRX Life §II.D): for an LH fit the raw matrix is the object whose contact
precision is claimed to be sufficient without post-correction, so it is the
primary scientific surface, while APC remains the baseline the argument is
measured against. The "already approaches the corrected one" part of that
argument is the paper's asymptotic benchmark for its tuned weights on its own
1k–20k-sequence alignments, not a property of any single run: on this Runner's
6×79 reference case the APC term is still comparable to the matrix it corrects
(`‖AP‖ / ‖raw‖ ≈ 0.45` over the off-diagonal entries), so the APC matrix remains
a genuinely different view there. The decision and its evidence are in
`SCIENTIFIC_TRACEABILITY.md` §4. The shape of the published result surface — the
ordered views, the narrative, and which logical file each section draws on — is
owned by the Task's `result_workspace` and the family Storyboard, which read the
same declarations this page summarizes.

**Profile semantics.** `profiles/profile.tsv` reports the **observed per-position
state frequencies** of the modeled alignment, with consensus, entropy, and gap
fraction. It is a profile / per-position state-frequency table, deliberately not
called a PSSM: no background distribution and no log-odds scoring are defined for
it.

**Coupling semantics.** `couplings/pairwise_scores.tsv` ranks the upper-triangle
residue pairs by APC-corrected coupling strength and keeps the raw score in the
same row. A coupling score is a **statistical dependence in the fitted model**. It
is not by itself proof of a physical contact, of causality, or of functional
coupling; reading the scores as contact evidence is a downstream use of them and
carries its own assumptions (sequence separation, contact definition, and so on).

**Sequence scores.** `model/sequence_scores.tsv` carries the model's
pseudo-likelihood loss and its **Hamiltonian** per row. The Hamiltonian is the
model's statistical MRF energy — it is not a thermodynamic free energy. The
source paper reports *empirical* correlations between its Hamiltonian and measured
stability for particular designed datasets (PRX Life §II.E, with the
interpretability case studies in §II.G); those results are system-specific and
support no stability, fitness, or functional claim about any run of this Runner.
(The §II.F phylogenetic-clustering findings are likewise empirical and about
sampled sequences, not about this Runner's output.)

**Citations.** The method and model citations travel in the run provenance
(`summary.json`, and the Server-published `citations.bib`) rather than on the
result surface.

## Databases, mounts, and network

None. This family consumes a user-supplied alignment, has no pretrained weights,
no managed sequence database, and no runtime mounts; normal execution performs no
downloads, so there is no database-preparation or cache procedure. The upstream
experimental DMS table and the paper benchmark archives are not required to fit a
user MSA and are not copied into the image.

## Runtime and resource envelope

- CPU-only JAX; no GPU requirement and no accelerator accounting.
- The coupling tensor is `L × K × L × K`, so compute and memory grow at least
  quadratically with alignment width. The Runner rejects alignments wider than its
  declared production limit of 512 positions, and the number of optimization
  updates is bounded by the Task's server-projected parameter schema; read the
  schema rather than this page for the bound.
- The full Python closure is pinned in `requirements.lock`. The build evidence
  for the current candidate image, including its checksum, is recorded in
  `MODEL_AND_LICENSE.md`; a local checksum is build evidence, not a deployment
  receipt.

## Failure behavior

`run.sh` fails closed: any non-zero stage exit aborts under `set -euo pipefail`,
and the post-fit check rejects a nominally successful fit that produced a missing
or empty declared artifact. The result contract is never published on a failed
run.

| Condition | Detected by | Message |
| --- | --- | --- |
| Missing/unknown input role | `task_input` | `unknown input role` |
| Fewer than two rows | `parse_alignment` | `at least two sequences` |
| Unequal row widths | `parse_alignment` | `unequal widths` |
| Unsupported residue | `parse_alignment` | `unsupported residues` |
| Width over the production limit | `parse_alignment` | `exceeds the production limit` |
| No usable columns at gap cutoff | `sequence_weights` | `no alignment columns remain` |
| Non-finite model | `main` | `non-finite model values` |
| Missing/empty artifact | `run.sh` | `did not produce required artifact` |

Upstream search and database failures cannot occur, because this Runner performs
neither. Large subprocess logs are not surfaced to users; the bounded Runner log
remains a downloadable diagnostic.

## Scientific acceptance

Two layers are kept deliberately separate; neither is a substitute for the other.

```bash
# Fast protocol contract (tiny synthetic fixture) plus Runner-owned unit logic.
# Needs jax/optax/matplotlib and skips those cases when the stack is absent.
python -m pytest docker/runners/gremlin_lh/tests -q

# Generic family contract (Doctor).
python -m revocompute doctor --config-root docker/runners --runner gremlin_lh --strict

# Regenerate the frozen receipt from the pinned notebook (maintainer only; not CI).
python docker/runners/gremlin_lh/tests/scientific/references/generate_upstream_reference.py \
    --upstream /path/to/GREMLIN_LH_outline_7.ipynb
```

`test_runner.py` runs the real `run.sh` against a protocol manifest and asserts
the declared artifact tree, model dimensions, profile/coupling indexing, and
summary consistency. It uses the tiny synthetic fixture: it proves the protocol
contract, **not** scientific equivalence.

`test_upstream_equivalence.py` is the scientific acceptance. It runs the Runner's
real fitting code with the receipt's upstream-compatible parameters on
`tests/data/msa/2KL8.i90c75_aln.a3m` — a six-row, 79-column homolog set for the de
novo designed 2KL8 protein, produced by the mock pipeline documented in
`tests/data/msa/README.md`, so it is the repository's canonical small real-shaped
MSA — and compares sequence weights, Neff, the one-body fields, coupling blocks,
the tensor norm and maximum magnitude, the full raw and APC matrices, the
per-sequence pseudo-likelihood and Hamiltonian, and the strongest APC pairs
against `docker/runners/gremlin_lh/tests/scientific/references/upstream_reference.json`. Every tolerance has a
stated reason in `SCIENTIFIC_TRACEABILITY.md` §6; the current implementation
passes with 20–100× margin.

The receipt is not an unexplained blob: it records the upstream repository, the
pinned commit, the notebook blob and file hashes, the input hash, the dependency
versions, the parameters, the seed, and the generation procedure, and it retains
the uncorrected pinned values so the intentional deviations stay visible.

## Where this earns its claims, and where it does not

What the evidence chain supports: the default fitting path is a faithful,
auditable transcription of the pinned notebook; every deliberate difference is
classified, measured, and disclosed; the scientific quantities that reach the
user are reproduced from the upstream implementation within stated float32
tolerances; the durable model state is complete and interpretable; and the
result surface separates statistical dependence from contact, causality, and
thermodynamics. It does **not** support calling this Runner a benchmark of the
paper's results — the paper's protein-scale contact-prediction, design, and
stability experiments are not reproduced here, and nothing in this family's
outputs should be read as a stability or fitness prediction.

See also [`MODEL_AND_LICENSE.md`](MODEL_AND_LICENSE.md) for the retained upstream
license notice and pinned source, the platform
[Adding a Runner](../../../docs/runner-guide/adding-a-runner.md) guide.
