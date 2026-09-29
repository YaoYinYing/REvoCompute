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

**Phase 4 - integrated verification and production switch.** The Control Plane
contracts, Vite-owned browser surfaces, and legacy-presentation subtraction are
implemented. Focused backend/frontend gates pass; browser acceptance, broad
repository gates, production deployment, independent review, and delivery
remain in progress.

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
  and `60b24ee` (Presentation Plane surfaces).
- Focused backend gate: 202 tests collected; the initial run exposed one stale
  exact OpenAPI path-set assertion, all other 201 passed, and the corrected
  assertion then passed independently.
- Frontend gate after subtraction: TypeScript typecheck, 54 Vitest tests across
  15 files, and the verified production build pass. The build contains local
  Swagger UI and logo assets and requires no CDN script, style, or font source.
- Responsive audits of the implemented surfaces at 320px, 390px, 768px, and
  desktop report no horizontal overflow.
- Integrated Playwright gate: 23 Vite-bundle browser tests pass across public,
  auth, profile, admin, ordinary task, result, direct-refresh, theme, and
  responsive behavior.
- The tracked backend presentation tree now contains only the email template;
  all superseded page templates and legacy page JavaScript/CSS are deleted.

## Immediate next actions

1. Run repository, coverage, documentation, image, Compose, and full-stack
   acceptance gates; then deploy with `--use-proxy` and exercise live behavior.
2. Run three independent review passes, batch valid findings, commit the final
   state, push the branch, open PR34, and pause the goal without review bots.
