# Production UI Polish - Implementation State

`TODO.md` sections 28-34 are the acceptance contract for PR37. This file
records execution state against that contract: the ten required fields, the
browser evidence, and the gate results. It is an execution record, not a diary.

## 1. Starting SHA

`87aeb19` - `feat(frontend): refine REvoCompute visual and product language
(#35)`. Branch: `feat/ui-polish` off `main`.

This work does not reopen the PR32-PR35 presentation architecture: the Vite SPA
stays the single presentation owner and the server keeps serving APIs only. The
change set is presentation (tokens, layout, copy), the Create Task control flow,
and two fixed legacy redirects.

## 2. frontend-design skill usage

The `frontend-design` skill was loaded and used as a critique frame against the
deployed post-PR35 surface: palette roles, typographic hierarchy, surface
grouping, and layout rhythm. It drove foundation-level corrections (palette
de-tint, font-role correction, hairline reduction) rather than per-page
decoration.

## 3. Baseline pages captured

Five pages captured before and after, each at desktop 1440x950 and mobile
390x844, in light and dark:

- Home `/`
- Runner Catalog `/runners`
- Runner detail `/runners/gremlin`
- Dashboard `/compute/dashboard`
- Create task `/compute/create_task?task_type=gremlin`

Captured from the local production build (`frontend/dist`) with mocked APIs to
a scratch directory. Scratch evidence only; not a repository artifact.

## 4. Direct screenshot inspection

The active agent **could and did directly inspect the rendered screenshots**
(image understanding was available). The after set - including the desktop and
mobile dark Create Task surfaces - was inspected directly; findings were read
off the images, not inferred from source. No claim of visual inspection is made
for any image that was not actually rendered in the agent's context.

## 5. Foundation changes

`frontend/src/styles/app.css` carries the foundation corrections:

- Corrected the green-tinted dark palette to a cool neutral canvas; separated
  cyan identity (`--app-accent`) from semantic green/success so identity and
  status are no longer the same signal.
- Replaced `--font-serif` with `--font-display` (identical to `--font-sans`),
  removing the accidental Georgia/serif application styling under strict CSP
  (`font-src 'self'`, no webfont). Hierarchy now comes from scale, weight,
  measure, and spacing.
- Reduced hairline-driven layout: fewer full-width separators; grouping carried
  by surface, spacing, and elevation rather than a border around every block.
- Consolidated duplicated success/accent roles and removed obsolete tokens.

## 6. Page changes

Feature-local presentation was corrected on top of the foundation:

- Home: REvoCompute-first; the scientific identity leads rather than an
  incidental motif.
- Runner Catalog: intentional density at 1 / few / many methods - the single
  enabled runner reads as deliberate, not as an empty grid.
- Create task: workbench and snapshot rail polished against the real
  PSSM-GREMLIN workflow. The rail is a Task Snapshot built from the collected
  capability summaries, and the `review` workspace capability was removed end to
  end, so the protocol column no longer duplicates the rail.
- Admin, auth, API docs, legal, profile, results: de-tinted and de-haired to
  match the corrected foundation.

Runner availability continues to derive from canonical APIs; no product code
special-cases the temporary 309 host.

## 7. Single-action submission status

Create task is a single `Run task` action. It validates locally, runs preflight,
and submits automatically on success - there is no second Review click. Server
safeguards are untouched: `preflightTask` always runs before `submitTask`; an
invalid preflight aborts without submitting; the `busy` guard prevents double
submission.

## 8. Legacy redirect status

Two fixed redirects were added, destinations as literals that are never derived
from request path or query (no open redirect):

- `/PSSM_GREMLIN/dashboard` -> `/compute/dashboard`
- `/PSSM_GREMLIN/create_task` -> `/compute/create_task?task_type=gremlin`

The destination keeps its own authentication boundary; the contract test
asserts an anonymous request to the destination still returns 401.

## 9. Browser acceptance

Rendered browser evidence was captured and directly inspected across Home,
Runner Catalog, runner detail, Dashboard, and Create task at desktop and mobile
widths in light and dark. The Playwright application suite and the focused
server frontend contract pass on the current tree.

## 10. Test results

Recorded on the current tree:

- Frontend: `npm run typecheck`, `npm test` (60 passed, 16 files), and
  `npm run build` (+ `verify:build`) all pass.
- Focused contracts: `tests/server/test_application_frontend_contract.py`
  4 passed; `tests/test_playwright_application.py` 37 passed, including the
  five single-action cases (`preflights_then_submits_without_a_second_click`,
  `run_task_is_disabled_until_local_validation_passes`,
  `failed_preflight_blocks_submission_and_restores_the_form`,
  `repeated_run_task_clicks_submit_once`,
  `the_check_window_locks_the_method_and_rejects_changed_inputs`).
- Browser gate (`make test-browser`): 89 passed, 2 skipped.
- Backend suite: under a fresh `TMPDIR` (which clears the tool-call `/tmp`
  failures), `uv run python -m pytest tests/ -m "not browser"` on the final tree
  reports **3 failed, 1501 passed, 19 skipped, 89 deselected**, exit 0. The
  three remaining failures are the environment-bound host-state cases below and
  reproduce on unchanged code, not regressions; no product source was changed
  for them:
  - two `tests/server/test_gpu_credits.py` admin-reset cases fail on host state
    and fail again on re-run;
  - `tests/runners/opendde/test_opendde_protocol.py` (x1) fails because it
    asserts an output path `.startswith('/tmp/')`, which the fresh `TMPDIR`
    changes.
  Under the default (saturated) `/tmp`, three tool-call cases also fail —
  `tests/server/test_tool_call_protocol.py` (x2) and
  `tests/server/tools/test_call_store.py` (x1) — for the same environment reason.
- `make test-cov`: passes with the same environment failures as above.
- `mkdocs build --strict`: passes from the repository root.

## 11. Gate that could not run

- **Which gate:** `make test-docker-full-stack`
  (`bash tests/run_full_stack_test.sh`).
- **Why:** the Docker build cannot reach the host-local egress proxy. The only
  proxy on this workstation is a `gost` listener bound to `127.0.0.1:63322`,
  which a container network cannot route to, so `apt-get`/`pip` egress fails
  and the image build aborts before the stack starts. This is unrelated to the
  change set.
- **What narrower evidence passed instead:** `npm run typecheck` / `npm test` /
  `npm run build` (+ `verify:build`); the focused server frontend contract; the
  full Playwright application suite; the browser gate; the backend suite and the
  coverage run; `mkdocs build --strict`; and direct render of the local
  production bundle across the five pages in both themes at both widths.
- **What remains to run later:** `make test-docker-full-stack` on a host whose
  container network has working package egress.

## 12. Known deferred issues

- `make test-docker-full-stack` could not run here (see the block above).
- The environment-bound backend-suite failures (host-state GPU-credit resets and
  a `TMPDIR`-sensitive OpenDDE path assertion) reproduce on unchanged code; they
  are not addressed by this change set.
- The two production DB path changes on the live 309 instance are deployment
  configuration and are not part of this change set.

## 13. Review findings resolved before the PR

A three-agent review of the post-removal change set surfaced the following;
all were fixed in the final tree before opening the PR:

- The single `Run task` action could submit a method the user had already
  navigated away from while the preflight was in flight. Fixed with an
  operation guard: the check owns the run for its duration — **Change method**
  and **Run task** are disabled/busy across the check, an in-flight run is
  abandoned when the method changes, and an input edit inside the check window
  invalidates the pending check instead of submitting pre-edit inputs.
- The mobile **New task** control lost its accessible name when its label span
  was hidden at narrow widths; it now carries an explicit `aria-label`.
- Two pages still described a terminal review step
  (`docs/operator-guide/task-adapters.md`, the RFdiffusion reference diagram in
  `docs/developer-guide/input-result-workspace.md`); both corrected.
- Residual `ct-review` / `refreshReview` naming in the snapshot rail renamed to
  `ct-snapshot-panel` / `refreshSnapshot`.
- `revocompute/doctor.py` no longer keeps a second copy of the built-in
  workspace-plugin allow-list; it imports the Core set.
- Added behavior tests for the snapshot summary collection and the single-action
  flow (validate → preflight → submit, blocked submit, single submit under
  repeat clicks, check-window invalidation).
