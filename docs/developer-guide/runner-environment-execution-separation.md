# Runner Environment–Execution Separation — PR #131

> Status: implementation proposal, not a claim of delivered behavior.
> Base: the merged composable-execution foundation from PR #130.
> Normative existing contract: [Runtime Bundles](../runner-guide/runtime-bundles.md).
> Principle: **build the scientific environment; mount the scientific execution code**.

## Problem and boundary

The runtime-bundle infrastructure already snapshots repository-owned code as immutable,
content-addressed, read-only overlays, pins the digest per family in the Task, and gates
activation on live scientific acceptance. Yet AlphaFold 3, GREMLIN_LH and PSSM-GREMLIN
still copy their REvoCompute execution scripts into SIF images through `%files`, and
declare those scripts in `build_inputs`. An edit to a run script therefore changes
the SIF build provenance even if the underlying scientific software stack is unchanged.

This campaign **migrates the three actual family implementations** and connects the
existing build, readiness, receipt, and activation lifecycle. Do not build a second
bundle manager, provenance ledger, admission path, or artifact store.

There are three independently versioned inputs to a reproducible Task:

1. **SIF environment identity**: Apptainer definition, base OS, scientific
   dependencies/locks, native packages, pinned upstream software and generated
   installation artifacts. A change here requires SIF rebuild and acceptance.
2. **Runtime Bundle identity**: REvoCompute-owned executable adapters, scripts,
   algorithm implementations and stage-input resolvers. A change here requires a
   new immutable bundle and scientific acceptance, but **not** a SIF rebuild.
3. **Execution and scientific-data identity**: frozen graph, input and artifact
   identities, parameter contract, model/database provenance and resource policy.
   Changes that affect acceptance must be revalidated; unrelated presentation
   changes must not invalidate the scientific receipt.

A file must never silently participate in both SIF and Runtime Bundle identity.
Do not remove `build_inputs` as a schema field: it correctly records genuine
environment dependencies and remains allowed to be empty.

## Target family mapping

| Family | Keep as SIF build input/environment | Move to Runtime Bundle | Important migration work |
| --- | --- | --- | --- |
| `alphafold3` | `alphafold3.def`, pinned upstream AF3, CUDA/Python, HMMER, compiled packages | `alphafold3/run.sh` plus existing `common/runtime/task_context.*` | Remove script `%files` and `chmod`, change manifest entrypoint; preserve AF3 features/model behavior and AF3 licensing boundary |
| `gremlin_lh` | `gremlin_lh.def`, `gremlin_lh/requirements.lock`, JAX/NumPy/SciPy/Optax/matplotlib environment | `gremlin_lh/run.sh`, `fit_model.py`, `stage_inputs.py`, shared context | Replace `/app/revocompute/fit_model.py` and associated in-image imports/paths; preserve alignment role verification and Potts output contract |
| `gremlin` (source directory `pssm_gremlin`) | `pssm_gremlin/gremlin.def`, `GREMLIN.yml`, Conda TF/GREMLIN, HHblits/HHfilter/PSI-BLAST executables | `pssm_gremlin/run.sh`, `stage_inputs.py`, the `scripts/` algorithm directory, shared context | Preserve two Python environments (legacy Conda scientific Python and modern resolver Python), stage selection `msa|fit|pssm`, produced-artifact role checks, existing output layouts |

`%files` is allowed for an environment lock required during `%post`, but must
not copy REvoCompute runtime/algorithm code. `%post` must not chmod runtime
code that is no longer in the image; `%test` checks the environment only.
Production execution uses `apptainer exec` and the manifest's explicit
`entrypoint`, **not** the image's `%runscript`. Remove or neutralize legacy
`%runscript` so it does not invoke an image-baked script. If an environment
truly requires compiled/generated REvoCompute code inside the image, justify
and test that exception explicitly; do not silently loosen the boundary.

The container path for a snapshot is
`/opt/revocompute/runtime/<family-source-dir>/...`; the family ID
`gremlin` maps to directory `pssm_gremlin`. Relative helpers and imports
must resolve from the script's actual location in the mounted snapshot rather
than from a mutable working directory or `/app/revocompute`. Any path override
for testing must not become an unverified production fallback.

## Expected change classification

| Change | SIF/build provenance | Runtime Bundle | Live-test behavior |
| --- | --- | --- | --- |
| Edit `run.sh`, `fit_model.py`, `stage_inputs.py`, or GREMLIN scripts | Unchanged | New digest | New candidate snapshot; scientific live-test required before activation |
| Edit `requirements.lock`, `GREMLIN.yml`, `.def`, or pinned upstream version | Changed | Unchanged unless overlay also changed | New candidate SIF; scientific live-test required |
| Edit both classes | Changed | Changed | Validate the exact new pair |
| No changes | Unchanged | Unchanged | No redundant build or re-acceptance if current identity and receipt remain valid |
| Change task execution contract, stage outputs, input bindings, or test specification | Usually unchanged | Usually unchanged | Revalidate receipt/contract as existing policy requires |
| Change presentation-only labels/docs | Unchanged | Unchanged | No scientific re-acceptance |

“Trigger live test” means a **gated controller/deployment operation**, not a
filesystem watcher that silently executes HPC workloads. The controller must
report the needed action, materialize and validate a candidate without
activating it, and publish only after acceptance. Integrate the established
CLI/workflow paths; do not create a second deployment orchestrator. Distinguish
a one-off server worker image build from a **scientific SIF rebuild** when
reporting zero rebuilds.

## Build, admission and promotion invariants

- The exact same normalized sources define a SIF's build identity across
  local checks and deployment. The contents and executable mode of the
  declared overlay alone define the Runtime Bundle digest.
- A Task pins `runtime_bundles: {family: digest}` for **every executing family**;
  a later activation may not change queued/running Tasks.
- The Slurm adapter resolves the pinned digest, verifies immutable bundle
  content and mounts it read-only at the reserved root. Missing/corrupted,
  unlisted, stale, or unverified executable input refuses before submission.
  No fallback to `/app/revocompute/run.sh` or checkout paths.
- Cross-family compiled graphs retain the verified producer-output-to-consumer
  role binding introduced in PR #130. Preserve per-stage StageRun identity,
  allocation and GPU accounting; do not turn serial branches into concurrency.
- Composed acceptance binds **all** participating SIF hashes, build
  provenances and Runtime Bundle digests. Companion SIF/bundle changes
  invalidate the relevant receipt. A single-family receipt cannot bless a
  foreign stage merely because its owning stage passed.
- Candidate bundles/SIFs are **not** production active by construction.
  Refusal or live-test failure leaves previous active identities intact.
  Activating a successfully tested bundle is permitted only via the existing
  controlled mechanism, never as a side effect of a failed test.
- Retention/GC must preserve the old immutable bundle for active, queued and
  running Tasks. Version rollback is switching the active index to an accepted
  prior identity, not rewriting historical snapshots.

## Regression and scientific acceptance

The PR is not complete when the YAML passes linting. Use a mutation-sensitive
matrix, implemented in the existing server/runner/fleet test suites:

1. Modify **only** each family adapter/algorithm file: assert unchanged
   `build_provenance_digest`, changed bundle digest, zero scientific SIF
   rebuild requests, stale/new acceptance before activation, and refusal
   to execute an unpinned or corrupt bundle.
2. Modify **only** the environment lock or `.def`: assert SIF identity changes,
   rebuild requested, and a previous receipt cannot authorize it.
3. Unchanged inputs: assert no-op behavior (no unnecessary rebuild/retest).
   Mixed changes must require acceptance of the exact SIF+bundle pair.
4. Verify the actual `ExecutionPlan.command` and generated Slurm/Apptainer
   wrapper target the pinned overlay, without an in-image or mutable-source
   fallback. Test correct executable modes, missing scripts, unexpected
   symlinks, digest tampering, and bundle removal after submission.
5. Verify both the legacy single-family GREMLIN stages and the composed
   `gremlin_msa_to_lh_fit` path with real output identities, verified alignment
   passed via `TASK_STAGE_INPUTS`, and no reuse of an unverified shared file.
   Validate AF3 `features -> model` on the existing SIF/overlay pair with
   immutable output provenance. A code-path presence assertion is insufficient.
6. Verify the non-GPU and GPU stages' scheduler allocation, accounting and
   fail-closed refusal paths. Preserve existing gate behavior across family
   discovery, disabled families and partial installations.
7. Check the CI change classifier and existing `RunnerFastContracts`,
   `RunnerScientificAcceptance`, `REvoComputeTests`,
   `ServerComposeFullStack`, and documentation. CI scientific tests may use
   isolated dependencies/stubs for contract mutation checks; do **not**
   mistake those results for real SIF/Slurm acceptance.

Before final campaign acceptance, report **real isolated Apptainer/Slurm
scientific evidence** on the exact PR head for the three migrated families:
AF3 GPU `features -> model`, standalone GREMLIN_LH, GREMLIN MSA/fit/PSSM,
and GREMLIN MSA -> GREMLIN_LH across families, including SIF and bundle digests,
StageRun/Slurm IDs, artifact hashes, scientific result validation and
allocation/ledger facts as applicable. First migration **does require**
building new candidate SIFs because the definitions changed; the proof of
zero rebuild concerns subsequent overlay-only mutations. Do not use an old
receipt as exact-head acceptance after acceptance-code changes.

## Out of scope and control

Do not automatically migrate the rest of the Runner Fleet. Produce a **fleet
audit** listing remaining baked script/algorithm entrypoints and justified
environment-coupled exceptions, for a separate rollout. Do not change the
scientific algorithms, rewrite resource accounting, introduce a new bundle
store, change license policies, add Nextflow, or authorize production changes.

PR is **Draft / NO MERGE** until exact-head CI, mutation-sensitive evidence,
isolated scientific acceptance, independent technical/security/scientific
reviews, Examiner and final Campaign Acceptance Auditor PASS. Maintainer alone
authorizes squash merge, production deployment, restart, migration and SIF
promotion. Keep the Independent Campaign Adviser active; post substantive
findings and receipts in PR threads as the canonical technical record.
