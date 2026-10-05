# Persistent Batch Equivalence and Adaptive OOM Scientific Provenance

## Objective

Close the scientific-correctness gap around the persistent multi-input and
adaptive OOM machinery introduced for structure-folding Runners.

This PR combines two ordered questions:

1. **Persistent batch equivalence:** does processing several inputs in one
   model-loaded task preserve each input's result relative to the corresponding
   single-input execution under the same effective scientific parameters?
2. **OOM provenance:** when recovery changes execution parameters, can a reviewer
   reconstruct exactly what was requested, what was actually used for each
   attempt/item, and whether the change can affect scientific output?

The target reference Runners are **ESMFold2 and SimpleFold**, matching the
existing persistent-runner/OOM work.

Do not redesign the persistent scheduler or build a new estimator.

---

## 0. Campaign position and dependencies

This is a **Wave 3** PR.

It can proceed in parallel with the fleet-result/browser-golden PR after the
Wave 2 dependencies have merged.

This work requires GPU live acceptance. Coordinate one exclusive deployment/
live-test lease through the Commander.

Do not use a host that cannot provide the required GPU/runtime and then replace
live acceptance with a synthetic claim.

---

## 1. Freeze the comparison contract before testing batch mode

For each target Runner identify which parameters affect scientific output and
which affect only resource/execution behavior.

Create an explicit classification such as:

```text
scientific/effective parameters
resource-only execution controls
recovery controls
provenance-only metadata
```

Do not assume chunk size, sample count, MSA controls, kernel backend, precision,
or similar controls are scientifically neutral without checking the Runner.

The equivalence test must compare executions with the same **effective
scientific parameters**, not merely the same user request.

---

## 2. Select a bounded sequence panel

Use a small deterministic panel of approximately 3-5 protein sequences spanning
meaningfully different lengths while remaining cheap enough for repeated GPU
acceptance.

Requirements:

- exact sequence hashes;
- no duplicate sequences;
- at least one short, one medium, and one longer case that exercises scheduling
  decisions without intentionally exhausting the GPU in the baseline run;
- fixed seeds where the Runner exposes stochastic sampling;
- stable provenance for the panel.

Do not use huge proteins merely to force OOM in the equivalence phase.

---

## 3. Single-input baseline

Run every panel item independently with the canonical default/non-recovery path.

Capture for each item:

- input hash;
- requested parameters;
- effective parameters;
- model/runtime identity;
- device profile relevant to deterministic behavior;
- output artifact hashes;
- scientific observables appropriate to that Runner.

Define the observable comparison from artifact semantics.

For structure prediction this may include, as available:

- residue count/sequence identity;
- coordinates after appropriate atom matching/alignment;
- per-residue confidence;
- global confidence;
- PAE or equivalent matrix;
- number/order of samples.

Do not rely on raw file-byte equality if harmless metadata/order makes that
scientifically inappropriate.

---

## 4. Persistent multi-input run

Run the same panel in one persistent task so the model remains loaded across
items.

Prove:

- every input maps to exactly one result item;
- no result is associated with another sequence;
- item ordering changes do not cross-contaminate results;
- the effective scientific parameter set for each item matches its single-run
  baseline;
- scientific observables match the single-run baseline within justified
  Runner-specific tolerances;
- an item failure does not silently relabel a later item's result;
- durable item status survives process/task bookkeeping.

Where deterministic exact equality is expected, assert it.
Where floating/reduction-order differences are legitimate, derive measured
tolerances and document them rather than widening them ad hoc.

---

## 5. Restart/resume equivalence

Exercise a controlled interruption after at least one item has completed.

After restart/recovery prove:

- completed items are not recomputed unless the contract explicitly requires it;
- pending items continue;
- no item is duplicated or lost;
- restored execution uses the same immutable task/input snapshot;
- already published item results remain unchanged;
- final aggregate manifest has one coherent item identity set.

Compare resumed results against the uninterrupted persistent baseline.

---

## 6. Forced OOM test boundary

Only after ordinary single-vs-persistent equivalence is established, exercise
the adaptive OOM path.

Use deterministic test hooks or a bounded live case capable of triggering the
existing recovery mechanism without risking node stability.

Do not create an intentionally dangerous allocation simply to produce a real
OOM if the same recovery state can be safely induced by an existing supported
test mechanism.

The purpose is to audit recovery semantics, not stress the cluster.

---

## 7. Requested versus effective provenance

For every item/attempt, persist enough provenance to reconstruct:

```text
requested parameters
estimator recommendation
attempt number
recovery rung/action
effective parameters
device/profile identity
OOM/failure observation that justified the transition
final successful parameter set
```

Use existing attempt/resource observation stores when possible.

Do not create a second opaque provenance database.

The final Result/receipt surface must make scientifically meaningful mutations
auditable. A user should not have to infer them from scheduler logs.

---

## 8. Scientific-impact classification of recovery actions

Audit every existing recovery action used by ESMFold2/SimpleFold.

Classify it as:

- resource-only, expected not to change scientific result;
- numerical/backend change that may change floating behavior;
- scientific-output change (for example changing samples/MSA/model behavior);
- unsupported/unsafe for automatic mutation.

For a resource-only recovery action, verify the final result remains equivalent
to the no-recovery baseline within the established comparator.

For a scientifically meaningful mutation, do **not** call the result equivalent
to the original request. Instead prove the requested/effective divergence is
explicit in provenance and user-visible result metadata where appropriate.

Automatic recovery must never silently change a scientific parameter.

---

## 9. Monotonicity and retry discipline

Preserve the existing bounded OOM design.

Verify:

- no-op recovery plans do not consume a misleading scientific transition;
- the recovery ladder is monotone with respect to intended resource relief;
- retry count remains bounded;
- a measurement-hook failure does not masquerade as an OOM;
- evidence from incompatible Runner/model/device revisions is not pooled
  silently;
- all-failed tasks remain failed with non-zero/terminal failure semantics.

Do not redesign the estimator unless a correctness defect is required to satisfy
these invariants.

---

## 10. Result provenance

Extend the smallest existing result/provenance surface necessary so downstream
users and tests can tell:

```text
requested == effective
```

or

```text
requested != effective because OOM recovery selected <action>
```

for each item.

Keep diagnostics subordinate to the scientific result, but do not hide a
scientific mutation.

If the current ResultManifest already has an appropriate provenance channel,
use it. Do not introduce a ResultManifest v4 merely for convenience.

---

## 11. Required tests

### Fast/unit/integration

Cover:

- per-item requested/effective parameter capture;
- mapping of item identity to output;
- order independence;
- restart reconstruction;
- duplicate/lost-item prevention;
- forced OOM transition;
- bounded retries;
- recovery action classification;
- provenance persistence;
- all-failed behavior.

### Live scientific acceptance

For **both ESMFold2 and SimpleFold** on an appropriate GPU target:

1. run bounded single-input baselines;
2. run the same panel persistently;
3. compare scientific observables;
4. perform one controlled restart/resume scenario where practical;
5. exercise at least one safe OOM-recovery path;
6. verify final requested/effective provenance.

Record exact head, GPU/device profile, Runner/model identity, task ids and
artifact/result evidence.

---

## 11a. Evidence layers

This PR rests on three distinct evidence layers, and must never blur them:

1. **Mock GPU Example Runner** (`docker/runners/mock_gpu_example/`) — proves the
   *mechanism*: the real `PersistentTask` lifecycle, the bounded recovery
   ladder, per-attempt recovery provenance, restart/resume identity, and the
   server projection, end to end, on a configurable **pseudo-device** with no
   GPU, model, weights, or production SIF. It is a test/reference artifact and
   makes no scientific claim about any real model.
2. **Real ESMFold2 / SimpleFold runtime** — the model-specific *scientific*
   evidence: single-input vs multi-item execution with the real pinned model and
   weights (see the SimpleFold result below; ESMFold2 is an evidenced hardware
   limit on this device).
3. **Production SIF + Slurm** — the *deployment/package* integration, exercised
   by the live-test receipt and Doctor gates.

Layer 1 is complete in-repo and runs in CI. Layer 3 is the deployment gate. On
layer 2, the available accelerator supports only one of the two target Runners:

### Measured accelerator feasibility (lab309, Quadro P4000 8084 MiB, CC 6.1)

Probed with the pinned upstream code and the sha256-verified released weights,
**outside** the production SIF.

#### ESMFold 2 — definitively infeasible on this device

The ESMC-6B backbone alone is **23.66 GiB fp32 (25,408,148,888 bytes across six
sha256-verified shards) = 11.83 GiB fp16**, against a device with 7.90 GiB total
/ 7.07 GiB free. A direct device allocation of the exact backbone byte size
fails at fp32 and at fp16 (`CUDA out of memory ... 7.90 GiB capacity ... 7.07
GiB free`); even the fp16 representation exceeds the device before any structure
module or activation. Pascal cc6.1 supports fp16 but not bf16/TF32, and no
supported precision or the family's own `cpu_offload`/`chunk_size` controls
reduce a 23.66 GiB resident backbone to fit. No forward pass is attempted
because the first shard cannot be placed.

#### SimpleFold — model-level layer-2 equivalence OBTAINED

The pinned `ml-simplefold` revision (c7a5570a6be9f5c695126e27c804e77567209934)
was run on the real P4000 (torch 2.9.0+cu126, CUDA 12.6) with the released,
sha256-verified `simplefold_1.6B.ckpt`
(`aaac2d73…`) and `esm2_t36_3B_UR50D.pt` (`7de8b408…`). A bounded 3-sequence
panel was executed twice — once as independent single-input runs, once in one
model-resident multi-item process (ESM conditioning computed once per item,
folding model loaded once, items consumed in turn) — at **fixed effective
scientific parameters** (model `simplefold_1.6B`, `num_steps=50`, `tau=0.01`,
multiplicity 1, per-item seed `base_seed + item_order`).

| item | length | seq sha256 (first 16) | item seed | single coords sha256 (first 16) | multi-item coords sha256 (first 16) |
| --- | ---: | --- | ---: | --- | --- |
| item0 | 52 | `444a15b706a32daa` | 42 | `ec99873dc04a65e5` | `ec99873dc04a65e5` |
| item1 | 51 | `932d0841f4b170c9` | 43 | `c31a1bcb88f087fa` | `c31a1bcb88f087fa` |
| item2 | 50 | `4538294bd1311cd9` | 44 | `aabdd1cba3efe460` | `aabdd1cba3efe460` |

Single vs multi-item were **BITWISE IDENTICAL** for every item — identical
denoised-coordinate tensors and identical output mmCIF sha256. This is per-item
identity mapping with no cross-contamination, no duplicate or lost item, and
result order-independence under one model-resident process. Peak device memory
was ~6159 MiB single / ~6202 MiB multi-item.

**Scope of this evidence.** This proves **model-level** determinism and
persistence: the real pinned model, sampling algorithm, featurization, and
per-item seeding, order-independent and reproducible across single vs multi-item
execution. It was obtained **outside** the reviewed plugin's own
`initialize_runtime`, which co-resides the folding model with ESM-2 3B (fp32)
and OOMs on this 8 GiB device (folding model 6.10 GiB, then the second
foldingdit latent module cannot be placed). Execution through the reviewed
`SimpleFoldPlugin`/Runner path — its own `pl.seed_everything(seed + group_start)`
seeding, its `_sample_group` loop, and its `process_fastas` path — was **not
exercised** and remains deferred; making it fit here would be a production-CUDA
change. This evidence does **not** assert that the reviewed plugin's persistent
execution is scientifically verified.

The comparison also established the adaptive-OOM boundary on the real model:
multiplicity-1 draws everything; explicit-multiplicity probes measured peak 6312
MiB (×4), 6517 (×8), 6911 (×16) and **OOM at ×32**, so a scientific-output
`sample_group_size` rung is the natural OOM recovery and lowers instantaneous
memory. The review panel itself ran at multiplicity 1.

---

## 12. Gates

Run existing persistent-runner tests, ESMFold2 and SimpleFold protocol tests,
OOM estimator/recovery tests, result provenance tests, and the appropriate
non-browser repository gate.

Run targeted browser/result tests only if the user-visible provenance surface is
changed.

Run `mkdocs build --strict` when docs change and `git diff --check`.

Because this PR makes a live scientific statement, exact-final-head GPU
acceptance is required before `READY_FOR_FINAL_REVIEW`.

---

## 13. Scope exclusions

Do **not**:

- add Triton;
- replace the existing estimator with a new ML architecture;
- redesign PersistentRunner;
- redesign Slurm scheduling;
- generalize immediately to every batch-capable Runner;
- treat a completed task as proof of scientific equivalence;
- use byte equality where the format has irrelevant nondeterministic metadata;
- hide requested/effective parameter divergence;
- widen scientific tolerances just to make the campaign green.

---

## 14. Definition of done

For ESMFold2 and SimpleFold, the repository must be able to prove:

> Persistent multi-input execution preserves each item's scientific result
> relative to the corresponding single-input execution when effective scientific
> parameters are unchanged; restart/resume preserves item identity; and any OOM
> recovery that changes effective behavior is explicit, bounded, and auditable
> rather than silent.

Status against this definition on the available accelerator:

- **SimpleFold** — model-level equivalence obtained (bitwise single vs
  multi-item, §11a). The reviewed `SimpleFoldPlugin`/Runner path itself is not
  exercised on this device (its `initialize_runtime` OOMs); that remains
  deferred and is stated as such.
- **ESMFold2** — an evidenced hardware limit on this device (ESMC-6B ≈ 23.66 GiB
  fp32 vs 7.90 GiB total; §11a). Its equivalence requires a larger GPU; this is
  not a deferral of an attainable run.
- **Item identity, restart/resume, and OOM classification/provenance** — proven
  on the persistent runner's item machinery and end-to-end on the mechanism-layer
  Mock GPU Example Runner (§11a).
