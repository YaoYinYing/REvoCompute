# REvoCompute UI Simplification + Result Viewer Consolidation

## Goal

Simplify REvoCompute's primary user-facing workflows and make the application scale naturally from mobile screens to ultra-wide workstations, while consolidating the result viewer into a persistent, fast, scientifically correct structure-preview architecture.

This work should **remove unfinished or over-designed product paths**, not create another UI framework.

The main outcomes are:

1. reorganize Profile into a real settings/navigation surface;
2. simplify Dashboard controls and make selection state always visible;
3. establish a shared responsive layout model including ultra-wide displays;
4. simplify Runner catalog density and access presentation;
5. aggressively simplify Create Task by removing unnecessary side panels, artifact reuse, and unfinished JAAG builders;
6. fix known theme inconsistencies;
7. add subtle shared layout transitions;
8. rebuild the structure result viewer around a persistent viewer lifecycle, cache/prefetch, and explicit confidence metadata;
9. simplify HTML result handling;
10. keep all existing Runner scientific contracts and backend execution behavior unchanged unless explicitly listed below.

---

# Design principles

## Deletion first

Prefer deleting:

* unused UI states;
* unfinished workflows;
* duplicated presentation logic;
* artifact-reuse UI and endpoints if no remaining consumer exists;
* JAAG builder integration;
* HTML execution/embedding logic;
* unnecessary layout wrappers;
* duplicated responsive CSS.

Do not replace deleted complexity with a new generalized framework.

---

## Core remains authoritative

Do not move TaskType, Runner access, result metadata, or scientific semantics into frontend code.

Frontend should consume:

```text
TaskType projection
Runner access projection
result manifest / expected files
result artifact metadata
```

Do not create another client-side schema.

---

## Shared UI primitives, not a component framework

Reuse existing CSS/JS primitives where reasonable.

It is acceptable to introduce a few small shared concepts such as:

```text
application shell width
workspace shell width
layout transition helper
structure viewer controller
```

Do not introduce React/Vue/Svelte or a client-side state framework.

---

# Phase 1 — Application shell and ultra-wide layout foundation

## 1. Replace fixed page-width assumptions

The current shared shell is approximately:

```css
.page {
  width: min(75rem, calc(100% - 2rem));
}

.page-wide {
  width: min(90rem, calc(100% - 2rem));
}
```

This leaves excessive unused horizontal space on 2560px / 3440px displays.

Introduce a small shared layout vocabulary.

Suggested conceptual tiers:

```text
reading
application
workspace
ultra-wide
```

For example:

```css
--shell-reading: 75rem;
--shell-app: 90rem;
--shell-workspace: 120rem;
--shell-ultrawide: 132rem;
```

Exact values may be adjusted after browser inspection.

Do not make prose paragraphs arbitrarily wide.

---

## 2. Assign pages by purpose

Use wider shells only where additional horizontal space is useful.

Expected intent:

```text
Landing          wide / adaptive
Profile          application
Runners          ultra-wide
Create Task      ultra-wide
Dashboard        ultra-wide
Result page      ultra-wide
API docs         wide
Admin pages      workspace
```

Content such as prose descriptions should continue using readable inner widths.

---

## 3. Add ultra-wide browser contracts

Add browser coverage for at least:

```text
1440x1000
1920x1080
2560x1440
3440x1440
```

Verify:

* no giant accidental dead margins;
* useful grids gain columns where appropriate;
* controls do not stretch into unreadable shapes;
* prose remains constrained;
* no horizontal overflow;
* mobile/tablet behavior remains unchanged.

Extend the existing responsive/scalability Playwright tests rather than inventing a separate screenshot framework.

---

# Phase 2 — Shared layout transition

## 4. Add one lightweight transition primitive

Use subtle transitions for layout mode switches in:

```text
Dashboard
Runner catalog
Create Task
```

Preferred duration:

```text
160–220 ms
```

Recommended visual behavior:

```text
opacity
small translateY / translateX
very small scale if appropriate
```

Avoid large motion.

---

## 5. Respect reduced motion

All transition behavior must respect:

```css
@media (prefers-reduced-motion: reduce)
```

Transitions should become immediate or nearly immediate.

---

## 6. Progressive View Transition API support

If useful, optionally use:

```js
document.startViewTransition(...)
```

as progressive enhancement.

Do not require it.

Fallback must remain ordinary DOM update + CSS transition.

Do not create a compatibility abstraction larger than the animation itself.

---

# Phase 3 — Profile information architecture

## 7. Replace the Profile card grid with settings navigation

Current Profile already contains:

```text
Account
Runner Access
GPU Credits
Change Password
API Key
```

Reorganize this into:

```text
Profile
Security
API Key
Runner Access
GPU Credits
Metrics
```

Desktop:

```text
┌───────────────┬─────────────────────────────────────┐
│ navigation    │ active section                      │
│               │                                     │
│ Profile       │                                     │
│ Security      │                                     │
│ API Key       │                                     │
│ Runner Access │                                     │
│ GPU Credits   │                                     │
│ Metrics       │                                     │
└───────────────┴─────────────────────────────────────┘
```

The sidebar should be sticky where appropriate.

---

## 8. Mobile Profile navigation

On narrow screens, convert the sidebar into either:

```text
horizontal scrollable tabs
```

or another compact accessible navigation surface.

Do not hide sections behind an obscure hamburger menu.

---

## 9. Profile section ownership

### Profile

Show:

```text
username
email
full name
affiliation
position
PI / supervisor
role where useful
```

Do not mix password/API credentials into this section.

### Security

Move password management here.

Leave room for future session/security controls without inventing them now.

### API Key

Keep API-key lifecycle here:

```text
status
generate/regenerate
copy once
revoke
```

### Runner Access

See dedicated Runner Access work below.

### GPU Credits

Keep:

```text
allocation
adjustments
usage
remaining
recent ledger entries
GPU admission state
```

### Metrics

Implement lightweight user activity statistics.

---

# Phase 4 — User Metrics

## 10. Add user activity Metrics section

Do not build a new analytics subsystem or analytics database.

Aggregate existing persisted task/activity/resource information.

Initial useful metrics:

```text
tasks submitted
tasks completed
tasks failed
success rate
CPU task count
GPU task count
GPU minutes / credits used
Runner / TaskType usage distribution
total runtime where available
median runtime where meaningful
task activity over time
```

---

## 11. Time windows

Support bounded windows such as:

```text
7 days
30 days
90 days
quarter
custom bounded range
```

Weeks/months/quarters can be projections over the same query path.

Avoid separate endpoints for every time grouping if one bounded aggregation endpoint suffices.

---

## 12. Metrics visual presentation

Prefer:

```text
small KPI row
one activity-over-time chart
one Runner/TaskType distribution chart
compact table if needed
```

Do not turn Profile into an analytics dashboard.

Use existing frontend/chart capability if present.

Do not introduce a heavy charting framework solely for this section.

---

# Phase 5 — Dashboard controls redesign

## 13. Reorganize Dashboard control hierarchy

Current Dashboard controls should be reorganized into a more compact toolbar.

Suggested hierarchy:

```text
Search | Status | Runner/TaskType | Sort | View
```

Admin-only controls should remain clearly secondary.

Do not give every control a separate large boxed region.

---

## 14. Separate ordinary filtering from selection actions

Selection controls should not permanently occupy the primary filter toolbar.

When no rows are selected:

```text
selection action bar hidden/minimal
```

When rows are selected:

```text
N selected
Clear
Delete / admin actions
```

should appear as a contextual action bar.

---

## 15. Fix invisible table selection state

The current table view can hide the meaningful selection status.

The selected count must remain visible when table mode is active.

Recommended placement:

```text
directly above/below table header
```

or:

```text
small sticky contextual action bar
```

Do not place selection feedback in another distant panel.

---

## 16. Preserve view modes

Keep existing view modes unless one is genuinely unused:

```text
detailed/cards
compact
table
```

Apply the shared transition primitive when switching.

Do not rebuild task rendering from scratch.

---

# Phase 6 — Landing page theme fix

## 17. Fix `Connect an AI agent`

The `Connect an AI agent` card must follow the current theme.

Remove hard-coded dark presentation colors where present.

Use shared variables such as:

```text
--paper
--bg
--ink
--muted
--line
--accent
```

Light mode must render a genuinely light card.

Dark mode must remain coherent.

---

## 18. Add theme regression coverage

Add a browser assertion that:

```text
light theme card background != dark theme card background
```

and that foreground/background contrast remains sensible.

Do not rely solely on a screenshot.

---

# Phase 7 — Runner catalog density

## 19. Make Compact mode actually compact

Current compact cards still have approximately:

```css
min-height: 10.5rem
```

Remove unnecessary minimum-height pressure.

Compact mode should prioritize information density.

Possible behavior:

```text
smaller padding
smaller vertical gaps
1–2 line description clamp
smaller metadata spacing
compressed footer
no artificial bottom whitespace
```

Do not shrink click targets below accessible sizes.

---

## 20. Improve ultra-wide Runner grid

Allow more columns on wide/ultra-wide displays.

The grid should gain information density instead of simply expanding card width.

Avoid cards wider than useful reading width.

---

# Phase 8 — Runner Access UX

## 21. Redesign Profile Runner Access

Current access rendering is verbose and card-like.

Change it into a denser policy/state surface.

Each restricted Runner/policy should communicate:

```text
Runner / policy name
license / upstream restriction
current state
request status
expiry
eligibility/requestability
last relevant decision if available
action
```

Possible states:

```text
Granted
Requestable
Pending
Rejected
Expired
Restricted
```

---

## 22. Prioritize state over prose

Descriptions and license explanations should be secondary.

The primary question should be answerable immediately:

> Can I use this Runner right now?

Then:

> If not, what action is available?

---

## 23. Keep access policy semantics unchanged

Do not redesign:

```text
entitlement model
policy matching
request approval semantics
license enforcement
```

This is a presentation/efficiency redesign.

---

# Phase 9 — Create Task simplification

## 24. Remove the three-column experiment layout

Current desktop structure is approximately:

```text
protocol track
+
main form
+
readiness panel
```

Delete this layout.

The two narrow side columns consume substantial screen area without carrying enough information.

---

## 25. New Create Task hierarchy

Recommended structure:

```text
Method identity
Use when / Provide / Receive
Access status if restricted

small progress indicator / optional section navigation

┌────────────────────────────────────────────┐
│                                            │
│             MAIN EXPERIMENT FORM           │
│                                            │
└────────────────────────────────────────────┘

validation summary
method considerations

                                 Run experiment
```

The primary form should receive most of the available width.

---

## 26. Protocol track simplification

Replace the persistent vertical protocol rail with either:

```text
small horizontal step indicator
```

or no separate protocol track at all if headings already communicate the sections.

Do not preserve it merely because it already exists.

---

## 27. Fold readiness into the submission flow

Delete the standalone sticky readiness panel.

Show validation close to the Run action.

Example:

```text
✓ Inputs valid
✓ Parameters valid
✓ Runner ready
✓ Access granted

Method considerations ▾

[ Run experiment ]
```

Error rows should link/focus the relevant input when practical.

---

# Phase 10 — Remove artifact reuse

## 28. Remove artifact reuse from Create Task

Artifact reuse is currently an over-designed and incomplete product path.

Delete frontend support for:

```text
reusable_artifacts
"Or reuse an existing artifact"
artifact reference selectors
reusable-artifacts loading
```

The normal Create Task workflow becomes:

```text
upload/provide fresh inputs
→ validate
→ immutable task snapshot
→ submit
```

---

## 29. Remove dead backend/API paths where safe

Trace all consumers of:

```text
/compute/api/types/<task_type>/reusable-artifacts
```

and the associated artifact-reference submission path.

If no remaining product/API requirement exists, delete the endpoint and dead supporting logic.

Do not retain dormant code "for future workflows".

If another current API consumer genuinely relies on the endpoint, isolate that fact and document it before deciding whether the backend path remains.

Frontend reuse must still be removed.

---

## 30. Update documentation

Remove cross-task artifact reuse from current product documentation.

If composition is discussed as a future idea, explicitly label it as future/non-product work.

Do not retain a detailed speculative "Phase 6 cross-task composition" design as if it were current contract unless it still has an active implementation goal.

---

# Phase 11 — Remove JAAG Builder integration

## 31. Remove unfinished `jaag-builder`

Remove the unfinished/misleading JAAG input builder integration from all Task contracts.

At minimum verify AlphaFold3 currently declares:

```yaml
plugin: jaag-builder
```

Remove such entries.

---

## 32. Remove dead JAAG frontend/plugin implementation

If `jaag-builder` has a dedicated plugin implementation and no remaining consumers:

```text
delete plugin
delete JS/CSS
delete plugin registration
delete tests
delete docs
```

Do not keep an unused plugin skeleton.

---

## 33. Replace with external helper link

For TaskTypes where JAAG is useful, add ordinary guidance such as:

```text
Need to prepare an input file?
Create one with JAAG ↗
```

Target:

```text
https://jaag.bio-tools.yaoyy.moe/
```

This is an external helper, not part of the form contract.

Use `target="_blank"` / `noopener noreferrer` as appropriate.

---

# Phase 12 — Result viewer architecture

## 34. Treat structure switching as state change, not viewer recreation

The core invariant must become:

```text
switch artifact != recreate Mol*
```

Create one persistent viewer host for the active result page.

Do not recreate/reload the entire viewer iframe/plugin for every structure selection.

---

## 35. Introduce a small StructureViewerController

A small controller may own:

```text
persistent viewer lifecycle
current artifact
load generation / cancellation
structure text cache
prefetch
style preset
color mode
fallback mode
```

Keep it focused.

Do not create a general plugin framework around it.

---

## 36. Persistent Mol* lifecycle

Desired flow:

```text
open Result page
    ↓
initialize Mol* once
    ↓
select structure A
    ↓
load A into existing Mol*
    ↓
select structure B
    ↓
replace/update hierarchy inside same Mol*
```

Mol* iframe/browser bundle initialization must not repeat on each file change.

---

## 37. Preserve cancellation correctness

Rapid file switching must not allow an old fetch/load operation to replace a newer selection.

Keep or improve the existing generation/AbortController behavior.

Test:

```text
A selected
B selected immediately
A response finishes after B
→ B remains active
```

---

# Phase 13 — Structure cache and prefetch

## 38. Keep bounded caching

Current cache is approximately:

```text
3 files
60 MB
```

Retain a bounded cache concept.

Consider true LRU behavior rather than simple recreation.

Exact values may remain conservative.

Do not allow unbounded browser memory growth.

---

## 39. Prefetch nearby structure artifacts

When opening one structure, opportunistically prefetch a small number of likely-next structures.

For example:

```text
selected
previous
next
```

or first few siblings.

Prefetch must remain bounded and cancellable.

Do not download every model from a 100-model result.

---

## 40. Cache identity

Cache by a stable artifact identity such as:

```text
task id
artifact path
artifact hash if available
```

Do not key only by display filename.

---

# Phase 14 — Confidence / pLDDT semantics

## 41. Do not infer pLDDT from CIF alone

A `.cif` file is not evidence that B-factor values are pLDDT.

Preserve explicit result metadata such as:

```text
confidence_encoding: plddt_bfactor
```

Only expose pLDDT coloring when the Runner/result contract explicitly declares compatible encoding.

---

## 42. Audit structure-producing Runners

Review structure outputs from relevant Runners such as:

```text
AlphaFold2
AlphaFold3
OpenFold
ESMFold
Boltz
Protenix
Chai
SimpleFold
etc.
```

Where scientifically correct, ensure result metadata describes confidence encoding.

Do not add pLDDT metadata to structures whose B-factor column has a different meaning.

---

## 43. CIF support

Ensure the viewer can apply the same confidence coloring semantics to compatible PDB and CIF structures.

The encoding contract, not the extension, determines behavior.

---

# Phase 15 — Structure style presets

## 44. Define a small shared preset vocabulary

Add a minimal presentation-level preset vocabulary such as:

```text
Cartoon
Cartoon + ligand
Sticks
Surface
Chain
Rainbow
Confidence
```

Do not encode a giant visualization DSL.

---

## 45. Mol* and fallback should share user-facing vocabulary

Where possible:

```text
preset name
color mode
```

should mean roughly the same thing in Mol* and Py2Dmol.

Feature parity is not required.

Mol* remains the primary rich viewer.

---

## 46. Levin Design analysis

Create a separate implementation spike inside this workstream for studying Levin Design's structure-view presentation behavior.

If an unpacked/local application bundle is available:

```text
inspect assets
identify preset names
identify representation combinations
identify color modes
identify camera/focus behavior
```

Do not copy proprietary code.

Extract interaction/design ideas only.

Do not block the core persistent-viewer work on this spike.

Record findings in a short developer note if useful.

---

# Phase 16 — Py2Dmol fallback upgrade

## 47. Keep Py2Dmol lightweight

Py2Dmol should be a useful fallback, not a second Mol*.

Support a bounded useful subset:

```text
cartoon
sticks
cartoon + ligand
surface
chain coloring
rainbow
confidence where metadata supports it
```

---

## 48. Avoid another independent viewer state model

Reuse the same presentation projection where feasible:

```text
active preset
active color mode
artifact metadata
```

Do not duplicate scientific interpretation logic in both viewer implementations.

---

# Phase 17 — HTML result simplification

## 49. Stop treating arbitrary Runner HTML as an application

Runner-generated HTML should not automatically become an executable embedded result application.

Default behavior:

```text
download
```

Optionally:

```text
plain source/text preview
```

if useful.

---

## 50. Remove unnecessary HTML iframe/sandbox complexity

Trace current HTML result preview behavior.

If arbitrary result HTML currently enters:

```text
iframe
sandboxed document
HTML-specific active preview
```

remove that rendering path unless there is a concrete current Runner requiring it.

Prefer platform-native structured artifacts.

---

## 51. Preferred rich-result formats

Runner authors should prefer:

```text
summary.json
CSV / TSV
JSON
PNG / SVG
PDF
PDB / CIF / SDF
plain text
```

over standalone HTML reports.

Update developer guidance accordingly.

---

# Phase 18 — Dark-mode and shared token audit

## 52. Audit touched surfaces for hardcoded light/dark colors

While touching these pages, replace obvious hardcoded surface colors that break theme switching.

Focus only on changed surfaces:

```text
landing agent card
Profile
Dashboard toolbar
Runner cards
Create Task
Result workspace
```

Do not turn this into a repository-wide visual redesign.

---

# Phase 19 — Testing

## 53. Profile browser contracts

Test:

```text
desktop sidebar visible
mobile tab/navigation usable
every section reachable
guest restrictions still respected
Runner Access states render
GPU Credits render
API key actions still available where permitted
Security/password works
Metrics window changes update data
```

---

## 54. Dashboard contracts

Test:

```text
selection status visible in table mode
selection contextual bar appears/disappears correctly
view switch works
filters remain accessible
admin-only actions stay admin-only
ultra-wide layout uses extra width
```

---

## 55. Create Task contracts

Test:

```text
no vertical protocol rail
no standalone readiness side panel
main form receives primary width
validation remains visible
Run action remains accessible
artifact reuse UI absent
no reusable-artifacts request from ordinary Create Task load
JAAG builder absent
JAAG external helper visible where configured
```

---

## 56. Result viewer contracts

Test:

```text
Mol* host initialized once
switching result structure does not recreate viewer host
cached artifact does not redownload
prefetched next artifact can switch without another fetch
cache remains bounded
rapid switching cannot render stale artifact
pLDDT control appears only with explicit confidence metadata
compatible CIF supports pLDDT
ordinary CIF does not falsely claim pLDDT
style preset survives structure switch where appropriate
fallback viewer remains usable
```

Mock browser/network boundaries where necessary.

Do not depend on internet/CDN access in tests.

---

## 57. HTML-result tests

Verify:

```text
HTML result is not executed as arbitrary active content
download remains available
optional source preview is inert
```

---

## 58. Theme tests

Verify touched components in both:

```text
light
dark
```

especially the landing agent card.

---

## 59. Responsive matrix

At minimum exercise representative widths:

```text
320
390
768
1024
1440
1920
2560
3440
```

Avoid making every test run at every width; choose focused matrices to keep CI bounded.

---

# Phase 20 — Documentation cleanup

## 60. Update user-facing docs

Reflect:

```text
new Profile navigation
simplified Create Task
no artifact reuse UI
JAAG as external helper
result viewer behavior
HTML download behavior
```

---

## 61. Update developer docs

Remove or rewrite obsolete references to:

```text
artifact reuse as active product
JAAG builder plugin
HTML result application preview
old three-column Create Task architecture
```

Document confidence metadata requirements for structure viewers.

---

# Commit plan

Keep the PR coherent by making several understandable commits.

Suggested sequence:

```text
1. refactor(ui): add adaptive application shells and layout transitions

2. refactor(ui): redesign profile, dashboard, runner catalog and access surfaces

3. simplify(create-task): remove side rails, artifact reuse and JAAG builder

4. refactor(results): persist Mol* viewer and add bounded structure prefetch

5. feat(results): unify structure presets and confidence-aware CIF/PDB rendering

6. simplify(results): downgrade arbitrary HTML outputs to inert/download behavior

7. test/docs: complete responsive, theme, viewer and workflow acceptance
```

Commit grouping may change if implementation naturally produces cleaner boundaries.

Do not create artificial commits just to match this exact list.

---

# Explicit non-goals

Do not include in this PR:

```text
new scientific Runners
Amber Relax
OpenFold3
Rosetta
DLPacker/PIPPack/DiffPack
generic OpenMM relaxation
project/workflow DAGs
cross-task composition
new frontend framework
new plugin framework
new analytics database
Mol* replacement
full redesign of admin infrastructure pages
```

Those are separate workstreams.

---

# Acceptance criteria

The PR is complete when:

```text
[ ] Profile uses section navigation:
    Profile / Security / API Key / Runner Access / GPU Credits / Metrics

[ ] Profile remains usable on mobile and ultra-wide displays

[ ] Metrics are derived from existing persisted data without a new analytics store

[ ] Dashboard controls are denser and logically grouped

[ ] Dashboard table view always exposes current selection state

[ ] Dashboard / Runner / Create Task layout switching has subtle shared motion

[ ] prefers-reduced-motion disables unnecessary animation

[ ] Connect an AI agent follows both light and dark themes

[ ] Runner compact mode has no artificial large bottom whitespace

[ ] Main application pages use appropriate extra space on 2560/3440px displays

[ ] Runner Access communicates current usability/state more efficiently

[ ] Create Task no longer uses the three-column protocol/form/readiness layout

[ ] readiness is integrated near submission

[ ] artifact reuse UI is gone

[ ] dead artifact-reuse backend code is removed where no consumer remains

[ ] JAAG builder plugin integration is removed

[ ] JAAG is presented only as an external input-preparation helper

[ ] one persistent Mol* viewer instance can switch between result structures

[ ] structure switching does not unnecessarily recreate/restart the viewer

[ ] bounded structure cache exists

[ ] bounded adjacent/sibling prefetch exists

[ ] rapid artifact switching is race-safe

[ ] pLDDT is driven by explicit result metadata, not file extension

[ ] compatible CIF structures can use confidence coloring

[ ] non-confidence CIF is never mislabeled pLDDT

[ ] structure style presets exist with a small stable vocabulary

[ ] Py2Dmol fallback supports a useful bounded preset subset

[ ] arbitrary Runner HTML is no longer treated as executable active result UI

[ ] download remains available for HTML artifacts

[ ] existing Runner scientific behavior is unchanged

[ ] existing access/security boundaries remain unchanged

[ ] responsive/browser contract suite passes

[ ] documentation is consistent with the simplified product
```

---

# Final engineering constraint

At the end of this PR, REvoCompute should contain **less product complexity than before the PR**, even though the result viewer is more capable.

A successful implementation should visibly delete obsolete code paths and make the ordinary workflows easier to understand.

Do not solve layout problems by adding more panels, wrappers, modes, descriptors, or configuration.
