# Visual Refinement — Restore REvoCompute Scientific Identity

## Objective

PR32–PR34 completed the frontend/backend Presentation ownership cutover.

That architecture is now canonical.

**Do not continue the frontend/backend architecture refactor.**

This work has a different purpose:

> Restore visual hierarchy, warmth, scientific character, and a recognizable REvoCompute design language on top of the new frontend architecture.

The current frontend is structurally strong but visually too flat, industrial, and generic. It reads like a scientific SaaS/admin console rather than a distinctive computational biology workbench.

The previous generation had meaningful aesthetic strengths:

- soft scientific canvas;
- warm off-white surfaces;
- restrained teal identity;
- serif/sans typographic contrast;
- generous breathing room;
- meaningful semantic surfaces;
- rounded but not playful geometry;
- scientific result emphasis;
- quiet metadata;
- subtle depth;
- stronger visual hierarchy.

These should be treated as **design heritage**, not restored as legacy implementation.

The intended result is:

```text
old visual strengths
        +
current frontend architecture
        +
new frontend-design critique
        =
REvoCompute design language
```

---

# 0. Fresh Session Bootstrap

Start from a fresh agent session and current remote `main`.

Before making changes:

1. Fetch latest remote.
2. Check out `main`.
3. Confirm the PR34 final presentation cutover is present.
4. Record exact starting SHA.
5. Ensure clean worktree.
6. Read:
   - `CLAUDE.md`
   - `AGENTS.md`
   - current frontend architecture docs
   - `IMPLEMENTATION_STATE.md`
   - relevant visual/frontend documentation.
7. Inspect current frontend CSS and presentation structure.
8. Inspect the historical pre-cutover CSS and representative screenshots.
9. Do not revive deleted Jinja templates or old page JavaScript.

This is a frontend presentation task.

---

# 1. Mandatory Design Review Before Coding

## 1.1 Use `frontend-design`

If the current agent environment provides the `frontend-design` skill:

**Load and follow it before editing any visual code.**

Use it to critique:

- current production deployment;
- supplied screenshots;
- historical screenshots;
- current CSS;
- historical CSS;
- visual hierarchy;
- typography;
- density;
- scientific workspace ergonomics;
- brand coherence.

Do not ask `frontend-design` to invent a fashionable dashboard from scratch.

Its design exploration must be constrained by REvoCompute's existing design heritage.

If the skill is unavailable, explicitly record that fact and perform the same critique manually before implementation.

---

# 2. Reference Set

Use both current and historical implementations as evidence.

## Current reference

Inspect current:

```text
frontend/src/styles/app.css
frontend/src/features/results/results.css
frontend/src/features/create-task/create-task.css
frontend/src/features/home/*
frontend/src/features/admin/*
frontend/src/features/profile/*
frontend/src/features/auth/*
```

Also inspect the current deployed site.

## Historical reference

Inspect the pre-frontend-cutover versions of:

```text
revocompute/static/css/base.css
revocompute/static/css/task-results.css
revocompute/static/css/dashboard.css
revocompute/static/css/create-task.css
revocompute/static/css/runners.css
revocompute/static/css/index.css
```

A suitable historical reference is the repository state immediately before the PR32 frontend cutover.

Do not copy entire historical CSS files into the new frontend.

Extract design principles and useful primitives only.

---

# 3. Core Design Thesis

Define REvoCompute visually as:

> **Scientific instrument × editorial laboratory**

The product should feel:

```text
precise
scientific
quiet
purposeful
editorial
slightly tactile
trustworthy
human-guided
```

It should not feel:

```text
generic SaaS
enterprise CRM
developer IDE
cloud management console
neon AI product
glassmorphic
dashboard card wall
template marketplace
```

---

# 4. Primary Design Principle

## Do not decorate everything. Restore hierarchy.

The current interface relies too heavily on:

```text
1px borders
flat rectangles
uniform spacing
uniform visual weight
small radius
```

Do not solve this by applying shadows and 18px radius everywhere.

Instead:

```text
important semantic object
→ clear surface

secondary supporting information
→ quieter surface/background

metadata
→ visually recedes

scientific artifact
→ receives priority

normal state
→ quiet

warning/failure
→ receives attention
```

---

# 5. Information Hierarchy Principle

For every page, ask:

> What is the user actually here to see or do?

Visual prominence must follow that answer.

Examples:

## Result

```text
Task identity
    ↓
Scientific result
    ↔
Supporting artifacts
```

Not:

```text
Task
Run outcome
Manifest validation
Generic description
Result
```

## Create Task

```text
Selected method
    ↓
Input
    ↓
Parameters
    ↓
Review
    ↓
Submit
```

Not:

```text
Method documentation
Method specification
Input
Debug-like validation rail
```

## Runner Catalog

```text
Scientific capability
    ↓
Method
    ↓
availability / compute / access
```

Not:

```text
46 equal database records
```

---

# 6. Remove Low-Information Copy

Audit UI copy aggressively.

Every visible sentence should answer a user question.

Remove or demote text such as:

```text
Expected Outputs Found
A filtered ensemble of sampled protein conformations and supporting artifacts.
The output check confirms configured files and table fields—not scientific or experimental validity.
```

when it does not help the normal user understand the result.

Internal implementation validation belongs in:

```text
Files & diagnostics
Result integrity
Execution
debug/diagnostic surfaces
```

not the primary scientific result surface.

---

# 7. Result Status Policy

Normal success should be visually quiet.

## Successful

Prefer:

```text
✓ Finished
```

inside task identity/header.

Do not give successful manifest validation an entire panel.

## Partial / warning

Show a compact warning:

```text
Completed with missing expected artifacts
```

with actionable details.

## Failed

Failure may legitimately take over the principal result area:

```text
Task failed

<meaningful reason>

View execution log
Return to configuration
```

Abnormal states deserve visual weight.

Normal states do not.

---

# 8. Design Tokens

Do not replace the existing brand palette.

The current color DNA is good.

Retain/reconcile approximately:

```text
background neutral/mint
warm off-white surface
deep charcoal ink
muted grey-green
deep teal
secondary green-teal
amber warning
restrained red failure
```

The problem is not the colors themselves but their current usage.

---

# 9. Canvas

The current application canvas is too uniformly grey-green.

Reintroduce a very subtle ambient background based on the historical design.

Historical inspiration included:

```css
radial-gradient(...)
linear-gradient(...)
```

but use substantially restrained intensity for long-running application workspaces.

Desired behavior:

```text
public/editorial surfaces
→ richer ambient canvas allowed

application workspaces
→ cleaner neutral canvas with subtle tint

scientific stage
→ stable high-contrast surface
```

Do not introduce distracting decorative gradients behind Mol*, tables, plots, or forms.

---

# 10. Surfaces

Create a small shared vocabulary.

Suggested conceptual primitives:

```text
surface
raised-surface
scientific-stage
side-rail
page-hero
dialog-surface
quiet-panel
```

Do not necessarily create literal utility classes for all of these if feature-local CSS is clearer.

Approximate visual qualities:

```text
semantic surface:
  radius ~ 12–18px

controls:
  radius ~ 7–10px

small utility:
  radius ~ 5–7px

pill/status:
  radius 999px
```

Use subtle shadows only where they communicate elevation or grouping.

---

# 11. Shadow Language

Historical REvoCompute used tasteful shadows successfully.

Restore a restrained hierarchy, e.g.:

```text
surface shadow
dialog shadow
hero/public visual shadow
```

Avoid:

```text
shadow on every card
multiple heavy shadows
glowing borders
neon elevation
```

---

# 12. Typography

Retain the existing design heritage:

```text
Source Serif 4
→ scientific titles
→ important page titles
→ editorial statements
→ result headings

IBM Plex Sans
→ UI
→ controls
→ body
→ forms
→ tables
```

Monospace only for genuine machine identity:

```text
task IDs
runner IDs
file names
hashes
code/config
```

Do not use monospace merely to communicate "technology".

---

# 13. Typography Scale

Re-establish stronger hierarchy.

Conceptual scale:

```text
Public display     48–80px where appropriate
Page title          30–40px
Scientific title    22–30px
Section heading     18–24px
UI subsection       15–18px
Body                14–16px
Metadata            12–13px
Micro               11–12px
```

Exact values may vary responsively.

Avoid a page where nearly everything sits between 12px and 16px.

---

# 14. Spacing Rhythm

Restore breathing room.

Create a coherent spacing rhythm rather than feature-specific arbitrary values.

Prioritize:

```text
page boundary
section separation
semantic surface padding
control grouping
metadata proximity
```

Do not increase whitespace indiscriminately.

Dashboard/table-heavy surfaces should remain dense.

---

# 15. Control Language

The current 3–4px rectangular control language contributes strongly to the industrial feel.

Rework:

```text
primary button
secondary button
quiet button
icon button
danger action
segmented control
input/select
tabs
status badge
```

Controls should feel related without being identical rectangles.

Primary/secondary buttons may use softer curvature.

Tiny utility controls should remain compact.

---

# 16. Interaction Motion

Use motion sparingly.

Allowed:

```text
small hover lift
surface transition
tab/selection transition
route/section fade
dialog enter/exit
```

Do not add:

```text
scroll-jacking
large parallax
decorative particle animation
constant pulsing
AI-style gradient animation
```

Respect `prefers-reduced-motion`.

---

# 17. Result Workspace — Highest Priority

The Result Workspace is the most important visual surface in REvoCompute.

Do not redesign its architecture.

Retain:

```text
ResultManifest semantics
Storyboards
Mol*
file rail
artifact preview
tabs
downloads
diagnostics
fullscreen
```

Change presentation only.

---

# 18. Remove the Result Outcome Block Concept

Do not restore the historical Run Outcome panel.

Normal result hierarchy should be:

```text
Task identity / concise status
             ↓
Scientific result
             ↔
Files & diagnostics
```

Success metadata should not interrupt the user before the result.

---

# 19. Result Header

Make the header concise and meaningful.

Example target hierarchy:

```text
BIOEMU                                  ✓ Finished

Scp2
91 sampled conformations

89def225…                         Dashboard   Refresh
```

or an equivalent appropriate structure.

Do not visually emphasize full task hashes or input filenames unless scientifically meaningful.

Machine identity belongs in metadata.

---

# 20. Scientific Result Surface

The primary artifact should become the strongest surface after the header.

For molecular results:

```text
semantic result title
small useful context
Mol* scientific stage
relevant scientific controls
```

Avoid surrounding the viewer with excessive web-page chrome.

The viewer should feel like a scientific instrument embedded in the product.

---

# 21. Mol* Toolbar

Audit the current row of buttons.

Reduce visual clutter through meaningful grouping.

Conceptually:

```text
Representation
Color
Selection
View
```

with high-frequency actions visible and secondary presets grouped.

Do not remove functionality.

Do not redesign Mol* integration.

---

# 22. Files & Diagnostics Rail

Preserve the file rail architecture.

Improve hierarchy so users see scientific semantics before raw storage topology where ResultManifest provides enough information.

Prefer conceptual grouping such as:

```text
Results
Supporting files
Inputs
Diagnostics
Execution
All files
```

when supported by canonical result semantics.

Do not infer scientific meaning from arbitrary path names in the frontend.

If the manifest cannot support semantic grouping, keep the raw tree rather than inventing semantics.

---

# 23. Result Integrity

If expected-file validation must remain visible, place it under diagnostics:

```text
Result integrity
✓ Declared artifacts present
```

Do not present it as a scientific conclusion.

---

# 24. Result Responsive Behavior

Preserve:

```text
desktop scientific stage + rail
collapsed rail
mobile stacked layout
fullscreen Mol*
```

Do not compromise scientific viewport size merely to make surfaces prettier.

---

# 25. Create Task — Second Priority

Do not change the PR33 Create Task architecture.

Retain:

```text
schema-driven controls
Runner-owned workspace plugin contract
preflight
access/readiness
review rail
submission snapshot
```

Improve hierarchy only.

---

# 26. Create Task Method Header

Reduce the dominance of:

```text
Use when
Input
Output
Compute
```

These are useful context but should not visually compete with the active task configuration.

Present them as concise method context, possibly collapsible or quieter.

---

# 27. Create Task Workflow

Visually establish:

```text
01 Input
02 Parameters
03 Review
```

or the actual workflow declared by the Runner.

The current actionable step must receive more visual weight than method documentation.

Do not implement a new page-based wizard.

The current single-workbench architecture remains canonical.

---

# 28. Review Rail

Transform the current review panel from a validation/debug appearance into a task snapshot.

Conceptually:

```text
TASK SNAPSHOT

AlphaFold 3
GPU · Access granted

Input
1 JSON document

Parameters
Defaults

────────────

1 issue
Add AlphaFold 3 JSON

[ Review task ]
```

Errors remain clear and accessible.

---

# 29. Runner Catalog

Keep the existing category organization and filtering architecture.

Do not return to the old backend catalog.

Reduce the CMDB/card-wall appearance.

---

# 30. Runner Density Modes

Make density meaningful.

## Compact

Aim toward a scientific directory/list language:

```text
BioEmu
Conformational ensemble sampling · GPU
```

with restrained separators/surfaces.

## Comfortable

Allow richer surfaces:

```text
summary
capabilities
availability
access
```

Do not simply change card height.

---

# 31. Runner Categories

Category headers should contribute to the scientific information architecture.

Use stronger editorial typography and spacing.

Methods in different scientific categories should feel grouped intentionally, not merely sorted.

---

# 32. Dashboard

Keep Dashboard highly utilitarian.

Do not make it a decorative showcase.

Improve:

```text
surface softness
radius
typographic hierarchy
toolbar grouping
summary stats
status legibility
spacing
```

Preserve:

```text
high density
table mode
compact mode
batch actions
fast scanning
```

Dashboard may remain the most "instrument-like" part of the product.

---

# 33. Dashboard Stats

Reduce grid-border dependence.

Use typography and spacing more strongly.

Do not turn every statistic into a large KPI marketing card.

---

# 34. Home Page — Full Visual Reassessment

Do not assume the current homepage is acceptable.

Use `frontend-design` to redesign/refine it substantially while preserving the product story.

The current page is too flat and visually forgettable despite its editorial layout.

---

# 35. Home Page Identity

The public landing page should be the clearest expression of REvoDesign/REvoCompute design language.

It should communicate:

```text
human-guided protein engineering
scientific evidence
structural biology
evolution
computation
connected REvoDesign ↔ REvoCompute workflow
agent-accessible computation
```

without feeling like generic AI marketing.

---

# 36. Home Hero

Reconsider:

```text
composition
scale
negative space
scientific visual motif
brand relationship
CTA hierarchy
agent entry
```

Do not rely only on oversized typography over an empty pale-green canvas.

The hero needs a visual memory point.

---

# 37. Scientific Visual Motifs

If the new home design needs visual elements, prefer motifs derived from scientific work:

```text
molecular geometry
residue/sequence motifs
evidence relationships
structure/evolution/computation pathways
workflow traces
scientific annotation
```

Avoid:

```text
generic AI blobs
abstract neon mesh
random gradient spheres
stock molecule imagery
```

Keep visuals lightweight and performant.

---

# 38. REvoDesign / REvoCompute Relationship

Clarify the product relationship visually.

REvoDesign:

```text
human-guided design
evidence synthesis
interactive reasoning
```

REvoCompute:

```text
managed computation
reproducible scientific execution
result exploration
```

They should feel like one ecosystem without becoming visually identical products.

---

# 39. Profile / Admin / Auth

These are lower-priority refinement surfaces.

Apply the shared design language consistently.

Do not introduce unnecessary visual personality.

Prioritize:

```text
clarity
form readability
danger-action clarity
dense admin efficiency
consistent dialogs
consistent inputs
```

Admin should remain operationally efficient.

---

# 40. API Docs / Legal

Keep these simple.

API Docs should primarily preserve Swagger usability.

Terms should prioritize reading comfort.

Do not over-design them.

---

# 41. Dark Mode

All visual changes must have intentional dark-mode equivalents.

Do not rely on automatic inversion.

Check:

```text
canvas
surface contrast
shadows
borders
Mol* surrounding UI
badges
alerts
inputs
dialogs
scientific plots/tables
```

Dark mode should retain REvoCompute identity rather than becoming generic charcoal UI.

---

# 42. Accessibility

Preserve:

```text
keyboard navigation
focus-visible
semantic headings
contrast
dialog accessibility
form labels
tab semantics
reduced motion
```

Aesthetic changes must not reduce functional accessibility.

---

# 43. CSS Architecture

Do not reintroduce legacy CSS ownership.

Historical CSS is read-only design evidence.

New styling stays under:

```text
frontend/src/styles/
frontend/src/features/*/
```

Prefer:

```text
shared tokens/primitives
+
feature-local layout
```

Avoid a new giant global stylesheet containing all page-specific rules.

---

# 44. No CSS Framework

Do not introduce:

```text
Tailwind
Bootstrap
Material UI
Chakra
Ant Design
new component library
```

The point is to develop REvoCompute's own design language.

---

# 45. No Application Framework Change

Do not introduce React/Vue/Svelte/etc. for visual refinement.

Mol*'s internal React dependency remains an implementation detail.

Keep the existing TypeScript frontend architecture.

---

# 46. No Architecture Work

Strictly prohibited unless a real correctness bug is discovered:

```text
new API architecture
new router architecture
backend ownership changes
Task lifecycle redesign
Runner contract redesign
ResultManifest redesign
authentication redesign
repository split
service split
CORS
GraphQL
WebSockets
```

If a visual improvement appears to require architecture work, stop and reconsider the visual solution.

---

# 47. Microcopy Audit

Perform a page-by-page copy audit.

Classify visible text as:

```text
identity
scientific context
action guidance
status
diagnostic
implementation detail
redundant
```

Remove or demote the last two categories.

Particularly inspect:

```text
Result status copy
Result descriptions
Create Task helper copy
Runner cards
empty states
validation messages
admin explanations
```

Do not remove scientifically meaningful guidance.

---

# 48. Visual Archaeology Deliverable

Before significant implementation, produce a short internal design note documenting:

```text
What the historical design did well
What the current design improved
What was lost during cutover
What should return
What should stay dead
```

This does not need to become a large permanent architecture document.

Keep it concise and actionable.

---

# 49. Design Language Deliverable

Document the final lightweight design language.

At minimum record:

```text
color roles
surface roles
typography roles
radius scale
shadow scale
spacing principles
control hierarchy
status hierarchy
scientific workspace principles
```

Do not build a heavyweight design-system project.

This is guidance for future frontend work.

---

# 50. Implementation Order

Perform work in three implementation passes.

## Pass 1 — Foundation

Refine:

```text
canvas
tokens
surface language
radius
shadow
typography
spacing
buttons
inputs
dialogs
header/navigation
```

Then visually verify all routes for regressions.

## Pass 2 — Scientific Workspaces

Prioritize:

```text
Result
Mol*
Files rail
Create Task
Review rail
scientific tables/plots/matrices
```

Perform microcopy reduction here.

## Pass 3 — Utility and Public Surfaces

Refine:

```text
Home
Runner Catalog
Dashboard
Profile
Admin
Auth
API Docs
Legal
```

Home deserves deeper design work than the other utility surfaces.

---

# 51. Screenshot-Based Review

Capture before/after screenshots for at least:

```text
Home
Runner Catalog
Create Task
Result — molecular structure
Result — trajectory/ensemble
Dashboard
Profile
Admin
```

Use consistent desktop dimensions.

Also inspect representative narrow/mobile viewport.

Compare against:

```text
historical implementation
current production
new design
```

Do not rely only on unit/browser tests for visual quality.

---

# 52. Functional Regression Rule

Visual refinement must not change scientific/application behavior.

Preserve all current browser contracts.

Pay special attention to:

```text
Mol* selection
fullscreen
downloads
file rail collapse
Runner filters
Create Task validation
workspace plugins
Dashboard actions
Admin destructive actions
Auth forms
dark mode
responsive navigation
```

---

# 53. Performance

Do not significantly increase initial bundle size.

Avoid large visual libraries.

Do not preload Mol* or heavy scientific features merely for aesthetics.

Any home visual should be lightweight.

---

# 54. Testing

Keep existing:

```text
frontend typecheck
frontend unit tests
browser contracts
strict CSP Mol*
backend tests
full-stack Compose
documentation
```

Add tests only where presentation changes create meaningful interaction behavior.

Do not write brittle pixel-perfect tests.

---

# 55. Visual Acceptance Criteria

This work is complete when:

1. REvoCompute no longer reads visually as generic enterprise SaaS.
2. Home has a recognizable visual identity and memory point.
3. Application and Home clearly belong to the same product ecosystem.
4. Result scientific artifacts dominate normal completed-task pages.
5. Normal successful status is visually quiet.
6. Low-information result copy is removed or demoted.
7. Files/diagnostics are clearly supporting material.
8. Create Task visually prioritizes actual configuration work.
9. Review rail reads as a task snapshot rather than debug output.
10. Runner Catalog feels like a scientific method directory, not an inventory database.
11. Dashboard remains efficient and dense.
12. Semantic surfaces replace excessive border-based grouping.
13. Typography hierarchy is obvious.
14. Controls no longer share one generic 4px rectangular language.
15. Historical design strengths are visibly recognizable without restoring legacy DOM/CSS.
16. Dark mode remains intentional.
17. Mobile layouts remain usable.
18. Accessibility is not reduced.
19. No backend/API/Runner architecture work was introduced.
20. All required CI remains green.

---

# 56. Stop Rule

This PR is visual/product refinement.

Do not allow it to become another architecture project.

When visual hierarchy, design language, and major page quality are substantially improved:

**stop.**

Further micro-polish can happen naturally during future feature work.

The project priority after this work remains:

```text
Runner fleet readiness
scientific correctness
target-host validation
production stability
scientific UX
```

not perpetual frontend restructuring.