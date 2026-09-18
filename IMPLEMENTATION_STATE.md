# Platform Trust Implementation State

## Baseline

- Branch: `docs/platform-trust-plan`
- Design: `TODO.md`
- Delivery PR: <https://github.com/YaoYinYing/REvoCompute/pull/20>

## Completion checklist

- [x] Add structured, privacy-safe operational events with request/Task/Celery/Slurm correlation.
- [x] Add Core-owned infrastructure readiness probes, aggregation, API, and user/admin projections.
- [x] Put uploaded files through bounded Core quarantine and security validation before durable Task storage.
- [x] Make `/compute/api/preflight/{task_type}` and submission reuse one authoritative validation path.
- [x] Add adversarial preflight and no-side-effect boundary coverage.
- [x] Add append-only, idempotent GPU-credit accounting and allocation-time enforcement.
- [x] Add user/admin GPU-credit APIs and UI, adjustments, and reconciliation.
- [x] Add append-only, idempotent administrative GPU-credit reset for one user and for all current users.
- [x] Add the canonical CPU-only Example Runner and standard onboarding documentation.
- [x] Complete security, failure/restart, Slurm GPU-accounting, and Example Runner live acceptance.
- [x] Promote the prepared Runner deployment and verify it through the public API on the target host.

## Current phase

Phase 5 production acceptance. The shared preflight boundary enforces request, per-file, aggregate-byte, and file-count
limits while hashing uploads into bounded quarantine. Core format dispatch fails closed and covers every production
format. Each validator is classified as `safe_inprocess` or `isolated`; the third-party YAML parser runs through a
static Core worker with CPU, address-space, output-file, descriptor, timeout, environment, temporary-directory, and
Python-network restrictions. Timeout, OOM-like termination, protocol failure, and parser crashes fail validation.
Task-owned JSON logical types now select Core semantic profiles: AlphaFold 3 and OpenDDE prohibit external paths and
URLs, while Foundry accepts only confined references to separately uploaded assets. AlphaFold 3's upstream file-path
fields are rejected, and both JAAG builders emit the pinned upstream `dialect`/`version` shape before generated files
pass through the same preflight endpoint as uploads.

## Current action

No bot review or deployment is being triggered. The Example Runner now has target-host acceptance through API
submission, worker dispatch, Slurm job 4797, Apptainer execution, output validation, artifact download, and a signed
PASS receipt for the exact candidate SIF. Receipt contract version 2 requires completed resource evidence with elapsed
time, allocated CPU/GPU resources, CPU time, peak resident memory, and GPU memory/utilization for GPU cases,
invalidating older weaker receipts. GPU live cases also seed isolated authorization and credit, then require exact
Slurm allocation, settlement, ledger, and balance-delta evidence before issuing a PASS receipt. The remaining live GPU
acceptance is deferred while the target accelerator is occupied by another user's unlimited-duration production
molecular dynamics job. Because Slurm accounting storage is disabled on this cluster, GPU allocations now sample only
their Slurm-assigned devices through `nvidia-smi` and retain bounded peak memory/utilization evidence from a host-only
capture directory; the existing `sacct` accelerator metrics remain accepted when available. Production rollout remains
intentionally pending.

The submission boundary now quarantines and completes Core file security validation before invoking Runner-owned
workspace normalization or validation. The Compose full-stack gate also refreshes infrastructure evidence through the
admin API and seeds live-test evidence with the current receipt/scheduler identity contract.

## Review follow-up

The Platform Trust review comments are resolved in this branch:

- Core preflight no longer executes Runner-owned workspace normalizer/validator entrypoints at all. The read-only
  preflight endpoint performs declarative Core checks only, and a successful preflight proves zero Runner calls; Runner
  workspace semantics run during real Task preparation. The boundary tests now match the namespaced capability id, which
  the earlier weaker test did not.
- Infrastructure admission is resource-specific: CPU-only Slurm work depends on the scheduler/worker/storage path, and
  only GPU work additionally depends on GPU inventory. The global aggregate still drives the operator overview.
- The worker-readable GPU authorization projection now unions overlapping grants by effective expiry (indefinite wins,
  otherwise the longest valid expiry) instead of keeping whichever grant was iterated last.
- The multipart `workspace` document passes the same shared bounded Core JSON decoder (bytes/depth/nodes, fail-closed
  `RecursionError`) as an uploaded JSON file before Runner code can inspect it.
- A GPU settlement failure is isolated from the scientific outcome: the finish callback records review evidence and a
  `gpu.usage.settlement_failed` event, and never rewrites a completed Runner as a failed Task.
- Lost-finish recovery uses one best-effort `scontrol show job <jobid>` query with no `sacct`/SlurmDBD dependency;
  ambiguous evidence is marked `review`, never estimated.
- GPU capacity is derived from configured GRES minus allocated `GresUsed`, not from node state.
- Cross-month policy is explicit (whole allocation charged to its start month), and the Example Runner now ships a named
  contract test that newer families copy.
- Administrative GPU-credit reset is implemented for one user and for all current users. `delta = effective_monthly_allowance
  - current_remaining` is computed and appended as one `admin_reset` entry inside a single `BEGIN IMMEDIATE` transaction;
  usage and prior adjustments are untouched, per-user allowance overrides are respected, GPU permission is independent,
  zero-delta resets append a durable zero-value marker (hidden from the user's own history) so the idempotency key is
  reserved, and both operations reuse an idempotency key so retries do not duplicate entries.
  The global batch shares one `batch_id` embedded in the ledger idempotency key (no new column/migration).

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
- `python -m pytest tests/test_input_validation.py tests/server/inputs/test_formats.py tests/server/inputs/test_typed_contract.py tests/server/test_preflight_boundary.py -q` — 103 passed after fail-closed format coverage and bounded upload/parser checks.
- `python -m pytest tests/test_security.py tests/test_security_advanced.py tests/test_artifact_references.py -q` — 84 passed.
- Python compilation and `git diff --check` — passed; `ruff` is not installed in this environment.
- `make test-unit` — 992 passed, 5 skipped, and 36 browser tests deselected after the security-hardening changes.
- `mkdocs build --strict` — passed after documenting fail-closed formats and upload limits.
- `python -m pytest tests/server/test_preflight_boundary.py tests/server/test_operational_events.py -q` — 34 passed after tracing request-size rejection.
- `python -m pytest tests/server/inputs/test_parser_isolation.py tests/test_input_validation.py tests/server/inputs/test_formats.py tests/server/inputs/test_typed_contract.py tests/server/test_preflight_boundary.py -q` — 109 passed with isolated YAML parsing.
- `python -m pytest tests/test_input_validation.py tests/server/test_preflight_boundary.py -q` — 109 passed after adding task-specific JSON semantic profiles and generated-input boundary coverage.
- `node tests/js/test_contracts.js` — 64 passed, including both JAAG builders' AlphaFold 3 serialization contract.
- `python -m pytest tests/runners/alphafold3/test_runner.py tests/runners/foundry/test_runner.py tests/runners/opendde/test_opendde_protocol.py tests/test_plugin_discovery.py tests/test_doctor.py tests/test_browser_contracts.py -q` — 49 passed.
- `mkdocs build --strict`, Python compilation, and `git diff --check` — passed for the JSON-hardening checkpoint.
- `python -m pytest tests/test_input_validation.py tests/server/inputs/test_formats.py tests/server/test_preflight_boundary.py -q` — 124 passed after malformed mmCIF/SDF, hidden-path, and deterministic bounded-fuzz coverage.
- `python -m pytest tests/test_input_validation.py tests/server/inputs/test_formats.py tests/server/test_preflight_boundary.py tests/test_artifact_references.py tests/server/test_gpu_credits.py tests/test_slurm_runner.py -q` — 205 passed after hard-link, concurrency, and cancellation-settlement coverage.
- `python -m pytest tests/test_playwright_runner_access.py::test_admin_applies_reasoned_gpu_credit_adjustment -q` — passed in Chromium at 430px with the resulting-balance preview.
- `mkdocs build --strict`, JavaScript/Python syntax checks, and `git diff --check` — passed for the adversarial-security checkpoint.
- `python -m pytest tests/server/test_gpu_credits.py tests/test_tasks.py::test_public_api_docs_expose_the_client_openapi_contract -q` — 24 passed after adding immutable per-user monthly allowance policy.
- Two mobile Chromium GPU-credit admin workflows passed for resulting-balance preview and monthly-allowance updates.
- `make test-unit` — 1,030 passed, 5 skipped, and 37 browser tests deselected after all locally executable TODO work.
- `mkdocs build --strict`, OpenAPI JSON validation, and `git diff --check` — passed after the final documentation review.
- `python -m pytest tests/integration/test_example_runner_delivery.py -q` — passed through API submission, real Example
  Runner execution, Core output acceptance, and authenticated artifact download with only scheduler transport replaced.
- `python -m pytest tests/test_live_test_protocol.py tests/test_live_test_executor.py tests/test_runner_live_worker.py
  tests/test_workflow_composer.py tests/test_slurm_runner.py tests/server/test_gpu_credits.py
  tests/server/test_operational_events.py -q` — 119 passed after making GPU live receipts require exact accounting
  evidence and fixing GPU workflow authorization to use its owning runtime family.
- `make test-unit` — 1,035 passed, 5 skipped, and 37 browser tests deselected after the GPU workflow and live receipt
  accounting changes.
- `python -m pytest tests/test_live_test_protocol.py tests/test_live_test_executor.py tests/test_runner_live_worker.py
  tests/test_runner_readiness.py tests/test_restart_ctl.py tests/test_slurm_runner.py tests/server/test_gpu_credits.py -q`
  — 205 passed with versioned, fail-closed Slurm resource observations.
- `python -m pytest tests/test_live_test_protocol.py tests/test_live_test_executor.py tests/test_runner_live_worker.py
  tests/test_runner_readiness.py tests/test_restart_ctl.py tests/test_slurm_runner.py tests/server/test_gpu_credits.py -q`
  — 209 passed after adding the allocation-wrapper resource fallback and bounded terminal stdout envelope.
- `REVODESIGN_SERVER_ENV=.env.production.v7-slurm bash run/restart.sh live-test --runner example --collection smoke`
  — passed on the target host through Slurm job 4797 and Apptainer using candidate SIF SHA-256
  `947de01244f31d476022b42c22194d259e81ced0b3ba50df8ec9589599448ff8`; the receipt records 8 allocated CPUs,
  0.84 seconds elapsed, 0.71 seconds user CPU, 0.15 seconds system CPU, and 42,924 KiB peak RSS. The versioned report
  is `/mnt/data/srv/revodesign/server-slurm/images/live-tests/example/1789497278243513148-smoke.json`.
- `python -m pytest tests/test_live_test_protocol.py tests/test_live_test_executor.py tests/test_runner_live_worker.py
  tests/test_runner_readiness.py tests/test_restart_ctl.py tests/test_slurm_runner.py tests/server/test_gpu_credits.py -q`
  — 212 passed with bounded allocation-wrapper GPU memory/utilization observations and the `sacct` fallback.
- `make test-unit` — 1,045 passed, 5 skipped, and 37 browser tests deselected after allocation-wrapper GPU
  observation support.
- `python -m pytest tests/server/test_preflight_boundary.py tests/test_runner_readiness.py
  tests/test_live_test_protocol.py -q` — 80 passed after moving Runner-owned workspace code behind Core file security.
- `python -m pytest tests/test_full_stack_smoke.py tests/server/test_preflight_boundary.py -q` — 38 passed.
- `make test-docker-full-stack` — passed through authenticated infrastructure refresh, submission, Celery, mocked Slurm
  and Apptainer execution, result acceptance, ranged artifact download, and archive verification.
- `make test-unit` — 1,047 passed, 5 skipped, and 37 browser tests deselected after the preflight and full-stack fixes.
- Shell syntax and `git diff --check` — passed for the full-stack and preflight checkpoint.

## Known blockers

- Slurm accounting storage is disabled on the target cluster (`sacct` returns no rows), so receipts rely on the
  allocation wrapper's own bounded observations plus `scontrol` metadata. The wrapper fallback added here covers the
  GPU case; the `sacct` path is retained for clusters that enable accounting.

## Post-merge deployment checkpoint

Promoted the prepared deployment on 2026-09-17 (`restart --mode=prepared --keep-gateway`) onto commit `7666991` plus
this branch's fixes. All 27 enabled Runner families reported `READY` (Doctor PASS, current SIF, current live test)
before and after promotion, and all six Compose services (`redis`, `web`, `gateway`, `maintenance`, `worker`,
`tool-worker`) were running when the prepared restart completed. The deploy stamp records `mode=prepared`, 25 promoted
families, and no rebuilt server image beyond the one rebuilt below.

### Fixes

**Slurm GPU allocation receipts.** The cluster exports `CUDA_VISIBLE_DEVICES=0` but neither `SLURM_JOB_GPUS` nor
`SLURM_GPUS_ON_NODE`, so scientifically successful GPU jobs failed receipt validation with
`RESOURCE_OBSERVATION_FAILURE`. The shared Slurm wrapper now reads `SLURM_JOB_GPUS` when present and falls back to
`CUDA_VISIBLE_DEVICES`, derives the GPU count from the explicit Slurm value or from the comma-separated device IDs, and
preserves `NoDevFiles` handling. Evidence: `tests/test_slurm_runner.py::test_gpu_wrapper_samples_assigned_device_and_emits_resource_evidence`
exercises the fallback with only `CUDA_VISIBLE_DEVICES` set.

**Proxy forwarding for live-test image builds.** `live-test --use-proxy` was accepted but ignored while preparing the
one-off server image. `resolve_proxy_args` is now shared with `build`, resolved in the live-test command, and forwarded
through `run_live_tests` and `prepare_live_test_server_image` into `build_web_images`. Runtime output now confirms
`Using configured proxy for dependency downloads (credential redacted).` The behavior test is
`tests/test_runner_live_worker.py::test_live_test_refreshes_submission_attestations_after_receipt_update`.

**Pre-stop sweep against an already-stopped worker.** `pre-stop-sweep-slurm` ran unconditionally before
`docker compose stop`, so a partially-stopped or crashed deployment aborted the restart with
`service "worker" is not running` before any service was touched. The sweep now checks that the compute `worker`
container itself is running and skips when it is not; `tool-worker` deliberately does not count, since it can
neither see nor cancel compute jobs and `compose exec worker` would still abort the restart (boot-time orphan
recovery in `task_runtime` handles leftover records). Evidence:
`tests/test_restart_ctl.py::test_slurm_sweep_skips_when_no_worker_container_is_running` and
`::test_slurm_sweep_skips_when_only_tool_worker_is_running`.

**Infrastructure evidence pulse.** Scheduler/GPU probes run in the compute worker and publish to
`$SERVER_DIR/readiness/infrastructure.json`, but only the worker's boot-time `worker_ready` hook refreshed that
snapshot. Within one `INFRA_STALE_SECONDS` (60 s) of a restart every Slurm submission was refused with
`slurm_controller is unavailable or stale`. A new maintenance task (`infrastructure-probe`, interval
`INFRA_REFRESH_SECONDS`) now dispatches one probe pass through the worker, matching the documented
"automatic infrastructure probe pass". The job is registered regardless of the current `slurm_enabled` value and
re-reads that flag on every pulse, because an admin can enable SLURM through the configuration API without
restarting the maintenance process. Evidence:
`tests/test_maintenance_manager.py::test_infrastructure_probe_pulses_worker_evidence_on_a_slurm_deployment`,
`::test_infrastructure_probe_dispatches_while_slurm_is_enabled`, and
`::test_infrastructure_probe_stays_idle_while_slurm_is_disabled`.

### Public API acceptance

Server image rebuilt with `build --use-proxy --server-only` (proxy line confirmed above) and the prepared restart
rerun. `runner-status --all` reported all 27 enabled families `READY`. Both tasks below were submitted through
`https://revocompute.yaoyy.com`-equivalent `/compute/api/post` against the deployed gateway on `127.0.0.1:8081` with a
real Bearer session, and tracked through the public status, result, artifact, and input endpoints.

- CPU: `pythia_ddg`, task `1f1e07d85e92445d5e46719e59e46165`, Slurm job `4871`, `finished` in 23.3 s. Immutable input
  snapshot hash matches the submitted `tests/data/pdb/2KL8.pdb`
  (`035c78fb64880cfac5f721a1831ea45a54b453741fbbc4785d738be83c19c15e`). Receipt: 8 allocated CPUs, 1 task, exit 0,
  23.1 s elapsed, 22.6 s user CPU, 3.86 s system CPU, 496,388 KiB peak RSS. Primary artifact `2KL8_pred_mask.csv`
  downloaded through the authenticated endpoint with a matching SHA-256
  (`85fb6f251bbdbe1cb328b4173e876c0e982a041d29fa5611fa0342b1ada5c01b`).
- GPU: `esm_extract`, task `cef3bbf2d11d5c8b02f99e42feb8154e`, Slurm job `4913`, `finished` in ~24 s. Receipt proves
  the GPU-accounting fix: `gpus=1 ids=0 visible=0`, peak GPU memory 3,155 MiB, peak GPU utilization 70%. The credit
  ledger recorded allocation `settled` with 26 GPU-seconds and the matching append-only usage entry
  (`usage:4913`, `-26`). Primary artifact `2KL8.pt` downloaded with a matching SHA-256
  (`9aac9acb6dab94912792acddcf775d89a1706974e4629507ac0a8057a300421f`).

Infrastructure readiness reported `READY`, `stale: false` for scheduler, GPU, worker, and storage throughout the
acceptance window. The stale `server` Compose project from an earlier product revision was drained after its services
were confirmed to serve nothing; only the `server-slurm` project remains running.

### Gates

- `python -m pytest tests/test_maintenance_manager.py tests/server/test_infrastructure_readiness.py tests/test_restart_ctl.py -q`
  — 105 passed (includes the three new sweep/probe cases).
- `python -m pytest tests/test_live_test_protocol.py tests/test_live_test_executor.py tests/test_runner_live_worker.py
  tests/test_runner_readiness.py tests/test_restart_ctl.py tests/test_slurm_runner.py tests/server/test_gpu_credits.py -q`
  — 243 passed.
- `make test` and `make test-cov` — see the pull request description for the recorded results.
- Live: `live-test --runner frustrampnn --collection smoke --use-proxy` — PASS,
  `/mnt/data/srv/revodesign/server-slurm/images/live-tests/frustrampnn/1789687388426610392-smoke.json`.
