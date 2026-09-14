# Typed Task Inputs and Test Architecture Cleanup - Implementation State

## Current phase

Implementation and local verification are complete. Accelerator-dependent live
acceptance and browser execution remain environment-specific delivery gates.

## Completed contract work

- [x] Replaced flat positional input fields with named roles, logical types,
  formats, and per-role cardinality owned by each `task.yaml`.
- [x] Migrated Server submission, artifact reuse, immutable manifests, Runner
  dispatch, live-test manifests, OpenAPI, and task-creation UI to role-indexed
  protocol-v3 `inputs`.
- [x] Made role binding explicit and independent of multipart/upload order.
- [x] Preserved original inputs and hashes under role-resolved snapshot paths;
  cleanup removes only disposable `scratch` and `prepared` content.
- [x] Separated transport/path safety, format parsing, logical-type validation,
  neutral normalization, and Runner-owned scientific preparation.
- [x] Removed Server positional access such as `saved_inputs[0]` and retired flat
  input-contract attributes from `TaskType`.
- [x] Kept the Server as the source of truth and Runner manifests self-contained
  for later extraction into a standalone repository.

## Completed test cleanup

- [x] Removed pure static/declaration suites and production-inventory assertions
  that only restated YAML, shell, SIF, dependency, documentation, or source text.
- [x] Reduced mixed Runner suites to executable wrappers, parsers, validators,
  normalizers, adapters, and observable API behavior.
- [x] Migrated retained request fixtures and Runner manifests to explicit roles.
- [x] Moved input-contract behavior to `tests/server/inputs/`.
- [x] Moved Runner-owned executable logic to `tests/runners/<family>/`.
- [x] Moved cross-component role/dispatch behavior to `tests/integration/`.
- [x] Preserved meaningful readiness, receipt, access-control, scheduler,
  persistence, artifact, browser-contract, and public API coverage.

## Verification

- Non-browser suite before the final nine static-test deletions: **864 passed,
  4 skipped**. The deleted cases had all passed and contained no executable
  behavior; affected focused suites were rerun afterward.
- `pytest -q tests/runners tests/integration`: **132 passed** after final cleanup.
- Final focused Server/Runner/integration regression gate: **189 passed**.
- Focused Slurm contract: **45 passed**.
- JavaScript contract: **1 passed** with `node --test tests/js/test_contracts.js`.
- Changed Runner shell scripts pass `bash -n`.
- Python compile and `git diff --check` pass.
- Full collection: **891 tests**.
- Playwright is not executable in this sandbox: Chromium aborts before test setup
  with `sandbox_host_linux.cc: Operation not permitted`. No browser assertion ran.
- `ruff` is not installed in the current environment.

## Production service recovery (2026-09-14)

- Recovered `/mnt/data/srv/revodesign/server-slurm` from an isolated clean clone of
  `main` commit `3d7bc735486925d21420cc94d8e62d6b3b0fc2e4`; unfinished workspace edits were
  not deployed.
- Prepared restart validated configured SIF metadata and resource policies and
  started redis, web, gateway, maintenance, and worker.
- Removed one stale `.maintenance` sentinel owned by `nobody:nogroup` that the
  configured Runner identity could not remove.
- Final verification from the deployed Docker network: `/compute/api/types`
  returns task JSON, the unauthenticated dashboard returns expected HTTP 401, and
  all five containers are running.

## Remaining delivery gates

- Run the Playwright suite in an environment where Chromium namespaces/sandboxing
  are permitted.
- Run Docker/Compose smoke and target-host SLURM/Apptainer live acceptance for the
  changed Runner contracts, following per-family resource and accelerator policy.
- The controller's silent tolerance of stale maintenance-marker removal is a
  separate operational defect and was not expanded into this refactor.
