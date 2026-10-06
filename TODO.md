# Persistent Item Correctness and Adaptive OOM Provenance

## Objective

Close the correctness gap around the persistent multi-item and adaptive OOM
machinery introduced for structure-folding Runners. This is an
**infrastructure / execution-semantics** change, and its merge-blocking claim is
scoped to what that machinery owns:

> Persistent multi-item execution preserves item identity and deterministic
> execution semantics; restart/resume is coherent; adaptive-OOM transitions are
> bounded, scientifically classified, fail closed for unsafe mutations, and
> expose requested-versus-effective provenance.

The claim decomposes into the questions this PR actually answers:

1. **Item identity and deterministic execution semantics:** does processing
   several inputs in one model-resident task map each input to exactly one
   result, order-independently, with no cross-contamination, duplicate, or lost
   item?
2. **Restart/resume coherence:** does a restarted worker resume against the same
   immutable input snapshot without recomputing, duplicating, or losing an item?
3. **Adaptive-OOM provenance:** when recovery changes execution parameters, can a
   reviewer reconstruct exactly what was requested, what was actually used for
   each attempt/item, and whether the change can affect scientific output?

The **Mock GPU Example Runner** proves this mechanism-level claim in CI without
physical GPU hardware. Real-model evidence is **supplemental validation** of the
same machinery (see §11a), not a merge requirement.

The former target reference Runners, **ESMFold2 and SimpleFold**, remain the
motivating families, but their model-specific scientific equivalence is
supplemental evidence here and separate acceptance work elsewhere.

Do not redesign the persistent scheduler or build a new estimator.

---

## 0. Campaign position and dependencies

This is a **Wave 3** PR.

It can proceed in parallel with the fleet-result/browser-golden PR after the
Wave 2 dependencies have merged.

This is an infrastructure / execution-semantics change. Its merge-blocking
evidence is CPU-executable (the Mock GPU Example Runner and the persistent
runner's own tests); real-model scientific equivalence is supplemental and may
require a GPU lease coordinated through the Commander, but is **not** a
READY_FOR_FINAL_REVIEW gate here.

Record model-level GPU evidence when a host provides it; do not use a host that
cannot provide a runtime and then replace real evidence with a synthetic claim.

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

### Merge-blocking acceptance (CPU-executable, no GPU required)

Proven end-to-end on the **Mock GPU Example Runner** and the persistent runner's
own tests. This is the claim READY_FOR_FINAL_REVIEW rests on:

1. one input maps to exactly one committed result, in input order, independent of
   execution order (no cross-contamination, duplicate, or lost item);
2. restart/resume keeps committed items, loses none, and recomputes when the
   immutable input snapshot differs;
3. a real (pseudo-device) OOM walks the declared, bounded, monotone fallback
   ladder; no-op plans consume no attempt;
4. every recovery action carries its scientific-impact class; a plan naming a
   scientific parameter is refused before execution and recorded;
5. per-attempt requested-versus-effective provenance persists in `work_items.json`
   and is republished by the server projection.

### Supplemental: real-model scientific validation

Recorded when a host provides the runtime; **not** a merge gate for this
infrastructure change. See §11a for what was obtained and what remains deferred.

---

## 11a. Evidence layers

This PR rests on three distinct evidence layers, and must never blur them. The
first is the merge-blocking one; the other two are supplemental:

1. **Mock GPU reference Runner** (`docker/runners/mock_gpu_example/`) ->
   *orchestration/recovery/provenance correctness*. It drives the real
   `PersistentTask` lifecycle, the bounded recovery ladder, per-attempt recovery
   provenance, restart/resume identity, and the server projection, end to end, on
   a configurable **pseudo-device** with no GPU, model, weights, or production
   SIF. It proves the mechanism and makes no scientific claim about any real
   model.
2. **Real ESMFold2 / SimpleFold runtime** -> *model-specific scientific
   validation* (supplemental; see the SimpleFold result below; ESMFold2 is an
   evidenced hardware limit on this device).
3. **Production SIF + Slurm** — the *deployment/package* integration, exercised
   by the live-test receipt and Doctor gates.

Layer 1 is complete in-repo, runs in CI, and is the merge-blocking evidence here.
Layers 2 and 3 are supplemental for this infrastructure change. On layer 2, the
available accelerator provides model-level evidence for only one of the two
motivating Runners:

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
OOM estimator/recovery tests, result provenance tests, the Mock GPU Example
Runner tests, and the appropriate non-browser repository gate.

Run targeted browser/result tests only if the user-visible provenance surface is
changed.

Run `mkdocs build --strict` when docs change and `git diff --check`.

The merge-blocking evidence for this infrastructure change is CPU-executable and
present in CI: the Mock GPU Example Runner and the persistent runner's own tests.
Real-model GPU acceptance is supplemental and is **not** required before
`READY_FOR_FINAL_REVIEW` here.

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

The repository must be able to prove:

> Persistent multi-item execution preserves item identity and deterministic
> execution semantics; restart/resume is coherent; adaptive-OOM transitions are
> bounded, scientifically classified, fail closed for unsafe mutations, and
> expose requested-versus-effective provenance.

This is proven for the persistent machinery, end to end, by the Mock GPU
reference Runner and the persistent runner's own tests (§11a, §12), and runs in
CI without physical GPU hardware. That mechanism-layer proof is the merge gate.

Supplemental real-model evidence, recorded here but **not** a gate:

- **SimpleFold** — model-level single vs multi-item execution is bitwise
  identical under the tested pinned model/parameters, with sha256-verified
  weights (§11a). The reviewed `SimpleFoldPlugin`/Runner path itself was **not**
  exercised on this device (its `initialize_runtime` OOMs) and is **not** claimed
  as verified.
- **ESMFold2** — cannot fit the available P4000; the measured memory evidence is
  recorded (§11a). Model-specific ESMFold2 equivalence is separate acceptance
  work on a larger GPU and is not required here.

The Mock GPU reference Runner proves orchestration, recovery, and provenance
correctness only; it does **not** prove model-specific scientific equivalence.
