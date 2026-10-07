# Multi-agent Campaign Protocol — Reviewer Quality, Independent Challenge, and Slot Yielding

## Objective

Strengthen the existing REvoCompute Multi-agent Campaign Protocol without creating
another approval layer or a general orchestration framework.

This PR addresses two observed failure modes from the current campaign:

1. repeated review rounds can converge on the same implementation framing while
   still missing a higher-level system invariant;
2. the Campaign Commander can remain active while all useful work is already
   delegated, occupying an agent slot that should be available to implementation,
   review, or specialist work.

The protocol should preserve the current role split and retained maintainer merge
authority while making review quality explicit and making control-plane roles
quiescent when they have no immediate work.

The governing principles are:

> **Reviewer quality is a campaign resource, not a checkbox.**

> **READY evidence is non-transitive: every merge-grade reviewer forms an
> independent verdict against the exact head.**

> **The Commander is a control plane, not a permanently resident worker.**

> **When no immediate coordination decision exists, control-plane agents yield
> their active slots to executable work.**

Read before editing:

~~~text
CLAUDE.md
LONG_TASK_HANDLING.md
docs/agents/long-task-handling.md
~~~

The canonical detailed protocol remains
`docs/agents/long-task-handling.md`; preserve the existing root
`LONG_TASK_HANDLING.md` relationship and do not create a second source of truth.

---

## 1. Scope

This is a protocol/documentation PR.

Primary implementation target:

~~~text
docs/agents/long-task-handling.md
~~~

Update `CLAUDE.md` only if a short durable project invariant is needed so agents
discover the new behavior before entering the detailed protocol.

Do not modify runtime product behavior, scheduler code, Runner code, frontend
behavior, CI architecture, or GitHub automation.

Do not introduce a new workflow engine, review bot, status database, or agent
framework merely to encode these rules.

---

## 2. Preserve the existing role topology

Keep the current conceptual roles:

~~~text
PR owner / subagent
    implementation + self-review

Reviewer
    implementation correctness

Independent Campaign Advisor
    campaign direction, scope, architecture, coordination health

Campaign Commander
    campaign control plane and convergence

Maintainer
    retained final merge authority unless explicitly delegated
~~~

Do not turn the Advisor into a mandatory approval gate.

Do not make the Commander a deep implementation reviewer.

The protocol change should improve the quality and independence of review while
keeping technical detail close to the PR that owns it.

---

## 3. PR threads are the canonical technical review record

Formalize the following operating rule:

- detailed technical findings belong in the relevant PR review thread/comment;
- the PR thread is the canonical technical record for the finding;
- Commander control state stores only the minimum coordination summary;
- maintainer chat/reporting should not duplicate a full review report by default.

For an affected PR, the Commander normally retains only:

~~~text
merge status
broad blocker category
owner
Advisor assessment
exact head SHA
CI / acceptance state
dependency state when material
~~~

When a reviewer finds a blocker:

1. write the detailed finding and evidence to the PR thread;
2. tell the Commander only whether the PR may merge and the broad blocker class;
3. dispatch the owning subagent to read the current thread itself;
4. require the subagent to summarize the finding in its own words;
5. verify the finding against the exact current head;
6. implement the smallest correct fix;
7. add regression / adversarial evidence;
8. return to `READY_FOR_FINAL_REVIEW`.

Do not copy the full technical review into campaign control state.

---

## 4. Reviewer quality is explicit

Add a Reviewer Quality & Independence policy.

A reviewer is not considered merge-grade merely because it is independent of the
implementation worktree.

Review quality has at least these dimensions:

~~~text
model/reasoning capability
context independence
review mandate
review budget
access to primary evidence
ability to reject the existing framing
~~~

The reviewer assigned to a high-risk PR must not be intentionally weaker than the
implementation owner merely because review is perceived as cheaper work.

For the highest-risk system-boundary PRs, prefer the strongest available
reasoning configuration that the campaign can afford.

Do not encode vendor-specific model names in the durable protocol.

---

## 5. Risk-tiered review

Introduce a lightweight review-risk classification. It is a scheduling aid, not
new bureaucracy.

### R1 — low systemic risk

Examples:

- prose/docs;
- local copy changes;
- visual polish with preserved behavior;
- bounded fixtures;
- non-semantic metadata.

Normal independent review is sufficient.

### R2 — ordinary implementation risk

Examples:

- ordinary API behavior;
- Runner adapters;
- bounded business logic;
- protocol projections;
- non-privileged state changes.

Require independent correctness review and exact-head evidence.

### R3 — system-boundary risk

Examples:

- authentication/authorization;
- security/trust boundaries;
- filesystem publication;
- persistent state;
- database transactions;
- quota/accounting;
- concurrency;
- scheduler lifecycle;
- privilege/control-plane operations;
- irreversible migrations;
- cross-process crash recovery.

R3 requires a merge-grade, fresh-framing adversarial review with an appropriate
high reasoning budget.

Keep the classification lightweight. Do not require a new metadata file or
workflow label unless the current repository already has a natural mechanism and
there is clear value.

---

## 6. Fresh-context merge review

For R3 work, the final merge-grade reviewer should minimize framing inheritance
from the implementer and prior reviewers.

Prefer this evidence order:

~~~text
governing invariants
→ current main / base
→ exact PR diff and runtime/data-flow
→ tests and acceptance evidence
→ PR review threads
→ owner / Commander READY summaries
~~~

The reviewer should form an independent failure model before reading the author's
conclusion that the PR is ready.

The goal is not artificial isolation. The goal is to avoid treating a previous
reviewer's problem framing as proof that the framing was complete.

A reviewer must be allowed to conclude:

~~~text
the implementation satisfies the stated TODO,
but the TODO / acceptance model still misses a system invariant
~~~

without being considered out of scope.

---

## 7. Counterexample obligation for merge-grade review

For R3 PRs, merge review must attempt to falsify the design rather than merely
confirm expected behavior.

The reviewer should explicitly consider relevant classes such as:

~~~text
TOCTOU
crash between adjacent state transitions
duplicate/replayed events
out-of-order events
lost acknowledgements
concurrent actors
stale snapshots
authority duplication
self-authorizing metadata
unknown interpreted as zero
identity/event conflation
cleanup/reconciliation races
partial persistence
retry after partial side effects
~~~

Not every PR needs every category.

The reviewer should identify the categories materially relevant to the changed
boundary and attempt at least one plausible counterexample sequence before
declaring the PR clean.

---

## 8. Review state-machine edges, not only states

For lifecycle, scheduler, accounting, cleanup, migration, or operator-control
changes, require reviewers to examine transitions in the form:

~~~text
State A
    --[physical evidence / durable event]-->
State B
~~~

For each material edge, ask:

~~~text
who triggers it?
what physical evidence proves it?
where is that evidence made durable?
what happens if the process crashes immediately before it?
what happens if it crashes immediately after it?
can the event repeat?
can it arrive out of order?
how does reconciliation distinguish the resulting cases?
~~~

A state model with correct nouns but incorrect transition evidence is not
merge-ready.

---

## 9. READY is non-transitive

Formalize:

> **Owner READY, Advisor confidence, prior reviewer approval, and green CI are
> evidence; none automatically implies merge-ready.**

A merge-grade reviewer must form its own verdict against the exact current head.

Any material new commit invalidates exact-head review evidence that depended on
the previous head.

Do not repeatedly rerun expensive full review for trivial docs-only changes when
the reviewer can bound the invalidated evidence precisely, but never carry a
correctness/security verdict across a material code change by assumption.

---

## 10. Independent review diversity

For R3 PRs, avoid a review topology in which implementation, review, and final
challenge all inherit the same model, prompt framing, and author summary.

At least one merge-grade pass should differ materially in one or more of:

~~~text
reasoning configuration
review prompt / mandate
context exposure order
specialist expertise
fresh-context setup
~~~

This is not a requirement to multiply reviewer count.

Prefer one strong independent challenge over several correlated shallow reviews.

---

## 11. Advisor role: active independent challenge, not approval gate

Preserve the Independent Campaign Advisor's organizational independence and
non-blocking nature, but extend its expected campaign assistance.

While a subagent is resolving a material review finding, the Advisor should be
available to independently check:

- whether the subagent understood the finding rather than merely patched its
  symptom;
- whether the proposed fix remains inside the PR's intended scope;
- whether the fix changes an architectural owner or creates a second source of
  truth;
- whether regression evidence actually covers the governing invariant;
- whether repeated review churn indicates a missing campaign-level assumption;
- whether the PR is converging toward merge-readiness or expanding into a
  framework.

The Advisor may summarize this at the campaign level.

It should not duplicate line-by-line review findings, become a mandatory approval
step, or take implementation ownership.

For R3 PRs or repeated conceptual blockers, an out-of-cycle Advisor challenge is
expected rather than merely optional.

---

## 12. Control-plane quiescence

Add a Control-plane Quiescence / Slot Yielding rule.

The Commander is event-driven coordination, not a permanently resident active
worker.

When no immediate coordination decision is required, the Commander MUST:

1. checkpoint the minimum campaign control state;
2. verify active owners/dependencies are known;
3. yield/quiesce its active agent slot;
4. allow that slot to be used by eligible implementation, review, validation, or
   debugging work;
5. resume only when a meaningful coordination event occurs or the human requests
   it.

Meaningful Commander work includes:

- dispatching a newly eligible PR;
- resolving a dependency or ownership conflict;
- responding to a subagent escalation;
- reconciling after an upstream merge;
- reacting to a new exact head / CI / review outcome;
- arbitrating a shared deployment/live-test resource;
- preparing a genuine campaign decision boundary.

The following do **not** justify remaining active:

- waiting for subagents;
- periodic polling with no new event;
- repeatedly rewriting the same campaign summary;
- asking owners for status before they have produced a checkpoint;
- speculative replanning of an unchanged DAG;
- premature merge review before a coherent checkpoint exists;
- manufacturing auxiliary work solely to keep a slot occupied.

---

## 13. Advisor slot yielding

The Advisor is also subject to slot economics.

The Advisor may remain active while it has useful independent campaign-level work
to perform, especially during high-risk implementation or review convergence.

When it has no current advisory question, checkpoint, or relevant evidence to
inspect, it should also yield rather than occupy a slot merely to remain
nominally present.

"Advisor must remain active" means the role remains instantiated and available
throughout the campaign, **not** that it must continuously consume an execution
slot while idle.

Do not weaken the requirement that the Advisor participate actively when its
independent challenge is useful.

---

## 14. Concurrency budget should optimize useful work

Revise the current concurrency-budget wording so the default topology does not
implicitly reserve a permanent slot for the Commander.

The hard ceiling remains whatever the launch context or existing protocol
specifies.

When capacity is scarce, prefer useful active work in approximately this order:

~~~text
1. implementation / blocker resolution on an eligible PR
2. merge-grade or checkpoint review with fresh evidence
3. specialist validation / integration evidence
4. bounded coordination required to unlock or reconcile work
5. passive monitoring
6. idle
~~~

Do not interpret this as "always fill every slot."

Idle remains correct when no useful conflict-free work exists.

The important change is:

> **A dormant Commander is preferable to an idle Commander occupying a slot while
> executable campaign work is queued.**

The Commander may wake briefly and temporarily consume capacity when coordination
is actually required, then yield again.

---

## 15. Event-driven resumption

Document the events that should wake a quiescent Commander.

Examples:

~~~text
owner checkpoint / READY_FOR_FINAL_REVIEW
new reviewer blocker
new commit to an active PR
CI completion requiring classification
upstream merge
dependency becomes satisfiable
shared-resource request
owner escalation
Advisor material advisory
maintainer instruction
~~~

Where the harness cannot literally suspend/resume an agent, approximate this by
ending the Commander's active turn after checkpointing state and recovering from
GitHub + durable campaign state on the next invocation.

Do not implement busy polling merely to emulate event-driven behavior.

---

## 16. Minimal durable Commander state

Keep Commander state intentionally reconstructable.

The durable campaign control summary should remain close to:

~~~text
PR
merge / no-merge status
broad blocker category
owner
Advisor assessment
exact head
CI / acceptance state
dependencies / leases only when material
~~~

Detailed technical findings remain in PR threads.

This small state is what makes Commander quiescence safe: after resumption it can
refresh GitHub live state rather than relying on a large private conversational
working set.

---

## 17. Review stopping rule

Strengthen review without creating infinite review loops.

A high-risk PR may reasonably stop review and return to the maintainer when:

- governing invariants are explicit;
- all known blocking findings are closed;
- the exact current head has green required CI/acceptance evidence;
- a fresh merge-grade reviewer cannot construct a new material counterexample;
- relevant transition/crash/adversarial cases have evidence;
- remaining observations are explicitly non-blocking hardening or future work;
- no unresolved review thread materially changes merge safety.

The goal is not to prove absence of all bugs.

The goal is to have no known reason that the exact head is unsafe or
architecturally incorrect to merge.

---

## 18. Current-campaign immediate applicability

This PR changes durable repository protocol, but the same rules should be applied
immediately as a working policy to the currently active REvoCompute campaign.

Until this PR merges:

- treat this TODO and PR body as the active campaign instruction for these
  protocol points;
- do not claim main already contains the new protocol;
- do not block current implementation PRs merely waiting for this docs PR when
  the rule can be followed operationally now.

The Commander should immediately:

- stop occupying a slot when all useful work is delegated;
- use PR threads as the detailed technical record;
- keep compact blocker summaries only;
- require subagents to read and summarize their own review findings;
- keep the Advisor actively assisting with understanding/scope/architecture;
- allocate strong fresh-context merge review to R3 PRs.

---

## 19. Acceptance criteria

Before `READY_FOR_FINAL_REVIEW`:

1. `docs/agents/long-task-handling.md` explicitly defines reviewer quality and
   independence rather than assuming any independent reviewer is sufficient.
2. The protocol contains a lightweight R1/R2/R3 or equivalent risk-tier policy.
3. R3 review is explicitly fresh-framing and counterexample-driven.
4. State-machine transition evidence is included for lifecycle-style PRs.
5. READY is explicitly non-transitive.
6. Detailed technical findings are explicitly canonical in PR threads, with
   compact Commander state.
7. The owning subagent is explicitly responsible for reading, summarizing, and
   resolving its own review threads.
8. The Advisor remains independent and non-blocking while actively helping test
   understanding, scope, architecture boundaries, and merge convergence.
9. Commander quiescence / slot yielding is explicit.
10. Advisor idle-slot yielding is explicit without making the Advisor optional.
11. The concurrency-budget text no longer assumes a permanently resident
    Commander slot.
12. The protocol identifies meaningful wake/resume events and forbids busy
    waiting/polling as fake work.
13. The review stopping rule prevents infinite review churn.
14. No new approval chain, workflow engine, automation framework, or duplicate
    protocol source is introduced.
15. Existing retained maintainer merge authority remains unchanged.

---

## 20. Verification

This should be a small documentation-only implementation.

At minimum run:

~~~bash
mkdocs build --strict
git diff --check
~~~

Inspect the rendered / source documentation to ensure the new language integrates
with the existing sections rather than duplicating or contradicting:

~~~text
Campaign Commander
Independent Campaign Advisor
Concurrency budget
Dynamic orchestration
review / READY handoff rules
maintainer attention policy
~~~

Perform a subtraction pass. Prefer modifying the existing sections over adding a
large parallel governance appendix.

Do not merge automatically. Return the exact head to
`READY_FOR_FINAL_REVIEW` for maintainer decision.
