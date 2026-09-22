# Levin Design Structure-View Notes

Status: bounded inspection spike (TODO Phase 15, item 46). Findings only — no
production change is proposed by the existence of this note. No proprietary
code, asset, or bundle text is reproduced here; only names, vocabulary, and
interaction ideas are recorded.

## What was inspected

`Levin-Harness-2.921.0-arm64.zip` (Levin Harness 2.921.0, bundle id
`com.levin.agent`, macOS arm64) downloaded and unpacked on this Linux x64 host.
It cannot be launched here, so the findings below come from static inspection of
the unpacked `.app` bundle: the Electron `app.asar` (unpacked read-only; the
relevant renderer chunks and the Mol* vendor chunk were read directly), the
bundled agreement documents, and `Info.plist`.

License: the bundle carries a proprietary Terms of Service
(`Contents/Resources/agreement/docs/terms.html`, v1.0). It grants a
non-commercial use license, forbids modification/redistribution, and reserves
all rights in the application, its code, and its interface design, including the
brand elements. It contains no clause prohibiting inspection of an installed
copy, and nothing here is copied — but the restriction on interface and code
rights is why this note records only vocabulary and behaviour, and why nothing
below should be reproduced as a design clone.

## Observed: it is a Mol* application

Levin ships Mol* as a vendor chunk and drives it through the public plugin
managers. The renderer chunk imports the Mol* surface and calls
`builders.structure.hierarchy.applyPreset(...)`, `addRepresentation`,
`hierarchy.current.structures`, `hierarchy.currentComponentGroups`,
`updateRepresentationsTheme`, `managers.structure.focus`, and
`Camera.Reset`. Its representation and color-theme vocabulary is Mol*'s
registry vocabulary: representation types (`cartoon`, `ball-and-stick`,
`molecular-surface`, `spacefill`, `point`, `line`, `backbone`, `putty`,
`carbohydrate`), color themes (`element-symbol`, `chain-id`,
`secondary-structure`, `plddt-confidence`, `uncertainty`, `hydrophobicity`,
`surface-charge`, `sequence-id`, `accessible-surface-area`, `molecule-type`,
`custom-palette`), and Mol*'s built-in structure preset
`preset-structure-representation-polymer-and-ligand`.

This is the most useful single fact for REvoCompute: the pinned Mol* 5.11.0
build we already use declares the same identifiers. Vocabulary that Levin
exposes to users is a thin, differently-labelled projection of Mol*'s own
registry, not a parallel abstraction.

## Preset vocabulary

Three distinct axes, not one list. Observed as three separate registries:

1. **Representation types** (10, shown with descriptions): Cartoon,
   Ball-and-Stick, Molecular Surface, Gaussian Surface, Spacefill, Point, Line,
   Backbone, Putty, Carbohydrate. These are Mol* representation identifiers.
2. **Style presets** (7, each a named bundle of visual + representation
   parameters): Research (default), Cinematic, Cartoon, X-Ray, Craft, Origami,
   Metal. A style preset is a *look*, not a structure composition.
3. **Color themes** (11, shown with short labels such as Element, Chain, SS,
   pLDDT, B-fact, Hydro, Charge, Rainbow, ASA, Mol, Custom).

There is also a fourth, structure-level axis: Mol*'s built-in structure presets
(`polymer-and-ligand`, `empty`, and the rest of the registry), used when loading
a structure before a style is applied.

Users can save the current combination as a named user preset, stored locally.
So Levin's effective preset space is the product of style x color x per-component
representation type, exposed through a style picker plus per-component
representation and theme pickers — not a flat list of named end states.

**Observed vs inferred.** The three registries, their labels, and the style
preset names are directly observed in the bundle. That the "style preset" axis
is mostly lighting/material/shading (and thus is not a representation choice at
all) is inferred from the parameter names it sets (metalness, roughness,
emissive, outlines, bloom, fog, lights) and the descriptions shown next to each
name.

## Representation combinations

Each component type gets its own representation, chosen independently. Observed
per-component defaults for the repo default configuration:

| Component | Representation | Notes |
| --- | --- | --- |
| Polymer backbone | Cartoon | user-selectable; also Backbone / Putty |
| Polymer sidechain | none by default | user-selectable |
| Ligand | Ball-and-Stick | fixed |
| Non-standard polymer | Ball-and-Stick | fixed |
| Water | Ball-and-Stick | alpha ~0.5, hydrogens ignored |
| Ion | Ball-and-Stick | alpha/size reduced |
| Lipid | Ball-and-Stick | alpha ~0.6 |
| Carbohydrate detail | Ball-and-Stick | low alpha, plus a 3D-SNFG symbol layer |
| Coarse-grained | Spacefill | |

Observed: per-component representation type is a first-class user setting
("Polymer backbone", "Polymer sidechain", "Carbohydrate"), while the
small-molecule/water/ion/lipid rows are fixed. Water, ion, and lipid are
*always offered* on a complex rather than being something the user asks for.

**Inferred:** the alternative — a single named combination such as
"cartoon + ligand" — exists too, but as Mol*'s structure preset, used at load
time; the app's steady state is the per-component table above.

## Color modes and confidence

Observed: the color theme list is flat and does not distinguish "elemental" from
"annotation" from "per-residue" themes. pLDDT and B-factor are separate themes
with separate labels, and there is no confidence-specific gating visible in the
UI list — both entries sit in the same dropdown as Element and Chain.

Observed: confidence coloring is Mol*'s own `plddt-confidence` theme; the theme's
applicability test, description text, and legend are Mol*'s. Levin adds an
explicit fallback path around it: when no pLDDT metric is available for a
residue, it will use the structure's B-factor column and label the readout
"B-factor fallback", and it refuses to do so for structures it identifies as
experimental. It also normalises scores to the 0–100 range when the source range
appears to be 0–1.

Observed: the app-level Molecule Type theme (protein / nucleic / ligand / water)
exists and is used to drive per-component coloring.

**This is the one substantive divergence from REvoCompute.** REvoCompute gates
confidence on an explicit `confidence_encoding: plddt_bfactor` declaration in the
owning runner's `task.yaml`, and never infers it from a `.cif` extension. Levin
takes the opposite approach: it probes the structure for a pLDDT metric, falls
back to B-factors under a stated condition, and exposes the theme whenever the
probe succeeds. That is *inference*, and it is exactly the failure mode
REvoCompute's declaration exists to prevent — a crystal structure's B-factors
are not a confidence score, and Levin's fallback would offer pLDDT coloring on
one. The declaration is the better contract; nothing here argues for relaxing
it.

## Camera and focus behavior

Observed:

- On structure load, the camera is explicitly reset (with a duration, zero for
  the first structure so the initial frame is instant).
- Changing a style preset, or changing focus-related visual settings, does
  **not** reset the camera. The camera transition duration is a single named
  setting reused by every focus/reset path.
- A single explicit per-structure focus toggle exists in the structure list:
  focusing one structure dims the others to a configured opacity, and picking
  disabled structures is suppressed while a focus is active. Focus is a
  per-structure state, not a per-session mode, and it is the mechanism by which
  a multi-structure session stays readable.
- Selection/click can recenter the camera, controlled by one toggle.
- Assembly handling is preprocessing, not viewer-side: if the file declares a
  non-identity assembly, the app materialises the assembly into new chains
  before handing anything to Mol*, and reports whether it did so. Symmetry is
  not a viewer toggle.
- Focus on a selection expands the framing radius by a fixed extra margin so
  the focused thing is not flush against the viewport edge.

**Inferred:** because the camera reset is bound to the structure-load path and
not to the style path, the user's viewpoint survives every preset change. This
matches REvoCompute's existing behavior (preset application calls only
representation/theme APIs), so it is confirmation rather than a gap.

## Interaction ideas

- **Per-component visibility and representation are rows in one structures
  dashboard**, alongside measurements, tags, and selection summaries — not a
  separate settings dialog.
- **Focus-as-dimming** for multi-structure sessions, with pick suppression on
  dimmed structures.
- **Sequence strip is a peer tab**, not a modal: the panel switches between a
  sequence view and an alignment view, and the structure list can push a
  structure into the sequence panel. Selection in the strip and selection in the
  canvas share one selection store.
- **User presets are local and named**, capturing the full style + representation
  parameter set; the built-in list stays short.

## What this suggests for REvoCompute

Three ideas, in descending order of confidence. The first two are small; the
third is not and is recorded as an explicit "do not do this yet".

1. **Nothing about the preset vocabulary needs to change.** Levin's user-facing
   representation vocabulary (Cartoon, Ball-and-Stick, Molecular Surface,
   Spacefill, Point, Line, Backbone, Putty, Carbohydrate) is Mol*'s registry
   list with labels; REvoCompute's seven-name vocabulary is a deliberate,
   smaller projection of the same registry and covers the same representation
   types plus two color modes. Levin offers more, but it offers them as a
   general-purpose modeling workbench; a result viewer does not need all ten.
   No additions are recommended.

2. **The two-axis split (what it is drawn as vs. how it is colored) is
   independently arrived at.** Levin keeps representation type, style, and color
   theme as separate picking axes and lets the combination be saved — it does
   not ship a flat list of named end states either. REvoCompute's split is
   therefore not a simplification relative to Levin; it is the same shape with
   fewer options on each axis. Worth recording as validation, not as a change.

3. **Per-component representation is the real ceiling.** The thing Levin does
   that REvoCompute cannot is let polymer backbone, sidechain, ligand,
   carbohydrate, and solvent each take a different representation at once, with
   solvent/ion/lipid always present on a complex. That is a materially richer
   model and would require a component-addressing layer in the viewer shell that
   does not exist today. It is the one idea here with real user-visible value,
   and it is also the one that would add the most complexity to a PR judged on
   having less. **Not recommended now.** If a confirmed need appears — e.g.
   users repeatedly asking to see a ligand in ball-and-stick while the protein
   stays cartoon *and* to keep a surface on the binding site — that is the
   trigger to revisit it, and the cheapest first step would be a single extra
   "Cartoon + ligand" variant rather than a component table.

Explicitly rejected: confidence auto-detection. Levin's pLDDT-with-B-factor-
fallback is the inference REvoCompute's `confidence_encoding` declaration exists
to forbid. The declaration stays.
