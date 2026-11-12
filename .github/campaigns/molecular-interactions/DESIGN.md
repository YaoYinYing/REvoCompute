# PR-2 — shared molecular interaction and Mol* presentation contract

**Status:** DESIGN ONLY · Draft; baseline `21b62a2c7fd6ce4862d05cf88fbdd111ac0af6d4`. **Owner:** shared frontend molecular viewer + input/result adapters. **Downstream:** CAVER picker and browser trajectory fit.

## Existing architectural seam
`frontend/src/features/structure/MolecularViewer.ts` already owns a Mol* instance and selection lifecycle; `frontend/src/features/results/molecular/viewer-contract.ts` and `structure-controller.ts` have a narrower result adapter, with playback; Create Task input `builtins.ts` already talks to selection. **Extend these, don't add a third viewer implementation or a server-global Mol* singleton.** Existing Mol* spec intentionally disables native expand/fullscreen controls; application-level modes must own focus/state.

## One typed scene interaction vocabulary
Define an explicit `MolecularScene` *TypeScript interface/adapter*, not a global server object, with immutable `topology_revision`, `coordinate_frame`, `units = angstrom`, `selected_atoms` and `selected_residues`. Atom identity: stable source/authored chain ID, residue author number, insertion code, residue name, atom name, atom serial, alternate location/conformer, model identifier where applicable. Distinguish author and label numbering, atom serial from index, and active trajectory frame from reference topology. A selection becomes invalid if topology revision or source digest changes; report explicit errors, never silently map stale chain IDs.

Operations/events: read/subscribe selection; set/clear highlight/focus; get/set crosshair `{x,y,z}`; derive centroid from selected coordinates; derive true mass-weighted COM using explicitly available atomic masses and hydrogen policy; get/set axis-aligned box `{center: XYZ, lengths: XYZ}`; optional orientation only with a defined rotation/frame convention. Explicitly reject empty atom subsets or mass gaps for COM, nonfinite values, negative box lengths, mismatched units and ambiguous alternate locations. XYZ zero and whole-structure COM are **explicit initialization choices**, not silent defaults; do not confuse geometric center with COM. Render crosshair/box as overlays and never mutate original structure/trajectory arrays.

A single source of truth for UI/form sync: event includes origin (form/viewer), transaction ID or revision, topology digest and selected frame. Ignore self-echo; debounce/cancel stale async atom picks. Expose imperative methods on the existing MolecularViewer and a typed narrow result adapter rather than mirroring independent state machines.

## Three display modes, one viewer instance
`normal`: embedded stage; `expand`: responsive overlay/floating near-viewport stage with backdrop blur, focus trap, Escape close and focus return; `maximize`: real Fullscreen API when supported, clearly labeled fallback otherwise. **Reparent or resize the same mounted WebGL canvas/viewer** where safe; preserve camera, selection, trajectory frame, overlays and history. Never destroy/reload structure merely to change display mode. App-controlled mode state must survive form changes and dispose exactly once on route exit. Mobile Safari Fullscreen API may differ; use a tested fallback and avoid claiming native fullscreen where unavailable.

## Interfaces and ownership
Browser Presentation Plane owns Mol* lifecycle, overlays, layout, selection and async cancellation. Server only transmits stable topology identity and authorized structure bytes; no new scene-processing service or process-global browser state. Preserve structure/result views, trajectory playback, existing CAVER typed selection, local result view and accessibility. Wire type guards for runtime Mol* payload boundaries rather than `unknown` casts everywhere.

## Accessibility and validation
Keyboard-selectable mode controls, screen-reader labels for selections/coordinates, focus trap/restore, Escape, reduced motion, adequate zoom/touch hit areas, responsive 390/834/1440 width screenshots, light/dark mode. Numerical tests for Angstrom positions, finite XYZ, centroid vs COM on known-mass atoms (including hydrogen inclusion/exclusion), atom mapping with altloc/insertion codes, frame changes, stale revisions, event-echo loops and WebGL cleanup. Browser interactions must confirm same canvas/viewer identity before and after expand/maximize and no selection loss.

## Non-goals
No CAVER-specific add-on in this PR, no server-global Mol*, no trajectory Kabsch fit yet, no new file format writers and no heavyweight molecular conversion service. UI images/screenshots are acceptance evidence, not implementation. Follow up with #153/#157 after this contract merges.