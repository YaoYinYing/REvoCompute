# TODO — Runner Management: Evidence-Based Lifecycle Lanes and Action Dialogs

> Campaign: REvoCompute Interaction Model Correction, PR B. Design-only Draft seed.
> Hard prerequisite: coordinate server-side submittability semantics with PR A; do not build a second readiness oracle.
> This root TODO.md is PR-local working design. Before READY_FOR_FINAL_REVIEW remove it from the tracked branch diff and migrate lasting interface documentation to the established operator/developer docs.

## 1. Problem and objective

2026-10-14 screenshot: the current Admin Runner Management table displays "Readiness", "Capacity", "Access", and "In flight" next to Runner names. Thirty families all show BUILD STALE. The table forces an administrator to translate backend engineering dimensions into a lifecycle workflow; click on a Runner appends its details far below the register, losing context. "Idle" under In flight refers to **no operator job in flight**, not a Runner that is idle or a Slurm GPU that is idle. "Access" belongs in user entitlements, not in a Runner build/test workflow.

Replace the presentation with a searchable, scannable **horizontal lifecycle lane matrix**, each Runner one row and each phase one cell, with stage-specific dialogs. Preserve server-owned readiness, evidence provenance, action planning and Host Executor capability. NO frontend-constructed fake lifecycle success.

Important explicit 2026-10-14 user correction:
**REMOVE Promote/Activate and Rollback/Restore from the Web UI wherever the Web deployment cannot execute them. Do not show fake links, disabled-but-inviting buttons, or CLI-only pseudo-controls.** The promoted/active artifact's state may still be displayed READ-ONLY as evidence. Do not expand backend web authority or host mounts just to satisfy a design diagram. If promotion/rollback is only supported through trusted host CLI, keep execution exclusively there.

## 2. Truth model and lifecycle

Read docs/operator-guide/runner-readiness.md and docs/operator-guide/deployment-control.md. Derive from existing fleet/admin contracts:
- NOT_CONFIGURED — invalid contract/configuration.
- NOT_BUILT — missing active SIF.
- BUILD_STALE — built artifact doesn't match current declared inputs/builder evidence.
- NOT_VALIDATED — lacks live-test receipt.
- VALIDATION_STALE — changed runner/runtime/coverage/receipt; image may be reusable.
- READY — required evidence is current.
These are **canonical readiness verdicts**, not a list to replace.

Represent lifecycle **evidence** as five orthogonal, answerable questions:
  BUILD       Is an active executable image present, with build identity evidence?
  TEST        Is a live test receipt present, current and covering required cases?
  ACTIVE      Which image is actually active/promoted? (read-only on Web)
  FRESHNESS   Does active build + validation match current definitions/runtime?
  ENABLED     Is this family configured/enabled for new submissions?

Do NOT turn these into a single mutually-exclusive enum. A family can be active/promoted but stale, or built and tested but disabled. "Unknown" evidence is not "No". Build current and validation current are distinct: changes to mounted runtime bundle can invalidate the latter without requiring SIF rebuild. If backend cannot prove whether an image was promoted as a separate event, show **Active image** rather than fabricated "Promoted". Never infer promoted solely from existence of historical build output.

Other independent facts:
- CAPACITY = real-time Slurm/GPU availability; scheduler busy never makes the SIF stale.
- ACCESS = user's license/policy entitlement; never display as primary lifecycle column.
- OPERATOR JOB = an ongoing management operation (build, test, etc.), not user task occupancy.
- HOST EXECUTOR = a global host capability, not a per-family health assessment.

## 3. Layout art direction

Follow docs/developer-guide/frontend-design-language.md and art direction. One working surface; density for 30+ families; no stacked cards per Runner, no neon rainbow lane, no decorative progress indicators. Colors are semantic and must be paired with text, shape and ARIA. Support dark/light, EN/zh-CN, full keyboard and mobile overflow.

Desktop model:

    Runner Management                                      [Refresh]
    Build, test and deployment evidence for Runner families.

    [Host actions unavailable. Viewing live evidence only.]  (short global notice)
    ───────────────────────────────────────────────────────────────────────────────
    [Search runner family __________________] [State: All ▾] [Sort: Needs work ▾]
    30 families   0 ready   30 require attention    [Show only actionable]
    ───────────────────────────────────────────────────────────────────────────────
    FAMILY            BUILD           LIVE TEST       ACTIVE IMAGE    FRESHNESS   ENABLED
    ───────────────────────────────────────────────────────────────────────────────
    alphafold3         ✓ Built         ○ Needs test    ● Active        ! Build old  Yes
    boltz              ✓ Built         ✓ Passed        ● Active        ✓ Current    Yes
    open-dde           ○ Not built     —               —               —            No
    simplefold         ✓ Built         ! Receipt old   ● Active        ! Test old   Yes
    ... (30+, scroll)
    ───────────────────────────────────────────────────────────────────────────────
    Status legend: ✓ confirmed / ! needs attention / ○ pending or absent / ? unknown
    Select a cell for evidence, corrective operations and history.

This is NOT a time-based Gantt chart. Use a **lifecycle swimlane/matrix** because build/test/activation/freshness are state dimensions, not planned durations. An authentic Operator Job timeline belongs inside a detail dialog; use measured timestamps and durations when present. Do not invent forecast bars, expected durations or per-stage dates.

CSS composition guidance (adapt to existing tokens and component utilities; not a mandatory verbatim implementation):

    .fleet-lanes {
      display: grid;
      grid-template-columns: minmax(11rem, 1.6fr)
                             repeat(3, minmax(9rem, 1fr))
                             minmax(10rem, 1fr) minmax(6rem, .65fr);
      min-width: 58rem;
    }
    .fleet-lanes__cell { min-width: 0; border-bottom: 1px solid var(--app-line); }
    .fleet-lanes__cell[data-state="stale"] { color: var(--app-warning); }
    .fleet-lanes__cell[data-state="missing"] { color: var(--app-muted); }
    .fleet-lanes__cell[data-state="confirmed"] { color: var(--app-success); }

A table with a sticky column is also acceptable and may be more accessible than div role grids. Respect semantic table headers, row labels and keyboard controls. For narrow viewport: horizontal scrolling with visible affordance, a persistent Runner identity column if feasible without trapping focus, plus a mobile stacked-per-runner detail summary when table becomes unusable. Avoid hiding critical evidence because of width.

## 4. Dialog behavior, not page-bottom detail

Example, clicking one lifecycle cell (Build):

    ┌─────────────────────────────────────────────────────────────────────────────┐
    │ AlphaFold 3 — Build evidence                                          [×] │
    ├─────────────────────────────────────────────────────────────────────────────┤
    │ Current state    BUILD STALE                                                │
    │ Active SIF       Present (safe identifier; no local host paths)            │
    │ Build inputs     Declaration digest mismatch                               │
    │ Builder          Recorded version / observed status                         │
    │ Last build       2026-.. (only if measured)                                 │
    │ Reason           BUILD_PROVENANCE_STALE                                     │
    │ Next step        Rebuild image; run host smoke validation                   │
    │                                                                             │
    │ [View recent operator jobs]                                                 │
    │ [Close]                                    [Prepare / Build — if supported]│
    └─────────────────────────────────────────────────────────────────────────────┘

- [ ] Selecting name or stage opens dialog / side sheet anchored to active Runner; stage selected determines default section. Remove existing trailing .fleet-detail-page or equivalent bottom-of-page append.
- [ ] Dialog: focus enters, Esc closes safely, restore focus to originating row/control, role/aria labels, scroll body, fits laptop and mobile, no background operation hidden during confirmation.
- [ ] Evidence: raw reason_code optionally secondary; human explanation primary; last validated timestamp, smoke cases/coverage, hashes in digest-safe truncated form with copy if appropriate. Do not expose privileged host paths or direct commands to browser.
- [ ] Action affordances ONLY from backend-published capabilities and typed action-plan endpoint; read plan and explicit consequences before confirmation. No client-side extrapolation of allowed_actions from cell label.
- [ ] When executor unavailable: show a concise one-line global notice, no enabled mutation operations, dialog remains read-only. Display actual status (not guessed). Avoid a full-width essay or leaking env var fix instructions.
- [ ] While operator action runs: display "Operator operation running: Build" with real job status and link to history/diagnostics. NEVER show "Idle" as if it were GPU state. Disable conflicting actions; keep real family state from backend unchanged until re-evaluated.
- [ ] Present action pending/completed/failed with backend events, error reason and updated status. Refresh changes in-place and keeps search and scroll/selection.
- [ ] Handle stale dialog state if another administrator starts a job; server must reject conflicting operations. Provide safe retry.

### Hard exclusion: promotion and rollback

- [ ] Audit current FleetAdmin.ts and operator API/UI for workflow labels "promote"/"rollback", "Activate"/"Restore previous", action lists, disclosure footers and dialogs.
- [ ] **Remove Web affordances to execute these operations** where host-only per deployment-control contract. Do not show a disabled "Activate" button; no fake CLI handoff button, no request to expose host privileges.
- [ ] Preserve read-only Active SIF / current deployment identity and its provenance. "Promoted" denotes evidence only, not a Web action.
- [ ] Keep host CLI routes, correct authorization and audit logging unmodified unless a real bug requires a separate scoped fix.
- [ ] Assert browser cannot invoke host-only action via any advertised Web mutation control; backend remains authoritative even for crafted POST.
- [ ] Do not introduce an "Enable" Web operation unless there is an existing typed, authorized and executable operation. Enabled/disabled status remains read-only otherwise.

## 5. What to remove from main table

- [ ] Drop Access column. It belongs on user/Runner access policy surfaces.
- [ ] Drop In flight column (with ambiguous "Idle"). Replace operator job activity as subordinate indicator in phase context or dialog, explicitly named "Management operation" if present.
- [ ] Drop Capacity from lifecycle columns. It belongs in resource/scheduler utilization views; where a Runner is READY but workload capacity is unknown, never reclassify its build state.
- [ ] Avoid duplicating an opaque Readiness label **as the entire table's primary model**. Maintain readiness verdict as an aggregate/summary and drill-down.
- [ ] Replace 30-item repetitive "Recommended: build-sif" and wall-of-warning with concise state grouping and phase-specific corrective path.
- [ ] Search, state filter, sort by attention or family, refresh are preserved. Count visible vs total without conflating enabled with ready.

## 6. Files to investigate

frontend/src/features/admin/fleet/FleetAdmin.ts (current page + details), frontend/src/features/admin/admin.css, frontend/src/features/admin/api.ts, OpenAPI types, shared dialog component in frontend/src/components/dom.*, revocompute/operator_service.py / runner_readiness.py / routes.py and operator job schemas, docs/operator-guide/runner-readiness.md, docs/operator-guide/deployment-control.md, playwright/admin fixtures, frontend i18n.

Do not rewrite the existing backend readiness FSM merely to support layout. New UI fields must come from current receipts/evidence or a small server projection, never a second durable lifecycle store.

## 7. Required test matrix

- [ ] Browser screenshot/interaction for at least 30 families: all BUILD_STALE, all READY, mixed, empty register, filtering, details, keyboard, mobile, bilingual, dark/light.
- [ ] Distinguish build stale from validation stale and NOT_BUILT; unknown evidence is never a green tick.
- [ ] Active/promoted but stale is displayable without contradictory state.
- [ ] Disabled but built/validated family keeps correct evidence and unavailable-new-submission meaning.
- [ ] Clicking cell opens modal within viewport; close restores focus; old bottom-of-page detail does not grow document.
- [ ] Host executor absent => read-only, no actionable build/test. Host executor present => only actual supported actions, with typed plan/confirmation.
- [ ] Promote and rollback **absent from Web UI**, and crafted requests are blocked by backend contracts where appropriate.
- [ ] Operator Job active => accurately labelled management activity, no ambiguous Idle or fake "runner idle".
- [ ] Verify PR A shared submittability semantics; reconcile API schema/rebase with Commander.
- [ ] Run focused TS/unit + Playwright, backend admin/operator tests if modified, accessibility audit, docs mkdocs build --strict and relevant full gates.
- [ ] Record exact head SHA, tests, screenshots, negative cases. Remove temporary root TODO and progress docs before final review; finish at READY_FOR_FINAL_REVIEW; owner has no merge authority.

## 8. Coordination / non-goals

- PR A: server-owned submitability projection. B consumes it and does not redesign admission.
- PR C: shared shell/dashboard CSS; B confines styles to fleet/admin feature where possible.
- PR #81 changes guided tours and admin entry points; coordinate conflicts with Commander.
- No broad frontend framework refactor, new Runner control-plane protocol, CLI delegation feature, Slurm scheduling UI or hidden host mutation capability.
