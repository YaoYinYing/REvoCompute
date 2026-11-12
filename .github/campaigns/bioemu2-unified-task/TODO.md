# BioEmu2 unified Task — execution checklist

## Investigation and contract
- [x] Verify HEAD, upstream `6d1ca744` CLI/API, #148 behavior, JAAG pinned serializer/source/license, current server role validation.
- [x] Prove whether BioEmu2's ligand steering is propagation-only for YAML-driven complexes; document per-mode external dependencies.
- [x] Specify one `bioemu2` schema (mode enum + mode-dependent CIF constraints), result files and legacy-read compatibility plan.
- [x] Confirm that the server can reject missing/extra CIF before allocation without importing heavyweight scientific packages.

## Implementation
- [x] Author new `bioemu2` Task manifest and conditional-input schema; remove old three Tasks from the selectable catalog.
- [x] Implement required System YAML and CIF rule through Core input validation, typed API projection, preflight, Task snapshot and submission.
- [ ] Wire a pinned JAAG builder to the System YAML role and preserve plain YAML uploads; add integration tests.
  - BLOCKED: vendoring the pinned JAAG `dist/jaag-builder.revo.js` was refused by the
    tool permission classifier (third-party browser code). No builder capability is
    declared, so plain System YAML upload remains the only path. Needs an explicit
    permission grant or a maintainer-provided in-repo reviewed builder module.
- [x] Replace FASTA-specific adapter with upstream System/CLI mapping; preserve pinned checkpoint, modes, seed and CCD fix.
- [x] Unify result declarations, mode-specific presentation/provenance and mode-aware docs without dropping historical Task artifacts.
- [x] Update Runner input policy docs and CHANGELOG.md [Unreleased].

## Verification and release boundary
- [x] 3-mode input matrix (server submission + preflight) and runner fast regressions for YAML parsing, mode dispatch, CCD retry and steering.
- [ ] Fast regressions + real SIF/pinned upstream CLI tests + server preflight negative tests + browser tests/screenshots.
  - Fast runner and server tests pass. Real SIF/CLI and browser runs require the
    Commander-authorized window and a fresh Runtime Bundle/live receipt.
- [ ] Actual ligand-bearing live scientific acceptance and fresh bundle identity/receipt **before READY**, never inferred from mock success.
  - BLOCKED: `/mnt/db/weights/bioemu2/steering/` is absent; the expected
    `boltz-1-ccd.pkl` is not provisioned. A live-test PASS would activate live
    readiness and needs a maintainer-authorized window (not granted).
- [ ] Independent Adviser CLEAR, Examiner PASS, separate Acceptance Auditor PASS on exact head; no merge/tag/deploy without maintainer.

## Fixtures
- [x] `tests/data/bioemu2/equilibrium_system.yaml` and `propagation_start.yaml`
  serialized by pinned JAAG `jaag-core`; propagated CIF is the captured 2KL8 topology.
- [ ] Ligand-bearing propagate fixture matching the pinned upstream parser and the
  reviewed JAAG serializer (needs real upstream execution evidence).
