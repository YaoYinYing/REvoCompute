# Restart Safety and Compact Dashboard Implementation State

Design source: `TODO.md`

## Current phase

Implementation complete; final delivery, exact-head CI, and production redeployment are in progress. The earlier frontend-hardening work remains in place while this follow-up fixes restart snapshot skew and the specified frontend/API regressions.

Next action: inspect and commit the final diff, push it to PR #13, verify all blocking CI jobs on that exact SHA, then redeploy production and perform the post-deploy checks.

## Visual design plan

- Color: retain mineral canvas `#eef2ed`, paper `#f8faf7`, research ink `#1d2a2f`, evidence teal `#0f4f63`, process green `#0d6e66`, and caution ochre `#b06c14` through existing tokens.
- Type: retain IBM Plex Sans for operational/data surfaces and Source Serif 4 only for established narrative headings.
- Layout: use compact horizontal toolbars and audit rows for operational pages; extend the existing landing two-column grid so the agent entry sits under the evidence column on desktop and spans normal flow below it on narrower screens.
- Principles: stable geometry, scan-first scientific data, restrained hierarchy, and no new card/pill vocabulary.
- Brief review: avoid the generic SaaS-card pattern by removing repetitive activity cards and the stretched Manage pill; preserve the evidence map as the sole expressive composition and keep every other changed surface quiet.

## Completion checklist

### Restart lifecycle

- [x] Keep each running server on one immutable `SERVER_DIR/docker/runners` snapshot for its lifetime.
- [x] Preserve/finalize in-flight tasks with the old container code and old snapshot before mutating deployment metadata.
- [x] Abort before Compose shutdown when pre-stop job cancellation or task preservation fails.
- [x] Stop the old stack before materializing and validating the new Runner snapshot.
- [x] Ensure the new server starts with matching new code and Runner metadata.
- [x] Audit `CONFIG.runners_dir`, `RUNNER_SOURCE_ROOT`, Compose mounts, discovery paths, and restart ordering.
- [x] Decouple pre-stop task-state preservation from full Runner discovery only if state semantics remain explicit and unduplicated.
- [x] Document the immutable instance metadata contract and operator-visible failure behavior.
- [x] Add mocked restart/version-skew coverage proving an advancing source cannot change old-instance pre-stop behavior.

### Dashboard

- [x] Make Compact mode preserve `details`, `results`, and `download` through semantic `data-action` selectors.
- [x] Verify Results and Download invoke distinct behavior, Download remains visible in `Preparing…`, geometry is stable, and Delete stays hidden.
- [x] Replace generic growing Dashboard control flex rules with a deterministic responsive filter grid.
- [x] Align first-row labels and control surfaces regardless of reserved regex-error content.
- [x] Keep all date fields consistently bounded, View controls content-sized, and Selection independent.
- [x] Add 1366/1920 geometry and overflow coverage while preserving regex, sort, layout, and selection behavior.

### Runner Access policy management

- [x] Keep accepted Restricted policy summary rows geometrically unchanged when Manage opens.
- [x] Replace the obsolete inline `#accessPolicyDetail` path with the shared accessible dialog and remove its stale DOM/CSS assumptions.
- [x] Render policy label/ID, counts, compact identity/state/action rows, and compact explicit empty groups in a bounded scrolling dialog.
- [x] Project existing policy-detail data needed for applicable revoke and decision actions without changing authorization semantics.
- [x] Reuse existing approve/reject/revoke/clear-suspension endpoints and shared destructive confirmations.
- [x] Refresh dialog detail, summary counts, request queue, and recent activity after mutations without a page reload.
- [x] Verify focus entry/return, Escape close, stable page geometry, immediate Recent activity placement, and desktop/tablet/phone overflow.

### Runner catalog visibility

- [x] Establish one application-wide semantic `[hidden]` rendering contract after auditing all current uses.
- [x] Verify real-template Runner search visually removes unmatched cards and zero-match categories despite normal flex/grid display rules.
- [x] Cover text/category composition, count/empty state, clearing, density transitions/persistence, and desktop/tablet/phone overflow.

### Progressive agent API

- [x] Make `/compute/api/types` a compact catalog projection with access state and detail/schema links but no parameter/schema/detail payloads.
- [x] Make `/compute/api/types/{name}` the selected method's scientific/form-presentation contract while linking, not duplicating, the canonical parameter schema.
- [x] Keep `/compute/api/task-parameters/{name}` as the sole full Runner-owned Draft 2020-12 parameter contract.
- [x] Add unambiguous `task_id`, `status_url`, and `results_url` submission/status guidance without breaking existing Location-based clients.
- [x] Audit and migrate Create Task, Runner catalog/detail, and Configuration consumers from the former rich collection payload.
- [x] Update OpenAPI, `/skills.md`, server API docs, README/user guidance, and structural separation tests for catalog -> detail -> schema -> submit -> monitor -> results.

### Documentation ownership

- [x] Point generic Documentation navigation on landing, Runner catalog/detail, and API docs to the REvoCompute documentation site.
- [x] Preserve the intentional REvoDesign PyMOL installation/plugin links and classify all other stale URLs.
- [x] Add a template contract test preventing generic navigation from drifting back to REvoDesign docs.

### CI performance

- [x] Register an explicit `browser` marker and classify every Playwright contract exactly once.
- [x] Keep `make test` complete while adding focused `test-unit` and xdist-backed `test-browser` targets.
- [x] Exclude browser execution from `test-cov` and upload coverage only from the non-browser job.
- [x] Run four-worker Python coverage, four-worker BrowserContracts, and ServerComposeFullStack as independent blocking jobs.
- [x] Keep Chromium installation, retained-on-failure tracing, duration reporting, and trace artifacts in BrowserContracts.
- [x] Audit browser contracts for fixed ports, shared databases/files, environment mutation, and artifact collisions.
- [x] Benchmark one, two, and four browser workers and repeat the chosen four-worker run for stability.

- [x] Keep task-table row geometry and the Actions toolbar stable through download preparation/checking states.
- [x] Preserve concise visible and complete accessible download progress.
- [x] Normalize `Task type`, `Submitted to`, and `Finished to` copy.
- [x] Keep RE controls as quiet, accessible pressed-state toggles with invalid-regex feedback.
- [x] Separate filter, view, and selection hierarchy without increasing panel height or breaking mobile wrapping.
- [x] Make zero-selection bulk delete semantically disabled and visually dormant.

### Runner Access

- [x] Make the empty pending-request state compact and populated state content-driven.
- [x] Present each restricted policy once as a compact responsive summary with counts and a normal Manage action.
- [x] Trace configured policy registry through API projection and frontend rendering; fix duplication at its source if real.
- [x] Apply intentional reusable normal/visited/hover/focus link styling.
- [x] Replace repetitive activity cards with a dense accessible time/user/policy-or-Runner/outcome feed.

### Landing and API Docs

- [x] Place the agent entry in the desktop hero's lower-right Grid/Flex region and return it to stacked flow on tablet/phone.
- [x] Restructure the existing agent entry into a technical heading, short description, and dominant full-width absolute-URL/copy row.
- [x] Add a restrained decorative terminal cue, explicit Copy label, stable live feedback, and responsive overflow/stacking coverage.
- [x] Preserve the existing hero placement/height, evidence composition, palette, typography, and `/skills.md` behavior.
- [x] Preserve hero content, CTA usability, and overflow-free layouts at all seven required viewports.
- [x] Add Swagger-root-scoped dark-theme coverage for operations, text, controls, tables, schemas, links, buttons, and code/request/response surfaces.
- [x] Preserve Swagger light mode and live application-theme switching without rebuilding Swagger.

### Regression and delivery gates

- [x] Run focused restart, TaskType/seed, static, and Playwright tests.
- [x] Run `make test`, `make test-cov`, Compose render, JavaScript/shell syntax, docs/package checks as applicable, and `git diff --check`.
- [x] Re-review the local final candidate for P1/P2 issues across restart and preserved frontend surfaces.

- [x] Add focused browser coverage for Dashboard transient geometry and dormant bulk delete.
- [x] Add focused browser coverage for compact/populated Runner Access states, one-policy/one-row, dense activity, long labels, and phone overflow.
- [x] Add focused browser coverage for landing placement at 1920, 1440, 1366, 1024, 834, 430, and 390 widths.
- [x] Add focused structural/computed-style browser coverage for Swagger light/dark readability and live switching.
- [x] Preserve existing responsive, dialog, Dashboard, and result-workspace tests.
- [x] Run focused browser tests, JavaScript/static checks, `make test`, `make test-cov`, strict docs, package, and Compose gates applicable to the final diff.
- [ ] Reconcile `TODO.md` and this file, inspect final diff/changed files, commit, push, open one PR, and confirm CI.
- [x] Do not request or trigger bot review.

## Progress log

### 2026-09-13 — restart-safety follow-up initialization

- Read the replacement `TODO.md`, repository guidance, long-task protocol, frontend-design skill, current restart controller, Compose mounts, runtime config, sweep helper, Dashboard renderer/CSS, and existing focused tests.
- Confirmed the skew mechanism: plan construction calls `materialize_runner_families()` before `cmd_down()`; that overwrites the live `${SERVER_DIR}/docker/runners` snapshot before the old worker executes its pre-stop sweep.
- Confirmed Compose does not mount `RUNNER_SOURCE_ROOT` into services. Runtime discovery defaults to `${SERVER_DIR}/docker/runners`; the lifecycle mutation, not the runtime default, violates immutability.
- Confirmed the Compact regression is the class-history selector `.actions > :not(.details):not(.results)`, while rendered controls already expose semantic `data-action` values.
- Added production-review follow-ups for Dashboard control geometry and Runner Access Manage behavior without reopening either surface's broader design.
- Confirmed Runner Access Manage has one obsolete inline renderer and already uses reusable summary/activity/mutation helpers plus the shared dialog system elsewhere.
- Added the landing agent-entry hierarchy refinement; the established lower-right hero placement remains the layout contract.
- Confirmed the Runner catalog production bug: author `display: flex/grid` rules override the browser's low-specificity hidden presentation, while existing tests only count attributes.
- Audited frontend hidden-state uses; all use `hidden` as semantic removal, and Create Task/Results already carry local important rules, so a base-level contract is appropriate.
- Added the progressive agent API projection and documentation-ownership requirements; both retain TaskType/task.yaml as the single scientific source of truth.

### 2026-09-13 — initialization

- Read the user objective, repository guidance, long-task protocol, Ponytail guidance, and complete `TODO.md`.
- Fetched `origin`, confirmed PR #12 merged into `main` as `745d03b`, and created `fix/frontend-state-hardening` from that exact head.
- Confirmed the only initial worktree change is the user-provided replacement `TODO.md`; it is retained as this follow-up's design truth.

### 2026-09-13 — implementation and verification

- Stabilized Dashboard action geometry with concise accessible progress, bounded single-row controls, explicit Results/Download/Delete hierarchy, grouped filter/view/selection controls, normalized copy, quiet RE state, and dormant zero-selection delete.
- Traced policies from strict unique-ID registration through the one-entry-per-policy API projection and one-pass frontend renderer; no source duplication exists, so no JavaScript deduplication was added.
- Compressed pending, policy, and activity states into responsive access rows; activity now exposes time, user, server-backed policy label, and outcome while preserving the API limit.
- Moved the existing agent entry into the hero's right-side Grid area on desktop and stacked it after evidence on tablet/phone without increasing the desktop first-fold height.
- Replaced Swagger's light island with root-scoped dark rules covering expanded operations, copy, fields, placeholders, buttons, response/schema tables, links, icons, and code/request/response surfaces.
- Added computed-geometry/style browser assertions for every requested regression; the frontend-design guidance kept the existing evidence composition as the sole expressive element and removed repetitive card/pill treatments elsewhere.
- Removed external font loading from the isolated Runner Access browser harness after it caused a non-product `Page.set_content` timeout in the first full run.

### 2026-09-13 — CI partition and browser parallelism

- Classified all 32 Playwright contracts with the registered `browser` marker; the complementary selection contains 941 tests, so no test is omitted by the two CI selectors.
- Split coverage and BrowserContracts into independent jobs alongside the existing Compose full-stack gate. Coverage no longer installs Chromium or traces browser execution.
- Audited the browser modules: they use per-test Playwright pages and mocked routes/static injection, with no fixed ports, external server processes, shared databases, or fixed output files. Pytest Playwright derives artifact paths from each test node ID.
- Added `pytest-xdist` and kept local browser execution at two workers while explicitly assigning four workers in GitHub Actions.
- Reduced the landing viewport contract from seven repeated document loads to one document with seven responsive reflows, preserving every viewport and assertion. Its call duration fell from about 35 seconds to about 6 seconds.
- Browser benchmarks: one worker 56.53 seconds wall, two workers 32.04 seconds wall, four workers 25.54 seconds wall. Two repeated four-worker runs passed in 27.06 and 27.13 pytest seconds.
- The serial non-browser coverage selection passed 936 tests with 4 skipped. This Python 3.11 host took 22m24s wall, dominated by three coverage-instrumented restart subprocess tests, which prompted a separate non-browser isolation audit.
- Audited non-browser isolation after the initial serial result: worker-local temp roots contain application databases and Runner copies, environment/module mutations are process-local, and the only live Redis test requests an ephemeral port. Four-worker non-coverage and coverage runs both passed all 936 selected tests.
- Four-worker non-browser execution took 213.39 seconds wall; four-worker coverage took 493.66 seconds wall and produced one combined XML report, a 63% improvement over serial coverage on this host. GitHub Actions uses four workers while local Make targets remain serial unless explicitly overridden.
- Final P1/P2 review found and fixed the `--keep-gateway` abort edge: a failed pre-stop sweep now lifts maintenance and leaves the old stack serving, while failures after shutdown retain maintenance. The complete restart-controller file passes 59 tests.

## Verification

- Focused hardening and preserved-browser gate: 120 passed; final focused accessibility/contrast gate: 84 passed.
- Final complete `make test`: 968 passed, 4 skipped, 3 established warnings in 687.34 seconds.
- Partitioned `make test-cov` before the final maintenance regression test: 936 passed, 4 skipped, 32 deselected, 3 established warnings; coverage XML generated. Final selection is 941 non-browser tests and 32 browser tests.
- BrowserContracts selection: 32 passed under four xdist workers in three consecutive runs; fastest measured wall time 25.54 seconds.
- `node --check` for changed JavaScript and `git diff --check`: pass.
- `python -m mkdocs build --strict`: pass (existing unnavlisted-page notice only).
- Base and SLURM-overlay `docker compose config --quiet`: pass with safe placeholder values.
- Wheel build and inspection: all nine changed packaged frontend assets are present.
- Landing acceptance covers 1920×1080, 1440×900, 1366×768, 1024×1366, 834×1194, 430×932, and 390×844 with no overflow or overlap; desktop hero remains within the first fold.

## Known failures or blockers

- None. Push, PR creation, and CI confirmation are the remaining delivery actions.

## Scope boundaries

- Preserve existing frontend architecture, entitlement semantics, Swagger/OpenAPI renderer, task schemas, layouts, dialogs, and result workspace.
- No unrelated backend, scheduler, Runner, SLURM, or API redesign.
- No bot review request or trigger.
