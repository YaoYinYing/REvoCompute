# Persistent Shell & Navigation / Dashboard selection

**Status:** PLANNED / DESIGN BRANCH ONLY. **Base:** main at `14ea7441fd1aeeccb2abf37a217c1bbf42ab0e6e`.
**Dependencies:** May start route/lifecycle design immediately; minimize cherry-picks/conflicts with PR #77 (Create Task) and #78 (Mol*), then integrate/test against their merged heads or exact demonstrated APIs. Do not overwrite their changes.
**Scope owner:** `frontend/src/main.ts`, `frontend/src/app/{shell,router,public-shell}.ts`, `frontend/src/styles/app.css`, `frontend/src/features/profile/`, `frontend/src/features/dashboard/`, scoped tests. Do not write Admin fleet/resource pages (PR #80).
**Reported:** left sidebar scrolls out; repeated click of active item collapses nav unexpectedly; section navigation causes full document refresh; language button combines icon + long label; Profile duplicates Account's only top-level entry with its second-level sections; Dashboard selection checkbox sits at bottom/footer alongside destructive actions in both cards and table; public Home links less discoverable; unexplained blank outlined boxes near Dashboard title should be verified.

## Architecture & product decisions
- [ ] Read the canonical Soft Precision design language, route classes and auth/session contracts. Inventory all current anchors and their forms of navigation: protected-to-protected, public-to-public, protected/public boundary, sign-in/logout, task/result deep links, hashes, downloads, external links, tour handoffs.
- [ ] Audit existing `main.ts`: it currently resolves route once and mounts Shell once per document. Design a *single persistent authenticated AppShell* and per-route outlet mount/unmount with explicit `AbortController`/dispose semantics. Avoid a second router or duplicate auth state.
- [ ] Intercept **only qualifying same-origin in-app navigation** with History API; preserve browser middle-click/cmd-click, Download, external links, fragments, auth redirects, refresh/deep-link server entrypoints, access-denied and back/forward.
- [ ] Screen-readers: correctly update `aria-current`, document title, main heading focus, history navigation announcement without stealing focus from input; skip link to actual main; no dangling event listener.

## UI behavior
- [ ] Desktop side rail persists through page navigation and page scrolling; viewport-height navigation scrolls internally when longer than screen; top bar remains stable. Mobile bottom bar remains reachable; do not break admin secondary nav.
- [ ] Add an explicit lower-left expand/collapse button with accessible name and `aria-expanded`, persisted rail choice; remove repeat-active-nav-as-toggle behavior. Repeated click now remains ordinary navigation/noop as appropriate.
- [ ] Account section becomes direct navigation to Account, Security, API key, Runner access, GPU credits, Metrics; reuse existing Profile internals when possible while giving each direct deep link, eliminating the nested left Profile tabs in desktop UI. No duplicated navigation owner.
- [ ] Show only language icon **or** current language label, not both; language choices continue accessible inside popover. Keep English/Chinese and mobile work correctly.
- [ ] Dashboard select: cards/compact selection at *start/identity*, table first dedicated selection column with Select all; independent actions remain in rightmost action column. Batch selection state is stable while switching view, filtering, sorting, pagination and targeted refresh; confirmation before deletion.
- [ ] Diagnose the five empty blue-outlined boxes in user Dashboard screenshot; distinguish annotation from actual bug; fix only if reproducible.
- [ ] Keep public Home links to Documentation/API/Agent resources discoverable without crowding authenticated topbar; coordinate later MCP entry with PR #81.

## Integration & acceptance
- [ ] Reproduction-led Playwright tests using production-built frontend for scroll, rail toggle, route transition with no document reload, address bar URL, browser back/forward, direct deep-link refresh and session expiration.
- [ ] Verify Request cancellation, no duplicate listeners/notifications, no Mol* GPU/React/context leak, no unsaved Create Task data silently lost, and no stale Tour anchors while changing routes. Use graceful state recovery rather than fake persistence.
- [ ] Keyboard/screen-reader/mobile 280/320 px, light/dark, EN/ZH regression and actual browser computed layouts; no test that simulates CSS.
- [ ] Runner parameter fields from PR #77 still editable and result viewer from PR #78 still mounts/disposes safely.
- [ ] Run frontend typecheck/unit/build, Playwright broad journeys, relevant CI and exact-head independent review; **no deployment or merge automatically**.
- [ ] Remove branch-only TODO, demo snippets, screenshot trees and temporary QA reports from final production diff.
