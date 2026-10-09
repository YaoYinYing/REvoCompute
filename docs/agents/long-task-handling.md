# Long-task Handling

Use this protocol for work that cannot be completed reliably as a single local
patch: large architectural refactors, migrations, and repository-wide redesigns,
and coordinated multi-PR campaigns, which may consist of ordinary features
rather than a refactor. It defines how to keep design truth, execution-progress
truth, and machine-verifiable truth separate and current.

## Long-running Refactor Protocol

For large architectural refactors, migrations, repository-wide redesigns, or other work that cannot be completed reliably as a single local patch, do not treat the task as a normal feature implementation.

The agent must maintain three separate sources of truth:

```text
DESIGN / TODO
    architectural truth

IMPLEMENTATION_STATE.md
    current execution/progress truth

tests / acceptance commands
    machine-verifiable truth
```

### 1. Read the design before editing

When the user or repository identifies a design document such as:

```text
TODO.md
DESIGN.md
MIGRATION.md
RFC.md
```

read it completely before making architectural changes.

Do not infer completion merely because some requested classes, modules, abstractions, or tests already exist.

For refactors, completion means the intended dependency direction and ownership model are actually in production use.

---

### 2. Convert the design into a persistent execution checklist

Before starting a large refactor, create or update:

```text
IMPLEMENTATION_STATE.md
```

Translate every important `MUST`, required migration step, acceptance criterion, and architectural invariant from the design into explicit checklist items.

Example:

```markdown
## Completion checklist

- [ ] Move authoritative task definitions out of the central registry
- [ ] Switch production discovery to plugin-owned manifests
- [ ] Remove the old production registry path
- [ ] Migrate one real implementation end-to-end
- [ ] Add zero-plugin startup coverage
- [ ] Add architecture boundary tests
- [ ] Run final acceptance commands
```

Do not use the checklist merely as documentation.

It is the persistent execution state for the current refactor.

---

### 3. Keep progress durable

After every major milestone, update `IMPLEMENTATION_STATE.md` with:

```text
completed items
current phase
files/components migrated
verification performed
known failures
remaining blockers
next concrete action
```

Do this before moving to the next major phase.

The execution state must be sufficient for another agent session to resume the work without reconstructing the migration from git history alone.

---

### 4. Recover state after context loss or session restart

After any of the following:

```text
context compaction
new agent session
long interruption
major test/debug cycle
uncertainty about the current migration state
```

re-read:

```text
repository instructions
the active design/TODO document
IMPLEMENTATION_STATE.md
```

before deciding what to do next.

Do not rely solely on conversation memory or a compacted context summary.

Repository files are the durable project memory.

---

### 5. Architecture ownership outranks minimum diff

For ordinary bugs, prefer small and focused changes.

For an explicitly requested architectural migration, minimum-diff heuristics must not preserve an architecture that the design requires removing.

Before adding a special case, ask:

```text
Who owns this knowledge?
```

If the knowledge belongs to a plugin, task, runner, adapter, backend, or another domain module, move the validation/configuration/behavior to that owner instead of hardcoding it into generic Core code.

A two-line fix is not preferable when it violates the target dependency direction.

---

### 6. Do not stop at scaffolding

The following do not by themselves count as completion:

```text
a new manager class exists
a new interface exists
a new schema exists
a doctor command exists
new tests for the new abstraction pass
```

For a migration, the new architecture must replace the old production path.

Always distinguish:

```text
new abstraction exists
```

from:

```text
production now depends on the new abstraction
```

The latter is required.

---

### 7. Avoid dual sources of truth

During a migration, temporary compatibility code may be used only when necessary to perform the transition.

By the end of the refactor, there must not be two authoritative representations of the same concept.

Examples of forbidden final states:

```text
new plugin registry + old central task registry

new schema + legacy validation table

new execution plan + production still constructing jobs directly

distributed manifests + central fallback manifest
```

If the design requires ownership inversion, the old authoritative path must be retired after its information has been migrated.

---

### 8. Migrate information before deleting its old container

When retiring a centralized file or registry, do not interpret "delete" literally before understanding what it contains.

Use this migration sequence:

```text
inventory
→ classify ownership
→ migrate
→ switch consumers
→ verify semantic preservation
→ remove old source of truth
```

For every important migrated field, know:

```text
old location
semantic meaning
new owner
new location
verification evidence
```

A deleted centralized file with lost behavior or metadata is a failed migration.

---

### 9. Prefer vertical-slice migration

When possible, migrate one complete real implementation end-to-end before bulk-moving every implementation.

For example:

```text
discovery
→ configuration/schema
→ runtime
→ output
→ presentation
→ doctor
→ tests
```

for one real component.

Use that implementation as the reference architecture for subsequent migrations.

Do not validate a repository-wide design only with synthetic fixtures.

Synthetic fixtures are useful for protocol tests but do not replace one real production integration.

---

### 10. Make acceptance criteria executable

Whenever possible, turn architectural requirements into commands or tests.

Prefer:

```text
pytest tests/test_zero_plugin_startup.py
pytest tests/test_plugin_discovery.py
python scripts/check_architecture.py
```

over subjective criteria such as:

```text
architecture looks clean
plugin system appears integrated
```

Add architecture tests for important dependency rules.

Examples:

```text
Core starts with zero plugins

adding a test plugin requires no Core changes

old centralized registry is absent

production does not call deprecated discovery code

generic modules contain no known domain-specific branches
```

A failing executable acceptance gate means the refactor is not complete.

---

### 11. Self-authored tests are not sufficient evidence

Tests added during the refactor often prove only that newly added abstractions work in isolation.

Before completion, also test the negative condition:

```text
the old architecture is no longer required
```

and the integration condition:

```text
the real production path uses the new architecture
```

For architectural migrations, explicitly test dependency removal, not only feature addition.

---

### 12. Maintain explicit phases

Large refactors should be tracked in phases such as:

```text
Phase 1 — inventory and design validation
Phase 2 — generic contracts
Phase 3 — reference implementation migration
Phase 4 — production dependency switch
Phase 5 — bulk migration
Phase 6 — old architecture removal
Phase 7 — doctor / architecture validation
Phase 8 — full regression verification
```

Record the active phase in `IMPLEMENTATION_STATE.md`.

Do not jump to cleanup/removal before the migrated path is operational.

---

### 13. Do not declare completion with unchecked checklist items

A final response is allowed only when:

```text
all required checklist items are complete
```

or an actual external blocker prevents further work.

An external blocker means something the agent cannot fix in the repository, such as:

```text
missing credentials
unavailable external service
required proprietary dependency unavailable
missing user decision on genuinely ambiguous product behavior
```

Large scope, failing tests, architectural complexity, or a long diff are not blockers.

Continue working.

---

### 14. Before finalizing, perform an architecture audit

For large refactors, explicitly search for remnants of the old architecture.

Examples:

```text
deprecated file names
old loader functions
old registries
legacy configuration keys
known domain identifiers in generic modules
special-case branches
compatibility fallbacks
duplicate sources of truth
```

Review each remaining occurrence.

Do not blindly remove matches, but require a reason for every intentional remainder.

---

### 15. Final acceptance report

Before completing a major refactor, update `IMPLEMENTATION_STATE.md` and report:

```text
what architecture changed
what old sources of truth were retired
where migrated information now lives
which real implementation proves the design
which production dependency paths changed
which acceptance tests prove the migration
which commands were run
which tests passed or failed
what intentional architecture debt remains
```

Do not describe scaffolding as finished migration.

---

### 16. Repository-level definition of done for architectural refactors

A large refactor is complete only when all three are true:

```text
DESIGN TRUTH
The repository structure and dependency direction match the intended architecture.

EXECUTION TRUTH
IMPLEMENTATION_STATE.md has no unresolved required migration items.

MACHINE TRUTH
The defined acceptance tests and architecture gates pass.
```

If one of these is false, continue the refactor.

---

## Multi-agent Campaign Protocol

A **Campaign** is a set of related PRs delivered as one effort, identified by a
coordinating GitHub issue or by an explicitly named PR group in the launch
instruction. Use this protocol when the task is identified as a Campaign, when a
Campaign Commander role is named, or whenever several PRs progress in parallel
under one coordination effort.

### Sources of truth

Do not replace any of these with conversation memory:

```text
Campaign coordination truth
    the coordinating issue or named PR group

PR design truth
    each PR's body and its TODO/design document

PR execution truth
    that PR's implementation-state document, when the work needs one

machine truth
    tests, CI, live acceptance, and exact-head evidence
```

### Campaign Commander

The Commander is a workflow owner, not a default implementation owner. The
Commander:

- reads the Campaign and every participating PR and TODO before assigning work;
- maintains the dependency and merge DAG;
- keeps exactly one owner per active PR and one explicit owner per high-conflict
  write surface;
- tracks blockers and cross-PR contract assumptions;
- coordinates rebases only when the rebase policy requires them;
- arbitrates deployment and live-test windows;
- arranges review without uncontrolled reviewer fan-out;
- keeps the campaign within the concurrency budget;
- reports each PR's exact head SHA and the merge order when the campaign is
  ready.

The Commander should not make feature changes itself. Small coordination-only
edits are allowed, but the Commander must not become a hidden additional PR
owner. The Commander does not merge or squash-merge unless the launch
instruction explicitly grants that authority; the normal endpoint is
`READY_FOR_FINAL_REVIEW`.

#### Control-plane quiescence

The Commander is a control plane, not a permanently resident worker. Its durable
control state stays small and reconstructable — merge status, broad blocker
category, owner, Advisor assessment, exact head, CI/acceptance state, and
material dependencies/leases — so that detail lives in PR threads (see Findings
live in PR threads) rather than in a large private working set.

When no immediate coordination decision exists, the Commander checkpoints that
state, confirms active owners and dependencies are known, and yields its active
slot to executable implementation, review, or validation work. Where the harness
cannot literally suspend an agent, it approximates this by ending the active
turn after checkpointing and recovering from GitHub plus durable campaign state
on the next invocation.

A quiescent Commander resumes only on a bounded set of wake events:

```text
WAKE
owner checkpoint or READY_FOR_FINAL_REVIEW
a new reviewer blocker
a commit that changes the head of a PR under review or awaiting merge
CI completion needing classification
an upstream merge
a dependency becoming satisfiable, or a PR becoming blocked because one is not
a shared-resource request, a deployment/live-test lease request, or a lease release
a liaison-bus notice addressed to the Commander
a shared write surface becoming free, or an agent slot becoming available
an owner escalation
a material Advisor advisory
a maintainer instruction
```

This is the coordination subset of the Dynamic-orchestration re-evaluation
events: a wake resumes coordination, while DAG re-evaluation itself is governed
there. Dispatching an ephemeral reviewer or specialist is itself a coordination
action, so a quiescent Commander re-enters to dispatch and then yields again —
quiescence is not an inability to schedule needed review.

None of the following is Commander work: waiting for subagents, polling with no
new event, rewriting the same campaign summary, requesting status before an owner
has produced a checkpoint, speculatively replanning an unchanged DAG, or
manufacturing auxiliary work to hold a slot. Busy polling to emulate presence is
forbidden; react to state changes instead.

### Maintainer attention is a scarce campaign resource

A Campaign must optimize not only implementation throughput and correctness but
also **maintainer attention cost**. A recent pair of high-throughput PR campaigns
consumed roughly twelve hours of sustained maintainer supervision in aggregate —
not because implementation stalled, but because too much routine convergence
work remained with the maintainer: repeatedly choosing PR order, asking for
status, noticing stale ancestry, requesting rebases, separating CI flakes from
regressions, re-checking whether review findings were still live, and deciding
when agents should continue or stop. More agents must not imply proportionally
more interruptions; if throughput roughly doubles, required maintainer attention
should stay roughly bounded. If it does not, the protocol is under-absorbing
coordination work.

The intended division of responsibility:

```text
Maintainer  -> goals and first-principles constraints, scientific/product/security
               judgment, major architectural trade-offs, scope changes, acceptance
               of user-visible design, final merge authority where retained, and
               genuinely ambiguous or irreversible decisions

Commander   -> routine convergence: refresh live state, maintain the dependency
               DAG, choose safe order, dispatch PR-scoped agents, keep the control
               root clean, detect stale ancestry, rebase/reconcile after upstream
               merges, resolve ordinary integration conflicts, rerun CI and
               dedicated gates, distinguish flakes from regressions with evidence,
               track findings (live / fixed / superseded), request focused review
               cells, regenerate derived artifacts from canonical sources, identify
               shared-file hotspots, park downstream work until real dependencies
               are ready, stop scope growth, and drive PRs to
               READY_FOR_FINAL_REVIEW
```

The maintainer should never have to ask whether a PR has rebased onto the new
`main`, whether a CI rerun finished, whether an old review thread is still
relevant, which PR is next, whether a generated client was regenerated, whether a
downstream PR may start, or whether a branch actually consumed a merged upstream
change. Those are Commander responsibilities.

**Escalation threshold.** Do not escalate routine engineering choices merely
because several valid options exist. Escalate only when at least one holds:

1. the decision changes an established architectural owner or creates a new
   source of truth;
2. it materially expands or cuts campaign scope;
3. scientific correctness or interpretation is ambiguous;
4. security posture would materially change;
5. a user-visible product/design decision needs subjective acceptance;
6. a migration or destructive operation has meaningful irreversible risk;
7. two valid approaches have materially different long-term maintenance cost;
8. proceeding would contradict a previously stated maintainer constraint;
9. evidence is insufficient to distinguish a regression from an
   infrastructure/test failure;
10. an imminent merge requires maintainer approval, or a proposed change would
    alter previously retained merge authority.

Otherwise choose the best bounded option, record the reasoning concisely, and
continue.

**Evidence before interruption.** Before asking the maintainer to decide
anything technical, gather enough evidence to make the decision easier. Do not
ask "CI failed; what should we do?" — first determine the exact failing
test/job, whether the changed files can plausibly affect it, whether it
reproduces, whether it fails on current `main`, whether nondeterminism,
environment, or ordering explains it, and whether a bounded fix belongs in the
current PR. Only escalate if a real trade-off remains.

**Report by decision boundary, not by implementation event.** Batch routine
state changes. Prefer "#58 and #59 are independently converging; #58 rebased
cleanly and is in exact-head security review; #59 found one admission invariant
violation and is fixing it. No maintainer decision required." over a stream of
"rebased / CI started / CI completed / a test failed / should I rerun / should I
continue." Routine failures are investigated before escalation.

**Convergence loop.** For a long-running Campaign the Commander repeatedly
performs `observe → classify → dispatch → verify → reconcile → reduce in-flight
state` without waiting for a maintainer prompt after every step. After every
upstream merge: refresh `main`; identify affected downstream branches;
re-evaluate ancestry and semantic dependencies; reconcile the smallest necessary
set; rerun exact-head evidence; update the dependency DAG; and continue
automatically where no maintainer decision is required. The goal is to keep
shrinking the campaign state the maintainer must mentally track.

**Stop conditions.** Autonomy does not mean manufacturing work. When all
remaining PRs are ready for maintainer final review, deliberately parked behind
explicit dependencies, or blocked on a genuine maintainer decision, stop
dispatching implementation work and present one concise campaign checkpoint. Do
not create speculative follow-up PRs merely because agent capacity is available.

### PR owners

Every active implementation PR has exactly one owning agent. The owner:

- works in a dedicated worktree for that PR branch;
- treats its PR body and TODO/design document as its scope and goal;
- maintains its execution state when the work requires it;
- implements, tests, self-reviews, and checkpoints coherent progress;
- reports cross-PR discoveries to the Commander instead of silently expanding
  scope;
- requests deployment or live-test access from the Commander;
- reports the exact final head SHA and acceptance evidence.

A PR owner must not recursively create a new team of reviewers or implementation
agents by default. Additional agents are a campaign-level resource the Commander
controls.

### Independent Campaign Advisor

The Advisor is a Campaign-wide, human-facing role that evaluates direction rather
than implementation: whether the Campaign is still solving the right problem by
the shortest correct path. It is not another reviewer or approval layer. The role
split is:

```text
Owner      -> optimize implementation
Reviewer   -> optimize implementation correctness
Commander  -> optimize safe Campaign delivery and merge throughput
Advisor    -> optimize direction and minimize unnecessary work / coordination entropy
```

The Advisor is organizationally independent of the Commander: outside the
Commander's authority, not assigned work by the Commander, and not part of the
Commander's implementation or review scheduling pool. It reports material advice
to the human and may notify the Commander. The Commander must not repurpose it as
an implementation owner, ordinary reviewer, reserve agent, deployment operator,
or merge agent. The Advisor must not assign owners or reviewers, hold deployment
leases, edit implementation PRs by default, merge or close PRs, or become a second
Commander. It has no implementation, deployment, merge, or routine approval
authority. Platform-wide concurrency limits still apply and the Advisor consumes a
slot like any other agent.

The Advisor is subject to the same slot economics as the Commander. The Advisor
role stays instantiated and available across the whole Campaign, but it holds an
execution slot only while it has an advisory question, checkpoint, or evidence to
inspect. When it has none, it checkpoints any pending advisory and yields its slot
like the Commander, and re-engages when an event or a human request makes its
independent challenge useful.

The Advisor spans the full Campaign lifecycle but is not a mandatory gate on any
PR. It performs:

- a **start review** of the Campaign goal, PR/TODO scopes, dependency DAG,
  expected evidence cost, critical path, and likely over-scope;
- a **mid-Campaign health review** of progress versus plan, merge throughput,
  review churn, scope drift, coordination overhead, blocked time, and whether
  protocol compliance is displacing delivery;
- a **pre-close review** of whether the original goal was achieved, whether any PR
  or branch has lost independent value, whether temporary state is cleaned up,
  and which lessons deserve durable protocol changes rather than new governance
  work.

It may also inspect out of cycle when an event warrants it: a PR accumulating more
than one conceptual blocker across review rounds; material scope expansion beyond
the original goal; a PR turning into a general framework; an oversized
fixture/evidence tree; an expensive deployment, GPU, or live run about to repeat;
open PRs not falling while review activity grows; blocked PRs dominating
actionable work; temporary branches accumulating; a material DAG or
acceptance-strategy change; new governance/meta work proposed mid-Campaign; or a
human request for an independent health check. A trigger invites inspection, not
automatic failure.

The Advisor forms judgment from primary evidence — Campaign instructions, PR
bodies and TODOs, current heads and diffs, important review findings, CI and live
acceptance, dependency relationships, and branch inventory — not from Commander
summaries alone. Deep line-by-line review is not required unless the Campaign-level
question needs it.

Advisories are non-blocking by default, ordered by Campaign impact, and use a
concise decision-oriented form:

```text
CAMPAIGN ADVISORY

Health:
ON TRACK | WATCH | INTERVENE

Observation:
Why it matters:
Recommendation:
Commander response:
ACCEPT | PARTIAL + rationale | REJECT + rationale
```

The Commander remains responsible for scheduling and execution and acknowledges
material advice with ACCEPT, PARTIAL + rationale, or REJECT + rationale. When the
Commander rejects material advice, both the advisory and the rationale remain
visible to the human; the Advisor must not silently take over coordination. The
Advisor escalates directly to the human only for Campaign-level red flags: the
Campaign is solving the wrong problem; a scientific or product claim materially
exceeds its evidence; a major irreversible architecture choice lacks
justification; security or privacy risk; the Campaign is clearly stalled and local
review loops are not converging; or a material blocker is repeatedly ignored
without rationale. Escalation asks for a human decision; it does not grant veto,
merge, or approval authority.

Do not create an approval chain:

```text
Owner -> Reviewer -> Advisor -> Commander -> Human -> Merge
```

Advisor approval is never required before ordinary review, merge, checkpoints,
deployment, or routine fixes; there is no Advisor checklist on every PR, and not
every advisory becomes a new issue or PR. The protocol prefers faster safe
convergence and fewer unnecessary tasks over governance accumulation — prefer
subtraction. A useful Advisor often says:

```text
do less
narrow the claim
merge the nearly-finished PR first
this dependency is only final-integration
this framework is unnecessary
this evidence can be smaller
```

### Concurrency budget

The hard ceiling is six total slots. Five useful active slots is the normal
target, not merely an upper bound: typically up to three implementation owners,
one or two active reviewers/integration agents, and coordination that is actually
required at the moment. No slot — including the Commander's — is permanently
reserved: the Commander and the Advisor occupy a slot only while executing
coordination or worth-it campaign-level work, and yield it when quiescent (see
Control-plane quiescence). One slot stays elastic and preemptible, borrowed
temporarily for review, specialist validation, debugging, or another eligible
implementation PR, and released the moment replacement, recovery, or
urgent-coordination capacity is needed. Do not leave a slot idle merely to
preserve a nominal reserve, and do not treat six-of-six saturation as a goal:
idle is correct when no useful, conflict-free work exists. Prefer at most three
implementation PRs in flight — more PRs may exist in the Campaign but stay queued
until capacity or dependency order allows them to start (see Dynamic orchestration
for how that eligibility is decided). A specialist reuses or releases another
slot rather than becoming a seventh participant. If the launch context supplies a
different current limit, that limit overrides the default.

When a slot is free, prefer the work in this order:

```text
1. implementation / blocker resolution on an eligible PR
2. merge-grade or checkpoint review with fresh evidence
3. specialist validation / integration evidence
4. bounded coordination that unlocks or reconciles work
5. passive monitoring
6. idle
```

A dormant Commander is preferable to an occupied slot while executable campaign
work is queued.

### Dynamic orchestration

A Campaign's Waves and dependencies describe a DAG, not a batch pipeline. The
Commander schedules against that DAG dynamically instead of gating every step on
a Wave boundary. This subsection adds the scheduling rule; it does not change the
budget, ownership, or merge rules above and below.

#### Waves are checkpoints, not barriers

A Campaign may group PRs into Waves for human planning, prioritization, and
integration checkpoints. By default:

```text
Wave != execution barrier
Wave != merge permission
Wave != implicit hard dependency
```

A later-wave PR may begin implementation before every earlier-wave PR has merged
when its work is independent enough to do so safely. Waves still express
intended priority, mark major integration checkpoints, and keep low-priority
work from consuming capacity while higher-priority work is actionable. If a
launch instruction explicitly declares a Wave a hard barrier, obey it.

#### Dependency classes

Do not treat every relationship as an all-or-nothing blocker. Every Campaign PR
declares exactly one **class** in the campaign control record; the class is
recorded, never inferred from a branch name:

```text
INDEPENDENT          merge order does not matter relative to its siblings,
                     beyond ordinary base drift
STACKED(parent_pr)   code depends on an unmerged ancestor: review it
                     independently, but it cannot enter the merge frontier
                     before that ancestor lands
COUPLED(group_id)    independently valid members land by sequential squash
                     in a recorded order; the group is never atomic
EXTERNAL             deliberately outside Commander ownership; still
                     participates in shared-host arbitration and main-drift
                     reconciliation
```

The class names one of three reasoning categories, or none:

**Hard implementation dependency.** The downstream PR cannot be implemented
correctly until the upstream contract, API, schema, artifact, or behavior exists.
Keep the downstream PR queued until the upstream merges (or an explicitly stacked
branch is intended); do not duplicate or guess the missing upstream contract.
This is `STACKED`.

**Final-integration dependency.** The downstream PR can do substantial useful
implementation against the current tree, but its final contract or evidence may
be invalidated by an upstream PR. Let it start when capacity allows, record the
upstream PR as a final-integration dependency, and after that PR merges
rebase/reconcile when required and rerun the affected acceptance. The downstream
PR must not reach `READY_FOR_FINAL_REVIEW` while an unresolved dependency can
still invalidate its result. This is `STACKED` when implementation itself is
blocked on the contract, and `COUPLED` when the PRs are independently
valid at every landing step, with coordinated sequential landing.

**Shared-resource / ownership dependency.** The PRs are logically independent but
cannot safely use the same mutable resource or write surface concurrently — a
deployment/live-test target, a high-conflict central schema or runtime surface, a
Runner family, or a scarce accelerator. Let implementation proceed in parallel
where safe and serialize only the conflicting operation, using the existing lease
and write-ownership rules rather than inventing a whole-PR dependency.

An `INDEPENDENT` PR states that two siblings may merge in either order; it is the
default only when that is actually true. `COUPLED` exists because "independently
reviewable" and "safe to land in any order" are different claims — a coupled set
is parallel during review and sequential, non-atomic at landing. Record the
landing order and revalidate every remaining candidate after each merge. If a
member cannot remain independently valid, use one PR or a STACKED dependency.

These classes are the explicit vocabulary for the categories above, not a second
taxonomy; a launch prompt may name them or leave the Commander to record them.

#### Ready frontier and the merge train

Commander scheduling has a second half after eligibility: deciding which already
reviewed PR is actually landable now. Maintain a small ordered **ready frontier**
instead of treating every open PR as equally merge-immediate.

For each PR at `READY_FOR_FINAL_REVIEW`:

1. confirm its dependency prerequisites — an unresolved ancestor keeps a
   `STACKED` descendant out of the frontier regardless of its own readiness;
2. inspect `main` movement since the base the PR's evidence was recorded
   against;
3. classify that drift (see Base-drift classes) and record the class;
4. run only the validation lanes the PR's risk tier and drift class require;
5. record the **merge candidate**: exact head, current base, patch identity, the
   lanes that ran, and their receipts;
6. present the maintainer one concise merge/no-merge decision.

After a merge, do not reflexively rebase every open PR. Recompute only the
descendants and the PRs whose declared dependency surface intersects the landed
change, then repeat the step above for them. The stable-review-head rule applies
throughout: once a PR is under review, changes there need a reason (a reviewer
finding, a failing required test, dependency reconciliation, or a
maintainer-directed change) rather than opportunistic polish.

A PR whose run cannot be reconstructed as a candidate — an unresolvable range, an
unclassifiable base relationship, or a conflicting merge — stays out of the
frontier and returns to the owner; it is not a merge decision.

#### Validation lanes follow the affected scope

Which validation a change set owes is decided by one classifier,
`tools/classify_ci_scope.py`, and consumed by the workflows. It answers with a
set of lanes — `docs`, `server`, `runner_fast`, `runner_scientific`, `browser`, `compose` — and
it fails closed: an unrecognized path, an empty or undeterminable change set, or
a manual dispatch selects every lane. A workflow gates a lane job on its output
being anything other than an explicit negative, so a classifier failure widens
validation instead of skipping it.

Do not add a second path policy in a workflow file, a Makefile, or a PR-local
script. Add the path to the classifier and let every consumer inherit the answer.
A scientific Runner change must never be classified as generic backend-only, and
a shared task-schema, auth, security, resource-accounting, or CI-policy change
selects the broad set.

#### Base-drift classes and evidence carry-forward

The exact-head rule exists so that no one reviews one diff and merges another; it
does not mean a human must rediscover the same findings because unrelated commits
landed on `main`. Separate what evidence proves:

```text
content evidence        what the PR itself changes
base-integration        whether that unchanged content still composes with the
evidence                current base
environment evidence    whether a live or deployment target still matches the
                        environment that was tested
```

Record a **review receipt** when merge-grade review completes, inside the PR
thread or as a structured PR comment — not in a new store. It carries the identity
the next decision needs: `pr`, `head_sha`, `base_sha`, `patch_digest`,
`changed_paths_digest`, `risk_tier`, `dependency_class`, `dependency_surface`,
`review_result`, and `reviewed_at`. The validation lanes that ran are the CI
classifier's answer, so they are not duplicated into the receipt.

`patch_digest` hashes canonical NUL-delimited raw Git file transitions against
its merge base, with rename detection disabled. The identity includes exact path
bytes, old/new modes (including symlink and executable type), and full old/new
blob IDs. Deletion and addition preserve both rename endpoints. Receipts require
`identity_format=git-raw-transition-v1`; older human-diff receipts never authorize
carry-forward. Whitespace, binary bytes, symlink targets and mode changes affect
the identity. Same-file base edits conservatively invalidate identity even if a
human patch appears unchanged. `merge_tree_oid` records the synthetic merge tree.

When `main` advances after review, classify the difference:

```text
C0  no relevant drift          unrelated docs, another Runner's fixture, a
                               backend leaf while an unrelated frontend page moved
C1  same subsystem, no         two modules in one package, two routes sharing
    content overlap            build configuration
C2  direct overlap or          same files changed, a shared schema/API changed,
    dependency surface         a dependency ancestor landed
C3  global invalidator         pyproject/lock/dependency policy, test framework,
                               CI workflow, shared trust/persistence boundary,
                               task schema or protocol, campaign protocol itself
```

The class decides the gate:

```text
C0 / C1 with an unchanged patch digest, an adoptable prior result, and no
        dependency-surface or global change
     -> prior content review is carried forward; the exact head still receives a
        fresh bounded delta/integration gate against the current base
C2 / C3, a changed patch, a stale or non-adoptable prior review, or a base
        relationship that cannot be classified
     -> fresh full merge-grade review against the exact head
```

State the outcome honestly: *content review carried forward because the patch
digest is unchanged; the current head received fresh integration/delta validation
against base X*. Never relabel a review of one SHA as a review of another, and
never carry a correctness or security verdict across a material code change.

This is the answer to "main just advanced — what must every other PR do?": not
"rebase, rerun broad CI, reacquire confidence", but "classify what actually
changed, invalidate only the evidence that depended on it, then run the smallest
safe current-main gate". For system-boundary (R3) work the strict principle is
unchanged — exact head, fresh framing, counterexample-driven review, with no
owner READY, Advisor confidence, prior approval, or green CI substituting for it.
The optimization for R3 is only that a content-identical rebase may take a
focused exact-head delta review instead of a second full rediscovery pass, and
the reviewer must still verify the unchanged patch identity and the new base
interaction explicitly.

`tools/campaign_merge_candidate.py` computes these identities (`patch_digest`,
`changed_paths_digest`, and the merge-tree of head into base) and returns the
drift decision. It is a helper any agent may run; it is not a service, holds no
state, and fails closed.

#### Eligibility-based scheduling

When a slot becomes available, treat a queued PR as eligible to start when:

1. it has no unresolved hard implementation dependency;
2. its high-conflict write ownership can be assigned safely;
3. starting it does not violate a current deployment/live-test lease;
4. enough information already exists to implement without inventing an upstream
   contract;
5. it is useful enough relative to higher-priority actionable work;
6. the Campaign remains within the concurrency budget and elastic-slot policy.

A later-wave PR meeting these conditions may start while an earlier-wave PR is
waiting for external review, fixing a narrow review finding, waiting on CI, or
waiting for a deployment window. Do not keep agents idle merely to preserve
visual Wave ordering, and do not start later work merely because a slot exists if
doing so would create speculative compatibility code, duplicated infrastructure,
or avoidable merge conflict.

#### Implementation readiness versus final readiness

```text
eligible to implement
        !=
eligible for final review
```

A PR with a final-integration dependency may make commits, test locally, and
complete most of its TODO before the upstream PR merges. Before reporting it
`READY_FOR_FINAL_REVIEW`, the owner and Commander confirm that required upstream
PRs are merged, the branch is rebased/reconciled when the dependency affects it,
upstream contract changes were actually consumed, affected tests and
live/scientific acceptance were rerun, and the evidence still describes the exact
final head. This keeps early parallelism from becoming stale acceptance evidence.

#### Event-driven re-evaluation

Re-evaluate the Campaign DAG when meaningful events occur rather than only at
Wave boundaries: a PR becomes blocked; a PR reaches `READY_FOR_FINAL_REVIEW`; a
review finding narrows or expands an upstream contract; a PR is squash-merged; CI
or live acceptance completes; a deployment/live-test lease is released; a shared
write surface becomes free; an agent slot becomes available; or a cross-PR
discovery creates or removes a dependency. Each pass answers what remains
blocked, what became eligible, what must rebase/reconcile, what resource can be
leased next, and what should remain queued. No constant polling or process
ceremony is required — react to state changes.

#### Proactive Commander communication

The Commander does not wait for owners to report final readiness. On each
meaningful event it observes, messages the affected agents, and schedules the next
action: a new coherent PR head appears — ask which checkpoint completed and
schedule review; CI finishes — tell the owner or reviewer what changed and
schedule the next action; findings arrive — forward them immediately; findings are
fixed — arrange the follow-up review without waiting for final completion; a
dependency merges — notify affected owners and trigger reconciliation or rebase; a
deployment lease frees — offer it to the next eligible PR; an agent goes idle —
re-evaluate queued implementation, review, and specialist work. Routine
coordination happens directly among agents, not through the human operator. The
desired loop is: owner reaches a checkpoint, review runs immediately, findings are
returned, the owner fixes them, and a follow-up review is scheduled.

#### Worked example

```text
Wave 1
  A — upstream evidence contract
  B — independent correctness fix

Wave 2
  C — can implement now, but must reconcile with A before final review
  D — independent scientific Runner work

Wave 3
  E — hard-depends on C

A receives a narrow review blocker.
B merges.

The Commander may keep A fixing, start C with A recorded as a final-integration
dependency, start D independently, and keep E queued.

After A merges: C rebases/reconciles and reruns affected acceptance.
After C merges: E becomes eligible.
```

The example shows that planning Waves and the actual dependency DAG are not the
same thing: C crossed a Wave boundary safely, while E stayed queued on a hard
dependency.

### Worktrees and write ownership

The primary repository checkout is the **Commander's control root** — a control
plane, not an implementation workspace. The Commander uses it to fetch and prune
remote state, keep `main` synchronized with `origin/main`, inspect PR, branch,
and worktree state, create and retire PR-scoped worktrees, observe merge events,
and broadcast updated main and dependency state. It normally satisfies:

```text
branch = main
working tree = clean
main = synchronized with origin/main
```

The Commander is the only Campaign role that performs routine control-root
operations, such as fetching and pruning, fast-forwarding a clean `main`, and
listing or pruning worktrees. No implementation owner, reviewer, specialist,
recovery agent, or other delegated subagent edits files, switches the checkout
off `main`, commits, or runs destructive branch operations in the control root. A
subagent whose `git rev-parse --show-toplevel` resolves to the control root stops
before modifying anything and reports the violation. If the control root is dirty
or off `main`, treat that as a Campaign infrastructure fault and resolve it
before further dispatch; never resolve a PR conflict or stage an emergency fix
there.

Each open PR has one canonical implementation worktree — a linked git worktree
bound to that PR's canonical branch — and one implementation owner:

```text
one open PR
-> one canonical remote branch
-> one canonical implementation worktree
-> one implementation owner
```

A Commander dispatch for implementation work carries that worktree path
explicitly:

```text
PR: #<number>
canonical branch: <branch>
worktree: <absolute path>
observed main: <sha>
role: owner | reviewer | specialist
```

The subagent verifies before work that `git rev-parse --show-toplevel`,
`git branch --show-current`, and its clean status match the assignment. Naming
only the PR number is not enough; name where its worktree is. One worktree must
not implement multiple open PRs, and two worktrees must not both claim canonical
ownership of one PR.

Parallel reading is unrestricted, but concurrent writes to a high-conflict shared
surface need one explicit owner at a time. Likely surfaces include the global
frontend shell/styles, OpenAPI/schema ownership, central server routes/contracts,
shared task/runtime infrastructure, a single Runner family, and common
deployment/runtime code. When two PRs require substantial writes to the same
surface, the Commander serializes them or explicitly stacks one on the other
rather than letting both race and relying on a later conflict resolution pass.

A reviewer must not mutate the control root. Read-only review inspects the PR
through GitHub, the API, or a diff. When writable local reproduction is required,
the reviewer creates a short-lived review worktree — for example
`worktrees/review-pr<N>-<short-id>` — not the control root and not the PR's
canonical implementation worktree. A review worktree produces findings, not
uncoordinated implementation commits: it is not a new remote source of truth, and
it is removed when the review or reproduction task ends. If the reviewer is
delegated to fix the PR, ownership transfers or the Commander coordinates the
commit path into the canonical worktree and branch.

Rebase and recovery operations stay outside the control root; see Canonical PR
branches and cleanup for their lifecycle rules.

These rules remove coordination ambiguity rather than adding an approval layer.
Assigning a worktree path is part of normal scheduling, and the Independent
Campaign Advisor may audit the control plane — a clean, synchronized, on-`main`
control root, one canonical worktree per active PR, no subagent in the control
root, no active worktree on a merged or closed PR, no accumulating scratch
worktrees or branches, and no mechanical rebase demands — without entering the
execution chain.

### Canonical PR branches and cleanup

An open PR has exactly one canonical remote implementation branch that its head
tracks. Temporary rebase, recovery, or scratch branches may exist only while they
are needed for a handoff or recovery; once their commits have been transferred
into the canonical branch, the Commander prunes them. Do not assume GitHub
deletes a merged branch. At Campaign completion, and at each PR merge or close,
perform an orphan-branch sweep: list the remote branches, keep `main` and the
canonical branch of **every** open Campaign PR — active, queued, blocked, or
awaiting review alike, not only the currently active slots — and delete every
other Campaign branch after confirming it carries no unique work absent from its
canonical branch or `main`. Branch cleanup is an explicit Campaign responsibility
unless repository configuration is independently verified to do it.

Do not create routine `-r2`, `-r3`, `-rebased`, or `-recovery` remote branches.
Recovery and rebase experiments prefer local temporary refs, a temporary
review/recovery worktree, or a short-lived scratch branch only when Git mechanics
genuinely require it. Any scratch branch or worktree has an explicit owner and
retirement condition and never becomes a second long-lived source of truth for
the same PR. When history rewriting is necessary, keep the PR's canonical branch
identity, require explicit authorization where force-push policy demands it,
avoid permanent alternate remote heads, retire the recovery worktree and branch
after the handoff, and report the exact resulting head SHA.

A merged or closed PR is a lifecycle event, not merely a GitHub state change: it
ends that PR worktree's normal lifecycle. When the Commander observes a merge it
synchronizes the control root — fetch/prune, fast-forward the clean checkout to
the new `origin/main` — and records:

```text
MERGE EVENT
PR: #<number>
old main: <sha>
new main: <sha>
```

It then broadcasts the main advancement to the owners whose dependencies or
integration bases may be affected, naming which PRs reconcile now, which should
reconcile before final merge, which remain blocked, and which need no action. It
does not mechanically require every worktree to rebase after every merge; see
Rebase policy.

**Post-merge owner cleanup.** A merge is not the end of a PR's operational
lifecycle. Before retiring the merged PR's worktree and execution state, the
Commander notifies the former owner to perform one final bounded cleanup of
PR-owned execution residue, and the owner reports completion back. The owner
removes the PR-scoped working state it created — CI/test scratch directories,
temporary pytest/run directories, generated acceptance or debug output not meant
for version control, temporary browser/render evidence once any required durable
evidence is retained, PR-owned deployment/live-test scratch, and other
worktree-local generated residue. The owner does not remove canonical fixtures,
committed scientific evidence, acceptance receipts the product or protocol
requires, shared caches or databases, another PR's workspace, or a host-level
shared directory whose ownership is not proven. The owner makes that
distinction because it has the best local implementation context; when it is
unsure whether a path is disposable or durable, it keeps the path and reports
the question. The intended lifecycle is:

```text
design -> implement -> review -> retire TODO / IMPLEMENTATION_STATE
       -> READY_FOR_FINAL_REVIEW -> merge
       -> owner cleans PR-owned CI/runtime residue
       -> Commander verifies retirement -> worktree/branch lifecycle cleanup
```

The cleanup request is a wake event like any other: the Commander wakes briefly
to reconcile downstream PRs and issue it to the former owner, then yields again,
and neither role stays active merely to wait for the completion report (see
Control-plane quiescence). Once cleanup is confirmed and no unique work remains,
retirement proceeds as below.

Finally it retires the merged PR's execution state: confirm no
uncommitted changes, no unique commits absent from the merged PR, and no
artifact or evidence that exists only in the worktree and is still required, then
remove the implementation worktree, prune the merged canonical branch when
repository policy permits, prune obsolete scratch and recovery worktrees and
branches, and run worktree pruning. Never silently discard unique work. A
merged or closed PR must not keep an active implementation worktree indefinitely,
and a queued open PR may retain its worktree but stays uniquely bound to that
PR. The Commander tracks each PR as at least:

```text
PR | canonical branch | worktree | owner | state | observed-main
```

with states such as QUEUED, ACTIVE, BLOCKED, REVIEW, READY_FOR_FINAL_REVIEW, and
MERGED/RETIRE or CLOSED/RETIRE. That is the whole control record; a PR's
dependency class, risk tier, patch digest, drift class, required next gate, and
any shared-resource lease are the additional coordination facts worth carrying,
and detailed findings stay in the PR thread. Do not grow a private working set
beyond what those decisions need, and never a campaign database.

Treat these as Campaign infrastructure violations and resolve the infrastructure
state before creating more parallel work: a control root dirtied or switched away
from `main` by subagent work; multiple implementation worktrees claiming
canonical ownership of one PR; one worktree implementing multiple open PRs; a
subagent dispatched without an explicit worktree; a merged or closed PR worktree
left active without reason; an unowned scratch worktree or branch with unique
work.

### Root TODO.md semantics

A PR's root-level `TODO.md` and `IMPLEMENTATION_STATE.md` (and their
`TODO_<slug>.md` variants) are ephemeral PR-local execution artifacts, not durable
repository state. They are allowed while the PR is active, but they describe the
work in progress, not the product: the merged PR and its Git history already
preserve the planning and execution record, so `main` should describe the current
product rather than retain completed PR scratch state.

Because these files are gitignored (`.gitignore`), a worktree copy is not
normally tracked churn, and removing one is a `git rm` (untrack) — the ignore
rule stays. A PR branch may legitimately carry its own `TODO.md`, and reviewers
and the Advisor must not reject a PR merely because its copy differs from
`main`; there is no need to proliferate `TODO_PR<number>.md` files to avoid
normal PR-local differences.

#### Retire PR working artifacts before final review

Before a PR reports `READY_FOR_FINAL_REVIEW`, remove its ephemeral working
artifacts from the final tree:

1. extract every still-durable architectural rule, operational limitation, or
   reusable guidance into its canonical documentation owner (see
   [Writing Documentation](../developer-guide/documentation.md)) — not into a
   fresh scratch file;
2. move genuinely unfinished work into an explicit follow-up issue or PR rather
   than leaving it implied in a discarded TODO;
3. remove the PR's `TODO.md` (and its `IMPLEMENTATION_STATE.md` if it has one);
4. remove or migrate every reference that still points at either file, including
   repository tooling and manifests;
5. confirm the merged tree does not depend on the removed notes.

Durable project or Campaign policy belongs in stable documentation such as
`CLAUDE.md`, this protocol, and the developer/operator docs.

### Per-PR execution state

A single long-running task may use the repository's conventional `TODO.md` and
`IMPLEMENTATION_STATE.md` while it is in flight. Concurrent PRs must not share one
mutable planning file. Worktree isolation already gives each PR its own copy of a
shared filename, so distinct worktrees may each carry `TODO.md`; a PR-specific
filename such as `TODO_<slug>.md` / `IMPLEMENTATION_STATE_<slug>.md` is needed
only when two PRs would otherwise collide on the same checkout or branch. The
invariant is one mutable execution truth per PR; the filename is not fixed when a
PR already has a clear, unambiguous design/state document. Both files are
retired before `READY_FOR_FINAL_REVIEW` as described above.

### Rebase policy

Do not rebase a branch merely because `main` advanced. Rebase when a declared
upstream or dependency PR has merged, when `main` changed a contract or shared
surface the PR depends on, when a real conflict or CI contract drift appears, or
when the PR enters final review and must be evaluated against current `main`.
After a meaningful rebase, rerun the affected focused gates and any acceptance
whose evidence the rebase could have invalidated. Independent PRs may keep
implementing on their existing base while unrelated changes land elsewhere.

### Deployment and live-test lease

A real deployment target is a shared mutable resource: only one agent may hold a
deployment or live-test window at a time. A PR owner requests the window from the
Commander; the Commander grants a lease for one PR at an exact head SHA; the
deployed SHA is recorded before acceptance begins; no second owner redeploys
until that acceptance finishes or is explicitly abandoned; and the lease is
released afterward. Keep this guidance host-neutral — host names, proxy flags,
local database-path drift, credentials, and handoff paths belong in the launch
prompt or environment handoff. Do not deploy merely for completeness: frontend
fixture, documentation, and similar changes receive a window only when their
acceptance contract needs the real production path.

### Heavy-work host lease

Campaign agent slots and physical host work are different resources. The slot
budget answers how many reasoning or implementation agents may be active; a
*knowledge* host lease answers how many heavy physical workloads may run on this
machine now. Control-plane ownership being independent — a Commander-owned PR and
an unrelated external agent session — does not make RAM, swap, CPU, disk
bandwidth, Docker/build cache, browser workers, or the demo deployment
independent, and an over-subscribed development host can take down the shared
demo stack for everyone.

This PR documents existing host practice; it does not implement or machine-verify
a heavy-work lease wrapper, metadata inspection, or contention/death acceptance.
Those mechanisms are deferred. Preserve the existing adopted host lock.

Where the host already runs an adopted shared heavy-work lock, that lock **is**
the lease: this protocol points at it rather than defining a second mechanism,
because two leases would be two sources of truth. Record its canonical path in
the launch prompt or host handoff, and use it as follows.

Treat these as heavy on a shared development host: full browser/Playwright
acceptance, full Python coverage under `xdist`, Docker/Compose builds, large
dependency installs, deployment or redeployment, image/SIF builds, and any other
command measurement shows creating memory or I/O pressure. Wrap them in the
shared lock with a bounded wait, and inside it, after acquisition:

- read `free -m` and `/proc/pressure/memory`; stop and report rather than
  proceeding when the host is already under pressure;
- run the command in a resource-capped scope (a `systemd-run --user --scope`
  with a memory and swap cap) where the host supports one;
- use explicit small worker counts, never `auto`;
- put bulk scratch and build output in a PR-owned directory, with a repository-
  filesystem pytest basetemp and `-p no:cacheprovider`;
- record the exact command, cap, and observed cost in the PR's evidence.

A Docker or Compose build runs in the daemon rather than the caller's session, so
a user-scope memory cap does not bound it; the lock is its only host-safety
control, and deploy/restart must take the same lock. Never delete or replace the
lock file while another agent may hold it — recreating it swaps the inode and
silently defeats exclusion. Never retry-loop a contended lease: one bounded wait,
then defer and record.

Ordinary coding and review do **not** take the heavy lease; an agent may keep
working while another process owns the heavy slot. Use the same lock, not a new
one, for a shared demo deployment window, and keep production out of routine
campaign scratch state.

The same distinction applies to the liaison bus below: `HEAVY_LEASE_ACQUIRED` /
`HEAVY_LEASE_RELEASED` and the deployment equivalents announce the shared-resource
state that the lock enforces. The bus announces; the lock excludes.

### Review model

Review is continuous Campaign work, not an end-stage gate. A PR is reviewed at
coherent checkpoints while implementation progresses, and the owner normally
keeps working while a reviewer checks a completed checkpoint. Do not fan out
three reviewers for every checkpoint, and never let two reviewers duplicate the
same review. The default is the PR owner self-reviews and runs focused tests; a
reviewer does a bounded checkpoint or integration pass; a specialist review runs
only when risk justifies it — scientific correctness, security/auth,
scheduler/runtime behavior, a substantial API/schema migration, or a substantial
visual/interaction redesign; then external final review. Keep implementation
review, integration/cross-PR review, and external final review distinct, and do
not spend multiple slots duplicating one review. The three-perspective Pre-final
review cell is the one place a substantive PR is reviewed from three independent
angles at once, and only at implementation-complete. The rule in `CLAUDE.md`
against retriggering automated review after every small push still applies.

#### Batch findings per pass

A reviewer collects merge-level findings into one coherent pass rather than
dripping one issue at a time; the owner then fixes the batch and the reviewer
rechecks only the affected findings. Findings themselves are unbounded prose, but
the control-plane summary a reviewer returns to the Commander stays small:

```text
merge / no-merge
blocker category
owner
Advisor confidence or concern
next event
```

Do not start merge-grade review against a PR that is still implementing, except as
an early architecture intervention; review a declared stable review head.

#### Review risk tiers

Scale review effort to systemic risk rather than applying one review depth
everywhere. This is a scheduling aid, not a new label or metadata file.

```text
R1  low systemic risk       prose/docs, local copy changes, visual polish with
                            preserved behavior, bounded fixtures, non-semantic
                            metadata -> ordinary independent review
R2  ordinary implementation ordinary API behavior, Runner adapters, bounded
    risk                    business logic, protocol projections, non-privileged
                            state -> independent correctness review at exact head
R3  system-boundary risk    security/trust boundaries, auth/authz, filesystem
                            publication, persistent state, database transactions,
                            quota/accounting, concurrency, scheduler lifecycle,
                            privileged control-plane operations, irreversible
                            migrations, cross-process crash recovery
                            -> merge-grade, fresh-framing, counterexample-driven
                            adversarial review at a high reasoning budget
```

#### Reviewer quality and independence

A reviewer is not merge-grade merely because it is independent of the
implementation worktree. Review quality has separate dimensions — model and
reasoning capability, context independence, review mandate, review budget, access
to primary evidence, and the ability to reject the existing framing. The reviewer
of a high-risk PR must not be intentionally weaker than the implementation owner
because review looks cheaper; for system-boundary PRs, prefer the strongest
reasoning configuration the campaign can afford, and avoid a topology in which
implementation, review, and final challenge all inherit the same model, framing,
and author summary — one strong independent challenge beats several correlated
shallow reviews. Do not encode vendor-specific model names in this protocol.

#### Fresh-context merge review

The merge-grade reviewer for R3 work minimizes framing inheritance. Prefer this
evidence order:

```text
governing invariants
-> current main / base
-> exact PR diff and runtime/data-flow
-> tests and acceptance evidence
-> PR review threads
-> owner / Commander READY summaries
```

The reviewer forms an independent failure model before reading the author's
conclusion that the PR is ready. A reviewer may conclude that the implementation
satisfies the stated TODO while the TODO or acceptance model still misses a
system invariant, without being out of scope.

#### Counterexamples and transition evidence

Merge review of R3 work attempts to falsify the design rather than confirm
expected behavior. Consider the categories materially relevant to the changed
boundary and construct at least one plausible counterexample sequence before
declaring the PR clean:

```text
TOCTOU
crash between adjacent state transitions
duplicate / replayed / out-of-order events
lost acknowledgements
concurrent actors and stale snapshots
authority duplication or self-authorizing metadata
unknown interpreted as zero
identity / event conflation
cleanup / reconciliation races
partial persistence, or retry after partial side effects
```

For lifecycle, scheduler, accounting, cleanup, migration, or operator-control
changes, review the transition edges, not only the states. For each material edge
`State A --[physical evidence / durable event]--> State B` the reviewer asks who
triggers it, what physical evidence proves it, where that evidence becomes
durable, what a crash immediately before or after does, whether the event can
repeat or arrive out of order, and how reconciliation distinguishes the resulting
cases. A state model with correct nouns but incorrect transition evidence is not
merge-ready.

#### READY is non-transitive

Owner `READY_FOR_FINAL_REVIEW`, Advisor confidence, a prior reviewer's approval,
and green CI are evidence; none implies merge-ready by itself. A merge-grade
reviewer forms its own verdict against the exact current head, and any material
new commit invalidates exact-head evidence that depended on the previous head.
Do not rerun a full expensive review for a trivial docs-only change when the
reviewer can bound the invalidated evidence precisely, but never carry a
correctness or security verdict across a material code change by assumption.

#### Findings live in PR threads

The PR review thread is the canonical detailed technical record of a finding;
Commander control state carries only the compact coordination summary described
in Control-plane quiescence. When a reviewer finds a blocker, it writes the
finding and its evidence to the PR thread and tells the Commander only whether
the PR may merge and the broad blocker class. The owning subagent then reads the
thread itself, restates the finding in its own words, verifies it against the
exact current head, makes the smallest correct fix, adds regression or adversarial
evidence that covers the governing invariant, and returns to
`READY_FOR_FINAL_REVIEW`. The full technical review is not copied into campaign
control state.

The Advisor may independently check, while a finding is being resolved, whether
the subagent understood the finding rather than patched its symptom, whether the
fix stays inside the PR's scope and preserves the architectural owner without
creating a second source of truth, whether the regression evidence covers the
governing invariant, whether repeated review churn signals a missing
campaign-level assumption, and whether the PR is converging toward merge or
expanding into a framework. For R3 PRs and repeated conceptual blockers such an
out-of-cycle challenge is expected rather than optional. The Advisor does not
duplicate line-by-line findings, gate approval, or take implementation ownership.

#### Review stopping rule

Stop review when governing invariants are explicit, all known blocking findings
are closed, the exact head has green required, branch-protected CI/acceptance
evidence, a fresh merge-grade reviewer cannot construct a new material
counterexample, the relevant transition/crash/adversarial cases have evidence,
and the remaining observations are explicitly non-blocking hardening or future
work. A claimed new counterexample counts as material only when it is a concrete
reproducible sequence touching the changed boundary, or — for R3 work — an
identified gap in durable transition evidence, since an absence of evidence is a
legitimate blocker that no reproducible sequence can express. The merge-grade
reviewer, or the Advisor when the reviewer cannot be recalled, must concur before
a blocking finding is downgraded; the Commander alone must not reclassify an R3
blocker as non-blocking hardening, and a downgrade records its reason. The goal
is not to prove absence of all bugs but to have no known reason the exact head is
unsafe or architecturally incorrect to merge.

#### Checkpoint-driven review

Review is checkpoint-driven, not commit-driven and not final-only. Trigger a
review when a meaningful TODO section completes, a coherent implementation
commit or checkpoint lands, focused tests go green, a prior finding is resolved,
a rebase or reconciliation completes, live or scientific acceptance completes, a
shared contract changes, and immediately before `READY_FOR_FINAL_REVIEW`.

#### Dynamic reviewer assignment

Do not model one rotating reviewer as the only reviewer, and do not wait for a
dedicated reviewer slot before reviewing a useful checkpoint. Assign reviewer
roles dynamically from available Campaign capacity. An idle PR owner may
temporarily peer-review another PR when there is no ownership conflict, the review
is bounded, the owner stays accountable for their own PR, and no circular
dependency results. Reviewer identity is temporary; PR ownership stays fixed.

#### Bounded owner review delegation

An owner may use at most one Commander-budgeted ephemeral reviewer or specialist
at a time, for one bounded review task, within the global ceiling. Such a
delegate may inspect code, diffs, and evidence; run focused validation; perform
scientific, security, runtime, or UI specialist review; and report findings. It
may not become a second implementation owner, touch unrelated scope, create PRs,
recursively fan out, start another reviewer, or merge anything. The Commander
controls the budget and may revoke or reassign the delegation. A short-lived
review lease records it:

```text
REVIEW_LEASE
PR: #N
scope: scientific fixture | API contract | runtime | frontend
slots: 1
expires when findings are reported
```

The vocabulary is optional; the bounded behavior is required. Evidence-footprint
review (see Bounded evidence and fixture footprint) is an example of a checkpoint
triggered while a scientific fixture is being designed, not only after completion.

### Bounded evidence and fixture footprint

Durable evidence stays proportional to the claim it proves. A generated output is
not a source artifact merely because a successful run produced it: committing an
entire runtime output directory is not the default reproducibility strategy. The
default question before retaining a generated file is:

```text
Which claim requires this file to remain in Git?
```

If the only answer is "the program produced it", do not keep it by default. File
count and review surface matter alongside byte size, so a fixture whose every
retained file maps to an explicit assertion is stronger evidence than a full
output snapshot.

Different verification goals need different durable evidence:

- **Scientific reference fixture** proves scientifically meaningful observables
  and detects adapter or implementation regressions. Prefer a pinned real input,
  upstream/version/method provenance, a compact independently generated
  expected-observable receipt, the minimum sufficient raw upstream files needed
  to re-derive the critical observables, representative raw cases for
  parser/geometry/contact edge cases, explicit tolerances with
  negative/perturbation tests, and a command for rebuilding the full upstream
  output when the executable and environment are available. Do not commit every
  per-item or per-residue output file when a bounded subset proves the claim.
- **Frontend real-result replay** proves the production frontend renders
  authentic Runner result semantics and selected real artifact bytes. Prefer the
  canonical ResultManifest/API projection, renderer-required artifact payloads,
  bounded representative payloads, hashes/size/reason records for excluded large
  or binary artifacts, and sanitized provenance. Do not turn replay into an
  archive of the full task result directory.
- **Production/live acceptance** proves an exact deployment executed through the
  real scheduler/runtime/API path and published a valid result. Prefer a
  machine-readable receipt, exact deployment/task/job/image/input/parameter
  identity, lifecycle and validation state, an artifact inventory with hashes,
  and the selected observables the acceptance claim needs. Do not check in the
  entire job workspace merely to prove the run happened.

#### Independence without snapshot inflation

Independent validation means the expected result must not be derived through the
same production code path under test; it does not mean every upstream output byte
must live permanently in Git. A small raw fixture, an independent
parser/reference builder, compact expected observables, and a production-adapter
comparison preserve independence without a full snapshot; so does a real run on
the target recorded as a machine receipt plus hashes plus selected durable raw
evidence. When a compact receipt already records the complete expected values,
retain only the raw files required to audit or re-derive the highest-value claims,
unless full-tree identity is itself under test.

For example, when a program emits one global descriptor table plus many
per-object geometry or contact files, a good scientific fixture keeps the
complete descriptor table when it proves global counts and ranking, a small
representative subset of per-object files that exercises geometry, contact,
parsing, or edge-case semantics, a compact reference receipt with the expected
global values, and negative tests showing the claims fail when perturbed.

A complete raw tree remains permitted when completeness is genuinely the claim:
the contract requires every artifact to be present, parser completeness across
all members is the behavior under test, cross-file relationships cannot be
reconstructed from a bounded subset, exact raw-byte identity is the acceptance
target, or the fixture is itself a small stable upstream conformance corpus. When
full output is retained, the PR must state why a bounded subset would be
insufficient. An archive can reduce repository path noise and preserve exact
bytes, but it hides the change from review; do not compress merely to hide an
unnecessarily broad fixture.

#### Generated-output review checkpoint

Before a PR with generated fixtures or evidence reaches
`READY_FOR_FINAL_REVIEW`, the owner and reviewer inspect the evidence footprint
and require a short justification when generated files materially dominate the
diff by file count or review surface. The review answers which explicit claim
each retained class of generated file supports; whether a compact
expected-observable receipt plus a representative raw subset could prove the same
claim; whether the fixture tests scientific semantics, parser behavior, frontend
rendering, or merely snapshot identity; whether large, binary, or volatile
outputs are represented more cleanly by hashes and metadata; whether another
developer can reproduce the omitted full output from the pinned input, version,
parameters, and documented command; and whether the pattern would stay reasonable
for a Runner that emits hundreds or thousands of files. Do not establish a
convention that works only because the current example is small, and do not
introduce a fixed byte-count or file-count threshold.

Evidence footprint is a review-quality constraint, not a new dependency class and
not a Wave barrier. The Commander treats footprint cleanup as part of the owning
PR when it concerns that PR's fixture design, does not spawn a broad repository
cleanup because one PR exposed the pattern, surfaces a footprint concern during
implementation or review before final readiness, lets independent Campaign work
continue under Dynamic orchestration, and preserves external/human merge
authority.

### Cross-PR findings

Parallel work makes incidental discoveries common. An owner that finds a defect
outside its PR scope reports it to the Commander instead of absorbing the change.
The Commander decides whether it blocks the current PR, belongs to another active
PR, needs a new follow-up PR, or is explicitly deferred — preserving narrow
ownership rather than turning the campaign into an unbounded cleanup.

### Campaign completion

Report a PR as `READY_FOR_FINAL_REVIEW` only when its required TODO/design items
are complete, its worktree is clean, its focused tests and required repository
gates pass, required live acceptance is recorded, review findings are resolved,
no dependency or rebase remains pending, and its exact head SHA is reported. For
a PR admitted early under Dynamic orchestration, "no dependency remains pending"
means any final-integration dependency has been reconciled and its affected
acceptance rerun against the exact final head.
Before declaring the Campaign ready, the Commander provides an integration
summary: each PR and exact head SHA, the current dependency and merge order, test
and live-acceptance evidence, known deferred issues, which PRs must rebase after
an earlier PR merges, and any unresolved cross-PR ownership or contract risk.

The normal workflow is: the campaign team brings PRs to
`READY_FOR_FINAL_REVIEW`; an external reviewer performs the final code review;
findings are fixed if needed; PRs are squash-merged along the dependency DAG.
Automatic merging is not part of this protocol.

### Pre-final review cell

Internal review is owner-side quality control before external final review, not
another approval bureaucracy. A substantive PR moves through
`ACTIVE → READY_FOR_INTERNAL_REVIEW → INTERNAL_REVIEW → FIX / TARGETED_RECHECK →
READY_FOR_FINAL_REVIEW`; the intermediate states stay distinct from
`READY_FOR_FINAL_REVIEW` so review progress is legible without becoming a gate.

When a substantive PR reaches implementation-complete, the owner freezes an exact
head SHA and the Commander dispatches three independent review perspectives:

- **Correctness / Contract** — implementation against the PR body and worktree
  TODO; scientific, API, and Runner semantics; correctness bugs and contract
  violations.
- **Evidence / Test** — whether tests, fixtures, provenance, and acceptance
  actually prove the claims; self-authored-evidence loops, missing negatives,
  oversized fixtures, unsupported equivalence.
- **Integration / Scope** — interaction with `main`, shared surfaces, and active
  PRs; regressions, duplicate abstractions, scope drift.

Reviews stay independent until submission: one reviewer's conclusions are not
exposed to another before findings are in. Reviewers are read-only by default and
never mutate the Commander control root or an owner worktree; when writable
reproduction is needed they use a short-lived review worktree removed afterward.

The Commander consolidates the three reports before returning findings —
deduplicate, reject style or preference not tied to the claim, classify
blocker / material / optional, and preserve the rationale for rejected findings,
returning one bounded finding set. Raw reports are not forwarded to the human.
Reviews bind to an exact head and the reviewed surfaces. After fixes, the
reviewer whose finding was affected performs a targeted recheck; all three are
not automatically repeated. A full three-way review is repeated only after a
material rewrite of the reviewed contract, scientific claim, or architecture.
Trivial, docs-only, or reconciliation-only PRs may take a reduced path at
Commander discretion. The Independent Campaign Advisor is not one of the three
reviewers and stays outside the execution and review chain.

Required acceptance may not be silently converted to deferred. When required
evidence cannot be obtained, either narrow the claim so the evidence is no longer
required, keep the PR blocked, or escalate the limitation to the human explicitly.
The Commander or Advisor may recommend a narrower claim but must not silently
waive a hard scientific or product acceptance requirement.

### Direct coordination

Where the agent environment supports peer communication, agents coordinate
directly rather than routing routine messages through the human operator —
ownership claims, dependency completion, rebase requests, deployment-window
requests, shared-contract changes, blockers, and readiness for review. A compact
status vocabulary keeps concurrent agents unambiguous:

```text
CLAIMED
IMPLEMENTING
TESTING
REVIEW
READY_FOR_INTERNAL_REVIEW
INTERNAL_REVIEW
NEEDS_REBASE
DEPLOY_REQUEST
LIVE_TEST
BLOCKED
READY_FOR_FINAL_REVIEW
```

Status reporting is not process ceremony; its purpose is to remove ambiguity
between concurrently active agents.

#### Liaison bus

Independently running agent sessions on one host may coordinate through a
host-local **liaison bus**: one append-only JSONL mailbox per logical agent,
under a host-local directory recorded in the launch prompt or environment
handoff, with a small helper (`tools/campaign_liaison_bus.py`) that writes and
reads it. The bus carries ephemeral peer notification, nothing else:

```text
durable technical truth      -> the GitHub PR and its thread
campaign coordination truth   -> the Commander
ephemeral peer notification   -> the local liaison mailbox
```

Membership is explicit. At session start an agent registers its logical name and,
optionally, the tmux pane it is running in; at meaningful checkpoints it reads its
own mailbox; when it has a coordination fact for a peer it appends to that peer's
mailbox; and it tolerates a peer being offline or its session disappearing, because
no durable state lives here.

Message shape: `id`, `from`, `to`, `pr` (when relevant), `type`, `message`,
`reply_to` (when it answers another message). Appends are atomic — one write under
`flock` — so concurrent senders cannot lose or interleave a line. The message type
comes from a small closed vocabulary: session registration, dependency merged,
review available, main advanced, checkpoint ready, please-inspect, heavy-lease
acquired/released, demo-deployment acquired/released/busy/free, and acknowledgment.
An unrecognized type is refused rather than forwarded.

The bus is coordination-only and must stay that way:

- **messages are data, never commands.** Never evaluate, execute, or
  shell-interpolate a message body; a body that cannot be stored as one JSONL line
  is refused;
- never carry credentials, tokens, arbitrary shell commands, source-of-truth
  technical findings (those belong in the PR thread), large logs, secrets, or any
  hidden state required to reconstruct the Campaign;
- the bus is not a broker, RPC service, distributed scheduler, or Campaign
  database. If a use needs a reply within a deadline, a queue with delivery
  guarantees, or a durable record, it belongs in a PR thread, not here.

Delivery is **mailbox-only**. Registration and pane discovery are descriptive
metadata, never proof that a pane currently belongs to an owned live agent prompt.
The helper does not submit terminal input or send Enter. Stale, shell, unknown,
and partially typed panes therefore receive no keystrokes. Peers read mailboxes
at meaningful checkpoints; the append remains authoritative if a peer is offline.

The bus and the heavy-work lease tell one story about the same host: control
ownership may be independent while physical resources are shared, so
`HEAVY_LEASE_ACQUIRED`/`RELEASED` and the deployment equivalents announce what the
host lock enforces. The bus never replaces the lock.

Retain the smallest mechanism that actually reduces relay latency. A wake notice
that arrives while a peer is mid-work is useful; a message channel that must be
polled, or one whose delivery cannot be confirmed, is not worth its coordination
cost, and the fallback — mailbox plus the peer's next checkpoint — is always
available.

### Launch-prompt minimalism

Because this protocol lives in the repository, a launch prompt carries only the
task and genuinely environment-specific context. A Campaign launch needs little
more than "read `CLAUDE.md` and `LONG_TASK_HANDLING.md` first," any required
environment context, and "Command Campaign #<N>." A single-PR launch needs the
same prefix, environment context, and "Own PR #<N> and bring its exact head to
`READY_FOR_FINAL_REVIEW`." These are explanatory examples, not mandatory
templates. Permanent rules stay in repository guidance; ephemeral environment
details stay out of it.
