# Resource Quota + Admin — accounting correctness and comprehension

**Status:** PLANNED / DESIGN BRANCH ONLY. **Base:** main at `14ea7441fd1aeeccb2abf37a217c1bbf42ab0e6e`.
**Dependency:** Can independently audit GPU credit/readiness/ResourceEnvelope now. **Navigation integration** waits for PR #79 persistent Shell/account hierarchy to avoid concurrent edits to `frontend/src/app/shell.ts` / `router.ts`. **Fleet backend** must reconcile with PR #76; do not own Host Executor mutation logic.
**Scope owners:** server GPU credits/resource model projections as needed, `frontend/src/features/admin/users/{UserAdmin,ResourceEnvelope}.ts`, `frontend/src/features/admin/fleet/FleetAdmin.ts`, `frontend/src/features/admin/credits/`, new focused user Quota view/tests.

## GPU credits — diagnosis before changes
- [ ] Reproduce that *all* users show 0 in Admin; snapshot exact API responses (redacted user data), distinguish `allow_gpu_use` from allowance and remaining credit.
- [ ] Compare `GET /compute/api/auth/admin/users`, per-user `/gpu-credit`, canonical `/resource-entitlement`, current UTC accounting period and actual append-only resource ledger/policies/reservations. Use test fixture user with configured positive and zero allowances, exhausted vs unset, unknown/unsettled.
- [ ] Inspect `TaskDatabase.DEFAULT_MONTHLY_GPU_SECONDS` and target-deployment policy. Never assume default 1000 credits applies to every user; never reset/overwrite a real ledger to make UI positive.
- [ ] Ensure balances/units `gpu_second` vs `credit=60 GPU-sec` have one canonical server-side projection. Unknown or missing telemetry must be distinct from observed zero, especially unsettled allocations.
- [ ] Add real API+DB contract tests and UI consumption tests, not static source assertions.

## Quota product design
- [ ] Reuse canonical `ResourceEnvelope`: GPU-seconds, CPU-core-seconds, logical storage bytes; show **actual** allowance, settled used, active reserved, unsettled/unknown, remaining, with unit labels; never recompute policy/admission in TS.
- [ ] User-scoped Quota workspace with a clear Account navigation entry (integrate **after PR #79**); Admin users drill into identical projection for a selected user. Both views read same APIs/provenance.
- [ ] Use calm, accurate stacked usage bars/compact visual summaries **only for finite denominators**. If allowance unbounded/unknown/zero, use explicit text state rather than false percentage; never clamp overdraft to hide it. Units and source evidence adjacent.
- [ ] Provide task-level attribution where canonical ledger carries `task_id`, `stage_id`, `slurm_job_id`, class and measured time/bytes. Respect authorization, stable ordering and pagination. Unattributed amounts labeled explicitly; no “all usage attributed” inference.
- [ ] Quota mutation remains existing audited admin API, confirmation, idempotency and explicit reason. Users cannot mutate policies.

## Runner Management redesign
- [ ] Rename Admin “Runner fleet” to user-comprehensible “Runner Management”; label as management of active runtime families, not generic Runner catalog.
- [ ] Summary: READY / needs attention / stale build / unavailable, actionable ordering, density, explanation and drill-down with derived evidence. Capacity, access, readiness and executor availability remain distinct; no computed client-side READY.
- [ ] Separate global Executor health banner from per-family problems; do not mass-rebuild or enable disabled runtimes.
- [ ] Provide meaningful empty/unknown states, EN/ZH copy and 280/320 px/table behaviors.

## Acceptance & guardrails
- [ ] Test credit >0, exactly 0, overdrawn, unsettled, no grant, unknown telemetry, CPU-only user, missing attribution, storage unlimited/limited, role authorization and history-preservation.
- [ ] Mock visuals may be based on the conversational Quota example, but **all displayed production numbers must come from server-owned entitlement**; no 58/12/30 demo percentages committed.
- [ ] Readiness and operator safety contracts remain unchanged; integrate against PR #76 exact head and PR #79 navigation architecture when ready.
- [ ] Focused server, API, Playwright, frontend tests and independent accounting/security reviewer; no production adjustments without separate authorization.
- [ ] Remove temporary TODO and generated mock assets before final merge review.
