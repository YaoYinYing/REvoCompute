# PR8 Full Fleet Restoration Implementation State

## Current phase

- Branch: `feat/full-fleet-restoration`
- Baseline: `main` at `6de5534` (merged PR #7)
- Parameter-contract hardening and local verification are complete. Exact-current
  fleet live validation is complete for all enabled families after a focused
  OpenDDE scratch-copy fix; deployment promotion remains blocked by target
  configuration drift.

## Completed in this session

- Removed deployment `runner.yaml` defaults from effective parameter resolution.
- Removed duplicated user-facing shell defaults from AF3, BioEmu, ColabFold,
  AlphaFold, FreeBindCraft, PLACER, and ESM adapters.
- Bounded BioEmu sampling to 1–1000 and batch size to 1–100.
- Routed ESM extraction temporary/cache state to task-local scratch.
- Added task.yaml projection/default-source architecture tests.
- Updated runner adaptation/access documentation.
- Removed the RunnerConfig/live-test compatibility path for deployment defaults;
  Doctor rejects any non-empty runner.yaml `defaults` declaration.
- Added canonical Draft 2020-12 `parameter_schema` to the TaskType detail API.
- Updated required smoke cases to exercise non-default AF3/BioEmu values,
  LigandMPNN sequence output, and ColabFold relaxation.

## Verification

- Focused parameter and runner contract tests: `109 passed`.
- Non-browser suite: `743 passed, 4 skipped`.
- Full coverage suite with browser permission: `756 passed, 4 skipped`, 82%.
- Browser contracts: `12 passed`.
- Strict Doctor: diagnostics `[]`.
- `mkdocs build --strict`, compileall, shell syntax, OpenAPI JSON parsing, and
  `git diff --check`: passing.
- Shell syntax and `git diff --check`: passing.
- Target-host live acceptance: 13/14 families passed on the first full run;
  OpenDDE was fixed from `cp -a` metadata preservation to
  `cp -R --no-preserve=mode,ownership`, rebuilt directly, and then passed its
  focused live test.
- OpenDDE focused static/Doctor gate: `47 passed`.
- Full fleet receipts were written for AlphaFold, AlphaFold3, BioEmu,
  ColabFold, EasIFA, ESM, ESMDynamic, FreeBindCraft, MPNN, OpenDDE,
  PLACER/RFdiffusion, PRIME, GREMLIN, and Pythia-ddG.

## Remaining

- Synchronize the target deployment `CONFIG_DIR` with the current repository
  plugin/config tree; prepared-restart currently rejects the target's enabled
  runner list as unknown and `runner-status` cannot establish current identity.
- After configuration synchronization, rerun prepared validation/restart and
  verify READY status for every enabled family.
- Commit, push, open the required unmerged PR, then monitor redeploy/readiness.

---

# Historical Project-Scope Removal State

This file records execution truth for `refactor/remove-project-scope`. The local,
intentionally gitignored `TODO.md` is the design truth; tests and acceptance
commands are machine truth. PR6 history remains available in Git and is
intentionally not duplicated here.

## Baseline and active phase

- Baseline: remote `main` at `0b70b76f0a31609b2e4167720c877558a14f18b7` (merged PR #6).
- Branch: `refactor/remove-project-scope`.
- Active phase: Phase 1 — introduction/current-tree audit and personal-task contract.
- Introduction boundary audited: `38c054c4eb69f19ae631ebb36653520583fe833a`
  against parent `ca97f5e16271ebcd048d66e7d70253522642d987`.

## Completion checklist

- [x] Verify clean current-main baseline and create the required feature branch.
- [x] Read repository guidance, TODO, prior state, and the Project introduction boundary.
- [x] Record and apply the DELETE/PRESERVE/TRANSFORM introduction inventory.
- [x] Remove Project/collaboration persistence and application initialization.
- [x] Establish the fresh personal-task schema epoch with fail-fast old-state rejection.
- [x] Remove `scope_type`/`scope_id` from task persistence and Runner-access audit context.
- [x] Preserve immutable user `storage_key`, task `submitted_by_user_id`, and useful username snapshots.
- [x] Simplify storage resolution to `users/<storage-key>/tasks/<task-id>` while retaining all confinement checks.
- [x] Derive task ownership/storage and task identity from the authenticated immutable user identity.
- [x] Replace scope-aware read/mutation/dashboard authorization with owner/admin checks.
- [x] Remove all Project routes, membership/role/invitation/lifecycle behavior, and API schemas.
- [x] Remove Project frontend assets, pages, navigation, and create-task scope selection.
- [x] Preserve same-owner finalized artifact references, immutable snapshots, manifest validation, and safe retrieval.
- [x] Remove Project fields from provenance while preserving Project-independent provenance propagation.
- [x] Remove Project-specific tests and transform retained storage/artifact/security coverage.
- [x] Remove canonical Project documentation and update personal storage/schema/operator documentation.
- [x] Add executable negative architecture/remnant checks.
- [x] Run focused regression gates.
- [x] Run full `make test` and `make test-cov` gates.
- [x] Run strict Doctor and relevant Runner contract gates without redesigning the PR6 control plane.
- [x] Run Compose/full-stack contracts with safe example values.
- [x] Run `mkdocs build --strict`, documentation checks, compileall, and `git diff --check`.
- [x] Audit every current-tree and introduction-diff Project remnant; justify lexical false positives.
- [x] Record exact final evidence, commit coherently, push the branch, and open the required unmerged PR.

## Introduction audit classification

- DELETE: `collaboration.py`; collaboration DB/bootstrap; Project records, storage keys,
  roles/capabilities/memberships/invitations/archive/transfer; Project storage dispatch;
  Project routes/pages/assets/tests/docs; task scope columns and Project audit context.
- PRESERVE: immutable user/task storage keys; `submitted_by_user_id`; schema-epoch
  fail-fast behavior; storage/path confinement; manifest-backed artifact metadata and
  retrieval; SHA-256/size checks; downstream input snapshots; artifact provenance;
  per-user task-ID isolation; result finalization/archive/range/preview behavior.
- TRANSFORM: scope identity to immutable user ownership identity; scoped storage to
  personal user storage; same-scope reuse to same-owner reuse; scope-aware task
  authorization/discovery to owner/admin checks; schema/docs/tests to the new epoch.

## Validation record

- Pre-edit worktree was clean on `main`; fetch and fast-forward-only pull succeeded.
- Cached and fetched `origin/main` both resolved to `0b70b76f0a31609b2e4167720c877558a14f18b7`.
- `0b70b76` is an ancestor of the feature branch baseline.
- Focused: `23 passed`.
- Full regression: `make test` -> `740 passed, 4 skipped, 3 warnings`.
- Coverage regression: `make test-cov` -> `752 passed, 4 skipped, 3 warnings`, total coverage 82%.
- Browser contracts: `12 passed` (host-level Chromium sandbox permission used).
- Strict Doctor: `python -m revocompute doctor --config-root docker/runners --strict --json` -> diagnostics `[]`.
- Compose render: `docker compose --env-file .env.example config --quiet` -> success.
- Full-stack contract: `make test-docker-full-stack` -> `Full-stack mocked-HPC test passed.`
- Docs/code gates: `mkdocs build --strict`, citation check, compileall, shell syntax, and `git diff --check` -> success.
- Final architecture audit: only intentional epoch-rejection markers and unrelated generic “project” terminology remain;
  no Project domain files, routes, persistence, scope dispatch, UI, or canonical docs remain.
- PR #7 cleanup validation: `pytest -q tests/test_project_removal_architecture.py tests/test_task_type_registry.py
  tests/test_plugin_discovery.py` -> `15 passed`; citation check, `mkdocs build --strict`, and `git diff --check` -> success.
- Final ESMDynamic citation uses the peer-reviewed Nature Communications (2026) DOI
  `10.1038/s41467-026-76361-2`; the bioRxiv DOI is no longer referenced.
- Persistent-state documentation cleanup: `pytest -q tests/test_project_removal_architecture.py
  tests/test_schema_epoch.py tests/test_task_type_registry.py tests/test_plugin_discovery.py` -> `19 passed`;
  citation check, `mkdocs build --strict`, and `git diff --check` -> success.

## Current blockers and next action

- No repository blocker.
- Branch is ready to commit, push, and open the requested unmerged PR.
