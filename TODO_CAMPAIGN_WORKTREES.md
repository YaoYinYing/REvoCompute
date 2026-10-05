# Campaign Worktree Isolation and Commander Control Plane

## Objective

Make worktree isolation a **hard Campaign invariant**.

The repository's primary checkout is the **Commander's control plane**, not an implementation workspace. Every implementation/review subagent must operate inside a dedicated PR-scoped Git worktree. The Commander owns synchronization of the primary checkout, broadcasts merge/main-advance events, and retires worktrees when their PR lifecycle ends.

This corrects a coordination failure mode where agents switch branches or modify files in the repository root, where stale PR-local TODO files on main are mistaken for durable repository policy, and where merged PR worktrees/branches accumulate without a single lifecycle owner.

---

## 1. Terminology

Define these concepts explicitly.

### Commander control root

The primary repository checkout used by the Commander to:

- fetch/prune remote state;
- keep `main` synchronized with `origin/main`;
- inspect PR/branch/worktree state;
- create and retire PR-scoped worktrees;
- observe merge events;
- broadcast updated main/dependency state.

It is **not** an implementation workspace.

### PR worktree

A linked Git worktree bound to one open PR's canonical branch.

It is the default workspace for:

- the PR implementation owner;
- bounded local testing;
- PR-specific `TODO.md` guidance;
- PR-local commits.

### Review worktree

Optional, short-lived, independent worktree created only when a reviewer needs an isolated writable checkout to reproduce or experiment with a PR.

Ordinary read-only review does not require a second worktree if tooling can inspect the PR directly.

---

## 2. Hard invariant: no subagent works in the control root

The primary repository checkout is reserved for Commander control-plane operations.

No implementation owner, reviewer, specialist, recovery agent, or delegated subagent may:

- edit files in the control root;
- switch the control root away from `main`;
- commit from the control root;
- run destructive branch/rebase operations there;
- treat it as a convenient default working directory.

The control root must normally satisfy:

~~~text
branch = main
working tree = clean
main = synchronized with origin/main
~~~

If a subagent discovers that its current Git top-level is the control root, it must stop before modifying anything and report the violation.

---

## 3. Hard invariant: every subagent receives an explicit worktree

A Commander dispatch must include, at minimum:

~~~text
PR: #<number>
canonical branch: <branch>
worktree: <absolute path>
observed main: <sha>
role: owner | reviewer | specialist
~~~

The subagent must verify before work:

~~~bash
git rev-parse --show-toplevel
git branch --show-current
git status --short
~~~

The resolved top-level and branch must match the assignment.

Do not tell an agent merely:

> Work on PR #45.

Tell it where that PR's worktree is.

---

## 4. One PR, one canonical implementation workspace

Maintain the invariant:

~~~text
one open PR
-> one canonical remote branch
-> one canonical implementation worktree
-> one implementation owner
~~~

Do not create routine `-r2`, `-r3`, `-rebased`, `-recovery` remote branches.

Recovery/rebase experiments should prefer:

- local temporary refs;
- temporary review/recovery worktrees;
- or a short-lived scratch branch only when Git mechanics genuinely require it.

Any scratch branch/worktree must have an explicit owner and retirement condition.

It must never become a second long-lived source of truth for the same PR.

---

## 5. TODO.md semantics

Clarify the root `TODO.md` contract:

> `TODO.md` is ephemeral PR/worktree-local execution guidance, not durable repository-wide policy.

Consequences:

- each PR branch may legitimately carry a different `TODO.md`;
- the copy visible on `main` after a merge is historical residue from the most recently merged work and must not be treated as current repository-wide design truth;
- reviewers/Advisors must not reject a PR merely because its `TODO.md` differs from the current copy on `main`;
- durable project/Campaign policy belongs in stable documentation such as `CLAUDE.md`, `LONG_TASK_HANDLING.md`, developer/operator docs, or another explicitly durable location.

Do not require proliferating `TODO_PR<number>.md` files solely to avoid normal PR-local `TODO.md` differences.

If a TODO is intended to remain durable after the PR, migrate the durable content into the appropriate policy/documentation file before merge.

---

## 6. Commander owns the control root

The Commander is the only Campaign role that performs routine control-root Git operations.

Typical control-plane operations include:

~~~bash
git fetch --prune origin
git switch main
git merge --ff-only origin/main
git worktree list
git worktree prune
~~~

The exact commands may vary, but the invariants do not:

- never merge implementation work manually into the control root;
- never resolve PR implementation conflicts in the control root;
- never leave the control root dirty;
- never use the control root as an owner's emergency workspace.

If the control root is dirty or not on `main`, treat that as a Campaign infrastructure fault and resolve it before further dispatch.

---

## 7. Merge is a lifecycle event

A merged PR is not merely a GitHub state change. It terminates that PR worktree's normal lifecycle.

When the Commander observes a merge:

### A. Synchronize control root

Update remote state and fast-forward the clean control root to the new `origin/main`.

Record:

~~~text
MERGE EVENT
PR: #<number>
old main: <sha>
new main: <sha>
~~~

### B. Broadcast main advancement

Notify active/queued owners whose dependencies or integration bases may be affected.

Example:

~~~text
MAIN_ADVANCED

merged: #42
new_main: a5f2f398...

#44: dependency released; reconcile now
#45: main advanced; reconcile before final merge if necessary
#46: remains blocked on #44
#47: no immediate action
~~~

Do **not** mechanically require every worktree to rebase after every merge.

Reconciliation is required only when the PR's dependency, write surface, mergeability, or final-integration contract requires it.

### C. Retire merged PR execution state

Before removal, verify:

- no uncommitted changes;
- no unique commits absent from the merged PR;
- no artifact/evidence that exists only in the worktree and is still required.

Then retire:

- the PR implementation worktree;
- merged canonical remote branch when repository policy permits;
- obsolete scratch/recovery worktrees/branches.

Run worktree pruning as appropriate.

---

## 8. Worktree lifecycle states

The Commander should track at least:

~~~text
PR | canonical branch | worktree | owner | state | observed-main
~~~

Useful states:

- QUEUED
- ACTIVE
- BLOCKED
- REVIEW
- READY_FOR_FINAL_REVIEW
- MERGED / RETIRE
- CLOSED / RETIRE

A queued open PR may retain its canonical worktree if preserving local state is useful, but it remains uniquely bound to that PR.

A merged/closed PR must not keep an active implementation worktree indefinitely.

---

## 9. Reconciliation after main advances

Do not equate:

> main changed

with:

> every PR must rebase immediately.

For each open PR, classify the merge event:

### No action

Use when the merged change is outside the PR's dependency/write surface and GitHub remains cleanly mergeable.

### Final-integration reconciliation

Use when the PR intentionally depended on a newly merged contract/evidence/API.

### Merge-conflict reconciliation

Use when Git reports real conflicts or overlapping durable behavior requires resolution.

### Rebase optional hygiene

Use when rebasing would only produce a newer SHA without changing the implementation or acceptance evidence.

Prefer the lowest-cost category that preserves correctness.

---

## 10. Review isolation

A reviewer must not mutate the Commander's control root.

For read-only review, prefer GitHub/API/diff inspection.

If writable local reproduction is required, create a dedicated review worktree, for example:

~~~text
worktrees/review-pr45-<short-id>
~~~

The review worktree:

- is not the PR's canonical implementation workspace;
- must not become a new remote source of truth;
- should be removed after the review/reproduction task;
- may produce findings, not uncoordinated implementation commits.

If the reviewer is explicitly delegated to fix the PR, ownership must be transferred or the Commander must coordinate the commit path into the canonical PR worktree/branch.

---

## 11. Recovery and force-push discipline

Rebase/recovery should happen inside the PR worktree or a bounded recovery worktree, never in the control root.

When history rewriting is necessary:

- preserve the PR's canonical branch identity;
- require explicit authorization when force-push policy demands it;
- avoid creating permanent alternate remote heads;
- after successful handoff, retire the recovery worktree/branch.

The Commander should report the exact resulting head SHA.

---

## 12. Advisor/audit checks

The Independent Campaign Advisor may audit the Commander control plane.

Useful checks include:

- Is the control root clean and on `main`?
- Is it synchronized with `origin/main` after the latest merge?
- Did the Commander broadcast the main advancement?
- Does every active PR have exactly one canonical implementation worktree?
- Is any subagent operating in the control root?
- Does any merged/closed PR still own an active worktree?
- Are scratch/recovery worktrees or branches accumulating?
- Are agents being asked to rebase mechanically when no reconciliation is required?

These are Campaign-health checks, not ordinary PR approval gates.

This PR may reference the Advisor role, but it must not depend on #52 being merged first.

---

## 13. Failure handling

Treat these as Campaign infrastructure violations:

- control root dirty from subagent work;
- control root switched away from `main`;
- multiple implementation worktrees claiming canonical ownership of one PR;
- one worktree used to implement multiple open PRs;
- subagent dispatched without an explicit worktree;
- merged PR worktree left active without reason;
- untracked scratch worktree/branch with unique work and no owner.

The Commander should resolve the infrastructure state before creating more parallel work.

Do not silently discard unique work.

---

## 14. Scope boundaries

This PR is governance/documentation only.

Do not:

- implement a worktree daemon;
- add a new orchestration service;
- add CI solely for local worktree state;
- introduce repository-specific absolute paths;
- prescribe one workstation directory layout;
- redesign GitHub branch protection;
- make every reviewer create a worktree;
- make every main advancement trigger a rebase;
- reopen existing implementation PRs.

Integrate this model into the existing Campaign guidance with the smallest coherent documentation change.

If #52 changes the same durable Campaign document first, reconcile rather than overwrite its Advisor rules.

---

## Acceptance

The final guidance must make these points unambiguous:

1. repository root/primary checkout is the Commander's control plane;
2. no subagent performs implementation work there;
3. every implementation subagent receives an explicit PR-scoped worktree path;
4. one open PR has one canonical branch/worktree/owner;
5. `TODO.md` is PR-local ephemeral guidance, not durable main-branch policy;
6. Commander keeps the control root clean, on main, and synchronized;
7. merge events trigger main synchronization, dependency broadcast, and worktree retirement;
8. not every main advancement requires every PR to rebase;
9. merged/closed PR worktrees and scratch state are cleaned up deliberately;
10. reviewers needing writable isolation use temporary review worktrees, not the control root;
11. recovery/force-push operations stay outside the control root;
12. the Independent Advisor may audit these invariants without entering the Commander's execution chain;
13. the new rules reduce coordination ambiguity rather than creating another approval layer.

Run:

~~~bash
mkdocs build --strict
git diff --check
~~~

and the repository's expected documentation-only CI path.

Bring the exact head to READY_FOR_FINAL_REVIEW.
