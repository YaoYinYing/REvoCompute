# Cared-for Precision — Post-Soft-Precision Visual Refinement

## Objective

This PR is a **taste refinement pass after PR #54**, not another frontend
architecture rewrite.

PR #54 established the current Soft Precision system, shell behavior, i18n,
notices, guided learning, Dashboard control model, responsive behavior, and a
durable frontend design contract. Keep those capabilities and their ownership
boundaries.

The new goal is narrower and harder:

> **Recover the authored, cared-for scientific character that existed in early
> REvoDesign / REvoCompute, while keeping the modern frontend architecture.**

The result should feel less like a competent design system assembled itself and
more like a scientific instrument that has been used, maintained, adjusted, and
looked after by people who care about the work.

This is not a nostalgia project and not a pixel restoration.

Use the current application as the implementation baseline, the historical
REvoDesign server UI as visual ancestry, and the companion art-direction/taste
documents as judgment aids.

Read, in this order, before editing:

```text
CLAUDE.md
LONG_TASK_HANDLING.md
TODO.md
IMPLEMENTATION_STATE.md
docs/developer-guide/frontend-design-language.md
docs/developer-guide/frontend-art-direction.md
docs/developer-guide/frontend-visual-ancestry.md
docs/developer-guide/frontend-taste-review.md
```

Also inspect the rendered application before making visual changes.

---

## 0. Governing idea

The working phrase for this pass is:

# Cared-for Precision

It refines, rather than replaces, **Soft Precision**.

Soft Precision already says the interface should be quiet, precise, gentle, and
trustworthy. Cared-for Precision adds a missing quality:

> **The interface should feel used, maintained, and intentionally composed —
> not freshly generated, cosmetically polished, or industrially standardized.**

Three short rules should stay visible throughout the work:

> **The surface is gentle. The hierarchy is decisive.**

> **Soft surface, substantial structure.**

> **Frameworks implement the design system. They do not define it.**

Do not turn these phrases into decorative motifs. They are decision filters.

---

## 1. Historical visual ancestry

Before redesigning anything, inspect the visual ancestry described in
`frontend-art-direction.md` and, where useful, the historical source in:

- REvoDesign PR #163: `feat(server): full server stack in docker`;
- the early server Dashboard;
- the early Result page;
- the early User Control page;
- the old Create Task styles introduced around that rewrite.

The historical implementation used, among other things:

- warm grey-green page fields rather than sterile white/blue-grey;
- quiet paper-like surfaces;
- IBM Plex Sans with Source Serif 4;
- deep teal structural accents;
- restrained but visible status colour;
- substantial cards and work surfaces;
- science/result content as the visually richest object;
- page-specific composition rather than one universal component layout.

These are **evidence**, not immutable tokens.

Do not copy old CSS mechanically.
Do not restore old templates.
Do not revive obsolete architecture.

The task is to identify why those pages felt authored and preserve the useful
judgments in the current system.

---

## 2. Do not define this work negatively

This PR must not become an anti-shadcn, anti-card, anti-pill, anti-shadow, or
anti-AI-UI purge.

A visual form is not wrong because it became common.

Cards, status rails, pills, shadows, gradients, serif type, icon controls, and
animations are all allowed when they carry enough meaning to justify their
attention cost.

Judge an element with three questions:

1. **What information or interaction does it carry?**
2. **What does the user lose if it is removed?**
3. **Is its visual strength proportional to that value?**

For example, a thin status rail on a Task card may be excellent when it enables
rapid peripheral scanning while a textual status label confirms the state. It is
bad when it exists only because “cards need an accent”.

The target is not novelty.

The target is **appropriate use**.

---

## 3. Preserve architecture; refine composition

Do not reopen the frontend architecture work completed in PR #54.

Preserve:

- current routing and shell ownership;
- current i18n architecture;
- current notice model;
- current guided-learning model;
- current Dashboard search/filter/view semantics;
- current server/scientific source-of-truth boundaries;
- current Result workspace contracts and generic renderer/plugin boundaries;
- current fixture/browser acceptance infrastructure;
- one-click task submission behavior;
- accessibility and keyboard behavior.

A component may be refactored when necessary to improve composition, but this PR
must not become a framework migration or a new frontend abstraction campaign.

The key principle is:

> **A component is a code boundary, not necessarily a visual boundary.**

Componentize behavior aggressively.
Componentize visual framing conservatively.

Users should perceive **objects and relationships**, not a component tree.

---

## 4. Framework and dependency policy

Do not introduce shadcn, another visual framework, or a new UI kit merely to
obtain a look.

Existing libraries may continue to implement mechanics.

A behavior primitive may be added only when it solves a real interaction or
accessibility problem more reliably than the existing code and does not move
visual ownership into the dependency.

The dependency direction must remain:

```text
product/scientific meaning
    ↓
REvoCompute design language
    ↓
semantic REvoCompute components
    ↓
interaction primitives
    ↓
framework / library / DOM / CSS
```

Never invert this into “choose a library component, then shape the product
around its variants”.

---

## 5. Start with a rendered baseline

Before changing tokens or components:

1. build the current frontend;
2. render the major surfaces in light and dark mode;
3. inspect desktop, tablet, and mobile;
4. collect a small local baseline screenshot set;
5. write brief notes in `IMPLEMENTATION_STATE.md` describing where the current
   UI feels:
   - generic;
   - overly componentized;
   - too industrial;
   - too visually thin;
   - too decorative;
   - already correct and therefore should be left alone.

At minimum inspect:

- Dashboard;
- Runner catalog/detail;
- Create Task;
- a representative Result workspace with real scientific visual content;
- Admin / User Control;
- Profile;
- login/public/auth surface;
- long system notice state;
- guided-learning state.

Do not start with a global palette replacement.

Look first.

---

## 6. Work-surface and material quality

The application should feel like a **clean, cared-for working surface**, not a
showroom and not a sterile lab brochure.

Explore, with judgment:

- warm-neutral or very lightly grey-green canvases;
- paper/fabric-like optical warmth without literal texture;
- surfaces that feel solid enough to hold work;
- borders that are present when they help containment;
- restrained shadows that communicate depth rather than polish;
- moderate curvature that softens without becoming bubbly;
- stronger local structure where the task requires it.

Avoid:

- glassmorphism;
- decorative blur;
- floating-everything layouts;
- washed-out low-contrast minimalism;
- “premium” cream palettes that become lifestyle branding;
- obvious painterly textures;
- faux paper grain;
- floral or laboratory-themed decoration.

The metaphor is experiential, not literal.

---

## 7. Colour: relation before palette

Do not convert the art references into a direct paint-by-number palette.

The important lesson from Monet is not “use blue and green”.
It is that **colour participates in an environment**.

Use colour so that:

- neutral surfaces are not optically sterile;
- white can carry environmental warmth/coolness without ceasing to read as
  white;
- scientific results may remain the richest colour on the page;
- semantic states remain immediately legible;
- the identity accent is authoritative because it is not sprayed everywhere;
- dark mode is independently composed rather than mathematically inverted.

The strongest art reference is Monet's **Woman with a Parasol**; **Water
Lilies** is a secondary reference for softened boundaries and colour
relationships.

Interpret, do not imitate.

No Monet gradients.
No painterly backgrounds.
No decorative brush effects.

The useful relationship is:

> **structure has weight; surfaces have air; colour comes from meaning and
> content; the whole page is connected by light rather than by boxes.**

---

## 8. Typography and editorial character

Re-evaluate typography as composition, not branding.

The historical UI used IBM Plex Sans + Source Serif 4 successfully in some
contexts. The current application does not need to restore that exact pairing,
but the agent may explore selective editorial contrast if it genuinely improves
page identity.

Possible uses include:

- high-level page titles;
- method/result titles;
- quiet section identity where a sans-only hierarchy feels generic.

Do not:

- force a serif onto every heading;
- turn the product into a magazine;
- use decorative display fonts;
- sacrifice technical legibility.

Machine facts remain exact and easy to compare:

- task IDs;
- hashes;
- job IDs;
- filenames;
- versions;
- wall times;
- numerical metrics.

Human language and machine identity should remain visibly distinct.

---

## 9. Dashboard

Preserve the successful information architecture:

```text
page identity
→ task overview
→ search/filter controls
→ task collection
```

Refine visual composition rather than adding features.

### Task collection

A Task is a real domain object and may legitimately remain card-like.

The Task card should feel substantial enough to be scanned repeatedly without
looking like a generic SaaS card template.

Allowed and encouraged when useful:

- a thin semantic status rail for fast peripheral scanning;
- a textual status indicator for confirmation/accessibility;
- machine-text Task ID;
- compact aligned metadata;
- contextual action hierarchy.

Avoid:

- status colour as large card fill;
- metadata microcards nested inside every card when typography/alignment is
  enough;
- equal-weight button rows;
- decorative icon tiles;
- multiple redundant visual state encodings that add noise rather than speed.

Do not remove the status rail merely because it is common.
Keep it if the rendered comparison proves it improves scanning.

### Summary

Summary statistics should feel integrated with the work surface.
They need not be independent floating cards.

Never invent charts or sparklines.

### Search/filter/view

Keep simple search obvious.
Keep advanced search progressive.
Keep view switching independent from filtering.

The visual grouping should make those semantics obvious without requiring every
control group to have its own framed panel.

---

## 10. Result workspace

The Result workspace is the strongest test of the entire art direction.

The scientific result should have the highest visual authority.

For a structure result:

- the molecular scene may be the most colourful object on the page;
- surrounding chrome should recede;
- files/provenance/diagnostics remain inspectable but secondary;
- controls should feel like tools attached to the scientific stage, not a
  toolbar demo.

For matrices, alignments, tables, plots, and other scientific results:

- preserve real data density;
- give the primary artifact enough scale;
- use surrounding whitespace deliberately;
- avoid wrapping every sub-region in competing cards;
- keep provenance and exact machine facts accessible.

Do not modify scientific semantics to make the screen prettier.

Do not add fabricated scientific decoration.

A useful review question:

> **If the scientific artifact disappeared, would the page still look like a
> polished product screenshot?**

If yes, the chrome may be too loud.

---

## 11. Runner catalog and Runner detail

The Runner catalog is a scientific registry, not an app marketplace.

Cards/rows may be used because Runners are domain objects, but avoid “product
tile” styling.

Prioritize:

- method identity;
- capability;
- runtime/readiness/access state;
- useful scientific description;
- clear path to task creation.

Runner detail may take on a slightly more editorial/monograph-like composition
than Dashboard, provided it stays operationally useful.

Do not add decorative hero art.

Do not colour-code every Runner.

---

## 12. Create Task

Create Task should feel like controlled scientific preparation.

Inputs and parameter groups are allowed to be componentized internally.
Visually, however, the user should perceive:

```text
what am I submitting?
what does this method need?
what will happen?
submit
```

rather than a grid of form cards.

Use progressive disclosure for advanced parameters.

Keep server-owned parameter vocabulary and help authoritative.

Do not reintroduce Review → Submit.

Do not add a second decorative “summary card” merely to restate the form.

---

## 13. Admin / User Control

Admin surfaces are allowed to be denser and more direct.

Do not sanitize them into sparse consumer SaaS settings pages.

Preserve fast scanning, table-like relationships, and operational action
visibility.

The historical User Control page is a useful ancestry reference because it
combined:

- editorial page identity;
- an unapologetically functional table;
- clear active navigation;
- compact status;
- many real actions;
- a visually strong destructive/reset region.

### GPU credit reset

The visually strong reset action may remain intentionally conspicuous.

It carries:

- destructive/large-scope semantics;
- operator consequence;
- a small piece of authorial humour/history.

Do not manufacture additional jokes to imitate it.

The lesson is simply:

> **A serious tool may contain restrained human character when the context earns
> it.**

Safety, confirmation, permissions, and consequence text still outrank the joke.

### Runner fleet control plane (owned by PR #55)

PR #55 owns the Runner control-plane *semantics*; this refinement owns how the
Administration region looks and how the shell composes. When the two meet, the
control-plane behavior is preserved and the visual layer is adapted to it — the
fleet surface uses the merged design language and does not become a separate
"ops dashboard" visual system.

The destination is one Administration region in the left navigation — the same
region as User control, Server logs, and Configuration. There is no second
Administration hierarchy and no top-bar Administration launcher.

The fleet-level view separates, at minimum: Runner family; enabled/deployed
state; derived readiness; the machine-readable reason rendered as understandable
human copy; transient capacity as its own field; access restriction as its own
field; active artifact/runtime identity; last validation time and evidence;
evidence freshness; the recommended corrective action; and any in-flight
operator job.

A Runner detail view exposes evidence lanes such as Doctor, active SIF identity,
Runtime bundle, execution contract, resource policy, `test.yaml`/smoke coverage,
live-test receipt, target host/scheduler identity, and the current invalidation
reason. Where an authoritative source exists, non-operational evidence is shown
separately. No "PASS" badge is manufactured for evidence that has no owner.

Corrective actions are state-aware, and the page never offers a button the plan
contract would reject on submit. A mutation reserves a durable Operator Job and
is polled, so no operator action holds a request open; cancellation is observed
between bounded stages, never claimed mid-stage.

---

## 14. Public/auth/profile surfaces

These pages should inherit the same material quality without becoming brand
landing pages.

Avoid:

- giant marketing gradients;
- illustration for its own sake;
- feature-card walls;
- “AI platform” copy/layout conventions.

Login/register/profile should feel calm, trustworthy, and maintained.

Public pages may be simpler than the authenticated application but should still
belong to the same product.

---

## 15. Motion and tactile quality

The UI should feel responsive and cared for without advertising animation.

Prefer:

- stable layout;
- clear pressed/selected state;
- gentle open/close transitions;
- smooth but short navigation changes;
- non-jarring theme changes;
- predictable focus movement;
- subtle feedback for copy/save/submit operations.

Avoid making “premium” motion a goal.

Do not routinely lift every card on hover.

Do not add parallax, counter animations, ornamental fade sequences, or other
marketing-site behavior.

Respect reduced-motion preferences.

The best motion should be noticed mainly when it is missing.

---

## 16. Authored exceptions

A design system prevents accidental inconsistency.
It must not erase justified exceptions.

An exception is allowed when:

- the content/interaction meaning is genuinely unusual;
- the normal system would weaken comprehension or character;
- the exception remains accessible;
- the rationale can be stated in one sentence.

Examples may include:

- a Result stage breaking ordinary max-width;
- a strongly visible destructive operator control;
- a semantic status rail;
- denser-than-normal Admin layouts;
- a page-specific typographic treatment.

Do not create exceptions just to look original.

> **Low-level design follows rules. Mature design knows why an exception still
> belongs to the same product.**

---

## 17. Per-page composition before component polish

For each major page:

1. identify the primary object;
2. identify the reading/scanning path;
3. remove unnecessary visual boundaries;
4. set macro spacing and page proportions;
5. set content density;
6. only then refine component details.

Do not spend the first half of the PR tuning button radii while page composition
is still wrong.

A useful test:

> **Can a screenshot reveal the DOM/component tree at first glance?**

If every semantic group announces itself as a separate rounded rectangle, revisit
the composition.

---

## 18. Dark mode

Dark mode needs its own art direction.

It must not be:

- light mode with inverted luminance;
- green-black industrial tooling;
- neon AI dashboard;
- black canvas plus glowing borders.

Preserve:

- comfortable long-session reading;
- scientific result colour integrity;
- semantic state separation;
- substantial surfaces;
- clear hierarchy;
- modest warmth/neutrality where possible.

Check structure viewers, matrices, plots, and status colours against both themes.

---

## 19. Responsive behavior

Do not shrink desktop composition into mobile.

Recompose.

On narrower screens:

- preserve object identity;
- preserve primary actions;
- allow metadata to wrap into meaningful rows;
- avoid horizontal control strips that become tiny;
- avoid hiding critical scientific state behind unexplained icons;
- keep touch targets accessible.

The mobile view may have different composition while preserving the same design
judgment.

---

## 20. Taste review rubric

Use `frontend-taste-review.md` throughout implementation, not only at the end.

At each major page, ask at minimum:

- Does the page look **composed** or merely assembled?
- Does it feel **cared for** or freshly generated?
- Is the primary scientific/work object visually dominant?
- Does every strong colour carry meaning?
- Does every card correspond to a real object or necessary boundary?
- Does removing a border break comprehension?
- Are machine facts easy to compare?
- Does complexity reveal itself progressively?
- Is a common convention being rejected only because it became fashionable?
- Is an unusual choice present only because we want originality?
- Could this screen be dropped into a CRM with labels changed? If yes, what
  scientific/product character is missing?

Record important judgment changes in `IMPLEMENTATION_STATE.md`.

---

## 21. Agent freedom

This PR intentionally gives the implementation agent room to make visual
decisions.

The agent may, when justified by rendered comparison:

- recalibrate neutral and accent tokens;
- adjust border/radius/elevation roles;
- change page proportions;
- change spacing rhythm;
- change typography hierarchy;
- selectively introduce/remove serif contrast;
- restore or remove semantic status rails;
- simplify or strengthen cards;
- change control grouping;
- refine dark-mode values;
- improve page-specific composition;
- create small shared primitives when they encode a durable REvoCompute
  judgment.

The agent does **not** need to preserve every Soft Precision pixel from PR #54.

The agent must preserve Soft Precision's **product behavior and design intent**.

When uncertain, prefer rendered evidence and scientific usability over literal
obedience to an old token.

---

## 22. Do not literalize the metaphors

The companion art-direction document intentionally uses sensory and artistic
references.

They are there to communicate taste.

Do **not** implement:

- flowers;
- rose motifs;
- lab-coat illustrations;
- fabric textures;
- detergent imagery;
- Monet reproductions;
- watercolor effects;
- brush strokes;
- pseudo-canvas grain;
- impressionist gradients.

The metaphors describe **care, materiality, air, colour hierarchy, and human
authorship**.

Nothing more.

---

## 23. Interaction and accessibility invariants

Visual refinement must not regress:

- keyboard navigation;
- visible focus;
- screen-reader names;
- WCAG AA contrast for text and critical controls;
- reduced motion;
- touch target usability;
- semantic HTML;
- current route behavior;
- current auth/permission behavior;
- notices and guided-learning state;
- downloadable results;
- Result workspace semantics;
- task action safety.

Colour may never be the only status channel.

A more tasteful screen that is harder to use is a regression.

---

## 24. Active PR coordination

At PR creation time:

- PR #55 is active around the Admin Runner control plane;
- PR #47 is active around persistent execution / adaptive OOM provenance.

Do not duplicate their domain work or overwrite behavior they own.

If their changes overlap files this refinement needs:

- rebase when appropriate;
- preserve their behavior;
- adapt the visual layer after their ownership changes land;
- do not “solve” merge conflict by reverting their feature work.

This PR owns visual/taste refinement, not those features.

---

## 25. Evidence and review workflow

Use the existing fixture/browser harness.

Maintain a bounded before/after storyboard for human review.

Recommended final screenshots:

- Dashboard — desktop light;
- Dashboard — desktop dark;
- Dashboard — mobile or narrow tablet;
- Runner catalog/detail;
- Create Task with advanced parameters visible;
- Result with a colour-rich molecular/scientific artifact;
- Result with a data-dense non-structure artifact;
- Admin / User Control;
- Profile/auth;
- persistent long notice;
- guided-learning state.

The screenshot set is review evidence, not a pixel-golden test corpus.

Do not add brittle screenshot-diff tests purely to freeze taste.

The implementation agent should inspect the actual rendered pages at meaningful
milestones rather than waiting until the end.

---

## 26. Test gates

Run the focused frontend tests while iterating, then at minimum:

```bash
cd frontend
npm ci
npm run typecheck
npm run test
npm run build
cd ..

python -m pytest tests/test_playwright_application.py -q
python -m pytest tests/test_playwright_soft_precision.py -q
python -m pytest tests/test_playwright_results.py -q
mkdocs build --strict
git diff --check
```

Also run any focused browser or server tests required by files actually changed.

If a previously named test moves or is superseded on current main, use the
canonical replacement and record it in `IMPLEMENTATION_STATE.md`.

Do not weaken functional tests to accommodate a visual rewrite.

---

## 27. Subtraction pass

Before final review, perform a visual and code subtraction pass.

Remove:

- CSS rules made obsolete by the refinement;
- duplicated surface/button/status treatments;
- unused tokens;
- legacy classes no longer rendered;
- redundant visual wrappers;
- decorative UI that no longer earns its space.

Do not leave two visual systems fighting each other.

Do not keep old CSS “just in case”.

---

## 28. Definition of done

This PR is ready for final review when:

1. the current PR #54 architecture and product behavior remain intact;
2. the major pages have been inspected and compositionally refined rather than
   merely recoloured;
3. the product no longer reads primarily as generic AI-SaaS / enterprise
   dashboard styling;
4. useful conventional elements remain when they have semantic value;
5. scientific content is visually dominant where science is the page purpose;
6. the UI feels substantial enough for daily expert use without becoming
   industrial;
7. light and dark modes both feel intentionally composed;
8. mobile/tablet views are recomposed rather than shrunk;
9. design-system consistency remains, but justified authored exceptions survive;
10. no new visual framework dictates the product language;
11. the taste rubric has been used against the final rendered pages;
12. browser/function/accessibility gates pass;
13. `IMPLEMENTATION_STATE.md` records the final judgment changes and evidence;
14. the final head is brought to `READY_FOR_FINAL_REVIEW`.

Do not merge.

The intended outcome is difficult to reduce to tokens, and that is deliberate.

A successful final screen should feel:

> **carefully composed, not systematically decorated; clean without sterility;
> soft at the surface, substantial underneath; precise without being
> industrial; serious about the work without wearing a serious face.**
