# Frontend Runner Fixture Harness

## Objective

Make Runner-facing frontend development and browser acceptance independent of whether a real Runner is enabled, built, licensed, scheduled, or executable on the current host.

The temporary 309 deployment currently enables only PSSM-GREMLIN. That must not prevent us from developing and testing frontend behavior for the full REvoCompute Runner grammar.

The core principle is:

> **Run the real production frontend against deterministic canonical API fixtures; mock execution state, not product code.**

This work should turn the browser-test mocks that currently live inside `tests/test_playwright_application.py` into a small reusable frontend fixture harness.

It is **not** a fake REvoCompute server, a second Runner schema, a scientific acceptance framework, or a production mock mode.

---

# 0. Branch / Integration Preconditions

This PR is intentionally opened first as a planning PR containing only this `TODO.md`.

Before implementation:

- fetch current `origin/main`;
- inspect the status of the UI-polish PR that introduced the current Create Task flow;
- rebase this branch onto the latest merged `main` before modifying implementation code;
- do not recreate or partially cherry-pick unfinished UI-polish work;
- record the exact implementation starting SHA in `IMPLEMENTATION_STATE.md`;
- keep the final PR focused on frontend test infrastructure and browser acceptance.

If the UI-polish PR has not merged yet, work only on fixture infrastructure that does not conflict with it, or wait and rebase before changing affected browser expectations.

---

# 1. Read Before Editing

Read at minimum:

```text
CLAUDE.md
AGENTS.md
TODO.md
IMPLEMENTATION_STATE.md
tests/test_playwright_application.py
tests/server/test_application_frontend_contract.py
frontend/src/api/
frontend/src/app/
frontend/src/features/runners/
frontend/src/features/create-task/
frontend/src/features/dashboard/
frontend/src/features/results/
revocompute/task_types/
run/revocompute_ctl/live_test.py
docs/developer-guide/input-result-workspace.md
docs/developer-guide/architecture.md
```

Inspect the current Runner discovery and task-type projection path.

Understand which frontend fields come from:

```text
Runner/task manifests
        ↓
server canonical loaders
        ↓
TaskType/API projections
        ↓
production frontend
```

The harness must preserve this ownership model.

---

# 2. Hard Boundaries

Do not modify real Runner manifests merely to make frontend tests convenient.

Do not change:

- Runner scientific behavior;
- Runner validation identity;
- live-test receipt semantics;
- scheduler behavior;
- Slurm behavior;
- SIF/Apptainer execution;
- GPU requirements;
- database requirements;
- result scientific validation;
- production API contracts unless a genuine contract defect is discovered and separately justified.

In particular:

> **A frontend test must never require removing or rewriting an input-workspace capability across the Runner fleet.**

Do not introduce:

- production-only `MOCK_RUNNERS=true` modes;
- hidden mock HTTP endpoints in the production server;
- fake task types shipped to production;
- duplicate frontend-only Runner definitions;
- a second schema for TaskType, InputWorkspace, ParameterSchema, TaskStatus, or ResultManifest;
- a fixture JSON file for every Runner by default;
- scientific claims based on mocked execution.

---

# 3. What We Are Testing

The harness should make these frontend surfaces testable without real Runner execution:

```text
Runner Catalog
Runner Detail
Create Task
Task Snapshot
preflight states
Dashboard
task lifecycle
Result Workspace
artifact/file rail
access/readiness states
responsive behavior
error states
```

It should support realistic browser flows such as:

```text
Runner Catalog
→ Runner Detail
→ Create Task
→ validation/preflight
→ submit
→ queued
→ running
→ finished
→ Result Workspace
```

without requiring:

```text
GPU
Slurm allocation
Runner image
model weights
scientific database
network download
license-protected runtime
real compute
```

---

# 4. Keep the Production Frontend Real

The browser must load the same built frontend bundle used in production.

The harness may replace HTTP responses through Playwright routing, but must not replace frontend components with mock components.

Target architecture:

```text
production frontend bundle
          │
          ▼
canonical HTTP API boundary
          │
          ├── production → real REvoCompute server
          │
          └── browser tests → deterministic fixture router
```

The mocked boundary is the network/API projection, not the UI implementation.

---

# 5. Extract the Existing Playwright Mock Monolith

Current browser acceptance already contains useful pieces such as:

```text
_catalog()
_detail()
_task_summary()
_install_app()
mock preflight
mock submit
mock task list
mock running state
mock result manifest
```

Do not throw this away and design a large framework from scratch.

Refactor incrementally.

Create a small reusable support package, with a location chosen to fit existing test conventions. A reasonable direction is:

```text
tests/frontend_fixtures/
    __init__.py
    models.py
    builders.py
    router.py
    scenarios.py
    results.py
```

The exact file split is not mandatory. Prefer fewer files if the abstraction remains readable.

The important separation is:

```text
fixture data/builders
scenario state
Playwright route installation
tests/assertions
```

Do not leave a new 1000-line replacement for the old `_install_app()`.

---

# 6. Scenario Model

Introduce one lightweight scenario abstraction that can describe the frontend-visible state of a Runner workflow.

A scenario should be able to supply canonical payloads for at least:

```text
catalog
task-type detail
parameter schema
access state
infrastructure/readiness
preflight response
submit response
task list / task summary
running status
result manifest
archive/download state when relevant
```

A conceptual API may look like:

```python
scenario = RunnerScenario.sequence_cpu()
scenario = scenario.with_catalog_size(1)
scenario = scenario.with_readiness("READY")
scenario = scenario.with_preflight(valid=True)
scenario = scenario.with_lifecycle("queued", "running", "finished")
scenario = scenario.with_result("alignment_matrix")
mount_scenario(page, scenario)
```

This is illustrative, not a required exact API.

Favor immutable/simple builders or dataclasses over mutable global dictionaries.

Keep names obvious.

Avoid inheritance hierarchies.

---

# 7. Determinism

Fixtures must be deterministic.

Use fixed:

- task IDs;
- timestamps;
- usernames;
- task names;
- paths;
- result sizes;
- progress values;
- status transitions.

Do not introduce randomness unless a test explicitly controls its seed.

Do not make browser tests depend on wall-clock timing beyond bounded polling behavior that is itself under test.

---

# 8. Canonical Contract Ownership

The harness must not become a manually maintained copy of production schemas.

Where practical, construct fixture projections through existing canonical server loaders/serializers.

The preferred relationship is:

```text
real repository manifest
        ↓
canonical loader / projection
        ↓
frontend fixture payload
```

rather than:

```text
real manifest
        ╳
handwritten duplicate JSON contract
```

However, do not force every browser test to boot the full Flask application merely to build a small deterministic payload.

Use judgment:

- derive representative real projections where this protects against contract drift;
- use compact synthetic scenarios for frontend capability combinations;
- validate fixture payloads against canonical schemas/contracts where available.

The important rule is that fixtures must fail loudly when production contracts materially change.

---

# 9. Real-Manifest Projection Tests

Add focused tests that prove representative real Runner manifests can still project into the frontend contract even when those Runners are not enabled for execution.

Choose representative manifests based on frontend grammar, not popularity.

At minimum cover examples of:

- sequence input;
- molecular structure input;
- parameters;
- GPU metadata;
- restricted access if represented declaratively;
- multi-step input workspace;
- rich workflow metadata.

Do not execute the Runner.

Do not require its image, weights, databases, or GPU.

The test target is:

> manifest/discovery → canonical frontend projection

not:

> manifest → scientific execution

---

# 10. Capability-Oriented Fixtures

Prefer a small matrix of **frontend capabilities** over one fixture per Runner.

Create reusable representative scenarios for concepts such as:

```text
sequence input
file upload
molecular structure input
multiple files
parameter controls
restricted access
GPU method
multi-stage workflow
large catalog
single-method deployment
unavailable/not-configured Runner
preflight warning
preflight error
queued task
running task
failed task
successful task
structure result
table result
matrix result
alignment result
nested artifact tree
partial diagnostics
```

A real named Runner may be used where it clarifies intent, but the harness should not require maintaining 46 near-duplicate fixture files.

---

# 11. Runner Catalog Cardinality

Formalize the cardinality cases already useful during UI work.

Test at least:

```text
1 Runner
3 Runners
12+ Runners
```

Verify:

- layout remains intentional;
- category/filter behavior remains usable;
- density controls behave sensibly;
- one Runner does not create a pathological empty layout;
- large catalogs remain scannable;
- deployment availability is represented correctly.

These tests must not depend on the 309 deployment configuration.

---

# 12. Readiness and Availability Matrix

Allow the same Runner presentation to be exercised under different readiness states without changing its manifest.

Cover representative states that the API actually supports, for example:

```text
READY
NOT_CONFIGURED
BUILDING / INITIALIZING if supported
STALE
FAILED
DISABLED
capacity unavailable
```

Do not invent status enums.

Read the canonical API contract first and use only supported values.

Verify that the frontend:

- communicates the state;
- disables or redirects actions correctly;
- does not imply that an unavailable deployment means the method does not exist;
- keeps Runner Detail inspectable when appropriate.

---

# 13. Access-Control Scenarios

Support deterministic scenarios for:

```text
unrestricted Runner
restricted + granted
restricted + requestable
restricted + pending
restricted + denied/not granted
```

Use the real access projection shape.

Test browser behavior only.

Do not bypass server authorization logic in production code.

---

# 14. Input Workspace Scenarios

Exercise the frontend grammar through fixture projections.

Representative capability combinations should include:

```text
files
sequence editor
molecular structure
regions / residue selection where currently supported
parameters
review/snapshot capability when present in the canonical contract
external workspace plugin descriptors where relevant
```

Important:

> **The harness must tolerate canonical capabilities that are not rendered as a separate user step.**

For example, if the production UX consumes a terminal review capability into the Task Snapshot rather than presenting a second confirmation stage, the fixture should preserve the canonical capability while testing the intended UI presentation.

Do not mutate the Runner contract to match the UI.

---

# 15. Parameter Schema Scenarios

Provide representative JSON Schema fixtures or canonical projections for:

```text
integer
number
boolean
enum
string
optional/defaulted field
bounded numeric field
advanced/less-common parameters where supported
```

Test:

- defaults;
- validation messages;
- serialization into preflight;
- changes invalidating stale preflight state;
- responsive layout.

Do not build a second parameter-schema parser for tests.

---

# 16. Preflight Scenarios

Provide deterministic preflight outcomes:

```text
valid
valid + warnings
invalid security
invalid contract
runner not ready
infrastructure not ready
access denied
capacity unavailable
```

Use only combinations supported by the production response contract.

Verify that the frontend:

- submits automatically after a valid preflight when that is the current product behavior;
- does not submit after invalid preflight;
- surfaces actionable errors;
- handles warnings without inventing a second confirmation stage;
- prevents duplicate submit actions while busy.

The harness should make these states cheap to test.

---

# 17. Fake Execution Lifecycle

Implement a deterministic task lifecycle controller for browser tests.

A scenario should be able to progress through:

```text
POST /compute/api/post
        ↓
queued
        ↓
running
        ↓
finished
```

and alternative paths:

```text
queued → failed
running → failed
queued/running → canceled
```

Do not use sleep-heavy tests.

Advance state deterministically based on request count or explicit scenario control.

Keep task state transitions readable in test code.

---

# 18. ResultManifest Fixture Library

Result UI development must not depend on producing real scientific outputs.

Build a small canonical ResultManifest fixture library covering frontend rendering classes such as:

```text
empty/minimal successful result
text/log artifact
table
alignment
matrix
single structure
multiple ranked structures
structure + confidence metadata
trajectory if currently supported
nested artifact tree
large-file/download-only artifact
partial result
failed result + diagnostics
archive pending/ready
```

Use only ResultManifest/view types actually supported by the current code.

Do not invent future ResultManifest vocabulary just for tests.

Fixture artifacts may use tiny deterministic test files where a viewer genuinely requires bytes.

---

# 19. PSSM-GREMLIN as a Realistic Representative

Keep one realistic PSSM-GREMLIN frontend scenario because it is the currently enabled Runner on 309 and provides a useful bridge between fixture tests and real deployment testing.

Model representative frontend outputs such as:

```text
FASTA input
alignment
filtered alignment
PSSM artifact
GREMLIN/MRF artifact metadata
logs/files
downloads
```

Do not claim scientific correctness from these fixtures.

Real PSSM-GREMLIN acceptance remains a separate test with real execution.

---

# 20. Structure-Prediction Representative Scenario

Add at least one structure-oriented scenario that exercises frontend behavior unavailable in PSSM-GREMLIN.

It may be based on a current structure-prediction Runner contract such as AlphaFold3/Boltz/another existing method, but should be selected after inspecting current manifests.

Exercise:

```text
structure-related input/output
GPU metadata
result structure view
confidence/matrix view if currently supported
artifact downloads
```

No actual model inference is required.

Do not couple this test to model weights.

---

# 21. Network Router Abstraction

Extract Playwright `page.route(...)` setup into a reusable router.

A reasonable shape:

```python
router = FrontendFixtureRouter(page, scenario)
router.install()
```

The router should own endpoint fulfillment and request capture.

Tests should not need dozens of repeated `page.route` calls.

Keep route handlers close to the scenario data they consume.

Provide a clear failure for unexpected API requests where practical, while allowing expected static frontend assets.

Do not intercept unrelated external requests silently.

---

# 22. Request Observation

Provide simple helpers to assert:

```text
preflight requested
submit requested
task list requested
status polled
result manifest requested
archive requested
access request submitted
```

Prefer semantic helpers over manual:

```python
assert any("/compute/api/post" in url for url in requests)
```

everywhere.

Do not overbuild a custom assertion framework.

---

# 23. Authentication Fixture Support

Keep a small deterministic authentication projection for browser tests.

Support at least:

```text
anonymous
normal user
admin when an admin surface requires it
expired/401 session
```

Do not test authentication cryptography through this harness.

Server-side auth behavior remains covered by server tests.

The browser harness tests frontend reactions to canonical auth responses.

---

# 24. Static Frontend Harness

Preserve the useful behavior in the existing `_install_app()`:

- serve the real built frontend bundle;
- preserve CSP;
- preserve same-origin behavior;
- preserve route refresh support;
- capture browser requests.

Move it into a reusable helper with a name that describes its purpose.

Do not weaken CSP merely to make fixtures easier.

Do not load frontend assets from a CDN.

---

# 25. Keep Server Contract Tests Separate

Do not move server behavioral tests into the frontend fixture harness.

Maintain clear boundaries:

```text
server contract tests
    → real Flask/domain/API behavior

frontend fixture browser tests
    → real frontend + deterministic canonical API responses

Runner acceptance
    → real Runner execution and scientific/output validation
```

Each layer should fail for a different class of defect.

---

# 26. Scientific Acceptance Must Stay Real

Document this distinction explicitly.

Fixture tests may prove:

> Given this canonical API contract, the frontend renders and behaves correctly.

Fixture tests may **not** prove:

> The Runner executes correctly.

or:

> The scientific output is valid.

Never allow a fixture result to satisfy Runner live acceptance, scientific acceptance, or production-readiness evidence.

Do not write fixture-generated live-test receipts.

Do not update scientific validation identity from fixture execution.

---

# 27. Protect Live-Validation Identity

This work must not stale Runner acceptance evidence merely to improve browser tests.

Before finalizing, inspect:

```text
run/revocompute_ctl/live_test.py
validation configuration_digest
TaskType input_workspace projection
Runner manifests
```

Confirm that this PR does not unintentionally alter scientific/runtime validation identity.

If a change would invalidate receipts across the Runner fleet, stop and redesign the test harness instead.

---

# 28. Test Migration

After the reusable harness exists, migrate existing browser tests incrementally.

At minimum migrate the scattered helpers currently responsible for:

```text
catalog
detail
preflight
submit
task list
status
result
```

Do not rewrite unrelated auth/admin browser tests unless the harness clearly reduces duplication without obscuring intent.

A test should become easier to understand after migration.

Prefer:

```python
scenario = sequence_scenario()
mount_scenario(page, scenario)
```

over many pages of endpoint plumbing.

---

# 29. Required Browser Acceptance Cases

At minimum keep or add focused coverage for:

### Runner navigation

```text
Catalog → Runner Detail → Create Task
```

### Successful submission

```text
valid input
→ one user submit action
→ preflight
→ submit
→ Dashboard
```

Use the product behavior present in the implementation base after rebasing.

### Preflight failure

```text
valid local input
→ preflight invalid
→ no POST task submission
→ actionable UI state
```

### Running lifecycle

```text
queued → running
```

### Finished lifecycle

```text
running → finished → Results
```

### Failure lifecycle

```text
running → failed → diagnostics
```

### Access

```text
restricted Runner → request/pending/granted states
```

### Readiness

```text
ready vs unavailable/not configured
```

### Cardinality

```text
1 / few / many Runners
```

### Responsive

At least representative narrow-screen coverage for Runner Catalog, Create Task, Dashboard and Result Workspace.

---

# 30. Optional Visual Fixture Pages

Do **not** add a production Storybook-like application unless a clear need emerges.

The default solution should remain Playwright/browser acceptance.

If a lightweight local visual fixture launcher would materially improve development, it must:

- live entirely in test/development tooling;
- use the production frontend bundle;
- not ship routes or fixtures in production;
- not become a second frontend application;
- not require a real Runner runtime.

Treat this as optional, not a requirement.

Keep the first implementation small.

---

# 31. Performance and Test Runtime

The harness should make browser tests cheaper, not slower.

Avoid:

- starting containers per scenario;
- booting Slurm;
- building images;
- model downloads;
- real network access;
- long sleeps;
- repeated frontend builds inside individual tests.

Reuse the existing built asset fixture where appropriate.

Keep scenario payloads small.

---

# 32. Failure Diagnostics

When a fixture browser test fails, make the failure useful.

Where practical, preserve:

- Playwright trace/screenshot behavior already used by the repository;
- scenario name;
- unexpected API request information;
- current lifecycle state.

Do not dump secrets or large binary fixture payloads into logs.

---

# 33. Documentation

Add concise developer documentation explaining:

1. what frontend Runner fixtures are;
2. what they are not;
3. how to add a new capability scenario;
4. how to use a real Runner manifest as a projection source;
5. how to add a ResultManifest rendering fixture;
6. when a real Runner acceptance test is still required.

Prefer extending an existing frontend/developer testing document if an appropriate home exists.

Do not create broad new architecture documentation for a small test harness.

---

# 34. Implementation State

Update `IMPLEMENTATION_STATE.md` with:

```text
starting SHA
fixture harness architecture
migrated browser tests
representative real-manifest projection tests
scenario matrix
ResultManifest fixture coverage
test commands/results
known deferred cases
confirmation that Runner live-validation identity is unchanged
```

Keep it concise.

---

# 35. Validation

Run focused tests during development.

At minimum:

```bash
python -m pytest tests/test_playwright_application.py -v
python -m pytest tests/server/test_application_frontend_contract.py -v
```

Run frontend checks when frontend code or types are touched:

```bash
cd frontend
npm run typecheck
npm test
npm run build
```

Before final delivery follow the repository gates in `CLAUDE.md`, including applicable:

```bash
make test
make test-cov
make test-browser
```

Run broader/full-stack tests only where relevant to changed code.

The purpose of this PR is specifically to reduce dependence on unavailable Runner runtimes; do not declare the harness unsuccessful merely because 309 cannot execute GPU Runners.

If an environment-specific gate cannot run, record the exact limitation and the narrower evidence that passed.

---

# 36. Subtraction Pass

Before final review, delete obsolete test plumbing made redundant by the harness.

Look for:

- duplicate catalog builders;
- duplicate task-detail dictionaries;
- repeated route handlers;
- repeated request-capture logic;
- repeated lifecycle payloads;
- dead scenario helpers.

Do not keep both old and new fixture systems indefinitely.

Do not over-deduplicate tiny helpers when the result becomes harder to read.

---

# 37. Review Questions

Before opening the implementation for merge, answer:

- Can the full Runner-facing frontend be exercised on a host with only PSSM-GREMLIN enabled?
- Can a structure/GPU Runner UI be tested without its runtime image or weights?
- Are fixtures expressed in canonical API vocabulary?
- Is production frontend code unchanged by mock/test mode?
- Are real Runner manifests still the product/scientific source of truth?
- Did any Runner manifest change only for test convenience?
- Did any live-validation identity change?
- Are fixture tests clearly distinguished from scientific acceptance?
- Is adding a new UI capability scenario simple?
- Did the test file become easier to understand rather than merely more abstract?

Any concerning answer must be resolved before merge.

---

# 38. Definition of Done

This work is complete when:

- [ ] a reusable frontend Runner fixture harness exists;
- [ ] the production frontend bundle is used unchanged;
- [ ] no production mock mode or mock API endpoint was added;
- [ ] no real Runner needs to be enabled to test Runner-facing UI;
- [ ] fixture payloads use canonical contracts;
- [ ] representative real manifests can project into frontend contracts without execution;
- [ ] 1/few/many catalog states are covered;
- [ ] readiness states are covered;
- [ ] access states are covered;
- [ ] representative input-workspace capabilities are covered;
- [ ] valid/warning/invalid preflight states are covered;
- [ ] queued/running/finished/failed lifecycle states are covered;
- [ ] representative ResultManifest rendering classes are covered;
- [ ] PSSM-GREMLIN has one realistic frontend fixture scenario;
- [ ] at least one structure/GPU-oriented scenario exists without requiring model execution;
- [ ] existing browser tests use the reusable harness where it improves clarity;
- [ ] server contract tests remain separate;
- [ ] scientific Runner acceptance remains real and separate;
- [ ] no Runner validation identity was changed for test convenience;
- [ ] no live-test receipt is invalidated by the fixture architecture;
- [ ] required tests pass on the final HEAD;
- [ ] obsolete mock plumbing is removed;
- [ ] developer documentation explains how to extend the harness.

The final result should make this statement true:

> **Frontend development depends on canonical Runner contracts, not on whether the current machine can actually execute the Runner.**
