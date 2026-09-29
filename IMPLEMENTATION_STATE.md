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

**Phase 1 - inventory and contract design.** The remaining Jinja/static
presentation has been inventoried. Backend, public/profile frontend, and admin
frontend vertical slices are being assigned with non-overlapping ownership.

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
- [ ] Classify every remaining browser artifact and HTML route in the final
      ownership audit.

### Control Plane contracts

- [ ] Add explicit server-authoritative reset-password and email-verification
      mutation APIs; browser GET routes must not validate or mutate tokens.
- [ ] Add a bounded legal terms resource with one canonical repository source.
- [ ] Expose registration capability only if existing APIs cannot represent
      enabled/email-service availability safely.
- [ ] Keep all profile/admin/auth authorization and validation server-owned.
- [ ] Update OpenAPI and regenerate frontend API types for every new contract.

### Presentation Plane cutover

- [ ] Establish the lightweight public/auth shell while reusing canonical theme,
      notifications, dialogs, and session behavior.
- [ ] Cut over Home, Terms, API Docs, Login, Forgot Password, Register, Reset
      Password, and Email Verification.
- [ ] Cut over Profile account editing, API-key lifecycle, metrics, GPU credits,
      and personal Runner access.
- [ ] Cut over User Control, access policy/request/entitlement administration,
      GPU-credit administration, Configuration, and Logs.
- [ ] Provide frontend-owned not-found, denied, unavailable, and failure states.
- [ ] Preserve direct navigation/refresh, strict CSP, keyboard behavior, and
      responsive layouts at 320px, 390px, 768px, and desktop.

### Production switch and subtraction

- [ ] Serve one inert frontend entry for every browser application route,
      subject only to intentional route-level access/concealment guards.
- [ ] Remove page-specific Jinja view-model construction and browser mutations
      from GET routes.
- [ ] Delete superseded browser templates while retaining email templates.
- [ ] Delete superseded legacy page/bridge JavaScript and page/global CSS.
- [ ] Remove dead `render_template`, static-JS serving, legacy auth/UI/theme
      globals, and compatibility/fallback paths.
- [ ] Verify no Runner definition, execution, build identity, Runtime Bundle,
      scheduler/OOM, Task lifecycle, or scientific behavior changed.

### Behavioral verification

- [ ] Focused backend auth/legal/route/deletion/authorization tests pass.
- [ ] Frontend generated-schema check, typecheck, focused unit tests, and
      production build verification pass.
- [ ] Browser acceptance covers auth, Profile/API key, an admin user mutation,
      access administration, GPU-credit mutation, Configuration, Logs, public
      routes, theme, responsive behavior, direct refresh, and strict CSP.
- [ ] `make test` passes on the final code.
- [ ] `make test-cov` passes on the final code.
- [ ] Docker/Compose smoke and full-stack gates pass.
- [ ] `mkdocs build --strict` passes after documentation updates.
- [ ] Production redeploy with `--use-proxy` and live public/user/API checks
      pass; run a suitable live Runner acceptance test if relevant and available.

### Delivery

- [ ] Update architecture/API documentation and this ledger with exact final
      evidence, remaining files, route classifications, and CI state.
- [ ] Perform the final dead-code, HTML-route, presentation-ownership,
      authorization, CSP, and execution-isolation audits.
- [ ] Commit coherent checkpoints before deployment and PR.
- [ ] Obtain three independent review passes before PR; batch and fix valid
      correctness, security, ownership, contract, and dead-code findings.
- [ ] Push the branch, open PR34, and verify exact-head CI/review state.

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

### Still to classify during implementation

- Logo/favicon source ownership and the temporary `/static/js/<path>` handler
  must be audited after all legacy consumers are removed.
- Every Flask response capable of returning HTML must receive a final explicit
  classification before delivery.

## Current evidence

- Fetched `origin/main` and local `main` both resolved to `36109f8`.
- The starting commit is PR33's squash merge and no prior PR34 code exists.
- The current OpenAPI covers most existing profile/admin domain APIs, including
  session, metrics, access, users, credits, configuration, infrastructure, and
  logs; the PR34-specific auth/legal resources are absent.
- The current frontend owns Runner, Dashboard, Create Task, Result, shell,
  session, theme, and notifications, but no PR34 feature family yet.
- No implementation or verification claim has been made for PR34.

## Immediate next actions

1. Commit the PR34 contract and execution-ledger checkpoint.
2. Delegate the backend contract/route slice, public/profile frontend slice, and
   admin frontend slice with explicit shared-file coordination.
3. Integrate each working vertical slice, run focused gates, then subtract its
   superseded Jinja/static implementation.
