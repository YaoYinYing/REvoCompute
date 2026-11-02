# PR #131 — Environment / Execution Separation

**Campaign:** Runner Environment–Execution Separation
**Status:** M0-M4 complete at `ddcf4933`: exact-head CI green, independent reviews closed, and isolated Slurm/Apptainer acceptance green for AlphaFold 3, GREMLIN, GREMLIN_LH and the composed GREMLIN→GREMLIN_LH path, including the overlay-only no-rebuild experiment. Final Campaign Acceptance Auditor and maintainer merge authorization pending. NOT merge-ready.
**Base:** `main` at `8704d8ecc4c5b52b428ff09e4f7736bf5acebb62` (merged #130).
**Design:** [Runner Environment–Execution Separation](docs/developer-guide/runner-environment-execution-separation.md).
**Canonical existing contract:** [Runtime Bundles](docs/runner-guide/runtime-bundles.md).

## /goal

Complete the existing two-layer Runner architecture end-to-end: **SIF contains the
scientific environment, Runtime Bundle contains REvoCompute-owned executable
adapters and algorithm code**. Migrate AlphaFold 3, GREMLIN_LH and PSSM-GREMLIN
without changing their scientific semantics; connect change classification,
candidate construction, exact-pair live acceptance, safe activation and
rollback; prove that an execution-code-only change never rebuilds a scientific
SIF. Deliver mutation-sensitive CI contracts and actual isolated
Slurm/Apptainer scientific receipts. Keep #130's scientific dataflow, resource
governance and fail-closed provenance guarantees.

## Control protocol

- [x] Commander records exact starting `main`, head and branch; appoints
      Environment/Definition, Runtime/Family, Lifecycle/CI, and Scientific
      Acceptance Owners with nonoverlapping write scopes.
- [x] Independent Campaign Adviser stays active from design through final
      Auditor; independently challenges scope, security, exception rationale,
      scientific parity and merge readiness.
- [x] Every Owner reads this TODO, the design document, merged #130's relevant
      findings and the current PR discussions; use the PR threads as canonical
      technical record. Do not silently redefine old invariants.
- [x] Commander tracks only merge status, blocker category, Owner, Adviser
      verdict, exact head and CI. Delegate implementation and detailed
      technical issue history; do not flood top-level comments with unchanged
      states.
- [x] No production deployment, restart, destructive migration, Runtime Bundle
      activation in production, SIF promotion or merge without **separate**
      maintainer approval. Candidate builds and isolated scientific runs must
      be bounded and disclosed in-thread before execution.
- [x] Preserve serial DAG and Nextflow-disabled decisions from #130; no
      concurrency, ledger or workflow-backend redesign in this PR.

## M0 — Baseline and dependency inventory (Owners: Environment + Adviser)

- [x] At exact head, inventory every image-baked REvoCompute script, Python
      module, source-relative import, entrypoint, `%files`, `%post`, `%test`,
      `%runscript`, `build_inputs`, `runtime_overlay`, and runtime
      `runner.yaml` path override for all **three target families**.
- [x] Build a manifest-driven mapping of **environment dependencies** versus
      **REvoCompute executable/algorithm code**; include the reason for each
      retained baked file. Keep upstream scientific software version locks and
      binary/compiled dependencies in SIF.
- [x] Identify and record baseline output/artifact contracts and test fixtures:
      AF3 features/model, GREMLIN MSA/fit/PSSM, GREMLIN_LH direct fit and
      composed MSA -> GREMLIN_LH. Preserve both older Python/Conda GREMLIN
      execution and the newer stage-input resolver interpreter.
- [x] Record current build provenance hashes, bundle digests and existing
      receipt identities; mark which evidence will be invalidated by initial
      `.def` migration. Baseline receipt is not future-head acceptance.
- [x] Confirm existing controller paths for `build`, `runner-status`,
      `live-test`, candidate materialization and activation; discover
      actual accepted CLI arguments rather than inventing new flags.

**M0 exit:** source map and minimal migration diff reviewed by Adviser; no
implementation until environment/algorithm classification is defensible.

## M1 — Complete the three Family migrations (Owners: Runtime/Family)

- [x] **AlphaFold 3:** Remove `alphafold3/run.sh` from SIF `%files`,
      `%post chmod`, script-only `%test` and `build_inputs`. Declare
      `alphafold3/run.sh` in `runtime_overlay` beside current common
      helpers and point manifest `entrypoint` to
      `/opt/revocompute/runtime/alphafold3/run.sh`. Keep AF3 upstream,
      CUDA/Python and HMMER dependencies intact. Do not rebuild SIF for later
      changes to the runtime adapter.
- [x] **GREMLIN_LH:** Keep `requirements.lock` as SIF build input used by
      `%post`. Move `run.sh`, `fit_model.py`, `stage_inputs.py` into the
      declared Runtime Bundle. Remove their `%files` and in-image checks;
      change `GREMLIN_LH_FIT_MODEL` default and imports to the pinned bundle
      path. Retain file-role, digest and algorithm output validation. Test
      the existing direct-alignment and composed-stage invocation modes.
- [x] **PSSM-GREMLIN (Family ID `gremlin`):** Keep `GREMLIN.yml` in the
      SIF build class. Move `run.sh`, `stage_inputs.py` and all declared
      GREMLIN algorithm scripts into the immutable bundle. Update
      `REVODESIGN_RUNSCRIPT_PATH`, script imports and entrypoint without
      changing the selected `-s msa|fit|pssm|all` protocol, materialized
      alignment role or declared output names. Explicitly retain legacy
      scientific Python vs modern stage-input resolver Python.
- [x] Remove or neutralize image `%runscript` entries that call removed
      scripts. The authoritative production path remains
      `ExecutionPlan.command` + `apptainer exec`, never `apptainer run`
      relying on legacy code.
- [x] Reduce image `%test` to the **scientific environment** (imports, ABI,
      installed executables/versions). Execute algorithm/CLI tests through
      the mounted candidate bundle outside `%test`.
- [x] Verify no `/app/revocompute` fallback or other mutable/host checkout
      path can execute in these three families. No algorithm refactor or
      different numerical defaults under the guise of file relocation.

**M1 exit:** static audit and focused fast contracts prove execution path
relocation, exact artifact protocols, env/build inputs correctly separated.
The initial `.def` changes intentionally make new candidate SIFs necessary.

## M2 — Make build/test/activation choose the correct layer (Owner: Lifecycle/CI)

- [x] Reuse existing SIF build provenance logic and bundle materialization;
      audit all rebuild callers for hidden dependence on `run.sh`,
      `runtime_overlay` or Task presentation. Fix only identified gaps.
- [x] Verify `build_inputs` can legitimately be **absent/empty** for AF3;
      keep the field as a real environment-file inventory for GREMLIN_LH and
      GREMLIN. Reject illegal overlap with overlay files, including directory
      containment.
- [x] From an overlay-only change, report `SIF CURRENT / Bundle STALE`;
      materialize a candidate snapshot, **reuse existing SIF**, invalidate the
      mismatched acceptance, run the required live test and only then allow
      bundle activation. Do not trigger a scientific `apptainer build`.
- [x] From `.def`/lock change, report `SIF STALE`, build a candidate SIF,
      and require a live test of that exact SIF + pinned bundle identity.
      No hidden fallback to a previous SIF.
- [x] No-change rerun is idempotent: the previous accepted identity remains
      valid, and no pointless SIF rebuild or live test is scheduled. Treat
      changed runtime arguments/Task execution contracts separately according
      to existing scientific acceptance rules.
- [x] Preserve candidate-only materialization, old-Task digest pinning,
      cross-family companion identity and refusal of missing/stale bundles,
      and bounded retention/GC of still-referenced prior versions.
- [x] Audit existing CI scope classifier: algorithm changes must run fast and
      appropriate scientific contracts; environment changes require rebuild
      identity tests. CI must not claim to have built actual target-HPC SIFs
      unless it really did so.
- [x] Add concise operator documentation using **existing** controller
      commands for (a) SIF rebuild, (b) bundle-only candidate validation,
      (c) receipt/activation, (d) rollback. Include difference between one-off
      Docker worker image build and scientific SIF build.

**M2 exit:** negative and positive tests for both change classes, correct
readiness, exact-pair activation, no-op and rollback.

## M3 — Mandatory mutation-sensitive regression gates (Owners: Lifecycle + Runtime)

- [x] **Overlay-only mutation** for each target family: different bundle
      digest, **same** SIF build digest and SIF file bytes; assert the build
      controller does not invoke SIF rebuild and that the new bundle is not
      active without scientific acceptance.
- [x] **Environment-only mutation** for lock/definition: changed SIF
      build digest and rebuild request; old receipt cannot authorize new
      image. Removing this guard must fail the test.
- [x] **Mixed/no-change controls**: both changes revalidate exact pair;
      neither change triggers no unnecessary rebuild/retest.
- [x] **Execution path proof**: inspect produced Slurm wrapper/Apptainer
      command; resolve the pinned `/opt/revocompute/runtime/<family>/run.sh`,
      correct absolute/relative helper imports and executable mode; refuse
      missing script, tampered bundle, wrong mount, wrong pin or legacy
      image-path execution before allocation/submission.
- [x] **Immutable history**: Task A pinned to Bundle A still launches A
      after B activation; Task B pins B; removal/corruption of A refuses rather
      than silently switches to B; GC keeps active/in-flight pins.
- [x] **Scientific contract parity**: AF3 feature provenance and model
      publication; GREMLIN three stages and independent output identities;
      GREMLIN_LH model/coupling outputs; composed alignment bytes rehashed and
      read from the server-provided stage-input role, not an undeclared file.
- [x] **Cross-family acceptance invalidation**: modifying a companion
      SIF/bundle identity invalidates composed receipt; omission of a
      required companion or forged artifact refuses before submission;
      single-family cases retain correctly scoped receipts.
- [x] **Resource and tenancy boundary**: leave #130's stage-run
      durability, credit reservation, GPU admission, allocation accounting
      and licensed-family policy intact. Mutation-sensitive failure paths
      cannot be bypassed by relocated code.
- [ ] **Tests/CI**: focused suite; clean worktree full server suite;
      RunnerFastContracts and scientific CI; fleet/plugin discovery;
      ServerComposeFullStack; Documentation; browser lane when selected by
      classifier. Publish exact head and each test command/result.
- [ ] Independent Adviser verifies that a mutated `run.sh` does **not**
      appear in SIF `build_inputs`, that all runtime scripts are explicitly
      overlay-declared, and that scientific dependencies did not escape into
      the bundle.

**M3 exit:** every negative test fails on deliberate guard removal or wrong
classification; no green-only superficial test accepted.

## M4 — Isolated real scientific acceptance (Owner: Scientific Acceptance)

- [x] Secure bounded operator clearance for candidate SIF builds and
      isolated Slurm/Apptainer acceptance if needed. No production SIF
      promotion, restart or deployment implied.
- [x] Build the **new candidate SIF once per changed environment**; verify
      `%test`, build provenance, environment capability and SIF digest.
      This one-time rebuild is expected because the migration changes
      `.def`. Do not claim zero rebuild for initial migration.
- [x] Execute AF3 minimal `features -> model` CPU/GPU composed workflow
      with verified feature input, model results, Slurm resource receipt and
      GPU ledger settlement.
- [x] Execute GREMLIN's `msa`, `fit` and `pssm` with distinct
      StageRun/allocation IDs and validated declared artifacts.
- [x] Execute standalone GREMLIN_LH and real cross-family
      `gremlin_msa_to_lh_fit`: validate MSA SHA-256 of producer and consumer
      role, actual GREMLIN_LH fit outputs, and per-family exact SIF + Runtime
      Bundle identities. No sample/stub scientific pass allowed here.
- [x] Perform the **post-migration overlay-only experiment** using controlled
      adapter-only edits without changing scientific output semantics;
      prove actual no-SIF-rebuild behavior and bundle re-acceptance. Restore
      intended code before final acceptance and repeat exact-head gates.
- [x] Capture case reports, stage attempts/status/identities, scientific
      outputs/checks, scheduler IDs/resources, provenance, database isolation
      and distinct candidate/active state. Post canonical receipts in PR
      threads with exact head, not only filesystem paths.
- [x] Negative live-test attempts preserve active images/bundles; a
      subsequently validated candidate uses the existing governed activation
      path, without unauthorized production activation.

**M4 exit:** authentic receipts for each migrated family and the cross-family
path; build/no-build decision proven, not just inferred from identity tests.

## M5 — Fleet audit, documentation and final gate (Owners: Adviser + Commander)

- [x] Audit all remaining Runner Family definitions for baked REvoCompute
      entrypoints, algorithm scripts, lock-file classification and hardcoded
      `/app/revocompute` execution. Produce a follow-up inventory, not a
      blanket mutation of unrelated families. (Inventory posted in the PR
      thread: 10 families bundle-driven, 31 keep baked adapters behind
      shared-helper overlays, 2 declare no overlay. None of the unmigrated
      families declares its entrypoint in `runtime_overlay`, so the new
      entrypoint contract cannot reject them.)
- [x] Reconcile `docs/runner-guide/runtime-bundles.md` with implemented
      behavior and link the architectural rationale. Make scope/limitations
      explicit: upstream libraries and compiled ABI artifacts can be image
      dependencies; pure REvoCompute adapters belong in bundles.
- [x] Exact-head independent R1/R2/R3, security/scientific review and Examiner
      complete; all new findings resolved in PR threads with regression
      evidence. Independent Campaign Adviser independently checks no
      hidden scope expansion and gives a separate verdict.
- [ ] Final Campaign Acceptance Auditor PASS at frozen exact head; CI and
      scientific receipts match that exact implementation.
- [ ] Retire this temporary `TODO.md` **before merge**, preserving
      architectural decisions and real acceptance evidence in durable docs
      and canonical PR discussions.
- [ ] Commander reports only merge status, blocker category, Owner,
      Adviser verdict, exact head and CI; **maintainer alone** may authorize
      squash merge and later production SIF/Bundle promotion.

## Stop / no-merge conditions

Any fallback to an unpinned or stale runtime script; algorithm-only mutation
causing an unintended SIF rebuild; a dependence lock silently treated as
bundle-only; missing/corrupt runtime executing anyway; accepting a
cross-family case without recording both families' exact SIF and bundle
identities; synthetic CI substituted for genuine scientific acceptance;
unjustified numerical result change; altered resource governance; or an
unapproved production action is a **NO MERGE** condition.

Initial state: scope and source inventory defined, no implementation or
scientific acceptance for #131 yet. The passing #130 receipts are baseline
evidence, **not** proof of migrated #131 candidates.
