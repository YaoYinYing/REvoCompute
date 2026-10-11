# IMPLEMENTATION_STATE — PR #74 Visual QA Campaign

Status: ACTIVE / R1 DISCOVERY IN FLIGHT — R0 COMPLETE
Maintainer activation: 2026-10-11
Owner: Campaign Commander (executing)
PR: https://github.com/YaoYinYing/REvoCompute/pull/74
Branch: `chore/visual-qa-campaign-plan`
Merge: prohibited without separate maintainer instruction

## R0 receipt — baseline, environment, realness (2026-10-11)

### Refs and ancestry

- `main` at R0: `d7aecea0e3f31639be5c692bfc1dd599b61bfde7` (unchanged since #73).
- Campaign branch reconciled onto main by rebase (force-push authorized by the
  maintainer mid-R0), then force-pushed with lease:
  `87a9394b` → **`d1874814f99715416b66f035e7828621ae590ed0`**.
- PR diff vs main is unchanged in content: `TODO.md` (+264) and
  `IMPLEMENTATION_STATE.md` (+94) only.
- Only one open PR (#74) exists; no competing frontend owner.

### Worktree and control root

- Canonical implementation worktree:
  `/home/yinying/repo/.rc-worktrees/pr74-visual-qa` → `d1874814`.
- Commander control root `/home/yinying/repo/REvoCompute` stays on `main`,
  synchronized with `origin/main`, no implementation writes.

### Heavy resource lease

- Adopted host lock: `/mnt/hdd/revocompute-agent-scratch/host-heavy.lock`
  (held free at R0). Every browser/build run wraps it with `flock -w 300`, reads
  `free -m` + `/proc/pressure/memory` after acquiring, and runs inside
  `systemd-run --user --scope -p MemoryMax=6G -p MemorySwapMax=4G`.
- Host at R0: 31.7 GB RAM, 16 CPUs, memory pressure some/full avg10 ≈ 0.

### Browser / build baseline

- Chromium **153.0.8010.52** (`~/.cache/ms-playwright/chromium-1243`), software
  GL via `--use-angle=swiftshader` (Mol* requires a non-caveat WebGL context).
- Production bundle built from `d1874814` under the lock: `npm run build`
  (verify:lock + verify:provenance + check:api-types + vite build + verify:build)
  → exit 0, `frontend/dist`.
- Shared test-only browser dists built once for the campaign and reused by every
  explorer: `/mnt/hdd/revocompute-agent-scratch/pr74/dist/{result,scientific}`.

### Demo environment (disposable, isolated)

Two complementary harnesses, both served locally, no production data, no Slurm:

1. **Fixture harness** (`tests/frontend_fixtures/`, repository-owned) driving the
   built bundle against deterministic canonical API fixtures. Wrapper:
   `/mnt/hdd/revocompute-agent-scratch/pr74/tools/browser_harness.py`.
   Covers Home, Runners, Create Task, Dashboard, Result workspace, Profile.
2. **Realness harness** (`.../tools/realapp_harness.py`) serving the **real Flask
   app over real HTTP with the real built bundle**, via
   `tests/conftest.py::_load_pssm_module` + the WSGI transport pattern from
   `tests/fleet/browser/test_playwright_admin_pages.py`. This is what answers
   "does the production page route exist".

### Realness route matrix (real Flask + real bundle, 1440×900)

| route | anon | user | admin |
| --- | --- | --- | --- |
| `/`, `/api-docs`, `/runners`, `/compute/dashboard`, `/compute/create_task`, `/compute/profile`, `/compute/login`, `/compute/register`, `/compute/terms` | 200 | 200 | 200 |
| `/compute/user_control`, `/compute/runner_fleet`, `/compute/logs`, `/compute/configuration` | 200 (shell) | **403** | **200** |

Browser-visible statuses confirm the documented authorization boundary: an
anonymous visitor is handed the shell (the client redirects to sign-in), a
signed-in non-admin receives the 403 shell, an admin receives the shell. 39
screenshots captured at `.../r0/realapp/`.

### Known coverage limitation (not a defect)

The fixture harness has no admin API projections, so the four admin pages render
their shell but their data panels show empty/error states in fixture runs. Admin
*page-route existence and authorization* are verified by the realness harness;
admin *data-panel states* are therefore only partially covered. This is an
explicit R0 limitation, not a discovery.

### Existing reported conditions carried in (not fresh findings)

- `strict=False` xfail covering 320px content-heavy Create Task / Result
  overflow (per the design doc).
- `revocompute.sqlite3.startup.lock` present in the control root (untracked
  runtime residue; not PR-owned).

### R0 exit

No UI fixes dispatched. R0 established the baseline, environment, realness
matrix, and coverage limitation above; R1 exploration is in flight.


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
| R0 | `d1874814` | fixture harness + real Flask harness | 0 | — | — | — | realness matrix captured | **complete** |
| R1 | `d1874814` | fixture harness | 4 explorers (A–D) | in flight | — | — | not run | **in flight** |
| R2–R10 | pending | pending | 0 | — | — | — | not run | not started |

## Exit

Stop at quality convergence or the R10 cap, whichever comes first. A final
Visual Quality Report must preserve exact-head test results, reproducible
before/after evidence, unresolved issues, cost/cleanup receipts, and unbiased
review. Remove `TODO.md` and this temporary state from the final PR
implementation branch only after all work is complete and ready for review.
