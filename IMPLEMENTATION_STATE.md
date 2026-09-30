# PR34 Implementation State

`TODO.md` is the architectural and acceptance contract. This file records the
current execution state; tests and the named acceptance commands are the
machine-verifiable truth.

## Starting point

- Starting branch: local `main`, matching fetched `origin/main`.
- Starting SHA: `36109f8ba06e4bd5b5bb44a962b30fd3774f5226`
  (`refactor(frontend): cut over main application presentation (#33)`).
- PR33 is present as the starting `main` tip.
- Initial worktree change: the user-provided PR34 replacement of `TODO.md` only.
- Feature branch: `feat/pr34-final-presentation-cutover`.
- No PR33 feature branch, abandoned stash, or previous implementation was restored.

## Active phase

**Phase 5 - review closure.** PR34 is open and its architecture has been
accepted. The two narrow final-review findings are implemented: frontend domain
vocabularies are exhaustively keyed by generated OpenAPI types, and Terms
fragment navigation runs after the asynchronous document render. Final local
verification is complete; only the updated branch push remains.

## Completion checklist

### Bootstrap and architecture

- [x] Read `CLAUDE.md`, `AGENTS.md`, `TODO.md`, `LONG_TASK_HANDLING.md`,
      the pasted task, frontend architecture docs, Runner task/family contracts,
      and the server API contract.
- [x] Fetch current remote state, confirm PR33 at `origin/main`, record the
      starting SHA, and create a fresh PR34 branch.
- [x] Replace the PR33 execution ledger with this PR34-only ledger.
- [x] Inventory remaining templates, legacy JavaScript/CSS, page routes, current
      frontend shell/router/session, OpenAPI paths, and relevant tests.
- [x] Classify every remaining browser artifact and HTML route in the final
      ownership audit.

### Control Plane contracts

- [x] Add explicit server-authoritative reset-password and email-verification
      mutation APIs; browser GET routes must not validate or mutate tokens.
- [x] Add a bounded legal terms resource with one canonical repository source.
- [x] Expose registration capability only if existing APIs cannot represent
      enabled/email-service availability safely.
- [x] Keep all profile/admin/auth authorization and validation server-owned.
- [x] Update OpenAPI and regenerate frontend API types for every new contract.

### Presentation Plane cutover

- [x] Establish the lightweight public/auth shell while reusing canonical theme,
      notifications, dialogs, and session behavior.
- [x] Cut over Home, Terms, API Docs, Login, Forgot Password, Register, Reset
      Password, and Email Verification.
- [x] Cut over Profile account editing, API-key lifecycle, metrics, GPU credits,
      and personal Runner access.
- [x] Cut over User Control, access policy/request/entitlement administration,
      GPU-credit administration, Configuration, and Logs.
- [x] Provide frontend-owned not-found, denied, unavailable, and failure states.
- [x] Preserve direct navigation/refresh, strict CSP, keyboard behavior, and
      responsive layouts at 320px, 390px, 768px, and desktop.

### Production switch and subtraction

- [x] Serve one inert frontend entry for every browser application route,
      subject only to intentional route-level access/concealment guards.
- [x] Remove page-specific Jinja view-model construction and browser mutations
      from GET routes.
- [x] Delete superseded browser templates while retaining email templates.
- [x] Delete superseded legacy page/bridge JavaScript and page/global CSS.
- [x] Remove dead `render_template`, static-JS serving, legacy auth/UI/theme
      globals, and compatibility/fallback paths.
- [x] Verify no Runner definition, execution, build identity, Runtime Bundle,
      scheduler/OOM, Task lifecycle, or scientific behavior changed.

### Behavioral verification

- [x] Focused backend auth/legal/route/deletion/authorization tests pass.
- [x] Frontend generated-schema check, typecheck, focused unit tests, and
      production build verification pass.
- [x] Browser acceptance covers auth, Profile/API key, an admin user mutation,
      access administration, GPU-credit mutation, Configuration, Logs, public
      routes, theme, responsive behavior, direct refresh, and strict CSP.
- [x] `make test` passes on the final code.
- [x] `make test-cov` passes on the final code.
- [x] Docker/Compose smoke and full-stack gates pass.
- [x] `mkdocs build --strict` passes after documentation updates.
- [x] Production redeploy with `--use-proxy` and live public/user/API checks
      pass; a suitable live Runner acceptance test was attempted and its
      independent host-runtime failure is recorded below.

### Delivery

- [x] Update architecture/API documentation and this ledger with exact final
      evidence, remaining files, route classifications, and CI state.
- [x] Perform the final dead-code, HTML-route, presentation-ownership,
      authorization, CSP, and execution-isolation audits.
- [x] Commit coherent checkpoints before deployment and PR.
- [x] Obtain three independent review passes before PR; batch and fix valid
      correctness, security, ownership, contract, and dead-code findings.
- [x] Push the branch and open PR34 without triggering review bots or waiting
      for post-push CI/review state.
- [x] Close final review findings for generated-contract vocabulary ownership
      and asynchronous Terms fragment navigation with focused tests.
- [x] Push the review-fix checkpoint. Per delivery instruction, do not trigger
      review bots or wait for post-push CI/review state.

## Initial inventory

### Cut over, then delete

- Templates: `api_docs.html`, `configuration.html`, `error.html`,
  `index.html`, `log_viewer.html`, `login.html`, `profile.html`,
  `register.html`, `reset-password.html`, `terms.html`,
  `user_control.html`, and `verify-email.html`.
- Legacy JavaScript: `api-docs.js`, `auth-api.js`, `configuration.js`,
  `error-page.js`, `index-agent-guide.js`, `log-viewer.js`, `login.js`,
  `profile.js`, `register.js`, `reset-password.js`, `theme-toggle.js`,
  `theme.js`, `ui.js`, and `user-control.js`.
- Legacy CSS: `api-docs.css`, `auth-page.css`, `base.css`,
  `configuration.css`, `error-page.css`, `index.css`, `log-viewer.css`,
  `profile.css`, and `user-control.css`.

### Backend-owned non-browser

- `revocompute/templates/email/` remains backend-owned.
- `/openapi.json`, `/skills.md`, health, artifact/download, and approved
  workspace asset responses remain Control Plane resources rather than pages.

### Final ownership classification

- `frontend/public/logo.svg` and `frontend/public/logo.ico` are Presentation
  Plane build inputs emitted under `/static/app/`; the legacy Flask logo and
  favicon endpoints are absent.
- `revocompute/templates/email/base.html` is the only retained Jinja template
  and is backend-owned email presentation, never a browser page.
- `revocompute/static/openapi.json` and `revocompute/static/skills.md` are
  bounded Control Plane resources. No tracked legacy browser JavaScript or CSS
  remains under `revocompute/static/`.
- Every supported browser route returns the same inert Vite entry after any
  route-level authentication/authorization guard. Error and unavailable states
  are rendered by the frontend.
- Runner storyboard assets remain Runner-owned scientific result presentation;
  their same-origin authenticated-fetch fallback is not a page framework or a
  second application shell.

## Current evidence

- Checkpoints: `83a6e11` (PR34 contract), `a072872` (Control Plane contracts),
  `60b24ee` (Presentation Plane surfaces), `847a838` (legacy subtraction),
  `40edaca` (review fixes), and `285800b` (full-stack presentation contract).
- Focused backend gate: 118 presentation/auth/admin tests pass.
- Frontend gate after subtraction: TypeScript typecheck, 55 Vitest tests, and
  the verified production build pass. The build contains local Swagger UI and
  logo assets and requires no CDN script, style, or font source.
- Responsive audits of the implemented surfaces at 320px, 390px, 768px, and
  desktop report no horizontal overflow.
- Integrated Playwright gate: 29 Vite-bundle browser tests pass across public,
  auth, profile, admin, ordinary task, result, direct-refresh, theme, and
  responsive behavior, including delayed Terms fragment navigation. The headed
  Mol* strict-CSP browser test also passes.
- The tracked backend presentation tree now contains only the email template;
  all superseded page templates and legacy page JavaScript/CSS are deleted.
- Repository gate after final review fixes: 1,584 tests pass and 20 skip.
  Coverage gate: 1,504 tests pass, 19 skip, 81 browser tests are intentionally
  deselected, and total server coverage is 83%.
- The full Docker/Compose mocked-HPC gate passes against the production image,
  including the inert Vite entry contract. Strict MkDocs and shell syntax gates
  pass.
- Production was rebuilt from committed head with `--server-only --use-proxy`.
  The controller's prepared activation rejected the pre-existing active
  AlphaFold image because it predates mandatory live-test receipts; no staged
  image was promoted. The validated `up` path activated the new application
  image against the unchanged active SIFs. All six services are running.
- Public HTTPS validation passes for the entry and static assets, legal and API
  documentation routes, anonymous authorization guard, tester login, Profile,
  metrics, GPU credit, Runner access, task catalog, infrastructure readiness,
  and bearer-token minting.
- Parallel SIF maintenance staged all 19 requested candidates. Eighteen pass
  `%test`; `placer-rfdiffusion` remains the sole deterministic failure because
  DGL tries to create `/root/.dgl` in a read-only home. `ppiformer` rebuilt and
  passed both GPU smoke cases under receipt
  `1790731271471465766-smoke.json`; `pythia_ddg` passed its CPU smoke under
  receipt `1790731078597654412-smoke.json`. The earlier `easifa/smoke` live job
  (72940) still records its independent read-only `/home/revodesign` failure.
  All candidates remain staged and unpromoted, and active SIFs are unchanged.
- Three independent reviews covered backend/security, frontend ownership, and
  delivery/operations. Valid findings were fixed and all affected gates were
  rerun locally; no review bot was requested.

## Immediate next actions

1. Pause the goal immediately after the push without review bots or CI
   babysitting.
