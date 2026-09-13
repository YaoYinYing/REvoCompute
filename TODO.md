# Frontend State Hardening and Micro-Polish

## Goal

The large frontend scalability redesign is complete. This follow-up PR should **not redesign the application again**.

Its purpose is to harden the existing UI under real runtime states and correct the remaining spatial/detail inconsistencies visible in production:

- Dashboard action states must not destabilize table geometry.
- Dashboard controls need a final hierarchy/copy pass.
- Runner Access needs substantially denser policy/activity presentation.
- Landing hero should use its remaining first-fold dead space more effectively.
- API Docs must participate correctly in dark mode.

The governing rule for this PR is:

> **Preserve the current architecture. Fix component behavior, spatial roles, and theme completeness.**

---

# 1. Dashboard — stabilize table action states

## Problem

The task table layout is visually stable until a Download action enters a transient state such as:

- `Preparing download…`
- `Checking access…`

The Download button then expands into a wider/taller two-line component and changes the visual rhythm of the row.

A transient operation state must not resize the table.

## Required behavior

Keep the `Actions` cell behaving like a compact horizontal toolbar.

- [x] Give task-action controls a consistent height.
- [x] Bound action-button width.
- [x] Keep table row height effectively invariant during download preparation.
- [x] Do not render verbose two-line progress text inside the button.
- [x] Replace verbose transient text with a compact state such as:
  - spinner + `Preparing…`
  - spinner + `Checking…`
  - or another concise single-line state.
- [x] Put secondary explanatory text in a tooltip/title/accessible status message if needed.
- [x] Do not hide useful progress information from screen readers.
- [x] Prevent long transient text from pushing `Delete` or other actions into a second line.

The action hierarchy should remain:

```text
Results    Download    Delete
primary    secondary   quiet/destructive
````

`Delete` should not visually compete with `Results`.

---

# 2. Dashboard — micro-polish filter and view controls

Preserve the current filtering architecture.

## Copy

Normalize user-facing terminology:

* [x] `TaskType` → `Task type`
* [x] `Submitted through` → `Submitted to`
* [x] `Finished through` → `Finished to`

Use these changes only where they correctly describe the existing date-range semantics.

Do not rename API fields, TaskType IDs, schema keys, or backend concepts.

## Regex toggle

The `RE` control currently has too much visual weight for a mode switch.

* [x] Keep regex functionality unchanged.
* [x] Restyle `RE` as a small mode toggle/chip.
* [x] Maintain clear `aria-pressed` state.
* [x] Preserve invalid-regex feedback.
* [x] Do not turn regex into a separate filter workflow.

## Filter versus view hierarchy

The panel currently combines:

* dataset filtering;
* sorting;
* layout selection;
* batch actions.

Keep them in the same overall panel, but improve grouping.

Suggested conceptual grouping:

```text
FILTERS
Task name | Task type | Status | Username | Date ranges

VIEW
Sort | Layout

SELECTION
Select visible | Clear selection | Delete selected
```

* [x] Use spacing, separators, or grouping rather than additional heavy cards.
* [x] Do not increase total panel height unnecessarily.
* [x] Preserve mobile wrapping.

## Selection actions

* [x] Make `Delete Selected (0)` visually dormant when nothing is selected.
* [x] Disable it semantically when selection count is zero.
* [x] Increase destructive emphasis only when deletion is actually actionable.

---

# 3. Runner Access — compact empty state

## Problem

`Pending eligibility decisions` reserves a large card even when there are no requests.

The section is important when populated, but should not dominate the page when empty.

## Required behavior

* [x] Keep the section visible.
* [x] Collapse the empty state to a compact height.
* [x] Do not reserve a large fixed/minimum height for an empty queue.
* [x] Use a short quiet message such as `No pending access requests.`
* [x] Restore normal content-driven height automatically when requests exist.

Do not hide the section entirely; administrators should still immediately know the queue is empty.

---

# 4. Runner Access — redesign restricted-policy rows

The current policy cards contain useful information but waste vertical space.

Current conceptual content:

```text
AlphaFold 3 non-commercial access

Authorized 2
Pending    0
Suspended  0

[---------------- Manage ----------------]
```

The full-width `Manage` pill is the wrong visual role.

## Target structure

Prefer a compact row/card:

```text
AlphaFold 3 non-commercial access        2 Authorized   0 Pending   0 Suspended   [Manage]
```

or a responsive equivalent.

* [x] Keep the policy name prominent.
* [x] Keep Authorized / Pending / Suspended counts easy to scan.
* [x] Make `Manage` a normal compact action button.
* [x] Remove the stretched full-width button shape.
* [x] Reduce unnecessary policy-card height.
* [x] Keep cards readable with long policy names.
* [x] Provide a sensible tablet layout.
* [x] Stack gracefully on phone screens.

Do not change policy semantics or entitlement APIs.

---

# 5. Runner Access — audit duplicate policy rendering

The production screenshot suggests that `Pallatom non-commercial access` may appear more than once.

Determine whether this is:

* an actual duplicate policy rendered twice;

* a screenshot boundary showing another section;

* duplicate entitlement → policy projection;

* or duplicated configuration.

* [x] Trace the policy list from configured policy registry to API response to frontend rendering.

* [x] Ensure one configured policy produces one policy summary.

* [x] Do not deduplicate blindly in JavaScript if duplicated source data indicates a backend/configuration bug.

* [x] Add a regression test if a real duplicate-rendering path exists.

---

# 6. Runner Access — fix link theming

`Access and licensing terms` currently leaks browser-default visited-link coloring.

* [x] Define normal link color using the REvoCompute theme.
* [x] Define `:visited` intentionally.
* [x] Preserve accessible contrast.
* [x] Keep hover/focus indication clear.
* [x] Do not allow default purple visited links inside application surfaces.

This should ideally be handled by a reusable application link rule rather than a one-off inline style.

---

# 7. Runner Access — redesign Recent Activity as an audit feed

## Problem

Every access event is currently displayed as a large card:

```text
tester
alphafold3_noncommercial — allowed
```

A long event history therefore creates excessive vertical repetition.

Activity is secondary audit information and should optimize for scanning.

## Required layout

Convert Recent Activity into a compact feed/table-like list.

Each event should expose, where available:

```text
Time | User | Policy / Runner | Outcome
```

For example:

```text
09-13 16:42    tester    AlphaFold 3 non-commercial    Allowed
09-13 16:38    tester    AlphaFold 3 non-commercial    Allowed
```

* [x] Include timestamp.
* [x] Show a human-readable policy/Runner label when available.
* [x] Preserve the raw policy identifier only when useful as secondary information.
* [x] Render outcome using compact state styling.
* [x] Reduce per-event vertical height substantially.
* [x] Avoid one bordered card per event unless grouping genuinely benefits readability.
* [x] Keep recent activity scrollable/readable when many events exist.
* [x] Preserve the existing activity limit/API semantics unless there is a clear bug.

Do not introduce pagination in this PR unless the current event volume makes it necessary.

---

# 8. Landing page — use the lower-right hero dead space

## Problem

Moving `Connect an AI agent` below the complete hero fixed the old asymmetric left column, but created another imbalance:

```text
LEFT                          RIGHT

hero copy                     evidence map
CTA                           judgment panel
                              [large empty region]

[          AI-agent strip across full width          ]
```

The desktop first fold contains unused lower-right space.

## Desktop target

Move the AI-agent entry into that unused lower-right region beneath the evidence/judgment composition.

Conceptually:

```text
┌──────────────────────────── HERO ─────────────────────────────┐
│                                                              │
│   hero copy                    evidence / judgment            │
│   hero copy                    evidence / judgment            │
│   CTA                                                        │
│                                Connect an AI agent            │
│                                /skills.md            [Copy]   │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

* [x] Keep the agent box outside the left text column.
* [x] Place it beneath/right of the evidence composition at desktop widths.
* [x] Use the existing empty space rather than increasing hero height.
* [x] Preserve the current hero copy and evidence composition.
* [x] Avoid absolute positioning that becomes brittle with content changes.

Prefer CSS Grid areas or equivalent responsive layout structure.

## Tablet/mobile behavior

Do **not** force the desktop composition onto narrow screens.

At smaller breakpoints:

```text
hero copy
evidence map
agent entry
```

* [x] Let the agent entry return to natural document flow.
* [x] Preserve comfortable spacing.
* [x] No overlap.
* [x] No horizontal overflow.
* [x] No requirement that mobile content fit into one viewport.

---

# 9. API Docs — complete dark-mode integration

## Problem

The application shell is in dark mode while Swagger UI remains substantially light-themed.

This produces:

* a large white documentation surface inside a dark application;
* inconsistent headers and panels;
* input fields with poor or invisible text contrast;
* theme boundaries that look accidental rather than intentional.

This is an actual usability defect, not merely aesthetic polish.

## Required approach

Keep Swagger/OpenAPI as the documentation renderer.

Do not replace Swagger UI or create a custom API documentation frontend in this PR.

Add a **scoped Swagger dark-mode theme layer** under the REvoCompute dark theme.

Avoid globally overriding generic `input`, `button`, `table`, etc. selectors.

Scope rules under the Swagger root, for example conceptually:

```css
html[data-theme="dark"] .swagger-ui ...
```

## Dark-mode coverage

Audit at minimum:

* [x] page background;
* [x] Swagger wrapper/background;
* [x] operation blocks;
* [x] GET/POST/etc. operation headers;
* [x] expanded operation content;
* [x] headings;
* [x] normal body text;
* [x] descriptions;
* [x] labels;
* [x] parameter names;
* [x] required markers;
* [x] text inputs;
* [x] textareas;
* [x] select controls;
* [x] placeholders;
* [x] Execute/Clear/Cancel buttons;
* [x] response tables;
* [x] response descriptions;
* [x] schemas/models;
* [x] code samples;
* [x] curl blocks;
* [x] request URLs;
* [x] borders/dividers;
* [x] links;
* [x] icons where Swagger permits styling.

Input text must always remain readable.

Do not produce situations such as:

```text
white input background + white/light text
```

## Light mode

* [x] Preserve normal Swagger light-mode readability.
* [x] Dark-mode overrides must not accidentally affect light mode.

## Theme switching

If the application allows live theme switching without page reload:

* [x] Swagger UI should update appropriately after theme changes.

Prefer CSS driven by the existing root theme attribute rather than rebuilding Swagger.

---

# 10. Shared spacing and control-shape pass

Apply only where affected by this PR.

Establish consistent geometry for:

* [x] ordinary buttons;
* [x] compact buttons;
* [x] segmented controls;
* [x] regex toggles;
* [x] status badges;
* [x] table action bars;
* [x] policy action buttons;
* [x] compact audit rows;
* [x] empty states.

Avoid introducing another parallel set of component styles.

Reuse existing design tokens where possible.

The intended hierarchy is:

```text
Primary action
Secondary action
Quiet utility
Destructive action
Mode toggle
Status badge
```

These should not all look like the same pill.

---

# 11. Accessibility

Preserve the accessibility work from the frontend-scalability PR.

Verify:

* [x] keyboard access to all changed controls;
* [x] visible focus states;
* [x] `RE` uses `aria-pressed`;
* [x] loading Download states expose progress text accessibly;
* [x] disabled bulk-delete state is conveyed semantically;
* [x] compact Runner Access rows remain understandable to screen readers;
* [x] Swagger inputs retain labels;
* [x] dark-mode text meets sensible contrast expectations;
* [x] no functionality becomes hover-only.

---

# 12. Regression tests

Add focused coverage for the defects fixed by this PR.

## Dashboard

* [x] Render a finished task with normal Download state.
* [x] Transition it into download preparation/checking state.
* [x] Assert the task row does not materially change height.
* [x] Assert action buttons remain on one toolbar row at desktop width.
* [x] Assert action state remains accessible.
* [x] Test zero-selection destructive action is disabled/dormant.
* [x] Preserve existing Detailed / Compact / Table tests.

## Runner Access

* [x] Empty pending-request state remains compact.
* [x] Populated pending state expands naturally.
* [x] Policy cards expose counts and compact Manage action.
* [x] One policy produces one rendered summary.
* [x] Recent activity shows timestamp/user/policy/outcome.
* [x] Long policy labels remain responsive.
* [x] No horizontal page overflow on phone.

## Landing

At representative widths verify agent placement:

```text
1920×1080
1440×900
1366×768
1024×1366
834×1194
430×932
390×844
```

* [x] Desktop: agent entry occupies the right-side lower hero region.
* [x] Tablet/mobile: entry returns to normal stacked flow.
* [x] No overlap with hero copy or evidence map.
* [x] Hero CTA remains visible and usable.
* [x] No horizontal overflow.

## API Docs

* [x] Render API docs under light theme.
* [x] Render API docs under dark theme.
* [x] Expand an operation containing parameters.
* [x] Verify parameter input foreground/background are both explicitly readable.
* [x] Verify descriptions, responses, and code blocks remain visible.
* [x] Verify switching themes does not require rebuilding the Swagger DOM.
* [x] Do not rely exclusively on screenshots; include structural/computed-style assertions where practical.

---

# 13. Architecture constraints

Do not solve these visual defects by weakening existing architecture.

* [x] No task-type-specific Dashboard CSS/JS.
* [x] No Runner-specific frontend branches for access policy layout.
* [x] No backend API redesign for purely visual fixes.
* [x] No replacement of Swagger UI.
* [x] No duplicate design-token system.
* [x] No absolute-positioning hack for the landing hero if Grid/Flex can express it.
* [x] No fixed-height empty-state cards.
* [x] No `eval` or unsafe dynamic execution.
* [x] No unrelated scheduler/Runner/runtime changes.

If an apparent frontend duplicate reveals a backend/configuration bug, fix the actual source rather than masking it in rendering.

---

# 14. Suggested implementation order

1. Dashboard action-state geometry.
2. Dashboard control/copy polish.
3. Runner Access empty state and policy rows.
4. Runner Access activity feed.
5. Runner Access duplicate-policy audit.
6. Landing hero grid refinement.
7. Swagger dark-mode theme.
8. Shared spacing/control cleanup.
9. Accessibility verification.
10. Browser regression tests.
11. Final responsive audit.

Do not broaden scope during implementation.

---

# Non-goals

This PR does **not** include:

* another frontend architecture redesign;
* new Dashboard layouts;
* new filtering semantics;
* new Runner Access policy semantics;
* new entitlement roles;
* new Runner integrations;
* scheduler or SLURM changes;
* API redesign;
* replacement of Swagger/OpenAPI;
* artifact-reuse work;
* result-workspace redesign;
* major navigation redesign.

---

# Definition of done

This PR is complete when:

* Dashboard task rows remain geometrically stable during transient action states.
* Dashboard copy and control hierarchy are internally consistent.
* Runner Access no longer wastes large areas on empty/secondary information.
* Policy `Manage` actions have the correct compact visual role.
* Recent activity is a dense audit surface rather than a stack of oversized cards.
* Duplicate policies do not render accidentally.
* The landing hero uses its desktop lower-right space without harming responsive layouts.
* API Docs are fully readable and visually coherent in both light and dark modes.
* No changed page introduces horizontal overflow at supported viewport classes.
* Existing frontend behavior remains intact.
* Focused Playwright/browser tests cover the new regressions.
* Full CI passes.

Once these conditions are satisfied, stop polishing and prepare the PR for review.
