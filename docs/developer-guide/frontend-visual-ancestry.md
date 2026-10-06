# Frontend Visual Ancestry

This page records the visual lineage that should remain visible to future
frontend work.

It is not a historical changelog and not a restoration specification.

Its purpose is to prevent architectural rewrites from being misread as aesthetic
rejections, and to give future designers/agents concrete evidence for what
REvoCompute has already considered successful.

---

## 1. Why this page exists

REvoCompute has changed architecture repeatedly.

The server moved from early Flask templates into a much more explicit frontend
system. Runner/result contracts became generic. The shell, i18n, notices,
guided-learning behavior, and browser acceptance harness were modernized in
PR #54.

Those changes were engineering decisions.

They do **not** imply that every earlier visual judgment was rejected.

A recurring failure mode in long-lived software is:

```text
architecture rewrite
→ old markup disappears
→ old visual language disappears with it
→ later developers assume the old visual language was intentionally deprecated
```

That inference is unsafe.

Use this page to distinguish:

- obsolete implementation;
- still-useful visual judgment.

---

## 2. Major ancestor: REvoDesign PR #163

The most important early ancestor is:

**REvoDesign PR #163 — `feat(server): full server stack in docker`**

<https://github.com/YaoYinYing/REvoDesign/pull/163>

Merged: 2026-02-23.

The PR was primarily a server/infrastructure rewrite, but it also contained a
substantial visual rewrite of the server-facing frontend.

Relevant historical files include:

```text
server/pssm_gremlin/templates/create_task.html
server/pssm_gremlin/templates/pssm_gremlin_dashboard.html
```

The PR was large and not structured as a modern visual-design PR.
That does not reduce its value as visual evidence.

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

It also introduced:

```text
IBM Plex Sans
Source Serif 4
```

Do not restore these values blindly.

What they prove is more important:

- the product once preferred a warm/grey-green environmental neutral over
  sterile blue-grey;
- “paper” could be almost white while still feeling different from a browser
  white canvas;
- deep teal could provide structure without becoming a generic bright-SaaS
  accent;
- an editorial type contrast could coexist with utilitarian controls.

Any current palette can differ while preserving those relationships.

---

## 4. Exemplar A — Result workspace

A remembered early Result screen placed a large molecular structure stage on
the left and a narrower Files & diagnostics surface on the right.

The valuable properties were:

- the molecular structure was visually dominant;
- surrounding UI used quiet pale surfaces;
- scientific representation colours supplied the strongest chroma;
- file inventory remained dense and usable;
- the file surface did not compete with the molecule;
- the page felt like a workbench, not a presentation slide.

### Preserve why

Do not copy the exact split ratio or old viewer chrome.

Preserve:

> **science first, chrome second**

and:

> **the interface can become visually quiet because the scientific object is
> already visually rich**

---

## 5. Exemplar B — Task Dashboard

A remembered early Dashboard used:

- substantial Task cards;
- a thin left status rail;
- status labels;
- machine-like Task IDs;
- aligned Submitted / Finished / Wall Time facts;
- compact sequence disclosure;
- direct task actions.

The status rail should be understood as **semantic peripheral encoding**, not as
a decorative brand stripe.

It allowed the eye to scan state without reading every label.

### Preserve why

Do not make “no rails” a design ideology.

Ask whether the rail:

- encodes real state;
- improves batch scanning;
- remains visually quiet;
- is confirmed by text for accessibility.

If yes, it is a legitimate tool.

---

## 6. Exemplar C — User Control

A remembered early User Control screen combined:

- a large editorial page title;
- a quiet descriptive subtitle;
- strong active tab/navigation state;
- a dense operational table;
- compact role/status treatments;
- many visible actions;
- a broad GPU credit reset region with a strong red action.

This screen matters because it did not treat “elegance” as “remove operational
density”.

The page was still obviously a working admin tool.

### Preserve why

Keep:

- real comparison density;
- direct operator action;
- clear consequences;
- enough page identity to avoid anonymous admin-console styling.

The strong GPU reset action is also evidence that a product can contain a small
authored joke or cultural trace without becoming unserious.

---

## 7. The architecture/style distinction

The recent frontend modernization removed or replaced much of the old markup and
CSS.

That should be interpreted as:

> **the architecture changed**

not:

> **the early visual character was rejected**

When a historical design decision is reconsidered, evaluate it on current
merits.

Do not preserve something only because it is old.

Do not remove something only because it looks familiar from a now-overused
design trend.

---

## 8. PR #54 and Soft Precision

PR #54 established the current durable visual system:

**`design(frontend): establish Soft Precision visual system`**

<https://github.com/YaoYinYing/REvoCompute/pull/54>

Soft Precision added a much stronger architecture for:

- global shell/navigation;
- i18n;
- system notices;
- guided learning;
- Dashboard search/filter/view behavior;
- cross-page visual roles;
- responsive/accessibility verification.

This visual-ancestry page does not ask future work to revert PR #54.

The intended relationship is:

```text
early REvoDesign visual character
        ↓
identify durable judgments
        ↓
Soft Precision architecture and behavior
        ↓
Cared-for Precision refinement
        ↓
future REvoCompute
```

The historical UI is a source, not a destination.

---

## 9. What should not return merely because it existed

Historical evidence is not immunity from critique.

Potentially weak or context-dependent historical patterns include:

- nested metadata boxes where aligned text would be clearer;
- excessive pills/badges;
- large-radius use without role distinction;
- card framing around content that no longer needs isolation;
- shadows used only to advertise polish;
- old responsive assumptions;
- old accessibility limitations;
- direct template coupling.

The instruction is not “restore the old page”.

The instruction is:

> **preserve successful judgment while using the current architecture and current
> usability standards**

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

A historical REvoCompute choice may use a form that later became overused:

- cards;
- pill labels;
- coloured rails;
- soft shadows;
- rounded surfaces.

That does not automatically invalidate it.

A design form can be:

- aesthetically fatigued;
- culturally overused;
- still functionally correct.

Future review should separate personal fatigue from actual design failure.

This is especially important for agent-driven frontend work, where “avoid
generic AI UI” can accidentally become another rigid formula.

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

That is the visual ancestry future changes should inherit.
