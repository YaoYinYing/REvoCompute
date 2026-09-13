# REvoCompute Frontend Scalability PR — Final Review and Remediation

## Status

PR #12 has implemented the main frontend-scalability architecture and should **not** be redesigned again.

This TODO defines the remaining correctness, contract, accessibility, visual-acceptance, and review work required before squash-merge.

The purpose of this phase is:

> preserve the successful frontend redesign, correct the remaining semantic gaps, prove the final interaction contracts, and bring design truth, implementation-state truth, and machine truth back into agreement.

Do not reopen completed page redesigns merely to polish them.

---

# 1. Preserve the architecture already established

The following architecture is accepted and should remain in place unless a remediation item below requires a focused change:

* shared `static/js/ui.js` presentation layer;
* shared persisted Runner/Create Task catalog density;
* persisted Dashboard Detailed / Compact / Table layout;
* shared custom dialog system;
* responsive page primitives;
* Runner/Create Task searchable catalogs;
* Dashboard filtering and sorting;
* Profile Runner Access redesign;
* User Control master/detail redesign;
* Markdown-backed Terms;
* Runner-policy licence metadata;
* metadata-driven pLDDT presentation;
* Mol* preview lifecycle fix;
* Review Shortlist removal;
* hidden artifact-reuse submission UI;
* Configuration TaskType search;
* declarative Runner-owned parameter presentation metadata.

Do not replace these with page-specific implementations.

---

# 2. P1 — Fix seed randomization semantics

The current generic seed widget is not yet semantically safe.

`x-ui-control: seed` identifies an integer as a seed, but it does not describe the difference between:

* a valid concrete reproducibility seed;
* a sentinel value;
* upstream-controlled randomization;
* an omitted seed.

For example, MPNN-family tasks declare:

```yaml
seed:
  type: integer
  x-ui-control: seed
  default: 0
  minimum: 0
  description: >
    Random seed for reproducible sequence sampling;
    zero requests upstream randomization.
```

The frontend currently generates a value from the complete declared numeric range. It may therefore generate `0` and present that value as a concrete browser-generated random seed even though `0` means “let upstream randomize.”

That violates the Runner contract.

## Required design

Keep Runner-owned semantics declarative.

Do **not** add JavaScript branches such as:

```javascript
if (taskType === "hypermpnn") {
    ...
}
```

Extend the reusable presentation contract so that a seed control can declare its browser-generation domain separately from its API-valid domain.

A suitable design may use a validated extension such as:

```yaml
x-ui-control:
  kind: seed
  random:
    minimum: 1
```

or an equivalent typed representation.

The exact syntax may differ, but it must support at least:

* ordinary integer seed;
* optional seed;
* API-valid sentinel values that browser random generation must exclude;
* runner-defined minimum and maximum;
* manual entry of sentinel values where the Runner permits them;
* omission where the Runner permits omission.

Do not alter the API-valid schema merely to simplify the dice control.

## Runner audit

Inspect every actual seed-bearing TaskType and its entrypoint/wrapper.

For each one determine:

```text
parameter name
required or optional
default
allowed range
whether empty means omission
whether zero has special meaning
whether another sentinel has special meaning
what the upstream CLI actually receives
```

At minimum explicitly verify:

* BioEmu;
* MPNN family;
* ColabFold / AlphaFold-related seed controls;
* Boltz;
* Chai-1;
* SimpleFold;
* FAMPNN;
* Foundry;
* RFdiffusion2;
* EvoSplit;
* GREMLIN_LH;
* Pallatom;
* CodonTransformer;
* dynamicMPNN.

Do not assume that every parameter containing the word `seed` should receive a dice control.

## Browser behaviour

When random generation is enabled:

* generate only a concrete Runner-valid reproducibility seed;
* never generate a sentinel meaning “randomize upstream”;
* display the generated value;
* allow regeneration;
* submit the concrete value.

When random generation is disabled:

* restore manual editing;
* preserve the user's prior manual value;
* permit empty input only when the Runner contract permits omission;
* permit sentinel values when the Runner contract permits them.

Continue using `crypto.getRandomValues()`.

## Tests

Add contract tests proving:

1. optional empty seed remains empty when randomization is disabled;
2. generated seed respects declared generation bounds;
3. generated seed never equals an excluded sentinel;
4. manual sentinel input remains accepted where the Runner allows it;
5. MPNN `0` retains its upstream-randomization meaning;
6. resetting restores the Runner-defined default;
7. API clients remain unaffected by frontend presentation metadata.

The test must not merely assert that a generated value lies between `minimum` and `maximum`.

---

# 3. P2 — Make the Dashboard filter contract explicit

The current Dashboard has a good structured filtering model:

* task-name text search;
* TaskType selector;
* status selector;
* admin username text search;
* submitted date range;
* finished date range.

Keep structured status and date controls.

Do **not** add regex to native date controls merely to satisfy the old wording literally. Regex is useful for textual identifiers, not date-range selection.

Refine the product contract to:

> All textual search fields support plain matching and optional regular expressions. Structured fields use structured controls.

Under that refined rule:

* task name must support RE;
* username must support RE where exposed;
* TaskType must support scalable textual discovery.

The current TaskType selector is acceptable for a small registry but should not become an unsearchable hundreds-item dropdown.

Implement one of these generic solutions:

```text
searchable combobox / datalist
```

or:

```text
TaskType text filter + suggestions + optional RE mode
```

Do not remove the convenient normal TaskType selection path.

If TaskType remains a strict selector, document that it is intentionally a structured filter and add a general textual TaskType search mechanism elsewhere in the same control.

## Tests

Cover:

* ordinary TaskType selection;
* large TaskType list discovery;
* TaskType plain-text matching if introduced;
* TaskType regex matching if introduced;
* invalid regex;
* combination with status/date filters;
* combination with finish-date sorting.

---

# 4. P2 — Verify dialog focus lifecycle

`ui.js` now centralizes dialogs, which is the correct architecture.

Before calling the primitive complete, add explicit browser coverage for focus restoration.

For each modal type:

```text
confirmation
alert
prompt
detail overlay
```

verify:

1. keyboard focus enters the dialog;
2. Escape cancels when cancellation is allowed;
3. focus does not escape behind an open modal;
4. closing returns focus to the control that invoked the dialog;
5. replacing one active dialog with another does not leave focus stranded;
6. destructive confirmation cannot execute twice.

If the native `<dialog>` implementation reliably restores focus in all supported browsers, keep the implementation simple and lock the behaviour with tests.

If not, explicitly retain the invoking element and restore focus after close.

Do not add page-specific focus hacks.

---

# 5. P2 — Complete landing-page visual acceptance

The hero now uses viewport-aware sizing and the `/skills.md` box has been moved below the hero, which fixes the primary layout imbalance.

The remaining task is **visual acceptance**, not another redesign.

Review the complete landing page at least at:

```text
1920×1080
1440×900
1366×768
1024×1366
834×1194
430×932
390×844
```

On desktop/laptop, confirm that the major page sections read as distinct visual chapters rather than one continuous stack of arbitrary card heights.

Do not force every section to `100vh`.

Instead adjust only where needed using:

* `min-height`;
* viewport-aware spacing;
* content constraints;
* section rhythm.

Specifically inspect:

* hero balance;
* relationship between hero and AI-agent strip;
* first-fold CTA visibility;
* evidence-map scale;
* Approach section;
* Workflow section;
* product bridge;
* final CTA.

At 1366×768 no important hero content should be pushed into an awkward half-visible second fold.

On tablet/mobile, normal document flow takes priority over slide-like composition.

---

# 6. P2 — Strengthen responsive tests with populated states

The existing nine-viewport overflow test is useful but insufficient as the only responsive acceptance evidence.

Add representative populated interaction states.

At minimum test:

## Dashboard

* Detailed;
* Compact;
* Table;
* compact detail overlay;
* long task name;
* failed task;
* running task;
* admin actions.

## Runner / Create Task catalogs

* enough methods to create multiple rows;
* long Runner names;
* restricted badges;
* compact density;
* zero search results.

## User Control

* long names and affiliations;
* action buttons;
* selected/batch state;
* user details dialog;
* edit dialog;
* Runner Access request queue.

## Seed control

* dice + toggle + numeric field at phone width.

## Result page

* Mol* structure;
* pLDDT control;
* long artifact names;
* result-view tabs.

The test does not need pixel-perfect snapshots.

Prefer robust assertions for:

* no page-level horizontal overflow;
* controls remain reachable;
* dialogs fit viewport;
* essential actions remain visible;
* scrolling happens inside the intended container;
* touch controls do not collapse below usable size.

---

# 7. P2 — Verify the three previous Codex Dashboard findings at current head

The previous Codex review found:

* table layout stopped status polling;
* table layout removed Cancel/Delete;
* compact detail clones lost lazy structure loading.

The current code appears to fix all three.

Keep the fixes and their regression tests.

Before merge:

* confirm table status elements still carry polling identity;
* confirm Pending/Running table rows expose Cancel;
* confirm deletable table rows expose Delete;
* confirm compact detail overlays bind structure lazy loading;
* confirm overlay Result/Download/Cancel/Delete actions still work.

After verifying, resolve the stale/outdated review threads rather than leaving ambiguous unresolved review state.

---

# 8. P2 — Reconcile TODO and IMPLEMENTATION_STATE

The branch currently says:

```text
Design source: TODO.md
```

but the active PR does not contain that design file.

Add this reviewed `TODO.md` to the branch as the architectural truth for the final remediation phase.

Then update `IMPLEMENTATION_STATE.md`.

It must no longer say:

```text
Complete
Next action: none
Known failures or blockers: None
```

while required remediation remains.

The new state should identify the current phase as something equivalent to:

```text
Final review remediation
```

and track each required item from this TODO.

In particular, remove or correct the current claims that:

* zero-sentinel seed semantics are already fully preserved;
* all accessibility acceptance is complete;
* no further review is required.

Do not mark the refactor complete until this TODO has no required unchecked item.

---

# 9. Final architecture audit

After remediation, search the final tree for architectural regressions.

Audit at least:

```text
window.confirm
window.alert
window.prompt
confirm(
alert(
prompt(

shortlist
shortlist.json
exportShortlist

artifactReferences
Reuse an artifact

task-type-specific branches in generic UI code

confidence_encoding
plddt
PDB/mmCIF format-based confidence inference

x-ui-control
seed
random_seed
base_seed
```

Classify every remaining hit.

Do not blindly remove legitimate references.

The required invariants are:

* no application-native JS popup remains;
* no Review Shortlist product implementation remains;
* hidden artifact reuse is not submitted accidentally;
* no TaskType-specific seed branch exists in generic frontend code;
* pLDDT is metadata-driven;
* seed generation is metadata-driven;
* API-valid sentinel semantics remain Runner-owned.

---

# 10. Current-head review gate

Current CI passing is necessary but not sufficient.

After all remediation commits:

1. run the focused affected suites;
2. run `make test`;
3. run `make test-cov`;
4. run strict documentation build;
5. run changed-JavaScript syntax/static checks;
6. run responsive Playwright suites;
7. verify package data for Markdown Terms;
8. ensure Docker Compose configuration still renders;
9. push the final head;
10. request a **fresh Codex review against the final head**.

Do not rely on the earlier review of an older commit.

No new P1/P2 correctness finding should remain.

If a valid finding appears, fix it and request review again.

---

# 11. Final PR hygiene

Before squash-merge:

* make all review threads either resolved or clearly obsolete with verified replacement coverage;
* update the PR description with final verification evidence;
* update `IMPLEMENTATION_STATE.md`;
* ensure this `TODO.md` has no required unchecked item;
* ensure there are no debugging artifacts or temporary screenshots;
* inspect `git diff --check`;
* inspect the final changed-file list for unrelated changes.

Do not add new product scope during this phase.

---

# Definition of done

PR #12 is ready to squash-merge only when all of the following are true:

* browser-generated seeds cannot collide with Runner sentinel semantics;
* seed behaviour is declarative and Runner-owned;
* textual Dashboard search behaviour is explicitly defined and tested;
* structured dates remain structured;
* shared dialogs have verified focus lifecycle;
* landing-page visual composition has passed desktop/tablet/mobile acceptance;
* populated responsive states have regression coverage;
* the three earlier Dashboard review findings remain fixed;
* `TODO.md` exists and is the active design truth;
* `IMPLEMENTATION_STATE.md` accurately describes remaining/completed work;
* current-head CI is green;
* final architecture audit is clean;
* a fresh current-head Codex review has no unresolved P1/P2 finding.

At that point, stop editing and prepare the PR for squash-merge.
