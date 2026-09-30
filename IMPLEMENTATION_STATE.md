# Visual Refinement Implementation State

`TODO.md` is the visual and acceptance contract. This file records execution
state; the screenshot set, the browser contracts, and the named acceptance
commands are the machine-verifiable truth.

## Starting point

- Starting branch: local `main`, matching `origin/main`.
- Starting SHA: `734f2cb0db769bab3df8bc468461d3624753b035`
  (`refactor(frontend): complete browser presentation cutover (#34)`).
- Initial worktree change: the user-provided visual-refinement replacement of
  `TODO.md` only.
- Feature branch: `feat/visual-refinement`.
- The PR32–PR34 presentation architecture is canonical and is not re-opened.

## Environment facts that constrain the work

- CSP is `font-src 'self'`: no external font may be loaded, and no font binary
  exists in the repository or its history. The declared families
  (`Source Serif 4`, `IBM Plex Sans`) therefore render as Georgia / system-ui.
  The typographic hierarchy must be carried by scale, weight, spacing, and
  measure — not by a new webfont. Recorded, not fixed: self-hosting font files
  is a separate decision with its own asset-ownership consequences.
- The 3–6px radius, one-pixel-border, and uniform-spacing problem is the
  observed cause of the "industrial console" reading, not the palette.

## Active phase

**Pass 4 — Arrived.** Passes 1–3 are committed on `feat/visual-refinement`; the
gates below are green on the committed tree. The remaining steps are the review
passes and the PR.

---

# Visual archaeology note (TODO §48)

## What the historical design did well

- A soft scientific canvas: radial/linear wash behind the page, so surfaces sat
  *on* something rather than floating in flat grey.
- Warm off-white semantic surfaces with real 18px curvature and one restrained
  shadow level (`.panel`, `0 12px 28px rgba(29,42,47,.08)`).
- A pill control language (`.btn` 999px) that read as tactile without being
  playful, and a segmented control that looked pressable rather than printed.
- Serif titles against sans UI — the single strongest identity carrier.
- The `evidence-map` figure: a real scientific motif with asymmetric curvature
  (`28px 28px 80px 28px`), grid annotation, and depth — a visual memory point
  rather than decoration.
- Generous section rhythm; sections separated by whitespace and a hairline
  rather than by a box.

## What the current design improved

- Information architecture and ownership: one inert Vite entry per route,
  feature-local CSS, genuine routing, accessible dialogs, `:focus-visible`,
  reduced-motion, dark mode as a token set rather than a filter.
- Dense, honest application surfaces: the dashboard, admin tables, and runner
  facts lists are more scannable and more truthful than the legacy pages.
- Result workspace structure: rail, collapse, fullscreen, diagnostics grouping
  are better shaped than the legacy result page.
- Copy and contracts: named input roles, readiness semantics, admin flows.

## What was lost during cutover

- Surface hierarchy. Everything became `1px solid var(--app-line)` on a flat
  field, so a scientific stage, a task card, and a toolbar all carry equal
  visual weight.
- Depth. Shadows survive only on menus, notices, and dialogs; the product has a
  single elevation level, so grouping is communicated by borders alone.
- Typographic contrast. Titles shrank (`clamp(1.65rem…2.35rem)`), and the body
  mass sits between 12px and 16px, flattening the page.
- Control warmth. 3–4px radius on buttons and inputs reads as an internal tool.
- Breathing room at the page and section boundary, replaced by uniform
  `padding: 1rem`.

## What should return

- An ambient canvas for public/editorial surfaces; a neutral, subtly tinted
  canvas for application workspaces; a stable high-contrast stage for science.
- A radius scale with meaning, not one value: semantic surface 14–18px,
  controls 8px, utility 6px, status pill 999px.
- Three shadow levels used only where they communicate elevation: surface,
  raised, dialog.
- Serif for scientific/page titles at meaningful size; sans for UI; monospace
  only for genuine machine identity (ids, hashes, filenames, code).
- One bold gesture per page. On Result that gesture is the scientific stage; on
  Home it is the scientific motif in the hero; elsewhere the page stays quiet.

## What should stay dead

- The Run Outcome panel and any success panel that interrupts the result.
- Decorative gradients behind Mol*, tables, plots, and forms.
- The card wall: many equal rounded boxes with equal shadow.
- Shadow on every card; glow; neon elevation; parallax; scroll-jacking.
- Restoring deleted Jinja templates, legacy page JS, or a global legacy sheet.

---

# Design language (TODO §49)

**Thesis.** Scientific instrument × editorial laboratory: precise, quiet,
purposeful, slightly tactile.

- **Colour roles.** Canvas neutral-mint `--app-bg`; warm off-white surface
  `--app-surface`; raised `--app-raised`; charcoal ink `--app-ink`; grey-green
  muted `--app-muted`; hairline `--app-line`; deep teal `--app-accent` (identity
  and primary action); green-teal `--app-accent-2` (success, confirmation);
  amber `--app-warning`; restrained red `--app-danger`. Palette unchanged; only
  usage changes.
- **Surface roles.** `canvas → surface → raised → scientific stage`, plus
  `side-rail`, `dialog`. A surface earns a shadow only when it is genuinely
  above another surface.
- **Typography roles.** Serif: page and scientific titles, editorial statements,
  metrics. Sans: UI, body, forms, tables. Mono: ids, hashes, filenames, code.
- **Radius scale.** `--r-surface-lg` 18px, `--r-surface` 14px, `--r-control` 8px,
  `--r-util` 6px, `--r-pill` 999px.
- **Shadow scale.** `--shadow-surface`, `--shadow-raised`, `--shadow-dialog`;
  dark mode keeps the same three roles at lower alpha over darker bases.
- **Spacing.** A single rhythm (`--space-1…6`) at page boundary, section, surface
  padding, control group, and metadata proximity. Dense instrument surfaces
  (dashboard, admin tables) opt down, they do not opt up.
- **Control hierarchy.** Primary (filled teal), secondary (surface + accent
  border), quiet (text only), icon (square util radius), danger (outlined red
  until confirmed), segmented (joined group, selected segment raised), input.
  Related, not identical.
- **Status hierarchy.** Success is quiet — a small `✓ Finished` in task
  identity, never a panel. Warning is a compact actionable strip. Failure may
  take over the principal result area.
- **Scientific workspace principles.** The stage is the strongest surface after
  the header; controls group by meaning (representation / colour / selection /
  view); diagnostics live in the rail, never on the result surface; the
  viewport is never shrunk for prettiness.

---

# Completion checklist

## Design review

- [x] `frontend-design` loaded and applied as a critique of the current
      deployment against the historical implementation.
- [x] Current deployed site captured (Home, Runner Catalog, API Docs, Login)
      at 1440×950 before any change.
- [x] Historical CSS read as evidence (pre-PR32 `base.css`, `index.css`,
      `task-results.css`).
- [x] Visual archaeology note recorded above.

## Pass 1 — Foundation (`frontend/src/styles/app.css`)

- [x] Canvas: ambient wash for public/editorial surfaces; tinted neutral for
      application workspaces.
- [x] Token vocabulary: colour roles, radius scale, shadow scale, spacing
      rhythm, type scale, font roles.
- [x] Surface language, typography, spacing, buttons, inputs, dialogs,
      header/navigation, notices.
- [x] All routes re-verified after Pass 1 for regressions.

## Pass 2 — Scientific workspaces

- [x] Result workspace presentation + success status demoted to the header.
- [x] Mol* toolbar grouping; scientific stage prominence.
- [x] Files & diagnostics rail hierarchy, grouped by manifest artifact role.
- [x] Create Task workbench and review rail as a task snapshot.
- [x] Scientific tables / plots / matrices.
- [x] Microcopy reduction (TODO §6, §47).

## Pass 3 — Utility and public surfaces

- [x] Home: hero with a scientific memory point.
- [x] Runner Catalog: scientific directory, meaningful density modes.
- [x] Dashboard: dense, instrument-like, less grid-border dependence.
- [x] Profile, Admin, Auth, API Docs, Legal.

## Verification

- [x] Before/after screenshots at consistent desktop dimensions.
- [x] Narrow/mobile viewport inspection.
- [x] Dark-mode validation across canvas, surfaces, shadows, badges, inputs,
      dialogs, plots, Mol* surroundings.
- [x] Accessibility preserved (keyboard, focus, headings, contrast, dialogs,
      tabs, reduced motion).
- [x] Typecheck + unit tests, browser contracts, strict-CSP Mol* test, backend
      tests, full-stack Compose, and `mkdocs build --strict` all pass.

## Delivery

- [x] Coherent checkpoints committed before deployment and PR.
- [ ] Redeploy with `--use-proxy`; live Runner acceptance test.
- [ ] Three independent review passes before PR; batch and fix valid findings.
- [ ] Push the branch and open the PR.
