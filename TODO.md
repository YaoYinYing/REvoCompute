# Mol* Advanced Controls — restore working disclosure

**Status:** PLANNED / DESIGN BRANCH ONLY. **Base:** main at `14ea7441fd1aeeccb2abf37a217c1bbf42ab0e6e`.
**Scope:** `frontend/src/features/structure/MolecularViewer.ts`, `frontend/src/features/results/molecular/structure-controller.ts`, Results viewer layout/CSS/tests. Avoid broad ResultWorkspace redesign.
**Symptom:** Results Mol* wrench/tool UI cannot expand.

## Evidence
- [ ] Review `MolecularViewer.mount` `showControls`, `spec.layout.initial.showControls`, `regionState.right`, `spec.components.controls.right`, responsive CSS and structure-controller factory call. `StructureController` currently does not pass explicit `showControls: true`; distinguish intended hidden vs broken disclosure.
- [ ] Reproduce in production-built Mol* with an authentic, read-only mmCIF/PDB artifact, desktop/touch/mobile; log pointer interactions, actual panel state, clipping/overlay and console errors; do not infer root cause from a screenshot.
- [ ] Compare when used in Results, Dashboard preview and Create Task selection to avoid changing modes that deliberately hide advanced controls.

## Implementation
- [ ] Restore a discoverable, operable toggle to reveal advanced Mol* native controls on Results, with clear close path and stable geometry. Do not make Mol* dominate the scientific Result workspace.
- [ ] Choose a single control-state owner. Avoid simultaneous contradictory `showControls` and `regionState` values, React remount races, fullscreen mismatch or CSS hiding while aria says expanded.
- [ ] Preserve existing custom toolbar for representation/chain coloring/focus; keep Mol* advanced tool panels optional.
- [ ] Respect strict CSP, self-hosted Mol* (no remote UI assets), focus return, keyboard accessibility, reduced motion, fullscreen and disposal of viewer events/resources.

## Acceptance
- [ ] Playwright+real Mol* click wrench -> panel visibly opens and usable -> closes; snapshot/trace for ordinary and fullscreen states.
- [ ] Test small/narrow viewport: no offscreen inaccessible tools, no scroll trap, no action covered by status overlay.
- [ ] Verify structure, trajectory, selection and renderer lifecycle still function; relevant Mol* CSP qualification green.
- [ ] Narrow code diff and independent viewer review on exact head; remove temporary TODO and artifacts before READY. No merge.
