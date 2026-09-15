# Platform Trust Implementation State

## Baseline

- Branch: `docs/platform-trust-plan`
- Design: `TODO.md`
- Delivery PR: <https://github.com/YaoYinYing/REvoCompute/pull/20>

## Completion checklist

- [ ] Add structured, privacy-safe operational events with request/Task/Celery/Slurm correlation.
- [ ] Add Core-owned infrastructure readiness probes, aggregation, API, and user/admin projections.
- [x] Put uploaded files through bounded Core quarantine and security validation before durable Task storage.
- [x] Make `/compute/api/preflight/{task_type}` and submission reuse one authoritative validation path.
- [ ] Add adversarial preflight and no-side-effect boundary coverage.
- [ ] Add append-only, idempotent GPU-credit accounting and allocation-time enforcement.
- [ ] Add user/admin GPU-credit APIs and UI, adjustments, and reconciliation.
- [ ] Add the canonical CPU-only Example Runner and standard onboarding documentation.
- [ ] Complete security, failure/restart, Slurm GPU-accounting, and Example Runner live acceptance.

## Current phase

Phase 1 infrastructure readiness. Phase 0 observability and the initial Phase 2 security-first preflight boundary are
implemented; hostile uploaded content is rejected from temporary quarantine before any durable blob, immutable
snapshot, Task row, or queue submission is created.

## Current action

Add the infrastructure readiness admin panel and project the safe grouped summary into user task surfaces. Real queue
and GPU capacity evidence remains separate follow-up work; the current API reports capacity as `UNKNOWN` when it has
no authoritative observation.

## Verification

- `python -m pytest tests/server/test_preflight_boundary.py tests/test_input_validation.py tests/server/inputs/test_typed_contract.py tests/test_artifact_references.py -q` — 68 passed.
- `python -m pytest tests/server/test_preflight_boundary.py tests/test_security.py -q` — 38 passed.
- `python -m pytest tests/server/test_preflight_boundary.py tests/test_input_validation.py tests/server/inputs/test_typed_contract.py tests/test_artifact_references.py tests/server/tools/test_api.py -q` — 79 passed.
- `python -m pytest tests/test_tasks.py tests/test_security.py tests/test_auth.py tests/test_runner_access_routes.py tests/server/test_preflight_boundary.py -q` — 187 passed.
- `python -m pytest tests/server/test_preflight_boundary.py tests/test_input_validation.py tests/test_tasks.py tests/test_runner_access_routes.py -q` — 143 passed.
- `mkdocs build --strict` — passed.
- `python -m pytest tests/server/test_operational_events.py tests/server/test_preflight_boundary.py tests/test_admin.py tests/test_log_rotation.py -q` — 53 passed.
- `python -m pytest tests/test_tasks.py tests/test_workflow_composer.py tests/test_slurm_runner.py tests/server/test_operational_events.py tests/server/test_preflight_boundary.py tests/test_admin.py tests/test_log_rotation.py -q` — 175 passed.
- `python -m pytest tests/test_tasks.py tests/test_workflow_composer.py tests/test_slurm_runner.py tests/test_scientific_result_protocols.py tests/server/test_operational_events.py -q` — 131 passed.
- `python -m pytest tests/server/test_infrastructure_readiness.py -q` — 13 passed.
- `python -m pytest tests/server/test_infrastructure_readiness.py tests/server/test_operational_events.py tests/server/test_preflight_boundary.py tests/test_admin.py tests/test_security.py tests/test_tasks.py -q` — 159 passed before the final four focused probe cases were added; the final focused readiness suite passed separately.
- `python -m json.tool revocompute/static/openapi.json` — passed.
- `mkdocs build --strict` — passed.
- `git diff --check` — clean.

## Known blockers

- None.
