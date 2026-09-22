# Levin Design Structure-View Notes

Status: bounded inspection spike (TODO Phase 15, item 46), reread. Findings only;
this note proposes no production change by its existence — the closing section is
a recommendation and is labelled as one. No proprietary code, asset, or bundle
text is reproduced here; only names, vocabulary, API call order, storage keys,
and interaction behaviour are recorded, and nothing here should be reproduced as
a design clone.

## What was inspected

`Levin-Harness-2.921.0-arm64.zip` (Levin Harness 2.921.0, bundle id
`com.levin.agent`, macOS arm64) unpacked on this Linux x64 host. It cannot be
launched here, so the findings below come from the unpacked bundle:
`Contents/Resources/app.asar` unpacked read-only into `asar/dist`, with the
harness's own renderer chunks (`assets/index-*.js`, `assets/MolstarWindowApp-*.js`,
`assets/MolstarContextMenuWindow-*.js`) and the bundled Mol* viewer chunk
(`molstar-viewer.js`) read directly, plus the bundled agreement documents and
`Info.plist`. Every claim marked **observed** was grepped in those files. Claims
marked **inferred** come from the public Mol* API surface (the npm typings and
build for the exact version identified below), which is what makes them worth
recording; none of them was executed.

License: the bundle carries a proprietary Terms of Service
(`Contents/Resources/agreement/docs/terms.html`, v1.0). It grants a
non-commercial use license, forbids modification/redistribution, and reserves all
rights in the application, its code, and its interface design, including the
brand elements. It contains no clause prohibiting inspection of an installed
copy, and nothing here is copied — but the restriction on interface and code
rights is why this note records only vocabulary and behaviour.

## It is a Mol* application, running the same Mol* release we pin

**Observed.** The bundled viewer chunk is byte-identical to the published
`molstar@5.11.0` viewer build: `molstar-viewer.js` and
`https://cdn.jsdelivr.net/npm/molstar@5.11.0/build/viewer/molstar.js` have the
same SHA-256 (`7fad5561…e84f1f3`), and its SRI `sha384-5Mfx4eL50NkWPky…` is the
same hash `revocompute/static/js/viewer-shell.js` pins. So REvoCompute and Levin
are running the *same* Mol* release, and Levin's pinned copy is sitting in a
recently shipped harness.

**Observed.** Levin also ships its own Mol*-derived module
(`assets/molstar-CdjskMsm.js`, including a CIF/mmCIF reader) rather than calling
the viewer build. That is why other renderer chunks can reach Mol* builder and
manager APIs at all; the `molstar.Viewer` bundle REvoCompute loads does not
export them.

**Observed.** `managers.structure.component.addRepresentation`,
`removeRepresentations`, `currentComponentGroups`, and
`updateRepresentationsTheme` do not appear anywhere in the harness's own chunks.
The one builder/manager entry point in them is a single call at load:

```
builders.structure.hierarchy.applyPreset(trajectory, "default",
  { representationPreset: "empty", structure: ... })
```

The combination of the pinned build and the exact call order matters for
question 2 below, and for the recommendation section. `applyPreset` is handed
the trajectory and `"empty"` as the representation preset: model, structure, and
properties are built with no representation at load time, and the user's
representation choice arrives afterwards. Three build-level facts follow from
the same pinned artifact and are used throughout:

- `managers.structure.hierarchy.applyPreset` takes *trajectories*; its body
  reads `t.models.length` for each entry before doing any work, so a
  `StructureRef` (which has no `models` field in 5.11; the trajectory sits one
  level up at `model.trajectory`) throws before a provider runs.
- `managers.structure.hierarchy.remove` deletes the `cell` children of each ref
  it is given.
- `managers.structure.hierarchy.current` carries the hierarchy *refs*
  (`structures`, `components`, `representations`) and the flat
  `currentComponentGroups`, not the representation callables, which live on the
  sibling `managers.structure.component` manager.

Everything in this group is read from the pinned build and the published
typings, not from a running Levin; the note says so at each use.

Other load-path observations: the structure pipeline can materialise an
assembly and convert to mmCIF as preprocessing (`wasMaterialized`,
`wasConvertedToCif`), and the master-viewer import path uses Mol*'s MVS
extension with a custom 4-file loader — so the harness has general capture and
state-setup primitives REvoCompute does not.

## The axes of user control, and what a "preset" actually is

**Observed.** Four separate axes, each with its own registry or store, not one
list of named end states:

1. **Representation types** (10, shown with descriptions): Cartoon,
   Ball-and-Stick, Molecular Surface, Gaussian Surface, Spacefill, Point, Line,
   Backbone, Putty, Carbohydrate. These are Mol* representation identifiers.
2. **Style presets / templates** (7, each a named bundle):
   Research (default), Cinematic, Cartoon, X-Ray, Craft, Origami, Metal.
3. **Color themes** (11, shown with short labels: Element, Chain, SS, pLDDT,
   B-factor, Hydro, Charge, Rainbow, ASA, Mol, Custom).
4. **Structure-level presets**: Mol*'s built-in hierarchy presets
   (`polymer-and-ligand`, `empty`, and the rest of the registry), used when
   loading a structure.

**Observed — the decisive detail for the preset question.** A style template is
*not* a look-only bundle. Each template carries the representation axis too: its
object contains `backboneReprType`, `sidechainReprType`, `carbohydrateReprType`,
and `focusSidechainReprType` alongside its visual block, and one template's own
description says "all 8 repr types". So a template is a saved bundle spanning
*all* axes: representation types, per-type parameters, lighting, and material.

**Observed — the state model.** Visual settings are a single plain store (a
Zustand store; the plain object behind it is its own `getSnapshot`), persisted
as JSON in `localStorage` under `levin-molstar-visual-settings`, with a
`settingsVersion` field for migrations. User-saved presets are a separate list
under `levin-molstar-user-style-presets`, each saved item storing
`{ id, label, desc, reprParams, visual }` where `visual` is the whole settings
snapshot minus `reprParams`. The panel's global-defaults group exposes the
cross-structure defaults as named controls: Default Color Theme, Backbone
("Required — always shown"), Sidechain ("Optional — Ball & Stick / Line /
None"), Carbohydrate ("SNFG sugar symbols for saccharides"), Focus Sidechain,
and the rendering group. Because user presets carry the same
`reprParams`/`visual` shape as the built-ins, a saved preset can change
representation types; Levin applies it *without* resetting representations only
for the style-only case, and the built-in-template candidate is passed with
`{ resetRepresentations: false }`.

**Observed — style-panel tabs.** Display, Geometry, Shading, Material, Bonds,
Atoms, Cartoon, Surface, with a parameter group per representation type. Only
cartoon, backbone, carbohydrate, line, point, putty, and spacefill have an entry
in the global per-type parameter schema; the other representation types in
Mol*'s registry have no user-editable parameters.

**Observed — vocabulary.** The color list is flat: pLDDT and B-factor are
separate entries in the same dropdown as Element and Chain, with no confidence
gating visible in the list. Theme labels are translated to short names
("Rainbow" for `sequence-id`, "Mol" for `molecule-type`, "Hydro" for
`hydrophobicity`, "Charge" for `surface-charge`, "ASA" for
`accessible-surface-area`, "Custom" for `custom-palette`) — user-facing
vocabulary is a relabelled projection of Mol*'s registry. One structure-scoped
color setting (`defaultColorTheme`) is the whole color state model; the
per-residue pLDDT legend and the per-element "carbon" / custom-color picker are
themes in the same registry, not a separate axis.

**Inferred.** The style axis is mostly lighting, material, and shading
(metalness, roughness, emissive, outlines, bloom, fog, lights). That is inferred
from the parameter names a template sets and the descriptions shown next to each
name, not from launching the app.

## Per-component representation: a global table, not per-structure state

**Observed — the table is built as a literal list each time it is applied**, and
its rows read the *global* settings store. Defaults for the repo default
configuration:

| Component | Representation | Source | Notes |
| --- | --- | --- | --- |
| Polymer backbone | Cartoon | user setting (`backboneReprType`) | required, always shown |
| Polymer sidechain | none | user setting (`sidechainReprType`) | expression-selected "sidechain with trace" component |
| Ligand | Ball-and-Stick | fixed | |
| Non-standard polymer | Ball-and-Stick | fixed | |
| Water | Ball-and-Stick | fixed | alpha ~0.5, hydrogens ignored |
| Ion | Ball-and-Stick | fixed | size reduced |
| Lipid | Ball-and-Stick | fixed | alpha ~0.6 |
| Carbohydrate detail | Ball-and-Stick | fixed | very low alpha |
| Carbohydrate | Carbohydrate | user setting (`carbohydrateReprType`) | 3D-SNFG symbols; row only when the setting is not none |
| Coarse | Spacefill | fixed | |

Rows are addressed by Mol*'s own static component names (`polymer`, `ligand`,
`non-standard`, `water`, `ion`, `lipid`, `branched`, `coarse`), so there is no
component-addressing scheme of Levin's own to learn: the sitting entries *are*
Mol*'s component types, with per-row parameter overrides and per-row labels.

**Observed.** Only the backbone, sidechain, and carbohydrate rows are editable
by the user; the rest have a fixed representation and differ only in alpha,
size, and hydrogen handling. Water, ion, and lipid are therefore *always
offered* on a complex rather than being asked for.

**Observed — scope.** Because every row reads the global store, the table is one
global setting projected onto each loaded structure; changing the backbone
representation is a global change applied to every loaded structure, not a
per-structure datum. There is no per-structure the component table.

**Inferred.** The steady-state of a loaded structure is this table rather than
one named combination; Mol*'s structure presets (`polymer-and-ligand` and
friends) are the load-time composition path.

## What a change does to camera, representations, and selection

Answers to the three sub-questions, each from observed call sites.

**(a) Camera — untouched.** Camera reset lives on the *load* path only: the
reload callback resets with `durationMs: 0` for the first structure and the
focus-duration setting otherwise,
and the hierarchy `applyPreset` involved in loading clears the model subtree.
Style-preset application never calls `Camera.Reset`; it only pushes the
focus/reset *duration* onto `canvas3d.props.cameraResetDurationMs` when that one
setting changed, so the user's viewpoint survives every style change. Focus and
click-recenter are separate paths (`focusLoci`, `focusSpheres`, a click-focus
toggle) and are not part of preset application. **Inferred:** a viewpoint reset
can be explicit (the reset camera action, or a new structure) but cannot be a
side effect of a preset.

**(b) Representations — replacement and styling are different operations, and
only one of them keeps the theme.** In the pinned 5.11 build the one-call
hierarchy preset deletes the refs it was given and rebuilds the hierarchy from
the decoded data inside a single data transaction; a representation provider
wanting to keep part of the old hierarchy would find it gone. The representation
builder's `addRepresentation` is additive (a new sibling representation; nothing
removed) and supplies fresh per-type defaults; `removeRepresentations` is the
explicit delete. Style application is the restyle that preserves existing
representations: it merges exactly the `typeParams` keys the schema declares and
walks existing representation cells updating in place by representation type,
keyed by tags.

The consequence for "apply a preset without losing the color theme": a color
theme is an attribute of the representation cell, so any preset that removes and
re-adds representations cannot keep it — the old cell is deleted and the new one
gets Mol*'s default theme. A preset that only *updates* existing representation
cells for the same component tags keeps it, and a new representation type needs
the theme re-applied afterwards. The committed `applyStructurePreset` does
neither: it captures the component list once, then calls the two representation
methods that do not exist on the object it took them from (see the
recommendation section), so no representation is replaced at all.

**(c) Selection — untouched.** Nothing in the style path touches
`managers.structure.selection` or the selection entries; the selection-mode
toggle is a separate viewer property and selection is a separate store. Focus
clearing is not a style operation; it belongs to the representation-reset path.

**Undo.** The harness's Mol* work goes through manager methods that commit with
`canUndo: 'Preset' | 'Remove' | 'Add Representation' | 'Update Theme'`, so a
preset change is undoable. REvoCompute's preset path commits with
`canUndo: "Preset"` but nothing in the page consumes Mol*'s undo history, so the
user-visible stream of undo entries is not used there — the *mechanism* for
undo is the same, and that is the finding.

**Preset application is transactional per operation, not per axis.** Observed:
style application is a handful of separate store writes plus a background
sync loop, and Mol* work is wrapped in one `dataTransaction` per manager call —
each mutation is undoable on its own, and nothing snapshots the axes together.
**Inferred:** Levin therefore has no atomic "apply this whole presentation"
transaction, which is why user presets are re-applied axis by axis.

## Divergences, and which side is right

**1. Confidence coloring. Keep the declaration.** Observed: confidence is
Mol*'s `plddt-confidence` theme; the applicability test, description, and legend
are Mol*'s own, and Levin adds an explicit fallback path — when no pLDDT metric
is available for a residue it uses the structure's B-factor column and labels the
readout "B-factor fallback", and it refuses to do that for structures it
identifies as experimental. It also normalises 0–1 scores to 0–100. That is
*inference*, and it is the failure mode REvoCompute's `confidence_encoding:
plddt_bfactor` declaration exists to prevent — a crystal structure's B-factors
are not a confidence score, and the fallback would offer pLDDT coloring on one.
The declaration is the better contract; nothing here argues for relaxing it. The
capability is not the issue either way: the pinned Mol* 5.11.0 build already
declares the `uncertainty` and `plddt-confidence` themes, so keeping the
declaration costs nothing in theme availability.

**2. Scope of the representation choice.** Levin's per-component representation
is a global default applied to every loaded structure; REvoCompute's is
per-structure within an artifact's viewer. A global default is right for a
modelling workbench where the user has a stable way of working. A result viewer
shows one artifact at a time and must render each as its Runner declared it; the
per-structure scope is the correct one, and copying the global scope would make a
preset on one artifact silently change all others.

**3. Aggregate color modes.** REvoCompute also has "show me this structure by
chain / rainbow, and offer confidence only when the artifact declares it".
Observed: Levin does *not* add such modes — one scope-based theme switcher, and
the theme composition is Mol*'s own. So on the color axis REvoCompute is a
deliberate superset, and that superset is the part users exercise; the Levin
comparison neither supports nor opposes it.

**4. Everything else is Mol* registry vocabulary on both sides.** The
representation names, theme names, and structure-preset names are Mol*'s, so
there is no separate design language to reconcile.

## Interaction behaviours worth recording

- **Focus-as-dimming** for multi-structure sessions, with picking suppressed on
  dimmed structures.
- **User presets are local and named**, capturing representation-plus-parameter
  bundles, and re-apply the built-in template candidate without resetting
  representations.
- **The structure list is the dashboard.** Per-structure rows carry visibility,
  per-component representation, tag layer, color theme, measurement counts, and
  selection summaries, with structure and selection actions; it is not a
  separate settings dialog. There is one global "Default Color Theme" rather
  than a theme per row.
- **Selection representation is a separate record from the structure
  representation**, tracked as partial coverage ("*n*/*m* residues shown"), and
  a selection-level representation adds to or removes from the whole-structure
  one.
- **"Reset states"** clears tags and measurements and resets representations for
  the target — one action that has no equivalent in REvoCompute.
- **The sequence strip is a peer tab**, and selection in the strip and in the
  canvas share one selection store; a structure can be pushed into the strip.

## What REvoCompute should do with this

Recommendations, each tied to the observation behind it. One mechanism is
confirmed by direct evidence; one axis needs no change; the rest is an extension
and a rejection list. This section is a recommendation, not a finding — the
note's status line still holds.

### The reported failure: the representation preset cannot apply

**Observed in the committed code.** `viewer-shell.js` (HEAD) applies a
representation preset as a single transaction containing
`managers.structure.component.removeRepresentations(components)` followed by
`managers.structure.component.addRepresentation(components, { type: name })`.
Three properties of the pinned build make that sequence a no-op:

1. Those two methods live on `managers.structure.component`, while
   `currentComponentGroups` is read off
   `managers.structure.hierarchy.current` — a plain `StructureComponentRef[][]`
   in 5.11, with no methods on it. So the first call throws `TypeError` rather
   than doing anything. It sits inside the transaction's `try`, and the returned
   promise is caught, so nothing surfaces.
2. Even with a working receiver, the manager overload of `addRepresentation`
   only ever passes the string to `registry.get(type)`, which returns a
   placeholder provider instead of throwing; the overload that accepts
   `{ type }` belongs to the builders API, not the manager.
3. `hierarchy.remove` deletes the `StructureComponent` transform for each
   removed representation, so the `components` array captured *before* the
   transaction is stale by the time it is reused.

**Inferred (a self-check on the extracted control flow, not a live run).** The
first two points mean the non-composed presets cannot apply on the pinned build:
Sticks, Surface, and Cartoon all run `component.addRepresentation`, and the
transaction body throws before reaching the add. That is the mechanism behind
"the buttons do nothing" rather than "the buttons render wrongly", and it fits
the passing browser tests, which assert only the `aria-pressed` state the page
computes from its own variable, never that the canvas changed — a decision the
module's own comment records.

The composed preset takes the other path and is affected by the `models`
mismatch in the same way: `hierarchy.applyPreset` reads `t.models.length` before
its provider runs, and its `catch` swallows the rejection. So on the pinned
build all four representation presets fail closed; the color presets, which
never reach this function for Mol*, are unaffected.

**Adopt: replace the representation layer through an API that exists on the
pinned build, then re-apply the color.** A preset is a representation change, so
it belongs on the representation path the build actually supports. Concretely:
keep the current transaction boundary and the guarantee that a failed preset
never turns a successful load into a reported error, but use the builder or
hierarchy call that the harness also uses for representation work rather than the
component manager's, and re-apply the current color theme in a *second*,
separate transaction. The ordering matters: applying the theme inside the same
transaction as a replacement hands it to cells the replacement then deletes, so
the theme is lost. The shell already re-applies the color after a representation
change; that part is correct and is the piece to keep.

**Adopt: never address representations through
`managers.structure.hierarchy.current.structures` on the pinned build.** In
5.11 those entries are `StructureRef`s without a `models` field, while both
`hierarchy.applyPreset` and `hierarchy.remove` read `ref.models` before doing
anything. That is the same class of mismatch as the component-manager one, and
it is the natural next mistake when moving a preset onto the hierarchy path. The
representation builder's cell-level call and the explicit cell-level delete are
the two shapes that work; the shell's existing pattern of re-reading
`currentComponentGroups` after a removal is the right instinct and should carry
over.

**Adopt: surface a preset that did not apply.** Every failure on this path is
currently swallowed by design ("presentation is not data"), and a preset that
silently does nothing is precisely the reported symptom. The shell already
distinguishes the requested representation from `presentation.applied`; that
distinction is what makes a report possible.

### The axis that needs no change

**Adopt: keep the two-axis split, and keep the color axis untouched by a
representation preset.** Our toolbar separates what the model is drawn as from
how it is shaded. Observed: Levin's split is the same split (representation type
versus theme versus lighting/material), with more options on each axis. The
committed shell already re-applies the color after a representation change and
tracks the requested color separately precisely because a swap resets it — the
correct design. **Nothing needs to change** on this axis; that is direct
evidence, not an inference.

### Extensions and rejections

**Adopt only if a task calls for it: extra representation types.** Backbone,
Putty, Line, and Point are one-line additions to the vocabulary when a structure
view genuinely needs them, because they are the same registry strings. Observed:
each is Mol*'s registry identifier and each already exists in the pinned build.
The current seven-name vocabulary covers the same axis, so this is an extension,
not a correction.

**Defer: the preset bar mixes two axes in one control group.** Observed in the
committed `task-results.js`: the preset bar offers representation presets
(Cartoon, Cartoon + ligand, Sticks, Surface) and color presets (Chain, Rainbow,
Confidence) as sibling buttons in one `role=group`, and clicking a representation
preset *preserves* the current color while clicking a color preset changes it.
Levin keeps the same two axes but gives them separate controls. This is the
identified gap between "preset design" and "what Levin does", it is real, and it
is not the reported failure — the buttons that do nothing are the three
non-composed representation presets, every one of which is a
`component.addRepresentation` call. Treat the control-model split as a follow-up
after the mechanism is fixed.

**Reject: the per-component representation table and per-component visibility.**
It is a materially richer model, and it is the one thing here REvoCompute cannot
do — observed: a component-addressing layer in the shell that assigns component
tags and rebuilds a component table per loaded structure, which does not exist
on our side. The trigger to revisit it is a confirmed need (users asking to see a
ligand in ball-and-stick while the protein stays cartoon, with a surface on the
binding site); until then the cost is a new state surface and a new UI for an
unasked-for requirement.

**Reject: confidence auto-detection and B-factor fallback**, for the reason in
the divergence above. The declaration stays.

**Reject: style templates (lighting, material, shading bundles) and
locally-saved user presets.** Observed: style templates span all axes, so
applying one *would* reset the color theme and the representation types, and the
saved-preset store exists to persist that whole bundle in `localStorage`. Our
single-workspace viewer has no per-user style store to hang it on.

**The trap to name explicitly.** "Apply the whole bundle, like Levin does" is the
tempting response to a preset that does not visibly work, and it is the wrong
one. Levin's templates change the representation type, so applying a template
resets both the theme and the representation; a template chip whose label sounds
like a look would silently re-declare what the structure is drawn as. The
faithful copy is a larger change that makes the stated requirement worse. The
property to copy from Levin is the *mechanism* (the one call that works on the
pinned build, and the theme re-applied after it), not the bundle.
