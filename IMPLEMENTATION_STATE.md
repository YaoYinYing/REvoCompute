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
- [x] Add append-only, idempotent GPU-credit accounting and allocation-time enforcement.
- [x] Add user/admin GPU-credit APIs and UI, adjustments, and reconciliation.
- [x] Add the canonical CPU-only Example Runner and standard onboarding documentation.
- [ ] Complete security, failure/restart, Slurm GPU-accounting, and Example Runner live acceptance.

## Current phase

Phase 4 onboarding. Phase 0 observability, Phase 1 infrastructure readiness, the initial Phase 2 security-first
preflight boundary, and Phase 3 GPU credits are implemented. The canonical CPU-only Example Runner now exercises
plugin discovery, named FASTA input, a Task-owned parameter, execution, result views, expected files, and a
ResultStoryboard without external dependencies.

## Current action

Run the Example Runner through the target-host API, worker, Slurm, and Apptainer live-test path, inspect artifact
acceptance and ResultStoryboard rendering, and issue the exact receipt. The family passes Doctor, direct SIF build,
and `%test`; this sandbox cannot contact the Slurm controller.

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
- `python -m pytest tests/test_input_validation.py tests/server/inputs/test_formats.py tests/server/test_preflight_boundary.py -q` — 73 passed after removing the executable validator plugin hook.
- `mkdocs build --strict` — passed after updating the Core validator ownership documentation.
- `git diff --check` — clean.
- `python -m pytest tests/server/test_gpu_credits.py tests/test_schema_epoch.py tests/test_slurm_runner.py tests/test_workflow_composer.py -q` — 65 passed.
- `python -m pytest tests/test_tasks.py tests/server/test_preflight_boundary.py tests/server/test_operational_events.py -q` — 96 passed.
- `python -m pytest tests/server/test_gpu_credits.py tests/test_tasks.py::test_public_api_docs_expose_the_client_openapi_contract tests/test_admin.py::test_admin_can_list_users tests/test_auth.py::test_profile_page_requires_login -q` — 13 passed.
- `python -m pytest tests/test_playwright_runner_access.py::test_profile_renders_self_scoped_gpu_credit_ledger tests/test_playwright_runner_access.py::test_admin_applies_reasoned_gpu_credit_adjustment -q` — 2 passed in Chromium at mobile widths.
- `mkdocs build --strict` — passed after documenting the GPU credit API and UTC reset semantics.
- `python -m pytest tests/server/test_gpu_credits.py tests/server/test_preflight_boundary.py tests/test_admin.py tests/test_auth.py tests/test_tasks.py -q` — 200 passed.
- Desktop (1440x1000) and mobile (390x844) Chromium screenshots of the Profile GPU Credits panel — visually inspected; no clipping or overlap.
- `python -m pytest tests/server/test_gpu_credits.py tests/server/test_preflight_boundary.py tests/test_admin.py tests/test_auth.py tests/test_tasks.py tests/test_workflow_composer.py tests/test_slurm_runner.py tests/server/test_operational_events.py -q` — 267 passed after adding Slurm-backed GPU allocation reconciliation.
- `python -m json.tool revocompute/static/openapi.json` — passed after documenting the admin reconciliation API.
- `mkdocs build --strict` — passed after documenting authoritative settlement and review behavior.
- `git diff --check` — clean.
- `python -m pytest tests/server/test_gpu_credits.py tests/server/test_preflight_boundary.py tests/test_admin.py tests/test_runner_access_routes.py tests/test_workflow_composer.py tests/test_slurm_runner.py tests/test_schema_epoch.py -q` — 152 passed after adding the worker-readable GPU authorization projection.
- `python -m pytest tests/server/test_gpu_credits.py tests/server/test_preflight_boundary.py::test_gpu_preflight_reports_credit_without_consuming_it tests/test_admin.py::test_admin_can_enable_own_gpu_access_with_unchanged_role -q` — 22 passed after the final idempotent allocation retry adjustment.
- `mkdocs build --strict` — passed after documenting the allocation-time authorization boundary.
- `python -m py_compile revocompute/db.py revocompute/routes.py revocompute/task_runtime.py tests/server/test_gpu_credits.py` — passed.
- `git diff --check` — clean.
- `python -m pytest tests/server/test_gpu_credits.py tests/test_slurm_runner.py tests/test_workflow_composer.py tests/server/test_preflight_boundary.py tests/test_admin.py tests/test_runner_access_routes.py tests/test_schema_epoch.py -q` — 153 passed after adding allocation-time Runner readiness enforcement.
- `python -m pytest tests/runners/example/test_analyze.py -q` — 6 passed, including named-role and resolved-parameter Runner execution.
- `python -m pytest tests/test_doctor.py tests/test_live_test_protocol.py tests/test_result_storyboard.py tests/test_scientific_result_protocols.py -q` — 32 passed.
- `python -m revocompute doctor --config-root docker/runners --runner example --task sequence_statistics --strict` — passed with no diagnostics.
- Production plugin discovery plus expected-file and storyboard parsing for `sequence_statistics` — passed.
- `apptainer build /tmp/revocompute-example-v1.sif example/example.def` from `docker/runners/` — passed, including `%test`; SHA-256 `6d24415ee0e5ff1e2f000dff9371bb59f103b7efbf5ee9c810d118895b563937`.
- `apptainer inspect /tmp/revocompute-example-v1.sif` and independent `apptainer test /tmp/revocompute-example-v1.sif` — passed.
- `mkdocs build --strict` — passed after publishing the Example Runner-based 10-step onboarding path.
- `bash -n docker/runners/example/run.sh`, Python compilation, and `git diff --check` — passed.
- `make test-unit` — 972 passed, 5 skipped, and 36 browser tests deselected.

## Known blockers

- The current sandbox cannot contact the Slurm controller (`slurm_load_jobs: Unable to contact slurm controller`), so
  the Example Runner API/worker/Slurm live receipt and deployed artifact UI acceptance require target-host execution.
