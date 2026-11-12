# BioEmu2 unified Task — execution checklist

## Investigation and contract
- [ ] Verify HEAD, upstream `6d1ca744` CLI/API, #148 behavior, JAAG pinned serializer/source/license, current server role validation.
- [ ] Prove whether BioEmu2's ligand steering is propagation-only for YAML-driven complexes; document per-mode external dependencies.
- [ ] Specify one `bioemu2` schema (mode enum + mode-dependent CIF constraints), result files and legacy-read compatibility plan.
- [ ] Confirm that the server can reject missing/extra CIF before allocation without importing heavyweight scientific packages.

## Implementation
- [ ] Author new `bioemu2` Task manifest and conditional-input schema; remove old three Tasks from the selectable catalog.
- [ ] Implement required System YAML and CIF rule through Core input validation, typed API projection, preflight, Task snapshot and submission.
- [ ] Wire a pinned JAAG builder to the System YAML role and preserve plain YAML uploads; add integration tests.
- [ ] Replace FASTA-specific adapter with upstream System/CLI mapping; preserve pinned checkpoint, modes, seed and CCD fix.
- [ ] Unify result declarations, mode-specific presentation/provenance and mode-aware docs without dropping historical Task artifacts.
- [ ] Update Runner input policy docs and CHANGELOG.md [Unreleased].

## Verification and release boundary
- [ ] 3-mode input matrix; scientific fixtures for multichain, ligands, modifications, explicit bonds and mismatched CIF.
- [ ] Fast regressions + real SIF/pinned upstream CLI tests + server preflight negative tests + browser tests/screenshots.
- [ ] Actual ligand-bearing live scientific acceptance and fresh bundle identity/receipt **before READY**, never inferred from mock success.
- [ ] Independent Adviser CLEAR, Examiner PASS, separate Acceptance Auditor PASS on exact head; no merge/tag/deploy without maintainer.