# TODO — Runner Admission & Fleet Evidence (Campaign 2026-10-25)

> Planning-only file. Remove this root `TODO.md` before declaring the implementation PR READY. No feature implementation is present in the initial Draft.
> Baseline: main `53df3225f894c25d604b7ad16b9a0557ea77c42b`.
> Issues: #89, #90. Owner executes in an isolated worktree; maintainer alone authorizes squash-merge.

## Goal
Make Runner submission eligibility and administrative lifecycle displays agree with **canonical server evidence**, without creating a parallel frontend readiness policy or widening operator permissions.

## Track A — submission/readiness (#89)
- [ ] Audit current API and UI call graph: catalog, Runner method detail, Create Task picker and deep link, preflight, and actual POST. Start from `revocompute/runner_readiness.py`, `revocompute/admission.py`, `revocompute/routes.py` (`_handle_submission` and `resolve_submission_readiness`), and the current TS frontend.
- [ ] Write an explicit truth table covering enabled/disabled, READY/NOT_READY/UNKNOWN, expired or changing attestation, entitlement, infrastructure capacity, and invalid name. Document the exact server-owned reason vocabulary and HTTP semantics; avoid a second TS oracle.
- [ ] Preserve discovery of unavailable methods, but ensure **no surface represents them as submittable**. Deep links and cached pages must fail clearly and guide recovery.
- [ ] Re-check server admission immediately at the final trusted submission boundary. Negative and time-of-check/time-of-use races must create **zero Task IDs, durable uploads, resource reservations, or scheduler jobs**. Trace existing order first; change only demonstrated gaps. Do not disturb tasks already accepted/running/completed.
- [ ] Exercise direct POST bypass, preflight-to-POST race, disappearing/malformed readiness evidence, and entitlement-vs-readiness-vs-capacity distinction with behavioral tests.

## Track B — Fleet lifecycle evidence (#90)
- [ ] Audit the current admin projection and deployed evidence in `revocompute/runner_admin_view.py`, `revocompute/runner_readiness.py`, and `frontend/src/features/admin/fleet/FleetAdmin.ts`.
- [ ] Surface **Enabled** as an independent server-grounded state wherever the canonical deployment evidence supports it. Do not imply that an absent fleet row is proof of readiness, and do not expose disabled families as executable.
- [ ] Repair the misleading **Active image** presentation: current UI uses `sif_exists` for both Build and Active image. Show actual active image identity/state only from an authoritative source; otherwise say **Unknown**. Do not infer active identity from a SIF's existence.
- [ ] Keep Build, Live test, Freshness, readiness, Access, Capacity, and Operator Job separate. Preserve the existing Fleet UI/actions; no speculative Web Promote/Activate/Rollback/Restore.
- [ ] Test differing lifecycle evidence on a representative 30+ family fleet, empty and unknown states, keyboard/dialog semantics, and responsive tables. Use server/contract tests for canonical projection; browser tests for rendered behavior.

## Coordination and evidence
- [ ] One PR owner, bounded independent subtasks. Coordinate with the other two Campaign PRs before modifying shared frontend fixture or CSS surfaces.
- [ ] Use relevant focused Server, integration, frontend, fleet and browser tests; then required impacted CI gates, `make test` where appropriate, and `mkdocs build --strict` if documentation changes.
- [ ] Include failure injection and an exact-head evidence table (test command/result/commit SHA, negative cases, before/after behavior); differentiate host observations from production proof.
- [ ] Obtain independent, counterexample-driven **merge-level review** for the final exact head. Record findings/fixes in this PR's threads. The Independent Campaign Advisor checks direction/scope when warranted, not as a mandatory signoff gate.
- [ ] Remove temporary root `TODO.md`; mark READY_FOR_FINAL_REVIEW only when complete. **Never auto-merge**; maintainer owns squash-merge and issue closure.

## Out of scope
Resource-accounting waterfall #91, broad Admin redesign, fairness scheduling, new Runner parameters, execution engine replacement, and deployment mutations.
