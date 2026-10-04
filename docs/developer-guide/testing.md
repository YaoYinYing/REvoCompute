# Testing and CI

Server tests exercise REvoCompute-owned behavior with synthetic Runner fixtures.
Runner pytest tests belong under `tests/runners/<family>/` only when they execute
small Runner-owned parsers, adapters, or preparation logic. Cross-component
contracts belong under `tests/integration/`.

Do not pytest-test static YAML, Apptainer definitions, dependency pins, shell,
JavaScript, CSS, HTML, workflows, or documentation. Real parsers, linters,
builders, shell/JS syntax checks, and browser behavior remain valid gates.

`docker/runners/<family>/test.yaml` is an executable smoke/live plan, not a unit
test fixture. Smoke proves a candidate runtime can execute a representative
task; only target-host live acceptance can issue promotable receipts or prove
Runner readiness. Fewer pytest cases are expected when static assertions are
removed.

## Frontend Runner fixtures

Runner-facing browser tests must not depend on whether the current host can
enable, build, or execute a Runner. `tests/frontend_fixtures/` serves the built
production frontend bundle against deterministic canonical API responses, so
Runner Catalog, Create Task, Dashboard, and the Result Workspace can be driven
through a full lifecycle — catalog, detail, preflight, submit, queued, running,
finished, results — without an image, weights, database, scheduler, or GPU.

A fixture test proves one thing:

> Given this canonical API contract, the frontend renders and behaves correctly.

It never proves that a Runner executes, that a scientific output is valid, or
that a Runner is ready for deployment. Some specific limits:

- a fixture result is not a live-test receipt, and no scientific acceptance or
  readiness evidence may be derived from one;
- a fixture payload validated against OpenAPI proves schema conformance, not
  that the manifest it resembles behaves that way at runtime;
- fixture success never substitutes for smoke, live acceptance, or scientific
  validation, and it never licenses a manifest change made only to make a test
  convenient.

The mocked boundary is the HTTP/API projection. The frontend bundle, the
OpenAPI document, and the server loaders stay real, and no production mock mode
or mock endpoint exists.

The harness can drift from production in its payloads and in the handful of
status codes and redirect semantics it chooses (for example, a followed `302`
redirect is resolved by the browser's network stack rather than by a route
handler, so the submit fixture answers `202`). Every payload a builder returns
is validated against `revocompute/static/openapi.json`, so a body-level
contract change fails loudly; the router's own response shapes are not covered
by that check. `tests/test_frontend_fixture_harness.py` covers the harness.

### Adding a capability scenario

A scenario is an immutable value built from the capability builders in
`tests/frontend_fixtures/`. Add a new capability by composing existing ones
rather than by writing endpoint plumbing in a test:

```python
scenario = controlled_scenario().with_readiness("DEGRADED").with_preflight("runner_not_ready")
requests = mount_scenario(page, scenario).requests
```

- `models.py` defines the value objects (`InputRole`, `ParameterSpec`,
  `WorkspaceStep`, `ResultArtifactSpec`, …) and the capability-oriented
  scenarios live in `scenarios.py` (`controlled_scenario`, `pssm_gremlin_scenario`,
  `structure_scenario`, `runner_scenario`).
- Prefer a capability variant (`with_access`, `with_lifecycle`, `with_result`,
  `with_catalog`) over a new named scenario. Add a named scenario only when it
  represents a real Runner the product ships.
- Values are deterministic (fixed ids, timestamps, sizes, and status sequences)
  and lifecycle state is a pure function of the poll count, so tests use no
  sleeps and no randomness.

### Using a real Runner manifest as a projection source

When a payload must track a specific manifest, take it from the server's own
projection rather than handwriting a duplicate. `tests/server/test_runner_manifest_frontend_projection.py`
loads an isolated application through `conftest._load_pssm_module`, which
discovers the real `docker/runners/` tree exactly as production does, then reads
`/compute/api/types`, `/compute/api/types/<name>`, and
`/compute/api/task-parameters/<name>`. The tests assert on those projections and
validate them against OpenAPI.

This runs no Runner and requires no image, weights, or GPU. Reach for it when a
scenario must match a shipped manifest's roles, parameters, or input workspace;
reach for a synthetic scenario when the point is a frontend capability the
fleet does not happen to declare.

### Adding a ResultManifest rendering fixture

Result rendering classes live in `tests/frontend_fixtures/results.py`. Register
one with `_register`; `build_result_manifest` then produces the canonical
manifest, and `validate_manifest` plus
`tests/test_frontend_fixture_harness.py` keep it in the declared ResultManifest
vocabulary. Use only view plugins, artifact roles, and artifact capabilities the
OpenAPI document already declares; do not invent future vocabulary for a test.
When a viewer genuinely needs bytes, a fixture artifact may carry a tiny
deterministic body.

Mount one in a browser test with `scenario.with_result("<name>")`. Registering a
new fixture requires no test-file changes beyond the one that uses it; add the
name to the rendering-class coverage in `test_frontend_fixture_harness.py` when
it introduces a class the library did not have.

### Replaying a captured real Runner result

Synthetic fixtures answer "given this canonical contract, does the frontend
behave?" A **replay bundle** answers the complementary question: does the
frontend render the manifest and the artifact bytes a *real* Runner published?

A bundle is a test-only, sanitized capture of one completed result, served
through the same router at the captured task id. Capture it with
`frontend_fixtures.capture_replay_bundle(task_id=..., result_root=..., provenance=...)`
— it verifies the manifest's identity, resolves every payload inside the result
root, re-hashes each from disk, sanitizes secret-bearing metadata, and fails on
a required view source it cannot resolve. Bounded textual/scientific payloads
are checked in; a larger or binary artifact keeps its hash/size/provenance in
`excluded` with the reason, never a partial file. A bundle carries a pointer to
the machine-generated production receipt that proves the run, so its provenance
is the receipt's, not a second record.

Mount one in a browser test with
`replay_scenario(gremlin_lh_runner(), ReplayBundle.load(path))`; a mismatched
task id still resolves to 404. The checked-in GREMLIN_LH 2KL8 bundle lives under
`tests/data/gremlin_lh_replay/`, `tests/test_replay_bundle.py` covers the
round-trip and drift guarantees, and `tests/test_playwright_replay_gremlin.py`
drives the real frontend against it.

A replay bundle proves **frontend compatibility with authentic Runner output**.
It does not prove the science, and it is not an acceptance receipt: the
synthetic-fixture, real-result-replay, and scientific-reference claims remain
separate. [Live Testing and Receipts](../operator-guide/live-testing.md) owns
scientific acceptance.

### When a real Runner acceptance test is still required

A fixture test never replaces real execution. Use one when the question is how
the frontend behaves. Run the family's `docker/runners/<family>/test.yaml` plan
— SIF `%test`, Doctor, smoke, and target-host live acceptance — when the
question is any of:

- whether the Runner executes on its real runtime and produces its declared
  outputs;
- whether those outputs are scientifically valid;
- whether the deployed image, dependencies, weights, database, GPU, or network
  path actually work;
- whether a manifest change is safe to ship, or whether a Runner is ready for
  deployment or earns a promotable receipt.

Fixture evidence and acceptance evidence are not interchangeable, and
`run/revocompute_ctl/live_test.py` receipts must never be produced from a
fixture run. [Live Testing and Receipts](../operator-guide/live-testing.md)
owns the acceptance procedure.

## Local development

```bash
# Install in editable mode with test dependencies
pip install -e ".[test]"

# Run the server-owned non-Docker suite
make test

# Run the same coverage target used by server CI
make test-cov

# Run the server directly without Docker
python -m revocompute.app
```

Security regression checks for Docker socket exposure, admin self-lockout,
banned users, and login throttling belong to this suite. The controls those
checks protect are documented in
[Deployment security](../reference/security.md).
