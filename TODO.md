# PR33 — Main Application Presentation Cutover

## Objective

PR32 established a real Presentation Plane and transferred Result Workspace + Mol* ownership to `frontend/`.

PR33 must now make the **entire ordinary user compute workflow** frontend-owned:

```text
Discover Runner
      ↓
Inspect Runner
      ↓
Configure Task
      ↓
Preflight
      ↓
Submit
      ↓
Dashboard / Monitor
      ↓
Result Workspace
```

The following application surfaces are transferred to `frontend/` in this PR:

```text
App Shell
Dashboard
Runner Catalog
Runner Detail
Create Task
Result Workspace integration
```

This is a **replacement/cutover**, not a backward-compatible migration.

When a surface is successfully transferred, delete its superseded Jinja template, page JavaScript, page CSS, view-model construction, and bridging code.

Do not maintain parallel old/new implementations.

The intended architecture after PR33 is:

```text
Browser

Presentation Plane
frontend/
├── App Shell
├── Dashboard
├── Runner Catalog
├── Runner Detail
├── Create Task
└── Result Workspace
        │
        │ same-origin HTTP/OpenAPI
        ▼
Control Plane
revocompute/
├── identity/authentication
├── TaskType contracts
├── task/query/mutation APIs
├── access/readiness
├── validation/preflight
├── artifact/result contracts
└── Runner-owned presentation asset authorization
        │
        ▼
Execution Plane
Celery / Slurm / Apptainer / Runtime Bundle / Runner
```

PR33 must not alter the Execution Plane to satisfy presentation needs.

---

# 0. Fresh Session Bootstrap

This work begins from a fresh agent session.

Before editing:

1. Fetch the latest remote state.
2. Check out current `main`.
3. Verify PR32 is present in history.
4. Record the exact starting SHA.
5. Read:
   - `CLAUDE.md`
   - `AGENTS.md`
   - current architecture documentation
   - Runner change-impact documentation
   - PR32 Result frontend implementation
6. Inspect the existing frontend build and route structure before designing new abstractions.
7. Replace the completed PR32 root `TODO.md` with this PR33 contract.
8. Reset/update `IMPLEMENTATION_STATE.md` to describe PR33 only.

Do not recover old abandoned implementations from stashes or previous branches unless a specific piece is demonstrably still canonical.

Do not begin from PR32's old feature branch.

---

# 1. Governing Principles

PR33 follows these invariants.

## 1.1 Ownership transfer, not compatibility

For each surface:

```text
old implementation
       ↓
new frontend implementation proves correct
       ↓
delete old implementation
```

Do not add:

- compatibility pages;
- deprecated frontend routes;
- old/new feature flags;
- legacy rendering fallbacks;
- duplicate API models;
- duplicate JavaScript implementations;
- redirects whose only purpose is preserving an obsolete route.

A URL may remain unchanged when it is still the desired canonical product URL. That is not backward compatibility.

## 1.2 Presentation depends on Control

Allowed:

```text
frontend
   ↓
OpenAPI / HTTP
   ↓
backend
```

Forbidden:

```text
frontend → Python internals
frontend → TaskStore
frontend → Slurm
frontend → runner filesystem layout

backend → frontend component state
backend → Vite chunk graph
backend → DOM/layout
backend → Runner-specific browser rendering
```

## 1.3 Presentation must never modify Execution requirements

Do not change:

- Runner `.def`;
- build inputs;
- runtime scripts;
- scientific executables;
- canonical scientific outputs;
- Slurm execution;
- Runtime Bundle behavior;

merely to satisfy the frontend.

If the browser needs another representation of canonical data, solve it in the Control Plane through an explicit bounded API/projection.

## 1.4 Do not pursue architectural perfection

Fix real correctness, security, ownership, contract, or maintainability problems.

Do not delay PR33 for cosmetic naming, theoretical abstraction purity, or optional framework work.

---

# 2. Establish the Shared Application Shell

PR32 created the frontend application but Result remains effectively the first route-specific island.

PR33 must establish the common application shell.

Suggested structure:

```text
frontend/src/
├── app/
│   ├── App.ts
│   ├── router.ts
│   ├── routes.ts
│   ├── session.ts
│   ├── navigation.ts
│   ├── theme.ts
│   └── notifications.ts
├── api/
├── components/
└── features/
    ├── dashboard/
    ├── runners/
    ├── create-task/
    └── results/
```

Exact filenames may differ.

The shell owns:

- route resolution;
- primary navigation;
- current-user/session presentation;
- theme;
- global loading/error state;
- notifications/toasts;
- route outlet;
- responsive navigation.

Do not introduce Redux, Zustand, React Router, Tailwind, Storybook, or another large framework unless an actual requirement cannot be cleanly satisfied with the current TypeScript architecture.

Mol* may continue to use React internally because that is its integration requirement; this does not require making REvoCompute itself a React application.

---

# 3. Canonical Frontend Routes

Continue using product routes that remain useful:

```text
/runners
/runners/:name
/compute/create_task
/compute/dashboard
/compute/results/:taskId
```

These become frontend application routes.

Do not preserve an old route solely because it existed historically.

Do not rename useful current URLs merely for aesthetic consistency.

Direct navigation and browser refresh must work for every frontend route.

Backend page handlers should only:

- enforce server-owned access rules where necessary;
- serve `frontend/dist/index.html` unchanged.

They must not render page-specific templates or inject business state.

---

# 4. Integrate Result Workspace into the App Shell

PR32 Result code is already the canonical implementation.

Do not rewrite it.

Adapt it only enough to mount cleanly as an application route:

```text
App Shell
   ↓
Route Outlet
   ↓
ResultWorkspace
```

Preserve:

- direct Mol* integration;
- Storyboards;
- artifact tree;
- scientific visualization;
- fullscreen;
- downloads;
- responsive workspace;
- current Result API contract.

Avoid re-opening PR32 architecture unless a real integration defect requires it.

Mol* must remain lazy-loaded.

---

# 5. Add the Canonical Task List API

The current Dashboard obtains its primary model from Jinja-injected server state.

That must end.

Introduce a canonical API such as:

```text
GET /compute/api/tasks
```

The exact route may differ if an existing canonical endpoint already satisfies the requirement, but do not create a second overlapping task-list API.

The response should expose stable Task resources, not a Jinja-oriented view model.

Define an OpenAPI schema such as `TaskSummary`.

Useful server-owned fields include:

```text
task_id
display_name
task_type
status
terminal
submitted_at
finished_at
walltime
owner / owner identity when authorized
progress
outcome
error when authorized
result_available
can_cancel
can_delete
input preview metadata when applicable
```

Avoid presentation-only fields such as:

```text
formatted date strings
CSS class names
button labels
HTML fragments
card layout hints
```

Frontend formats timestamps and chooses presentation.

For non-admin users return only their visible Tasks.

For admins return the Tasks permitted by current admin semantics.

Deleted/cleanup states must follow one authoritative backend contract rather than frontend-maintained guesses.

Document the endpoint in OpenAPI and regenerate TypeScript types.

---

# 6. Dashboard Cutover

Rebuild the Dashboard under:

```text
frontend/src/features/dashboard/
```

Preserve meaningful existing functionality:

- summary counts;
- search;
- regex search;
- task-type filter;
- status filter;
- submitted/finished date filtering;
- sort;
- detailed/compact/table layouts;
- running progress/state;
- Result navigation;
- download/archive action;
- cancel;
- delete;
- admin batch selection/delete;
- structure input preview where still useful;
- responsive layout;
- error display.

The frontend should consume Task API resources.

Do not recreate `_dashboard_task_status()` as a TypeScript clone.

If a field is server-owned truth, expose it through the API.

Polling should remain simple.

Prefer bounded polling for active Tasks.

Do not introduce WebSockets.

SSE is unnecessary unless a concrete requirement appears during implementation.

---

# 7. Dashboard Input Preview

The existing Dashboard can preview structure input.

If this remains useful, preserve it through an explicit authorized API contract.

Do not infer the server-side input path.

The Task resource may expose something conceptually like:

```text
input_preview:
    capability: molecular_structure
    format: pdb
    url: /compute/api/tasks/<id>/input
```

Only expose it when authorized and scientifically appropriate.

Use the frontend MolecularViewer abstraction where practical instead of retaining py2Dmol-only Dashboard code.

Do not eagerly initialize Mol* for every Dashboard row.

Structure preview must remain lazy.

---

# 8. Runner Catalog Cutover

Transfer:

```text
/runners
```

to `frontend/`.

Use:

```text
GET /compute/api/types
```

as the authoritative catalog.

Do not create a second Runner registry for the frontend.

Preserve useful catalog behavior:

- categories;
- runner/task name;
- summary/description;
- availability/readiness;
- access state;
- license/access notice;
- relevant hardware/resource information;
- links to Runner Detail;
- Create Task actions.

Public/anonymous catalog behavior should remain intentional.

The catalog must not read:

```text
plugin.yaml
task.yaml
runner.yaml
docker/runners/
```

directly.

The Control Plane remains the projection boundary.

---

# 9. Runner Detail Cutover

Transfer:

```text
/runners/:name
```

to `frontend/`.

Use:

```text
GET /compute/api/types/:name
```

and the canonical parameter schema.

Preserve meaningful content:

- scientific description;
- Runner/task identity;
- inputs;
- parameters;
- resource expectations;
- access state;
- citations;
- documentation;
- output/result capabilities where exposed;
- readiness/availability;
- Create Task CTA.

Do not reproduce the server's registry logic in frontend code.

Unknown Runner names should render a proper frontend not-found state based on the API response.

---

# 10. Create Task Cutover

This is the most important validation of the Runner Contract.

Transfer:

```text
/compute/create_task
```

completely to `frontend/`.

The frontend obtains all scientific task definitions from:

```text
GET /compute/api/types
GET /compute/api/types/:name
GET /compute/api/task-parameters/:task_type
```

and access/runtime information from existing APIs.

Submission continues through:

```text
POST /compute/api/preflight/:task_type
POST /compute/api/post
```

Access requests continue through:

```text
POST /compute/api/access/requests
```

Do not create a frontend task-type registry.

Do not branch generic Create Task code on Runner names.

A new ordinary parameter, enum, numeric bound, input role, or standard workspace component should not require editing the Create Task application.

---

# 11. Move Input Workspace Ownership into `frontend/`

The following old presentation implementation must not survive PR33:

```text
revocompute/static/js/input-workspace.js
revocompute/static/js/plugin-host.js
```

Reimplement/port their retained behavior into typed frontend modules.

Suggested boundary:

```text
frontend/src/features/create-task/
├── CreateTask.ts
├── task-form.ts
├── parameter-controls.ts
├── input-workspace/
│   ├── InputWorkspace.ts
│   ├── PluginHost.ts
│   ├── plugin-contract.ts
│   └── builtins/
```

Preserve relevant workspace capabilities:

- sequence entry;
- files;
- multiple input roles;
- primary input selection;
- typed parameter controls;
- seed/random controls;
- structure preview;
- chain/residue selection;
- validation;
- summaries;
- runner-contributed workspace capabilities.

Do not simply copy the old IIFE/global code into TypeScript unchanged.

Use proper module ownership.

---

# 12. Formalize the Runner-Owned Workspace Plugin Contract

Runner-specific Create Task UI remains runner-owned presentation logic.

That is valid.

However, it must cross a documented Presentation/Control contract.

The current workspace descriptor APIs should be audited and formally included in OpenAPI if they remain part of the frontend contract:

```text
GET /compute/api/workspace/plugins/:owner/:plugin_id
GET /compute/api/workspace/assets/:owner/:plugin_id/:asset
```

Prefer an explicit ES-module contract.

Conceptually:

```ts
export default {
    id,
    mount(...)
}
```

rather than requiring modules to mutate:

```text
window.REvoComputePlugins
```

The frontend owns:

- plugin lifecycle;
- capability registry;
- error isolation;
- asset loading;
- validation integration.

Runner-owned workspace modules own only their scientific/input-specific interaction.

Do not allow workspace modules to construct backend filesystem paths.

Only descriptor-approved same-origin assets may load.

Update existing runner-owned workspace modules to the canonical module contract where necessary.

Because these are presentation assets, this work must not alter Runner SIF Build Identity.

---

# 13. Remove the Legacy Create Task Mol* Bridge

PR32 temporarily emits stable assets such as:

```text
molecular-viewer.js
molecular-viewer.css
```

because the old Create Task page still loads the new viewer from legacy static JavaScript.

After Create Task itself becomes frontend-owned, that bridge is no longer needed.

Remove it if it has no other real consumer.

The frontend Create Task feature should import the MolecularViewer module through normal frontend source ownership.

Update build verification accordingly.

Do not keep a “stable legacy viewer entry” after its consumer has died.

---

# 14. Parameter Rendering Must Be Schema-Driven

Parameter controls must remain driven by the canonical parameter schema.

Support current declared types and UI metadata, including:

- bool;
- int;
- float;
- string;
- choices/enums;
- numeric min/max/step;
- required/default;
- seed controls;
- descriptions/help;
- units.

Do not manually encode known Runner parameter lists.

Validation should happen at multiple layers:

```text
frontend usability validation
        ↓
preflight API
        ↓
backend canonical validation
```

Frontend validation is never the authority.

---

# 15. Preserve Preflight as the Submission Gate

Create Task must continue to use preflight before actual submission.

The UI should clearly distinguish:

```text
client validation failure
preflight rejection
submission failure
queued successfully
```

Do not duplicate backend validation rules beyond ordinary HTML/schema usability constraints.

Do not infer readiness/access locally.

The backend decides whether the task may be submitted.

---

# 16. App Session Model

Use:

```text
GET /compute/api/auth/me
```

for frontend session identity.

Create a small frontend session service.

Do not store durable authentication tokens in `localStorage`.

Continue using same-origin HttpOnly/session behavior.

PR33 does not transfer Login/Register/Profile ownership.

Protected page routes may continue relying on backend authentication checks until PR34.

This is current ownership separation, not a compatibility layer.

---

# 17. Navigation

The frontend App Shell should provide coherent navigation between:

```text
Dashboard
Runners
Create Task
Result
```

Profile/Admin/Auth may remain ordinary links to their currently owned server pages until PR34.

Do not create a second navigation system for each feature.

Responsive/mobile navigation must remain usable.

---

# 18. Theme Ownership

Frontend-owned routes should use one frontend theme controller.

Do not require:

```text
/static/js/theme.js
/static/js/theme-toggle.js
```

for new frontend pages.

It is acceptable for those files to remain temporarily because still-current PR34 surfaces consume them.

Do not delete a shared static file until all current consumers are gone.

Do not create frontend dependency on server-rendered DOM theme state.

---

# 19. Styling

Move styles for cut-over surfaces into frontend ownership.

Examples:

```text
frontend/src/styles/
frontend/src/features/dashboard/*.css
frontend/src/features/runners/*.css
frontend/src/features/create-task/*.css
```

After proving the new pages, delete page-specific styles that have no remaining consumer.

Avoid introducing a new CSS framework.

Reuse the visual language established by REvoCompute rather than redesigning the entire product.

PR33 is an architecture/ownership refactor, not a visual rebrand.

---

# 20. Delete Superseded Application Presentation

After equivalent/new canonical behavior passes tests, delete:

```text
revocompute/templates/dashboard.html
revocompute/templates/runners.html
revocompute/templates/runner_detail.html
revocompute/templates/create_task.html

revocompute/static/js/dashboard.js
revocompute/static/js/runners.js
revocompute/static/js/create-task.js
revocompute/static/js/input-workspace.js
revocompute/static/js/plugin-host.js
```

Also delete page-specific CSS/helpers proven unused.

Do not retain them as:

```text
legacy/
deprecated/
fallback/
old/
compat/
```

Delete backend view-model assembly that exists only for those templates.

Examples include Dashboard-specific server formatting that is superseded by the Task API.

Do not delete presentation resources still genuinely used by PR34 surfaces.

---

# 21. Backend Frontend-Entry Serving

Factor the PR32 pattern into a very small generic helper if doing so reduces repetition:

```text
authorize route if required
        ↓
serve static/app/index.html unchanged
```

The backend must not parse Vite manifest data or know frontend chunks.

Avoid a broad Flask catch-all if it risks swallowing:

- API routes;
- artifact routes;
- docs;
- auth pages;
- static assets.

Explicit frontend route ownership is acceptable and easier to reason about.

---

# 22. OpenAPI Is the Contract

Every new frontend data dependency must be represented by the authoritative OpenAPI schema.

After API changes:

```text
OpenAPI
   ↓
generated TypeScript schema
   ↓
thin frontend client
```

Do not manually maintain duplicate TypeScript domain interfaces when generated types already express the resource.

Frontend convenience/view-state types are fine.

Backend model types must not leak into frontend.

---

# 23. API Gap Rule

PR33 may add or improve Control Plane APIs when the old Jinja page was hiding server-owned data.

Examples:

```text
GET /compute/api/tasks
workspace plugin descriptors
input preview metadata
```

Before adding an endpoint, verify an existing canonical endpoint cannot serve the need.

Do not create endpoints named around pages such as:

```text
/dashboard-data
/create-task-bootstrap
/frontend-config
/runner-page-data
```

Expose domain resources, not page payloads.

---

# 24. Dashboard Polling and State

Do not mirror server lifecycle rules manually.

Task responses should expose:

```text
status
terminal
available actions/capabilities where appropriate
```

The frontend may poll non-terminal tasks.

When a task becomes terminal, stop polling it.

Avoid full-page reloads as the normal refresh path.

A manual Refresh action may simply re-fetch API data.

---

# 25. Access and Readiness

Runner Catalog, Detail, and Create Task must consume the same authoritative access/readiness contract.

Do not implement separate access logic per page.

Restricted Runner behavior should be coherent across:

```text
Catalog
Detail
Create Task
```

An access request submitted from Create Task should update frontend state without requiring a server-rendered page reload.

---

# 26. Security

Preserve or improve the existing security boundaries.

Requirements:

- same-origin APIs;
- HttpOnly/session authentication;
- no durable token storage;
- no arbitrary remote plugin/module URLs;
- no arbitrary server filesystem paths;
- no unsafe HTML rendering of server text;
- no `eval` or dynamically executed source strings;
- plugin assets must be descriptor-approved;
- uploads remain bounded by backend rules;
- frontend cannot bypass preflight/access/readiness;
- admin-only actions remain server-authorized regardless of UI visibility.

Frontend hiding a button is not authorization.

---

# 27. Performance

Keep the shell lightweight.

Use route/feature lazy loading where meaningful.

At minimum:

- Mol* stays lazy;
- structure preview stays lazy;
- Result scientific modules stay lazy;
- Create Task runner-specific workspace assets load only for the selected task type.

Do not preload every Runner Storyboard or workspace plugin.

Do not optimize beyond demonstrated needs.

---

# 28. Testing — Backend Contract

Add/update backend tests for:

- task list resource;
- ordinary-user visibility;
- admin visibility;
- task action permissions;
- current-user contract;
- input preview authorization if retained;
- workspace plugin descriptors/assets;
- Runner type/detail contract;
- preflight/submission contract;
- frontend route serving;
- OpenAPI completeness.

Page route tests should verify frontend entry serving, not Jinja content.

---

# 29. Testing — Frontend

Add frontend tests for:

## App Shell

- route resolution;
- navigation;
- session loading;
- not-found state;
- theme;
- route feature lazy loading.

## Dashboard

- filtering;
- regex error state;
- sorting;
- layout switching;
- active-task refresh;
- terminal transition;
- cancel;
- delete;
- admin batch delete;
- Result navigation.

## Runner Catalog/Detail

- catalog rendering;
- category grouping;
- unknown Runner;
- access notice;
- Create Task navigation.

## Create Task

- task selection;
- query `task_type`;
- parameter schema rendering;
- validation;
- input roles;
- multi-file inputs;
- primary input selection;
- sequence mode;
- seed controls;
- workspace plugins;
- structure preview;
- access request;
- preflight reject;
- successful submission.

---

# 30. Browser / Full-Stack Acceptance

The ordinary user workflow must be tested end-to-end:

```text
login using existing auth page
    ↓
open Runner Catalog
    ↓
open Runner Detail
    ↓
Create Task
    ↓
choose inputs / parameters
    ↓
preflight
    ↓
submit
    ↓
Dashboard
    ↓
observe Task
    ↓
open Result
```

Also exercise:

- direct `/runners`;
- direct `/runners/:name`;
- direct `/compute/create_task`;
- direct `/compute/dashboard`;
- browser refresh on each route;
- mobile viewport;
- session expiry;
- restricted Runner;
- invalid task/Runner IDs;
- admin Dashboard actions.

Do not mock away the frontend/backend boundary in the full-stack acceptance tests.

---

# 31. Deletion Tests

Add repository/static assertions ensuring superseded files do not return.

The completed PR must not contain the old implementations listed in section 20.

Do not allow future code to silently reintroduce Jinja-owned Dashboard/Runner/Create Task application pages.

---

# 32. Runner Change-Impact Discipline

PR33 is Presentation/Control work.

Do not trigger Runner rebuilds through accidental execution changes.

Runner-owned workspace presentation assets may change where necessary.

Changes classified as Presentation Identity must remain presentation-only.

If implementation appears to require:

```text
run.sh
*.def
runtime.build_inputs
scientific output generation
```

stop and redesign the boundary before proceeding.

PR33 should not invalidate SIF Build Identity.

---

# 33. Documentation

Update architecture documentation to reflect the new ownership:

```text
Presentation Plane
frontend/
├── App Shell
├── Dashboard
├── Runner Catalog / Detail
├── Create Task
└── Result Workspace
```

Document remaining server-owned presentation surfaces truthfully.

Do not describe PR33 as a backward-compatible migration.

Use language such as:

```text
cutover
replacement
ownership transfer
frontend-owned
superseded implementation removed
```

Avoid leaving a duplicate root planning document.

Use only the canonical `TODO.md` plus the normal implementation-state record.

---

# 34. Explicit Non-Goals

PR33 must not:

- migrate Profile;
- migrate User Control/Admin;
- migrate Login/Register/Reset/Verification;
- migrate Logs/Configuration;
- rewrite the public mission/home page;
- rewrite API Docs;
- redesign authentication;
- introduce backward-compatibility layers;
- split the repository;
- split the public origin;
- introduce CORS;
- introduce microservices;
- introduce GraphQL;
- introduce WebSockets;
- redesign Result Workspace;
- redesign Mol*;
- modify Runner scientific execution;
- modify Runtime Bundle architecture;
- modify persistent execution/OOM/resource-learning;
- add new scientific Runners;
- redesign the whole visual language.

Those remaining presentation surfaces belong to the final cutover.

---

# 35. Acceptance Criteria

PR33 is complete when all of the following are true.

1. `frontend/` owns the common application shell.
2. Dashboard is frontend-owned.
3. Runner Catalog is frontend-owned.
4. Runner Detail is frontend-owned.
5. Create Task is frontend-owned.
6. Result Workspace operates inside the common frontend application.
7. Direct navigation and refresh work on all frontend routes.
8. Dashboard primary state comes from a documented API, not Jinja.
9. Runner pages consume TaskType APIs, not server-rendered registry objects.
10. Create Task is driven by TaskType + parameter + workspace contracts.
11. Generic Create Task code has no Runner-name branches.
12. Runner-owned input workspace plugins use an explicit frontend contract.
13. No superseded global `window.REvoComputePlugins` architecture remains.
14. No superseded stable legacy MolecularViewer bridge remains if it has no current consumer.
15. Preflight remains authoritative before submission.
16. Same-origin auth remains secure.
17. Frontend stores no durable auth secret.
18. Old Dashboard/Runner/Create Task templates are deleted.
19. Old Dashboard/Runner/Create Task JavaScript is deleted.
20. Unused page-specific CSS/helpers are deleted.
21. Backend no longer assembles Jinja view models for these surfaces.
22. OpenAPI describes every frontend data contract.
23. Generated frontend API types are current.
24. No Runner execution/build identity changes were introduced for presentation needs.
25. Frontend typecheck passes.
26. Frontend tests pass.
27. Backend tests pass.
28. Browser contracts pass.
29. full-stack Compose tests pass.
30. Documentation strict build passes.
31. The complete ordinary user compute workflow works without application Jinja presentation.
32. There is exactly one active implementation for each cut-over surface.

---

# 36. Final Review Rule

Before opening PR33, perform focused reviews against four questions.

### Ownership

For Dashboard, Runners, Create Task, and Result:

> Is there exactly one active presentation implementation, owned by `frontend/`?

### Contract

> Can the frontend reconstruct each page exclusively from URL + documented HTTP APIs?

### Dependency direction

> Did any browser need cause Runner execution/scientific output to change?

The answer must be no.

### Dead code

> Does any deleted/superseded Jinja/static implementation still have an active caller or fallback path?

If not, delete it.

Do not delay completion for non-principled polish.

Fix correctness, security, contract, ownership, and dependency violations; leave optional aesthetic cleanup for later.

---

# Expected PR33 End State

```text
frontend/
    App Shell
       │
       ├── Dashboard
       ├── Runner Catalog
       ├── Runner Detail
       ├── Create Task
       └── Result Workspace
              │
              │ OpenAPI / HTTP
              ▼
revocompute/
    Control Plane
              │
              ▼
    Celery / Slurm / Apptainer / Runner
```

At that point the ordinary scientific-compute workflow is fully frontend-owned.

PR34 should then be a bounded final cutover of the remaining account/admin/auth/server presentation surfaces and removal of the remaining application Jinja/static presentation architecture.