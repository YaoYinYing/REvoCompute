# GREMLIN_LH Runner

CPU-only REvoCompute family that fits a regularized Potts/MRF model (fields and
pairwise couplings) to an **already aligned** protein MSA and publishes the
model, the modeled alignment, a per-position profile, and ranked pairwise
couplings.

This is the platform's reference-grade scientific Runner: it exercises external
scientific semantics, intermediate artifacts, durable model state, and
structured result interpretation through the unmodified Runner Family Contract.
It introduces no Runner-local descriptor, no Core-side GREMLIN logic, and no new
platform abstraction.

## Scientific source of truth

GREMLIN_LH's scientific semantics are owned by the upstream notebook, **not** by
this Runner:

| Item | Value |
| --- | --- |
| Upstream repository | <https://github.com/sokrypton/GREMLIN_LH> |
| Pinned commit | `6b8a6beb426fd31bb10c3fdd398abd3355b782f9` |
| Authoritative workflow | `GREMLIN_LH_outline_7.ipynb` (blob `79cc0fdaba25ff1a6d6cb12ab2a2ebc8358c2c17`) |
| Reference model-fitting path | notebook cells 7–14 (`parse_aln`, `mk_msa`, `jax_weights`, `jax_cov`, `jax_apc`, `GREMLIN`) |
| Fast protocol-contract input | `tests/data/msa/gremlin_lh_tiny.a3m` (8 rows × 8 columns, one insertion) |
| Scientific reference input | `tests/data/msa/2KL8.i90c75_aln.fas` (aligned homolog set) |
| Frozen upstream reference receipt | `tests/data/gremlin_lh/upstream_reference.json` |
| Expected major outputs | fitted `V` (fields) and `W` (couplings), raw + APC coupling matrices, per-position profile |
| Method citation | Wang H. et al., *PRX Life* 2, 023005 (2024). <https://doi.org/10.1103/PRXLife.2.023005> |
| Model citation | Kamisetty H. et al., *PNAS* 110, 15674–15679 (2013). <https://doi.org/10.1073/pnas.1314045110> |

`fit_model.py` transcribes the reusable JAX inference path into a deterministic,
headless command. Interactive notebook cells that download paper benchmarks,
invoke bmDCA, or build figures are not runtime entrypoints.

## Workflow stages

```text
alignment input (A3M or aligned FASTA)
        ↓ parse_alignment        strip A3M insertions, validate width/alphabet
        ↓ encode_alignment       one-hot over the 21-state alphabet
        ↓ sequence_weights       reweight phylogenetically similar rows
        ↓ fit_model              Adam optimization of fields + couplings
        ↓ coupling_scores        Frobenius norms, then APC correction
        ↓ sequence_statistics    pseudo-likelihood + Hamiltonian per row
        ↓ write_results          durable artifact tree (below)
```

`run.sh` emits `REVODESIGN_STAGE:gremlin_lh_fit` before fitting and writes
`task_finished` only after every declared artifact is present and non-empty.

## Result artifact tree

`expected_files.yaml` is the authoritative declaration; the tree is stable and
machine-readable:

```text
summary.json                          run-level metadata and artifact index
query.fasta                           the first alignment row as the query
alignment/
  filtered_alignment.a3m              insertion-stripped alignment that was modeled
  statistics.json                     counts, Neff, gap/filtering statistics
  sequence_weights.tsv                per-row phylogenetic weight
model/
  gremlin_mrf.npz                     durable MRF: fields, couplings, alphabet, weights
  metadata.json                       array shapes, parameter echo, upstream pin
  training_history.csv                loss / data loss / regularization per checkpoint
  sequence_scores.tsv                 pseudo-likelihood loss and Hamiltonian per row
profiles/
  profile.tsv                         observed per-position state frequencies
couplings/
  pairwise_scores.tsv                 ranked upper-triangle residue pairs
  raw_scores.csv                      raw Frobenius coupling matrix
  apc_scores.csv                      APC-corrected coupling matrix
plots/
  coupling_apc.png                    APC coupling heatmap
```

### The durable model artifact

`model/gremlin_mrf.npz` is the preserved model state, chosen because the upstream
implementation works with NumPy/JAX arrays and no recognized interchange format
exists upstream. It is a compressed `.npz` (not a Python pickle) containing:

| Array | Shape | Meaning |
| --- | --- | --- |
| `fields` | `(L, K)` | one-site log-potentials `V`; zero when one-site fields are disabled |
| `couplings` | `(L, K, L, K)` | symmetrized, mean-centered pairwise couplings `W` |
| `alphabet` | `(K,)` | state order; index 0 is the gap state |
| `sequence_weights` | `(N,)` | per-row phylogenetic weights |
| `gap_index` | scalar | index of the gap state in `alphabet` |

`L` is the alignment width, `K = 21`, and `N` is the row count.
`model/metadata.json` records the shapes and the effective parameters so the
artifact is interpretable without reading this file.

### Profile semantics

`profiles/profile.tsv` reports **observed state frequencies**, not GREMLIN
energies or a conventional PSSM. It is deliberately named a profile rather than
a PSSM: the columns are `alignment_position`, `query_position`, `query_residue`,
`consensus`, `entropy`, `gap_fraction`, then one frequency column per alphabet
state. Positions are reported in alignment indexing and mapped back to
one-based query indexing.

### Coupling semantics

`couplings/pairwise_scores.tsv` contains `rank`, `alignment_i`, `alignment_j`,
`query_i`, `query_j`, `query_residue_i`, `query_residue_j`,
`sequence_separation`, `raw_score`, and `apc_score`. Coupling strength is
statistical dependence, not by itself proof of a physical contact.

## Deliberate differences from upstream

Two notebook inconsistencies are resolved according to their stated scientific
intent and are recorded in source comments:

1. **Gap state.** The notebook declares the alphabet with the gap state first but
   its weighting routine reads the final amino-acid plane where it means the gap
   state. This Runner uses the explicit gap state so the documented gap-cutoff
   semantics hold.
2. **Field L2 penalty.** The notebook uses integer floor division when scaling
   the field penalty. This Runner uses ordinary division, preserving the evident
   intended penalty.

Further differences are exposed as Task parameters or bounded numerical guards.
Their effective values for any run are recorded in `summary.json.parameters` and
declared once in the owning `task.yaml`, which the server projects as the Task's
parameter schema; read that schema rather than this page for names, defaults, and
help:

3. **Inverse-covariance initialization default.** The notebook initializes
   couplings from the regularized inverse covariance. This Runner's default
   production profile initializes from zeros to stay within a bounded time and
   memory envelope, and exposes the upstream initialization as a Task parameter.
   The upstream-compatible setting is the one exercised by the reference
   scientific acceptance test (see below).
4. **Mini-batch clamping.** Upstream samples rows without replacement and fails
   when the alignment has fewer rows than the requested batch. This Runner clamps
   the effective batch to the row count, so small alignments fit with every row.
5. **Field pseudocount floor.** The notebook's field pseudocount is bounded below
   so a duplicate-only alignment (`Neff == 1`) still yields finite fields.

Upstream also hardcodes its sequence-weighting constants inside `GREMLIN` and
uses the unseeded global NumPy RNG. This Runner surfaces the weighting constants
as Task parameters and adds an explicit sampling seed for reproducibility. At the
upstream values these reproduce the notebook behavior except for the explicit
seeding.

No other scientific behavior is changed; any further method change belongs in a
separate scientific PR.

## Databases, mounts, and network

None. This family consumes a user-supplied alignment, has no pretrained weights,
no managed sequence database, and no runtime mounts (`runner.yaml` is
CPU/runtime-only). Normal execution performs no downloads. There is therefore no
database-preparation or cache-management procedure for this Runner.

## Runtime and resource envelope

- CPU-only JAX; no GPU requirement and no accelerator accounting.
- The coupling tensor is `L × K × L × K`, so compute and memory grow at least
  quadratically with alignment width. Input width is capped at 512 positions and
  optimization updates are bounded by the Task's server-projected parameter
  schema, so this page never copies a live parameter limit.
- Defaults to four BLAS/OpenMP threads; `runner.yaml` sets `max_runtime_seconds:
  7200`.
- The full Python closure is pinned in `requirements.lock`. A direct Apptainer
  build on 2026-09-10 completed its `%test`; that local candidate checksum is
  build evidence, not a deployment receipt.

## Failure behavior

`run.sh` fails closed: any non-zero stage exit aborts under `set -euo pipefail`,
and the post-fit artifact check rejects a nominally successful fit that produced
a missing or empty declared output. The result contract is never published on a
failed run. Typical failures and their messages:

| Condition | Detected by | Message |
| --- | --- | --- |
| Missing/unknown input role | `task_input` | `unknown input role` |
| Fewer than two rows | `parse_alignment` | `at least two sequences` |
| Unequal row widths | `parse_alignment` | `unequal widths` |
| Unsupported residue | `parse_alignment` | `unsupported residues` |
| Width over 512 | `parse_alignment` | `exceeds the production limit` |
| No usable columns at gap cutoff | `sequence_weights` | `no alignment columns remain` |
| Non-finite model | `main` | `non-finite model values` |
| Missing/empty artifact | `run.sh` | `did not produce required artifact` |

Upstream search and database failures cannot occur because this Runner performs
neither. Large subprocess logs are not surfaced to users; the bounded Runner log
remains a downloadable diagnostic artifact.

## Testing this family

Two acceptance layers are kept deliberately separate:

```bash
# Fast protocol contract (tiny synthetic fixture), plus Runner-owned unit logic.
# Needs jax/optax/matplotlib; skips those cases when the scientific stack is absent.
python -m pytest tests/runners/gremlin_lh -q

# Pinned-stack upstream scientific-equivalence acceptance.
pip install -r docker/runners/gremlin_lh/requirements.lock pytest
python -m pytest tests/runners/gremlin_lh/test_upstream_equivalence.py -q

# Generic family contract (Doctor) against all enabled families
python -m revocompute doctor --config-root docker/runners --runner gremlin_lh --strict
```

`tests/runners/gremlin_lh/test_runner.py` executes the real `run.sh` against a
`task.json` manifest and asserts the declared artifact tree, model dimensions,
profile/coupling indexing, and summary consistency. It uses the tiny synthetic
fixture so it stays fast; it is a protocol contract, not a scientific reference.

`tests/runners/gremlin_lh/test_upstream_equivalence.py` is the scientific
acceptance. It runs the Runner with the upstream-compatible parameter set
(regularized inverse-covariance initialization and the upstream LH optimizer
path) on a real aligned homolog set and compares sequence weights/Neff, the
one-site fields `V`, pairwise coupling blocks `W`, and the raw/APC coupling
matrices against `tests/data/gremlin_lh/upstream_reference.json`. That receipt is
derived from the pinned upstream notebook with the two documented corrections
applied, records the input hash, parameters, and provenance, and retains the
uncorrected pinned values so the intentional deviation stays visible. CI runs
this acceptance in the `RunnerScientificAcceptance` job against the Runner's
pinned dependency stack.

See also [`MODEL_AND_LICENSE.md`](MODEL_AND_LICENSE.md) for the retained upstream
license notice, and the platform
[Adding a Runner](../../../docs/runner-guide/adding-a-runner.md) guide.
