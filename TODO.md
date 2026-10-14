# TODO — Dashboard Composition, Full-Height Navigation Rail, and Clear Metrics Axes

> Campaign: REvoCompute Interaction Model Correction, PR C. Design-only Draft PR.
> Root TODO.md is a PR-local working artifact. Remove from tracked PR diff at final review; durable design lives in existing developer docs/CSS.

## 1. Scope and user observations (2026-10-14)

Three specific, visible problems; fix them without a frontend architectural rewrite:
1. Dashboard screenshot: the tall left Total/Pending/Running/Finished/Needs attention column still consumes ~160px of main register width. The user requested this stats rail move to the **top, horizontally aligned in the highlighted space to the right of "Dashboard"**. Search, filters and task register must then span the complete content width.
2. Sidebar screenshot: expanded and collapsed rails have different perceived bottom heights, stop above the viewport bottom and leave the toggle above blank space. The collapse/expand control belongs at the physical bottom of the persistent rail in either width.
3. Metrics screenshot: minor Y-axis labels obscure the task chart; use simple count-oriented increments and a top bound at the next multiple of 10: peak 11 -> max 20. Fix colliding X labels.

Not part of scope: scientific methods, Task schema/admission, resource ledger, global design token rebranding, new task-card data model, animated decoration or global React/Vue migration. Existing "Soft Precision" palette/typography remain canonical.

## 2. Dashboard: exact spatial contract

Current code puts .dashboard-stats in grid column 1 and spans rows 2–4; .work-toolbar/.view-toolbar/.task-list live in column 2. Existing frontend/src/styles/app.css explicitly encodes these selectors. REMOVE the side-rail layout, not merely restyle numbers.

Required desktop composition:

    ┌─────────────────────────────── GLOBAL APP HEADER ────────────────────────────────┐
    │ [left navigation]                   [+ New task] [language] [account]            │
    ├──────────────┬────────────────────────────────────────────────────────────────────┤
    │ navigation   │  Task register                                                      │
    │              │  Dashboard      [TOTAL 56] [PENDING 0] [RUNNING 0] [FINISHED 48]  │
    │              │                 [NEEDS ATTENTION 8]            [New task] [Refresh] │
    │              ├────────────────────────────────────────────────────────────────────┤
    │              │ Search tasks [___________________________________________]       │
    │              │ [Status] [Type] [Owner] [Order] [Advanced search]                 │
    │              ├────────────────────────────────────────────────────────────────────┤
    │              │ [Select]           56 / 56 tasks            [Detailed|Compact|Table]│
    │              ├────────────────────────────────────────────────────────────────────┤
    │              │ TASK A                     Owner ...        Slurm ...               │
    │              │  Failed                     submitted ...   results ...            │
    │              ├────────────────────────────────────────────────────────────────────┤
    │              │ TASK B                     ...                                     │
    └──────────────┴────────────────────────────────────────────────────────────────────┘

The stats occupy the previously highlighted BLUE rectangle **at the right of the page title**, not above the entire page as another full-width card and not still in the left margin. At widths where five stats + page actions cannot fit on one line, wrap stats to two short rows below/in the heading block; then move page actions to their own row. The important invariant is that **the toolbar, view selector and cards never become column 2 to make room for a persistent statistics rail**.

Proposed DOM ownership: place an existing or a light stats child inside the page header composition; the page body is a single full-width flow. No duplicate counters in old position. Counters still derive from current Task dataset/query semantics; verify whether totals are global vs filtered before rearranging.

CSS model (use existing tokens; illustrative, not literal magic widths):

    .dashboard-page {
      display: block;
      width: min(100% - 2rem, 96rem);
      margin-inline: auto;
    }
    .dashboard-page > .page-heading {
      display: grid;
      grid-template-columns: minmax(12rem, auto) minmax(0, 1fr) auto;
      align-items: end;
      gap: clamp(.8rem, 2vw, 2rem);
    }
    .dashboard-stats {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: .5rem;
      border: 0;
    }
    .dashboard-page > .work-toolbar,
    .dashboard-page > .view-toolbar,
    .dashboard-page > .task-list { width: 100%; }

If the CSS breakpoints require 3+2 wrapping, use grid area changes at ~wide-tablet, not squeezing labels to illegible widths. The last stat "Needs attention" must not disappear. Avoid equal-weight giant statistic numbers: the task register remains the page's center of gravity.

### Checklist — Dashboard

- [ ] Write reproducible Playwright viewport screenshot test showing old column occupancy before changing CSS.
- [ ] Move real stats DOM to header region; ensure guided tour selectors/actions/element order remain functional (PR #81 overlap).
- [ ] Replace .dashboard-page two-column grid and remove stale grid-row/column style overrides, including media-query duplicates.
- [ ] Make filters and cards span available width. Detailed, Compact, Table layouts and select-all/batch controls remain operational.
- [ ] Preserve accessible h1, labelled stats section, natural tab order, visible counts, query controls and actions.
- [ ] Test empty, long-task-title, 56 tasks, long localized labels, admin vs non-admin owner filter, 125%/200% zoom, reduced width.
- [ ] Verify app top bar New task and page New task are still honest and route correctly; PR A owns method readiness, not this PR.

## 3. Navigation: one viewport-height rail in both states

Current frontend/src/styles/app.css:

    .app-shell { display:grid; min-height:100vh; grid-template-areas:"brand header" "nav outlet"; }
    .app-nav { position:sticky; top:0; align-self:start; max-height:100vh;
               display:flex; flex-direction:column; overflow-y:auto; }
    .app-nav-foot { margin-top:auto; }

Diagnosis: max-height is a ceiling, NOT a definite height. With align-self:start, .app-nav shrinks to its content; margin-top:auto has no extra space to push the toggle to viewport foot. Expansion changes content line-height/spacing, so heights differ.

Required composition in both widths:

    ┌─────────────────────────┐    ┌──────┐
    │ REvoCompute             │    │ logo │
    ├─────────────────────────┤    ├──────┤
    │ COMPUTE                 │    │ [⚙]  │
    │ Runners                 │    │ [▦]  │
    │ Dashboard               │    │      │
    │                         │    │      │
    │ ACCOUNT                 │    │ [○]  │
    │ ...                     │    │ ...  │
    │                         │    │      │
    │ ADMINISTRATION          │    │ [▣]  │
    │ ...                     │    │ ...  │
    │                         │    │      │
    │ [content may scroll]    │    │      │
    │                         │    │      │
    ├─────────────────────────┤    ├──────┤
    │ [◧ Collapse]            │    │ [◧]  │
    └── bottom of viewport ───┘    └──────┘

Layout requirement, regardless of chosen implementation:
- The navigation remains full-height from beneath the app header to the bottom of the viewport, including tall page content.
- Navigation items may scroll within their region on short viewport; the toggle remains accessible at the bottom, **outside of that scrollable region if needed**. Prefer splitting flex into scrollable items + fixed nav foot; can reuse current DOM with a small wrapper.
- Do not create a second, detached toggle elsewhere; use existing persisted rail setting, aria-expanded, aria-label and keyboard behavior.
- Avoid absolute-position hacks and fixed pixel page heights. Prefer CSS grid/flex and viewport units such as 100dvh, with measured/owned --app-bar token.
- Review sticky header behavior before choosing nav top; if global header is sticky, account for header height so sidebar never overlays it or leaves a gap during scroll.
- Mobile navigation differs from desktop; preserve mobile bar, page-bottom clearance, safe area, i18n labels. Do not force full-height desktop rail onto mobile.

Illustrative geometry (verify actual shell coordinates, media queries and browser behavior):

    .app-shell {
      min-height: 100dvh;
      grid-template-rows: var(--app-bar) minmax(0, 1fr);
    }
    .app-nav {
      align-self: stretch;
      min-height: 0;
      height: calc(100dvh - var(--app-bar));
      max-height: none;
      /* Sticky top must match verified global top-bar geometry. */
    }
    .app-nav-scroll { min-height: 0; flex: 1 1 auto; overflow-y: auto; }
    .app-nav-foot { margin-top: auto; flex: none; }

This is a conceptual proposal: solve both initial paint and vertical scrolling, not one screenshot by hardcoding height.

### Checklist — Sidebar

- [ ] Visual regression for rail collapsed and expanded on same viewport; bottom edge + toggle Y coordinate must match within layout tolerance.
- [ ] Test desktop viewport 900px high, 600px high, long admin nav, 200% zoom, scrollbar, both themes, mobile breakpoint.
- [ ] Persist collapse state across route navigation/reload; icon tooltips and focus order work when collapsed.
- [ ] Verify no page outlet content covered by rail; no second document scrollbar caused by nav-only overflow.
- [ ] Remove styles that make expanded/collapsed heights differ unintentionally.
- [ ] Preserve real footer control at bottom even after scrolling a long dashboard.

## 4. Metrics: integer count axes, remove minor labels

Current frontend/src/features/profile/sections.ts uses niceStep(peak / 4), four majors and four halfway minor ticks; CSS .activity-tick-minor and tests pin them. User asked for simpler thresholds.

Contract for **nonnegative integer Task counts**:
- peak 0 -> optional empty/zero chart, scale max 10 (or explicit empty state; keep scale truthful).
- 1..10 -> max 10.
- 11..20 -> max 20.
- 21..30 -> max 30.
- 99 -> max 100.
- 100 -> max 100; 101 -> max 110.
- A 10-based scale does NOT mean logarithmic scaling: linear bars, decimal step 10.
- Only labelled major ticks at integer tens plus 0; no minor tick labels. If tall charts demand reduced tick density at peak 2000+, choose a 10×k major step with an integer k so label count stays bounded; max remains next multiple of 10.
- Y axis must never show halfway labels like 3, 5, 7 which are visually misread as major values, nor non-integer counts.

Proposed function behavior:

    function countAxisMaximum(peak: number): number {
      return Math.max(10, Math.ceil(Math.max(0, peak) / 10) * 10);
    }

This is a UX count-axis rule only, not a shared scientific charting convention for continuous quantities. Do not propagate it into resource accounting units.

X-axis:
- Remove duplicate overlapping last bucket date; label a bounded subset of dates with sufficient space for full strings.
- Preserve true date bucket positions; use tooltips/accessible table or descriptive aria label for all buckets, including zero counts.
- Responsive label density and period semantics (daily/weekly/quarterly/yearly) maintained. Screen readers need complete data outside sparse visual labels if necessary.

### Checklist — Metrics

- [ ] Implement count axis max invariant and remove all minor tick DOM + CSS.
- [ ] Update tests that currently expect exactly four minor ticks: protect the new semantics, not old markup.
- [ ] Demonstrate peaks 0,1,10,11,20,21,99,100,101 and same-data responsive label behavior.
- [ ] Date labels do not overlap or render clipped; 30 buckets still readable.
- [ ] Preserve method distribution, success rate, duration and period selector data semantics unchanged.

## 5. Coordination, verification, limits

Potential files: frontend/src/features/dashboard/index.ts, frontend/src/styles/app.css (desktop and breakpoint blocks), frontend/src/app/shell.ts, frontend/src/features/profile/sections.ts, scoped css, tests/test_playwright_application.py, Dashboard and i18n frontend tests, guided tour specs, docs/developer-guide/frontend-design-language.md only if the canonical layout rule changes.

- [ ] Prioritize behavior-driven Playwright tests rather than snapshots of source or CSS text.
- [ ] Capture before/after screenshots for 1600×900, ~1100px wide, mobile widths and dark theme.
- [ ] Run TypeScript checks, relevant frontend tests, Playwright, full applicable CI, mkdocs --strict if docs changed.
- [ ] Review generated layout against the supplied 2026-10-14 annotated Dashboard screenshot (red stats rail -> blue header region) before claiming done.
- [ ] Rebase on PR #81 guided tour changes only through Commander; no unrelated tour redesign.
- [ ] Clean temporary root TODO/IMPLEMENTATION_STATE from final PR diff; report exact head SHA and READY_FOR_FINAL_REVIEW; no merge permission.
