# PR-6 — TODO

- [ ] Wait for #152; audit Mol* existing binary trajectory loader, source immutability and frame lifecycle.
- [ ] Specify atom-selection identity, reference frame, Angstrom coordinate space, uniform/mass weights, PBC warning policy.
- [ ] Implement numerically robust Kabsch with det=+1, rank/NaN/atom-map checks and center-only mode.
- [ ] Add reversible preview transform layer, raw reset/reselect, generation cancellation, playback and fullscreen continuity.
- [ ] Implement bounded Worker pipeline with progress, memory limits and disposal.
- [ ] Implement only validated PDB/mmCIF preview exporter(s) with exact units/topology/sidecar metadata; no fake XTC/DCD.
- [ ] Numerical reference tests, PBC failures, source-digest invariance, actual Mol* browser/export re-import tests and screenshots.
- [ ] CHANGELOG.md [Unreleased], Adviser CLEAR, Examiner PASS and new independent Auditor PASS at exact head.
- [ ] No merge/tag/deploy without maintainer approval.