# Frontend Taste Review

This page is a practical review companion for
[Frontend Design Language](frontend-design-language.md) and
[Frontend Art Direction](frontend-art-direction.md).

It is deliberately not a visual linter.

The purpose is to help a human or coding agent distinguish:

- a page that merely complies with a design system;
- a page that is genuinely well composed for REvoCompute.

Use this during implementation and again before final review.

---

## 1. The first question

Before checking tokens, ask:

> **Does this page feel composed, or does it feel assembled?**

A composed page has a clear visual center, reading path, density, and reason for
each boundary.

An assembled page may be perfectly consistent but still look like a collection
of library components.

If the answer is “assembled”, do not immediately tune radii or colours.

Revisit the page-level composition.

---

## 2. Primary-object test

Identify the primary object of the page.

Examples:

- Dashboard → Task collection;
- Runner catalog → available methods;
- Runner detail → the method and its contract;
- Create Task → the user's inputs and parameters;
- Result → the scientific result;
- Admin → system/user state;
- Profile → account/settings state.

Then ask:

> **Is that object visually more important than the controls around it?**

Failure patterns include:

- a toolbar stronger than the data it controls;
- statistics dominating the Task list;
- a file tree competing with the scientific result;
- a large title/header consuming too much viewport;
- every card having equal weight.

---

## 3. Component-seam test

Look at the page from a distance.

Can you reconstruct the component tree immediately because every semantic group
has:

- a rounded rectangle;
- its own border;
- its own background;
- its own header;
- its own shadow?

If yes, the visual implementation may be exposing engineering boundaries.

Remember:

> **A component is a code boundary, not necessarily a visual boundary.**

Try hierarchy in this order:

```text
spacing
→ alignment
→ typography
→ tonal contrast
→ hairline
→ explicit boundary
→ elevation
```

Do not jump directly to another card.

---

## 4. Card legitimacy test

For every card-like object, ask:

1. Is this a stable domain object?
2. Does the boundary improve scanning or interaction?
3. Would removing the card make relationships less clear?

Good candidates:

- Task;
- Runner when used as a catalog object;
- dialog/popover;
- bounded scientific stage;
- genuinely independent settings group.

Weak candidates:

- one heading plus two lines of text;
- a filter bar that could be a tool band;
- a metadata group that could be aligned text;
- an icon and description used only to fill space.

The goal is not fewer cards.
The goal is **earned cards**.

---

## 5. Colour legitimacy test

For every non-neutral colour, ask:

> **What does this colour mean?**

Acceptable answers include:

- primary action;
- active selection;
- running state;
- warning;
- failure;
- scientific data;
- method-defined categorical encoding.

Weak answers include:

- “this area looked empty”;
- “the design needed more personality”;
- “the component library uses this variant”;
- “every card needs an accent”.

Also ask:

> **If the page were converted to grayscale, would hierarchy still work?**

If not, colour may be carrying too much structural responsibility.

---

## 6. Status-encoding test

Status may legitimately use more than one channel.

For a Task, for example:

- a thin coloured rail can support fast scanning;
- a text label can confirm exact state;
- iconography may help where it adds meaning.

This is useful redundancy when each channel has a job.

It becomes noise when all channels are equally loud.

Never reject a status rail solely because it is common.

Reject it when it is decorative.

---

## 7. Boundary test

For each border or separator, ask:

> **What relationship does this boundary clarify?**

A border is justified when it:

- protects an interactive target;
- separates independent objects;
- establishes a scientific stage;
- keeps a dense table readable;
- defines a popover/dialog layer.

A border is suspect when it merely repeats grouping already made obvious by
spacing and alignment.

Likewise, a shadow should mean elevation rather than “polish”.

---

## 8. Material/substance test

REvoCompute should not feel fragile.

Ask:

- do surfaces feel substantial enough for repeated expert use?
- are controls too translucent or visually thin?
- is the page so low-contrast that it feels washed out?
- does every panel float, making the application feel weightless?
- does dark mode feel like black glass rather than a work surface?

The target is:

> **soft surface, substantial structure**

---

## 9. Scientific-authority test

On a Result page, ask:

> **What is the most visually interesting thing on the screen?**

Usually, the answer should be the scientific artifact.

A colourful molecular structure, heatmap, alignment, or plot should not need to
fight:

- a gradient header;
- bright card accents;
- oversized file chrome;
- colourful navigation;
- decorative icons.

If removing the scientific result still leaves a “hero screenshot” that feels
complete, the interface may be too visually self-important.

---

## 10. Data-honesty test

Never add visual data that do not exist.

Reject:

- fake sparklines;
- decorative trend charts;
- arbitrary progress rings;
- “health” scores without a real metric;
- illustrative scientific-looking plots.

Scientific software must be especially strict here.

> **Never visualize data that does not exist.**

---

## 11. Typography test

Ask:

- is page identity clear without exaggerated type?
- are machine facts exact and easy to compare?
- do labels recede appropriately?
- are values visually stronger than their labels?
- is monospace used for identity/code-like facts rather than as “scientific
  styling”?
- does any serif/display treatment improve composition, or is it merely a
  branding flourish?

Typography should create hierarchy before another box is added.

---

## 12. Density test

Use the rule:

> **macro-space, micro-density**

Ask:

- does the page breathe between major systems?
- are Tasks, files, parameters, tables, and result facts compact enough to scan?
- has “clean design” diluted useful information?
- is Admin artificially sparse?
- is mobile cluttered because desktop density was merely squeezed?

Different pages may legitimately have different density.

Consistency does not require equal whitespace everywhere.

---

## 13. Interaction-weight test

Button visual weight should match action importance and consequence.

Reject a row where every action is:

- outlined;
- pill-shaped;
- equal width;
- equal colour;
- equal prominence.

Ask:

- what is the primary contextual action?
- what is secondary?
- what is destructive?
- what is rare/operator-only?
- what can become a menu item without hiding important work?

Do not hide frequent expert actions merely to make the screen cleaner.

---

## 14. Motion test

For each transition or animation, ask:

> **What becomes easier to understand because this moves?**

Good reasons:

- preserving spatial continuity;
- showing open/closed state;
- confirming an action;
- preventing abrupt layout shifts;
- showing where a panel went.

Weak reasons:

- “premium feel”;
- visual excitement;
- every card should lift;
- scroll-triggered spectacle.

Respect reduced-motion preferences.

The best motion is usually noticed when it is absent.

---

## 15. Authorship test

Ask:

> **Is there any evidence that this page was made for this specific product?**

This does not mean adding decoration.

Evidence of authorship may be:

- a page-specific composition;
- a strong but justified operator action;
- a Result layout that yields to the science;
- a carefully worded empty state;
- a semantic status rail;
- a selective typographic decision;
- an unusually good file/provenance layout.

Then ask the inverse:

> **Could this page be dropped into a CRM by changing nouns?**

If yes, the product character may have been over-generalized.

---

## 16. Convention / cliché / misuse test

When an element feels “too common”, classify it before removing it.

### Convention

A mature pattern that improves comprehension.

Examples may include:

- red for destructive action;
- tabs for sibling views;
- checkboxes for selection;
- status labels;
- cards for stable objects.

Use confidently when appropriate.

### Cliché

A widely repeated pattern that may still be useful.

Examples may include:

- rounded cards;
- pills;
- soft shadows;
- icon rails.

Question the implementation, not the existence.

### Misuse

A pattern present without contextual reason.

Examples:

- an icon tile on every heading;
- hover lift on static informational blocks;
- colour accents on every card;
- gradients added to empty space;
- a badge for every metadata value.

Remove misuse.

Do not confuse fashion fatigue with functional invalidity.

---

## 17. Framework-independence test

Ask:

> **If the current UI library disappeared tomorrow, would we still know what this
> object should look and behave like?**

If not, the design may be mentally coupled to the framework.

Semantic components should own REvoCompute meaning.

Interaction libraries may own mechanics.

No framework should own the product's taste.

---

## 18. Exception test

When breaking a design-system rule, write one sentence explaining why.

A good exception rationale sounds like:

- “The molecular stage breaks max-width because the structure is the primary
  scientific object.”
- “The Task rail remains because it improves peripheral status scanning.”
- “The GPU reset action is visually strong because its scope and consequence are
  unusually broad.”
- “Admin remains dense because operators need to compare many users/actions in
  one viewport.”

A weak rationale sounds like:

- “It looks cooler.”
- “We need more personality.”
- “The design felt boring.”

If no clear reason exists, prefer the system rule.

---

## 19. Metaphor safety test

The art-direction metaphors are judgment aids.

Before shipping anything inspired by them, ask:

> **Have I implemented the literal metaphor instead of the quality it was meant
> to communicate?**

Reject literal translations such as:

- flowers;
- botanical patterns;
- fabric grain;
- lab imagery;
- Monet-like gradients;
- watercolor backgrounds;
- decorative brush textures.

Translate:

- care;
- materiality;
- air;
- weight;
- colour hierarchy;
- authorship.

Nothing else.

---

## 20. Light/dark parity test

Do not treat dark mode as an afterthought.

Check:

- neutral hue drift;
- readable hierarchy;
- semantic colour distinction;
- structure/plot colour integrity;
- border visibility;
- surface weight;
- focus visibility;
- warning/destructive clarity.

A dark UI can remain soft without turning green, neon, or glassy.

---

## 21. Responsive composition test

At mobile/tablet widths, ask:

- has the layout been recomposed or merely shrunk?
- is the primary object still obvious?
- are controls still grouped semantically?
- are frequent actions reachable?
- did metadata collapse into an unreadable pile?
- did icon-only controls lose meaning?
- are result surfaces given enough space?

Mobile consistency means preserving judgment, not geometry.

---

## 22. “Cared for” test

This is the least measurable and most important final question:

> **Does the interface feel like someone noticed the small things?**

Look for:

- awkward truncation;
- stale empty gaps;
- mismatched control heights;
- inexplicable alignment;
- labels wrapping badly;
- inconsistent numerical formatting;
- jarring state transitions;
- dark-mode colour casts;
- duplicated actions;
- panels that do not return space when collapsed;
- unexplained disabled states;
- a loading state that shifts the whole page.

A page may have no dramatic visual feature and still feel excellent when these
details are resolved.

---

## 23. Final review sequence

Use this order:

1. **meaning** — what is this page for?
2. **composition** — where should attention go?
3. **density** — what must be visible together?
4. **hierarchy** — what is primary/secondary/supporting?
5. **boundaries** — what truly needs framing?
6. **colour** — where does meaning deserve colour?
7. **type** — can typography do more of the work?
8. **controls** — is action hierarchy clear?
9. **motion** — does transition help understanding?
10. **details** — does it feel cared for?
11. **accessibility** — did refinement preserve usability?
12. **subtraction** — what can now be removed?

Do not review taste in the reverse order.

---

## 24. Fast scoring rubric

For a quick review, score each dimension from 0 to 2:

| Dimension | 0 | 1 | 2 |
| --- | --- | --- | --- |
| Primary object | unclear | present | unmistakable |
| Composition | component wall | serviceable | authored |
| Colour | decorative | mostly semantic | disciplined |
| Density | diluted/cluttered | acceptable | context-appropriate |
| Boundaries | overframed | mixed | earned |
| Scientific focus | chrome dominates | balanced | science dominates |
| Material quality | thin/glossy | neutral | substantial + gentle |
| Framework independence | library-shaped | mixed | product-shaped |
| Authorship | generic | some character | unmistakably REvoCompute |
| Care | rough edges | competent | thoroughly considered |

The score is not a release gate.

It is a way to identify where a page still feels generic.

A perfect numeric score with a lifeless page still fails the purpose of this
document.
