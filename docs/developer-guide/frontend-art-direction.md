# Frontend Art Direction — Cared-for Precision

This document is a companion to
[Frontend Design Language](frontend-design-language.md), with concrete historical
references recorded in [Frontend Visual Ancestry](frontend-visual-ancestry.md).

The design-language page defines durable system behavior and visual roles.
This page captures the more difficult layer that tokens cannot fully encode:
**art direction, visual ancestry, and taste**.

It exists because a frontend can satisfy every token and accessibility rule and
still feel generic.

The working phrase is:

# Cared-for Precision

It is not a replacement for **Soft Precision**.
It is a refinement of what Soft Precision should feel like when the product is
fully composed.

---

## 1. The emotional target

REvoCompute should not feel new for the sake of feeling new.

It should feel like a tool that has been:

- used;
- cleaned;
- adjusted;
- maintained;
- repaired when necessary;
- returned to the bench ready for another day of work.

The most useful metaphor is not a new lab coat.

It is a **well-used lab coat after being washed, dried, and cared for**:

- clean, but not sterile;
- soft at the surface;
- thick enough to feel safe;
- familiar rather than showroom-new;
- professional without becoming ceremonial;
- quiet enough that the work, not the garment, remains the point.

The phrase “cared for” is more important than “soft”.

Softness can be mimicked with radius and low contrast.
Care is revealed through hundreds of small decisions being right.

---

## 2. The wild-rose metaphor

Another useful metaphor is:

> **a clean white lab coat with one wild rose embroidered into it**

Do not implement this literally.

There must be no floral motif, rose logo, embroidery effect, botanical
background, or “romantic science” decoration.

The metaphor means:

- most of the interface may remain quiet and useful;
- visual vividness should be concentrated;
- the scientific content may provide the richest colour;
- a small authored exception can carry more character than a page full of
  decorative styling.

A structure, heatmap, molecular representation, sequence colouring, or real
scientific plot can be “the rose”.

Some pages do not need a rose at all.
Dashboard or Admin may simply be the clean working garment.

---

## 3. Historical visual ancestry

REvoCompute did not begin from a blank visual history.

A particularly important ancestor is the REvoDesign server rewrite:

- **REvoDesign PR #163**
  — `feat(server): full server stack in docker`
- merged 2026-02-23;
- later inherited into REvoCompute's history.

Reference:

<https://github.com/YaoYinYing/REvoDesign/pull/163>

That rewrite changed the server UI from a relatively generic Tailwind/Open Sans
surface into a distinct visual system.

Historically notable values included:

```css
--bg: #eef2ed;
--paper: #f8faf7;
--ink: #1d2a2f;
--muted: #5d6c72;
--line: #d4ddd8;
--accent: #0f4f63;
--accent-2: #0d6e66;
--warn: #b06c14;
```

and it used IBM Plex Sans with Source Serif 4.

These values are not a palette specification for the current frontend.

Their importance is evidence of several successful judgments:

- the “white” surface was not optically sterile;
- the page field carried a quiet grey-green environmental tone;
- deep teal could anchor structure without becoming a glowing brand colour;
- serif contrast could give high-level identity without turning the whole
  product editorial;
- cards and panels could feel substantial without becoming industrial;
- status colour could be visible without becoming the product identity;
- scientific content could remain the most colourful thing on the screen.

The goal is to recover **why it worked**, not its exact CSS.

---

## 4. What was good about the early Result page

The early Result page is a useful model because the interface willingly stepped
back.

The molecular structure occupied most of the visual authority.
Files and diagnostics remained available but quieter.
The surrounding canvas was pale and calm.
The structure itself supplied vivid magenta, ochre, green, purple, and other
scientific colours.

The important principle is:

> **The interface is quiet where information can speak.**

A scientific result page should not compete with its own result.

This is not an argument for sparse UI.
Dense controls and provenance remain valid when they are useful.

It is an argument for **visual authority**:
the thing the scientist came to inspect should look like the reason the page
exists.

---

## 5. What was good about the early Dashboard

The early Dashboard used a thin colour rail on Task cards for state.

That rail is worth treating carefully.

It is not inherently “AI UI”.
It can provide:

- rapid pre-attentive scanning;
- low-area state encoding;
- a stable peripheral cue across many Tasks.

A textual status label still confirms the exact state and maintains
accessibility.

This is useful visual redundancy.

The rule is not “no status rails”.

The rule is:

> **A status rail may exist when it improves scanning. It must not exist merely
> because a card feels unfinished without an accent.**

This distinction should apply to every conventional visual device.

---

## 6. What was good about the early User Control page

The early User Control page combined two qualities that are easy to separate by
mistake:

- editorial identity;
- unapologetically functional administration.

A large expressive page title coexisted with a dense table, compact status,
multiple operator actions, and strong active navigation.

That combination matters.

REvoCompute is a working application.
It should not remove useful density to make screenshots quieter.

The Admin area is allowed to look busy when the work is genuinely busy.

One memorable example is the large red GPU credit reset action.

Its strength is justified by:

- broad consequence;
- destructive/reset semantics;
- operator context;
- a small piece of project humour.

The point is not to manufacture more jokes.

The point is that **design-system consistency should not erase authorship**.

---

## 7. Precision: laboratory, not industrial

REvoCompute needs precision, but not necessarily **machine precision as an
aesthetic**.

Industrial visual precision tends to suggest:

- metal;
- hard grids;
- black/grey instrumentation;
- cold blue light;
- mechanical separators;
- extreme rectilinearity.

Laboratory precision can be different:

- clean fabric;
- glass;
- labels;
- paper;
- measured markings;
- real sample colour;
- durable work surfaces;
- instruments used by human hands.

The distinction is not decorative.

It affects how the frontend should feel:

> **soft surface, substantial structure**

Controls may have clear boundaries.
Tables may be dense.
Cards may have weight.
Actions may be direct.

The product should not feel fragile, translucent, weightless, or showroom-like.

---

## 8. Monet as art direction

The strongest artistic reference for the current refinement is:

**Claude Monet — _Woman with a Parasol_**

A secondary reference is Monet's **_Water Lilies_** series.

These references must never become literal UI themes.

### 8.1 Woman with a Parasol

The useful qualities are:

- air around substantial objects;
- cloth with weight but movement;
- white that contains environmental colour;
- grass/sky/light connecting the whole scene;
- colour that feels natural rather than assigned;
- composition that is gentle without becoming weak.

A useful translation is:

> **Structure has weight. Surfaces have air. Colour comes from meaning. The
> page is connected by light rather than by boxes.**

The white dress is especially relevant.

It reads as white without being a flat white swatch.
Light, blue sky, shadow, and reflected colour all participate in it.

For REvoCompute, this suggests that neutral surfaces can carry subtle
environmental relationships without becoming visibly tinted themes.

### 8.2 Water Lilies

The useful quality is not “blue-green”.

It is the way boundaries can soften while depth remains.

Water, reflection, sky, plant, and colour overlap without every region needing a
hard contour.

This is useful when thinking about:

- adjacent work surfaces;
- tool bands;
- Result stages;
- control regions;
- page-level grouping.

Do not translate this into gradients.

The lesson is **relational**, not stylistic.

---

## 9. Colour should not behave like component paint

A common generic-product failure is distributing the accent everywhere:

- blue button;
- blue badge;
- blue icon tile;
- blue active nav;
- blue focus ring;
- blue metric;
- blue chart;
- blue gradient.

The accent becomes omnipresent and therefore meaningless.

REvoCompute should use colour more like a scientific manuscript or a painting:
**where colour appears matters as much as which colour appears.**

The surrounding interface can be quiet enough that:

- a molecular representation is vivid;
- a warning is genuinely visible;
- a running state is easy to scan;
- a primary action carries authority;
- a meaningful selection can be unmistakable.

Colour should not be added to “finish” an empty area.

---

## 10. Componentization is not the enemy

REvoCompute should remain strongly componentized in implementation.

Componentization improves:

- behavioral reuse;
- accessibility;
- testability;
- state ownership;
- migration;
- maintenance.

The problem appears when implementation boundaries automatically become visual
boundaries.

A component should not receive, by default:

- its own rounded container;
- its own background;
- its own title;
- its own icon tile;
- its own shadow;
- its own hover effect.

The durable rule is:

> **A component is a code boundary, not necessarily a visual boundary.**

And:

> **Componentize behavior aggressively; componentize visual framing
> conservatively.**

The user should see a Task, a Runner, a scientific Result, a parameter group, a
file tree, or a user record — not “Card components”.

---

## 11. Frameworks must remain below taste

No framework or component library should become a mental dependency.

The most dangerous lock-in is not a package in `package.json`.

It is the habit of asking:

> Which library variant should this be?

before asking:

> What is this object in REvoCompute, and how should a scientist understand it?

The desired ownership order is:

```text
scientific/product meaning
→ REvoCompute art direction
→ semantic component
→ interaction primitive
→ implementation framework
```

A library may solve mechanics.

It must not outsource taste.

---

## 12. Authorship and exceptions

A completely systematized product can become anonymous.

REvoCompute should allow a small amount of authored character when the context
earns it.

Examples:

- a Result stage breaking normal page width;
- a strong operator reset action;
- a semantic Task status rail;
- an Admin page staying dense;
- selective typographic contrast;
- a page-specific relationship between primary and secondary surfaces.

These are not bugs in consistency.

They become bugs only when they are arbitrary.

The standard is:

> **Can the reason for the exception be stated clearly?**

If yes, and usability/accessibility remain sound, it may belong.

---

## 13. Serious work, not a serious face

REvoCompute handles serious scientific computation.

That does not require an emotionally sterile interface.

A professional tool may contain:

- warmth;
- humour;
- surprise;
- a sense that someone cared about a detail.

Do not turn this into playfulness as a product goal.

Do not add mascots, jokes, decorative copy, or whimsical animation simply to
appear human.

Humanity is more often visible through restraint:

- a well-judged label;
- a thoughtful empty state;
- a satisfying copy interaction;
- an unusually clear destructive action;
- a page that knows when to disappear behind the science.

---

## 14. The design should feel composed, not decorated

A useful final sentence for visual review is:

> **REvoCompute should feel carefully composed, not systematically decorated.**

Composition asks:

- where does the eye enter?
- what is read first?
- what is scanned repeatedly?
- where does the page breathe?
- what deserves silence?
- what should be dense?
- what should be vivid?
- what can disappear?

Decoration asks:

- what can be added to make this feel designed?

Prefer composition.

---

## 15. Avoid aesthetic over-correction

Do not let dislike of generic AI-generated UI create a new formula.

It is easy to replace one cliché with another:

```text
rounded SaaS cards
→
editorial minimalism
→
thin borders
→
huge whitespace
→
monochrome
→
oversized type
```

That is still a template.

Do not reject a useful convention merely because it is common.

Taste requires distinguishing:

- **convention** — mature, useful pattern;
- **cliché** — overused pattern that may still be valid;
- **misuse** — a pattern with no contextual reason.

Eliminate misuse.
Question cliché.
Use convention confidently when it helps.

---

## 16. What “cared for” looks like in implementation

“Care” should emerge from details such as:

- text not truncating unexpectedly;
- machine values aligning predictably;
- Result controls not moving when data loads;
- sensible empty states;
- theme transitions not flashing;
- a side panel giving space back when collapsed;
- clear asynchronous feedback;
- button hierarchy matching consequences;
- mobile layouts recomposing rather than squeezing;
- focus state looking intentional;
- precise file-tree density;
- long notices remaining readable;
- failure states exposing enough information to act.

None of these is a branding motif.

Together, they produce character.

---

## 17. Things this art direction does not prescribe

This page intentionally does **not** prescribe:

- one universal radius;
- one mandatory serif;
- one exact neutral hex;
- one card recipe;
- one status treatment;
- one global shadow;
- one fixed density;
- one layout for every page.

Those belong to rendered judgment and the live implementation.

The art direction should survive future framework or token changes.

---

## 18. Short art-direction checklist

When making a visual decision, prefer the option that is:

- more useful before it is more novel;
- more composed before it is more decorated;
- more substantial before it is more glossy;
- more human before it is more “premium”;
- more specific to scientific work before it is more fashionable;
- quieter around the science;
- decisive where the user must act;
- conventional when convention is the clearest answer;
- exceptional only when the context earns it.

A page that satisfies every design-system rule but feels anonymous is not done.

A page that has character but makes scientific work slower is also not done.

The target is both.
