# Frontend Design Language

This page is the visual contract for REvoCompute's frontend: the vocabulary a
change is judged against. It records *roles*, not values — the live values are
declared once in `frontend/src/styles/app.css` under `:root` and
`:root[data-theme="dark"]`, and that file is the only place they are written.

It deliberately does not prescribe component markup. Feature stylesheets own
their own layout; this page owns the meaning of the surfaces, type, colour and
controls they are composed from.

## Thesis

**Scientific instrument × editorial laboratory.** The product should read as a
precision instrument that publishes results: quiet, warm, purposeful, slightly
tactile. Not a dashboard product, not a card wall, not a control panel.

The consequence is a hierarchy rule rather than a style preference: the
scientific artifact is the loudest thing on any page that has one, and
everything around it is deliberately quieter than it would be on its own.

## Colour roles

The palette is fixed; usage is what a change may adjust. Each token names a
*role*, and a role may only be used for that role.

| Role | Meaning |
| --- | --- |
| `--app-bg` | Application canvas. A neutral tinted field, never pure white. |
| `--app-surface` | A surface that sits on the canvas and holds content. |
| `--app-raised` | A concrete object: a control, a menu, a dialog body. |
| `--app-stage` | The scientific stage behind a viewer. Stable in both themes. |
| `--app-ink` / `--app-muted` | Primary reading text / secondary and metadata text. |
| `--app-line` / `--app-line-strong` | Hairline separator / structural boundary. |
| `--app-accent` | Identity and primary action. |
| `--app-accent-2` | Success and confirmation. |
| `--app-soft` | Selected or active fill derived from the accent. |
| `--app-warning` / `--app-danger` | Attention that needs a decision / failure. |

Semantic status colours are never used as decoration, and the accent is never
used merely to make something larger.

## Surface roles

`canvas → surface → raised → scientific stage`, plus `side-rail` and `dialog`.

A surface earns a shadow only when it is genuinely above another surface. There
are three elevation levels and no more; a fourth level means the layout is
wrong, not that the scale needs extending. Grouping is communicated by
whitespace and a hairline first, a boundary line second, and elevation only when
the thing really floats (menus, notices, dialogs).

## Typography roles

Three families with three jobs:

- **Serif** — page and scientific titles, editorial statements, and large
  metrics. This is the single strongest identity carrier.
- **Sans** — UI, body copy, forms, tables. The default.
- **Mono** — genuine machine identity only: ids, hashes, filenames, code,
  sequence and residue notation.

Font files are not self-hosted and CSP is `font-src 'self'`, so the declared
families resolve to system fallbacks. Hierarchy must therefore be carried by
scale, weight, spacing and measure rather than by a webfont — do not introduce a
font dependency as a design fix.

Avoid accenting a single word inside a title, all-caps labels, and decorative
eyebrow text above a heading. A label earns its place by carrying information.

## Radius scale

Curvature communicates role, so there is a scale rather than one value:

| Token | Applies to |
| --- | --- |
| `--r-surface-lg` | Large editorial or feature surfaces |
| `--r-surface` | Standard content surface |
| `--r-control` | Buttons, inputs, selects, icon buttons |
| `--r-util` | Small utilities, chips, inner rows |
| `--r-pill` | Status, badges, segmented indicators |

Using one radius everywhere is the failure mode this scale exists to prevent.

## Shadow scale

`--shadow-surface`, `--shadow-raised`, `--shadow-dialog`. Dark mode keeps the
same three roles at a lower alpha over darker bases. A shadow is elevation
information; it is never ambient decoration. A raised surface may also carry a
hairline border — several deliberately do — so the rule is not that the two may
never appear together, it is that they must not say the same thing twice: a
restrained elevation plus a hairline that frames content is fine, while a
pronounced shadow on a border whose only job is to restate the shadow's edge is
redundant. Decide which of the two is carrying the hierarchy and let the other
stay quiet.

## Spacing

A single rhythm (`--space-1` … `--space-6`) is applied at the page boundary,
between sections, as surface padding, between a control and its label, and as
metadata proximity. Dense instrument surfaces (dashboard, admin tables) opt
*down* the rhythm; they never opt up. Uniform `padding: 1rem` across unrelated
elements is what flattens a page, so proximity encodes relationship.

## Control hierarchy

Primary (filled accent), secondary (surface with an accent border), quiet (text
only), icon (square, util radius), danger (outlined until confirmed), segmented
(joined group with the selected segment raised), and input.

These are related, not identical. A destructive action is never a filled primary
button, and a row of equal-weight buttons is a hierarchy defect even when each
button is individually correct.

## Status hierarchy

- **Success is quiet.** A small `✓ Finished` inside the task identity. Never a
  panel, never an interrupt before the result.
- **Warning** is a compact, actionable strip — it says what to do.
- **Failure** may take over the principal result area, because it is the result.
- **Running** is the one status that may animate, and only when the animation
  carries the passing of time.

Implementation detail belongs in the files, diagnostics and execution surfaces,
not on the primary result surface.

## Scientific workspace principles

- The stage is the strongest surface after the header; the viewport is never
  shrunk for prettiness.
- Viewer controls group by meaning — representation, colour, selection, view —
  with high-frequency actions visible and low-frequency presets grouped. No
  functionality is removed to reduce clutter.
- Diagnostics live in the rail, never on the result surface.
- The file rail may group by manifest-provided artifact role. Semantic grouping
  is never inferred from path names or file extensions.
- Empty, pending and failed states are direction, not mood: say what is
  missing and what to do next.

## Writing in the interface

Interface copy is design content. Every visible sentence answers a question a
user actually has, or it is removed. Names describe what the user is managing,
not how the system is built; the same action keeps the same name from button to
confirmation. Failure text states what happened and how to proceed, without
apology or vagueness.

## Changing this vocabulary

Add a token only when a new *role* genuinely exists, not to accommodate one
component's preferred value. When a feature needs something the scale does not
offer, that is usually a signal the hierarchy is wrong. The rules in this page
and the tokens in `app.css` are the same contract; keep them in step in one
change.
