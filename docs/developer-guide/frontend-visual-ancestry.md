# Frontend Visual Ancestry

> **This page is the historical evidence record, not a rule source.**
> It answers “what has REvoCompute already judged successfully, and on what
> evidence?” The durable rules live in
> [Frontend Design Language](frontend-design-language.md); the judgment behind
> them lives in [Frontend Art Direction](frontend-art-direction.md). Where a
> historical exemplar points at a current rule, this page cites the rule instead
> of restating it.

Its purpose is to prevent architectural rewrites from being misread as aesthetic
rejections, and to give future designers and agents concrete evidence for what
REvoCompute has already considered successful.

---

## 1. Why this page exists

REvoCompute has changed architecture repeatedly. The server moved from early
Flask templates into an explicit frontend system; Runner/result contracts became
generic; the shell, i18n, notices, guided-learning behavior, and browser
acceptance harness were modernized in PR #54.

Those were engineering decisions. They do **not** imply that every earlier visual
judgment was rejected.

A recurring failure mode in long-lived software is:

```text
architecture rewrite
→ old markup disappears
→ old visual language disappears with it
→ later developers assume the old visual language was intentionally deprecated
```

That inference is unsafe. Use this page to distinguish **obsolete
implementation** from **still-useful visual judgment**.

---

## 2. Major ancestor: REvoDesign PR #163

The most important early ancestor is:

**REvoDesign PR #163 — `feat(server): full server stack in docker`**

<https://github.com/YaoYinYing/REvoDesign/pull/163>

Merged 2026-02-23. The PR was primarily a server/infrastructure rewrite, but it
also contained a substantial visual rewrite of the server-facing frontend.

Relevant historical files included:

```text
server/pssm_gremlin/templates/create_task.html
server/pssm_gremlin/templates/pssm_gremlin_dashboard.html
```

The PR was large and not structured as a modern visual-design PR. That does not
reduce its value as visual evidence.

---

## 3. Historical palette evidence

The Create Task rewrite introduced the following working values:

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

It also introduced IBM Plex Sans with Source Serif 4.

**Do not restore these values blindly.** They are evidence, not a specification;
the current values are owned by `frontend/src/styles/app.css`. What they prove
is that the product once preferred:

- a warm/grey-green environmental neutral over sterile blue-grey;
- a “paper” that read as almost-white yet was not a browser white canvas;
- a deep teal that provided structure without a generic bright-SaaS accent;
- an editorial type contrast coexisting with utilitarian controls.

Those relationships are now owned as roles — not as hex values — by
[Frontend Design Language](frontend-design-language.md) §5 (colour) and §6
(surfaces). Any current palette may differ while preserving them.

---

## 4. Exemplar A — Result workspace

A remembered early Result screen placed a large molecular structure stage on the
left and a narrower Files & diagnostics surface on the right.

The valuable properties were:

- the molecular structure was visually dominant;
- surrounding UI used quiet pale surfaces;
- scientific representation colours supplied the strongest chroma;
- file inventory remained dense and usable without competing with the molecule;
- the page felt like a workbench, not a presentation slide.

### Preserve why

Do not copy the exact split ratio or old viewer chrome. Preserve the judgments
now stated as the primary rule of
[Frontend Design Language](frontend-design-language.md) §18 — *the scientific
artifact is the loudest thing on the page* — and its corollary: the interface can
become visually quiet because the scientific object is already visually rich.

---

## 5. Exemplar B — Task Dashboard

A remembered early Dashboard used substantial Task cards, a thin left status
rail, status labels, machine-like Task IDs, aligned Submitted / Finished / Wall
Time facts, compact sequence disclosure, and direct task actions.

The status rail should be understood as **semantic peripheral encoding**, not as
a decorative brand stripe: it let the eye scan state without reading every label.

### Preserve why

The rail is a legitimate tool when it encodes real state, improves batch
scanning, remains visually quiet, and is confirmed by text for accessibility —
which is exactly the rule now owned by
[Frontend Design Language](frontend-design-language.md) §15.1. Do not make “no
rails” a design ideology, and do not keep a rail that is merely decorative.

---

## 6. Exemplar C — User Control

A remembered early User Control screen combined a large editorial page title, a
quiet descriptive subtitle, strong active tab/navigation state, a dense
operational table, compact role/status treatments, many visible actions, and a
broad GPU credit reset region with a strong red action.

This screen matters because it did not treat “elegance” as “remove operational
density”. The page was still obviously a working admin tool.

### Preserve why

Keep real comparison density, direct operator action, clear consequences, and
enough page identity to avoid anonymous admin-console styling. The strong GPU
reset action is also evidence that a product can contain a small authored
cultural trace without becoming unserious — now governed by the exception
standard in [Frontend Design Language](frontend-design-language.md) §16 and its
rationale test in [Frontend Taste Review](frontend-taste-review.md) §13.

---

## 7. The architecture/style distinction

The recent frontend modernization removed or replaced much of the old markup and
CSS. That should be read as **the architecture changed**, not **the early visual
character was rejected**.

When a historical design decision is reconsidered, evaluate it on current merits:
do not preserve something only because it is old, and do not remove something
only because it now looks like an overused trend.

---

## 8. PR #54 and Soft Precision

PR #54 established the current durable visual system:

**`design(frontend): establish Soft Precision visual system`**

<https://github.com/YaoYinYing/REvoCompute/pull/54>

Soft Precision added a much stronger architecture for the global shell and
navigation, i18n, system notices, guided learning, Dashboard search/filter/view
behavior, cross-page visual roles, and responsive/accessibility verification.
Its rules are the content of
[Frontend Design Language](frontend-design-language.md).

This page does not ask future work to revert PR #54. The intended relationship
is a lineage, not a destination:

```text
early REvoDesign visual character
        ↓   identify durable judgments
Soft Precision architecture and behavior
        ↓
Cared-for Precision refinement
        ↓
future REvoCompute
```

The historical UI is a source, not a destination.

---

## 9. What should not return merely because it existed

Historical evidence is not immunity from critique. Potentially weak or
context-dependent historical patterns include nested metadata boxes where aligned
text would be clearer, excessive pills/badges, large-radius use without role
distinction, card framing around content that no longer needs isolation, shadows
used only to advertise polish, old responsive assumptions, old accessibility
limitations, and direct template coupling.

The instruction is not “restore the old page”. It is **preserve successful
judgment while using the current architecture and current usability standards**
(the anti-pattern checklist is owned by
[Frontend Design Language](frontend-design-language.md) §25).

---

## 10. Visual archaeology method

When an existing screen feels wrong but the desired correction is unclear:

1. inspect the current rendered page;
2. identify the exact discomfort (composition, density, colour, typography,
   material quality, hierarchy, interaction);
3. inspect the historical equivalent if one exists;
4. identify what the historical version did differently;
5. state the useful principle without referencing implementation;
6. reimplement that principle in the current system;
7. compare rendered before/after;
8. keep the change only if it improves current use.

Do not copy old CSS before completing step 5.

---

## 11. Historical reference is allowed to contradict current fashion

A historical REvoCompute choice may use a form that later became overused —
cards, pill labels, coloured rails, soft shadows, rounded surfaces. That does not
automatically invalidate it. A design form can be aesthetically fatigued,
culturally overused, and still functionally correct.

Future review should separate personal fatigue from actual design failure — the
convention/cliché/misuse discipline owned by
[Frontend Taste Review](frontend-taste-review.md) §12. This matters especially
for agent-driven frontend work, where “avoid generic AI UI” can accidentally
become another rigid formula.

---

## 12. What should remain recognizably ours

The precise details may evolve, but the following lineage is worth protecting:

- scientific content receives visual authority;
- neutral fields have some environmental warmth;
- surfaces feel substantial enough for daily work;
- colour is concentrated rather than sprayed;
- machine facts are exact and visible;
- dense expert workflows are not diluted for screenshot cleanliness;
- useful conventional patterns are allowed;
- page-specific composition is allowed;
- small authored exceptions are allowed;
- the UI feels maintained by people rather than generated by a template.

That is the visual ancestry future changes should inherit. Each line above is the
evidence for a rule in
[Frontend Design Language](frontend-design-language.md), not a replacement for
it.
