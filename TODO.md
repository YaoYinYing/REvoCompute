# TODO — Multi-Agent Visual QA & UI Refinement Campaign

> **Status: PARKED / NOT AUTHORIZED FOR EXECUTION.**
> This draft PR is a planning envelope, not a dispatched implementation task.
> No agent may claim, edit, deploy, test, review for readiness, or merge this PR
> until the maintainer explicitly releases its hold. The currently active
> Resource Governance / publication work has priority. Retain this TODO intact
> while parked; normal cleanup rules apply only after activation.

## Objective and non-goals

Run a bounded, evidence-driven visual QA and refinement campaign against the
**real rendered REvoCompute frontend**. Explore behavior across screen sizes,
themes, languages, states, density, interaction sequences, and scientific result
views; turn observed defects into reproducible issues; fix approved batches with
isolated owners; and independently verify each integrated change.

**Principle: divergent exploration, convergent design.** Explorers discover;
the Issue Collector verifies and deduplicates; Design Authority makes the
aesthetic decision; assigned Fixers implement; an independent Verifier accepts
or rejects. Ten is a **maximum** number of refinement rounds, not a mandatory
quota for generating changes.

Do not create a new UI architecture, design system, generic agent framework,
source of scientific data, fake production API, or a permanent test server just
to support this exercise. Prefer subtraction and existing infrastructure.

## Authoritative context (read after the hold is lifted)

- `CLAUDE.md` and `docs/agents/long-task-handling.md`, including the existing
  Multi-agent Campaign Protocol, Commander/worktree ownership, shared heavy
  resource lease, Independent Advisor, and exact-head review rules.
- `docs/developer-guide/frontend-design-language.md`: **Soft Precision**, the
  canonical visual rules. `frontend/src/styles/app.css` owns live tokens.
- `docs/developer-guide/frontend-art-direction.md`: **Cared-for Precision**;
  Monet references are relational judgment, **never literal UI themes**.
- `docs/developer-guide/frontend-taste-review.md`: ordered review questions,
  **not** a second rulebook.
- `docs/developer-guide/frontend-visual-ancestry.md`: historical evidence,
  not a palette to blindly restore.
- `docs/developer-guide/testing.md` and `tests/frontend_fixtures/`: existing
  production-bundle / canonical-API browser harness.
- Existing browser acceptance under `tests/test_playwright_*.py` and
  `tests/fleet/browser/`; do not replace or fork those tests.
- Inspect current `main`, all active PRs, routes, renderers, component
  ownership, API schemas, and CI at activation time. This plan is not permission
  to assume the present branch/repository state remains unchanged.

## Activation / isolation gate

- [ ] Maintainer explicitly lifts the hold in a **new** instruction.
- [ ] Commander fetches fresh `main` and all active PRs; records dependency,
      branch/worktree, UI ownership, and CI/deployment overlap.
- [ ] Defer start until higher-priority active Campaign work has released the
      shared deployment/browser-test window and no conflicting frontend owner
      remains, or receive a specific authorized concurrency plan.
- [ ] Allocate exactly one PR-scoped worktree for each writer; leave the primary
      repository checkout clean and on synced `main`.
- [ ] Confirm demo-host isolation, data policy, test-account access, browser
      tooling, agent/token/time budgets, and stop mechanism *before* dispatch.
- [ ] Record authorized campaign head SHA and environmental fingerprints.
- [ ] Once activated, maintain durable `IMPLEMENTATION_STATE.md`, issue registry,
      and round manifests in the PR worktree, separated from the design TODO.
      No running workers or disposable screenshots are needed while parked.

## 0 — Baseline and inventory (R0; no UI fixes)

- [ ] Inspect existing frontend/API/auth/route topology and reusable fixture
      capabilities; produce an inventory of Home, Runner catalog/detail,
      Create Task, Dashboard, Result Workspace/Mol*, Profile, and Admin pages.
- [ ] List page ownership, common controls, scientific renderers, user journeys,
      and relevant UI regressions already documented in code/tests or current
      GitHub issues. Distinguish *existing failures* from campaign regressions.
- [ ] Establish a deployment of the **built production bundle** at a temporary,
      authenticated demo origin. Real Flask page entrypoints, routing, static
      assets, and browser auth must work; an API-only mock that hides missing
      production routes is not acceptable.
- [ ] Keep environment isolated from production accounts, secrets, Slurm, Runner
      dispatch, filesystem artifacts, and shared infrastructure. No browsing
      action may submit a real scientific job or perform destructive Admin work.
- [ ] Reuse `tests/frontend_fixtures/` with deterministic canonical API
      projection / authentic read-only result replays for scenarios; do **not**
      add production mock endpoints or duplicate server-owned scientific
      contracts. Use real valid PDB/mmCIF/result samples where the viewer
      requires authentic bytes; mark all simulated data as synthetic.
- [ ] Seed scenario IDs and stable timestamps/content, not unbounded randomness:
      empty, ordinary, dense, queued/running, failed, unavailable, long
      identifiers, quota/admission warning, scientific result, and Admin-heavy.
      Keep the smallest representative fixture set; respect artifact size limits.
- [ ] Capture a pinned R0 baseline: git SHA, fixture revision, demo image digest,
      browser/OS/version, device/viewport, language, theme, state, screenshots,
      console errors, accessibility hints, and existing known failures.
- [ ] Provide a manifest of the URLs and interactions actually reachable by
      normal and Admin test personas. Never invent production destinations.

## 1 — Explorer missions and browser instrumentation

- [ ] Start with **3–5** browser Explorers as short-lived read-only workers,
      scheduled within the existing campaign slot budget. Do not spawn a
      long-lived process or permanent agent farm.
- [ ] Each Explorer gets an explicit persona, scenario, tested revision,
      viewport, theme, language, and a mission with navigation/actions; reserve
      some exploration time for unconstrained discovery beyond the scripted
      journey. Avoid identical missions and repeated screenshots.
- [ ] Use isolated Playwright BrowserContexts for concurrency (cookies,
      localStorage, auth persona, viewport, touch, reduced-motion). Share a
      browser process only where isolation is technically verified. Limit
      headed browser concurrency under the Commander resource lease.
- [ ] Required device baselines in CSS pixels: 375×812, 430×932, 768×1024,
      1024×768, 1440×900, 1920×1080; add 320px stress cases and a real-device
      smoke check when available. Include both orientations, dark/light mode,
      English/Simplified Chinese, keyboard navigation, and reduced motion.
- [ ] Missions must *interact*, not merely screenshot page loads: scroll,
      filter/sort, switch Dashboard modes, expand/collapse cards/tree, use
      dialogs/navigation, load scientific result views, toggle Mol* controls,
      fullscreen/exit, resize, change theme/language, inspect errors and
      back/forward navigation. Capture meaningful intermediate states.
- [ ] Each Explorer executes **at least two distinct journeys and three
      meaningful state transitions per assigned mission where applicable**.
      A failed or blocked path must be reported as such; do not manufacture
      interaction success or a quota of bugs.
- [ ] For reproducibility keep trace/steps, screenshot, browser/console
      evidence, URL, viewport, device, theme, locale, scenario ID, source SHA,
      and observed/expected behavior. Use deterministic seeds, explicit UI
      readiness assertions, bounded retries, and no fixed sleeps as correctness.
- [ ] Never upload credentials, cookies, bearer tokens, real patient/user data,
      secret-containing HARs, or privately owned scientific artifacts into
      reports/CI. Scrub traces and bound retention.
- [ ] For high-impact claims, independently reproduce in a second fresh
      context or against the actual demo route. A screenshot alone is not proof
      of an actionable functional defect.

## 2 — Issue Collector, triage, and design authority

- [ ] Maintain a **single canonical issue registry** scoped to this PR, keyed
      by normalized page/component + trigger + observed effect + revision
      family, with links to all affected viewports/states and bounded evidence.
      Do not automatically turn every observation into a GitHub issue.
- [ ] Lifecycle: observed → reproduced / not-reproduced → triaged →
      design-approved / deferred / duplicate → assigned → fixed →
      independently-verified / reopened. Aesthetic suggestions may be
      `design-proposal`, not counterfeit functional bugs.
- [ ] Minimum record: issue_id, source SHA, source agent/round, route,
      component, scenario, persona, device/viewport, theme, language,
      reproduction steps, expected/observed, category/severity, evidence
      paths, confidence, disposition, owner, fix SHA, verification evidence.
- [ ] Triage **P0** (unusable/unsafe/unauthorized), **P1** (journey blocked,
      missing content, severe overlap), **P2** (clear layout/a11y/interaction
      deficiency), **P3** (taste polish). Do not equate a model's visual
      preference with a functional failure. Escalate security bugs outside
      this PR without absorbing backend/security work.
- [ ] Group root causes before dispatch (design token, shared control, page
      composition, responsive breakpoint, viewer, i18n, accessibility).
      Resolve one shared cause rather than repeatedly patching symptoms.
- [ ] **Issue Collector does not dispatch Fixers.** Design Authority applies
      the canonical Soft Precision + Taste Review judgment before UI changes
      are approved. A concrete written reason is required for aesthetic
      exceptions; the number of Explorer votes is not design authority.
- [ ] Preserve scientific visual prominence, task parameter meanings, exact
      machine values, role-based navigation, useful expert density, no
      invented charts, no SaaS-card proliferation, no industrial green cast,
      and no literal Monet/floral treatment.

## 3 — Fixer ownership and independent verification

- [ ] Commander forms small non-overlapping, component-scoped batches; use
      **2–3 Fixers** where file ownership genuinely separates. One implementation
      owner per active worktree; shared CSS/tokens have exactly one writer.
- [ ] Fixers start from approved issue IDs and immutable evidence, inspect
      existing React/CSS contracts, write a focused failing behavioral or
      browser acceptance test for reproducible functional defects, and make
      the smallest cohesive change. No opportunistic architecture rewrite.
- [ ] Preserve API/routing/authorization, server-owned Task definitions,
      ResultManifest/scientific interpretation, Runner protocols, accounting,
      and Slurm behavior. No simplification by hiding critical expert controls.
- [ ] Run focused checks after each batch: frontend typecheck/unit/build,
      targeted `make test-browser` coverage, keyboard/responsive/i18n checks,
      and existing tests for touched interactions. Use shared CI/host resource
      lease and avoid repeated full-suite runs until integration.
- [ ] Integrate approved Fixer changes into one pinned candidate SHA; deploy
      **only between rounds**. All Explorers in one round inspect the same
      revision and fixture version. Never hot-replace resources mid-journey.
- [ ] Independent Verifier replays exact steps on affected viewports and
      representative neighbors, checks original defect resolved and no
      regressions, and compares before/after screenshots for visual judgment.
      Close only from independent evidence. Failed fixes reopen the same ID.
- [ ] Avoid pixel-golden corpora as taste oracles. Screenshot baselines and
      diff images are review artifacts; assertions should test meaningful
      DOM/accessibility/interaction behavior. Avoid brittle CSS-source tests.

## 4 — Bounded iteration and stopping rules

- [ ] **R0** baseline only. **R1–R3** broad discovery: major routes,
      navigation, responsive failures, blocked journeys. **R4–R6** targeted
      typography/composition/density/viewer improvements. **R7–R8**
      adversarial fresh-eye reviews by new Explorers without prior taste
      judgments. **R9–R10** regression/integration audit only, if necessary.
- [ ] After each round: freeze exploration; reconcile observations; reproduce,
      deduplicate, triage, approve a bounded fix batch; independently verify;
      integrate, run gates, redeploy, and only then dispatch next round.
- [ ] Set a per-round cap on concurrent workers, browser sessions, fix scope,
      evidence bytes, tokens/time, and deployment count. Commander reports
      budget/variance and stops if growth no longer produces valuable findings.
- [ ] Early-stop when **two consecutive rounds** add no reproducible P0/P1
      problems, none remain open, critical journeys pass in targeted devices,
      regressions are not increasing, and remaining P2/P3 yield is insufficient
      to justify risk/cost. Never close a P0/P1 merely to satisfy a metric.
- [ ] Hard stop after R10 or on security risk, unsafe/demo leakage, runaway
      cost, shared-host pressure, unresolved integration conflict, or repeated
      non-convergence; produce a report with open items rather than falsely
      declaring success.
- [ ] At a clean stop, terminate Explorers and Fixers, close browser contexts,
      release leases, remove transient demo data/accounts as authorized,
      preserve bounded sanitized evidence/report, and verify no orphan workers.
      No human-free auto-merge.

## 5 — Acceptance and report

- [ ] Demonstrate at least one full vertical slice: reproducible issue →
      approved triage → owner worktree → focused fix/test → integrated demo →
      independent re-check → verified closure, with source and fix SHAs.
- [ ] Validate the complete user journey on real production page entrypoints
      using the built frontend; fixture success alone does not prove scientific
      acceptance, runtime readiness, or actual Slurm execution.
- [ ] Confirm primary user journeys for normal + Admin personas, light/dark,
      desktop/tablet/mobile, EN/zh-CN, representative scientific results,
      and accessibility/reduced-motion and focus/overflow checks.
- [ ] Run relevant frontend checks, `make test-browser`, `make test` /
      `make test-cov` as applicable, `make test-docker-full-stack` for changed
      server/deployment boundaries, and `mkdocs build --strict` only if docs
      changed. Follow repository CI classification rather than adding an
      unrelated fleet/GPU suite.
- [ ] Produce `Visual Quality Report`: pinned initial/final SHAs; environment;
      scenario inventory; per-round visits/issues (new, duplicates, reopened,
      resolved); severity trend; changed components; before/after comparisons;
      QA/test/CI evidence; known limitations; deferred actionable findings;
      accessibility and language coverage; resource cost and cleanup status.
      Quantitative issue trends are indicators, not fabricated quality scores.
- [ ] Keep curated, non-sensitive evidence at a bounded footprint; use links
      and summaries instead of committing large screenshot/video/trace trees.
- [ ] Resolve overlap with active work; finish exact-head, risk-tiered review
      required by Campaign Protocol; clear working files (`TODO.md` and
      `IMPLEMENTATION_STATE.md`) only when implementation is complete and
      final review is genuinely ready. **Do not merge** without a separate
      explicit maintainer instruction.

## Out of scope

No new permanent staging service, visual AI scoring model, duplicate design
constitution, bespoke generic multi-agent framework, production fake Runner
mode, new scientific fixtures that change declared semantics, user analytics or
personal-data capture, scheduler/CPU/GPU policy edits, new Mol* scientific
features, or broad unrelated refactors. This is a bounded QA/polish campaign,
not a second frontend rebuild.
