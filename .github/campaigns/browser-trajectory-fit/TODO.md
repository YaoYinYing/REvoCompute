# PR-6 — TODO

- [x] Wait for #152; audit Mol* existing binary trajectory loader, source immutability and frame lifecycle.
- [x] Specify atom-selection identity, reference frame, Angstrom coordinate space, uniform/mass weights, PBC warning policy.
- [x] Implement numerically robust Kabsch with det=+1, rank/NaN/atom-map checks and center-only mode.
- [x] Add reversible preview transform layer, raw reset/reselect, generation cancellation, playback and fullscreen continuity.
- [x] Implement bounded Worker pipeline with progress, memory limits and disposal.
- [x] Implement only a validated single-model PDB preview exporter with exact units/topology/sidecar metadata; no fake XTC/DCD.
- [x] Numerical reference tests (NumPy cross-check), PBC failures, source-digest invariance.
- [ ] Real Mol* browser/export re-import tests and responsive screenshots (Examiner).
- [x] CHANGELOG.md [Unreleased] and `docs/user-guide/results.md`.
- [ ] Adviser CLEAR, Examiner PASS and new independent Auditor PASS at exact head.
- [ ] No merge/tag/deploy without maintainer approval.