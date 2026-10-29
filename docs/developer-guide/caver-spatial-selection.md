# CAVER Spatial Starting-Point Selection Design Record

This page defines the contract for choosing a CAVER tunnel starting point by
clicking a structure in the Create Task viewer and carrying that selection
through to the runner as validated canonical parameters. It covers the P0
acceptance contract, the P1 boundary, the prerequisite sequencing, and the known
constraints; it does not implement the picker, the viewer facade, or any
acceptance criterion, and it does not restate CAVER's parameter vocabulary or
start-point resolution rules, which the owning `task.yaml` and the runner own.

Status: design record only. The picker, viewer facade, selection-identity
widening, and every acceptance criterion below remain unimplemented.

Dependency: PR #125 (CAVER 3.0.2 runner) is runner-only. It converts typed
named inputs into a CAVER configuration, runs the pinned JAR, and normalizes the
output, but it deliberately does not implement molecule-click selection. The
click-to-Task round trip below therefore remains unimplemented after #125
merges.

## Ownership split with #125

#125 owns CAVER's `parameters:` block and all runner Python. This work may edit
the same task's `input_workspace:`, add runner-owned `input_workspace_plugins`
to that family's `plugin.yaml`, and add a `workspace/` module beside the runner.
It may not edit `parameters:` or any runner Python: the typed
`starting_point_*` vocabulary and CAVER's own resolution rules stay #125's, and
the picker drives the canonical controls rather than owning their values.

## Reference (design input, not code to copy)

`YaoYinYing/caver-pymol-plugin` at
`5322f22030fb9ef3f3ce25f419c2ecf511dc5816`. Read the workflow docs and the
selection code; do not vendor the PyMOL/Qt implementation. Start-point geometry
is the runner implementation #125 owns and is the authority the UI must agree
with; the PyMOL plugin's per-residue averaging is a reference, not a definition.

## P0 acceptance contract

1. In the existing Create Task molecule viewer, pick a whole residue, several
   residues (selection centroid), or a ligand/cofactor, and allow editable
   manual XYZ **in angstroms**. Show the picked identity and a clearly visible,
   camera-tracked 3D origin marker. Coordinates, selection highlight, numeric
   form and submission preview stay synchronized in both directions, including
   clear/reset and mode switches — no stale and no silently ignored fields.

   **Manual XYZ is authoritative only in `point` mode.** In atom, residue,
   ligand and group modes #125 resolves the point itself, so the numeric form is
   a labelled preview of the runner's answer, never an input the UI substitutes.
   The UI must show it as a preview and must not present a difference as a
   submission error.

   Atom mode is explicitly out of the first increment (it needs atom identity
   from the viewer that the shared contract does not carry yet); it is P0-b
   below.
2. Show explicitly how the selected identity maps onto the immutable source
   structure, and refuse before submission what CAVER cannot address. The
   identity that must be shown and validated is: auth chain (not Mol*'s label
   chain), auth residue number, insertion code, residue name, hetero flag, and —
   for atom mode — atom name, altloc and serial. Today the workspace contract
   carries only `{chain: label_asym_id, residue: label_seq_id}`, so ligand picks
   and blank-chain structures cannot be expressed at all; widening it is
   prerequisite work, not optional. Refuse mixed structures or frames, empty or
   ambiguous selectors, missing residues, insertion-coded residues, unsupported
   altlocs, blank-chain mismatches, and multi-model reference files. Preserve the
   raw selection, the centroid rule, the resolved point and CAVER's own origin
   and delta in provenance.
3. Model tunnel-wall chemistry intentionally: render and drive the runner's typed
   exclude parameters so the user can see which protein and nonstandard residues
   and hetero groups (HEM, FAD, ions, ligands) are in play, without silently
   omitting cofactors. Do not build an inverse "include" list, do not assume
   exclude and include are interchangeable, and do not restate the server-owned
   parameter vocabulary: names, enums, units, bounds and labels come from the
   projected schema, never from frontend constants.
4. Browser acceptance on the real application: viewer pick → selection/form →
   immutable Task input snapshot → validated canonical `starting_point_*` →
   generated CAVER config → real runner result. Assert the submitted
   `params[...]` and the stored workspace payload, because the workspace payload
   is provenance only and the runner reads canonical params. Cover mouse and
   keyboard interaction, both directions of synchronization, the refusals above,
   and the origin's position and unit. Model the harness on the existing
   `tests/fleet/browser/test_playwright_rfdiffusion_workspace.py`. Supply light
   and dark screenshots of the actual Create Task UI as sanitized PNGs on a
   PR-specific pre-release with direct asset URLs.

   The delta from today: `select_chains` and `select_residues` collapse into one
   boolean, so `select_chains` is currently a no-op alias. Either implement real
   chain-granularity selection or remove the option; turning on
   `select_residues` plus the new picker capability is what this contract needs.

## P1 boundary

P1 follows only after P0 works, and only if minimal: cluster/tunnel geometry
overlaid on the original structure with stable `snapshot / cluster / tunnel` ids
and two-way focus between table rows and geometry; a synchronized frame slider
with previous/next/playback and cluster/tunnel filtering for bounded
multi-snapshot inputs; radius/diameter, bottleneck, length, curvature,
throughput and occupancy with correct definitions and angstrom labels; reopening
persisted results without re-running CAVER. A frame-vs-distance plot is a
separate bounded follow-up, not a reason to enlarge this work. Native XTC/TRR
trajectories and arbitrary frame loading are out of scope: the runner contract is
a reference PDB plus up to 50 compatible PDB snapshots. The viewer's existing
geometry path consumes a recorded-spheres format, so tunnel polylines need new
viewer plumbing — another reason P1 stays separate.

## Sequencing

1. **Core prerequisite** (its own bounded change, reviewed as a server/frontend
   boundary): complete selection identity on the workspace contract (auth chain,
   residue name, hetero flag, insertion code preserved end to end); a narrow
   viewer facade on the workspace context exposing only select/focus/annotate; a
   parameter write accessor paired with the existing parameter read, so a control
   edit re-places the marker; and resolution of the `.ent` gap — the task accepts
   `pdb` and `ent` while the viewer previews only `pdb`/`cif`/`mmcif`, so an
   accepted `.ent` silently loses the viewer. No generic framework, no second
   viewer.
2. **Picker module**: a runner-owned `input_workspace_plugins` entry with no
   backend normalizer. Submission validates parameters before capability
   normalization runs, and `start_point_mode` is required without a default, so a
   backend that injects it can never run; a picker that claims those fields
   removes them from the generic form and then fails validation. The picker
   therefore drives the canonical controls through the shared context and
   records the raw selection through its own value.
3. **P0-b**: atom mode once the viewer reports atom identity.
4. Browser and live acceptance as in P0.4.

## Known constraints from #125

- CAVER's origin is compared against the runner's resolved point within 0.05
  angstrom. That is a backstop in `point` mode and a self-check in selector
  modes; it is not a substitute for correct client-side identity mapping, and a
  preview difference is not an error.
- Only a reference structure plus bounded compatible snapshots are supported.
- `vecmath.jar` redistribution remains a maintainer/legal decision and does not
  gate this UI.
