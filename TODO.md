# TODO — Browser, CI & Reproducibility Gates (Campaign 2026-10-25)

> Planning-only file. Remove this root `TODO.md` before declaring the implementation PR READY.
> Baseline: main `53df3225f894c25d604b7ad16b9a0557ea77c42b`.
> Issues: #102, #103, #105, #108. Maintainer owns squash-merge.

## Goal
Make fragile acceptance paths reproducible and lower CI setup variance, plus remove one verified unused Runner adapter read. This is a **test/developer-infrastructure** PR, not a product redesign.

## Track A — real local directory under CSP (#105)
- [ ] Add a **browser-marked** contract that selects a real on-disk fixture directory through `input[webkitdirectory]` via Playwright `set_input_files()`; do not fake `webkitRelativePath` on `File` objects.
- [ ] Exercise both choosing the result directory directly and choosing its parent; build the smallest valid matrix/entity table fixture with representative local byte content.
- [ ] Require actual production CSP, including `connect-src blob:` behavior, and assert the declared matrix/entity-table render and **zero requests to `/compute/api/results`**. No relaxed-CSP fallback or artificial remote result URL.
- [ ] Keep the fixture bounded, deterministic and safe from network access; put this in a dedicated new browser test file to avoid the Responsive & Results PR's test edits.
- [ ] Update accepted-limitation documentation only after the contract is enforced.

## Track B — Chromium download cache/headroom (#108)
- [ ] Measure the present BrowserContracts breakdown: initial #86 acceptance noted 24m24s / 25m, including 8m50s cold Chromium download; an existing later main run was materially faster, so record **comparable cold/warm** evidence, not an invented universal baseline.
- [ ] Cache Playwright Chromium under a **stable version-derived key** with OS/architecture and a controlled browser path (or justify an existing image). Verify package version resolution, cache restoration, license/supply-chain constraints, and that CI does not use untrusted PR-generated executable caches.
- [ ] Preserve the bounded clock and strict-CSP job, avoid increasing `timeout-minutes` as the solution. Record setup time and total duration before/after, including cold-cache behavior and cache-miss fallback.
- [ ] Treat actual browser runtime growth from Track A as part of the budget; don't hide new tests by raising timeouts.

## Track C — developer environment reproduction (#103)
- [ ] Reproduce and document supported project-venv (prefer `uv`) invocation for `tests/test_process_isolation.py` and `tests/test_restart_ctl.py`. The issue is **host PATH/Conda contamination**, not an established restart product bug.
- [ ] Preserve production `run/restart.sh` interpreter semantics. Correct the fake Docker shim's bare `python -` resolution with the smallest test-owned, portable solution if necessary, and provide actionable diagnostics for unsupported PATH states.
- [ ] Run the focused 135-test block in the documented environment, or record an explicit reproducibility blocker rather than claim success.

## Track D — MPNN dead read (#102)
- [ ] Verify `docker/runners/mpnn/run.sh` contains the unused `FIXED_POS="$(_parse_param fixed_positions)"` and no adapter consumer or declared schema parameter requires it.
- [ ] Remove only that dead read; preserve identical dispatched argv and output semantics. **Do not add** a `fixed_positions` Task/UI/API parameter.
- [ ] Use a Runner-owned executable fast regression, not a static source-string test and not Server schema inspection inside Runner unit tests.

## Execution and review
- [ ] Run shell syntax, Runner fast tests, targeted browser/strict-CSP, Python dev-env tests and impacted CI; run `mkdocs build --strict` if docs change.
- [ ] Record exact head, commands, versions, timings, cache hit/miss and negative browser/CSP evidence in the PR. Review time/performance regressions, cache poisoning and filesystem boundaries.
- [ ] Worktree-isolated owner; coordinate CI/browser lane usage and test file changes with other PR owners. Independent reviewer handles merge-level findings in this PR. Advisor is independent and advisory, not an obligatory approval chain.
- [ ] Remove temporary root `TODO.md` before READY_FOR_FINAL_REVIEW. **No auto-merge**.

## Out of scope
Production scheduler/restart redesign, MPNN fixed-position feature implementation, changing server resource policy, CSS redesign, GPU credit waterfall.
