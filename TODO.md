# Dynamic Campaign Orchestration

## Objective

Extend the Multi-agent Campaign Protocol introduced by PR #41 with an explicit
dynamic orchestration rule.

PR #41 already gives the Commander the right building blocks:

- maintain the dependency / merge DAG;
- keep no more than the useful number of implementation PRs in flight;
- queue work until capacity or dependency order allows it to start;
- avoid unnecessary rebases;
- serialize shared deployment/live-test access;
- hand completed work to the external reviewer at `READY_FOR_FINAL_REVIEW`.

What is still implicit is how the Commander should behave when a Campaign is
described in **waves** but a later-wave PR is already safe to implement while an
earlier PR is blocked on review, a small fix, CI, or a deployment lease.

Make that policy explicit:

> a Wave is a planning priority and integration checkpoint, not a hard
> implementation barrier unless the Campaign explicitly says otherwise.

The Commander should keep useful independent work moving while still preserving
dependency correctness, merge authority, evidence validity, and shared-resource
ownership.

This is a documentation/guidance-only follow-up to PR #41. Do not change product
runtime behavior.

---

## 0. Scope and boundaries

Expected implementation scope:

```text
LONG_TASK_HANDLING.md
TODO.md
```

Only touch `CLAUDE.md` / `AGENTS.md` if a genuinely new project-wide invariant
cannot be discovered through the existing instruction to follow the Multi-agent
Campaign Protocol. Prefer not to touch them: PR #41 already routes Campaign work
into `LONG_TASK_HANDLING.md`.

Do not modify:

- application/runtime code;
- Runner code;
- frontend code;
- CI behavior;
- deployment tooling;
- merge permissions;
- the six-slot default campaign budget;
- the one-owner-per-PR rule;
- the exclusive deployment/live-test lease;
- the existing `READY_FOR_FINAL_REVIEW` handoff.

Do not turn this into a generic workflow engine or scheduler implementation.

---

## 1. Define Waves correctly

Document that a Campaign may group PRs into Waves for human planning,
prioritization, and integration checkpoints.

By default:

```text
Wave != execution barrier
Wave != merge permission
Wave != implicit hard dependency
```

A later-wave PR may begin implementation before every earlier-wave PR has merged
when its work is independent enough to do so safely.

A Wave remains useful for:

- expressing intended priority;
- defining major integration checkpoints;
- deciding when broad downstream work should normally begin;
- giving the human/external reviewer a coherent group to review;
- preventing low-priority work from consuming capacity while higher-priority
  work is still actionable.

If a Campaign launch instruction explicitly declares a Wave to be a hard
barrier, obey that instruction.

---

## 2. Distinguish dependency classes

Add a compact dependency vocabulary so the Commander does not treat every
relationship as an all-or-nothing blocker.

At minimum distinguish:

### Hard implementation dependency

The downstream PR cannot be implemented correctly until the upstream contract,
API, schema, artifact, or behavior exists.

Example:

```text
PR B consumes a new production interface created by PR A
and cannot reasonably implement against the old interface.
```

Rule:

- keep B queued until A is merged or an explicitly stacked branch is intended;
- do not duplicate or guess the missing upstream contract.

### Final-integration dependency

The downstream PR can do substantial useful implementation against the current
tree, but its final contract/evidence may be invalidated by an upstream PR.

Example:

```text
PR B can build a replay path now,
but must reconcile with PR A's final receipt format before final acceptance.
```

Rule:

- B may start when capacity allows;
- record A as a final-integration dependency;
- after A merges, rebase/reconcile B when required;
- rerun affected acceptance;
- B must not reach `READY_FOR_FINAL_REVIEW` while that unresolved dependency
  can still invalidate its result.

### Shared-resource / ownership dependency

The PRs are logically independent but cannot safely use the same mutable
resource or write surface concurrently.

Examples:

- production deployment/live-test target;
- one high-conflict central schema or runtime surface;
- the same Runner family;
- a scarce GPU acceptance target.

Rule:

- implementation may proceed in parallel where safe;
- serialize only the conflicting operation/surface;
- use the existing Commander lease/ownership rules rather than turning the
  relationship into an artificial whole-PR dependency.

Do not require these exact names in every launch prompt. They are Commander
reasoning categories, not ceremony.

---

## 3. Add eligibility-based scheduling

Document a small scheduling decision for queued PRs.

When a slot becomes available, the Commander should consider a queued PR
eligible to start when:

1. it has no unresolved hard implementation dependency;
2. its high-conflict write ownership can be assigned safely;
3. starting it does not violate a current deployment/live-test lease;
4. enough information already exists to implement without inventing an upstream
   contract;
5. it is useful enough relative to higher-priority actionable work;
6. the campaign remains within the concurrency budget and reserve policy.

A later-wave PR satisfying these conditions may start while an earlier-wave PR
is:

- waiting for external review;
- fixing a narrow review finding;
- waiting on CI;
- waiting for a deployment window;
- otherwise temporarily blocked without blocking the later PR's implementation.

Do not keep agents idle merely to preserve visual Wave ordering.

Conversely, do not start later work merely because a slot exists if doing so
would create speculative compatibility code, duplicated infrastructure, or
avoidable merge conflict.

---

## 4. Separate implementation readiness from final readiness

Make the distinction explicit:

```text
eligible to implement
        !=
eligible for final review
```

A PR with a final-integration dependency may make commits, test locally, and
complete most of its TODO before the upstream PR merges.

Before reporting it `READY_FOR_FINAL_REVIEW`, however, the owner and Commander
must confirm:

- required upstream PRs are merged;
- the branch is rebased/reconciled when the dependency affects it;
- upstream contract changes were actually consumed;
- affected tests and live/scientific acceptance were rerun;
- evidence still describes the exact final head.

This prevents early parallelism from turning into stale acceptance evidence.

---

## 5. Preserve human/external merge authority

Dynamic orchestration must not expand Commander authority.

Retain the PR #41 rule:

> the Commander must not merge or squash-merge PRs unless the launch
> instruction explicitly grants that authority.

Normal flow remains:

```text
implementation may overlap dynamically
        ↓
PR reaches READY_FOR_FINAL_REVIEW
        ↓
external reviewer / human reviews
        ↓
human-authorized squash merge
        ↓
Commander updates DAG and re-evaluates queued work
```

Merging one PR may make another queued PR eligible, or may trigger a required
rebase/final-integration pass for an already active PR.

---

## 6. Make orchestration event-driven

Document that the Commander should re-evaluate the Campaign DAG when meaningful
events occur, rather than only at Wave boundaries.

Useful triggers include:

- a PR becomes blocked;
- a PR reaches `READY_FOR_FINAL_REVIEW`;
- a review finding narrows or expands an upstream contract;
- a PR is squash-merged;
- CI or live acceptance completes;
- a deployment/live-test lease is released;
- a shared write surface becomes free;
- an agent slot becomes available;
- a cross-PR discovery creates or removes a dependency.

The re-evaluation should answer:

```text
What remains blocked?
What became eligible?
What must rebase/reconcile?
What resource can be leased next?
What should remain queued?
```

Do not require constant polling or process ceremony. Re-evaluate on meaningful
state changes.

---

## 7. Keep capacity useful, not saturated

Preserve PR #41's conservative campaign budget:

```text
hard default campaign budget: 6 active agents
preferred steady state:       5 active agents
reserve:                      1 slot
preferred implementation PRs: at most 3 in flight
```

Dynamic orchestration should improve utilization without treating maximum
concurrency as a target.

The Commander may leave a slot unused when:

- the only available work has a hard dependency;
- another PR is about to release a high-conflict surface;
- starting work would create likely churn;
- reserve capacity is more valuable for review/debugging.

The goal is **useful concurrency**, not full occupancy.

---

## 8. Add a concise worked example

Add one generic example to `LONG_TASK_HANDLING.md`, without embedding current
PR numbers as permanent policy.

For example:

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

Commander may:
  keep A fixing,
  start C with A recorded as final-integration dependency,
  start D independently,
  keep E queued.

After A merges:
  C rebases/reconciles and reruns affected acceptance.
After C merges:
  E becomes eligible.
```

Use the example to make the distinction between planning Waves and the actual
dependency DAG obvious.

---

## 9. Avoid contradictory guidance

Perform a subtraction/consistency pass over the existing Campaign protocol.

In particular, ensure the new text agrees with the existing rules that:

- more PRs may exist than are actively implemented;
- independent PRs need not rebase merely because `main` changed;
- shared write surfaces may require serialization;
- deployment/live-test access is exclusive;
- one owner owns each active implementation PR;
- the Commander coordinates rather than becoming an extra implementation owner;
- external final review remains the normal handoff;
- merge order follows the actual dependency DAG.

Do not duplicate entire existing sections just to add the scheduling rule.
Prefer a focused “Dynamic orchestration” subsection and small cross-references.

---

## 10. Acceptance

Before reporting this PR ready:

1. Read the full Multi-agent Campaign Protocol as one document.
2. Confirm it no longer implies that all PRs in Wave N must merge before any
   useful work in Wave N+1 may begin.
3. Confirm hard dependencies still block implementation.
4. Confirm final-integration dependencies allow useful early work but block
   `READY_FOR_FINAL_REVIEW` until reconciled.
5. Confirm shared-resource conflicts serialize only the conflicting operation.
6. Confirm later-wave work cannot bypass campaign priority simply to fill slots.
7. Confirm the six-slot budget, reserve slot, and at-most-three implementation
   PR guidance remain unchanged.
8. Confirm Commander merge/squash authority has **not** expanded.
9. Confirm the protocol remains host-neutral and does not mention current
   temporary deployment details.
10. Run:

```bash
git diff --check
```

If `CLAUDE.md` / `AGENTS.md` are touched despite the preference above, also
require:

```bash
diff -u CLAUDE.md AGENTS.md
```

No static test should pin literal documentation wording.

---

## Definition of done

This PR is complete when a Commander can look at a Campaign containing Waves,
dependencies, limited agent slots, and shared live-test resources and correctly
decide that:

- an independent or final-integration-dependent later PR may start early;
- a hard-dependent PR remains queued;
- a shared-resource conflict delays only the conflicting operation;
- final acceptance is refreshed after relevant upstream merges;
- Wave priority still matters;
- and merge authority remains with the human/external reviewer unless explicitly
  delegated.

The intended result is a Campaign protocol that behaves like a dependency-aware
dynamic work queue rather than a rigid batch pipeline.
