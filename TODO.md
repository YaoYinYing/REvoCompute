# Soft Precision Frontend Visual System

## Objective

Establish and implement a durable REvoCompute visual language that is recognizably ours without relying on decorative motifs, novelty geometry, or an "AI-generated SaaS" aesthetic.

The design thesis is:

> **Soft Precision — precise without sharpness, professional without industrial coldness, complex without disorder, restrained without emptiness.**

REvoCompute should not decorate computation. It should give computation order.

The interface must make scientific work feel clear, inspectable, calm, and trustworthy. It should not resemble a generic SaaS dashboard, a Microsoft/Fluent enterprise control surface, an HPC administration console, or a futuristic AI product.

This PR is a visual-system and frontend-experience redesign. It is **not** an architecture refactor and must preserve the existing product model, server authority, Runner/task contracts, scientific result contracts, and successful task flows.

The current Dashboard information architecture is broadly sound. Keep its core shape:

```text
page identity
→ task overview
→ search/filter controls
→ task collection
```

Refine how that structure is expressed rather than replacing it with a new visual metaphor.

The durable visual contract lives in:

```text
docs/developer-guide/frontend-design-language.md
```

Read it before implementation and keep it synchronized with the final UI.

---

## 0. Read before editing

Read at minimum:

```text
CLAUDE.md
LONG_TASK_HANDLING.md
TODO.md
IMPLEMENTATION_STATE.md
docs/developer-guide/frontend-design-language.md
docs/developer-guide/input-result-workspace.md
docs/developer-guide/testing.md

frontend/src/styles/app.css
frontend/src/app/shell.ts
frontend/src/app/public-shell.ts
frontend/src/app/theme.ts
frontend/src/app/domain-vocabulary.ts
frontend/src/main.ts

frontend/src/features/dashboard/index.ts
frontend/src/features/dashboard/task-query.ts
frontend/src/features/runners/
frontend/src/features/create-task/
frontend/src/features/results/
frontend/src/features/profile/
frontend/src/features/admin/

tests/test_playwright_application.py
tests/test_playwright_gremlin_golden_acceptance.py
frontend/tests/
```

Use the available frontend-design skill/workflow before making visual decisions. Inspect the rendered application, not only CSS and DOM source.

Before implementation, fetch current `origin/main` and inspect open frontend/result PRs. At the time this plan was written, PR #46 and #47 remain active. Rebase before touching overlapping files. Do not duplicate or undo their scientific/result-contract work.

Record the exact implementation starting SHA in `IMPLEMENTATION_STATE.md`.

---

## 1. Non-goals and hard boundaries

Do **not** turn this into another repository architecture refactor.

Do not change:

- Runner scientific behavior;
- task parameter semantics or defaults;
- ResultManifest semantics merely for presentation;
- scheduler/Slurm/Apptainer behavior;
- result validation identity;
- server ownership of Runner/task vocabulary;
- one-click task submission behavior;
- real scientific result renderers merely to make screenshots look cleaner.

Do not introduce visual gimmicks whose only purpose is brand recognition.

Explicitly avoid:

- decorative status rails or green success stripes on task cards;
- decorative sparklines or charts without real underlying data;
- pastel icon tiles on every section;
- gradient hero surfaces;
- glassmorphism;
- glowing borders;
- cyberpunk/HPC-terminal styling;
- molecule/DNA background decoration;
- forced “workflow lines” or computation-trace ornament;
- excessive pill controls;
- excessive cards used only to wrap layout;
- hover-lift card motion as a default interaction;
- a new component framework or CSS-in-JS migration;
- a wholesale React rewrite;
- vendored frontend libraries.

A recognizable design language must come from repeated judgment, not repeated decoration.

---

## 2. Product-level design principles

Implement the UI so these principles are visible in ordinary use.

### 2.1 Quiet

The interface must not compete with scientific content.

Use emphasis sparingly. The result, input, task, Runner, or action that owns the page should be visually strongest; surrounding chrome should recede.

### 2.2 Precise

Machine facts must be easy to scan and compare:

- task IDs;
- job IDs;
- hashes;
- filenames;
- timestamps;
- durations;
- versions;
- numeric values;
- units.

Use stable formatting, tabular numerals where useful, and monospace only where the content is genuinely machine identity.

### 2.3 Gentle

Reduce the “Microsoft enterprise panel” / industrial feel without turning the interface cute or consumer-like.

Gentleness should come from:

- softer geometry;
- controlled contrast;
- comfortable spacing;
- restrained borders;
- reduced visual chrome;
- predictable motion;
- polite feedback.

It should **not** come from oversized radii, pastel decoration, bubbles, or rounded-everything styling.

### 2.4 Trustworthy

Every interaction should make system state legible.

Users should not need to guess whether:

- a task was submitted;
- an archive is preparing;
- a filter is active;
- a notice was hidden;
- a destructive action happened;
- the current language/theme was applied.

Trust comes from clear state and provenance, not ornament.

### 2.5 Macro-space, micro-density

Use generous page-level composition and tighter information-level composition.

```text
page / section spacing  → breathable
task metadata           → compact
parameter lists         → compact
artifact/file lists     → compact
result controls         → compact
```

Do not dilute scientific information in the name of “premium whitespace”.

---

## 3. Visual foundation and token audit

Audit `frontend/src/styles/app.css` before adding tokens.

Refactor existing tokens where necessary so the live CSS expresses the revised visual contract.

### 3.1 Geometry

Keep a small radius scale with role-specific curvature.

The intended feel is:

- corners are softened;
- rectangles still read as rectangles;
- pills remain exceptional;
- controls do not look like Fluent/Windows command bars;
- large cards do not look like soft consumer-SaaS bubbles.

Do not use one radius everywhere.

### 3.2 Borders and elevation

Prefer:

```text
spacing
→ alignment
→ hairline separation
→ explicit boundary
→ elevation
```

in that order.

A shadow means genuine elevation. Ordinary task cards and content surfaces should usually stand through background/border contrast, not floating shadows.

Menus, dialogs, popovers, and true overlays may use stronger elevation.

### 3.3 Colour

Keep a neutral canvas with a restrained REvo blue accent.

REvo blue behaves like ink, not paint. Use it for:

- primary action;
- selection;
- active navigation;
- focus;
- meaningful links.

Semantic status colour must remain semantically scoped.

Do not tint every card by state. Do not use status colour to decorate layout.

“Finished” is a fact, not a celebration.

### 3.4 Dark mode

Treat dark mode as its own calibrated surface system, not a simple light-mode inversion.

Avoid the previous green/teal cast.

Validate:

- neutral canvas;
- restrained borders;
- non-white reading text;
- accent luminance;
- success/warning/danger contrast;
- Mol*/scientific-stage compatibility.

---

## 4. Typography and machine facts

Typography is a core brand asset.

Create/retain two clear text roles:

```text
human language
    headings, labels, descriptions, actions

machine facts
    ids, hashes, filenames, code-like values, exact technical identifiers
```

Do not put every technical value in monospace.

Use monospace when fixed identity matters. Use tabular numerals for comparable numbers and time values when supported by the stack.

Reduce hierarchy noise:

- fewer arbitrary font-size steps;
- stronger contrast between page/object titles and metadata;
- metadata labels should recede;
- avoid decorative uppercase eyebrow labels;
- do not style ordinary labels as branding.

Long IDs must remain selectable and inspectable. Truncation must never destroy access to the full value.

---

## 5. Application shell

Rework the authenticated shell as a quiet environment around the work.

### 5.1 Desktop navigation rail

Default to a narrow icon rail.

Requirements:

- logo/brand remains legible without turning the rail into a banner;
- primary navigation uses icons in the collapsed state;
- accessible labels/tooltips remain available;
- the active item is clear without a heavy left status stripe;
- spacing is open enough that the rail does not resemble an IDE toolbar;
- repeatedly activating/clicking the **current navigation item** toggles expanded/collapsed navigation;
- remove any dedicated bottom collapse arrow/button;
- preserve keyboard navigation and focus states;
- persist the user's rail preference locally;
- expansion reveals labels without moving the underlying page into a broken layout.

Do not change mobile navigation into a thin desktop rail; keep a mobile-specific navigation solution.

### 5.2 Top bar

The top bar is global chrome, not a second primary navigation.

It should hold only global capabilities such as:

- language;
- theme;
- persistent/system notices;
- account;
- admin affordance when relevant.

Do not add a decorative global search field unless a real global search capability exists.

Do not duplicate page-level actions simply to fill the header.

### 5.3 i18n control

Add a language control to the authenticated/public chrome.

Initial app-owned locale support:

```text
en
zh-CN
```

The implementation must:

- localize frontend-owned static copy through one translation layer;
- persist explicit user choice locally;
- use browser locale only as an initial preference;
- update `document.documentElement.lang`;
- keep accessible labels localized;
- fall back deterministically to English;
- avoid string concatenation that breaks grammar.

**Do not duplicate server-owned Runner/task vocabulary in frontend translation catalogs.**

Server-projected scientific parameter names/help, Runner-owned text, and other server-authoritative vocabulary remain server-owned unless a future server localization contract explicitly supports localized variants.

The i18n layer must not become a second source of truth for task semantics.

---

## 6. Persistent system notices

The existing transient toast system remains useful for short action feedback.

Add a separate **persistent system notice** surface for long-lived operational information.

It should support:

- long text;
- a bounded height with internal scrolling when necessary;
- hide/collapse;
- dismiss when the notice is dismissible;
- restore/re-open from a global notice affordance;
- multiple notices without stacking the page into a wall;
- info/warning/critical semantics;
- keyboard and screen-reader access;
- persistence of dismissal by stable notice identity when appropriate.

Typical content:

- scheduled maintenance;
- service degradation;
- Runner availability changes;
- release/migration notes;
- operator announcements.

Do not hard-code a fake maintenance message into production.

First inspect whether an existing server-owned operational/configuration source can expose notices. If none exists, add the **smallest read-only server-owned projection** needed for operator-configured notices. Keep notice content out of frontend source code and do not build a general CMS.

Transient action errors/successes still use toast-style feedback and must not be routed through the persistent notice panel.

---

## 7. Guided learning / interactive manual

Add a hands-on guided learning module for first-time and returning users.

This is not a generic SaaS “welcome tour”.

The goal is to teach the REvoCompute conceptual model:

```text
Runner
→ input
→ task
→ execution state
→ result
→ artifacts/provenance
```

Requirements:

- a visible but non-dominant “Guided tour” entry on the Dashboard for users who have not completed/dismissed it;
- a durable way to restart the tour later;
- route-aware steps;
- no forced modal takeover;
- keyboard navigation;
- escape/dismiss support;
- reduced-motion support;
- progress stored locally;
- steps anchored to real interactive elements;
- graceful skipping when an element is absent because of role, viewport, or deployment state.

The first implementation should cover the ordinary user path:

```text
Dashboard
→ Runner catalog/detail
→ Create task
→ Dashboard lifecycle
→ Result workspace
```

It should explain concepts, not merely say “click this button”.

Do not duplicate full documentation text inside the tour. Link to the relevant documentation for deeper explanation.

---

## 8. Dashboard composition

Preserve the current Dashboard's overall information architecture while improving hierarchy.

### 8.1 Page header

The page title establishes place, not marketing.

Keep `Dashboard` strong but not oversized.

Page actions should not compete with the task collection.

### 8.2 Overview statistics

Keep the five high-level task states if they remain useful:

```text
Total
Pending
Running
Finished
Needs attention
```

Do not add decorative mini charts.

A sparkline is allowed only if it displays real historical data with a defined time window and meaning.

Avoid colouring every overview card differently. Use neutral surfaces with local semantic emphasis.

### 8.3 Search/filter toolbar

The default mode should be simple and aligned.

Keep the highest-frequency controls visible:

- text search;
- status;
- task type;
- owner for admins;
- sort/order.

Move lower-frequency controls into an **Advanced search** affordance.

Advanced search may include:

- submitted date range;
- finished date range;
- regex mode;
- other existing low-frequency query fields.

Requirements:

- labels and controls share a coherent baseline/grid;
- no awkward mixed heights;
- no regex toggle appended as visual noise to the search field by default;
- advanced state is obvious when active;
- filters remain queryable/testable with existing task-query logic.

### 8.4 View mode control

The view switch answers “how should I view this collection?” and must be visually separate from search/filter controls, which answer “which tasks should I see?”.

Keep:

```text
Detailed
Compact
Table
```

Use a compact segmented/icon treatment with accessible text/labels.

Persist the user's preferred view locally if this can be done without changing API semantics.

---

## 9. Task cards

Task cards remain.

A Task is an independent computational object and therefore earns a boundary.

### 9.1 Remove decorative status treatment

Delete status-coloured decorative side rails/top lines and equivalent accents.

Do not tint the whole card by finished/running state.

Status belongs inside the task's information hierarchy.

### 9.2 Card identity

The strongest line in a card is the task display name.

Then:

- task type / Runner identity;
- status;
- core machine facts;
- actions.

Avoid generic decorative icon tiles. If an icon is retained, it must carry a stable semantic role and should not need a pastel backing tile to exist.

### 9.3 Metadata layout

Redesign the `dl` layout for fast scanning.

A recommended detailed-card reading order is:

```text
Type        <value>
Task ID     <machine value>
Submitted   <time>

Owner       <value>      [admin only]
Wall time   <duration>
Finished    <time>       [when meaningful]
```

The exact columns may adapt to width, but preserve these principles:

- labels are quieter than values;
- related facts stay close;
- IDs/hashes receive machine-text treatment;
- dates and durations align consistently;
- absent values do not create random visual holes;
- mobile collapses to a readable single/two-column flow.

Do not turn each fact into a chip or micro-card.

### 9.4 Actions

The card is content first, controls second.

Action hierarchy:

```text
Results      strongest contextual action
Download /
Prepare ZIP  secondary
Cancel       contextual warning
Delete       quiet until invoked
Select       low-emphasis batch affordance
```

Do not make all actions equal-weight outlined buttons.

Destructive actions require existing confirmation semantics.

---

## 10. Runner surfaces

Do not turn the Runner catalog into an app store.

Treat it as a curated scientific method registry.

The catalog/detail views should prioritize:

- method identity;
- method purpose;
- inputs/outputs;
- availability/readiness;
- access;
- version/source/citation where already projected;
- resource character where meaningful.

Comfortable cards may remain, but remove decorative hover-lift and avoid pastel-icon-card clichés.

Compact density should feel like a registry/list rather than a compressed card wall.

Do not invent frontend-only scientific metadata.

---

## 11. Create Task

Preserve the current one-click submit direction.

The page should make the user feel in control **before** submission rather than inserting another confirmation page.

Improve:

- parameter grouping;
- spacing and label hierarchy;
- required/default/advanced distinction;
- validation readability;
- input workspace hierarchy;
- task snapshot/execution summary when already supported by the canonical contract.

Do not duplicate `task.yaml` parameter semantics in frontend code.

Do not reintroduce a Review → Submit two-step flow.

---

## 12. Result workspace

The scientific result is visually dominant.

Do not let this redesign conflict with PR #46/result-contract work.

After rebasing onto relevant result PRs, apply the shared visual language to:

- page chrome;
- side/file rails;
- tabs/controls;
- typography;
- spacing;
- dialogs;
- empty/error/loading states.

Do **not** simplify away scientific controls or alter renderer meaning for aesthetic consistency.

Principle:

> provenance remains easy to inspect, but provenance does not visually overpower the scientific result.

The result workspace is allowed to be denser and more technical than Dashboard.

Contextual density is part of the design system.

---

## 13. Admin, profile, authentication, public pages

Propagate shared visual rules without forcing identical page layouts.

Each surface may have its own density:

```text
Dashboard       calm overview
Runner pages    curated registry
Create Task     controlled preparation
Result          scientific workspace
Admin           dense system control
Profile         quiet settings
Public pages    restrained orientation
```

Shared identity comes from tokens, type, spacing, colour semantics, control hierarchy, language, and interaction — not from wrapping every page in the same cards.

---

## 14. Motion and feedback

Motion exists to explain state change.

Target motion should be short and low amplitude.

Use it for:

- rail expansion/collapse;
- notice reveal/hide;
- advanced-search reveal;
- dialog/popover entry;
- stateful control transitions.

Avoid:

- card hover lift as a default;
- large page transitions;
- decorative loading shimmer;
- continuous ambient animation.

Respect `prefers-reduced-motion`.

Every asynchronous action must expose an understandable busy/success/failure state.

---

## 15. Accessibility

Do not trade accessibility for visual cleanliness.

Verify:

- WCAG contrast for text and interactive states;
- keyboard access to navigation, filters, tour, notices, menus, dialogs;
- visible focus without harsh Microsoft-style focus chrome;
- screen-reader labels for icon-only controls;
- logical DOM/source order;
- reduced motion;
- touch targets on mobile/tablet;
- `lang` updates with locale;
- no colour-only status communication.

---

## 16. Responsive behavior

Test at least:

```text
mobile narrow
mobile landscape / small tablet
tablet
desktop ~1280
wide desktop
```

The desktop rail must not become an unusable compressed rail on mobile.

The Dashboard toolbar may wrap/recompose, but search, filters, Advanced Search, and View remain conceptually separate.

Task metadata must reflow without horizontal scrolling in card modes.

Table mode may scroll horizontally where necessary.

Persistent notices must not consume the full mobile viewport.

Guided-tour callouts must remain usable or fall back to a compact step panel.

---

## 17. Implementation discipline

Do not rewrite the frontend stack.

Prefer small, explicit TypeScript modules.

Likely ownership areas include:

```text
frontend/src/styles/app.css
frontend/src/app/shell.ts
frontend/src/app/public-shell.ts
frontend/src/app/theme.ts
frontend/src/app/i18n.ts                 (if introduced)
frontend/src/app/system-notices.ts       (if introduced)
frontend/src/app/guided-tour.ts          (if introduced)
frontend/src/features/dashboard/
frontend/src/features/runners/
frontend/src/features/create-task/
frontend/src/features/results/
frontend/src/features/profile/
frontend/src/features/admin/
frontend/tests/
tests/test_playwright_application.py
```

Exact filenames are not mandatory.

Avoid one giant “design system” utility file.

Reuse existing primitives and domain modules.

Do not add a component abstraction unless at least two real call sites benefit from it.

---

## 18. Browser and visual acceptance

Use the real production frontend bundle and the existing deterministic frontend fixture harness for browser acceptance.

Add/extend browser scenarios for:

- desktop collapsed nav;
- expanded nav;
- repeated active-nav activation toggling the rail;
- language switching;
- locale persistence;
- persistent system notice open/hide/reopen/scroll;
- Guided Tour start/progress/dismiss/restart;
- Dashboard simple filters;
- Advanced Search open/close and active state;
- independent view switch;
- task card metadata hierarchy;
- no decorative status rail;
- detailed/compact/table views;
- dark mode;
- mobile/tablet navigation and toolbar reflow.

Where screenshots are useful, generate a **small deliberate storyboard**, not a large screenshot corpus.

Recommended visual review frames:

```text
Dashboard / desktop / light
Dashboard / desktop / dark
Dashboard / tablet
Dashboard / mobile
Runner catalog / desktop
Create Task / desktop
Result workspace / representative real-result fixture
```

Screenshots are review evidence, not pixel-golden tests unless the existing test stack already has a justified stable mechanism.

Do not add brittle image-diff tests merely to freeze the mockup.

---

## 19. Testing gates

At minimum run the final-head equivalents of:

```bash
cd frontend
npm ci
npm run typecheck
npm run test
npm run build

cd ..
python -m pytest tests/test_playwright_application.py -q
mkdocs build --strict
git diff --check
```

Run additional focused tests for any touched server notice/config projection.

Do not weaken CSP.

Do not load fonts, icons, or UI assets from a CDN.

Do not silently skip browser acceptance because a real Runner is unavailable; use canonical fixture scenarios for frontend behavior.

---

## 20. Review checklist

Before `READY_FOR_FINAL_REVIEW`, inspect the final rendered application and answer all of these explicitly in `IMPLEMENTATION_STATE.md` or the PR report:

1. Does the Dashboard still feel like the same product structurally, rather than a redesign for redesign's sake?
2. Are decorative status rails gone?
3. Does the shell feel less like Microsoft/Fluent enterprise software?
4. Is the design softer without becoming bubbly, cute, or pastel-heavy?
5. Is REvo blue used as semantic ink rather than surface paint?
6. Are cards used because they represent objects, not because every section needs a box?
7. Are borders/shadows/radii role-driven?
8. Is the task metadata grid faster to read than before?
9. Are search/filter controls aligned?
10. Is Advanced Search subordinate but discoverable?
11. Is the View switch visually independent from filtering?
12. Can the desktop nav rail expand/collapse without a separate collapse button?
13. Can users switch English/Simplified Chinese without duplicating server-owned task semantics?
14. Can long system notices be read, hidden, and reopened?
15. Does Guided Tour teach the product model rather than only point at controls?
16. Are decorative charts absent unless backed by real data?
17. Does dark mode avoid the old green cast?
18. Do mobile/tablet layouts preserve hierarchy?
19. Is the Result workspace still science-first?
20. Can a user infer state without relying on colour alone?

---

## 21. Definition of done

This work is complete when the frontend no longer depends on generic “modern SaaS” styling to feel finished.

A reviewer should be able to remove the REvoCompute wordmark and still observe a coherent product identity produced by:

- information hierarchy;
- typography;
- density;
- geometry;
- colour semantics;
- interaction behavior;
- scientific-data treatment;
- repeated restraint.

The final interface should feel:

> **precise, but not sharp; professional, but not industrial; complex, but not chaotic; restrained, but not empty.**

The success criterion is not “looks more designed”.

The success criterion is:

> **REvoCompute has a visible order of its own.**
