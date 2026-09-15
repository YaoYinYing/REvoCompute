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

Continue Core content/format mismatch and complexity hardening, with behavior-level adversarial tests and no durable
side effects. Path policy now rejects Unix, Windows, UNC, Unicode-normalized, encoded, ambiguous, NUL, control, and
traversal attacks before quarantine writes.

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
- `python -m pytest tests/test_playwright_scalability.py::test_configuration_infrastructure_panel_and_refresh tests/test_playwright_scalability.py::test_configuration_tasktype_filter -q` — 2 passed.
- `python -m pytest tests/test_admin.py::test_configuration_page_script_initializes_theme_and_admin_data tests/test_browser_contracts.py::test_js_modules_load_in_correct_order -q` — 2 passed.
- Desktop (1440x1000) and mobile (390x844) Chromium screenshots of the Infrastructure tab — visually inspected; no clipping or overlap after responsive row stacking.
- `python -m pytest tests/server/test_infrastructure_readiness.py tests/server/test_preflight_boundary.py tests/test_tasks.py::test_public_api_docs_expose_the_client_openapi_contract -q` — 25 passed.
- `python -m pytest tests/server/test_infrastructure_readiness.py tests/server/test_preflight_boundary.py tests/test_runner_access_routes.py tests/server/test_operational_events.py tests/test_tasks.py -q` — 115 passed.
- `python -m pytest tests/server/test_infrastructure_readiness.py tests/server/test_preflight_boundary.py tests/test_runner_access_routes.py -q` — 40 passed after moving scheduler probes to worker-published evidence.
- `python -m pytest tests/test_tasks.py tests/server/test_operational_events.py tests/server/test_infrastructure_readiness.py tests/server/test_preflight_boundary.py tests/test_runner_access_routes.py -q` — 116 passed.
- `python -m pytest tests/test_playwright_scalability.py::test_failed_sequence_submission_does_not_leak_generated_file_into_retry -q` — 1 passed.
- `python -m pytest tests/server/test_infrastructure_readiness.py -q` — 18 passed after adding the non-allocating Slurm `srun --test-only` submission sanity probe.
- `python -m pytest tests/server/test_preflight_boundary.py -q` — 19 passed after adding adversarial path cases; the subsequent NUL policy case passed in the broader run.
- `python -m pytest tests/server/test_preflight_boundary.py tests/test_security.py tests/test_security_advanced.py tests/test_artifact_references.py -q` — 104 passed.
- `git diff --check` — clean.

## Known blockers

- None.
