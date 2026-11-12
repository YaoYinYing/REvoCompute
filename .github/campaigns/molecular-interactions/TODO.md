# PR-2 — TODO

- [x] Inventory MolecularViewer, result viewer-contract/controller, input structure inspector, selection adapters and disposal behavior.
- [x] Establish typed atom/residue identity, topology revision, Angstrom coordinate frame, event origin and no-echo synchronization.
- [x] Implement crosshair get/set and initialization, selected centroid/true COM, axis-aligned box with validated lengths.
- [x] Add normal/expand/maximize shared-canvas controls without rebuilding the viewer.
- [x] Adapt the result integration (StructureController and both result stages) and preserve trajectory playback and the legacy residue-selection callback.
- [ ] Input integration follow-up: `frontend/src/features/create-task/**` belongs to PR #149. The existing `MolecularViewer` selection callback and re-exported `MolecularSelection`/`SelectedResidue` types keep the current `builtins.ts` working unchanged, but moving the inspector onto the typed scene adapter must be coordinated through the Commander.
- [x] Numerics, invalid identity, stale topology, event loop, focus, disposal and mobile fullscreen fallback unit tests (`tests/molecular-scene.test.ts`, `tests/display-mode.test.ts`).
- [ ] Browser end-to-end controls + 390/834/1440 light/dark screenshots and keyboard navigation proof — assigned to the independent Examiner; not run by the Owner.
- [x] Update docs and CHANGELOG.md [Unreleased].
- [ ] Independent Adviser/Examiner/Auditor on exact head; no merge/deploy without maintainer.