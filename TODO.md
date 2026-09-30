# PR34 — Final Browser Presentation Cutover

## Objective

PR32 transferred Result Workspace + Mol* ownership to `frontend/`.

PR33 transferred the ordinary scientific compute workflow to `frontend/`:

```text
Runner discovery
→ Runner detail
→ Create Task
→ Preflight / Submit
→ Dashboard
→ Result
```

PR34 completes the browser Presentation Plane cutover.

After this PR:

> **All browser-facing product presentation is owned by `frontend/`. Flask is the REvoCompute Control Plane/API server, not a page-rendering application.**

The remaining browser surfaces to replace are:

```text
Account / self-service
├── Profile
├── API key
├── Usage / metrics
├── GPU credits
└── Runner access

Administration
├── User Control
├── Access policies / requests / entitlements
├── GPU credit administration
├── Runtime configuration
└── Logs

Authentication
├── Login
├── Register
├── Forgot password
├── Reset password
└── Email verification

Public / publication surfaces
├── Home
├── Terms
└── API Docs
```

This is a **replacement / ownership cutover**.

It is not a backward-compatible migration.

When a frontend implementation becomes canonical, delete the superseded template, JavaScript, CSS, server-rendered view model, and compatibility bridge.

Do not leave duplicate implementations under names such as:

```text
legacy/
old/
deprecated/
compat/
fallback/
v1/
```

---

# 0. Fresh Session Bootstrap

Start from a fresh agent session and current remote `main`.

Before editing:

1. Fetch remote.
2. Check out current `main`.
3. Confirm PR33 squash merge is present.
4. Record the exact starting SHA.
5. Verify worktree is clean.
6. Read:
   - `CLAUDE.md`
   - `AGENTS.md`
   - current `TODO.md`
   - `IMPLEMENTATION_STATE.md`
   - frontend architecture documentation
   - PR32/PR33 frontend application structure
   - OpenAPI contract
7. Inventory all remaining:
   - `revocompute/templates/`
   - `revocompute/static/js/`
   - `revocompute/static/css/`
   - browser page routes in `revocompute/routes.py`
8. Classify each remaining browser artifact as:
   - CUT OVER;
   - DELETE;
   - BACKEND-OWNED NON-BROWSER;
   - still legitimately shared.

Replace the previous root `TODO.md` with this PR34 contract.

Update `IMPLEMENTATION_STATE.md` to describe PR34 only.

Do not continue from PR33's branch.

---

# 1. Architectural End State

PR34 must finish this architecture:

```text
┌────────────────────────────────┐
│ Presentation Plane             │
│ frontend/                      │
│                                │
│ Home                           │
│ Auth                           │
│ Runners                        │
│ Create Task                    │
│ Dashboard                      │
│ Result                         │
│ Profile                        │
│ Administration                 │
│ Legal                          │
│ API Docs                       │
└───────────────┬────────────────┘
                │ HTTP / OpenAPI
                ▼
┌────────────────────────────────┐
│ Control Plane                  │
│ revocompute/                   │
│                                │
│ Authentication                 │
│ Users                          │
│ Tasks                          │
│ Runner Registry                │
│ Access                         │
│ GPU Credits                    │
│ Configuration                  │
│ Results / Artifacts            │
│ Logs                           │
│ Legal source                   │
└───────────────┬────────────────┘
                │
                ▼
┌────────────────────────────────┐
│ Execution Plane                │
│ Celery / Slurm / Apptainer     │
│ Runtime Bundle / Runner        │
└────────────────────────────────┘
```

After PR34, application browser pages must not depend on Jinja rendering.

---

# 2. Governing Rules

## 2.1 Replacement, not compatibility

For every cut-over surface:

```text
old browser implementation
        ↓
new frontend implementation proven correct
        ↓
delete old implementation
```

Do not maintain an alternate old route implementation.

A URL may remain unchanged when it is still the desired canonical URL.

That is product continuity, not backward compatibility.

---

## 2.2 Frontend consumes domain APIs

Allowed:

```text
frontend
   ↓
same-origin HTTP/OpenAPI
   ↓
Control Plane
```

Forbidden:

```text
frontend → Python models
frontend → Flask globals
frontend → database
frontend → filesystem
frontend → TaskStore
frontend → Slurm
frontend → direct config files

backend → DOM
backend → component state
backend → Vite asset graph
backend → page-specific HTML fragments
```

---

## 2.3 Security remains server-authoritative

Frontend may hide unavailable controls.

Frontend must never become authorization.

The backend remains authoritative for:

- user identity;
- roles;
- admin authorization;
- API-key ownership;
- access policies;
- access requests;
- entitlements;
- GPU credits;
- user mutations;
- runtime configuration;
- log access;
- reset/verification token validity.

---

## 2.4 Do not chase perfection

Block PR34 only for:

- correctness;
- security;
- ownership;
- contract direction;
- meaningful regressions;
- dead duplicate implementations;
- broken CI.

Do not prolong PR34 for optional visual polish or theoretical abstraction purity.

---

# 3. Two Frontend Shells

Do not force every page into the authenticated application shell.

Formalize two browser shells.

## 3.1 Application Shell

Use the existing PR33 shell for:

```text
/runners
/runners/:name

/compute/dashboard
/compute/create_task
/compute/results/:id

/compute/profile
/compute/user_control
/compute/configuration
/compute/logs
```

It owns:

- main navigation;
- current user;
- admin navigation;
- theme;
- notifications;
- route outlet;
- responsive application layout.

---

## 3.2 Auth/Public Shell

Create a lighter shell for:

```text
/
/compute/login
/compute/register
/compute/reset_password
/compute/user_verify
/compute/terms
/api-docs
```

It may share:

- branding;
- theme;
- notification primitives;
- form primitives;
- accessibility conventions.

It must not expose authenticated application controls merely because the implementation lives in the same frontend.

Exact filenames are flexible.

Suggested shape:

```text
frontend/src/app/
├── router.ts
├── shell.ts
├── public-shell.ts
├── session.ts
├── theme.ts
├── dialogs.ts
└── notifications.ts
```

---

# 4. Expand the Canonical Router

Add frontend ownership for all remaining browser routes.

Conceptually:

```text
/
→ home

/api-docs
→ api-docs

/compute/login
→ login

/compute/register
→ register

/compute/reset_password
→ reset-password

/compute/user_verify
→ verify-email

/compute/terms
→ terms

/compute/profile
→ profile

/compute/user_control
→ admin-users

/compute/configuration
→ admin-configuration

/compute/logs
→ admin-logs
```

Preserve the canonical existing URLs unless changing one solves a real problem.

Direct navigation and refresh must work.

---

# 5. Profile Cutover

Replace:

```text
revocompute/templates/profile.html
revocompute/static/js/profile.js
revocompute/static/css/profile.css
```

with:

```text
frontend/src/features/profile/
```

Suggested substructure:

```text
profile/
├── Profile.ts
├── account.ts
├── api-key.ts
├── usage.ts
├── credits.ts
├── access.ts
└── profile.css
```

Preserve current useful behavior.

---

# 6. Profile — Account

Consume:

```text
GET /compute/api/auth/me
PUT /compute/api/auth/me
```

Support current editable identity/profile fields.

Do not duplicate backend validation rules unnecessarily.

Backend remains authoritative.

The frontend should provide usability validation only.

---

# 7. Profile — API Key

Consume:

```text
GET    /compute/api/auth/me/api-key
POST   /compute/api/auth/me/api-key
DELETE /compute/api/auth/me/api-key
```

Preserve:

- status;
- generation;
- one-time secret display;
- revoke;
- confirmation.

Never persist API-key secrets in:

```text
localStorage
sessionStorage
IndexedDB
```

The secret may exist only in live presentation state required to display it after creation.

---

# 8. Profile — GPU Credits

Consume the canonical GPU-credit API.

Preserve:

- current allowance;
- remaining credits;
- relevant usage information;
- ledger/reason information currently exposed to the user.

Do not reproduce credit accounting logic in TypeScript.

Frontend formats quantities.

Backend calculates them.

---

# 9. Profile — Usage / Metrics

Consume:

```text
GET /compute/api/user-metrics
```

Preserve the current selectable time windows and useful summaries.

Do not add a charting framework solely for this page unless necessary.

Use simple DOM/SVG/CSS visualization if sufficient.

---

# 10. Profile — Runner Access

Consume:

```text
GET  /compute/api/access
POST /compute/api/access/requests
```

Preserve:

- policy state;
- granted access;
- pending requests;
- license/terms references;
- suspension/restriction state where currently visible.

Use the same access vocabulary already established in Runner Catalog/Create Task.

Do not build a second access-state interpretation model.

---

# 11. Administration Architecture

Create one frontend administration feature family.

Suggested structure:

```text
frontend/src/features/admin/
├── users/
├── access/
├── credits/
├── configuration/
├── logs/
└── shared/
```

Do not implement five unrelated mini-applications.

Shared admin primitives may include:

- searchable data lists;
- destructive confirmation;
- reason prompts;
- loading/error state;
- pagination/filter helpers;
- audit/event rendering.

Keep these small.

Do not create a generic enterprise-admin framework.

---

# 12. User Control Cutover

Replace:

```text
revocompute/templates/user_control.html
revocompute/static/js/user-control.js
revocompute/static/css/user-control.css
```

Use the existing admin APIs.

Preserve meaningful functionality:

- list users;
- search/filter;
- add user;
- edit user;
- delete user;
- batch actions;
- account status;
- registration status;
- role;
- profile metadata;
- access state;
- GPU-credit administration.

Server authorization remains mandatory.

---

# 13. Admin User Mutations

Continue consuming canonical endpoints such as:

```text
GET  /compute/api/auth/admin/users
POST /compute/api/auth/admin/users
PUT  /compute/api/auth/admin/users/:id
DELETE /compute/api/auth/admin/users/:id
POST /compute/api/auth/admin/users/batch
```

Do not wrap these in page-specific endpoints such as:

```text
/admin-page-data
/user-control-bootstrap
```

Frontend consumes domain resources.

---

# 14. Access Administration

Preserve administration of:

```text
access policies
access requests
entitlements
suspensions
revocation
event/audit history
```

Consume existing APIs:

```text
/compute/api/auth/admin/access/*
/compute/api/auth/admin/users/:id/entitlements
...
```

Do not redesign the policy model in PR34.

Do not alter Runner authorization semantics merely because the UI changes.

---

# 15. GPU Credit Administration

Preserve current operations:

- inspect per-user credit state;
- adjustment;
- allowance change;
- per-user reset;
- global reset;
- reconciliation if exposed;
- required reason;
- idempotency keys;
- confirmation.

The frontend must not calculate authoritative balances.

Continue using backend responses.

Destructive/high-impact credit actions need explicit confirmation.

Global reset must retain strong deliberate confirmation.

---

# 16. Configuration Cutover

Replace:

```text
configuration.html
configuration.js
configuration.css
```

with:

```text
frontend/src/features/admin/configuration/
```

Consume:

```text
GET /compute/api/auth/admin/config
PUT /compute/api/auth/admin/config

GET /compute/api/infrastructure
POST /compute/api/auth/admin/infrastructure/refresh

GET /compute/api/types
```

Preserve:

- configuration sections;
- task-type configuration;
- infrastructure status;
- scheduler status;
- GPU status;
- stale evidence;
- refresh;
- validation failures.

Do not infer runtime configuration from Runner files.

Do not redesign configuration persistence.

---

# 17. Logs Cutover

Replace:

```text
log_viewer.html
log-viewer.js
log-viewer.css
```

Use:

```text
GET /compute/api/auth/admin/logs/:name
GET /compute/api/auth/admin/logs/archives
GET /compute/api/auth/admin/logs/archives/:archive
```

Preserve:

- log source selection;
- bounded tail/view;
- refresh;
- rotated archive listing;
- archive download/access;
- error state.

Do not create a browser endpoint that exposes arbitrary filesystem paths.

The server remains responsible for the allowed log vocabulary.

---

# 18. Authentication Feature Family

Create:

```text
frontend/src/features/auth/
├── Login.ts
├── Register.ts
├── ForgotPassword.ts
├── ResetPassword.ts
├── VerifyEmail.ts
└── auth.css
```

Authentication UI uses the public/auth shell rather than the authenticated application shell.

---

# 19. Login Cutover

Replace:

```text
login.html
login.js
```

Use:

```text
POST /compute/api/auth/login
POST /compute/api/auth/forgot-password
```

Preserve:

- username/email + password login behavior;
- forgot-password request;
- generic email-response wording;
- return target;
- disabled/loading state;
- meaningful errors.

Validate any `return_to` target safely.

Do not allow open redirects.

---

# 20. Registration Cutover

Replace:

```text
register.html
register.js
```

Consume:

```text
GET  /compute/api/auth/captcha
POST /compute/api/auth/register
POST /compute/api/auth/resend-verification
```

Preserve:

- registration availability;
- email-service availability;
- CAPTCHA;
- account fields;
- terms acceptance;
- post-registration state;
- resend verification.

Do not reproduce backend eligibility logic in the frontend.

Registration-disabled deployments must remain explicit.

---

# 21. Registration Availability Contract

Today Flask may block the registration page before rendering.

After cutover, expose a small server-owned registration capability if the frontend cannot already infer it safely.

Prefer a domain contract such as:

```text
registration:
    enabled
    email_available
```

Do not inject these values into HTML.

Do not create compatibility flags.

If the existing CAPTCHA/register endpoints already provide enough information, reuse them rather than creating unnecessary API surface.

---

# 22. Reset Password Cutover

Current behavior mixes token validation and page rendering.

Separate browser presentation from token authority.

Preferred contract:

```text
/compute/reset_password?token=<opaque>
        ↓
frontend extracts opaque token
        ↓
POST /compute/api/auth/reset-password
```

Move the existing password-reset mutation to an explicit auth API route if practical.

Frontend must not decode or interpret the token.

Backend remains responsible for:

- token validity;
- expiration;
- user lookup;
- password update.

If an explicit pre-validation endpoint is useful, keep it minimal.

Do not add client-side security assumptions.

---

# 23. Email Verification Cutover

Current GET verification route performs mutation and renders Jinja.

Replace the browser presentation with frontend ownership.

Preferred model:

```text
/compute/user_verify?token=<opaque>
        ↓
VerifyEmail frontend
        ↓
POST /compute/api/auth/verify-email
```

Backend validates the token and performs the mutation.

The browser GET route should not itself mutate account state after the cutover.

Return explicit success/failure JSON.

Do not decode the token client-side.

---

# 24. Home Page Cutover

Replace:

```text
templates/index.html
static/css/index.css
static/js/index-agent-guide.js
```

with:

```text
frontend/src/features/home/
```

Preserve the current product content and information hierarchy unless a change is required for the new frontend architecture.

PR34 is not a home-page redesign.

Preserve:

- REvoCompute positioning;
- Runner / workflow discovery links;
- agent/skills URL copy behavior;
- public navigation;
- responsive behavior;
- theme.

The home page is public.

Do not require session loading before meaningful content can render.

---

# 25. API Docs Cutover

Replace:

```text
api_docs.html
api-docs.js
api-docs.css
```

with:

```text
frontend/src/features/api-docs/
```

The Control Plane owns:

```text
/openapi.json
```

The frontend owns how it is displayed.

Continue using Swagger UI or the current equivalent if appropriate.

Do not move OpenAPI ownership into frontend code.

Theme integration must continue to work.

---

# 26. Terms / Legal Cutover

Keep the legal source canonical in the repository:

```text
revocompute/legal/TERMS_OF_SERVICE.md
```

Do not embed a duplicate copy in TypeScript.

Expose legal content through a small domain API, for example:

```text
GET /compute/api/legal/terms
```

Possible response:

```text
version
updated_at if available
markdown
```

or sanitized server-rendered HTML if that is the safer existing pipeline.

Frontend route:

```text
/compute/terms
```

renders the document.

Do not use arbitrary unsanitized HTML.

Design this so additional legal documents could use the same contract later without creating a general CMS.

---

# 27. Error Presentation

Delete the dedicated browser error-page architecture if it no longer has a justified owner:

```text
error.html
error-page.js
error-page.css
```

Frontend should own user-facing states such as:

```text
NotFound
AccessDenied
Unavailable
GenericFailure
```

Backend APIs return proper status codes and JSON.

For failures occurring before the frontend build can load, a minimal HTTP/text response is sufficient.

Do not keep a large Jinja error system solely for cosmetic fallback.

---

# 28. Route Serving

Browser application routes should converge on:

```text
serve frontend/dist/index.html unchanged
```

after any server-side access/concealment checks intentionally retained.

The backend must not:

- parse the Vite manifest;
- inject user state;
- inject config;
- inject tokens;
- inject page JSON;
- construct page-specific asset graphs.

---

# 29. Page-Level Authorization

API authorization is authoritative.

It is acceptable to retain server-side browser-route guards such as:

```text
@login_required
@admin_required
```

when they are useful and simple.

Do not remove them merely for architectural purity.

However, the returned successful page must still be the inert frontend entry.

No protected browser route should require a Jinja template.

---

# 30. Session and Mutation Authorization

PR33's frontend session implementation is canonical.

Reuse:

```text
frontend/src/app/session.ts
```

Do not create a second auth client.

After PR34, delete:

```text
revocompute/static/js/auth-api.js
```

All frontend mutations should use the canonical ephemeral bearer flow.

Continue enforcing same-origin authorized paths.

Do not persist bearer tokens.

---

# 31. Shared Dialogs / Alerts

Legacy pages currently depend on:

```text
revocompute/static/js/ui.js
```

Port only the useful concepts into frontend primitives:

```text
Confirm
Prompt
Alert / Notice
Dialog
```

Use accessible native `<dialog>` or an equally small implementation.

After all consumers are gone:

```text
static/js/ui.js
```

must be deleted.

Do not build a large UI framework.

---

# 32. Theme Ownership

PR33 frontend theme handling is canonical for frontend-owned pages.

Port remaining public/auth/admin surfaces onto it.

After all browser consumers are gone, delete legacy:

```text
static/js/theme.js
static/js/theme-toggle.js
```

unless a non-frontend browser surface still genuinely requires them.

Do not maintain two theme systems.

---

# 33. CSS Ownership

Move surviving browser styles into frontend ownership.

After each feature cutover, delete its old static CSS.

Expected removals include:

```text
api-docs.css
auth-page.css
configuration.css
error-page.css
index.css
log-viewer.css
profile.css
user-control.css
```

`base.css` should also disappear if no browser page legitimately depends on it after cutover.

Do not keep dead global CSS for compatibility.

---

# 34. JavaScript Deletion Target

At completion, these old browser scripts should be removed if they have no non-browser consumer:

```text
api-docs.js
auth-api.js
configuration.js
error-page.js
index-agent-guide.js
log-viewer.js
login.js
profile.js
register.js
reset-password.js
theme-toggle.js
theme.js
ui.js
user-control.js
```

No equivalent files should be recreated under a `legacy` directory.

---

# 35. Template Deletion Target

At completion, browser templates should be gone.

Expected deletions:

```text
api_docs.html
configuration.html
error.html
index.html
log_viewer.html
login.html
profile.html
register.html
reset-password.html
terms.html
user_control.html
verify-email.html
```

The intended remaining template usage is:

```text
revocompute/templates/email/
```

Email templates are backend communication artifacts, not browser Presentation Plane.

Do not move them merely to make the templates directory empty.

---

# 36. Static Asset End State

Aim for:

```text
revocompute/static/
└── app/
    └── frontend build output
```

plus any genuinely backend-owned immutable files still justified.

If logo/favicon ownership can cleanly move into frontend build, do so.

Do not spend large effort moving trivial immutable assets solely for directory aesthetics.

---

# 37. API / OpenAPI Discipline

Every new frontend data dependency must be documented in OpenAPI.

Likely API additions/adjustments include:

```text
auth reset-password mutation
auth verify-email mutation
legal terms resource
possibly registration capability
```

Use domain names, not page names.

Bad:

```text
/profile-page-data
/admin-bootstrap
/login-config
```

Good:

```text
/auth/me
/auth/verify-email
/legal/terms
```

Regenerate frontend API types after contract changes.

---

# 38. Avoid Duplicate Domain Models

Use generated OpenAPI types where they accurately describe API resources.

Frontend-only view state may use local interfaces.

Do not manually replicate backend domain models if generated types already exist.

---

# 39. Public vs Protected Routes

Expected public routes include:

```text
/
/runners
/runners/:name
/api-docs
/compute/login
/compute/register
/compute/reset_password
/compute/user_verify
/compute/terms
```

Protected application routes include:

```text
/compute/dashboard
/compute/create_task
/compute/results/:id according to existing result visibility semantics
/compute/profile
```

Admin routes include:

```text
/compute/user_control
/compute/configuration
/compute/logs
```

Do not weaken API authorization based on route classification.

---

# 40. Preserve Existing Result / Compute Architecture

PR34 must not reopen:

```text
Result Workspace
Mol*
Storyboards
Create Task workspace contract
Dashboard Task API
Runner Catalog
Runner Detail
```

except for minimal App Shell/router integration.

PR32 and PR33 are canonical.

Do not refactor them opportunistically.

---

# 41. Runner / Execution Non-Goals

PR34 must not modify for presentation reasons:

```text
*.def
runtime.build_inputs
run.sh
Runtime Bundles
Slurm
Celery execution
scientific outputs
scientific validation
OOM learning
persistent execution
Runner readiness
```

PR34 should not make Runner SIFs `BUILD_STALE`.

Runner-owned browser presentation assets may be touched only if required by a genuine frontend contract issue.

---

# 42. Auth Backend Non-Goals

Do not:

- replace current session architecture;
- introduce JWT architecture;
- replace the user database;
- redesign password hashing;
- redesign API keys;
- redesign registration approval;
- redesign access policies;
- redesign roles;
- redesign GPU-credit accounting.

Only separate browser presentation from existing Control Plane behavior.

---

# 43. Home / Public Non-Goals

Do not:

- rebrand REvoCompute;
- rewrite all copy;
- redesign the product story;
- add animation-heavy marketing UI;
- introduce a CMS;
- introduce analytics infrastructure;
- add SEO infrastructure unrelated to cutover.

Preserve useful existing presentation.

---

# 44. Tests — Frontend

Add focused frontend tests for the new feature families.

## Profile

Cover at least:

- profile rendering/update;
- API-key creation/revoke lifecycle;
- access state;
- credit/usage rendering;
- guest restrictions where applicable.

## Admin

Cover:

- user search/list;
- user mutation;
- destructive confirmation;
- access request decision;
- entitlement/revoke;
- credit adjustment/reset;
- configuration fetch/update;
- log source/archive behavior.

## Auth

Cover:

- login;
- forgot-password;
- registration;
- CAPTCHA/error;
- reset token submission;
- verification success/failure;
- safe `return_to`.

## Public

Cover:

- home route;
- Terms;
- API Docs;
- public navigation.

---

# 45. Tests — Browser Acceptance

Keep the suite focused.

High-value flows:

## Authentication

```text
login
→ authenticated app route
```

```text
register
→ verification pending state
```

```text
forgot password
→ generic response
```

```text
reset password
→ token submitted to backend
→ success/failure
```

```text
verify email
→ backend mutation
→ success/failure
```

## Profile

```text
profile
→ update
→ refresh
→ server state preserved
```

API-key lifecycle should be exercised.

## Admin

At least one full User Control mutation flow.

At least one access-policy/request flow.

At least one GPU-credit mutation.

Configuration and Logs should each receive a real browser contract.

## Public

Preserve important existing:

- responsive landing page;
- theme behavior;
- API Docs theme behavior.

Do not restore obsolete DOM assertions from removed implementations.

---

# 46. Tests — Authorization

Explicitly test that frontend presentation cannot bypass backend security.

Examples:

```text
ordinary user → admin user API = 403
ordinary user → admin config API = 403
ordinary user → admin logs API = 403
anonymous → protected API = 401
```

Do not rely only on hidden UI controls.

---

# 47. Tests — Deletion

Add repository assertions that superseded browser presentation does not return.

After cutover, deleted old pages/scripts/styles should return 404 where appropriate.

Prevent future accidental resurrection of:

```text
render_template("profile.html")
render_template("user_control.html")
...
```

The exact test mechanism is flexible.

---

# 48. Browser Route Contract

Add tests confirming every frontend-owned route returns the same inert generated frontend entry, subject only to intended access guards.

No route should contain request/domain state injected into HTML.

---

# 49. Build Verification

The frontend build must contain all route feature chunks required by the final browser application.

Do not make backend build verification understand frontend internals.

Frontend's own build verifier may inspect Vite output.

Backend should only require the built entry document.

---

# 50. CSP

Retain strict CSP compatibility.

No new feature may require:

```text
unsafe-eval
remote arbitrary scripts
inline executable code
```

Swagger/API Docs integration must satisfy the same CSP strategy.

Authentication pages should not weaken CSP.

---

# 51. Accessibility

Preserve basic keyboard and accessible-control behavior for:

- navigation;
- forms;
- dialogs;
- admin destructive actions;
- tabs/sections;
- auth forms;
- API key secret controls.

Do not block the PR on exhaustive accessibility perfection.

Fix obvious structural regressions.

---

# 52. Responsive Behavior

At minimum exercise:

```text
320px
390px
768px
desktop
```

for:

- Auth shell;
- Profile;
- Admin;
- Home.

No document-level horizontal overflow.

Preserve the useful responsive contracts retained after PR33.

---

# 53. Implementation State

`IMPLEMENTATION_STATE.md` must truthfully track:

```text
frontend ownership
remaining templates
remaining legacy JS
remaining legacy CSS
new API contracts
CI status
```

Do not declare cutover complete until exact-head required CI is green.

---

# 54. Final Dead-Code Audit

Before opening PR34, search the repository for:

```text
render_template(
templates/
static/js/
static/css/

REvoDesignAuth
REvoDesignTheme
window.REvo*
UI.alert
UI.confirm
UI.prompt
```

Classify every remaining occurrence.

Remove browser presentation leftovers whose consumers have died.

Do not delete email-template infrastructure.

---

# 55. Final Route Audit

Enumerate all Flask routes that return HTML.

For each one, explicitly classify it as:

```text
frontend entry
email/non-browser
minimal exceptional response
```

There should be no browser application route rendering a Jinja product page.

---

# 56. Final Presentation Ownership Audit

For every browser-visible feature ask:

> Where does its DOM come from?

The correct answer should be:

```text
frontend/
```

not:

```text
Flask/Jinja
```

---

# 57. Final Control Plane Audit

For every sensitive action ask:

> Who authorizes and validates it?

The correct answer should remain:

```text
backend
```

not:

```text
frontend
```

---

# 58. Explicit Non-Goals

PR34 must not:

- introduce backward-compatibility layers;
- split frontend/backend repositories;
- introduce a second domain;
- introduce CORS;
- introduce microservices;
- introduce GraphQL;
- introduce WebSockets;
- adopt a frontend framework solely for this cutover;
- introduce Redux/Zustand/etc.;
- redesign Runner contracts;
- modify Runner scientific execution;
- redesign Task lifecycle;
- redesign authentication architecture;
- redesign access policies;
- redesign GPU-credit accounting;
- redesign runtime configuration;
- rework Slurm/Celery;
- add new Runners;
- redesign Result Workspace;
- redesign Create Task;
- redesign Dashboard;
- redesign Mol*.

---

# 59. Acceptance Criteria

PR34 is complete only when all of the following are true.

1. Profile is frontend-owned.
2. API-key management is frontend-owned.
3. user metrics / GPU-credit presentation is frontend-owned.
4. personal Runner access management is frontend-owned.
5. User Control is frontend-owned.
6. access-policy administration is frontend-owned.
7. GPU-credit administration is frontend-owned.
8. Configuration is frontend-owned.
9. Logs is frontend-owned.
10. Login is frontend-owned.
11. Forgot Password is frontend-owned.
12. Register is frontend-owned.
13. Reset Password is frontend-owned.
14. Email Verification is frontend-owned.
15. Home is frontend-owned.
16. Terms is frontend-owned.
17. API Docs is frontend-owned.
18. user-facing error states are frontend-owned.
19. browser application routes serve generated frontend entry rather than Jinja pages.
20. no page injects domain state into HTML.
21. reset tokens remain server-validated.
22. verification tokens remain server-validated.
23. email verification browser GET no longer needs to perform the account mutation.
24. legal content has one canonical repository source.
25. frontend uses same-origin API contracts.
26. frontend persists no bearer token/API-key secret.
27. admin authorization remains entirely server-enforced.
28. Profile/Admin/Auth use PR33's canonical session/auth client.
29. old `auth-api.js` is deleted.
30. old `ui.js` is deleted when no consumer remains.
31. old legacy theme scripts are deleted when no consumer remains.
32. superseded browser JS is deleted.
33. superseded browser CSS is deleted.
34. superseded browser templates are deleted.
35. `revocompute/templates/` contains no browser application templates.
36. email templates remain intact.
37. no compatibility/fallback browser implementation remains.
38. OpenAPI includes any new domain endpoints.
39. generated frontend API types are current.
40. frontend typecheck passes.
41. frontend unit tests pass.
42. backend tests pass.
43. browser contracts pass.
44. strict-CSP browser qualification passes.
45. full-stack Compose tests pass.
46. docs strict build passes.
47. no Runner SIF Build Identity change was introduced for presentation needs.
48. direct refresh works on every frontend-owned route.
49. public routes remain usable anonymously.
50. protected/admin APIs remain inaccessible without proper authorization.

---

# 60. Definition of Done

At completion:

```text
revocompute/templates/
└── email/
```

is the expected conceptual state.

The exact directory may contain unavoidable non-browser support artifacts, but **there must be no remaining browser application Jinja architecture**.

Likewise, browser runtime JavaScript must originate from:

```text
frontend/
```

rather than hand-maintained:

```text
revocompute/static/js/
```

and browser styling must originate from the frontend build rather than parallel legacy page CSS.

---

# 61. Final Review Questions

Before marking PR34 ready, answer these five questions.

## A. Browser ownership

Is every browser-visible product surface owned by `frontend/`?

## B. Backend purity

Does Flask still render any application page for reasons other than a genuinely non-browser concern?

## C. Security

Are all sensitive operations still authorized and validated server-side?

## D. Dead architecture

Does any old Jinja/static browser implementation remain as a fallback, deprecated version, or duplicate?

The answer must be no.

## E. Execution isolation

Did this browser cutover change Runner scientific execution, SIF build identity, Runtime Bundle execution, or scheduler behavior?

The answer must be no.

---

# 62. Stop Rule

PR34 is intended to finish the frontend/backend presentation refactor.

Once:

```text
Presentation Plane = frontend/
Control Plane      = revocompute/
Execution Plane    = Runner/Celery/Slurm/Apptainer
```

is true and required CI is green:

**stop refactoring the architecture.**

Do not create PR35 merely to chase presentation-architecture purity.

Subsequent work should return to product and scientific priorities:

- Runner readiness;
- scientific correctness;
- target-host acceptance;
- workflow quality;
- UX refinement;
- operational stability;
- new computational capabilities.

PR34 should close this architectural chapter.