# Multi-PR Campaign Throughput — Design and Implementation Plan

## Status

Planning artifact for this PR. This file is temporary execution/design state and must be removed before merge after durable rules are migrated into the canonical agent/protocol documentation.

Base at PR creation: `main@5e3e94889bc82cb3eeca6e696f419f82a95d7041`.

---

## 1. Problem statement

REvoCompute can now run several PR owners, an Independent Campaign Adviser, and a Commander in parallel, but **parallel agent count is not translating into proportional merge throughput**.

The present campaign protocol is strong at preventing unsafe merges. Its weakness is that too much work is serialized at the end:

```text
owner implementation
  ↓
owner validation
  ↓
fresh independent review
  ↓
fixes
  ↓
re-review
  ↓
main advances
  ↓
rebase/reconcile
  ↓
evidence becomes stale
  ↓
repeat broad CI / review
  ↓
maintainer merge
```

At the same time, the repository's current code-CI path is intentionally conservative but coarse. Except for documentation-only changes, `.github/workflows/tests.yml` currently runs four broad lanes for every code PR:

- Python server/contract coverage plus registry determinism;
- GREMLIN_LH scientific-equivalence acceptance;
- frontend typecheck/unit/build plus the full browser-contract suite;
- server Compose full-stack acceptance.

This is safe, but it makes unrelated changes pay unrelated validation cost.

The result is a queueing problem, not primarily an agent-intelligence problem:

1. **review work arrives in bursts at the same final stage;**
2. **main movement invalidates more evidence than necessary;**
3. **independent PRs are often treated operationally like dependent PRs;**
4. **dependent PRs are sometimes treated like independent PRs until merge time;**
5. **heavy local validation competes for the same physical 309 host even when control-plane ownership is independent;**
6. **Commander spends time babysitting stable PRs instead of making only the coordination decisions that require a Commander.**

The target is not "merge faster at any cost." The target is:

> **Increase completed, safely merged PRs per unit wall-clock time by removing unnecessary serialization and repeated work while preserving exact-head safety where it actually matters.**

---

## 2. External engineering patterns worth borrowing

This PR should borrow principles rather than copy another company's tooling.

### 2.1 Google: small, self-contained changes

Google's public engineering practices argue that small changelists are reviewed faster and more thoroughly, produce fewer merge conflicts, are easier to roll back, and allow authors to continue with later work while earlier changes are in review.

Reference:
https://google.github.io/eng-practices/review/developer/small-cls.html

REvoCompute implication:

- one architectural invariant or one independently useful vertical slice per PR;
- tests stay with the behavior they protect;
- do not create empty scaffolding PRs that only become meaningful several PRs later;
- split before implementation when the dependency graph is known, not after a giant diff already exists.

### 2.2 Gerrit / Android: dependencies are explicit and "submitted together"

Gerrit models related changes as dependency/topic sets and computes the changes that must be submittable together.

Reference:
https://gerrit-review.googlesource.com/Documentation/cross-repository-changes.html

REvoCompute implication:

- the campaign must represent the PR DAG explicitly;
- an actually dependent PR must not masquerade as a fully independent branch;
- a blocked descendant should not repeatedly rebase/validate as though it could merge before its ancestor;
- merge readiness should be computed from the ready frontier of the DAG.

### 2.3 Meta/Sapling: stacked changes remain independently reviewable

Sapling/ReviewStack treats a stack as a first-class review object: lower changes can be reviewed and approved while authors continue adding work above them.

Reference:
https://sapling-scm.com/docs/addons/reviewstack/

GitHub now also documents stacked pull-request merging and bottom-up progression:
https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/merging-stacked-pull-requests

REvoCompute implication:

- use stacked PRs when there is a real code dependency;
- review each layer independently;
- keep the next layer moving without pretending the stack is merge-order independent;
- after an ancestor lands, only the affected descendants need reconciliation.

### 2.4 GitHub merge queue: validate the merge frontier, not every imagined future base

GitHub merge queues create temporary merge-group refs and validate the actual candidate set against the protected branch before landing it.

References:
https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/merging-a-pull-request-with-a-merge-queue
https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#merge_group

Current repository constraint:

GitHub documents merge queues for public repositories owned by organizations (and qualifying private organization repositories). REvoCompute is currently under a personal account, so this PR **must not depend on GitHub merge queue availability**.

REvoCompute implication:

- copy the semantics, not the product dependency;
- build a lightweight campaign merge train / ready-frontier protocol that can later map to native merge queue support if repository ownership changes.

---

## 3. Design principles

### 3.1 Parallelism is useful only before the true serialization point

The maintainer's final squash-merge authority remains serial. That is acceptable.

The goal is to push every other activity left of that point:

```text
implementation ─────────┐
focused validation ─────┤
review ─────────────────┤  parallel where independent
dependency preparation ─┤
documentation ──────────┘
                        ↓
                small merge frontier
                        ↓
                 maintainer decision
```

### 3.2 Evidence should invalidate by meaning, not merely by SHA

The current exact-head rule protects against reviewing one diff and merging another. Keep that invariant.

But distinguish:

- **content evidence** — what the PR itself changes;
- **base-integration evidence** — whether that unchanged content still composes with current main;
- **environment evidence** — whether a live/deployment target still matches the tested environment.

A content-identical rebase should not force a human to rediscover the same implementation findings from zero.

The system still needs an exact-head merge gate, but that gate can be a bounded **delta/integration review** when:

- the PR patch digest is unchanged;
- no declared dependency surface changed;
- no high-risk global files changed;
- the previous merge-grade review is tied to the same patch digest;
- required merge-candidate tests pass on the new exact head.

If any of those conditions fail, escalate to a fresh full review.

### 3.3 CI cost should follow affected risk

A frontend-only visual fix should not install the GREMLIN scientific stack.

A runner-equivalence change should not need the full browser matrix unless it changes shared UI/server contracts.

A deployment-controller change should exercise Compose/control boundaries even if it barely touches Python application code.

Classification must fail safe: uncertainty means **run more**, never silently run less.

### 3.4 Control-plane independence is not physical-resource independence

Commander, Adviser, campaign owners, and an independent Codex session may have separate control ownership while sharing:

- RAM;
- swap;
- CPU;
- disk bandwidth;
- Docker/build cache;
- browser workers;
- the demo deployment.

The 309 host incident demonstrated that agent independence can still cause host-level oversubscription.

This PR must make host resource leasing a separate concern from campaign agent-slot allocation.

### 3.5 Commander should react to events, not poll stable state

Commander work should be triggered by:

- PR state transition;
- reviewer blocker;
- CI failure requiring ownership decision;
- dependency ancestor merge;
- shared-resource request;
- ready-frontier change;
- maintainer merge;
- post-merge cleanup completion.

A Commander that has no immediate coordination decision should checkpoint and yield.

---

## 4. Target campaign model

### 4.1 PR classes

Every campaign PR must declare exactly one dependency class:

```text
INDEPENDENT
STACKED(parent_pr)
COUPLED(group_id)
EXTERNAL
```

Definitions:

- **INDEPENDENT** — can merge in either order with sibling PRs, subject to ordinary base drift.
- **STACKED(parent_pr)** — code depends on an unmerged ancestor. It is reviewed independently but cannot enter the merge frontier before required ancestors.
- **COUPLED(group_id)** — multiple PRs are individually reviewable but must be treated as one integration set for final validation/landing order.
- **EXTERNAL** — intentionally outside Commander ownership; still participates in shared-host resource arbitration and main-drift reconciliation.

Do not infer this class from branch naming alone. Record it in campaign control state.

### 4.2 PR lifecycle

Use a lifecycle that separates implementation completion from merge eligibility:

```text
PLANNED
  ↓
IMPLEMENTING
  ↓
OWNER_READY
  ↓
REVIEWING
  ↓
READY_FOR_FINAL_REVIEW
  ↓
MERGE_FRONTIER
  ↓
MERGE_CANDIDATE
  ↓
MERGED
  ↓
POST_MERGE_CLEANUP
  ↓
RETIRED
```

Important distinctions:

- **OWNER_READY** means the owner has finished the intended implementation and focused validation.
- **READY_FOR_FINAL_REVIEW** means required independent review findings are closed on a stable content head.
- **MERGE_FRONTIER** means dependencies allow this PR to be considered now.
- **MERGE_CANDIDATE** means current-main integration evidence is sufficient for maintainer merge consideration.
- **MERGED** is not yet lifecycle completion.
- **RETIRED** follows owner cleanup of PR-owned CI/runtime residue and worktree retirement.

### 4.3 Stable review head

Once a PR enters `REVIEWING`, the owner should stop opportunistic cleanup or unrelated polishing.

Changes after that point require a reason:

- reviewer finding;
- failing required test;
- dependency reconciliation;
- maintainer-directed change.

This reduces "moving target review."

### 4.4 Ready frontier / merge train

Commander maintains a small ordered frontier rather than babysitting every open PR equally.

For each PR in `READY_FOR_FINAL_REVIEW`:

1. confirm dependency prerequisites;
2. inspect main movement since its recorded base;
3. classify base drift;
4. run only required merge-candidate validation;
5. place it in `MERGE_FRONTIER`;
6. present the maintainer with a concise merge/no-merge decision.

After a merge:

- recompute only descendants or PRs whose dependency surfaces intersect the landed change;
- do not reflexively rebase every open PR;
- do not rerun every validation lane for every PR.

---

## 5. Base-drift and evidence invalidation model

### 5.1 Record a review receipt

For merge-grade review, record enough identity to decide whether evidence can be carried forward:

```text
pr_number
head_sha
base_sha
patch_digest
changed_paths_digest
risk_tier
dependency_class
dependency_surface
review_result
reviewed_at
```

This does not need to become a database. A structured PR comment or campaign-state record is sufficient if machine-readable enough for tooling.

### 5.2 Base drift classes

When `main` advances after review, classify the difference:

#### Class 0 — no relevant drift

Examples:

- docs unrelated to the PR;
- another runner's isolated fixture;
- unrelated frontend page while this PR changes a backend-only leaf module.

Action:

- do not re-review content;
- do not rerun unrelated CI;
- exact-head merge-candidate check may be minimal.

#### Class 1 — same subsystem, no content overlap

Examples:

- two server PRs touching separate modules but sharing package/test infrastructure;
- two frontend changes in separate routes sharing global build configuration.

Action:

- rebase/reconcile if needed;
- run affected subsystem CI;
- perform bounded delta review.

#### Class 2 — direct overlap or semantic dependency

Examples:

- same files changed;
- shared schema/API changed;
- runner contract changed under a UI/API consumer;
- dependency ancestor landed with behavior used by the descendant.

Action:

- reconcile;
- rerun affected/full validation;
- fresh review of changed semantics.

#### Class 3 — global invalidator

Examples:

- `pyproject.toml`, lock/dependency policy, test framework, CI workflow, shared security/auth boundary, task schema/protocol, migration semantics, campaign protocol itself.

Action:

- fail safe;
- treat prior integration evidence as stale;
- require the risk-tier's full merge-grade gate.

### 5.3 Patch-digest rule

A rebase that changes only commit ancestry but leaves the effective PR patch unchanged should be detectable.

Do not claim the old SHA was reviewed as the new SHA.

Instead record:

> Content review carried forward because patch digest is unchanged; current exact head received fresh integration/delta validation against base X.

This preserves audit honesty without forcing duplicate human work.

### 5.4 System-boundary exception

For high-risk system-boundary changes, keep the current strict principle:

- exact-head merge decision;
- fresh framing;
- counterexample-driven review;
- no owner READY, Adviser confidence, prior approval, or green CI substitutes for merge-grade review.

The optimization is that a content-identical rebase may use a **focused exact-head delta review** rather than a second full rediscovery pass, provided the reviewer explicitly verifies the unchanged patch identity and the new base interaction.

---

## 6. CI redesign: affected lanes with fail-safe fallback

### 6.1 Extend the existing classifier, do not create a second source of truth

`tools/classify_ci_scope.py` already distinguishes documentation-only changes.

Evolve that mechanism into the canonical CI-scope classifier.

Candidate outputs:

```text
docs
server
frontend
browser
runner_scientific
compose
scheduler_control
security_boundary
full
```

The exact vocabulary may be simplified during implementation, but there must be one classifier consumed by workflows and tested independently.

### 6.2 Initial lane rules

A reasonable starting point:

- **docs-only** → docs build/layout checks; code test matrix skipped.
- **frontend leaf change** → frontend typecheck/unit/build + relevant browser contracts.
- **server application/API change** → server/contract tests; browser only when frontend/API behavior is affected.
- **runner-specific scientific code** → runner-focused tests + scientific acceptance for affected runner(s).
- **deployment/controller/Compose** → controller tests + full-stack Compose gate.
- **shared task schema/security/auth/resource/scheduler boundary** → full or explicitly broad matrix.
- **CI classifier/workflow/build-system change** → full matrix.
- **unknown path** → full matrix.

### 6.3 Browser test selection

Do not solve this by brittle filename-to-test hardcoding.

Prefer broad stable feature groups/markers.

If the browser suite cannot yet be selected safely, keep the full browser lane for frontend changes first; optimize it only after marker coverage is trustworthy.

### 6.4 Scientific acceptance selection

The current workflow always installs and validates GREMLIN_LH for all non-doc code PRs.

Change this so GREMLIN_LH scientific acceptance runs when:

- GREMLIN_LH scientific/runtime files change;
- shared runner contract code changes in a way that may affect it;
- the classifier cannot establish isolation;
- the merge candidate is deliberately requesting a full scientific gate.

Do not weaken scientific correctness to save minutes.

### 6.5 Merge-candidate validation

Because native GitHub merge queue may not be available, define a repository-supported merge-candidate command/workflow that can validate a selected PR against current main.

Implementation should prefer the simplest reliable mechanism supported by GitHub Actions and git refs.

Requirements:

- identify exact candidate head and current base;
- produce a receipt with both SHAs;
- run the risk-tier-required gates;
- be invocable without rewriting the PR's development branch merely to test a hypothetical merge;
- fail closed if the candidate cannot be reconstructed safely.

Do not build a custom distributed queue service.

---

## 7. Review-flow redesign

### 7.1 Batch findings per pass

A reviewer should collect merge-level findings into one coherent pass when possible rather than drip one issue every few minutes.

PR thread remains the canonical technical record.

The chat/control-plane summary remains small:

```text
merge/no-merge
blocker category
owner
Adviser confidence / concern
next event
```

### 7.2 Risk-tiered review

Keep/clarify the existing risk tiers:

- low-risk leaf change;
- subsystem change;
- cross-boundary change;
- system-boundary/security/scientific-critical change.

Review depth and fresh-exact-head requirements follow risk, not PR number or diff size alone.

### 7.3 Adviser role

The Independent Campaign Adviser remains active, but should not duplicate the primary merge reviewer.

Adviser responsibilities:

- dependency classification;
- scope creep detection;
- architecture-boundary challenge;
- whether owner interpreted review findings correctly;
- whether evidence invalidation classification is defensible;
- merge-readiness confidence.

### 7.4 No review while implementation is still moving

Except for early architecture intervention, do not spend merge-grade review cycles on a PR that has not reached a declared stable review head.

---

## 8. Shared-host resource arbitration

### 8.1 Separate agent slots from heavy-work slots

Campaign agent slot budget answers:

> How many reasoning/implementation agents may be active?

Host lease answers:

> How many heavy physical workloads may run on this machine now?

They are not the same resource.

### 8.2 Heavy operations

At minimum treat these as heavy on the 309 development host:

- full Playwright/browser acceptance;
- full Python coverage under xdist when concurrent with other heavy work;
- Docker/Compose builds or rebuilds;
- large dependency installs;
- deployment/redeployment;
- image/SIF build;
- other tasks shown by measurement to create memory or I/O pressure.

### 8.3 Lease behavior

Implement a minimal host-local advisory lease that all campaign owners and independent agents can use.

Requirements:

- explicit acquire/release;
- owner metadata (PR/worktree/PID/start time);
- crash-safe stale-owner detection;
- no `eval`/`exec`;
- no network service;
- no privileged daemon;
- bounded and inspectable;
- safe cleanup after reboot;
- default heavy concurrency on 309 should be conservative (one heavy job at a time unless measurement justifies more).

Do not make ordinary coding wait for the heavy lease.

An agent may continue code/review work while another process owns the heavy slot.

### 8.4 Demo deployment is also a lease

`revocompute-demo.yaoyy.moe` is a shared mutable validation target.

Treat deployment/live-test ownership as an explicit lease separate from production.

Production remains controlled and should not become routine campaign scratch state.

---

## 9. Campaign control state should become smaller, not larger

Do not create a giant orchestration database.

Commander needs only enough state to answer:

```text
PR
dependency class
state
risk tier
stable content head / patch digest
blocker category
owner
Adviser status
current base / drift class
required next gate
shared-resource lease, if any
```

Detailed technical findings stay in PR threads.

Tests/receipts remain machine-verifiable evidence.

Repository TODO / IMPLEMENTATION_STATE remains execution truth only while work is active.

---

## 10. Metrics: prove throughput improved

Before changing behavior, capture a small baseline from a recent multi-PR campaign if reconstructable.

Track per campaign:

- PR count;
- wall-clock campaign duration;
- median owner-ready → merge time;
- number of rebases/reconciliations per PR;
- number of full CI reruns after owner-ready;
- number of merge-grade human review passes per PR;
- number of times evidence was invalidated by base movement;
- time spent waiting on shared heavy resources;
- number of host resource-contention incidents;
- number of post-merge regressions attributable to insufficient validation.

The goal is not to optimize a vanity metric.

Success means:

- lower repeated-work count;
- lower ready-to-merge latency;
- no increase in escaped regressions;
- no reduction in required safety for high-risk PRs.

---

## 11. Implementation phases

### Phase A — protocol and model

- [ ] Add the dependency classes and lifecycle states to the canonical Multi-agent Campaign Protocol.
- [ ] Define stable review head semantics.
- [ ] Define ready frontier / merge train behavior.
- [ ] Define base-drift classes and evidence carry-forward rules.
- [ ] Preserve maintainer-only squash-merge authority.
- [ ] Preserve post-merge owner cleanup before retirement.
- [ ] Define External PR behavior: outside Commander ownership but inside shared-host arbitration.

### Phase B — CI scope classifier

- [ ] Refactor/extend `tools/classify_ci_scope.py` into a tested affected-lane classifier.
- [ ] Add explicit fail-safe fallback to full CI.
- [ ] Add tests for representative path combinations.
- [ ] Avoid duplicated path policy in multiple workflow files.
- [ ] Keep docs-only optimization working.

### Phase C — workflow lane gating

- [ ] Gate server/contract tests by classifier output.
- [ ] Gate GREMLIN_LH scientific acceptance by actual scientific/shared-contract impact.
- [ ] Gate browser/frontend lane by frontend/contract impact.
- [ ] Gate Compose full-stack by deployment/control/cross-boundary impact.
- [ ] Ensure classifier/build-system changes trigger broad validation.
- [ ] Verify skipped jobs still behave correctly with any required-check semantics.

### Phase D — merge-candidate / evidence tooling

- [ ] Add the smallest useful tool or documented command to compute patch digest and changed-path digest.
- [ ] Add base-drift classification support.
- [ ] Add a merge-candidate receipt format with exact head/base identity.
- [ ] Support focused delta validation when patch content is unchanged.
- [ ] Fail closed when drift cannot be classified safely.
- [ ] Do not create an always-on orchestration service.

### Phase E — host lease

- [ ] Add a small host-local heavy-work lease helper.
- [ ] Add stale lease / crashed owner handling.
- [ ] Document heavy workload classes and demo-deployment lease.
- [ ] Add unit/integration tests for contention and stale-owner recovery.
- [ ] Keep ordinary work independent of the lease.

### Phase F — campaign ergonomics

- [ ] Update Commander/owner/Adviser examples so they do not poll.
- [ ] Add a concise ready-frontier status format.
- [ ] Add an example independent PR and an example stacked pair.
- [ ] Add an example main-advance event showing Class 0 versus Class 2 invalidation.
- [ ] Keep PR thread as canonical technical record.

### Phase G — subtraction and proof

- [ ] Remove old protocol language that blindly requires global reconciliation after every main advance if superseded.
- [ ] Remove duplicate CI classification logic.
- [ ] Run protocol/docs strict build.
- [ ] Run classifier tests.
- [ ] Run representative workflow validation.
- [ ] Exercise host-lease contention.
- [ ] Demonstrate at least one simulated multi-PR campaign where an unrelated merge does not cause unnecessary full revalidation.
- [ ] Demonstrate a high-risk/global invalidator that correctly escalates to full validation.
- [ ] Record before/after expected workflow cost for representative PR classes.
- [ ] Delete this `TODO.md` before merge after durable material moves to canonical docs.

---

## 12. Required acceptance scenarios

The implementation is not complete until these cases are demonstrated.

### Scenario 1 — two independent leaf PRs

PR-A changes an isolated frontend surface.

PR-B changes an isolated backend leaf module.

Expected:

- both implement/review in parallel;
- A does not run unrelated scientific acceptance;
- B does not run unrelated browser acceptance unless a shared contract requires it;
- merge of A does not automatically force a full re-review of B;
- B receives the bounded current-main gate appropriate to its drift class.

### Scenario 2 — stacked dependency

PR-B consumes an API introduced by PR-A.

Expected:

- B is explicitly `STACKED(A)`;
- B can be reviewed while A is pending;
- B cannot enter merge frontier before A;
- after A merges, B reconciles only what the ancestor/base transition invalidated;
- evidence identity remains auditable.

### Scenario 3 — global invalidator

A PR changes shared auth/security/task-schema/CI-classifier semantics.

Expected:

- classifier selects broad/full validation;
- dependent evidence is marked stale where required;
- no "optimization" bypasses merge-grade system-boundary review.

### Scenario 4 — content-identical rebase

A reviewed PR is rebased after unrelated main movement; its effective patch is unchanged.

Expected:

- tooling proves patch identity;
- prior content review is not falsely relabeled as review of the new SHA;
- a fresh exact-head integration/delta gate is recorded;
- full rediscovery review is not mandatory unless risk/drift classification says so.

### Scenario 5 — concurrent heavy validation on 309

Commander-owned PR and independent external Codex both attempt heavy browser/build work.

Expected:

- one gets the heavy lease;
- the other does not launch the competing heavy workload;
- ordinary code/review work may continue;
- stale lease is recoverable after process death/reboot;
- no dependence on Commander ownership for lease enforcement.

### Scenario 6 — scientific runner change

A GREMLIN_LH scientific change is proposed.

Expected:

- scientific acceptance remains required;
- optimization does not classify it as generic backend-only;
- exact scientific evidence remains tied to the tested head/content.

### Scenario 7 — unknown new path

A new top-level code area appears and classifier policy does not recognize it.

Expected:

- full CI runs;
- no silent under-testing.

---

## 13. Non-goals

This PR must **not**:

- remove maintainer final merge authority;
- auto-merge PRs;
- build a bespoke GitHub/Gerrit replacement;
- require moving the repository to an organization;
- depend on native GitHub merge queue availability;
- weaken high-risk scientific/security/system-boundary review;
- replace GitHub Actions with a new CI provider;
- build a distributed scheduler for coding agents;
- centralize all PR comments or technical findings into Commander state;
- create a permanent root-level process guide parallel to canonical docs;
- optimize CI by deleting coverage or scientific contracts without an affected-scope argument;
- make the 309 demo deployment a mandatory test for every PR.

---

## 14. Design test

The design is successful when the answer to this question changes:

> "Main just advanced. What must every other PR do?"

From:

> "Rebase, rerun broad CI, reacquire review confidence."

To:

> **"Classify what actually changed, invalidate only the evidence that depended on it, then run the smallest safe current-main gate."**

That is the core throughput improvement.

The second design test is:

> "A second coding agent is independent of Commander. Can it launch another full browser/build workload on the same 32 GB host?"

The answer must become:

> **"Control ownership may be independent; heavy physical-resource use still requires the shared host lease."**
