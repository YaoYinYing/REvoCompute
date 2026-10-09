# TODO — Enforce Runner-owned test boundaries

## Goal

Make Runner test ownership match Runner code ownership.

After this PR, the REvoCompute Server must know **Runner protocols and behavior classes, not concrete production Runner identities**. A production Runner should carry its own fast contract tests, wrapper/adapter tests, artifacts/golden fixtures, and scientific acceptance tests under its own directory.

The architectural target is:

> Core knows the protocol, not the plugins.

and, specifically for tests:

> Server tests know Runner behavior classes, not Runner identities.

A useful deletion invariant is:

```bash
rm -rf docker/runners/<family>
```

Removing one production Runner must not make Server/Core tests fail merely because that family disappeared. Only Runner-fleet CI/discovery receipts for the removed family should change.

## Current problem

The root Server suite currently runs:

```bash
pytest tests/ -m "not browser"
```

That collection includes `tests/runners/**`. At the current baseline there are dozens of Runner-owned Python test files mixed into the Server coverage suite, including family-specific adapters, wrappers, fake inference paths, asset validation, artifact contracts, and scientific logic.

This causes several architectural and CI problems:

1. Server coverage owns tests for code under `docker/runners/<family>`.
2. Server test dependencies and collection can observe scientific Runner dependencies it should not own.
3. Runner-specific failures appear as generic Server/Core failures.
4. Some Runner paths are re-tested again in specialized acceptance jobs.
5. Server infrastructure tests sometimes borrow a real production Runner as a fixture, creating dependency inversion.
6. Registry/workflow tests can become slower merely because one production Runner gains more tests.
7. The CI classifier cannot cleanly reason about Server vs Runner ownership while both are collected by one root suite.

GREMLIN_LH makes the boundary especially visible: its upstream-equivalence test is already correctly executed in a pinned Runner scientific environment, yet the same source tree also lives under the root `tests/` namespace collected by Server coverage.

## Desired repository layout

### Server-owned tests

Keep root `tests/` for Server/Core, generic protocol, integration, browser, and synthetic-fixture tests only.

Target shape:

```text
tests/
├── server/
│   ├── auth / access / security
│   ├── api / task lifecycle
│   ├── resource / scheduler control plane
│   ├── storage / publication
│   ├── operator / maintenance
│   └── ...
├── contracts/
│   ├── runner_manifest
│   ├── task_context
│   ├── result_manifest
│   └── runner_protocol
├── integration/
│   ├── example_runner
│   ├── mock_gpu_runner
│   └── synthetic_multistage_runner
├── fixtures/
│   └── runners/
└── browser/
```

The exact subdirectory migration may be incremental; do not churn unrelated test files only for aesthetics. The important invariant is ownership, not forcing every existing Server test into a new path in this PR.

### Runner-owned tests

Each production Runner owns its tests beside its implementation:

```text
docker/runners/<family>/
├── runner.yaml
├── README.md
├── requirements.lock
├── run.sh
├── ...
└── tests/
    ├── test_runner.py
    ├── test_plugin.py
    ├── test_artifacts.py
    ├── fixtures/
    └── ...
```

A family with scientific/reference validation may additionally own:

```text
docker/runners/<family>/tests/
├── test_scientific_acceptance.py
├── fixtures/
├── references/
└── reference_generation/
```

Do not require every Runner to use every file name or layer.

## Test ownership classification

Do **not** blindly move every current `tests/runners/**` file.

Classify every test by what invariant it actually proves.

### A. Runner implementation tests → move to the Runner

Examples:

- family-specific parsing/normalization;
- adapter behavior;
- `run.sh` behavior;
- offline asset wiring;
- family-specific environment variables;
- family-specific parameter translation;
- expected output/artifact tree;
- negative cases specific to one tool;
- fake-model/fake-upstream execution;
- persistent-runner behavior owned by that family;
- scientific numerical behavior;
- upstream/reference equivalence;
- family-specific golden data.

These belong under:

```text
docker/runners/<family>/tests/
```

### B. Generic Server behavior currently tested through a real Runner → abstract back into Server tests

Examples:

- restricted Runner entitlement precedes resource admission;
- GPU admission is enforced before queue side effects;
- public catalog hides host mounts/entitlements;
- generic multistage workflow semantics;
- generic Runner manifest discovery;
- generic task input roles;
- canonical ResultManifest behavior;
- generic resource declarations/fallback plans;
- generic Runner readiness/admission.

These are Server-owned invariants even if the current regression happens to use AlphaFold3, SimpleFold, GREMLIN, or another real family.

Replace the production Runner with a purpose-built synthetic fixture such as:

```text
tests/fixtures/runners/example_cpu/
tests/fixtures/runners/example_gpu/
tests/fixtures/runners/example_restricted/
tests/fixtures/runners/example_multistage/
tests/fixtures/runners/example_result_contract/
tests/fixtures/runners/malformed/
```

Prefer extending the existing Example Runner / Mock GPU Runner fixtures over inventing redundant test-only families.

### C. Protocol conformance crossing the boundary → split responsibility

If a current test proves both:

1. Server correctly interprets a generic protocol feature; and
2. a concrete Runner correctly declares/implements that feature,

split it into two tests:

- Server side: synthetic fixture proves the protocol behavior;
- Runner side: family-local test proves that Runner's manifest/adapter conforms.

Do not preserve a cross-layer test merely because moving it wholesale is easier.

## Strong architecture invariant

Production Server/Core code and Server-owned tests must not contain family-specific behavior branches for production Runner identities.

Examples of suspicious patterns:

```python
if task_type == "alphafold3":
    ...

assert "simplefold" in ...
```

The correct Server abstraction is manifest/protocol capability, not family name.

There can be bounded exceptions for:

- migration/legacy compatibility that is explicitly documented and tested;
- user-facing static documentation/catalog snapshots where the purpose is fleet enumeration;
- Runner-fleet tooling whose job is intentionally to enumerate installed families.

Do not silently grandfather arbitrary existing literals.

## Add a machine-verifiable boundary gate

Add an architecture check that prevents family-specific coupling from returning.

The gate should:

1. discover concrete production Runner family IDs from the production Runner manifests;
2. inspect Server/Core production modules and Server-owned test paths;
3. fail on prohibited hard-coded family dependencies outside an explicit, narrow allowlist;
4. report path + family ID + reason;
5. fail closed for new unexplained exceptions.

Avoid a naive substring grep that produces uncontrolled false positives. Prefer syntax-/token-aware inspection where practical, or a deliberately constrained textual scanner with documented exclusions.

The gate must not forbid generic filesystem discovery of `docker/runners`; it forbids Server semantics that depend on a concrete family identity.

## Shared Runner test support

Current family tests may depend on helpers currently living under root `tests/`, for example Runner protocol helpers.

Move shared Runner-test-only helpers to a neutral Runner-owned support location, for example:

```text
docker/runners/_testkit/
```

or another clearly non-production-family namespace.

Requirements:

- Server tests do not import Runner testkit code.
- Runner tests may import generic protocol/result helpers from the testkit.
- The testkit must not become a second Server implementation.
- Keep helpers small and protocol-oriented.
- Do not place family-specific business logic in the shared testkit.

If a helper is actually a generic Server contract helper, keep it in Server tests instead.

## Fixtures and reference data

Move family-owned fixture/reference data with the Runner when practical.

Examples:

- GREMLIN_LH scientific reference JSON;
- upstream/reference generation utilities;
- family-only fake Python modules;
- family-only tiny inputs;
- family-specific expected artifact trees.

Keep shared biological/structural fixtures in a neutral shared test-data area only when multiple unrelated Runner/Server tests genuinely consume the same immutable fixture.

Do not duplicate large fixture data merely to satisfy directory aesthetics.

Every scientific reference must retain its existing provenance, hashes, pinned upstream version/commit, tolerances, and regeneration instructions.

## CI ownership

### 1. Server test job must stop collecting production Runner tests

The Server coverage target must explicitly collect Server-owned paths and must not recurse into:

```text
docker/runners/*/tests
```

A Server test command must remain valid when all production Runner test directories are absent.

### 2. Add a Runner fast-contract gate

Create a separate Runner-owned CI lane for fast tests that do not require full scientific model stacks.

The first implementation may use a simple generic collector over Runner test directories rather than an elaborate dynamic control plane.

Requirements:

- failures identify the Runner family;
- generic fast Runner tests do not execute inside Server coverage;
- no GPU, model weights, databases, or external network are required unless explicitly part of a specialized acceptance lane;
- missing optional scientific dependencies must not silently turn required fast-contract coverage into skips.

A family test that needs its pinned scientific stack belongs in scientific acceptance instead.

### 3. Scientific acceptance stays family-owned and pinned

GREMLIN_LH upstream equivalence is the current exemplar.

Keep its scientific acceptance isolated from Server dependencies and execute it using the Runner-owned pinned environment.

Move the test/reference files under the GREMLIN_LH Runner, preserving scientific behavior and provenance byte-for-byte unless path changes require bounded updates.

Do not weaken numerical tolerances to simplify migration.

The generic CI label may remain `RunnerScientificAcceptance`, but the implementation should make clear which family/case failed.

### 4. Registry determinism must not execute a real Runner's whole test file

The current registry determinism gate directly includes a production AlphaFold3 Runner test file.

Replace that dependency with a synthetic multistage/workflow fixture that proves the same Server registry/workflow invariant.

AlphaFold3's own tests stay family-owned.

### 5. Preserve aggregate merge semantics

Do not weaken required validation while separating ownership.

A PR touching Server/Core should still receive all required Server gates.

A PR touching a Runner should receive the relevant Runner contract/scientific gates plus any generic protocol integration required by the change.

This PR does **not** need to implement #69's full semantic CI classifier. Keep selection conservative and fail broad for unknown/global changes.

## Coverage semantics

Server coverage should measure Server code:

```text
--cov=revocompute
```

using Server-owned tests.

Do not rely on production Runner tests to inflate or fill Server coverage.

Runner coverage is Runner-owned and optional by implementation type. Shell-heavy/scientific Runners should be judged primarily by executable contract, artifact completeness, negative cases, and scientific/reference acceptance rather than one global percentage target.

If moving tests exposes previously hidden Server coverage gaps, add Server-owned protocol tests rather than putting Runner tests back into the Server suite.

## Test markers

Introduce/standardize only the markers necessary to express ownership and cost, for example:

- `runner_contract`
- `scientific_acceptance`
- existing `browser`

Avoid marker proliferation when directory ownership already expresses the same fact.

A test must not be both Server coverage and family scientific acceptance merely to keep historical execution counts unchanged.

## Migration inventory

Before moving files, create an inventory table in the PR discussion or implementation notes with at least:

- current test path;
- production code under test;
- ownership classification: Server / Runner / split;
- destination;
- dependency requirements;
- fixture/reference data moved;
- CI lane after migration.

Review every current `tests/runners/**` family.

Pay special attention to mixed-layer files such as AlphaFold3 tests that combine family wrapper behavior with Server entitlement/admission behavior.

## Required acceptance tests

### Deletion invariant

Create a test fixture or bounded validation proving Server tests do not require concrete production Runner identities.

At minimum:

- Server protocol/discovery tests run against synthetic fixtures;
- no Server-owned test imports files from a production family test directory;
- deleting/excluding one production Runner test directory does not break Server collection.

Do not literally delete production Runner code in normal CI if that would make fleet enumeration intentionally fail; use a controlled isolated fixture/root where appropriate.

### Collection invariant

Provide a collection receipt showing:

- Server test collection count and paths;
- Runner fast-contract collection count/families;
- scientific acceptance collection count/families;
- zero production Runner tests in the Server suite.

Fail CI if a test under `docker/runners/<family>/tests` is accidentally recollected by the Server job.

### Dependency invariant

Server test environment must not install a Runner's pinned scientific stack merely to collect Server tests.

Runner scientific dependencies remain confined to their Runner acceptance lane.

### No-skip masking

A required Runner contract must not be considered covered merely because `pytest.importorskip(...)` skipped it in the Server environment.

After migration, required Runner fast/scientific tests must run in the lane that owns the needed dependencies or fail explicitly.

### Architecture invariant

Add regressions proving:

- Server generic restricted-access behavior uses a synthetic restricted Runner;
- Server multistage/workflow behavior uses a synthetic staged Runner;
- Server registry determinism does not import/execute a production Runner's test module;
- production Runner family IDs cannot be newly hard-coded into Core/Server tests without an explicit exception.

## Preserve scientific correctness

This is an ownership/refactoring PR, not a scientific rewrite.

For moved scientific tests:

- preserve algorithms;
- preserve reference values;
- preserve seeds;
- preserve tolerances;
- preserve upstream pins/hashes;
- preserve artifact assertions;
- preserve intentional documented deviations.

Path-only changes must not regenerate scientific goldens.

Any changed scientific expected value is out of scope unless independently justified as a separate bug fix.

## Preserve Runner Protocol behavior

Do not change the production Runner Protocol merely to make the move easier.

If migration reveals that Server tests depended on family-specific behavior because the protocol lacks an abstraction, document that gap and make the smallest generic protocol correction only if strictly necessary.

Do not add family-name branches to Core.

## Relationship to active PRs

This PR is independent of the #70 Slurm race hotfix and must not modify that defect.

It is also independent of #57 MCP semantics.

#69 may later consume the cleaner Server/Runner CI boundaries for semantic lane selection. Do not duplicate #69's campaign state machine, drift classifier, liaison bus, or heavy-work lease work here.

If main advances through #70/#57 during implementation, reconcile normally and re-run exact-head evidence.

## Explicit non-goals

Do not use this PR to:

- optimize password KDF tests;
- redesign `_load_pssm_module()` fixture bootstrapping;
- perform general Server test sharding for latency;
- rewrite all root test directory organization;
- modify product UI;
- modify scheduler/resource accounting;
- change scientific algorithms;
- add new Runners;
- remove production Runners;
- build a generalized CI orchestration framework;
- implement #69's selective-lane classifier.

Those are follow-ups once ownership boundaries are correct.

## Validation

At minimum, provide exact-head evidence for:

1. Server/Core test suite passing with production Runner tests excluded;
2. Runner fast-contract suite passing;
3. GREMLIN_LH upstream scientific equivalence passing in its pinned environment;
4. Browser contracts unchanged where applicable;
5. Server Compose/full-stack contract unchanged;
6. registry determinism using synthetic Runner fixtures;
7. architecture boundary gate passing;
8. test collection receipt proving no ownership overlap;
9. `mkdocs build --strict` if documentation is updated;
10. full required GitHub CI green.

Record durations for the old Server coverage job and the new Server/Runner lanes. Performance improvement is expected but correctness/ownership is the merge criterion.

## Review focus

Fresh merge-grade review must specifically verify:

- no Runner-specific scientific/adapter test remains owned by root Server collection;
- no Server invariant was accidentally moved into a Runner and thereby weakened;
- mixed tests were split at the correct abstraction boundary;
- Server fixtures are synthetic rather than aliases/copies of production families;
- Runner-local tests remain runnable in isolation;
- scientific references retained provenance and tolerance;
- no family-specific Core branch was introduced;
- CI has not converted required tests into skips;
- Server coverage remains meaningful after Runner tests are removed.

## Completion

Before final review:

- update the Runner development/protocol documentation with the test ownership rule and expected `tests/` layout;
- document how a new Runner developer/agent runs that Runner's tests locally;
- document which CI lane owns fast vs scientific validation;
- remove this `TODO.md`;
- freeze the exact final head;
- return exact-head CI/collection/scientific evidence.

Do not merge. Maintainer final squash-merge authority remains unchanged.
