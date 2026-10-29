# CAVER spatial starting-point UI — dependent package

Owner role: `owner-caver-ui`. Dependency: PR #125 (CAVER 3.0.2 runner) must land its typed
`starting_point_*` contract first; this package consumes it and must not change it. The
maintainer's directive of 2026-10-29 on #125 is the requirement of record; this file turns it
into an acceptance contract. Status: **not implemented** — this PR carries the contract and
the sequencing, not a working feature.

## Why this is separate

#125 is a runner-only PR: it converts typed named inputs into a CAVER configuration, runs the
pinned CAVER 3.0.2 JAR, and normalizes the output. It deliberately does not implement
molecule-click selection. The Campaign's original "interactive starting point" objective is
therefore **not** complete at #125's merge, and must not be reported as complete until the
click-to-Task round trip below has real browser and CAVER evidence.

## Reference (design input, not code to copy)

`YaoYinYing/caver-pymol-plugin` at `5322f22030fb9ef3f3ce25f419c2ecf511dc5816`. Read the
workflow docs and the selection code; do not vendor the PyMOL/Qt implementation and do not
substitute the fork's bundled JAR for the pinned official CAVER 3.0.2 distribution. The
plugin's code averages per-residue/atom centers for mixed selections — that is **not**
automatically a mass-weighted centroid regardless of guide wording, so define and test the
web app's actual centroid semantics against CAVER 3.0.2's own
`Residue.getCenter`/`createStartingPoint` behaviour instead of cloning a label.

## P0 acceptance contract (required for this package to be READY)

1. In the existing Create Task molecule viewer, pick an atom, a whole residue, multiple
   atoms/residues (selection centroid), or a ligand/cofactor/pocket, and allow editable manual
   XYZ **in angstroms**. Show the picked identity and a clearly visible 3D origin marker.
   Coordinates, selection highlight, numeric form and submission preview stay synchronized in
   both directions, including clear/reset and mode switches — no stale and no silently ignored
   fields.
2. Show explicitly how atom id, PDB chain, residue number, atom name, altloc and the selected
   reference frame map onto the **immutable source structure**. Reject mixed objects or frames,
   empty or ambiguous selectors, missing residues, unsupported insertion-code identities and
   unsupported alternate conformations **before** submission. Preserve the source selection,
   the centroid rule, the resolved XYZ and CAVER's actual origin and delta in provenance.
3. Model tunnel-wall chemistry intentionally: let the user inspect which protein and
   nonstandard residue types and hetero groups (HEM, FAD, ions, ligands) are included, without
   silently omitting cofactors. The plugin offers an *include* list while the Runner exposes
   typed *exclude* parameters — verify the mapping against CAVER 3.0.2 semantics instead of
   assuming they are inverses, and do not duplicate or restate the server-owned parameter
   schema in frontend code.
4. Browser acceptance on the real application: viewer click → selection/form → immutable Task
   input snapshot → validated canonical `starting_point_*` → generated CAVER config → real
   runner result. Independently check origin position and units, negative selector cases, and
   both mouse and keyboard interaction. Supply light and dark screenshots of the actual Create
   Task UI as sanitized PNGs on a PR-specific pre-release with direct asset URLs.
   The current `structure_summary` capability with `select_chains: false` / `select_residues:
   false` does not meet this requirement.

## P1 (only after P0 works, only if minimal)

Cluster/tunnel geometry overlaid on the original structure with stable
`snapshot / cluster / tunnel` ids and two-way focus between table rows and geometry; a
synchronized frame slider with previous/next/playback and cluster/tunnel filtering for bounded
multi-snapshot inputs; radius/diameter, bottleneck, length, curvature, throughput and
occupancy with correct definitions and angstrom labels; reopening persisted results without
re-running CAVER. A frame-vs-distance plot is a separate bounded follow-up, not a reason to
enlarge this package. Native XTC/TRR trajectories and arbitrary frame loading are out of scope:
the runner contract is a reference PDB plus up to 50 compatible PDB snapshots.

## Sequencing and ownership

1. Independent Advisor review of `MolecularViewer`/scene ownership and reuse **before** any
   generic framework is introduced; this package extends the existing capability plugin
   contract (`structure` with selection enabled), it does not invent a parallel viewer.
2. Implement P0 against the merged #125 contract; the runner's typed parameters remain the
   only source of user-facing parameter vocabulary.
3. Browser and live acceptance as in P0.4, then the normal three-round review and Campaign
   Acceptance Audit under the protocol version in force at launch.

## Known constraints carried from #125

- The runner reports CAVER's own origin and refuses a selection that disagrees beyond
  0.05 angstrom, so the UI's resolved point must equal CAVER's; that check is the backstop,
  not a substitute for correct client-side resolution.
- Only a reference structure plus bounded compatible snapshots are supported.
- `vecmath.jar` redistribution remains a maintainer/legal decision and does not gate this UI.
