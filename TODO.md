# TODO — Runner Submitability: One Admission Truth Across Discovery and Creation

> Campaign: REvoCompute Interaction Model Correction, PR A. Design/assignment seed only; implementation not yet started. Owner to maintain PR-local IMPLEMENTATION_STATE.md when execution begins.
>
> This root TODO.md is **temporary**, per LONG_TASK_HANDLING.md: remove it from the PR diff before READY_FOR_FINAL_REVIEW and preserve stable public contracts in the owning docs. Do not merge root TODO into main.

## 1. Product goal

The public Runner catalog, Runner details, New Task entry point, deep-linked Create Task page, preflight, and POST submission MUST agree about whether a **new** task is submittable. A non-READY Runner never offers an operational Create/Submit action, yet may remain discoverable with a clear reason. Deep links into a non-submittable TaskType produce an intelligible explanation instead of a partially working form. The server must remain authoritative: a disabled DOM button is not admission control.

Observed scenario (2026-10-14): the fleet showed 30/30 enabled Runner families as BUILD_STALE, while the public task workflow could still expose their create-task paths. Fix the projection mismatch; do not make stale runners READY by relaxing validation.

Invariants:
- enabled/configured is not READY; READY is not access granted; access granted is not quota; available GPU is not Runner identity validity.
- The existing Doctor + SIF/build provenance + live receipt + runtime bundle + policy/coverage readiness evaluator owns truth. No second frontend readiness engine, hardcoded list, or static allowlist.
- UNKNOWN, disconnected, timed out, or incomplete evidence is **not** permission to submit. Display unknown/temporarily unavailable without manufacturing reasons.
- A previously admitted queued/running Task is unaffected by subsequent readiness invalidation. Only new admissions must be denied.
- No new Task ID, durable upload, reservation, Celery dispatch, or Slurm job may result from a readiness-rejected request.
- Permission failures remain permission failures. Never leak sensitive host paths, configuration, user identity, or administrator-only evidence into public reasons.

## 2. Required reconnaissance

- [ ] Read CLAUDE.md, LONG_TASK_HANDLING.md, AGENTS.md, developer frontend design language and operator runner-readiness docs.
- [ ] Verify current main HEAD, branches, pending PR #81 (MCP/onboarding changes touch frontend/app/i18n and tour), CI and targeted code before modification. Explicit PR-owned worktree only; no edits in Commander control checkout.
- [ ] Follow existing getTaskCatalog/getTaskType/getReadiness in frontend/src/features/runners/index.ts; inspect frontend/src/features/create-task/, frontend/src/app/router.ts, dashboard New task links, server discovery APIs, preflight and production POST admission.
- [ ] Confirm whether the catalog already contains Runner readiness and/or an admission reason; only extend a server projection if it is genuinely missing. Do not transfer internal credentials or executor configuration.
- [ ] Collect actual 403/404/409/422/503 response semantics and schema generation tooling before editing API contracts.

## 3. UX contracts (ASCII mockups are guidance, not fake production data)

### 3.1 Catalog and method details

    /runners                                                  Search [___________]
    ───────────────────────────────────────────────────────────────────────────────
    Method                       Runner state                     Action
    AlphaFold 3                  ● READY                          [Create task]
      Structure prediction         Eligible, subject to quota
    ───────────────────────────────────────────────────────────────────────────────
    Boltz                        ◌ VALIDATION STALE               [View method]
      Structure prediction         Current image needs live test   Create task unavailable
    ───────────────────────────────────────────────────────────────────────────────
    SimpleFold                   ◌ NOT BUILT                      [View method]
      Structure prediction         No active executable image      Create task unavailable
    ───────────────────────────────────────────────────────────────────────────────

- [ ] Distinguish scientific description from operational availability. Preserve method detail pages; remove or genuinely disable New Task on non-submittable methods.
- [ ] Visible plain-language status and next meaningful action; compact concise labels, color + icon/text redundant; hover-only labels are never the sole carrier.
- [ ] Do not confuse user-specific access restrictions with Runner technical state. Show "Access required" or corresponding existing entitlement state separately.
- [ ] If non-ready methods are hidden from actionable selection, ensure the absence is explained and filter/search still behaves. Do not present "0 available" as "no supported methods".
- [ ] Cover global top-bar "New task", dashboard "New task", runner cards, detail actions, route redirects and keyboard activation, not just one button.

### 3.2 Explicit deep-link failure

    /compute/create_task?task_type=boltz
    ┌──────────────────────────────────────────────────────────────┐
    │  Method temporarily unavailable                               │
    │                                                               │
    │  Boltz cannot accept new submissions.                         │
    │  Runner state: VALIDATION STALE                                │
    │  Reason: Current execution receipt no longer matches runner. │
    │                                                               │
    │  [Browse other methods]          [Back to Dashboard]          │
    └──────────────────────────────────────────────────────────────┘

- [ ] Parse and normalize task_type once; invalid/unknown type is a proper not-found contract, not an arbitrary runtime crash.
- [ ] Before mounting inputs/uploads/editor or allowing submission, resolve server-owned availability for the selected type. Show loading, error, stale and ready as independent views.
- [ ] Direct deep-link failure remains clear after refresh and browser back/forward; no soft redirect that loses the reason.
- [ ] A server-rendered SPA shell may return HTTP 200 as navigation bootstrap; the authoritative typed API must return semantically correct error codes and the **rendered page** must clearly show blocked state. Do not invent a fake HTTP 500 from the SPA.
- [ ] Stable errors: 403 for unauthorized; 404 unknown type; 409 for known but conflicting readiness/policy; 503 for genuine temporary infrastructure failure; use existing contractual codes if already semantically equivalent. Do NOT return 50x for ordinary "not built" or "disabled".
- [ ] Show reason code and safe human explanation, latest known state, a valid non-admin recovery link. No raw SIF paths, kernel tracebacks or internal service topology.
- [ ] No submit button or upload widget in blocked view. Retry/check-again must reread server state; no offline inference or cached READY bypass.

### 3.3 Lifecycle and admission race

    catalog GET -> READY
            |
       user opens editor
            |
    readiness becomes STALE
            |
    preflight / submit -> server recomputes -> 409, no side effects
            |
    UI retains local form inputs, explains change, blocks submission

- [ ] Preflight and final submission recheck authoritative state even if catalog returned READY moments ago.
- [ ] Previously loaded/create-task editor must transition to blocked state after authoritative rejection, without silently dropping chosen inputs; do not promise unsafe re-submission.
- [ ] Handle access revocation, quota exhaustion and scheduler degradation as **separate** reasons rather than making all failures look like build staleness.
- [ ] Use bounded caching only where existing contracts permit; invalidate on deployment/readiness change; correctness must never depend on long-lived frontend cache.

## 4. Technical scope & design

Prefer reusing a server-owned availability projection from the canonical evaluator. If a new transport representation is required, keep it minimal and explicit, conceptually:

    task_type: "<canonical ID>"
    runner_family: "<family>"
    technical_readiness: "READY | NOT_BUILT | BUILD_STALE | ..."
    can_start_new_submission: false
    reason_code: "BUILD_PROVENANCE_STALE"
    safe_message: "Current image needs rebuilding."
    evaluated_at: <UTC timestamp / existing schema if present>

Note: This is a **concept sketch**, not a direction to introduce a duplicated boolean in persisted database tables. The admission path remains authoritative, and any 'can submit' projection is a UI hint subject to revalidation. For user-specific authorization and quota, either supply a server-owned composite projection or keep independent clearly labelled states. Avoid one synthetic universal status that erases provenance.

Potential files to trace (verify, do not blindly change): frontend/src/features/runners/index.ts, frontend/src/features/create-task/, frontend/src/app/router.ts, frontend/src/app/shell.ts, frontend/src/api/app-api.ts, generated OpenAPI types, revocompute/routes.py, revocompute/admission.py, revocompute/runner_readiness.py, integration/browser tests, owned user/operator docs.

## 5. Execution checklist

- [ ] Write focused failing backend test: catalog advertises stale/invalid state and the submission endpoint blocks the same Runner.
- [ ] Write focused failing Playwright test: stale Runner has no actionable create-task entry on catalog and detail views.
- [ ] Write focused direct deep-link browser test for NOT_BUILT, BUILD_STALE, VALIDATION_STALE, disabled, unknown task, user unauthorized, and unreachable readiness.
- [ ] Implement canonical projection, not a second TypeScript decision tree. Reuse existing public reason vocabulary.
- [ ] Apply actionable/disabled contract to every entry point and keyboard action.
- [ ] Add an explicit, localized failure experience; preserve human-readable loading/empty/error states and safe accessibility.
- [ ] Verify race: READY when page loads, STALE before submit => no side effects; surface rejection rather than assuming the UI hint admits.
- [ ] Verify already-running tasks and historic results remain readable after invalidation.
- [ ] Cover dark/light themes, narrow/mobile widths, English/Simplified Chinese, refresh/back/forward, network failure.
- [ ] Update owning user documentation; no duplicate root guide; generated API schema only via existing workflow.
- [ ] Run focused backend, frontend unit, Playwright, API/contract, full applicable gates and mkdocs --strict for docs edits; record commands, result and exact head SHA.
- [ ] Remove this temporary tracked root TODO.md and execution-state scratch docs before final review; retain durable implementation explanation in existing docs.
- [ ] Report READY_FOR_FINAL_REVIEW only with evidence and exact SHA. No merge, no force-push without Commander permission.

## 6. Negative/failure acceptance

- No stale Runner can be submitted by typing URL, calling JSON API directly, following a cached link, or racing with status change.
- No non-ready false-positive "available" buttons in public catalog, New Task selection, or method detail.
- Unknown/unreachable is not displayed as READY or as capacity zero.
- Unauthorized users cannot use error details to infer licensed methods they should not inspect.
- No leaked upload bytes, resource hold, Slurm job, or durable Task on rejected admission.
- No unrelated Runner YAML changes, no readiness policy weakening, no new duplicate state store.

## 7. Coordination

This PR A defines the availability presentation semantics consumed by PR B (Runner lifecycle lanes). PR B must not independently invent a conflicting "submittable" evaluator. PR #81 touches tours/i18n; coordinate that overlap. Commander owns integration/rebase and final merge decision.
