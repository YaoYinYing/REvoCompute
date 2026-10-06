# Frontend Taste Review

> **This page is a review instrument, not a rule source.**
> The durable rules live in
> [Frontend Design Language](frontend-design-language.md) — it is the single
> canonical source for surfaces, colour roles, status encoding, typography,
> density, boundaries, per-page composition, motion, dark mode, and the
> accessibility/anti-pattern contracts. The judgment behind those rules lives in
> [Frontend Art Direction](frontend-art-direction.md); historical evidence lives
> in [Frontend Visual Ancestry](frontend-visual-ancestry.md).
>
> Everything below is a **question to ask of a rendered page**, each pointing at
> the rule that answers it. Nothing here defines a second visual system.

It is deliberately not a visual linter. Its purpose is to help a human or coding
agent distinguish a page that merely complies with the system from a page that is
genuinely well composed for REvoCompute. Use it during implementation and again
before final review.

Ask the questions **in order** — meaning before decoration, composition before
controls, and subtraction last.

---

## 1. Composition

- **Does this page feel composed, or assembled?** A composed page has a clear
  visual center, reading path, and reason for each boundary. If it reads as
  assembled, revisit page-level composition before tuning radii or colour.
  (Rules: §3 one working surface, §4 visual gravity.)
- **Is the primary object the most visually important thing on the page?** The
  center of gravity per page is named in §4. Failure signs: a toolbar stronger
  than its data, statistics dominating the Task list, a header eating the
  viewport, every card at equal weight.
- **Can you reconstruct the component tree from a screenshot?** If every
  semantic group has its own rounded rectangle, border, background, header, and
  shadow, the implementation is exposing engineering boundaries as visual ones.
  (Rule: §3; escalate hierarchy in order — spacing, alignment, tonal contrast,
  hairline, explicit boundary, elevation.)
- **Does complexity reveal itself progressively?** Disclosures, advanced panels,
  and secondary controls should not compete with the primary object up front.
  (Rules: §14 Dashboard search/filter, §17 Create Task.)

## 2. Composition order and density

- **Was composition settled before component polish?** Identify the primary
  object, the reading path, and the macro spacing before refining a control.
  (Rule: §3; art direction §13.)
- **Is it macro-space, micro-density?** The page should breathe between major
  systems while Tasks, files, parameters, and result facts stay compact enough
  to scan. Consistency does not mean equal whitespace everywhere — Admin and
  Result may legitimately be denser than a public page. (Rule: §8.)

## 3. Colour

- **What does each non-neutral colour mean?** Every strong colour must answer:
  primary action, active selection, running state, warning, failure, scientific
  data, or method-defined categorical encoding. “The area looked empty” is not an
  answer. (Rules: §5.2 ink not paint, §5.4 no decorative data colour.)
- **Would hierarchy survive in grayscale?** If not, colour is carrying structural
  work that spacing and typography should carry. (Rule: §5.)
- **Is scientific content the richest colour on the page?** Chrome should not
  out-saturate the science. (Rules: §5, §18; art direction §2 wild rose.)

## 4. Status encoding

- **Is any status conveyed by colour alone?** It must not be. A shape cue plus a
  textual label accompany status colour. (Rule: §15.1.)
- **Does a status cue earn its place?** A compact peripheral cue is valid when it
  speeds batch scanning; it is decoration when the card merely “feels unfinished
  without an accent.” (Rules: §2, §15.1.)

## 5. Boundaries and material

- **What relationship does each border or separator clarify?** A border is
  justified when it protects an interactive target, separates independent
  objects, establishes a scientific stage, keeps a dense table readable, or
  defines a popover/dialog layer. (Rules: §3, §6.1.)
- **Does a shadow mean elevation or just polish?** Most surfaces should stand on
  border plus tone. (Rule: §6.2.)
- **Do surfaces feel substantial enough for daily expert use?** Not fragile,
  translucent, washed out, or floating. (Rule: §6.)

## 6. Typography and machine facts

- **Are machine facts exact and easy to compare?** IDs, job IDs, hashes,
  filenames, versions, wall times, and numeric metrics use machine-text
  conventions and consistent formatting. (Rules: §7.2, §15.3.)
- **Do labels recede and values lead?** Is monospace reserved for identity-like
  facts rather than used as “scientific styling”? (Rules: §7.2, §7.3.)
- **Does any display/serif treatment improve composition, or is it a branding
  flourish?** (Rule: §7; art direction §3.)

## 7. Actions and interaction weight

- **Does button weight match importance and consequence?** A flat row of equally
  prominent buttons is a hierarchy failure. (Rule: §20.)
- **Are frequent expert actions still reachable?** Do not hide them merely to
  make a screen look cleaner. (Rules: §15.4, §20.)

## 8. Scientific authority

- **What is the most visually interesting thing on a Result page?** It should be
  the scientific artifact. (Rule: §18.)
- **If the artifact disappeared, would the page still look like a finished
  product screenshot?** If yes, the chrome is too loud. (Rule: §18.)
- **Was any visual data invented?** Never add fabricated sparklines, trend
  charts, progress rings, “health” scores, or scientific-looking decoration.
  (Rules: §5.4, §18.)

## 9. Motion

- **What becomes easier to understand because this moves?** Valid: spatial
  continuity, open/closed state, action confirmation, avoiding layout shift,
  showing where a panel went. Invalid: “premium feel”, hover-lift on static
  content, scroll spectacle. Respect reduced motion. (Rule: §21.)

## 10. Dark mode and responsive

- **Does dark mode feel independently composed?** Not inverted light mode, not
  green-black industrial, not neon, not black glass; scientific colour and
  semantic separation preserved. (Rule: §22.)
- **Does mobile recompose or merely shrink?** Object identity and primary actions
  preserved, metadata wrapping into meaningful rows, touch targets accessible,
  no critical state hidden behind unexplained icons. (Rule: §9.2.)

## 11. Authorship

- **Is there evidence this page was made for this product?** A page-specific
  composition, a justified operator action, a Result layout that yields to the
  science, a carefully worded empty state — none of it decoration.
  (Art direction: §11.)
- **Could this page be dropped into a CRM by changing nouns?** If yes, its
  product character may be over-generalized. (Rule: §2.)

## 12. Convention, cliché, misuse

When something feels “too common”, classify it before removing it:

- **Convention** — a mature pattern that improves comprehension (status labels,
  tabs, checkboxes, cards for stable objects). Use it confidently.
- **Cliché** — widely repeated but possibly valid (rounded cards, pills, soft
  shadows). Question the implementation, not the existence.
- **Misuse** — present without contextual reason (an icon tile on every heading,
  hover-lift on static blocks, an accent on every card). Remove it.

Do not confuse fashion fatigue with functional invalidity.
(Art direction: §14; rules: §2, §25.)

## 13. Exception test

When you break a system rule, state the reason in one sentence. A good rationale
sounds like “the molecular stage breaks max-width because the structure is the
primary scientific object.” A weak one sounds like “it looks cooler.” If no clear
reason exists, prefer the system rule. (Rule: §19.1 authored exceptions; art
direction: §11.)

## 14. Metaphor safety

The art-direction metaphors are judgment aids, not themes. Before shipping
anything inspired by them, confirm you have implemented the *quality* (care,
materiality, air, weight, colour hierarchy, authorship) and not the *literal*
metaphor — no flowers, botanical patterns, fabric grain, lab imagery, Monet-like
gradients, or brush textures. (Rules: §2.1 metaphor safety; art direction:
§2, §7.1.)

## 15. Accessibility preservation

Refinement must not regress keyboard navigation, visible focus, screen-reader
names, WCAG AA contrast, reduced motion, touch targets, semantic HTML, route and
auth behavior, notices, guided learning, downloadable results, Result semantics,
or task-action safety. A more tasteful screen that is harder to use is a
regression. (Rule: §23.)

## 16. Cared-for details

- **Does the interface feel like someone noticed the small things?** Look for
  awkward truncation, stale empty gaps, mismatched control heights, bad label
  wrapping, inconsistent number formatting, jarring transitions, dark-mode
  colour casts, duplicated actions, panels that do not return space when
  collapsed, unexplained disabled states, or a loading state that shifts the
  page. (Art direction: §15.)

## 17. Subtraction

**What can now be removed?** Obsolete CSS, duplicated surface/button/status
treatments, unused tokens, classes no longer rendered, redundant visual
wrappers, decoration that no longer earns its space. Do not leave two visual
systems fighting. (Rule: §25 anti-pattern checklist.)

---

## 18. Fast scoring rubric

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

The score is not a release gate; it locates where a page still feels generic. A
perfect numeric score on a lifeless page still fails the purpose of this
document, and no score excuses a regression against §15 above.
