# TODO — Responsive & Result Correctness (Campaign 2026-10-25)

> Planning-only file. Remove this root `TODO.md` before declaring the implementation PR READY.
> Baseline: main `53df3225f894c25d604b7ad16b9a0557ea77c42b`.
> Issues: #68, #101, #106, #107. Maintainer reserves squash-merge.

## Goal
Close small, reproducible user-facing layout, localization, and scientific result presentation defects **without a frontend redesign**.

## Track A — narrow viewport and navigation (#68, #101)
- [ ] Re-run the existing `tests/test_playwright_runner_fixtures.py::test_narrow_content_heavy_surfaces_fit_the_viewport` against an exact-head production bundle. It is already a positive assertion at this main HEAD (not visibly marked `xfail`), and the last main BrowserContracts was green. If both 320px cases are demonstrably fixed, **report #68 as already covered, do not rewrite CSS just to produce a diff**, and close only with evidence.
- [ ] Verify the Create Task protocol, Result header/actions at 320px and 390px; require settled `scrollWidth <= clientWidth`, complete identities/actions, keyboard/touch access, and bounded internal scrolling for large scientific views. Make only focused fixes if defects reproduce.
- [ ] Reproduce #101 on `/runners/:name` at narrow, 768, 1024 and wide viewport widths, including expanded/collapsed rail. Check headings, facts, sticky anchors and navigation overlap via **rendered bounding-box geometry**, not DOM text or brittle CSS-string tests.
- [ ] Correct shell/detail offsets only where necessary. No global spacing/theme rewrites or layout regression at phone/desktop widths.

## Track B — result localization and table semantics (#106, #107)
- [ ] Replace the seven `LOCAL_*` literal errors in `frontend/src/features/results/table-page.ts` with `results.local.table.*` catalog keys in **both** English and zh-CN, preserving precise bound/malformed/encoding reason meaning and parser safety limits.
- [ ] Test the visible local-table refusal path in both locales, not only the string constants; keep errors fail-closed.
- [ ] In `EntitySummaryTable` (`scientific.ts`), create explicit `<thead>` and `<tbody>`, maintain row selection/keyboard behavior, and read rows through `tbody tr` in a browser contract.
- [ ] In `matrix-view.ts`, separate >`MAX_COLUMNS` from malformed shape; emit `results.matrix.error.exceedsColumns` in both locales; test boundary exactly-at-cap, one-over-cap, and malformed rows.
- [ ] Avoid expanding scientific data bounds, projections, result manifest contracts, or API payloads.

## Verification
- [ ] Demonstrate each issue's precondition and postcondition, and distinguish “already passes” from “fixed in this PR”.
- [ ] Run affected frontend unit/typecheck/build, focused browser and fixture lanes, responsive keyboard tests, and impacted CI.
- [ ] Inspect exact diff for unrelated style churn; no screenshot-only acceptance. Add before/after geometry or DOM evidence.
- [ ] An independent reviewer checks exact-head behavior and accessibility; findings remain in PR threads. Advisor evaluates scope only when needed; maintainer decides merge.
- [ ] Remove temporary root `TODO.md` before READY_FOR_FINAL_REVIEW. **No auto-merge**.

## Cross-PR separation
The Quality Gates PR owns a **new** real-directory browser contract (#105), Chromium cache (#108), and local test environment (#103). Coordinate on tests, but do not edit its CI workflow or new directory-chooser test. This PR owns production frontend results and focused browser geometry tests.

## Out of scope
GPU credit waterfall #91, Fleet/server admission #89/#90, overall design-system refactor, new result types or backend contract migration.
