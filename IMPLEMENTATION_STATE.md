# Frontend Scalability Implementation State

Design source: `TODO.md`

## Current phase

Complete — implementation and acceptance verification finished.

Next action: none; the branch is ready for review as one frontend-scalability PR.

## Visual design plan

### Tokens

- Mineral canvas `#eef2ed`, paper `#f8faf7`, research ink `#1d2a2f`, evidence teal `#0f4f63`, process green `#0d6e66`, and caution ochre `#b06c14`.
- IBM Plex Sans remains the operational/data face; Source Serif 4 remains limited to narrative and major headings. Body lines stay below roughly 80 characters.
- One spacing scale and three content widths: reading (`44rem`), application (`75rem`), and wide scientific workspace (`90rem`).

### Layout concept

REvoCompute should read like a calm research bench: discovery controls are always visible at the top, dense evidence occupies the center, and secondary metadata progressively discloses at the edge or in an overlay.

```text
desktop: [context / title] [primary controls]
         [search + filters + view mode        ]
         [catalog / task / scientific workspace]

tablet:  [context / title]
         [search + wrapped controls]
         [two-column or master/detail content]

phone:   [context / title]
         [full-width search]
         [scroll-safe segmented controls]
         [single-column rows; details in dialog]
```

Content and controls are left-aligned; only the landing hero's evidence composition may use centered alignment. The memorable element is the structure/evolution/computation evidence map. Operational pages stay quiet and data-led.

### Brief review and revision

The first-pass existing visual language leaned on generic gradient washes, repeated rounded cards, pill controls, and shadows. The redesign keeps the established scientific palette and typefaces but flattens decoration, uses borders only to encode grouping/state, limits shadows to overlays, and reserves large whitespace for landing-page hierarchy. This makes the system specific to scientific catalog browsing rather than a reusable SaaS card kit.

## Completion checklist

### Shared interaction system

- [x] Add shared responsive containers/layout rules for desktop, tablet, and phone without clipped or horizontally scrolling content.
- [x] Add accessible shared buttons, status chips, empty states, metadata rows, search/filter toolbars, and segmented controls.
- [x] Add safe versioned browser preferences with `comfortable` catalog and `detailed` Dashboard defaults.
- [x] Add one Promise-based accessible `<dialog>` system for alerts, confirmations, and detail overlays, including blur fallback, Escape handling, focus restoration, and double-submit protection.
- [x] Remove application use of native `confirm`, `alert`, and `prompt`.
- [x] Preserve light/dark themes, keyboard focus, touch targets, reduced motion, and asynchronous status announcements.

### Page migrations

- [x] Recompose the landing page into responsive visual chapters and move the `/skills.md` entry below the complete hero.
- [x] Give the Runner catalog visible multi-field search and persisted Comfortable/Compact density views.
- [x] Give Create Task the same catalog discovery and density interaction, using the shared preference.
- [x] Hide artifact-reuse submission controls without removing backend provenance architecture or submitting stale hidden values.
- [x] Replace the Create Task `Change method` exception with the shared button system.
- [x] Add a declaratively identified seed control that preserves optional, required, ranged, and zero-sentinel Runner semantics.
- [x] Add persisted Detailed/Compact/Table Dashboard modes and a shared large detail overlay.
- [x] Add composable Dashboard TaskType/status/name/admin-username/date filters, plain/regex text modes with validation, and submission/finish sorting.
- [x] Redesign Profile Runner Access as policy-grouped entitlement/licence verification with clear states, expiry, and request actions.
- [x] Redesign User Management as responsive master/detail with distinct batch actions and search/filter.
- [x] Redesign Runner Access administration around pending eligibility decisions, policy context, evidence, and activity.
- [x] Re-layout Add User into responsive credentials, research identity, and role/access groups.
- [x] Move Terms prose to one repository-controlled Markdown source rendered by a maintained parser.
- [x] Explain service terms versus authoritative upstream Runner licences and the why/what/who/how access workflow.
- [x] Redesign Configuration Task Types for searchable, compact large-registry browsing while preserving enable/disable semantics.
- [x] Fix the Principal Result Mol* empty region at its DOM/layout source.
- [x] Show pLDDT controls only from declared `confidence_encoding`, covering PDB and mmCIF.
- [x] Remove Review Shortlist from templates, JavaScript, CSS, exports, tests, and documentation while preserving generic scientific selection.

### Architecture and regressions

- [x] Keep Runner execution and parameter semantics in owning `task.yaml` declarations and entrypoints; add only a typed, validated reusable presentation hint if needed.
- [x] Keep Runner entitlements independent from account roles and do not imply administrators can waive upstream licences.
- [x] Use existing APIs/registry metadata; document and test any genuine reusable contract extension.
- [x] Fix the `Undefined user` data path and use the deterministic full-name → username → email → stable-ID label chain.
- [x] Add/update browser contract and Playwright coverage for every interaction listed in TODO section 23.
- [x] Validate representative desktop, tablet, and phone viewports without relying only on screenshots.
- [x] Audit for legacy native dialogs, shortlist remnants, TaskType-specific frontend branches, duplicated Terms, and format-inferred pLDDT.
- [x] Run focused Python/browser tests, relevant Playwright suites, `make test`, and `make test-cov`.
- [x] Update this file with final architecture, migration, verification, failures, and intentional debt; leave no required unchecked items.

## Progress log

### 2026-09-12 — initialization

- Started `feat/frontend-scalability` from `main` / `origin/main` at `3c6a723` after fetching the merged PR.
- Read `TODO.md`, `LONG_TASK_HANDLING.md`, repository guidance, and the Ponytail implementation guidance.
- Installed and read the user-requested `frontend-design` skill, then recorded and critiqued the visual plan above before product edits.
- Inventoried the shared base, affected templates/styles/scripts, API catalog payload, parameter renderer, native dialogs, shortlist references, Terms route, and representative seed declarations.
- Found the seed UI has a clean generic extension point: typed `TaskParam` presentation metadata serialized by the existing TaskType API and consumed by the shared parameter renderer.
- Found the Mol* spacer root-cause candidate: `task-results.js` creates and appends a second persistent `.artifact-preview-stage` beside the canonical preview stage.

### 2026-09-12 — implementation and focused verification

- Added the shared `ui.js` preference, segmented-control, dialog, confirmation, alert, prompt, and detail-overlay layer plus responsive CSS primitives.
- Migrated the landing page, Runner/Create Task catalogs, Dashboard, Profile, User Control, Terms, Configuration, and scientific result workspace.
- Added and validated the typed `x-ui-control: seed` schema hint across scalar Runner seeds without changing defaults, omission, ranges, or zero-sentinel semantics.
- Projected completion timestamps and task-declared structure `confidence_encoding` through existing API payloads.
- Removed the Review Shortlist product code and reclaimed the result workspace while preserving candidate/entity interaction.
- Fixed the Mol* spacer at its source by keeping the warm iframe in the canonical preview surface and disposing stale warm state when the shared preview host clears it.
- Fixed dialog Playwright tests that accidentally awaited unresolved UI Promises, and added prompt initial-focus coverage.
- Added a stable Markdown Terms anchor and projected policy restrictions, licence metadata, decision evidence, and prior grant history into the existing admin access workflow.
- Architecture searches found no application-native dialogs, shortlist implementation remnants, TaskType-specific JavaScript branches, duplicated Terms prose, or format-inferred pLDDT behavior.

### 2026-09-13 — single automated review pass

- Opened PR #12 and used its one automatic Codex review; no additional review was requested.
- Batched all three valid findings into one Dashboard correction: table rows retain polling metadata and cancel/delete actions, and compact detail clones bind the shared lazy structure-preview loader.
- Added regression coverage for table polling/actions and structure loading inside the detail dialog.

## Verification

- Focused Python/browser contract gate: 157 passed before two test-contract corrections; the corrected subsets pass.
- JavaScript plugin/viewer contract scripts: 57 passed.
- Shared UI Playwright: 4 passed.
- Scalability and nine-viewport Playwright: 5 passed.
- Runner access Playwright: 3 passed.
- Scientific result Playwright: 8 passed, including PDB/mmCIF pLDDT metadata presence and absence.
- Workspace Playwright passed as part of the affected-suite run.
- `git diff --check`, Python compilation, and changed JavaScript syntax checks pass.
- `make test`: 956 passed, 4 skipped, 3 pre-existing warnings.
- `make test-cov`: 956 passed, 4 skipped, 3 pre-existing warnings; 82% total coverage.
- Process-isolation coverage subset after allowing for instrumentation overhead: 27 passed.
- Base and SLURM-overlay `docker compose config --quiet` renders pass with safe example values.
- `python -m mkdocs build --strict`: pass.
- Built-wheel inspection confirms `legal/TERMS_OF_SERVICE.md`, `ui.js`, the Terms template, and the `Markdown>=3.7,<4` dependency are packaged.
- Post-review focused verification: 5 scalability Playwright tests and 9 Dashboard/Create Task server tests pass.

## Known failures or blockers

None.

## Final architecture and migration

- `static/js/ui.js` owns guarded presentation preferences, segmented controls, and the Promise-based dialog/confirmation/prompt/detail-overlay lifecycle. Shared base CSS owns its responsive, focus, backdrop, reduced-motion, and fallback behavior.
- Runner and Create Task discovery consume the existing catalog API and one shared density preference. Dashboard composes local layout, search, structured filters, regex validation, and timestamp-backed sorting without changing task execution APIs.
- The only Runner parameter presentation extension is the validated integer `x-ui-control: seed` hint. The owning `task.yaml` still defines optionality, defaults, ranges, and zero sentinels, and the browser submits a concrete schema-valid value.
- Runner access remains policy-owned entitlement verification. User and administrator views consume existing policy, request, grant, and identity records; account roles do not confer Runner access and approval text does not claim to alter upstream licences.
- Terms prose now has one packaged Markdown source rendered on each request. The HTML template owns only page layout.
- Result manifests project task-declared `confidence_encoding`; the viewer never infers pLDDT from PDB/mmCIF format. The duplicate Mol* stage lifecycle was removed at its DOM source.
- Review Shortlist product UI, export handling, styling, and documentation were removed. Generic candidate/entity selection remains for linked scientific views.
- Landing, Runners, Create Task, Dashboard, Profile, all User Control scopes, Terms, Configuration Task Types, and Principal Result now use the shared responsive interaction system.

## Intentional scope boundaries

- Cross-task artifact-reference backend and provenance support remain intact, while the unfinished submission UI returns no references and is not rendered.
- No Runner execution, scheduler, SLURM resource, scientific parameter, or licence-permission semantics were changed.
- No target-cluster SLURM/Apptainer living run was required for this frontend and projection-only change; Compose rendering, full repository tests, real Mol* browser coverage, and packaging checks are the relevant delivery gates.
