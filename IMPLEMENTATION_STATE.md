# Project-Scope Removal Implementation State

This file records execution truth for `refactor/remove-project-scope`. `TODO.md`
is the design truth; tests and acceptance commands are machine truth. PR6 history
remains available in Git and is intentionally not duplicated here.

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

## Current blockers and next action

- No repository blocker.
- Branch is ready to commit, push, and open the requested unmerged PR.
