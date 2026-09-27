# Runner Family Protocol

Each family under `docker/runners/<family>/` owns its manifests, task contracts,
direct Apptainer definition, runtime script, `test.yaml`, and result handling.
The direct-SIF lifecycle is Doctor, build, live acceptance, receipt, and
promotion; scientific behavior remains family-owned and generic server code
must not branch on Runner names.

Runner freshness has three independent meanings. **Build Identity** covers the
definition and explicitly declared `runtime.build_inputs`; only a change there
makes a built SIF stale. **Execution Contract Identity** covers parsed Task and
runtime behavior, expected results, effective resources, and live-test
coverage; changing it keeps the SIF but invalidates its validation receipt.
**Presentation Identity** covers user-visible metadata with no execution effect
and invalidates neither. The canonical examples and action matrix are in
[Adding a Runner](adding-a-runner.md#runner-change-impact-model).

A PASS receipt binds the exact SIF and build provenance to the current
execution contract, `test.yaml` plus fixture contents, required smoke cases,
and execution account. Build freshness is evaluated before receipt freshness,
so simultaneous build and execution changes report `BUILD_STALE`, not merely
`VALIDATION_STALE`.

A family whose Task may contain many independent work items additionally owns
the persistent runtime lifecycle, per-item commit, and resume semantics
described in [Persistent Execution](persistent-execution.md).
