# PR #132 — Production Readiness: Runner Fleet, Contract and Failure Attribution

**Baseline:** merged main `b7a3190e63d08071812f0ad21be280f173eb3528` (PR #131).
**Mission:** make the next REvoCompute release *safe to deploy*, **without deploying it**.
**Authority:** maintainer retains merge, production build/promotion/restart/deployment and activation decisions. Maintainer has authorized normal isolated Slurm/Apptainer scientific acceptance as campaign work. Existing BioEmu queues are not a campaign hold. No production secrets, configuration files, evidence DBs or identities may be committed.

## Definition of ready

Produce a reviewable **Release Candidate Readiness Dossier** for the actual intended enabled fleet. Every enabled/advertised-to-submit family must either be (A) proved submittable against the exact active/candidate SIF and Runtime Bundle with a valid current scientific acceptance receipt, or (B) clearly marked **NOT READY / withheld from submission**, with reason and recovery. Never make an unverified Runner appear ready merely to complete the checklist. There is no requirement to migrate all 43 families before considering a smaller verified release cohort.

Evidence classes are distinct: static contract, adapter fake-executable tests, real CLI scientific evidence, and target-host Slurm+Apptainer acceptance. Synthetic evidence cannot promote a family to production-ready.

## M0 — Freeze baseline, fleet and release cohort (Commander + independent Adviser)

- [ ] Fetch live main, open PRs, release issues #89/#90 and PR #130 Codex discussion `discussion_r4438562141`; read the full PR #131 M4 and fleet acceptance record. Record exact main/head and current CI. Never reuse historic acceptance claims without matching identities.
- [ ] Inventory all 43 family manifests: configured/enabled state when trustworthy host evidence is available; `plugin.yaml` build_inputs / runtime_overlay / entrypoint; image `.def`, `%files` and `%runscript`; dependency locks; required smoke; TaskTypes, result contracts, weights/DB/mounts, scientific references and actual receipt level.
- [ ] Reconcile the PR #131 fleet classification (10 bundle-driven, 31 baked, 2 no overlay) against current main; note the partial `placer-rfdiffusion`, `simplefold` `%runscript`, and `mol1` baked asset-path problems.
- [ ] Run/read `tools/audit_runner_scientific_contracts.py --json` and the result audit. Distinguish the 12 currently reported `tree_absent` Tasks and stale audit-corpus evidence levels from actual M4 evidence recorded in PR #131. Do not silently upgrade machine-readable evidence from prose receipts.
- [ ] Define release cohorts: **A** intended/enabled production families requiring hard readiness gates; **B** candidates for bounded fixes/migration in this PR; **C** intentionally deferred, non-submittable families. If deployed enablement/configuration is inaccessible, mark it **UNKNOWN**, request a redacted read-only host snapshot and continue source work; do not guess.
- [ ] Adviser verifies the roster, scope, dependency graph, acceptance costs, and which blockers are genuinely production-relevant. Post the matrix and decisions in PR comments.

## M1 — Close the Codex P2 from merged PR #130 (Core / StageRun owner)

Canonical finding: https://github.com/YaoYinYing/REvoCompute/pull/130#discussion_r4438562141

- [ ] Reproduce the exact scenario: stage A fails; later independent stage B succeeds; workflow remains FAILED but Task-level diagnostics wrongly describe B.
- [ ] Make a failed StageRun's durable `reason_code`, stage identity, exit / scheduler evidence the authority for **workflow failure attribution**. Build a deterministic Task-level failure summary from failed stages or explicitly recorded pre-dispatch refusals. Do not treat the mutable latest-allocation diagnostics row as the authoritative failure of the whole DAG.
- [ ] Preserve per-stage diagnostics, sibling success artifacts, blocked-descendant reasons, retries, cancellation, and existing stage accounting. Do **not** turn serial DAG into concurrent scheduling or add another diagnostics database/ledger.
- [ ] Regression-test failed A → successful independent B; two failures with deterministic primary attribution; pre-dispatch refusal; blocked downstream; all-success; cancelled; retry; real Slurm adapter diagnostics overwrite. Mutation of the correction must fail a regression.
- [ ] Comment on the canonical #130 Codex thread with the new PR and evidence; do not rewrite the merged #130 branch.

## M2 — Close prioritized Runner contract / runtime gaps (Family owners)

- [ ] First remediate **production cohort A** issues: inaccurate enablement/admission, invalid entrypoints, missing/incorrect overlay declarations, baked mutable execution paths, asset mounts, required output views, test definitions, incomplete scientific artifacts, or absent acceptance. Choose and justify each actual file change from evidence.
- [ ] Investigate candidate cohort B at minimum: `simplefold` legacy `%runscript`, `mol1` image-path asset dependencies, and partial `placer-rfdiffusion` migration. Include only bounded fixes that can be verified within this campaign; open separate issues/PRs for dependency-heavy families such as Foundry and EvoSplit if no-overlay migration would demand new broad builds.
- [ ] For any migrated Family, preserve upstream scientific software and locks in SIF; place REvoCompute adapters and scripts in `runtime_overlay`; require the correct mounted entrypoint. A moved `.def` file triggers a **one-time candidate SIF rebuild**, even if later adapter-only changes do not.
- [ ] Audit and repair **required** `expected_files.yaml` / view-source contracts for *release-cohort* Tasks lacking trees or publishing wrong roles. Changes must reflect observed scientific output, not broaden patterns until tests pass. Other unaudited Tasks remain explicit deferred gaps.
- [ ] Do not blanket-migrate the 31 baked families; prioritize real user-facing/production blockers and verified high-value candidates. Avoid unrelated numerical-algorithm refactors or resource-policy changes.
- [ ] Retain existing supported family behavior and immutable Task pinning. Every change gets a test that fails without the fix.

## M3 — Revise Runner Contract documentation (Docs / Independent Adviser)

- [ ] Make `docs/runner-guide/runner-family-protocol.md` the short, human-readable **normative contract** with the complete family lifecycle and release gate: identity classes (Build / Bundle / Execution / Presentation), ownership, scientific input roles, output/artifact identity, stage evidence, testing evidence levels, admission, rollback and refusal, and exceptions.
- [ ] Keep `adding-a-runner.md` a walkthrough; `runtime-bundles.md` the detailed mount/identity contract; `plugin-manifest.md` and `task-contract.md` authoritative field guidance; `test-plan.md` the test declaration guide; operator guides the actual CLI. Link rather than duplicate tables or create parallel policy.
- [ ] Correct stale examples to match shipped manifests, `runner-status`, full smoke receipts, exact activation and actual deploy commands. Clearly distinguish **`READY`** from access, capacity, model/database mount availability, and post-merge **production activation**; do not present CI green as HPC scientific acceptance.
- [ ] Update `docker/runners/README.md` and nav links only when they disagree with the canonical contract. Keep docs short enough for humans; `mkdocs build --strict` must pass.

## M4 — Production candidacy gates, no deployment (Acceptance / Lifecycle / Adviser)

- [ ] Verify issue #89's server-authoritative catalog/deep-link/preflight/POST admission consistency for the release cohort. A readiness race must refuse before Task, upload publication, quota hold or scheduler request. If already implemented, link evidence and do not redo the UI.
- [ ] Verify issue #90's enabled state and active-image evidence are truthful; distinguish UNKNOWN from READY. No fake Web Promote/Restore buttons or changes to host authorization boundaries. Defer unrelated GPU waterfall issue #91.
- [ ] For release cohort A and fixed cohort B candidates: exact-head Doctor, fleet/fast contracts, SIF build identity, published Bundle identity, required result tree/view acceptance, scientific references, required smoke, Slurm resource evidence and receipt statuses. Run isolated acceptance through normal shared Slurm scheduling with separate DB, stores and ports. The maintainer handles existing BioEmu jobs; proceed without repeated clearance or cancellation of production workloads.
- [ ] Prove negative refusal for stale/corrupted/missing SIF/Bundle, unaccepted new code, missing resources, incorrect or incomplete scientific output, wrong upstream artifact roles, disabled family, and authorization/capacity difference. Check old running Tasks remain pinned and rollback stays receipt-gated.
- [ ] Publish a release candidate matrix: family/TaskType, enabled (true/false/unknown), build-ready, bundle-ready, receipt (exact SHA), result-contract covered, required assets present, admission-ready, reason and next action. No invented values. A release may only claim the **verified cohort**, not the entire catalog.

## M5 — Evidence and final review

- [ ] R1/R2/R3 + security/science reviewers inspect exact source, test claims, and release-roster evidence. Independent Campaign Adviser stays active and independently challenges overreach or omissions. File-specific findings live in PR review threads.
- [ ] Run focused mutation-sensitive tests, `make runner-fast`, `make test-fleet`, full Server tests, `tools/check_test_boundaries.py`, scientific contract auditor, strict docs, browser/full stack, relevant CI lanes; record exact-head results.
- [ ] For every scientific output/definition change, obtain current isolated real Slurm/Apptainer receipts before declaring that family ready. Otherwise explicitly defer that family as NOT READY. Do not inherit M4 receipts for changed scientific identities.
- [ ] Prepare a **go/no-go deployment-readiness report**, rollback/hold plan and a dry-run checklist for a later, separately authorized deployment; do not promote or restart.
- [ ] Final Campaign Acceptance Auditor PASS on frozen exact head; retain durable docs and PR thread evidence. Remove this temporary root TODO before merge. **Maintainer decides squash merge and production deployment separately.**

## Campaign protocol

Commander delegates nonoverlapping Core/StageRun, Family, Docs, Lifecycle/Acceptance, and Independent Adviser owners. Execute approved code/docs work without routine maintainer interruptions; ask only for genuine policy/scope changes, inaccessible host credentials, or production deployment/promotion/merge authority. Keep the PR conversation as canonical technical evidence. Report compactly: merge state, blocker category, owner, Adviser, exact head, CI, release-cohort gate.

**Stop conditions:** a false READY claim, bypassed submission guard, invented scientific receipt, silent legacy executable fallback, output-contract loosening without scientific evidence, unvalidated SIF/Bundle activation, destructive migration, unauthorized HPC/production action, or scope expansion into all 43 families without a bounded reason.
