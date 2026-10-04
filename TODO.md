# Multi-agent Campaign Guidance

## Objective

REvoCompute's current agent workflow has evolved beyond one agent serially
implementing one PR at a time.

The proven working pattern is now:

```text
human + external reviewer
        ↓
PR goal + detailed TODO
        ↓
one owning implementation agent
        ↓
review / correction
        ↓
squash merge
```

Recent work also showed that several independent PRs can progress efficiently
in parallel when each has its own worktree and owner, while one coordinating
agent manages dependencies, rebases, deployment windows, and integration.

This PR must make that collaboration model a durable repository rule so future
launch prompts do **not** have to repeat the same operational instructions.

The intended result is:

> launch prompts identify the task and any genuinely machine-specific context;
> repository guidance defines how agents work.

Do not turn `CLAUDE.md` into a large operations manual. Keep invariant rules
there and put the detailed multi-agent procedure in `LONG_TASK_HANDLING.md`.

---

# 0. Scope and boundaries

This is an **agent-guidance/documentation-only** change.

Expected files:

```text
CLAUDE.md
AGENTS.md
LONG_TASK_HANDLING.md
TODO.md
```

No product code, frontend code, Runner code, server behavior, API contract,
deployment script, CI workflow, or scientific behavior should change.

Do not add tests that assert literal Markdown wording. Repository guidance is
not a runtime contract.

Do not add machine-specific deployment details such as temporary host names,
local paths, proxy settings, or credentials to permanent repository guidance.
Those belong in the launch prompt or host handoff because they are environmental
context, not project invariants.

---

# 1. Preserve the guidance hierarchy

Keep the existing ownership model:

```text
CLAUDE.md
    concise project-invariant agent rules

AGENTS.md
    exact mirror of CLAUDE.md

LONG_TASK_HANDLING.md
    detailed methodology for long-running work,
    including multi-agent campaigns
```

`CLAUDE.md` must remain concise.

Add only enough invariant guidance to make agents discover and obey the
campaign protocol. A suitable shape is:

- long-running work already requires reading `LONG_TASK_HANDLING.md`;
- when a task is identified as a Campaign, Campaign Commander role, or a
  coordinated multi-PR effort, read and follow the Multi-agent Campaign
  Protocol in `LONG_TASK_HANDLING.md` before assigning or editing work;
- parallel PR owners use isolated worktrees;
- shared deployment/review/concurrency resources are coordinated rather than
  independently consumed.

Do **not** copy the detailed campaign procedure into `CLAUDE.md`.

After editing, `AGENTS.md` must still mirror `CLAUDE.md` exactly.

---

# 2. Add a Multi-agent Campaign Protocol

Add a focused section to `LONG_TASK_HANDLING.md` for coordinated multi-PR
work.

A Campaign is a set of related PRs managed as one delivery effort. The Campaign
may be identified by a coordinating GitHub issue or by an explicit PR group in
the launch instruction.

The protocol must distinguish:

```text
Campaign coordination truth
    coordinating issue / explicitly named PR group

PR design truth
    PR body + that PR's TODO/design document

PR execution truth
    that PR's implementation-state document when needed

machine truth
    tests, CI, live acceptance, exact-head evidence
```

The Campaign Commander coordinates these sources; it does not replace them with
conversation memory.

---

# 3. Define the Campaign Commander role

The Commander is a workflow owner, not the default implementation owner.

Its responsibilities must include:

- read the Campaign and every participating PR/TODO before assigning work;
- construct and maintain the dependency / merge DAG;
- assign one owner per active PR;
- keep high-conflict write ownership explicit;
- track blockers and cross-PR contract assumptions;
- coordinate rebases only when they are actually necessary;
- arbitrate deployment/live-test windows;
- arrange review without uncontrolled reviewer fan-out;
- keep the campaign within the concurrency budget;
- report exact head SHAs and merge order when work is ready for external final
  review.

The Commander should normally avoid making feature changes itself. It may make
small coordination-only edits when appropriate, but should not become a hidden
fourth PR owner while also attempting to manage the campaign.

The Commander must not merge or squash-merge PRs unless the launch instruction
explicitly grants that authority. The normal endpoint is
`READY_FOR_FINAL_REVIEW`.

---

# 4. Define PR owner responsibilities

Every active implementation PR has exactly one owning agent.

The owner must:

- use a dedicated worktree for that PR branch;
- treat its PR body and TODO/design document as its scope and goal;
- maintain its execution state when the work is large enough to require it;
- implement, test, self-review, and checkpoint coherent progress;
- report cross-PR discoveries to the Commander instead of silently expanding
  scope;
- request deployment/live-test access from the Commander when needed;
- report the exact final head SHA and acceptance evidence.

A PR owner must not recursively create a new team of reviewers or implementation
agents by default. Additional agents are a campaign-level resource controlled by
the Commander.

---

# 5. Concurrency budget

REvoCompute currently operates with a practical global agent-slot limit where
excessive concurrency causes rate limiting and lower reliability.

Codify a conservative default:

```text
hard default campaign budget: 6 active agents
preferred steady state:       5 active agents
reserve:                      1 slot
```

A typical campaign should therefore be:

```text
1 Campaign Commander
up to 3 PR owners
1 rotating reviewer / integration agent
1 reserve slot
```

The reserve exists for replacement, debugging, or a temporary specialist.

A specialist does not automatically become a seventh participant. Prefer
temporarily reusing/releasing another slot.

If the launch context explicitly supplies a different current limit, that limit
overrides the default. The durable rule is to stay below the known ceiling and
keep spare capacity rather than saturating all available slots.

Prefer at most **three implementation PRs in flight** at once.

More PRs may exist in the Campaign, but they should remain queued until capacity
or dependency order allows them to start.

---

# 6. Worktree and write-ownership rules

Each PR owner must work in its own git worktree.

Do not implement unrelated PRs in the shared/root checkout.

Parallel reading is unrestricted, but concurrent writes to high-conflict shared
surfaces should have one explicit owner at a time.

Examples of likely high-conflict surfaces include:

- global frontend shell/styles;
- OpenAPI/schema ownership;
- central server routes/contracts;
- shared task/runtime infrastructure;
- the same Runner family;
- common deployment/runtime code.

If two PRs require substantial writes to the same ownership surface, the
Commander should:

1. serialize them, or
2. explicitly stack one on the other,

rather than allowing both agents to race and relying on a later conflict
resolution pass.

---

# 7. PR-specific plan/state files during parallel work

Parallel PRs must not fight over one shared mutable planning file.

Preserve the existing single-task protocol, but add the multi-PR rule:

- a single long-running task may use the repository's conventional
  `TODO.md` / `IMPLEMENTATION_STATE.md`;
- concurrent PRs should use PR-specific plan/state filenames or another
  unambiguous PR-owned location;
- do not make several worktrees independently rewrite the same root execution
  state.

Examples:

```text
TODO_<slug>.md
IMPLEMENTATION_STATE_<slug>.md
```

or an equivalent clearly PR-owned path.

Do not require one exact filename if an existing PR already has a clear,
unambiguous design/state document.

The important invariant is **one mutable execution truth per PR**, not the
spelling of the filename.

---

# 8. Rebase policy

Do not rebase every branch merely because `main` advanced.

That creates unnecessary churn in a parallel campaign.

Require or strongly prefer rebase when:

1. a declared upstream/dependency PR has merged;
2. `main` changed a contract or shared surface relevant to the PR;
3. a real merge conflict or CI contract drift appears; or
4. the PR is entering final review/merge and must be evaluated against current
   `main`.

After a meaningful rebase, rerun the affected focused gates and any acceptance
whose evidence could have been invalidated.

Independent PRs may continue implementation on their existing base while
unrelated changes land elsewhere.

---

# 9. Deployment and live-test lease

A real deployment target is a shared mutable resource.

Only one agent may own a deployment/live-test window at a time.

The protocol must require:

- PR owner requests a deploy/live-test window from the Commander;
- Commander grants a lease for a specific PR and exact head SHA;
- the deployed SHA is recorded before acceptance begins;
- no second owner redeploys until the first owner's acceptance has completed or
  been explicitly abandoned;
- after the window, the lease is released.

The repository guidance must stay host-neutral. Temporary host names, proxy
flags, local database-path drift, credentials, and handoff-file paths belong in
the launch prompt / environment handoff.

Do not require production deployment merely for completeness. Frontend fixture
work, documentation, or other changes should only receive a deployment window
when their acceptance contract actually needs the real production path.

---

# 10. Review model

Remove the old assumption that every PR should independently fan out three
review agents.

That model multiplies slot use as the number of PRs grows.

Use this default:

```text
PR owner
    → self-review + focused tests
    → one rotating campaign reviewer/integration pass
    → optional specialist review only when risk justifies it
    → external final review
```

A specialist review is appropriate for genuinely high-risk areas such as:

- scientific correctness;
- security/auth;
- scheduler/runtime behavior;
- a substantial API/schema migration;
- a substantial visual/interaction redesign.

Reuse idle PR owners for peer review when useful.

Batch review findings. Preserve the existing rule against repeatedly triggering
automated review after every small push.

The Commander should distinguish:

```text
implementation review
integration / cross-PR review
external final review
```

and should not spend multiple slots duplicating the same review.

---

# 11. Direct agent coordination

Where the agent environment supports peer communication, agents should
communicate directly rather than requiring the human operator to relay routine
messages.

At minimum, agents should be able to communicate:

- ownership claims;
- dependency completion;
- rebase requests;
- deployment-window requests;
- shared-contract changes;
- blockers;
- readiness for review.

A compact status vocabulary may be documented, for example:

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

Do not turn status reporting into process ceremony. The purpose is to reduce
ambiguity between concurrently active agents.

---

# 12. Scope discoveries across PRs

Parallel work makes incidental discoveries more common.

If an owner finds a defect outside its PR scope, it must not silently absorb the
change.

Report it to the Commander.

The Commander decides whether the finding:

- blocks the current PR;
- belongs to another active PR;
- requires a new follow-up PR;
- or is explicitly deferred.

Keep the existing REvoCompute preference for narrow ownership and avoid turning a
campaign into an unbounded repository cleanup.

---

# 13. Campaign completion and merge readiness

A PR may be reported as `READY_FOR_FINAL_REVIEW` only when:

- required TODO/design items are complete;
- its worktree is clean;
- focused tests pass;
- required repository gates pass;
- required live acceptance is recorded;
- review findings are resolved;
- no known dependency/rebase remains pending;
- exact head SHA is reported.

Before declaring the Campaign ready, the Commander must provide an integration
summary containing:

- each PR and exact head SHA;
- current dependency / merge order;
- tests and live-acceptance evidence;
- known deferred issues;
- which PRs must rebase after an earlier PR merges;
- any unresolved cross-PR ownership or contract risk.

The normal workflow remains:

```text
Campaign team brings PRs to READY_FOR_FINAL_REVIEW
        ↓
external reviewer performs final code review
        ↓
fix findings if needed
        ↓
squash merge according to the dependency DAG
```

Do not make automatic merging part of the generic Campaign protocol.

---

# 14. Launch-prompt minimalism

Document the explicit goal of this change:

**do not duplicate repository workflow rules in every `/goal` prompt.**

A normal future Campaign launch should need little more than:

```text
/goal
Read CLAUDE.md and LONG_TASK_HANDLING.md first.

<environment-specific context only when genuinely required>

Task:
Command Campaign #<N>.
```

A normal single-PR launch should similarly contain only:

```text
/goal
Read CLAUDE.md and LONG_TASK_HANDLING.md first.

<environment-specific context only when genuinely required>

Task:
Own PR #<N> and bring its exact head to READY_FOR_FINAL_REVIEW.
```

These examples are explanatory, not mandatory literal templates.

Permanent repository rules must stay in repository guidance.

Ephemeral environment details must stay out of repository guidance.

---

# 15. Subtraction pass

After adding the Campaign protocol, inspect existing guidance for rules that are
now duplicated or contradictory.

In particular:

- do not repeat the same review discipline in several places;
- do not repeat worktree/rebase/deployment rules in both `CLAUDE.md` and
  `LONG_TASK_HANDLING.md`;
- keep the concise invariant in `CLAUDE.md`, detailed procedure in
  `LONG_TASK_HANDLING.md`;
- preserve useful existing long-refactor methodology;
- do not weaken existing rules about credentials, exact-head verification,
  scientific live testing, or architecture ownership.

This PR is meant to reduce repeated prompting, not create repeated
documentation.

---

# 16. Acceptance

Before reporting the PR ready:

1. Read the final `CLAUDE.md`, `AGENTS.md`, and
   `LONG_TASK_HANDLING.md` together as one agent would.
2. Confirm the responsibility boundaries are obvious:
   - launcher supplies task + environment-specific context;
   - repository guidance supplies workflow;
   - Campaign supplies cross-PR coordination;
   - PR supplies implementation scope;
   - tests/live acceptance supply machine truth.
3. Confirm `CLAUDE.md` remains concise rather than becoming a duplicate
   operations manual.
4. Confirm `AGENTS.md` mirrors `CLAUDE.md` exactly.
5. Confirm no host-specific names, paths, proxy settings, or test credentials
   were added to durable guidance.
6. Confirm the protocol does not encourage recursive fan-out that can exceed the
   six-agent default budget.
7. Confirm one deployment lease cannot be held by multiple PR owners.
8. Confirm parallel PRs are not instructed to share one mutable
   `IMPLEMENTATION_STATE.md`.
9. Confirm the Commander is a coordinator by default, not another hidden
   implementation owner.
10. Confirm the normal endpoint is `READY_FOR_FINAL_REVIEW`, not automatic
    merge.
11. Run:

```bash
diff -u CLAUDE.md AGENTS.md
git diff --check
```

12. If any site documentation is changed in addition to the expected root
    guidance files, also run:

```bash
mkdocs build --strict
```

No static-text test should be added merely to pin this wording.

---

# 17. Definition of done

This PR is complete when a future launch prompt can be short because the
repository itself answers:

- what a Campaign is;
- what the Commander owns;
- what a PR owner owns;
- how many agents should be active;
- how worktrees are isolated;
- when rebases are required;
- how shared deployment is leased;
- how review capacity is reused;
- how cross-PR findings are routed;
- and what evidence is required before final review.

The guidance should make the new workflow obvious without requiring the human
operator to act as a message relay or restate the operating manual in every
prompt.
