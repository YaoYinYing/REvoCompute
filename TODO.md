# PR37 — REvoCompute Production UI Polish

## Objective

PR32–PR34 established the canonical frontend/backend presentation boundary.

PR35 established the first version of the new REvoCompute visual language.

This work **does not reopen either architecture**.

The purpose of this branch is to take the post-PR35 frontend from a coherent design experiment to a polished production interface:

> **Contemporary scientific workstation × quiet editorial clarity**

The current frontend has a stronger information architecture than the legacy UI, but several visual choices make it feel older and less elegant than intended, especially in dark mode:

- dark backgrounds and surfaces are excessively green-tinted;
- muted text is also green-tinted;
- teal/green is used simultaneously as atmosphere, identity, and success semantics;
- serif-heavy application headings frequently resolve to Georgia and create an outdated institutional/corporate appearance;
- full-width hairlines and fine rules are overused as layout structure;
- some surfaces resemble instrument labels or administrative forms rather than a contemporary scientific workstation;
- the Home page still presents REvoDesign more strongly than REvoCompute despite living at `revocompute.yaoyy.moe`;
- Create Task currently requires `Review → Run`, adding an unnecessary second action;
- the one-runner deployment on the temporary 309 host exposes awkward catalog/card behavior;
- selected legacy browser URLs currently 404 even though their semantic replacements are known.

The intended outcome is:

```text
PR35 architecture and information hierarchy
        +
legacy UI's chromatic clarity
        +
modern neutral scientific-workstation styling
        +
less interaction friction
        +
real deployment/browser validation
        =
REvoCompute production UI
```

---

# 0. Hard Boundaries

These are non-negotiable.

## Preserve

Preserve the canonical post-PR34 frontend architecture:

```text
frontend/
Vite production build
frontend-owned application presentation
server-owned APIs and domain contracts
Runner-owned scientific definitions
ResultManifest semantics
direct Mol* integration
workspace plugin contracts
```

Do not restore deleted Jinja presentation.

Do not restore old global JavaScript/CSS.

Do not move presentation ownership back into Flask.

Do not create a second task definition or parameter source in the frontend.

Do not change scientific Runner behavior as part of this work.

Do not touch GREMLIN_LH scientific reconstruction work being developed in the separate worktree.

Do not make the repository behave as though only PSSM-GREMLIN exists merely because the temporary 309 deployment currently enables only that family.

## Explicitly out of scope

Do not:

- perform another frontend/backend architecture refactor;
- replace Vite or introduce a new frontend framework;
- redesign the plugin system;
- redesign ResultManifest;
- redesign Mol* integration;
- modify scheduler architecture;
- modify Runner execution semantics;
- add generic legacy compatibility shims;
- add wildcard `/PSSM_GREMLIN/*` forwarding;
- build unrelated GPU Runner images on the temporary 309 workstation;
- introduce decorative AI gradients, neon glow, glassmorphism, particle effects, or generic SaaS dashboard styling;
- solve design hierarchy by adding more cards.

---

# 1. Fresh Worktree Bootstrap

Work from the dedicated UI polish worktree.

The expected location is similar to:

```text
/home/yinying/repo/REvoCompute-ui-polish
```

but the actual current working directory is authoritative.

Before editing:

```bash
pwd
git status
git branch --show-current
git fetch origin
git log -1 --oneline
git worktree list
```

Record:

```text
starting SHA
branch
worktree path
working-tree cleanliness
```

The expected base is current `origin/main`, which at planning time contains PR35.

Do not assume the planning-time SHA is still current.

Read before coding:

```text
CLAUDE.md
AGENTS.md
LONG_TASK_HANDLING.md when applicable
TODO.md
IMPLEMENTATION_STATE.md
docs/developer-guide/frontend-design-language.md
docs/developer-guide/architecture.md
docs/developer-guide/input-result-workspace.md
frontend/src/styles/app.css
frontend/src/app/shell.ts
frontend/src/app/router.ts
frontend/src/features/home/
frontend/src/features/runners/
frontend/src/features/dashboard/
frontend/src/features/create-task/
frontend/src/features/results/
tests/server/test_application_frontend_contract.py
tests/test_playwright_application.py
```

Inspect relevant Git history rather than relying on memory.

---

# 2. Mandatory `frontend-design` Skill

## 2.1 Load the skill before visual editing

The `frontend-design` skill is mandatory.

Use the Claude Code skill system to locate and invoke it before changing CSS or page composition.

If invocation syntax differs in the current environment, inspect the available skills/help rather than guessing.

The skill must be used to critique:

- current deployed REvoCompute;
- current post-PR35 source;
- dark mode;
- light mode;
- historical visual evidence;
- typography;
- colour relationships;
- spacing;
- hierarchy;
- surface language;
- page composition;
- responsive behavior;
- interaction affordances.

Do **not** ask the skill to invent an unrelated fashionable redesign.

Constrain it with the design direction in this document.

If `frontend-design` is genuinely unavailable, stop before visual implementation and report that fact. Do not silently substitute a generic redesign.

---

# 3. Mandatory Visual Observation Before Coding

This task must not be performed from source code alone.

The agent is running headless through Claude Code with DeepSeek v4.1 Flash, so first determine what browser and image-inspection capabilities actually exist.

## 3.1 Inspect the live deployment

Attempt to inspect:

```text
https://revocompute.yaoyy.moe/
https://revocompute.yaoyy.moe/runners
https://revocompute.yaoyy.moe/compute/login
```

For authenticated surfaces, use an existing safe local/test authentication mechanism or an already configured development session if one exists.

Never expose credentials in:

```text
commands
logs
commits
screenshots
TODO.md
status reports
```

Relevant authenticated surfaces:

```text
/compute/dashboard
/compute/create_task?task_type=gremlin
a completed PSSM-GREMLIN result when available
```

## 3.2 Capture baseline screenshots

Before modifying visual code, capture at least:

```text
Home
Runner Catalog
Login
Dashboard
Create Task — PSSM-GREMLIN
Result — PSSM-GREMLIN if available
```

At:

```text
desktop: approximately 1440 × 950
mobile/narrow: approximately 390 × 844
```

Capture both:

```text
light
dark
```

Store screenshots outside the repository, for example:

```text
/tmp/revocompute-ui-polish/before/
```

Do not commit screenshot artifacts unless explicitly requested.

## 3.3 Actually inspect the screenshots when possible

If the active Claude Code/model/tool environment supports image understanding:

**inspect the screenshots directly.**

Do not rely only on CSS source.

Use the visual evidence to identify:

```text
dominant colour cast
hierarchy problems
awkward empty space
alignment problems
overused borders
typography character
button prominence
surface density
mobile breakage
one-runner catalog behavior
```

If the active model cannot consume images:

1. do not claim to have visually inspected them;
2. still capture them for human comparison;
3. inspect the DOM and computed CSS using browser automation;
4. measure layout dimensions, spacing, font-family resolution, colours, overflow and responsive state;
5. use `frontend-design` plus those measurements;
6. explicitly record the limitation.

Do not fabricate visual observations.

---

# 4. Historical Visual Archaeology

Review the pre-cutover and pre-PR35 history as **design evidence**, not implementation to restore.

Use Git history to inspect representative historical CSS/pages.

Identify what the older interface did well:

```text
cooler blue-black dark canvas
clear cyan/blue identity
neutral separation between background and surfaces
cleaner distinction between identity colour and semantic success
greater chromatic clarity
less green atmospheric tint
simple direct submission
```

Also identify what must remain dead:

```text
large frame inside large frame
card-within-card form layouts
oversized Submission Checklist
isolated single-purpose legacy pages
old Jinja presentation
legacy JavaScript
large blocks of instructional copy
old page architecture
```

The goal is not:

```text
restore legacy UI
```

The goal is:

```text
recover its elegance where it was genuinely better
while keeping the modern architecture and information hierarchy
```

---

# 5. Revised Design Thesis

PR35 used:

> Scientific instrument × editorial laboratory

That concept is useful but the implementation over-indexed the editorial side.

PR37 should use:

> **Contemporary scientific workstation × quiet editorial clarity**

Desired qualities:

```text
modern
precise
scientific
calm
neutral
confident
clear
fast
purposeful
slightly tactile
```

Avoid:

```text
retro institutional
1980s corporate
green-black terminal
old laboratory information system
paper archive
administrative portal
generic SaaS
enterprise CRM
developer IDE clone
gaming UI
neon AI product
```

The application must look like professional scientific software designed now.

---

# 6. Foundation First — Dark Palette

This is the highest-priority visual task.

Do not begin page-by-page cosmetic tuning until the foundation is corrected.

## 6.1 Remove the green atmospheric cast

Current dark mode excessively concentrates background, surface, raised surface, muted text, accent, and success inside a green/teal hue family.

That must change.

The dark theme should use approximately:

```text
canvas       → neutral blue-black / graphite
surface      → restrained cool charcoal / blue-grey
raised       → slightly lighter cool neutral
stage        → stable deep neutral
primary text → cool near-white
muted text   → neutral cool grey
identity     → restrained cyan / blue-cyan
success      → green, semantic only
warning      → amber
danger       → restrained red
```

A starting direction, **not mandatory exact values**:

```css
--app-bg:          #0c1218;
--app-surface:     #111a22;
--app-raised:      #17222c;
--app-stage:       #0d151c;

--app-ink:         #edf2f5;
--app-muted:       #98a6b2;

--app-line:        #26333e;
--app-line-strong: #344552;

--app-accent:      #4ca3bd;

--app-success:     #64b59c;
--app-warning:     #d5a657;
--app-danger:      #df776e;
```

Use `frontend-design` and rendered screenshots to tune the final values.

Do not mechanically adopt these hex codes if a better coherent palette emerges.

## 6.2 Separate identity from status semantics

Do not let one teal/green colour simultaneously mean:

```text
brand
selected
success
available
finished
decorative atmosphere
```

Establish explicit roles.

Prefer conceptual separation:

```text
accent
success
warning
danger
running
selection/background tint
```

Green should primarily communicate successful/available semantic state, not paint the whole application.

## 6.3 Light mode

Do not degrade light mode while fixing dark mode.

Check both modes side-by-side.

Light mode should remain:

```text
neutral
quiet
slightly warm or cool-neutral
highly readable
scientific
```

Avoid a pale green wash strong enough to tint the entire application.

---

# 7. Typography — Remove the Accidental Georgia Identity

The current stack declares:

```text
Source Serif 4
→ Georgia fallback
```

but the intended font is not actually shipped.

As a result, important application headings often render as Georgia.

This contributes strongly to the outdated institutional appearance.

## 7.1 Application UI

Application surfaces should use modern sans typography for:

```text
REvoCompute wordmark in application shell
Create task
Runner names
Dashboard titles
Runner Detail
Result headings
Profile
Admin
Configuration
forms
controls
navigation
Task Snapshot
```

Build hierarchy using:

```text
size
weight
tracking
line-height
spacing
measure
```

not an unavailable display font.

## 7.2 Serif usage

Serif is no longer mandatory as a product-wide identity device.

It may remain in a very limited public/editorial context only if rendered evidence shows that it genuinely improves the page.

Do not retain serif merely because PR35 documented it.

Do not let Georgia become the product identity.

Do not add an external font CDN.

Do not introduce a font binary dependency solely to rescue the old design thesis.

A font-packaging decision is separate work unless a very strong case emerges and is explicitly approved.

---

# 8. Reduce Hairline-Driven Layout

PR35 still uses too many full-width `1px` separators.

Audit:

```text
page heading separators
Method context
section boundaries
Runner Detail
Home sections
task surfaces
toolbars
```

Use hierarchy in this order:

```text
spacing
proximity
typography
surface/background
then hairline where structurally useful
```

A full-width line should communicate a real boundary, not simply fill empty space.

Do not remove all borders.

Inputs, tables, technical grids and true structural boundaries may still need them.

---

# 9. Application Shell Polish

Preserve the current shell architecture.

## 9.1 Brand behavior

Change the REvoCompute brand link to:

```text
/
```

rather than:

```text
/runners
```

The product mark should return to the product home.

## 9.2 Navigation semantics

Current conceptual navigation:

```text
Runners
Dashboard
New task
```

Treat:

```text
Runners / Dashboard
```

as destinations.

Treat:

```text
New task
```

as an action.

It may remain in the header, but its styling should communicate a different semantic role rather than presenting three equal navigation destinations.

Do not over-emphasize it.

## 9.3 Header

Retain:

```text
compact height
sticky behavior
profile/admin/theme controls
clear active state
```

Refine:

```text
type
spacing
icon weight
active indication
dark palette
surface/background relationship
```

Avoid turning the header into a floating SaaS pill bar.

---

# 10. Home — Make REvoCompute the Product

The current Home page at `revocompute.yaoyy.moe` gives REvoDesign the dominant identity.

Correct this.

## 10.1 First-screen identity

A visitor should immediately understand:

```text
This is REvoCompute.
It provides managed scientific computation for protein/enzyme design and analysis.
It belongs to the REvoDesign ecosystem.
```

Do not remove REvoDesign.

Correct the hierarchy:

```text
REvoCompute first
REvoDesign relationship second
```

Update the document title accordingly.

## 10.2 Hero

The primary heading should not simply be:

```text
REvoDesign
```

on the REvoCompute domain.

Develop a REvoCompute-first hero using the frontend-design critique.

Avoid generic AI marketing language.

Avoid giant empty typography over decorative background.

## 10.3 Scientific memory point

The current evidence plate is a useful concept but currently tells a REvoDesign-centric story:

```text
Structure
Evolution
Computation
→ Designer judgment
→ Testable mutations
```

Consider reframing the visual motif around REvoCompute itself.

Possible conceptual language:

```text
Scientific input
→ reproducible Runner
→ inspectable result
```

or:

```text
Sequence / Structure / Design
          ↓
     Managed compute
          ↓
Structure / Table / Model / Artifact
```

Do not hard-code scientific claims that are not supported by actual product capabilities.

Keep the motif lightweight.

## 10.4 Reduce prose

Audit Home copy aggressively.

Aim to remove approximately 20–30% of low-information or repetitive prose if doing so improves the page.

The visitor should remember:

```text
REvoCompute
Scientific Runners
Inspectable results
REvoDesign ↔ REvoCompute ecosystem
Agent-accessible computation
```

Do not explain the same philosophy three times.

## 10.5 Agent entry

Keep agent accessibility.

Do not let `Connect an AI agent` visually compete with the primary product story.

Consider a quieter capability strip or later-page section.

Preserve `/skills.md`.

---

# 11. Runner Catalog — Handle 1, Few and Many Runners

The current temporary 309 deployment enables only PSSM-GREMLIN.

Treat this as an important real-world acceptance state.

Do **not** optimize the product only for a fleet of ~46 methods.

The catalog must look intentional with:

```text
1 runner
2–4 runners
many runners
```

## 11.1 Comfortable density

Avoid a two-column grid leaving an awkward empty half-page when only one Runner exists.

Use responsive sizing such as an appropriate `auto-fit/minmax` strategy or another deliberate layout supported by the design.

Do not allow one card to expand absurdly wide.

## 11.2 Density controls

If only one or very few methods are available, determine whether the density switch adds any user value.

If not, hide or de-emphasize it based on actual catalog cardinality.

Do not hard-code PSSM-GREMLIN behavior.

## 11.3 Deployment language

Where appropriate, prefer wording such as:

```text
available on this deployment
enabled on this deployment
```

rather than implying that the current temporary server represents REvoCompute's complete capability set.

Repository capability and deployment availability are different concepts.

---

# 12. Create Task — Single-Action Submission

This is a required behavioral change.

The current flow is:

```text
Review
  ↓
preflight
  ↓
Run
  ↓
submit
```

Replace it with:

```text
Run task
   ↓
local validation
   ↓
server preflight
   ├── invalid → show actionable issues and stop
   └── valid   → submit automatically
                     ↓
                  Dashboard
```

## 12.1 Keep all safety checks

Do not remove:

```text
workspace validation
input contract validation
access validation
security preflight
admission/readiness checks
server-side validation
```

The change removes only the unnecessary second user confirmation.

## 12.2 Primary action

The primary action should consistently be:

```text
Run task
```

Do not dynamically change it between:

```text
Review
Review again
Run
```

## 12.3 Busy lifecycle

One click begins one continuous operation:

```text
Run task
→ Checking…
→ Queueing…
→ Task queued
```

The primary action must remain disabled through the entire:

```text
preflight → submission
```

chain.

Do not re-enable the button between those phases.

Prevent accidental duplicate submission.

## 12.4 Failure behavior

Local validation failure:

```text
do not call preflight
show actionable validation problems
```

Preflight failure:

```text
do not submit
show server-projected actionable issues
re-enable Run task
```

Submission failure:

```text
show meaningful error
re-enable Run task
invalidate stale preflight state if appropriate
```

Warnings that do not make preflight invalid must not force a second confirmation click.

## 12.5 Remove obsolete copy

Remove or replace copy such as:

```text
Choose a method, prepare its inputs, then review and run.
Run the review to complete the checks.
Checks passed. Review them, then run.
Review again.
Fix the listed issues before review.
Review failed.
```

Prefer language such as:

```text
Choose a method and prepare its inputs.
Ready to run.
Checking task…
Queueing task…
Fix the listed issues before running.
Task checks failed.
```

## 12.6 Task Snapshot, not Review Rail

The right rail should conceptually be:

```text
TASK SNAPSHOT

PSSM-GREMLIN
CPU · Open

Input
1 FASTA

Parameters
Defaults

────────

Ready to run

[ Run task ]
```

not a wizard review stage.

When blocked:

```text
2 issues to fix

• ...
• ...

[ Run task ] disabled
```

Keep it concise.

---

# 13. PSSM-GREMLIN Create Task Polish

Use the currently enabled PSSM-GREMLIN Runner as the primary real acceptance case.

The current screenshot reveals excessive vertical fragmentation around:

```text
Provide the input
FASTA input
Protein sequence
file picker
1–1 file(s): fasta
validation message
Sequence
description
sequence name
textarea
No pasted sequence
```

Audit whether every visible line helps the user act.

Do not remove contract-required information.

Reduce duplication where server-projected metadata and workspace guidance say the same thing twice.

The primary interaction should read immediately as:

```text
Provide protein sequence
→ upload FASTA OR paste sequence
→ optional parameters
→ Run task
```

without making the scientific contract ambiguous.

Do not duplicate Runner-owned parameter/help text in frontend source.

---

# 14. Legacy Browser Redirects

Add explicit compatibility redirects for known semantically equivalent legacy browser entry points.

Required:

```text
/PSSM_GREMLIN/dashboard
    → /compute/dashboard

/PSSM_GREMLIN/create_task
    → /compute/create_task?task_type=gremlin
```

## 14.1 Implement at the Flask route layer

Do not implement these in:

```text
frontend router
JavaScript
Cloudflare rules
nginx-only configuration
```

The application should own these browser compatibility routes.

## 14.2 Redirect class

Use a temporary redirect during the current migration/recovery period.

Prefer:

```text
302
```

unless existing project conventions strongly justify another temporary redirect status.

Do not prematurely introduce permanent browser/CDN caching with 301/308.

## 14.3 No wildcard shim

Do not implement:

```text
/PSSM_GREMLIN/<path>
→ arbitrary modern equivalent
```

Only explicit routes whose semantic destination is known.

Keep currently unsupported old URLs unsupported.

In particular, do not create legacy API compatibility as a side effect of this task.

## 14.4 Tests

The current frontend contract explicitly expects:

```text
/PSSM_GREMLIN/dashboard → 404
```

Update that behavior test.

Add real HTTP behavior assertions for:

```text
status
Location header
query string
authentication behavior at destination
```

Do not test literal Python source text.

---

# 15. Dashboard Polish

Dashboard should remain the most utilitarian application surface.

Do not make it a showcase page.

Keep:

```text
high-density scanning
Detailed / Compact / Table
sorting
filters
batch actions
task status
```

Improve only where rendered evidence supports it:

```text
toolbar grouping
alignment
empty states
few-task state
typographic hierarchy
button hierarchy
status distinction
surface neutrality
responsive behavior
```

Avoid giant KPI cards.

Avoid adding decorative dashboard chrome.

---

# 16. Runner Detail

Keep the current information architecture.

Audit:

```text
category
method name
summary
availability/access
runtime facts
scientific contract
workflow
inputs
parameters
citations
Create task CTA
```

Reduce the institutional/document-page feel caused by:

```text
full-width lines
serif-heavy headings
small muted copy
repetitive metadata
```

Do not remove scientifically meaningful contract information merely to make the page shorter.

---

# 17. Result Workspace

PR37 should not redesign Result Workspace architecture.

Preserve:

```text
ResultManifest
storyboards
Mol*
artifact preview
file rail
downloads
diagnostics
fullscreen
rail collapse
```

Use PSSM-GREMLIN as a real result acceptance case where possible.

Confirm:

```text
scientific result remains the strongest surface
normal success remains quiet
files/diagnostics remain subordinate
download affordances are clear
dark canvas does not contaminate scientific plots/tables
```

Only make presentation changes supported by visual inspection.

Do not reopen Mol* architecture.

---

# 18. Profile / Admin / Auth / Legal / API Docs

Apply the corrected foundation consistently.

Priorities:

```text
readability
neutral surfaces
modern sans hierarchy
form clarity
danger-action clarity
compact admin efficiency
consistent controls
```

Do not add personality for its own sake.

API Docs should preserve Swagger usability.

Terms should prioritize reading comfort.

Login should feel part of the same product rather than a different template.

---

# 19. Responsive and Accessibility

Every changed surface must be inspected at:

```text
desktop
tablet-ish intermediate width
narrow/mobile
```

Preserve or improve:

```text
keyboard navigation
focus-visible state
heading structure
contrast
dialog semantics
form labels
aria-live status
reduced motion
touch targets
overflow handling
```

Do not trade scientific viewport area for decorative padding.

No horizontal page overflow at normal mobile widths.

---

# 20. Motion

Keep motion restrained.

Allowed:

```text
small hover transition
subtle selection transition
dialog enter/exit
very light route/section appearance
running-state motion when informative
```

Avoid:

```text
parallax
scroll-jacking
animated gradients
pulsing decoration
large card movement
constant ambient motion
```

Respect:

```css
prefers-reduced-motion
```

---

# 21. Browser-Driven Iteration Loop

Do not make all CSS changes in one blind pass.

Use this loop:

```text
inspect
→ identify one visual/systemic problem
→ make focused change
→ build
→ render
→ capture screenshot
→ inspect
→ compare
→ continue
```

Prioritize systemic fixes first:

```text
palette
typography
surface roles
border usage
control hierarchy
```

Then page-specific polish.

A page-specific workaround should not compensate for a broken global token.

---

# 22. Required Screenshot Comparison

After implementation, capture the same matrix used for baseline:

```text
Home
Runner Catalog
Login
Dashboard
Create Task — PSSM-GREMLIN
Result — PSSM-GREMLIN if available
```

At desktop and narrow widths.

Both light and dark.

Store under something like:

```text
/tmp/revocompute-ui-polish/after/
```

If image understanding is available, compare before/after directly.

Specifically evaluate:

```text
Does dark mode still look green?
Does the product still read as retro/institutional?
Does Georgia appear anywhere as accidental application identity?
Does REvoCompute dominate the Home page?
Does one Runner look intentional?
Can a user identify the primary action immediately?
Does Create Task feel like a workbench rather than a form wizard?
Are surfaces differentiated without border overload?
Does the page still feel calm?
```

Do not declare visual success from tests alone.

---

# 23. PSSM-GREMLIN Real Storyboard Acceptance

When operationally feasible on the 309 deployment, exercise one real workflow:

```text
open Runner
→ Create task deep-link
→ provide a minimal valid FASTA
→ Run task once
→ automatic preflight
→ automatic submit
→ Dashboard
→ running/finished state
→ Result
→ PSSM/GREMLIN outputs
→ files/downloads
```

The purpose is UI acceptance, not a scientific benchmark.

Do not run unnecessary large workloads.

Do not rebuild unrelated Runner images.

If a real compute run is not reasonable, exercise the same browser flow using the project's existing realistic test fixtures and explicitly record the limitation.

---

# 24. Tests — Create Task

Update browser behavior tests so they test the new requirement:

```text
valid input
→ click Run task exactly once
→ preflight request occurs
→ submit request occurs automatically
→ navigation to Dashboard
```

Add/adjust coverage for:

```text
local validation blocks preflight
preflight failure blocks submit
preflight success proceeds automatically
warnings do not require second confirmation
double-click / repeated action cannot duplicate submission
submission failure restores usable state
editing input invalidates previous preflight
```

Delete tests that exist only to preserve:

```text
Review → Run
```

Do not replace them with source-text assertions.

---

# 25. Tests — Legacy Redirects

Update:

```text
tests/server/test_application_frontend_contract.py
```

or the most appropriate behavior test location.

Verify:

```text
GET /PSSM_GREMLIN/dashboard
→ temporary redirect
→ Location: /compute/dashboard

GET /PSSM_GREMLIN/create_task
→ temporary redirect
→ Location: /compute/create_task?task_type=gremlin
```

Keep legacy static assets and unknown legacy presentation paths unavailable unless explicitly required.

Do not weaken the presentation ownership boundary.

---

# 26. Tests — Runner Cardinality

Add browser/component behavior coverage where practical for:

```text
1 enabled method
few enabled methods
many enabled methods
```

Verify layout behavior rather than literal CSS source.

The test should protect:

```text
usable catalog
no pathological empty column
no clipped controls
meaningful density behavior
```

not a particular implementation such as a specific `grid-template-columns` string.

---

# 27. Documentation

Update:

```text
docs/developer-guide/frontend-design-language.md
```

to reflect the corrected design language.

Important changes include:

```text
Scientific workstation × quiet editorial clarity
neutral dark canvas
cyan/blue identity
green reserved primarily for semantic success
modern sans application typography
serif optional and limited
whitespace before hairlines
```

Do not leave PR35 documentation describing behavior that no longer exists.

Document legacy browser redirects only if there is an existing appropriate user/operator page.

Do not create a new root-level compatibility guide.

Keep documentation concise.

---

# 28. Implementation State

Update `IMPLEMENTATION_STATE.md` as work progresses.

Record:

```text
starting SHA
frontend-design skill usage
baseline pages captured
whether the active agent could directly inspect screenshots
foundation changes
page changes
single-action submission status
legacy redirect status
browser acceptance
test results
known deferred issues
```

Do not fill it with minute-by-minute diary entries.

It should remain a useful execution record.

---

# 29. Required Validation

Run focused checks during implementation.

From `frontend/`:

```bash
npm run typecheck
npm test
npm run build
```

Run focused server/frontend contracts:

```bash
python -m pytest tests/server/test_application_frontend_contract.py -v
python -m pytest tests/test_playwright_application.py -v
```

Run other focused browser suites affected by changed pages.

Before delivery, follow the repository's required gates from `CLAUDE.md`:

```bash
make test
make test-cov
```

For browser-facing work:

```bash
make test-browser
```

Because this change also modifies Flask browser routes and the production frontend bundle, run the relevant full-stack gate when the 309 environment can support it:

```bash
make test-docker-full-stack
```

If documentation changes:

```bash
mkdocs build --strict
```

Do not declare a gate successful if it was skipped.

If a gate cannot run because of the temporary 309 environment, record exactly:

```text
which gate
why
what narrower evidence passed
what remains to run later
```

Do not make unrelated code changes merely to force an environment-specific test to pass.

---

# 30. Resource Constraint

The current development host is the temporary 2019 Dell 309 workstation.

Treat its limited resources as a deployment constraint, not a product constraint.

Currently only PSSM-GREMLIN is enabled.

Do not:

```text
build GPU fleet images
remove unavailable Runner definitions
hide repository capability permanently
special-case "309" in product code
```

UI logic should continue to derive actual enabled/available Runner state from canonical APIs.

---

# 31. Security and Correctness

Preserve:

```text
authentication
authorization
safe return_to handling
Runner access policies
same-origin frontend assets
CSP
server-side validation
preflight semantics
admission semantics
task idempotency behavior
```

Single-click submission must not weaken server-side safeguards.

Legacy redirects must not create open redirects.

Never interpolate untrusted path/query data into redirect destinations for these fixed mappings.

---

# 32. Subtraction Pass

Before final review, inspect what this work made obsolete.

Likely candidates include:

```text
Review-only button state
Review again state
review-specific copy
review-step assumptions in tests
obsolete visual tokens
unused serif application rules
duplicated success/accent roles
unnecessary full-width separators
```

Delete superseded code instead of retaining parallel behavior.

Do not leave:

```text
old Review path
+
new Run path
```

behind feature flags or compatibility aliases.

---

# 33. Final Review Pass

Before opening the PR:

1. Ensure clean intentional diff.
2. Inspect every changed file.
3. Run one dedicated visual review using `frontend-design`.
4. Run one behavior/correctness review.
5. Re-render the real pages.
6. Inspect dark mode again after all fixes.
7. Inspect narrow/mobile again.
8. Verify the one-click task flow.
9. Verify the two legacy redirects.
10. Verify one-runner Catalog behavior.
11. Run final tests against the exact final HEAD.
12. Perform the subtraction pass.
13. Commit only coherent changes.

Do not repeatedly trigger automated review after every small fix.

Batch valid findings and re-review only after meaningful changes.

---

# 34. Acceptance Criteria

The work is complete only when all applicable statements are true.

## Visual foundation

- [ ] `frontend-design` was loaded and used before coding.
- [ ] Current live/local UI was rendered before changes.
- [ ] Baseline screenshots were captured.
- [ ] The agent directly inspected screenshots if its environment supported image understanding.
- [ ] If image understanding was unavailable, that limitation was explicitly recorded.
- [ ] Dark mode no longer has a pervasive green cast.
- [ ] Dark canvas and surfaces are neutral blue-black/graphite rather than green-black.
- [ ] Brand accent and success colour have distinct semantic roles.
- [ ] Application headings no longer accidentally depend on Georgia for identity.
- [ ] Application surfaces use a modern sans hierarchy.
- [ ] Hairlines are not being used as the primary page-layout mechanism.
- [ ] Light mode remains coherent.
- [ ] Dark mode remains coherent.

## Product identity

- [ ] Home clearly identifies REvoCompute first.
- [ ] REvoDesign remains visible as the related design ecosystem.
- [ ] Home copy is materially less repetitive.
- [ ] The scientific visual motif explains REvoCompute rather than only REvoDesign.
- [ ] Agent capability remains discoverable without dominating the Hero.

## App shell

- [ ] REvoCompute brand returns to `/`.
- [ ] `New task` reads as an action rather than an equal destination.
- [ ] Header remains compact and usable.
- [ ] Desktop and mobile navigation remain functional.

## Runner Catalog

- [ ] One-runner deployment looks intentional.
- [ ] Few-runner deployment looks intentional.
- [ ] Many-runner deployment remains usable.
- [ ] UI distinguishes deployment availability from global product capability.
- [ ] Density controls are meaningful rather than ornamental.

## Create Task

- [ ] Primary action is `Run task`.
- [ ] One click performs local validation.
- [ ] One click performs server preflight.
- [ ] Valid preflight automatically continues to submit.
- [ ] No second confirmation click is required.
- [ ] Preflight failure never submits.
- [ ] Busy state spans preflight through submission.
- [ ] Duplicate clicking cannot queue duplicate submissions through the UI.
- [ ] Right rail is a Task Snapshot, not a wizard Review step.
- [ ] Obsolete Review-specific copy is removed.
- [ ] PSSM-GREMLIN input UI is less repetitive without weakening contract clarity.

> The `review` workspace capability was removed rather than reworded. The right
> rail is a Task Snapshot built from the collected capability summaries, and no
> task declares a review step, so the protocol column no longer duplicates the
> rail. Core dropped the `plugin: review` allow-list entry and the
> last-capability-must-be-review rule in the same change; the 55 runner task
> manifests lost their review step.

## Legacy paths

- [ ] `/PSSM_GREMLIN/dashboard` redirects to `/compute/dashboard`.
- [ ] `/PSSM_GREMLIN/create_task` redirects to `/compute/create_task?task_type=gremlin`.
- [ ] Redirects are application-owned.
- [ ] Redirects are temporary during migration.
- [ ] No wildcard legacy redirect exists.
- [ ] Unknown/deleted legacy frontend assets remain unavailable.

## Other pages

- [ ] Dashboard remains dense and utilitarian.
- [ ] Runner Detail remains scientifically informative.
- [ ] Result Workspace architecture is unchanged.
- [ ] PSSM-GREMLIN result remains easy to inspect.
- [ ] Profile/Admin/Auth share the corrected visual foundation.
- [ ] API Docs remain usable.
- [ ] Terms remain readable.

## Responsive/accessibility

- [ ] Desktop checked.
- [ ] Narrow/mobile checked.
- [ ] Light checked.
- [ ] Dark checked.
- [ ] Keyboard navigation preserved.
- [ ] Focus states preserved.
- [ ] Reduced motion preserved.
- [ ] No new horizontal overflow.
- [ ] Contrast remains acceptable.

## Verification

- [ ] `npm run typecheck`
- [ ] `npm test`
- [ ] `npm run build`
- [ ] focused server contract tests
- [ ] focused Playwright application tests
- [ ] `make test`
- [ ] `make test-cov`
- [ ] `make test-browser`
- [ ] relevant full-stack test, or explicit environment limitation recorded
- [ ] `mkdocs build --strict` if docs changed
- [ ] final screenshots captured
- [ ] final visual review completed
- [ ] subtraction pass completed
- [ ] final HEAD clean and reviewable

---

# 35. Delivery

Keep this as one coherent production-polish PR.

A reasonable commit structure is:

```text
1. visual foundation: palette, typography, shared shell
2. product surfaces: Home, Runner Catalog, Dashboard
3. create-task: single-action submission and interaction polish
4. compatibility: explicit legacy browser redirects
5. result/supporting surface polish and responsive fixes
6. tests/docs/final cleanup
```

The exact commit count is not important.

Coherence is.

Do not mix GREMLIN_LH scientific reconstruction into this branch.

The final PR description should explicitly state that this work:

```text
does not reopen frontend architecture
does not change Runner scientific behavior
does not reduce server-side validation
does not make 309 deployment constraints permanent
```

and should summarize:

```text
visual foundation correction
REvoCompute-first identity
single-action task submission
one/few/many Runner UX
legacy browser redirects
real browser acceptance
```

