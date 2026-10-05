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

### Concurrency budget

The hard ceiling is six total slots. Five useful active slots is the normal
target, not merely an upper bound: typically one Commander, up to three
implementation owners, and one active reviewer/integration agent. The sixth slot
is elastic and preemptible — borrowed temporarily for review, specialist
validation, debugging, or another eligible implementation PR, and released or
preempted the moment replacement, recovery, or urgent-coordination capacity is
actually needed. Do not leave the sixth slot idle merely to preserve a nominal
reserve, and do not treat six-of-six saturation as a goal: idle is correct when no
useful, conflict-free work exists. Prefer at most three implementation PRs in
flight — more PRs may exist in the Campaign but stay queued until capacity or
dependency order allows them to start (see Dynamic orchestration for how that
eligibility is decided). A specialist reuses or releases another slot rather than
becoming a seventh participant. If the launch context supplies a different
current limit, that limit overrides the default.

When a slot is free, prefer the work in this order:

```text
1. review of a fresh coherent checkpoint
2. specialist validation
3. unblock / debug
4. another eligible implementation PR
5. idle
```

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

Do not treat every relationship as an all-or-nothing blocker. Distinguish:

**Hard implementation dependency.** The downstream PR cannot be implemented
correctly until the upstream contract, API, schema, artifact, or behavior exists.
Keep the downstream PR queued until the upstream merges (or an explicitly stacked
branch is intended); do not duplicate or guess the missing upstream contract.

**Final-integration dependency.** The downstream PR can do substantial useful
implementation against the current tree, but its final contract or evidence may
be invalidated by an upstream PR. Let it start when capacity allows, record the
upstream PR as a final-integration dependency, and after that PR merges
rebase/reconcile when required and rerun the affected acceptance. The downstream
PR must not reach `READY_FOR_FINAL_REVIEW` while an unresolved dependency can
still invalidate its result.

**Shared-resource / ownership dependency.** The PRs are logically independent but
cannot safely use the same mutable resource or write surface concurrently — a
deployment/live-test target, a high-conflict central schema or runtime surface, a
Runner family, or a scarce accelerator. Let implementation proceed in parallel
where safe and serialize only the conflicting operation, using the existing lease
and write-ownership rules rather than inventing a whole-PR dependency.

These are Commander reasoning categories, not required ceremony; a launch prompt
need not name them.

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

Each PR owner works in its own git worktree; do not implement unrelated PRs in
the shared checkout. Parallel reading is unrestricted, but concurrent writes to a
high-conflict shared surface need one explicit owner at a time. Likely surfaces
include the global frontend shell/styles, OpenAPI/schema ownership, central
server routes/contracts, shared task/runtime infrastructure, a single Runner
family, and common deployment/runtime code. When two PRs require substantial
writes to the same surface, the Commander serializes them or explicitly stacks
one on the other rather than letting both race and relying on a later conflict
resolution pass.

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

### Per-PR execution state

A single long-running task may use the repository's conventional `TODO.md` and
`IMPLEMENTATION_STATE.md`. Concurrent PRs must not share one mutable planning
file: each uses a PR-specific filename such as `TODO_<slug>.md` /
`IMPLEMENTATION_STATE_<slug>.md`, or an equally unambiguous PR-owned path. The
invariant is one mutable execution truth per PR; the filename is not fixed when a
PR already has a clear, unambiguous design/state document.

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

### Review model

Review is continuous Campaign work, not an end-stage gate. A PR is reviewed at
coherent checkpoints while implementation progresses, and the owner normally
keeps working while a reviewer checks a completed checkpoint. Never fan out three
review agents per PR, and never let two reviewers duplicate the same review. The
default is the PR owner self-reviews and runs focused tests; a reviewer does a
bounded checkpoint or integration pass; a specialist review runs only when risk
justifies it — scientific correctness, security/auth, scheduler/runtime behavior,
a substantial API/schema migration, or a substantial visual/interaction redesign;
then external final review. Keep implementation review, integration/cross-PR
review, and external final review distinct, and do not spend multiple slots
duplicating one review. The rule in `CLAUDE.md` against retriggering
automated review after every small push still applies.

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
NEEDS_REBASE
DEPLOY_REQUEST
LIVE_TEST
BLOCKED
READY_FOR_FINAL_REVIEW
```

Status reporting is not process ceremony; its purpose is to remove ambiguity
between concurrently active agents.

### Launch-prompt minimalism

Because this protocol lives in the repository, a launch prompt carries only the
task and genuinely environment-specific context. A Campaign launch needs little
more than "read `CLAUDE.md` and `LONG_TASK_HANDLING.md` first," any required
environment context, and "Command Campaign #<N>." A single-PR launch needs the
same prefix, environment context, and "Own PR #<N> and bring its exact head to
`READY_FOR_FINAL_REVIEW`." These are explanatory examples, not mandatory
templates. Permanent rules stay in repository guidance; ephemeral environment
details stay out of it.
