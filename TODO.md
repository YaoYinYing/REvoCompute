# TODO — Resource Accounting UX: GPU Credit Waterfall, Compact Quota Bars, and Explainable Reconciliation

> Campaign: REvoCompute Interaction Model Correction, PR D. Design-only Draft PR; no runtime changes yet.
> PR-local TODO.md: remove from tracked branch diff before READY_FOR_FINAL_REVIEW. Durable product contract stays in existing docs/user-guide + server-api + UI code.

## 1. Core principle

The resource pages must tell the story of **what was allotted, what was consumed, what is reserved, and why the balance is what it is**, rather than show raw backend bookkeeping vocabulary as the primary visual object.

Three user observations (2026-10-14):
1. GPU credits "Recent activity" is a tall ledger; use an actual waterfall (green increases, red decreases, hover/focus details).
2. Quota currently mixes envelope table, storage stats, tiny chart and an oversized ledger. Replace with GPU / CPU / Storage resource overview resembling user reference figure 7: three labelled horizontal allocations, segmented Used / Reserved / Remaining, click a resource to inspect attribution by Task/Slurm job.
3. "GPU reconciliation" is unexplained. It settles lost finish-callback Slurm allocations with trustworthy evidence. Rename and explain; this is an admin operations tool, not a daily account activity label.

Critical: Do NOT create a second accounting truth. Backend ResourceEntitlement and append-only ledger are authoritative; positive/negative adjustments, rollback/reversal, reset, monthly allowances and usage history remain immutable facts. UI may aggregate for viewing, never rewrite, synthesize or suppress evidence.

## 2. First recon tasks

- [ ] Read CLAUDE.md, LONG_TASK_HANDLING.md, docs/reference/server-api.md (resource entitlement, append-only ledger, GPU credits, missing finish callbacks), docs/developer-guide/frontend-design-language.md, art direction.
- [ ] Inspect main/CI/PR #81 and branches; work only in PR-specific worktree.
- [ ] Trace frontend/src/features/profile/sections.ts (gpuCreditsPanel, renderGpuCredit), frontend/src/features/quota/QuotaView.ts + quota CSS, frontend/src/features/admin/credits/CreditAdmin.ts (renderReconciliation), frontend/src/features/admin/api.ts, resource ledger API and access guards.
- [ ] Inspect actual summary history API: chronological order? full month vs bounded recent N? timestamps? signed gpu_seconds? effect of monthly grant/allowance-adjustment/admin-reset? Missing/unknown allocation holds?
- [ ] Identify stable canonical fields for storage owned/ceiling, CPU "Recorded only" and GPU allowance/used/reserved. No inferred denominators.
- [ ] Find test fixtures for un-attributed rows, migration, very large adjustments, negative balance, over-quota, zero-allowance, unknown scheduler evidence.

## 3. GPU Credits waterfall — design contract

Waterfall is a cumulative balance chart, **not** a chart of individual magnitude all starting from zero. A step's base and top follow opening balance + the actual signed event, with connectors between steps. Positive adjustments/credit grants are green (increase), GPU usage and debit adjustments red (decrease), zero delta/metadata-only events muted. Use accessible legend labels; semantic colors from tokens rather than hardcoded #00ff00 / #ff0000. Neutral closing balance column may use accent/ink.

ASCII geometry (illustrative only, not real account data):

    GPU credits                                             October 2026
    1 credit = 1 GPU-minute     [Monthly] [View activity ledger]
    Monthly 1,000 | Net adjustments +10,011.55 | Used 11.55 | Remaining 11,000
    ─────────────────────────────────────────────────────────────────────────────
    Balance
    12k  ┤                    ┌─────────────┐
    11k  ┤                    │ GREEN +10k  │──┐      ┌──── Ending 11k
    10k  ┤                    │             │  │ RED  │
     1k  ┤  ┌──── 1k ─────┐───┘             └──┴──────┘
       0 ┼──────────────────────────────────────────────────────────────────
            Start       Adjustment      GPU usage       Closing balance
                       (ordered ledger events, not arbitrary categories)

    [Hover/keyboard-focus one step]
    ┌────────────────────────────────────────────────────────┐
    │  2026-10-12 19:58 UTC                                  │
    │  Admin adjustment         +10,000 GPU-min              │
    │  Reason: test                                           │
    │  Balance after event: ... GPU-min                      │
    │  Related Task: — | Slurm job: —                        │
    └────────────────────────────────────────────────────────┘

Implementation facts:
- [ ] Define display baseline and event ordering from complete authoritative data; use ascending event timestamp AND stable ledger sequence/ID to resolve ties. Reverse-chronological display is permissible only if the balance traversal remains correct.
- [ ] Existing history may be a bounded slice and may omit the month grant; do **not** compute a false start at zero and declare it the monthly balance. If history is partial, request a server-owned opening balance or render a labeled "Prior activity" carry-in backed by immutable aggregates. Confirm sum of displayed deltas + opening balance = canonical closing balance to exact base units.
- [ ] Keep integer GPU-seconds internally; convert to GPU-min only at display boundary. Avoid double float accumulation; format compact numbers with full precision in tooltip/details. Display UTC accounting month boundary, local timestamps with explicit timezone where presented.
- [ ] Same-minute multiple entries must remain individually discoverable in detailed ledger even if chart aggregates by day/category. Aggregation must never reorder a balance.
- [ ] Grants/adjustments and actual consumption are not interchangeable. Credits available do not equal physical GPU utilization or full resource reservation.
- [ ] Administratively reset credit balance is an append-only adjustment, NOT deleting usage. Chart shows the delta and makes the history auditable.
- [ ] Scale huge debit/credit events (e.g. +100,000 vs -209,988.45) without making routine usage invisible: use compact event grouping by time, optional zoom/domain selection, "View all entries" ledger, or an explicit inset. Never use an unlabeled visual axis break or distortion of signed amounts.
- [ ] Negative intermediate balances/overdrafts cross below zero correctly; zero change displays as a discrete inspectable event or in detailed ledger; do not render negative values as green.
- [ ] Allow mouse hover, keyboard focus and touch/press to access event details. Provide a companion accessible data table so a chart is not the only source of information.
- [ ] No-data history: clear empty state and correct summary, not a decorative dummy chart.
- [ ] Keep monthly grant, net adjustments, used and remaining summary visible. Preserve allow_gpu_use independent status.

Illustrative domain model for visualization only (not a new persisted ledger):

    opening_balance_gpu_seconds: int
    steps: [
      { id, occurred_at, kind, delta_gpu_seconds: signed int,
        start_balance_gpu_seconds, end_balance_gpu_seconds,
        task_id?, slurm_job_id?, reason?, evidence_source? }
    ]
    closing_balance_gpu_seconds: int

Build this from backend-backed data only. Where an existing history object lacks task/job attribution, show "Not attributed" rather than inventing it.

## 4. Quota page composition — reference screenshot 7

Preserve product's Soft Precision light/dark themes; reference screenshot's black surface is a **geometry reference**, NOT an instruction to turn the account page into a black dashboard. Use one bordered/surface overview only if it improves semantics; avoid nested card soup.

Desktop wireframe:

    Quota                                           [Accounting period: Oct 2026]
    Your compute entitlement and storage ownership.                       (read-only)
    ───────────────────────────────────────────────────────────────────────────────
    Resource usage

    GPU allocation                                                0.1% used · GPU-min
    ┌───────────────────────────────────────────────────────────────────────────────┐
    │■■■ USED  |▒ RESERVED|                          REMAINING                       │
    └───────────────────────────────────────────────────────────────────────────────┘
    Used 11.55 GPU-min     Reserved 0      Remaining 11,000 GPU-min
    [View GPU task attribution →]

    CPU allocation                                                4.4 core-hours
    No enforcement ceiling. CPU time is recorded, not quota-gated.
    [View CPU task attribution →]

    Storage                                                         120 MiB owned
    ┌───────────────────────────────────────────────────────────────────────────────┐
    │■ USED |                                    REMAINING                           │
    └───────────────────────────────────────────────────────────────────────────────┘
    Used 120 MiB            Reserved 0*          Remaining ~100 GiB
    [View storage task attribution →]
    (*show Reserved ONLY if a genuine server-owned reserved storage amount exists)
    ───────────────────────────────────────────────────────────────────────────────
    Selected resource: GPU              [By Task] [Ledger]
    Task / Slurm allocation          Used      Reserved      Evidence / settlement
    a898... / 10304                ...       ...           Settled
    ...                            ...       ...           Unsettled
    Unattributed history            ...       —             Administrative entry
    ───────────────────────────────────────────────────────────────────────────────

Users should first understand position, then optionally investigate attribution. The raw ledger is a disclosure/secondary tab, not the whole primary visual experience. The user can still inspect every existing row and pagination/window caveat.

### Quota semantics (non-negotiable)

- GPU denominator is authoritative configured allowance. Segments Used, Reserved, Remaining must agree with projection. Guard >100% and overdrafts with an explicit excess marker/amount; NEVER clamp excess away. Unknown settled usage is not silently zero; reserve may remain until trustworthy evidence settles.
- CPU currently "Recorded only" / "Not gated". Therefore show **CPU core-hours spent** as a textual meter WITHOUT a percentage, remaining segment or made-up CPU allowance. Only enable percentage when the backend really supplies an enforced positive ceiling.
- Storage denominator is owned-byte limit when present; "100 GiB" is the ceiling, **not** physical free disk. For no limit show "No storage ceiling" and absolute usage, not 0%.
- A ceiling=0 differs from no ceiling: show "0 allowance" or blocked state, no 100%-of-zero chart.
- Rounding 120 MiB out of 100 GiB visually gives a thin bar; include textual values so meaningful tiny allocations are still legible, without lying by imposing a minimum non-zero percentage.
- "Reserved" is not a synonym for storage bytes awaiting deletion. Show storage reservation only if modeled in the authoritative data and actually relevant.
- One user-facing base unit policy: bytes, GPU-seconds, CPU-core-seconds, UTC timestamps in backend; formatted GiB/MiB, GPU-min/core-hours in UI. Make conversions and precision explicit in tooltips.
- The existing QuotaView is used by account and admin drill-in; retain the same canonical projection and avoid separate duplicate layouts/derivations.
- Click/keyboard activation on resource heading/bar reveals task attribution, job IDs, type, elapsed/settled status, counts and evidence, when available.
- Attribution must not be built by summing an arbitrary **paginated recent-ledger window** and claiming complete Task totals. If backend lacks a canonical grouped Task aggregation, add a small authorized resource-usage drilldown endpoint with known completeness/pagination and reuse ledger source; no second authoritative table.
- "Unattributed" is a FIRST-CLASS truth, not data to repair in the UI. Admin adjustments/migrations may have no task. Display counts and caveats where attribution data is missing.
- Link to Task/Slurm view only when authorized and resolvable. No invented links or leaked unrelated-user allocations.
- Read-only user Quota: no grants/reset/delete operations here. Admin mutations stay in Admin operations.
- Use accessible segmented bar label and legend for every segment, not color alone; support small screens via vertical stacking and touch-sized controls.

Sample CSS (adapt existing design system; not exact colors):

    .resource-overview { display: grid; gap: clamp(1rem, 2vw, 1.5rem); }
    .resource-row { display: grid; gap: .45rem; }
    .resource-row__head { display: flex; justify-content: space-between; flex-wrap: wrap; }
    .resource-track { display: flex; overflow: hidden; block-size: .8rem;
                      border-radius: var(--r-pill); background: var(--app-stage); }
    .resource-track__used { background: var(--app-accent); }
    .resource-track__reserved { background: var(--app-line-strong); }
    .resource-row__legend { display: flex; gap: 1rem; flex-wrap: wrap; }

Do not let a tiny usage percentage become invisible to keyboard or assistive technology; adjacent text is mandatory.

## 5. GPU reconciliation — understandable operations

Existing code frontend/src/features/admin/credits/CreditAdmin.ts renders heading "GPU reconciliation" and "Settle retained Slurm evidence after a missing finish callback." The operator clicks Run reconciliation.

Proposed Admin UX:

    Unsettled GPU allocations                        [Reconcile usage]
    Allocation records awaiting trustworthy terminal evidence.
    0 require review   |   Last checked: ... (if recorded)
    ─────────────────────────────────────────────────────────────
    Task          Slurm job   GPUs  Started     Evidence    Settlement
    ...           10304       1     2026-...    Unknown     Review
    ...
    [What does reconciliation do?]
    Re-checks scheduler/controller evidence and settles eligible allocations.
    It does not estimate missing GPU time, erase usage history, or invent zeroes.

- [ ] Rename header and primary button to "Unsettled GPU allocations" / "Reconcile usage" (or similarly plain operator language). Tooltip/explainer states why the queue exists.
- [ ] Display source/reason and status only when the backend returns trustworthy evidence; do not claim "last checked" timestamp if it was never captured.
- [ ] Keep operator confirmation for action that may post immutable ledger facts; after completion present resolved/unresolved/unknown counts if returned, not unconditional "all fixed".
- [ ] No synchronous UI assumption: action failure, timeout and partial reconciliation remain visible and retryable within backend idempotency guarantees.
- [ ] Do not initiate reconciliation on ordinary user page load. Admin-only, existing authorization remains authoritative.
- [ ] Never merge reconciliation into routine GPU credits history as a fictional event; actual ledger adjustments are what appear in history.
- [ ] Do not silently change settlement/accounting algorithm, automatic maintenance cadence, or missing-evidence safety rules.

## 6. Implementation map and checklist

Likely paths to inspect: frontend/src/features/profile/sections.ts and profile CSS; frontend/src/features/quota/QuotaView.ts and quota CSS; frontend/src/features/admin/credits/CreditAdmin.ts and admin.css; frontend/src/features/admin/api.ts, frontend/src/api/app-api.ts, contract types, revocompute/resource_ledger.py, resource_lifecycle.py, routes, tests/server, tests/integration, frontend test fixtures and Playwright; docs/reference/server-api.md/user-guide.

- [ ] Reproduce October screenshot with fixture showing 1,000 monthly grant, +10,011.55 adjustments, 11.55 usage, 11,000 remaining.
- [ ] Verify ledger sign conventions with existing "admin reset", grant and usage; add balance sum invariant tests in base units.
- [ ] Identify whether credit history is complete; implement honest carry-in handling. Reject chart computation if authoritative opening balance cannot be established; show summary and ledger instead of fabricating.
- [ ] Render waterfall with positive green, negative red, zero neutral, cumulative connectors, closing total, responsive labels; support focus, hover, touch and no motion preference.
- [ ] Preserve full audit-table access and period filtering; test extreme positive/negative 6-figure adjustments and small minute-scale usage.
- [ ] Replace Quota envelope-first hierarchy with three-resource usage overview; preserve ledger as optional inspector and existing read-only permissions.
- [ ] Implement task attribution only from complete authorized server facts; show unsettled, unattributed and partial/unknown honestly.
- [ ] CPU ungated: no CPU percent/remaining. Storage without ceiling: no invented 100%.
- [ ] Admin reconciliation plain-language label, explicit safety explanation and idempotent retry behavior.
- [ ] EN/zh-CN, dark/light, mobile/tablet, 200% zoom, keyboard/screen readers, UTC/local labels, big-number formatting.
- [ ] Add focused backend API/unit tests where contract added, frontend unit tests for math/formatting, Playwright for tooltip and drill-in. No code-text snapshot tests.
- [ ] Validate browser UI against screenshot #7 for structure, not synthetic data. Run applicable TS, pytest, Playwright, accessibility checks and mkdocs build --strict on docs changes.
- [ ] Remove PR-local root TODO.md / progress scratch before final review; report exact SHA, remaining caveats, tests and READY_FOR_FINAL_REVIEW. Do not merge/force push.

## 7. Cross-PR and safety boundaries

PR A owns submission availability; PR B owns fleet action UX; PR C owns shared shell/Dashboard/Metrics. PR D must not rewrite those pages or compete over app.css; place styles in feature-local CSS. Coordinate i18n edits with PR #81 and PR C. Resource entitlement is admission truth and append-only ledger is audit truth: this PR must not alter those invariants to fit a desired bar length. No speculative billing, payment, scheduler fairness or accounting database migration.
