# Frontend Art Direction — Cared-for Precision

> **The rules live in [Frontend Design Language](frontend-design-language.md).**
> That page is the single canonical source for every durable visual rule:
> surfaces, colour roles, status encoding, typography, density, elevation,
> boundaries, task cards, the result workspace, Create Task, and the
> accessibility/anti-pattern contracts. This page does **not** restate those
> rules; when a rule is named here it is a pointer, not a second definition.
>
> This page owns one thing only: the layer tokens cannot encode —
> **the judgment behind the direction** (why it should feel cared for, the
> relational art references, authorship, and laboratory-not-industrial
> character). Historical evidence referenced from a rule belongs to
> [Frontend Visual Ancestry](frontend-visual-ancestry.md); the review questions
> belong to [Frontend Taste Review](frontend-taste-review.md).

It exists because a frontend can satisfy every token and accessibility rule and
still feel generic. The working phrase is **Cared-for Precision** — not a
replacement for **Soft Precision**, but a refinement of what Soft Precision
should feel like when the product is fully composed.

---

## 1. The emotional target

REvoCompute should not feel new for the sake of feeling new.

It should feel like a tool that has been used, cleaned, adjusted, maintained,
repaired when necessary, and returned to the bench ready for another day of
work.

The most useful metaphor is not a new lab coat. It is a **well-used lab coat
after being washed, dried, and cared for**: clean, but not sterile; soft at the
surface; thick enough to feel safe; familiar rather than showroom-new;
professional without becoming ceremonial; quiet enough that the work, not the
garment, remains the point.

The phrase “cared for” is more important than “soft”. Softness can be mimicked
with radius and low contrast; care is revealed through hundreds of small
decisions being right — whose reviewable form is
[Frontend Taste Review](frontend-taste-review.md) §16.

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

REvoCompute did not begin from a blank visual history, and the direction is not
novelty for its own sake.

The lineage, the concrete REvoDesign PR #163 evidence, the historical palette
values, and the Result / Dashboard / User Control exemplars are recorded in
[Frontend Visual Ancestry](frontend-visual-ancestry.md).

That page is the single source for historical evidence. This page does not
restate it.

What matters here is the judgment the ancestry proves, which the design language
now owns as rules rather than as a palette spec: **the “white” surface was never
optically sterile, the page field carried a quiet environmental tone, and the
interface could stay quiet because the scientific content was already the most
colourful thing on the screen.** The current token values are owned by
`frontend/src/styles/app.css`; the roles they play are owned by
[Frontend Design Language](frontend-design-language.md) §5–§6.

---

## 4. The interface yields to the work

The early Result page is the clearest ancestor of the current rule that
**the scientific artifact is the loudest thing on the page**
([Frontend Design Language](frontend-design-language.md) §18).

The judgment worth carrying forward is not a layout ratio:

> **The interface is quiet where information can speak.**

A scientific Result page should not compete with its own result, and the thing
the scientist came to inspect should look like the reason the page exists.

This is not an argument for sparse UI — dense controls and provenance remain
valid when they are useful. The rule is visual authority, not emptiness.

---

## 5. Redundancy, not decoration

A status cue can legitimately combine a compact peripheral mark with a textual
label. That is useful visual redundancy when each channel has a job.

The durable rule is owned by [Frontend Design Language](frontend-design-language.md)
§2 and §15.1: **a status cue may exist when it improves scanning; it must not
exist merely because a card feels unfinished without an accent.**

Do not reject a conventional visual device merely because it is common; judge
its reason and its attention cost.

---

## 6. Authorship survives the system

REvoCompute is a working application, and it should not remove useful density to
make screenshots quieter. Admin may look busy when the work is genuinely busy.

A design system prevents accidental inconsistency; it must not erase justified
authorship. The concrete forms that authorship may take, and the one-sentence
standard an exception must satisfy, belong to §11 below; the durable rule is
owned by [Frontend Design Language](frontend-design-language.md) §19.1. The
historical User
Control page — an editorial page title beside a dense operational table and a
deliberately strong destructive reset action — is the ancestor of that judgment
(evidence in [Frontend Visual Ancestry](frontend-visual-ancestry.md)).

---

## 7. Precision: laboratory, not industrial

REvoCompute needs precision, but not **machine precision as an aesthetic**.

Industrial visual precision tends to suggest metal, hard grids, black/grey
instrumentation, cold blue light, mechanical separators, extreme rectilinearity.

Laboratory precision can be different: clean fabric, glass, labels, paper,
measured markings, real sample colour, durable work surfaces, instruments used
by human hands.

The distinction is not decorative. It is the target the design language states as
**soft surface, substantial structure**
([Frontend Design Language](frontend-design-language.md) §6): controls may have
clear boundaries, tables may be dense, cards may have weight, actions may be
direct — but the product should not feel fragile, translucent, weightless, or
showroom-like.

### 7.1 Monet as art direction

The strongest artistic reference for the refinement is **Claude Monet —
_Woman with a Parasol_**, with **Water Lilies** as a secondary reference.

These references must never become literal UI themes (see the metaphor-safety
questions in [Frontend Taste Review](frontend-taste-review.md) §14, governed by
[Frontend Design Language](frontend-design-language.md) §2.1).

The useful qualities of _Woman with a Parasol_: air around substantial objects;
cloth with weight but movement; white that contains environmental colour;
grass/sky/light connecting the whole scene; colour that feels natural rather than
assigned; composition that is gentle without becoming weak. The white dress
reads as white without being a flat white swatch — light, blue sky, shadow, and
reflected colour all participate in it. For REvoCompute this means neutral
surfaces can carry subtle environmental relationships without becoming visibly
tinted themes.

The useful quality of _Water Lilies_ is not “blue-green”: it is how boundaries
can soften while depth remains — water, reflection, sky, plant, and colour
overlapping without every region needing a hard contour. That is useful when
thinking about adjacent work surfaces, tool bands, Result stages, control
regions, and page-level grouping. Do not translate it into gradients; the lesson
is **relational**, not stylistic.

A useful translation of both references:

> **Structure has weight. Surfaces have air. Colour comes from meaning. The page
> is connected by light rather than by boxes.**

---

## 8. Colour should not behave like component paint

The rule that the identity accent is **ink, not paint** — sprayed only on action,
selection, focus, links, and real semantic state — and that no colour is added
to decorate data is owned by [Frontend Design Language](frontend-design-language.md)
§5.2 and §5.4.

What belongs here is the reasoning, in the direction's own language:

REvoCompute should use colour more like a scientific manuscript or a painting:
**where colour appears matters as much as which colour appears.** The surrounding
interface can be quiet enough that a molecular representation is vivid, a warning
is genuinely visible, a running state is easy to scan, and a primary action
carries authority. Colour should not be added to “finish” an empty area.

---

## 9. Componentization is not the enemy

REvoCompute should remain strongly componentized in implementation.
Componentization improves behavioral reuse, accessibility, testability, state
ownership, migration, and maintenance.

The problem appears when implementation boundaries automatically become visual
boundaries. This is stated as a durable rule — and as the page-composition order
(spacing → alignment → tonal contrast → hairline → boundary → elevation) — in
[Frontend Design Language](frontend-design-language.md) §3.

The judgment to carry: a component should not receive, by default, its own
rounded container, background, title, icon tile, shadow, or hover effect. The
user should see a Task, a Runner, a scientific Result, a parameter group, a file
tree, or a user record — not “Card components”.

> **A component is a code boundary, not necessarily a visual boundary.
> Componentize behavior aggressively; componentize visual framing
> conservatively.**

---

## 10. Frameworks must remain below taste

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

## 11. Authorship and exceptions

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

## 12. Serious work, not a serious face

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

## 13. The design should feel composed, not decorated

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

## 14. Avoid aesthetic over-correction

Do not let dislike of generic AI-generated UI create a new formula. It is easy
to replace one cliché with another:

```text
rounded SaaS cards → editorial minimalism → thin borders
→ huge whitespace → monochrome → oversized type
```

That is still a template.

The classification that keeps this honest — **convention** (mature, useful),
**cliché** (overused but possibly valid), **misuse** (no contextual reason) — and
the test to apply it are owned by
[Frontend Taste Review](frontend-taste-review.md) §12. The direction's summary:
eliminate misuse, question cliché, use convention confidently when it helps.

---

## 15. What “cared for” looks like

“Care” is not a branding motif. It emerges from details being right: text not
truncating unexpectedly, machine values aligning predictably, Result controls
not moving when data loads, sensible empty states, theme transitions not
flashing, a collapsed panel giving its space back, focus looking intentional,
failure states exposing enough information to act.

None of these is individually remarkable; together they produce character. The
reviewable checklist lives in
[Frontend Taste Review](frontend-taste-review.md) §16.

---

## 16. What this page deliberately leaves open

The durable rules — colour roles, surface/elevation/radius roles, typography,
density, per-page composition, motion, dark mode — are owned by
[Frontend Design Language](frontend-design-language.md). This page states the
judgment behind them, not their values.

It therefore does **not** pin:

- one universal radius;
- one mandatory serif;
- one exact neutral hex;
- one card recipe;
- one status treatment;
- one global shadow;
- one fixed density;
- one layout for every page.

Those values live in the implementation and are judged by rendered evidence. The
direction should survive future framework or token changes.

---

## 17. Short art-direction checklist

When a decision is genuinely open — where the rules allow more than one honest
answer — prefer the option that is:

- more useful before it is more novel;
- more composed before it is more decorated;
- more substantial before it is more glossy;
- more human before it is more “premium”;
- more specific to scientific work before it is more fashionable;
- quieter around the science;
- decisive where the user must act;
- conventional when convention is the clearest answer;
- exceptional only when the context earns it.

This checklist resolves ties; it does not override a rule in
[Frontend Design Language](frontend-design-language.md). A page that satisfies
every rule but feels anonymous is not done, and a page with character that makes
scientific work slower is also not done. The target is both.
