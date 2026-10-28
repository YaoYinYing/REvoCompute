# TODO — feat(accounting): canonical GPU-credit waterfall and attribution (#91)

> **Status:** Design / implementation not yet started. No merge authorization.
> **Baseline when drafted:** `17e80ed1dbd00f1389f3ec7047e5661b85ed52eb` (2026-10-28); revalidate against the exact head at implementation.
> **Scope:** Resolve issue #91 by providing a truthful bounded chronological GPU-credit waterfall and queryable ledger attribution without changing append-only resource facts.

## Objective
Resolve issue #91 by providing a truthful bounded chronological GPU-credit waterfall and queryable ledger attribution without changing append-only resource facts.

## Grounded starting facts
- Issue #91 remains open with a 2026-10-25 triage note documenting `list_compute_ledger` default 50 newest-first entries.
- PR #88 already supplied quota/reservation bars, per-resource attribution, and raw ledger; preserve it.
- The source of truth is integer GPU-seconds with signed adjustments and ledger provenance, not a client-side estimate.

## Implementation checklist
- [x] Inspect the live current `main` API, `list_compute_ledger`, ledger schema and existing user/admin credit screens before introducing a new endpoint or chart.
- [x] Define a bounded canonical history contract: UTC ordering, verified balance anchors (cursor pagination deferred), explicit completeness/truncation signals and immutable entry identifiers.
- [x] Return authoritative opening balance and signed GPU-second deltas for each requested window when known; when unknown, render a clear unavailability reason, never invent zero.
- [x] Support usage charge, reservation, release, monthly grant, correction, administrative adjustment and reversal according to canonical ledger semantics.
- [x] Present an accessible cumulative waterfall with opening, individual deltas and closing balance, including negative balances and partial history; chart must reconcile to server summary exactly.
- [x] Use integer units internally and format GPU-minutes/credits only for presentation; preserve time-zone display clarity and ordering.
- [x] Link entries to Task, StageRun, allocation/Slurm evidence when known; show unknown attribution explicitly and provide link to raw ledger.
- [x] Preserve RBAC (user sees own, admin authorized scope), append-only auditing, reconciliation policy and no unauthorized balance mutation.
- [x] Make large windows performant without unbounded downloads (bounded window + verified opening). Export/source receipts deferred with cursor pagination until a >200-row window is demonstrated.
- [ ] Resolve Issue #91 only after maintainer has reviewed merged production behavior and acceptance evidence.

## Test and acceptance checklist
- [x] Opening and closing balances match authoritative ledger over complete windows and paginated partial windows.
- [x] 50+ entries, reversed ordering, duplicated timestamps, negative balances, corrections and canceled allocations.
- [x] Overflow safeguards, idempotent replay, duplicate ledger event suppression, unknown attribution, and transient source outage.
- [x] Keyboard-only inspection, screen-reader descriptions, narrow/mobile layout and both themes.
- [x] Existing #88 bar/ledger tests remain passing; exact-head server/frontend contracts and CI.

## Explicit non-goals
- No reset-usage-to-zero action, altered settlement authority, or synthetic history.
- No scheduler fairness redesign; no fourth resource accounting database.

## Dependency and integration policy
Standalone implementation of https://github.com/YaoYinYing/REvoCompute/issues/91. This issue is not a generic resource governance rewrite.

## Review protocol and handoff
- [ ] Read `CLAUDE.md`, `LONG_TASK_HANDLING.md`, the Single-PR Campaign Protocol and this TODO before coding.
- [ ] Appoint one PR owner; preserve an independent Campaign Adviser and strict worktree/write ownership.
- [ ] Create or update `IMPLEMENTATION_STATE.md` alongside this TODO when substantive implementation begins; track progress, exact tests and outstanding blockers.
- [ ] Validate exact head, identify adjacent open/merged PRs and avoid rewriting canonical functionality or introducing parallel sources of truth.
- [ ] Post detailed technical findings and regressions to this PR's review threads; report owner/adviser status to Commander.
- [ ] Include fail-path tests, relevant docs, migration/read-only compatibility where needed, and no unverifiable performance or science claims.
- [ ] Keep PR draft until implementation is complete, exact-head CI/review evidence exists and maintainer accepts the scope.
