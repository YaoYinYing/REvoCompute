# Frontend State Hardening Implementation State

Design source: `TODO.md`

## Current phase

Delivery preparation. Implementation and all required local gates are complete on `fix/frontend-state-hardening`, which starts from merged PR #12 at `745d03b`.

Next action: inspect the final diff, commit, push, open one PR, and confirm CI without requesting bot review.

## Visual design plan

- Color: retain mineral canvas `#eef2ed`, paper `#f8faf7`, research ink `#1d2a2f`, evidence teal `#0f4f63`, process green `#0d6e66`, and caution ochre `#b06c14` through existing tokens.
- Type: retain IBM Plex Sans for operational/data surfaces and Source Serif 4 only for established narrative headings.
- Layout: use compact horizontal toolbars and audit rows for operational pages; extend the existing landing two-column grid so the agent entry sits under the evidence column on desktop and spans normal flow below it on narrower screens.
- Principles: stable geometry, scan-first scientific data, restrained hierarchy, and no new card/pill vocabulary.
- Brief review: avoid the generic SaaS-card pattern by removing repetitive activity cards and the stretched Manage pill; preserve the evidence map as the sole expressive composition and keep every other changed surface quiet.

## Completion checklist

### Dashboard

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
- [x] Preserve hero content, CTA usability, and overflow-free layouts at all seven required viewports.
- [x] Add Swagger-root-scoped dark-theme coverage for operations, text, controls, tables, schemas, links, buttons, and code/request/response surfaces.
- [x] Preserve Swagger light mode and live application-theme switching without rebuilding Swagger.

### Regression and delivery gates

- [x] Add focused browser coverage for Dashboard transient geometry and dormant bulk delete.
- [x] Add focused browser coverage for compact/populated Runner Access states, one-policy/one-row, dense activity, long labels, and phone overflow.
- [x] Add focused browser coverage for landing placement at 1920, 1440, 1366, 1024, 834, 430, and 390 widths.
- [x] Add focused structural/computed-style browser coverage for Swagger light/dark readability and live switching.
- [x] Preserve existing responsive, dialog, Dashboard, and result-workspace tests.
- [x] Run focused browser tests, JavaScript/static checks, `make test`, `make test-cov`, strict docs, package, and Compose gates applicable to the final diff.
- [ ] Reconcile `TODO.md` and this file, inspect final diff/changed files, commit, push, open one PR, and confirm CI.
- [x] Do not request or trigger bot review.

## Progress log

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

## Verification

- Focused hardening and preserved-browser gate: 120 passed; final focused accessibility/contrast gate: 84 passed.
- `make test`: 963 passed, 4 skipped, 3 established warnings.
- `make test-cov`: 963 passed, 4 skipped, 3 established warnings; 82% total coverage.
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
