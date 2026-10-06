# Frontend Design Language

This page is the durable visual contract for REvoCompute's frontend. It defines
the principles by which pages, controls, scientific workspaces, and system chrome
are judged. It intentionally describes **roles and behavior** rather than copying
live token values. The live values remain owned by
`frontend/src/styles/app.css`.

The design language has one working name: **Soft Precision**.

**This page is the single canonical source of REvoCompute's visual rules.** If
another frontend document appears to state a rule differently, this page wins.

Three companion pages support it without restating it:

- [Frontend Art Direction — Cared-for Precision](frontend-art-direction.md) —
  the judgment and relational art references behind these rules: the
  *Cared-for Precision* refinement of Soft Precision (why it should feel cared
  for, laboratory-not-industrial character, authorship).
- [Frontend Visual Ancestry](frontend-visual-ancestry.md) — the historical
  evidence (REvoDesign PR #163, exemplars) that justifies these rules.
- [Frontend Taste Review](frontend-taste-review.md) — the ordered questions to
  ask of a rendered page, each pointing back here.

Those pages explain how to preserve authorship, historical character, and
contextual judgment. They are not a second rulebook.

> **Precise without sharpness. Professional without industrial coldness.
> Complex without disorder. Restrained without emptiness.**

REvoCompute should not decorate computation. It should give computation order.

The interface is successful when users stop noticing the interface as a layer
between themselves and the scientific work, while still feeling that every
object, state, and result has been considered carefully.

---

## 1. What REvoCompute should feel like

REvoCompute is not a generic SaaS dashboard, a Microsoft/Fluent-style enterprise
control surface, an HPC administration console, or a futuristic AI product.

It sits between scientific method and computational infrastructure. The
interface should therefore feel:

- **quiet** — scientific content is louder than chrome;
- **precise** — technical facts are formatted and placed consistently;
- **gentle** — geometry and interaction do not feel mechanical or hostile;
- **trustworthy** — the system exposes state, provenance, and consequences.

The user should not think:

> this website looks futuristic.

A better reaction is:

> this system feels complete.

After repeated use:

> this system makes complex computation easy to reason about.

That is the intended identity.

---

## 2. Identity comes from judgment, not motifs

REvoCompute must not depend on one visual gimmick for recognition.

Do not create identity from:

- coloured task rails used as a decorative signature;
- computation-trace lines;
- molecule/DNA decoration;
- unusual card clipping;
- gradients;
- glowing borders;
- icon tiles;
- arbitrary motion;
- a different colour for every Runner.

A mature visual language appears when the same judgments recur across the
product:

- what deserves a boundary;
- what deserves colour;
- what is allowed to be visually loud;
- what can remain plain text;
- how machine facts differ from prose;
- how much space belongs between systems versus within one object;
- how an asynchronous action communicates state;
- how complexity is revealed rather than hidden.

If those decisions are consistent, the product becomes recognizable without
needing a decorative signature.

This is not a ban on conventional visual devices. A thin status rail, card,
pill, shadow, or other familiar pattern is valid when it carries semantic or
interaction value. Judge the reason and attention cost, not whether the pattern
has become fashionable or overused elsewhere.

---

## 3. Overall composition: one working surface

A page is not a stack of components.

Avoid composing pages as:

```text
header card
+ metrics card
+ filter card
+ content cards
+ action cards
```

Instead, treat the page as one working surface with different semantic regions.

Use, in order:

```text
spacing
→ alignment
→ tonal contrast
→ hairline separation
→ explicit boundary
→ elevation
```

A box is not the default tool for hierarchy.

A Task is a true object and may deserve a card.

A search/filter region is usually a tool band and may not need to look like a
separate floating object.

A heading is not a card.

A group of related metadata is usually typography and alignment, not a
collection of chips.

This distinction is one of the most important defenses against generic
AI-generated UI.

---

## 4. Visual gravity

Every page has one visual center of gravity.

Examples:

| Page | Visual center |
| --- | --- |
| Dashboard | the task collection |
| Runner catalog | the available scientific methods |
| Runner detail | the method and its contract |
| Create Task | the user's inputs and parameters |
| Result | the scientific result |
| Admin | system state and controls |
| Profile | account/settings state |

Do not give equal visual weight to every region.

Page title, statistics, toolbars, notices, and secondary controls must support
the primary object rather than compete with it.

A design system is not successful because every component looks equally
finished. It is successful because the page knows what matters most.

---

## 5. Colour

Colour is a semantic resource.

### 5.1 Neutral foundation

The canvas and content surfaces should be neutral.

The background may have a cool bias, but it should not read as visibly blue,
green, or teal. A strong hue in the neutral field muddies both identity colour
and status colour.

Dark mode must be recalibrated independently and must not inherit a green cast.

### 5.2 REvo blue

REvo blue behaves like **ink**, not paint.

Use it for:

- primary action;
- active navigation;
- selected state;
- focus;
- meaningful links;
- identity where identity is needed.

Do not use it simply because an area feels visually empty.

The less often the accent is used, the more authoritative it becomes.

### 5.3 Semantic states

Status colours are not branding.

Use success, warning, running, and danger only where the state itself matters.

A finished task is not a celebration. It is a fact.

A complete task card should not become green.

A failed task may legitimately demand more visual attention because failure can
change the user's next action.

Never communicate status by colour alone.

### 5.4 No decorative data colour

A coloured mini chart must correspond to real data.

Never render a sparkline simply because a metric card looks empty.

> **Never visualize data that does not exist.**

This is both a design principle and a scientific principle.

---

## 6. Surfaces, borders, and elevation

Use a small surface hierarchy:

```text
canvas
surface
raised surface
scientific stage
overlay/dialog
```

### 6.1 Borders

A hairline border is appropriate when an object needs a durable boundary.

A border should not restate a heavy shadow.

A structural separator should not be upgraded to a full card simply because a
component library makes cards convenient.

### 6.2 Shadows

Shadow means elevation.

Ordinary dashboard cards should not float merely to look polished.

Use meaningful elevation for:

- menus;
- popovers;
- dialogs;
- transient overlays;
- a system notice only when it is actually layered above content.

Hover should not routinely lift cards.

### 6.3 Radius

Curvature communicates role.

Use a small role-based scale rather than one global rounded value.

The desired feeling is **softened rectangles**, not bubbles.

Pill geometry is reserved for objects that are truly pill-like:

- status;
- compact tags;
- selected compact indicators where the shape helps grouping.

Buttons, tabs, filters, cards, and navigation do not all need pill geometry.

This is how the interface remains gentle without becoming cute.

---

## 7. Typography

Typography is one of REvoCompute's strongest possible identity systems because
the product handles scientific prose and machine facts at the same time.

### 7.1 Human language

Use the primary sans stack for:

- page titles;
- section titles;
- controls;
- descriptions;
- explanations;
- help text.

Hierarchy comes from size, weight, line-height, spacing, and position.

Avoid decorative eyebrow text, forced uppercase section labels, and stylized
single-word accents inside headings.

### 7.2 Machine facts

Use the machine-text role for things whose exact identity matters:

- task IDs;
- hashes;
- job IDs;
- filenames;
- code-like identifiers;
- residue/sequence notation where appropriate.

Do not turn all scientific numbers into monospace.

Use tabular numerals for comparable numbers and times where available.

### 7.3 Labels and values

Metadata labels should recede.

Values should be easier to compare.

The user should naturally read:

```text
object
→ state
→ important facts
→ supporting facts
→ system detail
```

rather than encountering all levels at once.

---

## 8. Spacing and density

The principal spacing rule is:

> **macro-space, micro-density.**

The page itself may breathe.

Objects and sections may have clear separation.

Inside a Task, parameter list, file tree, result inventory, or admin table,
information should remain compact enough to scan.

Scientific software loses value when useful data is diluted by presentation
whitespace.

Different pages may have different density.

That is not inconsistency.

The design system should support contextual density while preserving the same
visual grammar.

---

## 9. Navigation

### 9.1 Desktop rail

Authenticated desktop navigation defaults to a narrow icon rail.

The rail should feel like quiet product chrome, not an IDE toolbar.

Requirements:

- generous vertical spacing;
- restrained active state;
- no heavy status-coloured edge;
- accessible tooltip/label for icon-only items;
- keyboard support;
- locally persisted expanded/collapsed preference.

Repeated activation of the **current** navigation item toggles the rail between
collapsed and expanded states.

There is no separate collapse-arrow button.

Expansion reveals labels but does not turn the rail into a second content area.

### 9.2 Mobile

Do not force the desktop rail onto mobile.

Mobile navigation should be designed for touch and limited width.

The navigation model may differ while preserving the same information
architecture and vocabulary.

---

## 10. Top bar

The top bar is global chrome, not another navigation layer.

It may contain:

- language;
- theme;
- notice/announcement affordance;
- account;
- role-dependent administration access.

Do not add a search field unless a real global search capability exists.

Do not duplicate page actions into the top bar merely to make it look complete.

The best top bar is one users mostly stop noticing.

---

## 11. Internationalization

The frontend-owned interface supports at least:

```text
English
Simplified Chinese
```

App-owned text belongs to one localization layer.

Language selection should:

- persist;
- update document language;
- localize accessible labels;
- fall back predictably;
- avoid broken string concatenation.

Do not duplicate server-owned scientific vocabulary in frontend translation
catalogs.

Task parameter names, constraints, help, Runner-authored descriptions, and
other server-authoritative semantics remain server-owned unless the server
contract itself gains localization support.

Internationalization must never create a second scientific source of truth.

---

## 12. System notices

Short action feedback and long-lived system communication are different things.

### 12.1 Toasts

Use transient notices for:

- copied;
- submitted;
- saved;
- short failures;
- immediate action feedback.

They disappear.

### 12.2 Persistent system notices

Use a persistent notice surface for:

- maintenance;
- service degradation;
- important availability changes;
- release/migration information;
- operator announcements.

A persistent notice:

- can contain long text;
- has a bounded scrollable body when necessary;
- can be hidden;
- can be reopened from the global notice affordance;
- may be dismissible by stable identity;
- does not permanently steal vertical space.

It should feel like the system speaking clearly, not like a warning banner
trying to stop the user.

---

## 13. Guided learning

REvoCompute should include a hands-on learning path.

The tour teaches the conceptual model:

```text
Runner
→ input
→ Task
→ execution
→ result
→ artifact/provenance
```

It should not behave like a consumer SaaS “welcome carousel”.

A tour step should answer a meaningful question:

- What is a Runner?
- What becomes immutable when I submit?
- Where do I watch task state?
- What makes a result inspectable?
- Where are the artifacts and provenance?

The tour may point at controls, but it should explain the concept represented by
the control.

The module should be optional, restartable, keyboard accessible, and
route-aware. Step copy is frontend-owned and lives in the i18n catalogs, so a
locale change localizes the tour exactly as it localizes the surrounding chrome.

A step whose surface is one concrete object — the result workspace addresses a
single task — is skipped when no such object is available. The tour never
invents an identifier and never navigates to a route it cannot address.

Deep explanation belongs in documentation; the tour teaches orientation.

---

## 14. Dashboard

The Dashboard structure is intentionally conservative.

The current overall shape is useful and should remain recognizable.

### 14.1 Header

The heading tells the user where they are.

It is not a marketing hero.

A page title can be strong without dominating the screen.

### 14.2 Task overview

Task totals are an overview, not five independent products.

Keep the group visually coherent.

Local semantic cues are allowed.

Do not fill each state with a different pastel treatment.

Do not add decorative trend graphics.

### 14.3 Search and filters

The default filter surface is intentionally simple.

High-frequency controls remain visible.

Low-frequency controls enter an **Advanced search** mode.

Search/filter controls should align as a system rather than looking like a row
of unrelated form fields.

The advanced mode should be discoverable but should not dominate the default
state.

### 14.4 View mode

View mode is independent from filtering.

Filtering answers:

> which tasks?

View mode answers:

> how should those tasks be presented?

Detailed, Compact, and Table belong in their own compact control group, separated
from search/filter semantics.

---

## 15. Task cards

Cards remain part of REvoCompute.

A Task is an independent computational object with identity, lifecycle,
metadata, result, and actions. A boundary is therefore meaningful.

### 15.1 What a Task card is not

Do not use:

- a green left rail for Finished;
- a red top rail for Failed;
- whole-card state tinting;
- decorative gradients;
- floating hover lift;
- icon tiles added merely to make the card feel designed.

### 15.2 Information hierarchy

The card should read in this order:

```text
Task name
status
Runner/type
machine facts
time/ownership facts
actions
```

The exact grid changes by viewport.

Metadata remains typography and layout, not micro-cards.

### 15.3 Machine values

Task ID, job ID, hashes, and similar identifiers use machine-text conventions.

Dates, durations, and numeric values use consistent formatting.

### 15.4 Actions

The card is an object before it is a toolbar.

Results is the strongest contextual action.

Archive/download is secondary.

Delete should remain quiet until invoked.

Batch selection is a low-emphasis affordance.

A row of equally prominent buttons is a hierarchy failure.

---

## 16. Runner catalog and detail

The Runner catalog is a scientific method registry, not an app store.

A Runner entry should emphasize method identity and meaning before decoration.

Use available canonical data to present:

- purpose;
- inputs/outputs;
- availability/readiness;
- access;
- source/citation/version where projected;
- relevant resource character.

Do not invent frontend-only scientific metadata.

Comfortable card mode is allowed.

Compact mode should become more registry-like rather than simply shrinking the
same card.

---

## 17. Create Task

Create Task is a preparation surface.

It should make users feel:

> I understand what I am about to run.

It should not add a second confirmation page to create a sense of safety.

Use hierarchy to distinguish:

- input roles;
- required parameters;
- defaults;
- advanced parameters;
- validation;
- the execution/task snapshot.

The owning `task.yaml` remains the source of scientific parameter semantics.

One-click submission remains the product direction.

---

## 18. Result workspace

The Result workspace is where the product's design philosophy matters most.

> **The scientific artifact is the loudest thing on the page.**

Structure, matrix, alignment, trajectory, table, or other result content gets
visual priority.

Provenance, files, logs, diagnostics, and metadata remain easy to reach and
inspect but should not visually overpower the scientific result.

Do not remove controls or information solely to make the workspace look clean.

A professional scientific workspace is allowed to be dense.

Its order should make density legible.

---

## 19. Page personalities

The visual language does not require every page to look the same.

| Surface | Character |
| --- | --- |
| Dashboard | calm overview |
| Runner catalog | curated registry |
| Runner detail | method reference |
| Create Task | controlled preparation |
| Result | scientific workspace |
| Admin | dense system control |
| Profile | quiet settings |
| Public/home | restrained orientation |

Shared identity comes from:

- typography;
- colour semantics;
- geometry;
- spacing;
- control hierarchy;
- interaction grammar;
- language;
- data treatment.

Not from repeating the same card layout.

---

## 20. Controls

Control hierarchy should be visible without relying on saturated colour.

Roles:

- **primary** — commits the main action;
- **secondary** — useful but not dominant;
- **quiet** — ordinary local action;
- **icon** — compact action with an accessible name;
- **danger** — destructive action, visually restrained until confirmation;
- **segmented** — one dimension with mutually exclusive presentation choices.

Avoid turning every control into a pill.

Avoid strong outlines around every low-level control.

Focus remains clear but should not resemble harsh enterprise-software chrome.

---

## 21. Motion

Motion explains change.

It does not decorate the product.

Appropriate motion includes:

- navigation expansion;
- advanced-search reveal;
- notice show/hide;
- dialog/popover entry;
- local state transitions.

Avoid:

- default card lift;
- ambient movement;
- large page transitions;
- decorative shimmer;
- animated status except where time/progress is genuinely represented.

Always respect reduced-motion preferences.

---

## 22. Dark mode

Dark mode uses the same semantic hierarchy but a separately calibrated palette.

It should:

- stay neutral;
- avoid green/teal wash;
- use softer boundaries;
- avoid pure white text;
- preserve accent distinction;
- preserve success/warning/danger distinction;
- give scientific viewers/stages enough contrast.

Dark mode is not “developer mode” and should not drift toward terminal or
cyberpunk aesthetics.

---

## 23. Accessibility

Visual quietness must not reduce accessibility.

Required properties include:

- sufficient text/control contrast;
- non-colour status cues;
- visible focus;
- keyboard access;
- meaningful accessible names for icon controls;
- source order matching reading order;
- reduced-motion support;
- touch-friendly targets;
- correct document language.

A control that is visually subtle must remain behaviorally obvious.

---

## 24. Writing

Interface copy is visual design.

Use stable verbs and nouns.

Do not call the same thing “Run”, “Submit”, “Create”, and “Start” across
different screens unless the concepts are genuinely different.

Prefer language that describes the user-facing object, not internal
implementation.

Error text says:

- what happened;
- what the user can do next.

Avoid apology, marketing language, and vague reassurance.

---

## 25. Anti-pattern checklist

A change should be questioned when it adds any of the following without a strong
semantic reason:

- a new coloured side rail;
- a decorative icon container;
- a new pastel surface;
- a new shadow level;
- a new radius value;
- a new pill;
- a chart with no decision value;
- a card whose only content is another layout group;
- a hover transform;
- a global top-bar control with no real global capability;
- a duplicate frontend copy of server-owned vocabulary;
- an animated effect that does not explain state.

The goal is not austerity.

The goal is that every visible decision earns its place.

---

## 26. The design test

A REvoCompute screen should pass three questions.

### First glance

Can I tell what this page is for?

### Ten seconds

Can I tell what matters most and what I can do?

### Ten minutes

Do I trust that the interface is showing me the important facts without hiding
the complexity I may need later?

A fourth, brand-level test is useful:

> If the REvoCompute wordmark is removed, does the interface still feel like a
> coherent product with a recognizable order?

Recognition should come from the system's judgment, not a decorative motif.

---

## 27. Manifesto

> **REvoCompute does not decorate computation. It gives computation form.**
>
> Its interface is quiet where information speaks for itself, precise where
> facts matter, and gentle where complexity could otherwise become friction.
>
> Objects have boundaries because they are objects, not because everything needs
> a card. Colour carries meaning. Space establishes hierarchy. Typography
> distinguishes explanation from evidence. Complexity is preserved, but revealed
> in layers.
>
> REvoCompute should never feel futuristic, industrial, playful, or corporate.
> It should feel considered.

In shorter form:

> **Precise, not sharp. Professional, not industrial. Complex, not chaotic.
> Restrained, not empty.**
