# Authenticated Tool Runtime Implementation State

## Baseline

- Branch: `feat/authenticated-tool-runtime`
- Base: `d67683d94a1c1f133b5d37ffe81cd9f5b2365a3f` (`main` / `origin/main` at start).
- Existing user work in `TODO.md` is preserved.

## Delivered

- Independent typed Tool contracts and explicitly enabled family discovery under `docker/tools/`.
- Authenticated progressive catalog, parameter, asynchronous call, status, result, and typed-output APIs with no history endpoint.
- Separate SQLite `tool_calls` lifecycle store with strict IDs, atomic outstanding/storage admission, idempotency, ownership, TTL, and pressure cleanup.
- Immutable per-call input/output/scratch workspaces, named role binding, Task artifact authorization, Tool-output-to-Task durable snapshots, and provenance.
- Dedicated Celery `tools` queue/worker boundary; CPU-only, offline Apptainer execution with fixed mounts, fresh child processes, process-group timeout, and no user code/CLI passthrough.
- Lazy one-family warm instances with cross-process single-flight, health probing, circuit breaker, telemetry, idle shutdown, worker-generation reset, bounded redeploy drain, and graceful worker shutdown.
- Production `bioio` and `chemio` families with meaningful SIF `%test` checks and conservative scientific semantics; no PDBQT/preparation behavior.
- Controller snapshot/build/promotion support for explicitly enabled Tool families; Compose web/worker/tool-worker separation; Doctor and operator status CLI.
- OpenAPI, CLAUDE/AGENTS guidance, developer/operator documentation, environment examples, and behavior-focused tests.

## Verification

- Exact candidate SIFs rebuilt from checked-in definitions; both `%test` scripts passed.
- Exact-host acceptance passed all six Tools, cold/warm reuse, concurrent single-flight, fixed workspace exchange isolation, offline/thread checks, timeout recovery, idle shutdown/restart, and benchmark output.
- Acceptance measurements on this host: bioio first/warm `1.87s`/`0.58s`; chemio first/warm `1.68s`/`0.33s`; direct bioio exec `1.06s`.
- Full non-browser gate: `889 passed, 5 skipped`; coverage measured `82%`.
- Three restart subprocess tests exceeded their 90-second limits only under 16-way coverage contention and passed sequentially (`3 passed`).
- Focused Tool/API/runtime/controller gates are green; `git diff --check` and Python compilation are clean.
- Opt-in acceptance command: `REVOCOMPUTE_TOOL_ACCEPTANCE_IMAGE_DIR=<candidate-image-dir> python -m pytest tests/integration/test_tool_runtime_acceptance.py -q -s`.

## Remaining delivery gates

- Run browser and Docker full-stack smoke in an environment that permits Chromium namespaces and deployment containers.
- Push this branch and open (do not merge) `feat: add authenticated tool call runtime`.
