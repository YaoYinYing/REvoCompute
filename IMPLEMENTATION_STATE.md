# PR33 Implementation State

`TODO.md` is the architectural and acceptance contract. This file records the
current execution state; tests and the named acceptance commands are the
machine-verifiable truth.

## Starting point

- Starting branch: local `main`, matching local `origin/main`.
- Starting SHA: `724a155` (`refactor(frontend): establish Result presentation boundary (#32)`).
- PR32 is present as the current `main` tip.
- The required remote fetch was attempted twice but could not run because the
  command-approval service returned HTTP 503. It must be retried before push.
- Initial worktree change: the user-provided PR33 replacement of `TODO.md` only.
- No abandoned stash or previous feature branch has been restored.

## Active phase

**Verification and delivery.** The frontend cutover, API contracts, Runner
workspace module migration, legacy subtraction, browser qualification, Compose
smoke, and independent reviews are complete. Final broad verification,
production deployment, live acceptance, and PR delivery remain.

## Completion checklist

### Bootstrap and architecture

- [x] Read `CLAUDE.md`, `AGENTS.md`, `TODO.md`, and `LONG_TASK_HANDLING.md`.
- [x] Read the current Presentation/Control/Execution architecture and Runner
      change-impact guidance.
- [x] Inspect the PR32 Result frontend and current frontend build/router shape.
- [x] Record the starting SHA and confirm PR32 in local history.
- [x] Fetch current remote state successfully and create the PR33 feature branch.
- [x] Replace the completed PR32 execution ledger with this PR33-only ledger.

### Control Plane contracts

- [x] Add one canonical, authorized Task list resource and OpenAPI `TaskSummary`
      contract without page-oriented fields.
- [x] Expose authorized, lazy input-preview capability where scientifically
      appropriate, without server-path inference.
- [x] Formalize workspace plugin descriptors/assets in OpenAPI and use an
      explicit approved same-origin ES-module contract.
- [x] Confirm TaskType catalog/detail, parameter schema, session, access,
      readiness, preflight, submission, cancellation, deletion, and archive
      contracts are sufficient; add only missing domain fields.
- [x] Regenerate and verify frontend OpenAPI types.

### Presentation Plane cutover

- [x] Establish the shared frontend App Shell, URL router, navigation, session,
      theme, notifications, route loading/error handling, and responsive layout.
- [x] Mount the existing Result Workspace inside the shared shell without
      redesigning it; keep Mol* and scientific modules lazy.
- [x] Cut over Dashboard, including filtering, sorting, layouts, polling,
      progress, actions, admin batch behavior, and lazy structure preview.
- [x] Cut over Runner Catalog and Runner Detail from canonical TaskType APIs.
- [x] Cut over Create Task from TaskType, parameter, access/readiness,
      workspace, preflight, and submission contracts.
- [x] Port the input workspace to typed frontend modules with schema-driven
      parameters, named roles, sequence/files/structure/selection/review, and
      isolated Runner-owned plugins.
- [x] Preserve direct navigation and refresh for every frontend-owned route.

### Production switch and subtraction

- [x] Make backend page handlers authorize where required and serve the frontend
      entry unchanged, with no Jinja state injection.
- [x] Delete superseded Dashboard/Runner/Create Task templates, page JavaScript,
      input-workspace/plugin-host globals, and unused page CSS/helpers.
- [x] Remove the stable legacy MolecularViewer bridge after its final consumer
      is migrated.
- [x] Remove backend Jinja view-model assembly and prove no duplicate/fallback
      implementation remains.
- [x] Verify no Runner execution, definition, build-input, Runtime Bundle,
      scheduler, OOM, or scientific-output identity changed.

### Behavioral verification

- [x] Backend contract/auth/visibility/action/frontend-entry tests pass.
- [x] Frontend typecheck, generated-schema check, unit tests, and production
      build pass.
- [x] Browser tests cover shell, Dashboard, Runner Catalog/Detail, Create Task,
      Result integration, direct URLs/refresh, mobile, expiry, restricted and
      invalid states, and admin actions.
- [x] Ordinary Runner -> Create Task -> Dashboard -> Result flow passes across
      the real frontend/backend boundary.
- [ ] `make test` passes on the final code.
- [x] `make test-cov` passes on the final code.
- [x] Docker/Compose smoke and full-stack gates pass.
- [x] `mkdocs build --strict` passes after architecture/docs updates.

### Delivery

- [x] Update architecture documentation and this ledger with current evidence.
- [x] Perform a subtraction/remnant audit against every legacy filename and
      ownership invariant in `TODO.md`.
- [x] Commit coherent checkpoints before deployment and PR.
- [x] Obtain three independent focused review passes; fix correctness, security,
      ownership, contract-direction, and dead-code findings.
- [ ] Redeploy with the production environment and `--use-proxy`; validate the
      public API/user flow and run a suitable live Runner acceptance test when
      accelerator availability permits.
- [ ] Push the PR33 branch, open PR33, and verify CI/review state.

## Current evidence

- Local `main` and local `origin/main` both started at `724a155`. A fresh remote
  fetch succeeded before delivery and confirmed `origin/main` remains at that
  SHA. The feature branch is `feat/pr33-main-application-cutover`.
- `GET /compute/api/tasks`, typed workspace descriptors, authorized structure
  input preview, and all new OpenAPI/generated TypeScript contracts pass focused
  schema/auth tests (`76 passed, 4 skipped`, followed by final focused reruns).
- Frontend `typecheck`, generated schema check, 40 unit tests, and production
  build pass. The manifest emits Mol* only as a hashed lazy chunk.
- The first broad non-browser diagnostic run reached `1490 passed, 19 skipped`;
  its two stale fixture failures were corrected and their focused rerun is
  `5 passed`. The final `make test-cov` gate passes with `1492 passed, 19
  skipped, 79 deselected`, and 83% coverage.
- `mkdocs build --strict` passes.
- The application browser suite passes (`11 passed`), including the ordinary
  Runner-to-Result workflow, direct-route refresh, restricted access, session
  expiry, mobile navigation clearance, dark theme, and admin actions.
- The Docker/Compose full-stack gate passes end to end.
- Three focused review passes covered architecture/ownership, security/API
  contracts, and frontend behavior. Their actionable findings were fixed and
  covered by focused server, frontend-unit, and browser regression tests.
- Superseded templates, page scripts/styles, global plugin hosts, the stable
  MolecularViewer bridge, old redirects, and duplicate root backlog are deleted.
- The only Runner file changed is the RFdiffusion workspace presentation module;
  no Runner definition, execution adapter, build input, scheduler contract,
  scientific output, or Runtime Bundle declaration changed.

## Immediate next actions

1. Finish the in-progress final non-browser coverage gate and run the isolated
   full browser gate.
2. Push the review branch and open PR33 for pre-review.
3. Deploy with the production environment and `--use-proxy`, validate the
   public workflow, and run live acceptance.
4. Complete the separately requested stale-SIF candidate rebuilds without
   promoting any candidate that lacks a matching live-test receipt.
