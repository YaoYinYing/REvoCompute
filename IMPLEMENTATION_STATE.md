# Frontend Runner Fixture Harness Implementation State

`TODO_FRONTEND_FIXTURE_HARNESS.md` is the design contract for this PR. This file
records execution state; the committed tests and the named commands are the
machine-verifiable record.

## Starting point

- Branch base: `0520fb1` (`feat(frontend): production UI polish (#36)`), the
  current `main`. The branch was originally opened on `87aeb191` (#35), rebased
  onto `a9ff463` (#39) and `c82ea79` (#37), and finally merged forward onto
  `0520fb1` (#36); it is level with `main`.
- Feature branch: `test/frontend-runner-fixture-harness`.
- Scope: frontend test infrastructure and browser acceptance only. No product
  code, Runner manifest, or validation identity changes.

### Adapting to the PR #36 single-action Create Task

PR #36 retired the two-step Review/Run Create Task flow in favour of one
`Run task` action that preflights and submits in a single step, and changed the
snapshot summary from a per-check count to an "N issues to fix" line. The merge
kept `main`'s rewritten `tests/test_playwright_application.py` verbatim and
adapted `tests/test_playwright_runner_fixtures.py` to the new flow:

- the harness cases drive `Run task` instead of the removed `Review`/`Run` pair,
  and read `.ct-validation-summary` rather than a "check failed" string;
- a non-blocking preflight finding is asserted while the workbench stays mounted
  (the submission request is held), because a *completed* preflight now
  navigates straight to the dashboard;
- the granted-access case enables the run only once the input is supplied, since
  the local validation gate is what disables the action there.

No fixture builder needed to change: `input_workspace`, the `review` capability
payload, and the projection shapes are unchanged by #36.

## Fixture harness architecture

`tests/frontend_fixtures/` serves the built production frontend bundle against
deterministic canonical API responses. The mocked boundary is the HTTP/API
projection; the frontend bundle, `revocompute/static/openapi.json`, and the
server loaders stay real. There is no production mock mode and no mock endpoint.

- `models.py` — immutable value objects (`InputRole`, `ParameterSpec`,
  `WorkspaceStep`/`WorkspaceCapability`, `PreflightInput`/`PreflightSpec`,
  `ResultArtifactSpec`, `AccessState`, `ReadinessState`, `LifecycleSpec`,
  `RunnerDefinition`, …).
- `builders.py` - canonical payload builders. Response bodies are validated
  against their OpenAPI component (`validate_payload`) before leaving the
  builder, so a fixture fails loudly when a production contract changes. A few
  small bodies the router hand-builds (access policies, archive/task actions)
  are outside that check.
- `scenarios.py` — immutable `RunnerScenario` plus the capability scenarios
  (`controlled_scenario`, `pssm_gremlin_scenario`, `structure_scenario`,
  `runner_scenario`). Lifecycle state is a pure function of the poll count.
- `router.py` — Playwright route installation, request capture, and semantic
  request helpers (`mount_scenario`). An undeclared endpoint is recorded and the
  route raises `UnexpectedRequest`, so it surfaces as a test failure.
- `auth.py`, `results.py` — authentication projections and the ResultManifest
  fixture library.

`tests/test_frontend_fixture_harness.py` covers the harness itself: canonical
vocabulary, schema validity, deterministic lifecycle, request capture, and
reference-scenario projection.

The harness is scoped to the Runner-facing surfaces. Auth/admin/profile browser
tests keep their own smaller in-file stubs in `tests/test_playwright_application.py`;
the harness carries no admin fixture surface, and the workspace-plugin asset
routes are exercised through the real RFdiffusion manifest projection rather
than a synthetic fixture.

## Migrated browser tests

The scattered endpoint plumbing in `tests/test_playwright_application.py` was
replaced by `mount_scenario(page, scenario)`. Runner-facing browser acceptance
now lives in two files, both driving the production bundle:

- `tests/test_playwright_application.py` — ordinary navigation → create → submit
  → finished journey plus auth, profile, admin, and public-route coverage.
- `tests/test_playwright_runner_fixtures.py` (new) — the states around the happy
  path that a real deployment produces and the harness now makes cheap:
  preflight rejection, preflight warning, Runner-not-ready, infrastructure
  readiness in the catalog, unavailable-infrastructure detail, create-task
  admission, catalog cardinality (1/few/many), failed lifecycle with
  diagnostics, restricted access pending/granted, narrow-screen workspace, a GPU
  structure Runner without weights or inference, and the PSSM-GREMLIN contract
  (whose scenario is transcribed from the real `gremlin_lh_fit` `task.yaml`).

Both files pass on the current commit, after the review fixes; the run results
are recorded under "Delivery commands and results". Two cases are documented
`xfail(strict=False)`: at 320px the Create Task protocol column and the result
header actions exceed the viewport width, so those two surfaces scroll
horizontally. The assertion is stated positively, so a layout fix flips them to
XPASS rather than failing on the fix.

## Representative real-manifest projection tests

`tests/server/test_runner_manifest_frontend_projection.py` proves the other
direction: real `task.yaml` manifests still project into the frontend contract
without execution. It loads an isolated application through
`conftest._load_pssm_module`, which discovers the real `docker/runners/` tree as
production does, then reads `/compute/api/types`, `/compute/api/types/<name>`,
and `/compute/api/task-parameters/<name>` and validates each response against
OpenAPI. Families are chosen for frontend grammar, not popularity:

| Runner | Grammar exercised |
| --- | --- |
| `colabfold_af2` | sequence input role, GPU flag, GPU workflow stage, parameter schema, multi-step workspace |
| `fpocket` | molecular-structure input role, structure-inspection capability, numeric bounds |
| `alphafold3` | GPU + restricted access (catalog and detail projections), parameter schema |
| `boltz_predict` | two input roles with an optional-cardinality range, multi-step workspace |
| `gremlin_lh_fit` | rich guidance prose, citations, parameter-rich schema |

No Runner is executed, enabled for deployment, or required to have an image,
weights, database, or GPU. A separate case disables a task type through
`manage_db` and asserts it leaves the catalog and both detail endpoints (404),
showing enablement is orthogonal to the manifest contract.

`pssm_gremlin_scenario()` in the fixture harness is transcribed field-for-field
from this family's `task.yaml` (identity, input role and formats, the three
workspace steps and their capability ids, all fourteen parameters, both
citations, and the result workspace). Two projection cases in this file pin that
fidelity mechanically against the loaded manifest: the fixture's view ids,
plugins, and roles must equal the real `result_workspace` (including
`raw_couplings` = primary and `apc_couplings` = evidence), and its input roles,
parameter names, and display name must match. A fixture that inverts the
manifest's primary/evidence relationship or drifts from its vocabulary now fails
instead of merely shrinking to a look-alike.

The harness also keeps result identity honest: `build_result_manifest` uses the
mounted Runner's name as the manifest `task_type` (so it never disagrees with
`run.method.id`), and the scenario's artifact/table/projection/logical-file
accessors are task-scoped, so a mismatched 32-hex task id resolves to nothing
(the router answers 404) rather than the mounted scenario's bytes.

## Scenario matrix (frontend capabilities)

- input: sequence editor, file upload, molecular-structure input, multiple
  files, parameters, review/snapshot.
- catalog cardinality: 1 / few / many.
- readiness: READY plus DEGRADED/STALE/UNAVAILABLE with per-group scheduler and
  GPU capacity.
- access: open, requestable, pending, granted, denied.
- preflight: valid, warning, invalid security, invalid contract,
  Runner-not-ready, infrastructure-not-ready, access denied, capacity busy, GPU
  credit exhausted.
- lifecycle: queued → running → finished, plus queued/running → failed.
- authentication: anonymous, user, admin, expired.

## ResultManifest fixture coverage

`tests/frontend_fixtures/results.py` registers one fixture per rendering class:
`minimal_success`, `text_log`, `table`, `matrix`, `alignment`, `structure`,
`multi_structure`, `metric_series`, `trajectory`, `large_download_only`,
`nested_tree`, `partial`, `failed_diagnostics`, `archive_pending`,
`archive_ready`, `storyboard`. `test_frontend_fixture_harness.py` asserts the
whole set validates and uses only declared view/artifact vocabulary.

## Delivery commands and results

- `pytest tests/server/test_runner_manifest_frontend_projection.py -q` → 11 passed.
- `pytest tests/test_frontend_fixture_harness.py -q` → 20 passed.
- `pytest tests/test_frontend_fixture_harness.py tests/server/test_runner_manifest_frontend_projection.py tests/server/test_application_frontend_contract.py tests/server/test_gremlin_lh_result_views.py -q`
  → 40 passed.
- `mkdocs build --strict` → built clean (run from a temporary uv environment
  installing `mkdocs>=1.6,<2` and `mkdocs-material>=9,<10`, per
  `docs/developer-guide/documentation.md`; the repository venv does not carry
  the docs toolchain).
- `pytest tests -m "browser and not molstar_csp" -n 4 --dist=load -q`
  → 120 passed, 1 skipped, 2 xfailed, run against the built bundle on this HEAD.
- `pytest tests -m "not browser" -n 4 --dist=load -q`
  → 1559 passed, 23 skipped. (An earlier run of this gate reported spurious
  errors because the shared `/tmp` tmpfs had exhausted its inode table; after
  clearing the accumulated `pytest-of-*` run directories the suite is clean.)

## Known deferred cases

- Unsupported surface: the harness is Runner-facing only. Auth/admin/profile
  browser tests keep their own in-file stubs, and the workspace-plugin asset
  routes are exercised through the real RFdiffusion manifest projection rather
  than a synthetic fixture.
- `docker/runners/boltz/tasks/boltz_predict/task.yaml` `considerations[0]` is an
  unquoted YAML scalar whose continuation line begins with `msa: `, so the loader
  parses it as a single-key mapping and `/compute/api/types/boltz_predict`
  projects a non-string where `TaskTypeDetail.considerations` requires a string
  (the detail page then renders `[object Object]`). This is a pre-existing,
  user-visible manifest defect present on the base commit, independent of
  validation identity (`considerations` is not part of `configuration_digest`).
  The projection test for `boltz_predict` therefore reads its raw detail without
  the `TaskTypeDetail` schema check that every other family passes; fixing the
  manifest is out of scope for a test-infrastructure PR and is left as a follow-up.

## Live-validation identity

This PR changes only `tests/` and `docs/`. `git diff --stat origin/main...HEAD`
lists no Runner manifest, no `run/revocompute_ctl/live_test.py`, and no
production module, so `configuration_digest` and every Runner's validation
identity are unchanged. No live-test receipt is created, stale, or rewritten by
the fixture architecture.

---

# Cared-for Precision Refinement (PR #56)

`TODO.md` is the design contract; `docs/developer-guide/frontend-design-language.md`
is the single canonical source of the durable visual rules. This section records
execution state for the post-Soft-Precision taste refinement.

## Starting point

- Observed `main`: `e64077589ff6c3583bb4b27b528daa2b1551abce`.
- Feature branch: `design/cared-for-precision-refinement`; worktree
  `/home/yinying/repo/.rc-worktrees/cared-for-precision-refinement`.
- Scope: frontend presentation and the design documentation set only. No
  behavior, DOM contract, i18n, Result contract, server ownership, auth, or
  validation-identity change.

## Rendered baseline (§5) — where the UI felt generic

The pre-pass bundle was competent but **undersaturated and soft-generic**: a
cool blue-grey field, a shadowless flat result preview, and a gradient structure
toolbar. The correct structure (hairline stat strip rather than floating cards,
text-only status with a shape cue, tinted result stage, editorial runner
heading) was already in place and was retained.

## What the refinement changed

- **Environmental neutral (§6, §7)** — the light canvas moved from a sterile
  blue-grey to a sub-threshold warm grey-green (`--app-bg`, `--app-surface`,
  `--app-stage`, `--app-line`, `--app-ink`). The bias stays below a visible cast;
  REvo blue remains ink (action/selection/focus/links only, §5.2) and the
  scientific content stays the richest colour.
- **Elevation as depth, not polish (§6.2)** — `--shadow-surface` gained a
  restrained ground shadow so work surfaces read as laid on the bench rather
  than floating; most surfaces still stand on border + tone.
- **Scientific stage (§10/§18)** — `.result-preview` lost its border and is now
  defined by tone plus ground shadow; `.structure-viewport` moved its border to
  `var(--result-line)`; the structure toolbar is a flat `var(--result-surface)`
  with a hairline (chrome above the science), replacing a gradient.
- **Create Task (§12)** — `.ct-primary` elevation is derived from the accent via
  `color-mix()` instead of a hardcoded teal literal.

## Documentation consolidation

`frontend-design-language.md` now declares itself the single canonical rule
source. `frontend-art-direction.md` keeps only the judgment layer (emotional
target, wild-rose metaphor, laboratory-not-industrial character, Monet as
relational art direction, authorship, composition over decoration) and cites the
rule sections; `frontend-taste-review.md` is a review instrument (ordered
questions, each pointing at its governing rule) plus the fast rubric;
`frontend-visual-ancestry.md` is the historical-evidence record that cites the
current rules rather than re-deriving them from the 2026 palette.

## §27 subtraction pass

Removed dead CSS with no rendered consumer (verified repo-wide, excluding built
`dist/`): the unused `--space-*` scale (the single `var(--space-4)` use inlined),
the unused `.tnum` utility, the unrendered `.list-heading` rules (with
`.catalog-count` folded into the aligned toolbar as a tabular machine fact), and
the dead `.dashboard-controls` selector. No second visual system remains.

## Delivery commands and results

- `cd frontend && npm run typecheck && npm run test && npm run build` ->
  typecheck clean; 19 test files / 88 tests passed; build runs verify:lock,
  verify:provenance, check:api-types, verify:build.
- `pytest tests/test_playwright_soft_precision.py -q` -> 18 passed (the Soft
  Precision contract matrix: rail, mobile nav, i18n, notices, guided tour,
  advanced-search subordination, view-switch independence, text-only status, WCAG
  light+dark, touch targets, reduced motion).
- `pytest tests/test_playwright_application.py -q` -> 38 passed.
- `pytest tests/test_playwright_results.py -q` -> 18 passed.
- `mkdocs build --strict` -> clean (docs toolchain via `uv run --with`; the
  repository venv does not carry it).

## Review evidence

A bounded after-storyboard (10 surfaces: Dashboard desktop light/dark and
mobile, structure Result, Runner catalog, Runner detail, Create Task,
Admin/User Control, Profile, login) was rendered from the production bundle
through the real fixture harness. It is review evidence, not a pixel-golden
corpus; no screenshot-diff test was added.

## Reopened strength pass (composition over token tuning)

The first delivery was judged technically sound but too subtle. This pass raises
strength of authorship by composition, not tokens: a page opens on one
editorial-scale masthead set off by a rule, and identity → primary content →
controls → metadata descend in weight instead of reading as equal bands. Commit
`3527b61`; the §27 subtraction followed in a second commit.

Changed surfaces (composition only; no behaviour, DOM, i18n, contract, or
a11y change):

- **Shell / page frames** — taller page padding; `.page-heading`,
  `.runner-detail-heading` and `route-error` h1 at editorial scale with a
  tighter display tracking; runner-group and detail-section gutters widened to a
  16rem index column with a 2px spine rule so a category/section reads as an
  authored divider, not a caption. Dashboard stat figures scaled to 2.5rem; the
  attention figure stays the only locally-weighted one.
- **Create Task** — method groups are ruled chapters; the protocol reads as
  numbered stages on a measured gutter; the snapshot panel scales its method
  identity. No parameter/validation/one-click-submit change.
- **Result** — the result's own identity is now the loudest text in the
  workspace; the scientific stage opens taller. The structure toolbar comment
  was moved onto the rule it explains (subtraction).
- **Admin** — the toolbar is a bordered instrument panel (dense but framed), the
  table header carries a 2px rule, the stat strip figures scale. Density kept.
- **Profile / auth** — relaxed page rhythm and scaled section headings.

Rendered judgment was made against the deployed baseline
(`cp-after` vs the after-set) on Dashboard, Runner catalog/detail, Create Task,
a structure Result, Admin/User Control, Profile and login, in both themes and at
desktop plus tablet/mobile widths. The strengthened composition reads as
intended rather than as decoration: hierarchy is carried by scale, gutter and
rule, not by added ornament; soft-surface/border-vs-tone decisions are
unchanged.

§27 subtraction applied in this pass: removed a non-composition dashboard
stat-label tracking that changed no rhythm, and relocated the misplaced
structure-toolbar rationale comment. Net change is composition-only.

Re-ran at the delivered head: `npm run typecheck` clean, `npm run test` 19 files
/ 88 tests passed, `npm run build` (verify:lock, verify:provenance,
check:api-types, vite build, verify:build) clean; browser gates
(`test_playwright_soft_precision`, `test_playwright_application`,
`test_playwright_runner_fixtures`, `test_playwright_results`) 96 passed /
2 xfailed; Molstar CSP case 2 skipped as designed; `mkdocs build --strict`
clean.

---

# Administration information-architecture correction (PR #56)

A deployed-UI review found one information-architecture defect: User control,
Server logs, and Configuration are persistent page-level workspaces, but they
were reachable only through a `details` menu in the top-right chrome — a hidden
launcher for three destinations, while the top bar is defined as global chrome
(`frontend-design-language.md` §10).

## Decision

The left navigation now states the product's architecture as three regions
(§9.2): **Compute** (Runners, Dashboard), **Account** (Profile), and
**Administration** (User control, Server logs, Configuration). Each region is a
quiet label over its destinations, separated by a hairline and space; there is
no Admin card, no second icon system, and no added visual weight — Discoverability
comes from position and grouping, not from ornament.

- The top-right `Administration` dropdown is **removed** (script and its CSS); the
  top bar returns to global chrome only (language, notices, account, theme,
  logout). There is no second hidden Administration launcher.
- Region membership is **authorization, not visual hiding**: `shell.setUser`
  renders the Administration region only when the server projects the session as
  an administrator. Anonymous and ordinary-user navigation gain no forbidden link.
- Profile's local section nav (Account/Security/API key/Runner access/GPU
  credits/Metrics) is a *different navigation level* and is untouched; the new
  region is deliberately not appended there, and a test asserts the global nav
  carries no profile section tabs.
- Extension: a region accepts destinations as their routes exist; no speculative
  Fleet/Reports entries were added.
- Responsive: above the bottom-bar band the rail is a column; a collapsed icon rail
  keeps the inter-region rule and drops the word, and expanding the rail paints each
  region name. On the bottom bar the Compute and Account destinations sit directly on
  the bar (their wrappers dissolve; only those two headings take the 1px sr-only form)
  and the current destination still marks itself there; a repeat activation navigates
  instead of toggling a rail that has no column form.
- Administration on mobile is a deliberate **bounded secondary surface just above the
  bar** — one row of three destinations under its own painted "Administration" heading
  (the sr-only rule is deliberately not applied to this group, since the heading is
  what names the surface), cleared by the outlet padding — rather than three items
  crowding the primary bar. Verified as painting real pixels, not a clipped sliver:
  at 320/360/390px the heading's box is 320-390 x 24.45px, `position: static`,
  `clip: auto`, it is the topmost element at its own centre, and a screenshot with the
  heading differs from the same page with the sr-only rule re-applied.
  It is absent for anyone not authorized, so ordinary and anonymous mobile navigation
  are unchanged.
- One behaviour change with the same change set: the Account (Profile) destination
  now follows session state like the top-bar profile affordance, so anonymous
  navigation offers the sign-in route (`/compute/login?return_to=…`) rather than a
  protected `/compute/profile` link.

## Tests updated (not screenshots)

- `tests/test_playwright_soft_precision.py` — region labelling and the
  ordinary-user/administrator visibility split, the mobile bar carrying
  destinations without region headings, the administrator's bounded mobile
  Administration surface above the bar (its heading asserted to have a non-zero
  painted box and to be the topmost element at its centre, so a clipped sr-only
  sliver fails the test), the ordinary user having no such surface, and the
  expanded desktop rail painting the region labels.
- `tests/test_playwright_application.py` — the admin dashboard case now asserts the
  left-nav destination instead of opening a removed dropdown; the responsive admin
  case asserts the current-page marker and that Profile's local tabs stay out of
  the global nav; a new case asserts anonymous navigation carries no Administration
  link or launcher at 320px and 1280px.

## Delivery commands and results

- `cd frontend && npm run typecheck && npm run test && npm run build` — typecheck
  clean; 19 files / 88 tests passed; build (verify:lock, verify:provenance,
  check:api-types, vite build, verify:build) clean.
- `pytest tests -m "browser and not molstar_csp" -n 4 --dist=load -q` — 171 passed,
  1 skipped, 2 xfailed.
- `pytest tests -m "not browser" -n 4 --dist=load -q` — clean (run with `--basetemp`
  on the repository filesystem; see the `/tmp` tmpfs note above).
- `mkdocs build --strict` — clean.

## Rendered evidence

Storyboard rendered from the production bundle through the real fixture harness at
the pre-change and post-change heads: desktop (1280) Administrator rail showing the
three regions with the Administration destination marked current, ordinary-user
desktop rail showing Compute + Account and no Administration region, anonymous rail
at 1280/320, the collapsed and expanded tablet rail at 1024, and the mobile bar at
360 in both the administrator state (primary bar plus the bounded Administration
surface above it) and the ordinary-user state (primary bar only). Review evidence
only; no screenshot-diff test.

---

# Soft Precision Visual System (PR #54)

This section records execution state for the Soft Precision visual pass.
`TODO.md` is the design contract; `docs/developer-guide/frontend-design-language.md`
is the durable visual contract. The committed tests and the named commands are
the machine-verifiable record.

## Starting point

- Observed `main`: `2cedb3f55b89e1738cb67691e72a478f74318be3`.
- Feature branch: `design/soft-precision-visual-system`; PR-scoped worktree
  `campaign/pr54-soft-precision-visual`.
- Scope: frontend presentation, one small server-owned notice projection, and
  their tests. No Runner behavior, task-parameter semantics, ResultManifest
  semantics, scheduler behavior, or validation identity changes.

## What Soft Precision changed

- **Foundation** (`frontend/src/styles/app.css`, `frontend/src/features/*/*.css`):
  neutral canvas with a hairline cool bias (no visible blue/teal field); a
  role-based radius scale (`--r-util`/`--r-control`/`--r-surface`/`--r-surface-lg`),
  with pill geometry reserved for status/tags; elevation reduced to
  surface/raised/dialog so ordinary surfaces stand on border + tone, not shadow;
  a separately calibrated dark palette with no green cast; hairline (1px) status
  boundaries replacing the former 3px decorative rails; soft focus ring.
- **Shell** (`frontend/src/app/shell.ts`): a desktop icon rail that expands on
  demand. Repeated activation of the *current* navigation item toggles the rail;
  there is no separate collapse button. The rail preference persists in
  `localStorage`. The top bar is global chrome only (language, notices, theme,
  account, administration) plus one primary page action. Mobile keeps a distinct
  bottom navigation.
- **i18n** (`frontend/src/app/i18n.ts`): one localization layer for
  frontend-owned copy (`en`, `zh-CN`), persisted choice, browser-locale initial
  preference, deterministic English fallback, `document.documentElement.lang`
  updates, and `{param}` interpolation. Server-owned Runner/task vocabulary and
  result-renderer wording are deliberately excluded from the catalogs.
- **Persistent system notices** (`frontend/src/app/system-notices.ts` +
  `revocompute/routes.py` `GET /compute/api/system/notices`): operator-configured,
  repository-owned (`revocompute/legal/SYSTEM_NOTICES.md`), content-addressed
  notices rendered as text; bounded scrollable body; hide by stable identity;
  reopen from the global affordance. Distinct from the transient toast surface.
- **Guided tour** (`frontend/src/app/guided-tour.ts`): a route-aware,
  keyboard-accessible, restartable five-step path through the product model
  (Runner → input → Task → lifecycle → result → provenance) on the Dashboard.
- **Dashboard** (`frontend/src/features/dashboard/index.ts`): preserved
  information architecture (page identity → task overview → search/filter →
  task collection). One aligned filter band with an `Advanced search` disclosure
  for low-frequency fields; the regex control moved out of the search field into
  that panel. A view switch (Detailed/Compact/Table) in its own group, separate
  from filtering. Task cards read name → type → status → machine facts → actions,
  with no status rail, machine-text treatment for the task ID only, tabular
  numerals for dates/durations, and a graded action hierarchy.
- **Propagation**: Runner catalog (registry-like compact mode, no hover-lift,
  no pastel icon tiles), Create Task (no hover-lift; parameter/validation
  hierarchy unchanged), Result workspace (shared tokens and softer controls; no
  renderer or ResultManifest change), Admin/Profile/Auth/Public (shared grammar,
  contextual density preserved).

## Server-owned contract change

- New anonymous endpoint `GET /compute/api/system/notices` returning
  `SystemNotices { notices: [{id, level, title, body}] }`, sourced from
  `revocompute/legal/SYSTEM_NOTICES.md` (bounded, content-addressed). The shipped
  source is comment-only, so a fresh deployment announces nothing.
- `revocompute/static/openapi.json` gains the path + schema;
  `frontend/src/api/schema.generated.ts` is **regenerated** via
  `npm run generate:api-types` (not hand-edited) and `npm run check:api-types`
  passes.

## Final-integration items

- **#47 (`revocompute/static/openapi.json` + generated client)**: both branches
  edit `openapi.json` and regenerate `schema.generated.ts`. At reconciliation,
  merge `main` **after** #47 lands and regenerate `schema.generated.ts` from the
  combined document, then re-run `npm run check:api-types`. Do not hand-merge the
  generated TS.
- **#46 (result-contract audit)**: this pass is presentation-only for the Result
  workspace. No ResultManifest, replay, fixture-ownership, or renderer semantics
  were changed; no competing result abstraction was introduced.

## Propagation rendered-state checkpoint

At head `6f99e14f7c26190bae9a1ce9b1977c71bf2c5fd5`, propagation was verified in the
real built bundle across all six surfaces in both themes (Runner catalog, Create
Task, Result workspace, Admin/User control, Profile, public/login auth shell) via
a temporary screenshot harness that was deleted before this checkpoint. All
surfaces render the shared grammar (neutral canvas, REvo blue accent ink,
tokenized warning/success, machine-text IDs, hairline status boundaries with no
decorative rails). Result remained presentation-only. The worktree is clean of
strays at this head.

## Delivery commands and results

- `cd frontend && npm ci && npm run typecheck && npm run test && npm run build`
  -> 19 test files / 87 tests passed; build runs verify:lock, verify:provenance,
  check:api-types, verify:build. Re-run at the delivered head `ddd44dd`.
- `pytest tests -m "browser and not molstar_csp" -n 4 --dist=load -q` -> 151
  passed, 1 skipped, 2 xfailed at head `ddd44dd`. `tests/test_playwright_soft_precision.py`
  alone -> 12 passed (the Soft Precision matrix).
- `pytest tests -m "not browser" -n 4 --dist=load -q` -> 1694 passed, 23 skipped at
  head `ddd44dd`, run with `--basetemp` on the root filesystem because the shared
  `/tmp` tmpfs had exhausted its inode table (a host-state condition, not a code
  defect; the tmpfs also makes a default-basetemp run report spurious `ENOSPC`
  setup errors). The one observed failure
  (`tests/runners/opendde/...antibody_antigen_checkpoint`) asserts an absolute
  `/tmp/` scratch prefix that only holds when the basetemp is under `/tmp`; it is a
  fixture-path assumption of the relocation, not a product regression, and passes
  unchanged under the default basetemp.
- `mkdocs build --strict` -> clean (docs toolchain via `uv run --with`).

## Pre-final review fixes (accessibility / responsive acceptance)

The Pre-Final Review Cell found acceptance claims that were asserted in prose but
not proven by tests. The fix keeps the claim and proves it with a small, bounded
set of real assertions in `tests/test_playwright_soft_precision.py` (no a11y
framework):

- **Visible focus, accessible names** — a primary header action paints a
  non-`none`, positive-width outline under keyboard focus; the theme toggle,
  guided-tour launcher, and language control expose accessible names.
- **Contrast** — body ink and muted text on the canvas meet WCAG 4.5:1 in both
  light and dark, computed from real `getComputedStyle` values via a robust
  `rgb()`/`rgba()`/hex parser and the WCAG relative-luminance formula.
- **Tablet** — at 834px the navigation is the bottom-anchored mobile bar, the
  filter band and view switch stay separate, and the document does not overflow
  horizontally.
- **Touch + reduced motion** — mobile navigation targets are at least 44px, and a
  `prefers-reduced-motion: reduce` preference collapses ornamental transition
  timing.
- **Machine-text honesty** — the ID field is asserted to be a `<dd>` rendering
  non-empty task-ID text in a mono face, replacing the tautological class check.
- **Neutral dark palette** — the comma-split colour parse (which read the alpha
  channel of `rgba()`) is replaced by the robust parser; the neutrality check now
  also covers body ink and asserts the accent stays blue-dominant.

Two dead artifacts the review flagged were removed in the same pass: an
`.app-header-actions .app-new-task` rule whose selector never matched (the control
is prepended directly to the header), and an unused `attribute()` helper in
`guided-tour.ts`. The Dashboard `formatDate` change to a fixed `en-GB`/UTC
machine-fact format is intended: dates are machine facts and compare by eye, which
matches the "consistent formatting" contract in
`docs/developer-guide/frontend-design-language.md` §15.3.

---

# Deterministic Runner Fleet Control Plane (PR #55)

`TODO.md` is the design contract for this PR. This section records execution
state; the committed tests and the named commands are the machine-verifiable
record. Observed `main` at dispatch: `e6407758`; the branch was later rebased
onto `1f1f3c1`, which landed the registry-determinism fix (#62) this branch
consumes.

## What landed

- **One canonical control core** (`revocompute/runner_readiness.py`,
  `runner_registry.py`, `runner_host.py`, `runner_admin_view.py`,
  `runner_promotion.py`). The CLI, production admission, the Admin API, and the
  tests resolve `runner-status`/readiness from the same evaluator, so a family
  cannot be READY on one surface and unavailable to a submission on another.
- **Readiness / capacity / access / infrastructure stay separate** — never one
  "available" flag.
- **Typed operator actions** (`operator_actions.py`): a closed registry with
  bounded parameters, explicit tiers, and lease scopes; no command, argv, env,
  or path field exists anywhere.
- **Plan before execute** (`operator_plan.py`): a content-addressed plan; a stale
  plan fails closed (`409 stale_plan`).
- **Operator Jobs** (`operator_jobs.py` + `_schema.py`): durable records with a
  closed lifecycle, one exclusive lease per family, idempotency, and restart
  reconciliation that never repeats an irreversible action.
- **Minimal Host Operator Executor** (`operator_executor.py`): fixed argv from a
  table, allowlisted env, bounded cwd/timeout, redacted bounded logs, fail-closed
  when unavailable.
- **Admin API** (`operator_service.py` + routes): fleet, detail, plan, action,
  history, jobs, cancel; admin role + bearer gate on every mutation; OpenAPI owns
  the schema and the generated TS is regenerated.
- **Admin Fleet UI** (`frontend/src/features/admin/fleet/FleetAdmin.ts`) in the
  merged Soft Precision language; state-aware corrective actions showing what a
  plan will and will not do; executor-unavailable degraded banner. Operator Job
  history renders the job's own lifecycle vocabulary (`operator_jobs` statuses),
  never a readiness-state badge.
- **Activation/rollback** (`runner_promotion.py`): plan-bound atomic activation
  preserving the replaced artifact, and rollback to a control-core-known
  validated artifact. Deliberately **not** wired to the Web: refused there.
- **Readiness core is consumed, not duplicated**: `runner_registry` and
  `access_control` only *parse* policy documents; the active registry snapshot
  is owned by `task_types` (#62). The admin view and the fleet list resolve
  readiness through the one `runner_readiness` evaluator.

## Delivery commands and results

- `pytest tests -m "not browser" -n 4 --dist=load` → 1901 passed, 23 skipped
  (basetemp on the root filesystem; the shared `/tmp` tmpfs exhausts inodes).
- `pytest tests -m "browser and not molstar_csp" -n 4 --dist=load` → 165 passed,
  1 skipped, 2 xfailed, against the built bundle.
- `cd frontend && npm run typecheck && npm run test && npm run build` → clean;
  97 unit tests passed.
- `mkdocs build --strict` → clean.

## Not done, by decision

- Registry determinism is PR #62's; this branch consumes it when it lands rather
  than re-implementing it.
- The Host Operator Executor stays at its two real host operations; the Web
  surface refuses activation and rollback rather than approximating them.
- §20.9 end-to-end failure drill is deprioritized by the Campaign Commander.


# Untrusted Scientific Input and Artifact Boundary Hardening (PR #58)

`TODO.md` is the design contract for this PR. This section is its execution
state; the committed tests and the named commands are the machine-verifiable
record.

## Starting point

- Branch base: `e64077589ff6c3583bb4b27b528daa2b1551abce` (current `main`).
- Feature branch: `security/untrusted-scientific-boundaries`; worktree
  `security-untrusted-scientific-boundaries`.
- Scope: Core scientific-ingress validation and Runner artifact-publication
  hardening only. No #55 readiness/control, no #56 frontend, no #57 MCP, no
  accounting/quota, no Slurm placement.

## Ingress audit (complete)

Every surface that accepts untrusted scientific bytes reaches the same canonical
Core path — `validate_input_file` + `validate_logical_input` under the quarantine
window — before promotion, snapshot creation, or dispatch:

| Surface | Entry | Canonical? | Bypass? |
| --- | --- | --- | --- |
| Browser multipart `/compute/api/post` | `_handle_submission` | yes | no |
| Preflight `/compute/api/preflight/<tt>` | `_rate_limited_preflight` | yes | no (returns before promote/claim/dispatch) |
| API-key auth | `auth.load_current_user` | yes (same routes) | no |
| Tool call `/compute/api/tools/<name>/call` | `submit_tool_call` | yes | no |
| Cross-Task artifact ref (in a Tool call) | `_tool_task_artifact` | yes (content re-validated) | no (cross-user 403) |
| Workspace normalize POST | `normalize_workspace` | n/a (no file bytes) | CSRF gate added |
| live-test CLI | `live_test_executor` | yes | n/a (not HTTP) |
| MCP | absent on this branch | — | reconcile as a projection after #57 |

## What changed

- `revocompute/ingress_security.py` (new): the bounded admission vocabulary
  (reason code -> phase), the content-derived `validator_revision()`, the
  `ValidationReceipt`, `canonical_relative_path`, receipt verification, and the
  collision-collapse helper. It owns reason codes and their phase only; the
  operational event names it routes to are the existing
  `operational_events.EVENT_NAMES` entries — no second event family.
- `revocompute/routes.py`: collision -> `input_namespace_collision`; receipt
  recorded per admitted item and carried into `task.json`; type+size bound into
  the task identity; `preflight_task` uses the shared phase/event vocabulary; the
  routes-local path shim removed; workspace-normalize CSRF gate added.
- `revocompute/task_runtime.py`: publication boundary (`_publishable_artifact`
  with `O_NOFOLLOW`+`fstat`, symlink/special/hard-link refusal, entry-count and
  byte-total guards, duplicate-path refusal, output-check problems and a bounded
  `manifest.published` reason code); worker verifies the snapshot against the
  receipt before dispatch and revalidates legacy rows; debug capture copies
  instead of hard-linking.
- `revocompute/input_validators/*`: bounded resource-limit classification for the
  isolated worker.

## Delivery commands and results

- `TMPDIR=<root-fs> pytest tests -m "not browser" -n 4 --dist=load -q -p no:cacheprovider`
  -> 1829 passed, 24 skipped, 1 failed.
  The single failure is `tests/runners/opendde/test_opendde_protocol.py` asserting
  an absolute `/tmp/` scratch prefix; it fails only when the pytest basetemp is
  relocated off the tmpfs (the shared `/tmp` tmpfs on this host has ~1M inodes and
  concurrent runs exhaust it). It passes with the default basetemp, so it is a
  fixture-path assumption of the relocation, not a product regression.
- `pytest tests/server tests/test_ingress_boundary.py tests/test_input_validation.py -q`
  -> 468 passed, 1 skipped.
- `cd frontend && npm ci && npm run typecheck && npm test && npm run build`
  -> typecheck clean (incl. `check:api-types`), 19 files / 88 tests passed, build
  passes `verify:lock`/`verify:provenance`/`check:api-types`/`verify:build`.
  The frontend bundle is unchanged; no `openapi.json` regeneration was needed
  because the receipt rides inside existing free-form objects.

## Known deferred

- MCP reconciliation after #57 lands (projection only; #57 does not exist on this
  branch).
- The `boltz_predict` `considerations` manifest defect noted in the previous
  section is unrelated and still open.

## Pre-final review cell fixes (head d83f303)

The three-way cell (Security + Correctness/Contract + Evidence/Integration)
confirmed the publication boundary could not be escaped and returned two
BLOCKERs plus MATERIALs; all are fixed:

- BLOCKER 1 — the worker read `validation_receipt` while ingress wrote
  `validation`, so the execution-time check was dead code. The key is unified at
  every writer and revalidation is now mandatory (a receipt proves identity, it
  does not replace validation). Three new tests cover the live branch, a stale
  revision with matching bytes, and a forged receipt over invalid bytes.
- BLOCKER 2 — a file/directory prefix pair in one role (`x.pdb` +
  `x.pdb/y.pdb`) now fails closed as `input_namespace_collision` before the
  preparation claim instead of 500ing with orphan state.
- MATERIAL — `validator_resource_limit` is reachable (timeout, resource kill,
  in-band sentinel), the isolated worker converts RLIMIT_AS fatal signals, the
  capacity guard stops the walk and bounds the recorded refusals, the capacity
  ceilings are server-owned config, and the credit reason code is one spelling
  with an enumerated reverse-direction vocabulary test.

Gates on this head: full non-browser suite 1834 passed / 24 skipped / 1 failed
(the accepted opendde `/tmp`-prefix basetemp artifact); the frontend typecheck /
test / build gates are unchanged and green.

## Named follow-ups (tracked, not silent)

- `validator_revision()` reports `sha256:unavailable` when a boundary source
  cannot be read, and verification does NOT fail on that value: the revision
  comparison is skipped because both sides read `unavailable`. After the
  BLOCKER-1 fix this is a false-accept of an unknown boundary identity, not a
  validation bypass — the bytes are still re-validated through the canonical
  boundary on every dispatch. It is deferred rather than fixed here because the
  stay-on-`main` durability contract requires a restored task to keep executing,
  so failing on `unavailable` must be paired with guaranteeing the sources are
  always present in a production install, which is a separate change. Owner:
  follow-up PR; tracked so it is not dropped.
- The admission reason-code vocabulary and the artifact reason codes are named
  here as a shared surface for #59 reconciliation (`gpu_credit_exhausted` is the
  unified spelling; #59's accounting codes must join this vocabulary rather than
  mint a parallel one).
- MCP reconciliation after #57 lands (projection only; the canonical path and
  the receipt are the trust boundary, MCP projects them).
