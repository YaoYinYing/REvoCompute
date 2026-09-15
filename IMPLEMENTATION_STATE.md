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

Phase 2 security-first preflight. Hostile uploaded content is now rejected from temporary quarantine before any
durable blob, immutable snapshot, Task row, or queue submission is created.

## Current action

Extend the established request/Task/Celery correlation through Slurm allocation, Runner stage, and manifest
publication events.

## Verification

- `python -m pytest tests/server/test_preflight_boundary.py tests/test_input_validation.py tests/server/inputs/test_typed_contract.py tests/test_artifact_references.py -q` — 68 passed.
- `python -m pytest tests/server/test_preflight_boundary.py tests/test_security.py -q` — 38 passed.
- `python -m pytest tests/server/test_preflight_boundary.py tests/test_input_validation.py tests/server/inputs/test_typed_contract.py tests/test_artifact_references.py tests/server/tools/test_api.py -q` — 79 passed.
- `python -m pytest tests/test_tasks.py tests/test_security.py tests/test_auth.py tests/test_runner_access_routes.py tests/server/test_preflight_boundary.py -q` — 187 passed.
- `python -m pytest tests/server/test_preflight_boundary.py tests/test_input_validation.py tests/test_tasks.py tests/test_runner_access_routes.py -q` — 143 passed.
- `mkdocs build --strict` — passed.
- `python -m pytest tests/server/test_operational_events.py tests/server/test_preflight_boundary.py tests/test_admin.py tests/test_log_rotation.py -q` — 53 passed.
- `python -m pytest tests/test_tasks.py tests/test_workflow_composer.py tests/test_slurm_runner.py tests/server/test_operational_events.py tests/server/test_preflight_boundary.py tests/test_admin.py tests/test_log_rotation.py -q` — 175 passed.
- `git diff --check` — clean.

## Known blockers

- None.
