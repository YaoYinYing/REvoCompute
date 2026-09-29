# PR32 — Establish the REvoCompute Frontend Boundary

## Objective

Re-scope the current Result Workspace / Mol* work into the first vertical slice of a broader frontend/backend separation.

PR32 must establish a real `frontend/` application and migrate the **Result Workspace, artifact browsing, and Mol\*** into it. The backend remains the authoritative control plane and exposes data only through HTTP/API contracts.

This is **Phase 1**, not a full frontend rewrite.

The intended architecture after this PR is:

```text
Browser
  │
  ▼
REvoCompute Frontend
  │
  │ HTTP / OpenAPI
  ▼
REvoCompute Backend
  │
  ▼
Core / Celery / Slurm / Apptainer / Runtime Bundle
```

The repository remains a **monorepo**.

Production remains a **single-origin deployment**.

Do not create separate frontend/backend repositories, separate public domains, microservices, or CORS dependencies.

---

# 0. Preserve the Current PR32 Work

Before changing implementation:

- Inspect the complete current worktree and staged/unstaged diff.
- Do **not** reset the branch.
- Do **not** discard already-correct Mol* or Result Workspace work.
- Classify existing changes into:
  - `KEEP`: already compatible with the new frontend boundary.
  - `ADAPT`: useful work that currently depends on Flask templates, iframe state, or backend-owned presentation state.
  - `DROP`: work that only deepens the old frontend/backend coupling or duplicates the new design.
- Record this classification briefly in the implementation notes before continuing.

The architectural target has changed; the scientific and UX requirements have not.

Existing fixes for Mol*, fullscreen, artifact downloads, file navigation, responsive layout, result presentation, and viewer lifecycle should be retained whenever they remain valid.

---

# 1. Define the Boundary

The frontend may depend on **documented backend API contracts only**.

The frontend must not import or infer backend implementation details such as:

- Python models;
- Flask globals;
- SQLite/database layout;
- `task_store` internals;
- Celery objects;
- Slurm job objects;
- runner filesystem paths;
- `plugin.yaml` files directly;
- server-side Result directory layouts;
- Runtime Bundle internals.

The backend must not contain presentation logic for the new Result Workspace.

The backend must not know:

- Mol* state;
- DOM state;
- viewer fullscreen state;
- selected file-tree node;
- responsive breakpoints;
- panel widths;
- Storyboard layout;
- frontend component lifecycle.

The only supported boundary is:

```text
Frontend
    ↓
HTTP/API
    ↓
Backend
```

---

# 2. Create the Frontend Application

Create an independent source tree:

```text
frontend/
├── package.json
├── package-lock.json
├── tsconfig.json
├── vite.config.ts
├── src/
│   ├── app/
│   ├── api/
│   ├── components/
│   └── features/
│       └── results/
└── tests/
```

Use:

- Vite;
- TypeScript;
- ES modules.

Do **not** introduce React, Redux, Zustand, Tailwind, Storybook, or another application framework merely as part of this separation.

If the existing PR32 implementation already demonstrates a concrete need for a component framework, document that need before introducing one.

Prefer the smallest architecture that supports the Result Workspace cleanly.

---

# 3. Keep the Deployment Single-Origin

Development should support:

```text
frontend dev server
        │
        └── proxy /compute/api/*
                    ↓
                 backend
```

Production should remain conceptually:

```text
Nginx
├── frontend routes/static assets
└── /compute/api/* → backend
```

Requirements:

- no CORS dependency;
- no second public API host;
- no separate authentication origin;
- no frontend repository split;
- no independent deployment service in this PR.

Preserve existing authenticated artifact access.

Large artifacts must not be streamed through frontend JavaScript.

Downloads should continue through authorized backend/download infrastructure, including existing X-Accel or equivalent server-side mechanisms where applicable.

---

# 4. Make OpenAPI the Frontend Contract

Audit the existing OpenAPI document and Result-related API endpoints.

The frontend must obtain data through API calls rather than Jinja-injected objects.

Use the OpenAPI contract to derive frontend TypeScript types where practical.

Prefer:

```text
OpenAPI
   ↓
generated/validated TypeScript types
   ↓
thin hand-written API client
```

Do not generate or introduce a large SDK abstraction.

Create a small frontend API layer with operations conceptually equivalent to:

```text
getCurrentUser()
getTask()
getTaskType()
getResultManifest()
getArtifactMetadata()
getArtifactURL()
```

Use actual existing endpoint names and schemas where they already exist.

Do not create duplicate endpoints merely to make frontend code aesthetically convenient.

Add only the minimal API fields/endpoints that are genuinely missing.

---

# 5. Eliminate Server-Injected Result State

The new Result Workspace must be able to initialize from:

```html
<div id="app"></div>
```

plus the current URL.

Do not depend on patterns such as:

```html
<script>
window.task = {{ ... }};
window.result = {{ ... }};
window.isAdmin = {{ ... }};
</script>
```

Do not serialize backend Python view-models into the HTML shell.

The frontend should derive the task/result identity from routing and fetch authoritative state through the API.

Preserve existing externally visible Result URLs where practical.

A browser refresh or copied Result URL must reconstruct the page without preloaded Jinja business state.

---

# 6. Migrate Result Workspace into `frontend/`

Create a frontend-owned Result feature, conceptually:

```text
frontend/src/features/results/
├── ResultWorkspace.ts
├── ResultHeader.ts
├── FilesPanel.ts
├── ArtifactPreview.ts
├── DiagnosticsPanel.ts
├── Storyboard.ts
└── molecular/
    ├── MolecularViewer.ts
    ├── MolstarAdapter.ts
    └── ViewerState.ts
```

Exact filenames may differ if a simpler decomposition is clearer.

The Result Workspace owns:

- current artifact selection;
- file-tree expansion state;
- search/filter state;
- panel visibility;
- panel sizing;
- fullscreen presentation state;
- preview lifecycle;
- Mol* lifecycle;
- Storyboard state;
- frontend-only result presentation state.

The backend owns:

- task state;
- artifact identity;
- artifact authorization;
- result manifest;
- diagnostics data;
- provenance;
- download authorization.

Do not duplicate backend state into a second frontend source of truth.

---

# 7. Remove the Mol* iframe Boundary

Mol* must become a normal frontend dependency/component.

Remove the architectural dependency on:

```text
viewer_shell.html
iframe
postMessage-based application coordination
```

unless a narrowly scoped temporary compatibility shim is unavoidable during migration.

The final Result Workspace must initialize Mol* directly inside a frontend-owned DOM container.

Requirements:

- direct lifecycle ownership;
- deterministic initialization;
- deterministic disposal;
- no duplicate PluginContext after navigation/reload;
- no stale event listeners;
- no hidden iframe state;
- no cross-frame fullscreen logic;
- no duplicated file-loading logic.

Use a pinned Mol* dependency.

Fetch/build it as part of the frontend build rather than depending on a runtime CDN.

Do not vendor an arbitrary copied Mol* distribution into the repository when the package can be reproducibly fetched during build.

---

# 8. Fix Fullscreen Correctly

Fullscreen must apply to the actual molecular-viewer workspace/container, not an iframe pretending to be fullscreen.

Use the browser Fullscreen API where supported.

Requirements:

- enter fullscreen from the viewer;
- exit through the UI;
- `Esc` restores the normal Result Workspace;
- layout recalculates after enter/exit;
- viewer canvas resizes correctly;
- no duplicate toolbar;
- no stale fullscreen state after navigation;
- no page reload required.

---

# 9. Make Files & Diagnostics a Frontend Workspace

For desktop layouts, place **Files & diagnostics** in the right-side workspace as previously planned.

The panel should support:

- collapse/expand;
- search;
- file-tree hierarchy;
- diagnostics visibility;
- artifact selection.

When collapsed, the released width must be reclaimed by the main preview/workspace.

Tablet/mobile layouts should convert the panel to an appropriate drawer/sheet/tab treatment rather than leaving a fixed desktop sidebar.

Do not let the file panel obscure the primary viewer on small screens.

---

# 10. Fix File Tree Semantics

The hierarchy already communicates directory paths.

A file inside:

```text
models/
└── candidate_1.pdb
```

must be displayed as:

```text
candidate_1.pdb
```

not:

```text
models/candidate_1.pdb
```

The complete relative path should remain available for:

- API identity;
- download;
- copy-path action;
- tooltip/details;
- diagnostics.

Display name and artifact identity must remain separate concepts.

---

# 11. Make Result Manifest the Presentation Source of Truth

Do not make the frontend infer scientific meaning solely from filename suffixes.

Prefer explicit artifact metadata supplied through the Result Manifest.

The desired model is:

```text
Runner output
    ↓
Result Manifest
    ↓
Artifact metadata / capability
    ↓
Frontend renderer
```

Support a small artifact presentation vocabulary where the backend already provides enough information, for example:

```text
molecular_structure
table
plot
image
text
archive
download_only
unknown
```

Do not invent an elaborate plugin framework in this PR.

A simple renderer registry is sufficient.

Filename/media-type inference may remain as a compatibility fallback for legacy results, but it must not become the new primary contract.

---

# 12. Keep Mol* Independent of Runner Identity

Mol* must not contain logic such as:

```text
if runner == "alphafold3"
if runner == "boltz"
if runner == "chai1"
```

The molecular viewer should consume artifacts.

Runner-specific interpretation belongs in Result Manifest generation or backend scientific result normalization.

The viewer should only need information such as:

```text
artifact URL
artifact media type
artifact role
optional display metadata
```

This is required so future structure-producing runners work without editing Mol* integration code.

---

# 13. Preserve and Fix Artifact Downloads

All downloadable artifacts that are currently authorized for the user must remain downloadable after removing the iframe/Jinja implementation.

Do not implement downloads by fetching large files into JavaScript memory and constructing Blob URLs unless there is no server-side alternative.

Prefer browser navigation/download requests to authenticated artifact endpoints.

Verify:

- individual structure download;
- arbitrary result-file download;
- archive download where supported;
- files opened in Mol* remain separately downloadable;
- failed/partial result artifacts remain accessible according to existing backend policy.

---

# 14. Remove Decorative Result Taxonomy Where It Adds No Semantics

Revisit the existing:

- Outcome;
- Evidence;
- Selection;

presentation decoration.

If these labels do not correspond to authoritative Result Manifest semantics, remove them rather than recreating them in the new frontend.

The Result Workspace should expose actual scientific artifacts and metadata rather than impose a generic narrative taxonomy on every runner.

---

# 15. Preserve Storyboard Behavior

Do not remove useful Storyboard functionality while restructuring the frontend.

Move Storyboard state into the frontend Result feature.

Ensure:

- artifact selection remains deterministic;
- switching between structures does not unnecessarily recreate the entire application;
- Mol* state is reset only when scientifically/technically necessary;
- Storyboard and file-tree selections cannot silently diverge.

---

# 16. Responsive Result Layout

Explicitly validate:

- desktop;
- tablet;
- mobile.

The new Result Workspace must not inherit the old component-by-component responsive behavior.

Test at least:

```text
wide desktop
normal laptop
tablet portrait/landscape
narrow mobile
```

Requirements:

- no horizontal page overflow;
- no file panel covering the viewer;
- controls remain reachable;
- fullscreen control remains reachable;
- file search remains usable;
- toolbar does not wrap into unusable layouts;
- viewer receives usable vertical space.

---

# 17. Authentication Boundary

Keep browser authentication same-origin.

Do not redesign authentication in PR32.

The frontend may call a current-user/session endpoint if required, but this PR must not introduce:

- new token storage in `localStorage`;
- client-side storage of API secrets;
- cross-origin authentication;
- new auth frameworks.

Preserve HttpOnly/session-cookie protections where currently used.

---

# 18. Security Requirements

The frontend must not accept arbitrary remote structure URLs and proxy/fetch them through privileged backend access.

Artifact loading should use authorized REvoCompute artifact identities/URLs.

Do not use:

- `eval`;
- dynamically executed source strings;
- unsafe HTML insertion for server-controlled text.

Preserve escaping/sanitization for filenames, diagnostics, runner messages, and user-controlled metadata.

Ensure frontend routing cannot turn artifact paths into arbitrary filesystem access.

---

# 19. Keep Legacy Pages Working

PR32 migrates **Result Workspace only** as the first real frontend vertical slice.

The following pages remain outside the migration scope:

- Dashboard;
- Runner catalog;
- Create Task;
- Profile;
- User Control;
- Admin;
- login/register/reset flows.

Do not rewrite these pages in PR32.

Do not block their existing Jinja/static-JS implementations from continuing to work.

This temporary coexistence is intentional.

---

# 20. Do Not Refactor the Backend Core

PR32 must not become another backend architecture PR.

Avoid unrelated changes to:

- Core;
- ExecutionPlan;
- Celery;
- Slurm;
- Runtime Bundle;
- OOM recovery;
- persistent multi-input execution;
- runner freshness;
- scientific runner implementation;
- credit accounting.

Backend changes are permitted only when required to expose a stable frontend API contract.

Keep them minimal.

---

# 21. Development Workflow

Provide simple development commands or documented equivalents for:

```text
frontend dev
backend dev
full-stack dev
```

The frontend development server should proxy API requests to the backend.

Avoid requiring developers to rebuild frontend production assets after every source edit.

The production frontend build must be reproducible from the repository lockfile.

---

# 22. CI and Contract Checks

Add or update CI coverage for:

### Backend

- Result API contract;
- artifact authorization;
- Result Manifest schema;
- existing backend tests.

### Frontend

- TypeScript compile/typecheck;
- frontend build;
- key Result Workspace logic;
- renderer selection;
- Mol* lifecycle helpers where testable without WebGL.

### Full stack / browser

Test at minimum:

- authenticated Result page load;
- browser refresh on Result URL;
- direct Result URL navigation;
- artifact-tree browsing;
- file search;
- molecular structure preview;
- switching between structures;
- file download;
- fullscreen enter/exit;
- panel collapse/restore;
- failed task;
- partial result;
- empty/missing preview;
- mobile layout;
- logout/session expiry behavior.

Existing BrowserContracts and ServerComposeFullStack coverage must remain green.

---

# 23. Remove Obsolete Mol* Boundary Code

After the new path is working and tested, remove code that exists only for the previous iframe architecture.

Candidates include:

```text
viewer_shell.html
viewer-shell.js
iframe bridge/postMessage glue
duplicated viewer state
duplicated artifact-loading helpers
```

Delete only code proven unused.

Do not leave two competing Mol* architectures “temporarily” enabled after PR32.

---

# 24. Do Not Delete All Jinja/Static Infrastructure Yet

Do not perform the final cleanup of:

```text
revocompute/templates/
revocompute/static/
```

because other pages still depend on them.

PR32 should, however, make the Result Workspace independent of them.

The final removal belongs to the later migration phase after all browser application pages move to `frontend/`.

---

# 25. Document the New Architecture

Update architecture/developer documentation to state explicitly:

```text
Presentation Plane
    frontend/

Control Plane
    REvoCompute backend

Execution Plane
    Runner / Celery / Slurm / Apptainer
```

Document that frontend/backend communication occurs through HTTP/API contracts.

Document the temporary coexistence of the new Result frontend and legacy Jinja pages.

Document the planned migration sequence without implementing it in PR32:

```text
PR32  Result Workspace + Mol*
next  Dashboard + Runner Catalog
next  Create Task
next  Profile/Admin/Auth
final legacy frontend removal
```

Do not assign future PR numbers as a hard contract.

---

# 26. Explicit Non-Goals

PR32 must **not**:

- migrate the entire UI;
- split the repository;
- split the public domain;
- introduce microservices;
- introduce CORS;
- redesign authentication;
- introduce a frontend state-management framework without demonstrated need;
- redesign Runner contracts;
- redesign Result scientific semantics beyond the minimum artifact capability contract;
- refactor backend execution architecture;
- add new scientific runners;
- fix unrelated backlog items;
- combine the Runtime Bundle fleet migration with this work.

---

# Acceptance Criteria

PR32 is complete only when all of the following are true.

1. A real `frontend/` application exists and builds independently.
2. Result Workspace source is owned by `frontend/`.
3. Mol* runs directly inside the frontend application.
4. No Mol* iframe is required.
5. Result Workspace can initialize from its URL and API calls without Jinja-injected task/result state.
6. OpenAPI/API schemas provide the authoritative frontend/backend contract.
7. Existing Result URLs remain usable or have a deliberate compatibility route.
8. Structure viewing works.
9. Structure switching works.
10. Artifact downloads work.
11. Fullscreen works and exits cleanly.
12. Files & diagnostics behaves correctly on desktop/tablet/mobile.
13. Collapsing the file panel returns space to the main workspace.
14. File-tree rows show local filenames rather than redundant full paths.
15. Result Manifest/artifact metadata drives preview selection where available.
16. Mol* contains no runner-specific branching.
17. Remaining legacy pages continue to work.
18. Same-origin authentication remains intact.
19. Production requires no runtime CDN for Mol*.
20. Frontend build/typecheck passes.
21. Backend tests pass.
22. Browser/full-stack contracts pass.
23. Obsolete iframe/viewer-shell code is removed after migration.
24. Architecture documentation describes the new Presentation/Control/Execution boundary.
25. No unrelated backend or runner architecture refactor is included.

---

# Review Rule

Before declaring the work finished, perform a dedicated review against the architectural invariant:

> The Result frontend must be replaceable without changing REvoCompute compute/control logic, and the backend must be refactorable internally without requiring the Result frontend to understand Python, Slurm, runner filesystem layout, or server implementation details.

Then perform a second review specifically for accidental legacy coupling:

- Jinja-injected application state;
- backend-generated presentation models;
- direct filesystem-path assumptions;
- runner-specific frontend branches;
- iframe/postMessage remnants;
- duplicated task/result semantics;
- runtime CDN dependencies;
- frontend handling of large artifact bytes.

Fix discovered violations before finalizing PR32.