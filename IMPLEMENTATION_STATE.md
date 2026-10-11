# IMPLEMENTATION_STATE — PR #74 Visual QA Campaign

Status: ACTIVE / R0 PRE-FLIGHT — NO EXPLORER OR FIXER EXECUTION RECEIPTS YET
Maintainer activation: 2026-10-11
Owner: Campaign Commander (to be assigned in the executing Claude team)
PR: https://github.com/YaoYinYing/REvoCompute/pull/74
Branch: `chore/visual-qa-campaign-plan`
Merge: prohibited without separate maintainer instruction

## What is confirmed from GitHub

- At authorization, PR #72 and PR #73 are closed and merged.
- PR #74 was the only open PR returned by repository PR search at intake.
- GitHub main at preflight: `d7aecea0e3f31639be5c692bfc1dd599b61bfde7`.
- PR #74 began from `a360093be50bd547d6862ffc75225611c2f68ba6`;
  before this activation commit it was 2 commits behind main and 1 ahead.
  Reconcile ancestry in a PR-owned worktree before implementing; no force-push
  without explicit permission. Refresh exact refs because they may change.
- The repository already contains Playwright tests and a canonical
  `tests/frontend_fixtures/` harness which serves the built production frontend.
  The existing fixture harness has a browser acceptance path under
  `tests/test_playwright_runner_fixtures.py`.
- Canonical design rules:
  `docs/developer-guide/frontend-design-language.md` (Soft Precision);
  aesthetic rationale: `frontend-art-direction.md`;
  questions: `frontend-taste-review.md`;
  live tokens: `frontend/src/styles/app.css`.
- Known browser test annotations already include a strict=False xfail covering
  320px content-heavy Create Task / Result overflow. Treat as an existing
  reported condition requiring browser reproduction, not as a fresh finding.
- Test entry points include `make test-browser` (pytest Playwright),
  frontend npm typecheck/unit/build and the repo CI gates.

## Not yet verified

- Actual Claude teammate availability, slot count, and execution runtime.
- PR-owned worktree checkout and synchronized head.
- Shared development-host resource lease and pressure measurements.
- Safe demo host, isolated test account, real route shell, transport security.
- Browser binary versions, Playwright execution, screenshot storage.
- Real API/fixtures for Admin states, available scientific replay samples.
- R0 screenshot baseline, console/a11y behavior, and any newly found defect.
- Issue registry, Design Authority approvals, fixer ownership, round receipts.

**No agent tasks are represented as completed without execution evidence.**
GitHub metadata writes do not constitute browser exploration, a demo deployment,
or use of any Claude Agent Team slot.

## Next commands for the executing Commander

1. Read `CLAUDE.md`, `docs/agents/long-task-handling.md`, this TODO, and
   the canonical frontend design/testing docs; refresh main and every open PR.
2. Check the repo's existing shared host lease, memory, and browser concurrency
   limits. Create exactly one PR-scoped worktree; keep the control root clean.
3. Reconcile the branch with main, without unauthorized force-push. Check
   frontend bundle, fixture harness, and test entry points.
4. Confirm isolated demo and test-data boundary, then record an exact SHA and
   browser/fixture versions.
5. Dispatch an initial bounded R0 exploration batch with the 6-slot ceiling:
   Commander transient, up to 4 independent Explorers, one Collector; keep a
   slot elastic/reclaimable. Allow the Commander to yield when quiescent.
6. Save R0 environment/screenshots/observations/issue registry. Only then
   have Design Authority triage fixes and repurpose slots for 2–3 Fixers plus
   independent verification. No repeated cosmetic changes without new evidence.
7. Commit periodically in this branch, update this state after meaningful
   milestones, and post concise PR-thread checkpoints referencing exact SHAs.

## Mission lanes (suggested; adapt to verified routes)

- Explorer A: Home, navigation, theme/language, responsive mobile and tablet.
- Explorer B: Runner catalog/detail and Create Task workflow with long schemas.
- Explorer C: Dashboard and lifecycle, search/filter, dense/failure scenarios.
- Explorer D: Result Workspace, files, Mol*, fullscreen, scientific views.
- Explorer E (elastic): Admin and accessibility/keyboard adversarial passes
  once permission and browser capacity are confirmed.

Each Explorer must be read-only and record reproducible evidence from the
**same pinned candidate revision**. The Collector aggregates; never dispatches
Fixers without Design Authority and Commander ownership allocation.

## Round receipt table

| Round | Exact SHA | Fixture/demo | Explorers | Verified new | Fixed | Regressions | Gate | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| R0 | pending | pending | 0 confirmed | — | — | — | not run | awaiting execution environment |
| R1–R10 | pending | pending | 0 confirmed | — | — | — | not run | not started |

## Exit

Stop at quality convergence or the R10 cap, whichever comes first. A final
Visual Quality Report must preserve exact-head test results, reproducible
before/after evidence, unresolved issues, cost/cleanup receipts, and unbiased
review. Remove `TODO.md` and this temporary state from the final PR
implementation branch only after all work is complete and ready for review.
