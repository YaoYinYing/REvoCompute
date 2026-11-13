# BioEmu2 unified Task — execution checklist

## Investigation and contract
- [x] Verify HEAD, upstream `6d1ca744` CLI/API, #148 behavior, JAAG pinned serializer/source/license, current server role validation.
- [x] Prove whether BioEmu2's ligand steering is propagation-only for YAML-driven complexes; document per-mode external dependencies.
- [x] Specify one `bioemu2` schema (mode enum + mode-dependent CIF constraints), result files and legacy-read compatibility plan.
- [x] Confirm that the server can reject missing/extra CIF before allocation without importing heavyweight scientific packages.

## Implementation
- [x] Author new `bioemu2` Task manifest and conditional-input schema; remove old three Tasks from the selectable catalog.
- [x] Implement required System YAML and CIF rule through Core input validation, typed API projection, preflight, Task snapshot and submission.
- [x] Wire a pinned JAAG builder to the System YAML role and preserve plain YAML uploads; add integration tests.
  - The builder is a REvoCompute-owned frontend builtin (`jaag-builder`) that
    validates and serializes with the pinned JAAG core (`6bc0ff50`, Apache-2.0)
    and binds the generated YAML to the declared `system` role. The core is
    fetched at build time by `frontend/scripts/fetch-jaag-core.mjs` and verified
    against `frontend/provenance/jaag.json`; no third-party JS is committed.
    Plain YAML upload remains the first capability in the same step.
- [x] Replace FASTA-specific adapter with upstream System/CLI mapping; preserve pinned checkpoint, modes, seed and CCD fix.
- [x] Unify result declarations, mode-specific presentation/provenance and mode-aware docs without dropping historical Task artifacts.
- [x] Update Runner input policy docs and CHANGELOG.md [Unreleased].

## Verification and release boundary
- [x] 3-mode input matrix (server submission + preflight) and runner fast regressions for YAML parsing, mode dispatch, CCD retry and steering.
- [x] Fast Runner/Server regressions: mode dispatch and CLI args, malformed YAML failing before the CLI, role matrix at submission/preflight, CCD retry, steering-asset gating, deprecated-task catalog/doctor handling, fleet inventory.
- [x] Pinned-upstream parser/CLI acceptance: `docker/runners/bioemu2/tests/scientific/test_pinned_upstream.py`
  runs against `bioemu2_v1.sif` (`6d1ca744`), parses the three JAAG fixtures and
  the upstream-packaged examples with the real `load_system_and_contacts`, and
  parses every flag emitted by the adapter's three mode commands with the real
  Click command objects. This is parser/CLI acceptance, not a scientific result.
- [ ] Browser interaction screenshot for the builder. The builder is covered by
  the frontend DOM test; a rendered browser pass needs the shared browser lane.
- [ ] Actual ligand-bearing live scientific acceptance and fresh bundle identity/receipt **before READY**, never inferred from mock success.
  - BLOCKED: `/mnt/db/weights/bioemu2/steering/` is absent; the expected
    `boltz-1-ccd.pkl` is not provisioned. The host's `/mnt/db/boltz/ccd.pkl` has
    the same declared SHA-256 (`2d3b2f03…`) but is not copied without
    authorization. The available GPU is a 40 GB A100, below the 80 GB A100
    upstream records as the smallest tested device, and no live window is
    authorized.
- [ ] Independent Adviser CLEAR, Examiner PASS, separate Acceptance Auditor PASS on exact head; no merge/tag/deploy without maintainer.

## Fixtures
- [x] `tests/data/bioemu2/equilibrium_system.yaml`, `propagation_start.yaml` and
  `ligand_system.yaml` serialized by pinned JAAG `jaag-core`; the propagated CIF
  is the captured 2KL8 topology; the ligand system declares a `NAG` CCD ligand.
- [x] Ligand-bearing System YAML parses with the pinned upstream parser and is
  detected by the adapter's steering-code rule.
