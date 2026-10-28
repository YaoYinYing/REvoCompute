# TODO — fix(ui): stabilize example dialogs, runner access and task labels

> **Status:** Implemented on `campaign/2026-10-28-ui-corrections`; R1 review findings applied. PR stays Draft; no merge authorization.
> **Baseline when drafted:** `17e80ed1dbd00f1389f3ec7047e5661b85ed52eb` (2026-10-28); revalidate against the exact head at implementation.
> **Scope:** Repair the create-task modal presentation; simplify Runner Access information hierarchy; shorten scientific Task display names without changing identifiers or permissions.

## Objective
Repair the create-task modal presentation; simplify Runner Access information hierarchy; shorten scientific Task display names without changing identifiers or permissions.

## Grounded starting facts
- Screenshot evidence: the AF3 Load Example modal appears transparent and its content overlaps the page beneath the scrim.
- The create-task CSS variables are scoped to `.create-task`; `CreateTask.ts` appends `<dialog>` under `document.body`, outside the inheritance scope.
- `frontend/src/features/profile/sections.ts` owns Runner Access state display and requests; screenshot shows narrow request controls.
- `task.yaml` owns `display_name`, which is separate from the stable Task `id`.

## Implementation checklist
- [x] Reproduce the modal problem in a real browser at a pinned exact main head, including a hard reload, both supported themes and one narrow viewport; record before screenshots.
- [x] Investigate CSS custom-property inheritance, native dialog top-layer placement, browser default styles and stylesheets; fix ownership globally rather than adding arbitrary z-index.
- [x] Audit Load Example, access request and replace/overwrite confirmation dialogs for visual consistency and focus/escape behavior.
- [x] Keep existing demo behavior: input-only hydration, no implicit computation, undo or replace confirmation, generation race guards and source/license attribution.
- [x] Fix modal alignment, scroll containment, keyboard tab order, close action, overlay interaction, screen-reader labels and mobile layout.
- [x] Reorganize Runner Access by actionable state: compact Granted list; Requestable/Pending/Expired/Rejected content with full-width request forms, explanatory policy context and expiry.
- [x] Preserve immutable permission decisions, upstream license requirements, `policy_id` mapping, access status semantics, and operator-approved gate checks.
- [x] Review Task `display_name` values for overlong role descriptions; use concise upstream/model names and move scientific purpose to summary/use_when; do not modify IDs.
- [x] Check representative catalogs (AlphaFold, RoseTTAFold3, BioEmu2, OpenDDE, PLACER) and translations for typography, display-name ambiguity and truncation.
- [x] Preserve layout language and native design tokens; do not imitate Tamarind assets or clone its page.

## Test and acceptance checklist
- [x] Browser screenshot/regression test for the example dialog with a visible background, readable text, and focus containment in light/dark (light/dark also cover the access and replace dialogs).
- [x] Keyboard and mobile tests for modal closure, request form and name display.
- [x] Test demo selection/undo, empty list, API failure and slow-response cancellation.
- [x] Test policy state transitions without submitting unauthorized requests, expired grants and pending requests (including the expired-plus-pending projection and expired-but-not-requestable case).
- [ ] Assert stable Task IDs, runner dispatch and history API after renames; localization snapshots. Task IDs, dispatch family and the parameter endpoint are covered by `tests/fleet/test_task_label_projection.py`; display names are server-owned and not localized, and the history contract is keyed by the unchanged Task id, so no separate history mutation is exercised.
- [x] Run relevant existing frontend static checks, unit/browser regressions and give exact commands with outputs.

## Explicit non-goals
- Do not alter Core entitlement decisions or task execution resources.
- Do not merge task naming into Runner IDs, nor change application navigation architecture.

## Dependency and integration policy
Independent UI work; do not block or modify Stage Contract, #91, or new Runner scopes.

## Review protocol and handoff
- [ ] Read `CLAUDE.md`, `LONG_TASK_HANDLING.md`, the Single-PR Campaign Protocol and this TODO before coding.
- [ ] Appoint one PR owner; preserve an independent Campaign Adviser and strict worktree/write ownership.
- [x] Create or update `IMPLEMENTATION_STATE.md` alongside this TODO when substantive implementation begins; track progress, exact tests and outstanding blockers.
- [ ] Validate exact head, identify adjacent open/merged PRs and avoid rewriting canonical functionality or introducing parallel sources of truth.
- [ ] Post detailed technical findings and regressions to this PR's review threads; report owner/adviser status to Commander.
- [ ] Include fail-path tests, relevant docs, migration/read-only compatibility where needed, and no unverifiable performance or science claims.
- [ ] Keep PR draft until implementation is complete, exact-head CI/review evidence exists and maintainer accepts the scope.
