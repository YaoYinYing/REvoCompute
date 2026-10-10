# Runner Family Protocol

Each family under `docker/runners/<family>/` owns its manifests, task contracts,
direct Apptainer definition, runtime script, `test.yaml`, and result handling.
The direct-SIF lifecycle is Doctor, build, live acceptance, receipt, and
promotion; scientific behavior remains family-owned and generic server code
must not branch on Runner names.

Runner freshness has four independent meanings. **Build Identity** covers the
definition and explicitly declared `runtime.build_inputs`; only a change there
makes a built SIF stale. **Runtime Bundle Identity** covers the repository-owned
executable code declared by `runtime.runtime_overlay`: a change keeps the SIF
current and invalidates its validation receipt, and is reported with
`reason=runtime_bundle_changed`. **Execution Contract Identity** covers parsed
Task and runtime behavior, expected results, effective resources, and live-test
coverage; changing it keeps the SIF but invalidates its validation receipt.
**Presentation Identity** covers user-visible metadata with no execution effect
and invalidates neither. The canonical examples and action matrix are in
[Adding a Runner](adding-a-runner.md#runner-change-impact-model); the runtime
bundle's own identity, pinning, and retention rules are in
[Runtime Bundles](runtime-bundles.md).

A PASS receipt binds the exact SIF, Runtime Bundle digest, and build provenance
to the current execution contract, `test.yaml` plus fixture contents, required
smoke cases, and execution account. A receipt produced for one bundle never
authorizes another. Build freshness is evaluated before receipt freshness, so
simultaneous build and execution changes report `BUILD_STALE`, not merely
`VALIDATION_STALE`.

A family whose Task may contain many independent work items additionally owns
the persistent runtime lifecycle, per-item commit, and resume semantics
described in [Persistent Execution](persistent-execution.md).


## Repository test ownership

The family owns executable tests under `tests/fast/` and pinned scientific
acceptance under `tests/scientific/`. Keep fake modules, references, goldens, and
regeneration utilities inside that family-root `tests/` namespace: deployment
materialization excludes it. Runtime/build assets must live outside it and be
explicitly declared in the manifest. The shared `docker/runner_testkit/` is a
sibling of the production Runner root and is never discovered as a plugin.

Run one family's fast contracts from the repository root:

```bash
python -m pytest -p docker.runner_testkit.pytest_plugin --import-mode=importlib \
  docker/runners/<family>/tests/fast
```

`make runner-fast` collects every family's fast directory. Scientific directories
are never imported by that command. Run scientific tests with the family's
locked dependencies and documented acceptance command; missing required
dependencies are failures, not optional skips. Generic Server protocol tests
use Server-owned synthetic fixtures, and shipped manifest projections are
separately named fleet tests. [Testing and CI](../developer-guide/testing.md)
owns lane and collection policy.
