# Cared-for Precision — Interaction and Composition Finishing Pass

## Objective

Finish the UI work that remained after PR #56
(`design(frontend): recover cared-for scientific character`) without reopening
its architecture or starting another visual-system rewrite.

PR #56 successfully established the Cared-for Precision refinement on top of Soft
Precision, but its final automated review completed just after merge and exposed
real interaction/responsive details that were not part of the merged exact head.
Since then, additional backend/control-plane work has landed on `main`, so this
PR should also inspect the current rendered application for small composition and
interaction regressions introduced by integration.

The governing goal is:

> **Make the current REvoCompute frontend feel finished in use, not merely
> finished in screenshots.**

This is a finishing pass, not a redesign.

Preserve:

- Soft Precision's architecture and behavior;
- Cared-for Precision's art direction;
- the current information architecture;
- one-click task submission;
- server-owned scientific/data contracts;
- Result workspace semantics;
- current auth and permission boundaries;
- accessibility and responsive behavior;
- the existing frontend stack and component organization.

Read before editing:

~~~text
CLAUDE.md
LONG_TASK_HANDLING.md
TODO.md
docs/developer-guide/frontend-design-language.md
docs/developer-guide/frontend-art-direction.md
docs/developer-guide/frontend-visual-ancestry.md
docs/developer-guide/frontend-taste-review.md
~~~

Also read PR #56's final review discussion, especially the findings produced
after its merge.

Use the current `main` as implementation truth. Historical #56 code is context,
not a patch source.

---

## 1. Worktree and ownership

This PR is intentionally **outside the active Commander campaign**.

It has one independent owner: Codex.

The owner must work only in a dedicated worktree under:

~~~text
/home/yinying/repo/.rc-worktrees/
~~~

Recommended path:

~~~text
/home/yinying/repo/.rc-worktrees/cared-for-precision-finishing
~~~

Do not edit from the primary repository checkout.

Do not ask the Campaign Commander to assign reviewers, rebase the branch, manage
the worktree, or consume a campaign slot for this PR.

The owner is responsible for:

- keeping this branch current with `origin/main`;
- resolving its own conflicts;
- testing its exact head;
- cleaning PR-local scratch/CI residue after merge when asked;
- retiring this `TODO.md` before `READY_FOR_FINAL_REVIEW`.

If current campaign work lands changes in overlapping frontend files, re-read the
new `main` and preserve the newer behavior. Do not revert campaign-owned work
to make this branch easier to merge.

---

## 2. Mandatory post-#56 regressions

Two concrete findings from #56's final Codex review are mandatory starting
points. Confirm them against current `main` before changing code.

### 2.1 Signed-out Account/Profile semantics

On current `main`, signing out changes the Account destination's `href` to the
Sign in route but leaves at least part of its semantic labeling as Profile.

Inspect both the rail/mobile Account destination and the top-bar identity
affordance.

When a control navigates to Sign in, all user-facing and accessibility semantics
must agree with that destination:

~~~text
visible text
title
aria-label
href
icon meaning where material
~~~

When a user becomes authenticated, restore Profile/account semantics
consistently.

Add regression coverage for anonymous and authenticated states, including the
mobile navigation form.

Do not solve this by hiding the Account destination.

### 2.2 System notices versus mobile Administration surface

At mobile/tablet widths, the Admin-only Administration navigation becomes a
fixed secondary surface above the primary bottom bar.

The system-notice stack must not overlap that surface.

The final layout must account for:

- ordinary signed-in users;
- administrators with the Administration surface visible;
- one or multiple system notices;
- narrow widths used by the existing browser suite;
- notice expansion/collapse/dismissal;
- safe page-bottom clearance.

Prefer a small relationship-based CSS/layout correction over hard-coding a
second independent mobile system.

Add browser regression evidence that the relevant bounding boxes do not overlap.

---

## 3. Rendered finishing pass

After the two mandatory findings are fixed, perform a bounded rendered review of
the current application using the canonical Taste Review.

This review is allowed to produce additional UI changes only when a concrete
rendered defect or interaction-quality problem is identified.

Prioritize the "cared-for details" class of defects:

- stale or misleading labels;
- awkward truncation/wrapping;
- overlapping fixed/sticky surfaces;
- mismatched control heights or alignment;
- accidental empty gaps;
- collapsed content that does not release space;
- loading/error/empty states that shift or weaken hierarchy;
- disabled states without understandable reason;
- duplicated actions;
- responsive layouts that merely shrink rather than recompose;
- dark-mode relationships that became muddy/green or lose hierarchy;
- touch targets/focus states that are technically present but visually poor;
- a toolbar/header becoming louder than the scientific/work object;
- page composition exposing component boundaries as unnecessary cards.

Do not create work just because this is a visual PR.

Every additional change beyond §2 must be explainable in one sentence as a real
current-product problem visible in rendering or interaction.

---

## 4. Pages to inspect

At minimum inspect:

~~~text
Runner catalog
Runner detail
Dashboard
Create Task
Result — structure-rich example
Result — data/table-rich example
Profile / auth shell
Admin Runner Fleet
Admin User Control
Admin Configuration
Admin Logs
persistent system notices
guided-learning / transient notice states where available
~~~

Cover:

~~~text
desktop light
desktop dark
tablet
mobile
anonymous shell where applicable
ordinary authenticated user
administrator
~~~

Not every page needs code changes.

"No change needed" is a valid and preferred result when the current composition
already works.

---

## 5. Composition before decoration

Follow the established order:

~~~text
meaning
→ visual center of gravity
→ reading/scanning path
→ macro spacing
→ density
→ boundaries
→ control polish
→ colour/elevation
~~~

Do not begin by retuning global tokens.

Do not add new decorative motifs, gradients, chart-like decoration, or
scientific-looking data that does not exist.

Do not literalize Monet, the wild rose, the cared-for lab coat, or historical
REvoDesign imagery.

The design references are relational:

> structure has weight; surfaces have air; colour comes from meaning.

---

## 6. Preserve useful density

This PR must not turn expert surfaces into sparse marketing layouts.

Keep:

- direct task actions;
- dense scientific metadata where comparison matters;
- machine-readable identifiers where useful;
- operational controls in Admin;
- provenance and result evidence;
- advanced parameters behind existing progressive disclosure;
- meaningful status redundancy.

A cleaner screenshot that slows an expert down is a regression.

---

## 7. Result workspace

Do not redesign the Result architecture.

Only refine Result UI when current rendering demonstrates a finishing defect.

The scientific artifact remains the visual center.

Chrome must not become more vivid than structures, matrices, plots, sequence
colouring, or other genuine scientific content.

Do not change ResultManifest semantics, artifact contracts, viewer protocol, or
scientific interpretation in this PR.

---

## 8. Admin surfaces

The Admin UI may remain dense.

Do not turn Runner Fleet, User Control, Configuration, or Logs into decorative
dashboard cards.

Focus on:

- comparison;
- state legibility;
- action consequence;
- alignment;
- responsive behavior;
- relationship between global shell and local admin content.

Do not touch backend operator semantics, readiness logic, resource accounting,
or scheduler behavior.

A missing/broken server route or backend contract is out of scope for this PR;
record it separately rather than disguising it with frontend fallback behavior.

---

## 9. Responsive behavior

Test narrow layouts as compositions, not reduced desktop screenshots.

At minimum inspect widths around:

~~~text
320px
360px
390px
tablet breakpoint
desktop
~~~

Pay particular attention to simultaneous fixed/overlay UI:

~~~text
bottom navigation
Administration secondary navigation
system notices
transient notices
dialogs/popovers
language menu
~~~

No important control may be covered by another persistent surface.

---

## 10. Accessibility

Do not regress:

- semantic labels;
- accessible names matching action/destination;
- keyboard navigation;
- visible focus;
- screen-reader structure;
- WCAG AA text/control contrast;
- reduced-motion behavior;
- touch targets;
- status not conveyed by colour alone.

The signed-out Account finding in §2 is an accessibility bug as well as a copy
bug.

---

## 11. Dark mode

Inspect dark mode independently.

Do not accept:

- green-black industrial tint;
- black-glass styling;
- neon accents;
- lost separator hierarchy;
- scientific colours becoming dull or chrome becoming more saturated than data.

Prefer local corrections when only one surface is wrong.

Do not retune the full palette without strong rendered evidence.

---

## 12. Motion

Motion exists only to explain state/spatial continuity.

Allowed examples:

- disclosure continuity;
- panel open/close;
- action confirmation;
- avoiding abrupt layout shift.

Do not add:

- hover lift to static content;
- decorative entrance animation;
- parallax;
- scroll spectacle;
- "premium" motion with no informational purpose.

Respect reduced motion.

---

## 13. Current deployment topology

Development remains on the 309 host.

Current roles:

~~~text
https://revocompute.yaoyy.moe/
    production; follows main

https://revocompute-demo.yaoyy.moe/
    309 development/demo environment
~~~

Do not use the production deployment for routine iteration.

Use local/frontend fixture/browser testing first.

If a deployed visual check is needed, use only the 309 demo environment and
preserve host-local deployment overlays. Do not overwrite unrelated local
configuration.

This PR does not own production deployment.

---

## 14. No Commander dependency

This PR is intentionally independent of the active multi-agent campaign.

Do not require Commander approval for ordinary implementation progress.

Do not ask Commander to:

- allocate this owner;
- reserve a campaign slot;
- schedule its review;
- manage its worktree;
- rebase it;
- deploy it;
- include it in the campaign DAG.

The campaign may advance `main` independently.

The owner follows `main` and reconciles this branch as needed.

Final squash-merge authority remains with the maintainer.

---

## 15. Testing and evidence

Use the real production frontend code and existing fixture/browser harness.

Run focused tests while iterating.

Before final review, at minimum run the current canonical equivalents of:

~~~bash
cd frontend
npm ci
npm run typecheck
npm run test
npm run build
cd ..

python -m pytest tests/test_playwright_application.py -q
python -m pytest tests/test_playwright_soft_precision.py -q
python -m pytest tests/test_playwright_results.py -q
python -m pytest tests/test_playwright_runner_fixtures.py -q
mkdocs build --strict
git diff --check
~~~

Add focused regression coverage for the two mandatory §2 findings.

Do not weaken existing tests to accommodate a visual change.

Rendered evidence should be bounded and useful for human judgment; do not create
a giant screenshot artifact tree or pixel-golden test suite.

---

## 16. Subtraction pass

Before final review:

- remove CSS made obsolete by the finishing changes;
- remove duplicate selectors/overrides introduced during iteration;
- remove temporary visual-debug code;
- remove unused tokens only if this PR made them obsolete;
- verify no second navigation/notice behavior was created;
- remove PR-local screenshots/scratch output that are not intended evidence.

Do not use this as a general CSS cleanup campaign.

---

## 17. PR working-artifact retirement

`TODO.md` is an ephemeral PR-local design artifact.

Before returning `READY_FOR_FINAL_REVIEW`:

1. migrate any newly discovered durable visual rule into the canonical frontend
   design docs only if it is genuinely reusable;
2. create a separate follow-up issue/PR for real unfinished work that should not
   expand this PR;
3. delete this root `TODO.md`;
4. delete any temporary `IMPLEMENTATION_STATE.md` if one was created;
5. verify no code/docs refer to those ephemeral files;
6. clean PR-local generated evidence/scratch that should not merge.

The merged tree should contain product/documentation truth, not execution memory.

---

## 18. Definition of done

This PR is ready for final review when:

1. both post-#56 findings in §2 are confirmed against current main and correctly
   resolved;
2. anonymous/authenticated Account/Profile semantics agree across visible and
   accessible labels;
3. mobile system notices do not overlap the Administration surface;
4. a bounded rendered audit of the current major pages is complete;
5. every additional UI change has a concrete rendered/interaction rationale;
6. no backend/scientific/control-plane contract changed;
7. no second design system or framework was introduced;
8. desktop/light/dark/tablet/mobile behavior remains coherent;
9. accessibility invariants hold;
10. focused frontend/browser tests and build gates pass on the exact head;
11. the subtraction pass is complete;
12. `TODO.md` and any temporary execution-state file are removed before
    `READY_FOR_FINAL_REVIEW`;
13. the exact head is reported to the maintainer for final merge decision.

Do not merge automatically.
