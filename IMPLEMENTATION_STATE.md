# IMPLEMENTATION_STATE — PR #74 Visual QA Campaign

Status: ACTIVE / R1 DISCOVERY COMPLETE — TRIAGE + DESIGN AUTHORITY IN FLIGHT
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

Served-bundle identity was verified by asset hash: the real app served
`app-CY-0vaDE.js`, byte-identical to the pinned build's
`frontend/dist/.vite/manifest.json` entry from `d1874814`. (The long-lived 309
deployment on `:8081` serves `app-DWUKs37W.js` — a different revision. The live
site was **read-only observed, never touched**; it is not the campaign target.)

### Non-2xx subresources, explained (not findings)

The realness harness returns exactly two non-2xx subresources, both proven to be
environment artifacts rather than product defects:

- `/openapi.json` 404 on `/api-docs` — the harness overrides `app.static_folder`
  with a temp root holding only the `app/` bundle symlink, so
  `send_from_directory(static_folder, "openapi.json")` misses. The route exists
  (`@app.route("/openapi.json")`); a real deployment serves the file. All other
  literal-static-file checks are equally non-authoritative under this harness.
- `/compute/api/auth/admin/logs/gunicorn-access?tail_bytes=1000000` 404 on
  `/compute/logs` — no gunicorn access log exists under the isolated dev server;
  the log viewer reports the absence as 404.

Both were found by an explicit response probe
(`tools/probe_bad_responses.py`), not inferred.


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


## R1 receipt — discovery (2026-10-11, revision `d1874814`)

Four read-only Explorer agents ran the fixture harness at the pinned revision;
each captured PNG evidence and wrote a structured `findings.json`. Raw output
lives under `/mnt/hdd/revocompute-agent-scratch/pr74/r1/{a,b,c,d}/` (B also emits
sibling `b_resp/`, `b_confirm/`; A emits sibling `a-*` dirs — sibling layout is
not missing evidence).

- **Explorer A** (shell/nav/theme/i18n/responsive): 9 entries. No shell defect
  found; 320→1920px shows zero horizontal overflow and zero console errors.
  Harness coverage gaps: `/compute/register` unserved by the fixture router
  (route exists server-side); narrow-width `.runner-facts` paint timeout.
- **Explorer B** (catalog/detail → Create Task): 6 entries. Substantive:
  320px workbench overflow; pre-emptive "N issues to fix" on pristine mount;
  zh-CN body-copy gap; restricted-detail ungated "Create task".
- **Explorer C** (dashboard/lifecycle): 3 entries. Dashboard omits infra
  readiness (present on `/runners`); table Status renders raw enum vs card
  curated label; running-task progress affordance (reproducible: false).
- **Explorer D** (result workspace/Mol*/a11y): 6 entries. zh-CN does not
  localize the Result workspace; heading source order (shell `h2`s before page
  `h1`); matrix result 16× 404 console burst (renders gracefully). Coverage
  gaps: Profile `/user-metrics` unserved; download-only artifact selector miss.

24 raw entries. These are **observed**, not yet triaged.

## R1 triage + Design Authority (2026-10-11)

Issue Collector deduped 24 raw entries to **7 substantive issues, 7 coverage
gaps, 10 no-action** (`registry.json` / `registry.md`). Design Authority
adjudicated each against Soft Precision (`design-verdicts.json` /
`design-verdicts.md`).

**APPROVE-FIX (defect, fixer worklist):**
- `R1-B-01` 320px content-heavy overflow (Create Task + Result result-header).
  DA corrected the explorer: single-column reflow already exists at <=860px/<=560px,
  so the Fixer must measure the true residual offending node. The existing
  `strict=False` xfail is a deferred fix, not an accepted limitation - flip to strict.
- `R1-B-03+R1-D-01` zh-CN partial localization (Create Task / Runners / Results
  body copy). Sec 11 boundary: localize frontend-authored prose; server-owned
  scientific vocabulary stays English, never duplicated into the catalog.
- `R1-C-02` dashboard Table Status renders raw enum vs card outcome. One-line fix.
- `R1-D-02` shell nav-group h2s precede page h1. Semantics-only fix.

**PROPOSE-CHANGE (maintainer/product decision - NOT implemented unilaterally):**
- `R1-B-02` pristine Create Task shows many issues to fix on mount.
- `R1-B-06` restricted runner detail still shows primary Create task beside the
  Restricted banner (downstream gate correct; not a bypass).

**NO-CHANGE (no-action):** `R1-C-01` dashboard readiness (belongs to the Sec 12.2
notice surface, not a dashboard region), `R1-D-03` matrix 404 burst (fixture-harness
artifact; UI degrades gracefully).

**Fixer dispatch (R2).** Three isolated PR-owned worktrees cut from the campaign
head `f99cbe57`, one writer each, disjoint surfaces: `pr74-fix-dashboard-shell`
(R1-C-02 + R1-D-02), `pr74-fix-ct-320` (R1-B-01), `pr74-fix-i18n`
(R1-B-03 + R1-D-01). Each owns a focused behavioral test plus the typecheck /
unit / build gate (Playwright where required) under the host lease. The two
PROPOSE-CHANGE items are held for maintainer sign-off, not dispatched.

## R2 receipt — fixes (2026-10-11)

Three Fixers ran in parallel in isolated PR-owned worktrees cut from the
campaign head `f99cbe57`, one writer per disjoint surface, no shared CSS file:

- `chore/pr74-fix-dashboard-shell` @ `4cdc8aca` — R1-C-02 (dashboard table Status
  now uses the shared `statusText()` = `task.outcome || task.status`, matching the
  card; filter/sort/class stay on the raw enum) and R1-D-02 (nav captions demoted
  `h2` -> `span`, each group `role="group"` + `aria-labelledby`; page `h1` now
  leads the outline, no visual change). Follow-up: four browser assertions that
  used `get_by_label("Administration")` as a proxy for "no top-bar launcher" were
  re-scoped to `.app-header` (top bar) so they still assert the original
  requirement without the newly-labelled region making them ambiguous.
- `chore/pr74-fix-ct-320` @ `7de63615` — R1-B-01. Measured the TRUE culprit: the
  single-column reflow already existed; the residual 320px overflow was a
  min-content floor propagated through a bare `1fr` track from the native file
  input. Fixed with `minmax(0, 1fr)` in the existing <=560px tier and
  `flex-wrap: wrap` on `.result-header` at <=32rem (no new breakpoint). Flipped the
  `strict=False` xfail to a required assertion; both parametrizations pass.
- `chore/pr74-fix-i18n` @ `99b99bf3` — R1-B-03 + R1-D-01. Catalog expanded to
  393 en / 393 zh-CN in exact parity; Create Task, Runners and Results frontend
  prose routed through `t()`. Sec 11 boundary held: server-owned scientific
  vocabulary is not in the catalog and stays English verbatim; templated validation
  localizes only the frame, not the interpolated server label.

**Integration.** All three merged into `chore/visual-qa-campaign-plan` ->
**`8c04b86dcc2c750de7b37ef930f311251a636802`** (merges `826557f4`, `6eea9467`,
`8c04b86d`; no conflicts). Integrated gate at `8c04b86d` under the host lease:
`npm run typecheck` clean, `npm test` 129 passed / 25 files, `npm run build` +
`verify:build` exit 0, and the three browser modules `130 passed in 115.74s`.

**Held for maintainer (PROPOSE-CHANGE, NOT implemented):** R1-B-02 (pristine
Create Task shows `N issues to fix` on mount) and R1-B-06 (restricted runner
detail still shows a primary `Create task` beside the Restricted banner). Both are
design-authority `design-proposal`, not defects; the downstream gate is correct in
each case. The design language does not settle either, so they await a maintainer
decision rather than being changed unilaterally.

## R3 receipt — independent verification + visual confirmation (2026-10-11, `8c04b86d`)

Two independent agents reviewed the integrated head. Neither wrote the code under
review.

**Independent Verifier** (`verification.json` / `verification.md`), gate re-run by
the verifier itself: typecheck PASS, unit 129/129 PASS, build PASS, browser
`130 passed in 116.44s`, 0 xfail remaining. Per-claim verdicts:

- `R1-D-02` **CONFIRMED** — page `h1` is first in the outline on every probed
  route; each group resolves to one accessible name at 360/834/1000/1280 and both
  rail states; no code depended on the caption being a heading.
- `R1-B-01` **CONFIRMED** — counterfactual: re-injecting the OLD declarations
  restores +56px (create_task) and +25px (results) at 320px; shipped CSS is 0/0.
  No tap target shrunk.
- `R1-C-02` **PARTIAL** — `statusText()` is shared and filter/sort still use the
  raw enum, but card and table still do NOT render the same text for a finalized
  task with no per-item `outcome` (`outcome` null/`""`): the card pill carries the
  global `text-transform: capitalize` (app.css:253) and reads `Finished`, the
  table cell has no transform and reads `finished`. The new unit test compared raw
  `textContent`, so it could not see the case difference. Display-only.
- `R1-B-03+R1-D-01` **PARTIAL** — boundary held (no server value routed through
  `t()`; parity 397/397 verified independently), but frontend-authored ERROR copy
  in the same features is still English and reaches a zh-CN user
  (`create-task/api.ts` ~20 workspace-plugin errors via `InputWorkspace.ts:103`,
  `submission.ts`, `results/scientific.ts`, `structure/MolecularViewer.ts`).
  `InputWorkspace.ts:103` also matches the English substring `'unsupported
  component'`, which couples behavior to user-facing language.
- Incidental (pre-existing, not a regression): at 561-860px the parameter heading
  overflows its own grid cell by ~28px, absorbed by an ancestor so the document
  `scrollWidth` stays 0.

**Visual Confirmation Explorer** (`r3/findings.json`), before/after through the
same fixture harness (BEFORE = `d1874814` via `git archive`, driven through the
identical harness): **4/4 fixes PASS, 0 new regressions, CONVERGED**, 0 console
errors on every AFTER route. 320/375/768/834/1440 sweep clean; dark + zh-CN
render clean; rail toggle and `aria-current` preserved. R1-C-02 measured
`finished` -> `SUCCESS` in light AND dark; R1-D-02 outline `['Compute','Account',
`Dashboard`,...]` -> `['Dashboard',...]`; R1-B-01 `376/320` -> `320/320` and
`345/320` -> `320/320`.

**Consequence.** The confirmation round proves the four fixes visually converge,
but the verifier's two PARTIAL verdicts are real residual defects (same approved
findings, incompletely closed). Per the campaign rule that no owner READY or
green CI substitutes for counterexample-driven review, R4 reopens exactly those
two residuals as fresh, isolated fixes rather than declaring the round closed.

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
| R1 | `d1874814` | fixture harness | 4 explorers (A–D) | 24 raw entries | — | — | not run | **discovery complete; triaged** |
| R2 | `8c04b86d` | fixture harness | 3 fixers (disjoint surfaces) | 0 new | 4 approved fixes | none | typecheck+unit+build+browser all green | **fixes integrated; verification in flight** |
| R3 | `8c04b86d` | fixture harness | 1 verifier + 1 confirmation explorer | 4 confirmed / 2 partial | — | 0 | before/after browser + 130 browser passed | **verification complete; residuals fixed in R4** |
| R4–R10 | pending | pending | 0 | — | — | — | not run | not started |

## Exit

Stop at quality convergence or the R10 cap, whichever comes first. A final
Visual Quality Report must preserve exact-head test results, reproducible
before/after evidence, unresolved issues, cost/cleanup receipts, and unbiased
review. Remove `TODO.md` and this temporary state from the final PR
implementation branch only after all work is complete and ready for review.
