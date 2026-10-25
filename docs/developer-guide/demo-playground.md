# Demo Playground

The demo playground is an isolated REvoCompute deployment profile that serves
the canonical Task contracts and a curated set of recorded results to a browser
without installing a scientific runtime. It exists so a designer or an agent can
exercise the real shell, forms, and Result Workspace, then capture evidence of
what the browser actually did. It is not a second compute site.

This page covers the profile's trust model, its Preview and Replay surfaces, the
replay-bundle contract, the LCU runbook, and its limitations. The controller
commands that install it are in
[Demo Deployment](../operator-guide/demo-deployment.md).

## Purpose and scope

The playground supports an `observe → change → build → use the browser → capture
evidence → revise` loop on a host that has a display and browser automation but
no GPU, model weights, reference databases, or Slurm partition. It is a
foundation for that loop, not the Design Exploration Campaign that will use it.

The server remains the single source of truth. A demo deployment materializes
the same Runner family tree a production deployment does, so every Task
definition, input role, parameter, and declared demo input comes from the owning
manifests. The browser reads that registry through the ordinary
`/compute/api/types`, `/compute/api/task-parameters/<task_type>`, and
`/compute/api/types/<name>/demos` projections; the profile adds no alternate
Task catalog. It adds a projection and a replay source, never a second Task or
parameter registry.

## Product modes

| Mode | Truth source | What it proves | What it does not prove |
| --- | --- | --- | --- |
| **Preview** | Canonical `task.yaml` and `demos.yaml` data materialized from the enabled families | The catalog, method detail, form, typed input roles, parameter semantics, and validation behave as the browser contract says | That any Runner is installed, ready, or scientifically accepted here |
| **Replay** | A validated replay bundle carrying a served ResultManifest v3 and captured artifact bytes | The Result Workspace renders and pages authentic recorded output through its ordinary renderers | That this deployment executed anything, or that the recorded science is valid |
| **Live** | A local executor, Runner discovery, and an execution receipt | Host-specific execution evidence | Nothing applicable — **Live is absent in this profile** |

Live is not a hidden toggle. `REVOCOMPUTE_JOB_EXECUTOR=demo` is accepted only
together with `REVOCOMPUTE_DEMO_MODE=true`, and the controller treats the demo
profile as having no executor at all. It does not layer
`docker-compose.slurm.yml`, validate a SIF build definition, or materialize
Runtime Bundles. A deployment that needs Live is a different deployment.

## Trust boundaries and isolation

The profile is a deployment fact owned by the server, not a frontend flag.

- `GET /compute/api/environment` is the one profile fact the browser reads. A
  demo answers `demo_mode: true`, `execution: "preview_only"`, and a notice; a
  production deployment answers `demo_mode: false`, `execution: "available"`,
  and nothing else changes. A read that fails stays visible with a retry, but it
  does not gate the run control: the browser waits only while the read is in
  flight, and the form still submits. The `403` submission refusal below remains
  the boundary.
- `ENABLED_TASKRUNNERS` selects which families are materialized, advertised, and
  accepted. In the demo profile the selector decides only which Task
  definitions the browser can inspect; it grants no execution. An empty value
  selects every discovered family.
- Every execution surface is refused at the server, before it can create a row,
  workspace, or reservation, enqueue work, take a lease, purge data, or revoke
  a job. Read-only payloads -- the catalog, replay content, readiness reports,
  and result projections -- continue to answer.
- Task submission is refused at the one shared boundary
  (`_handle_submission`), before form parsing, validation, reservation, or
  charge. `POST /compute/api/post` answers `403` with the flat envelope
  `{"error": ..., "code": "demo_read_only", "valid": false}`, which creates no
  Task row.
  `POST /compute/api/preflight/<task_type>` projects that same refusal through
  the `TaskPreflightResult` model instead: `valid: false`,
  `admission.allowed: false`, and `errors[0].code: "demo_read_only"`. The
  preflight envelope has no top-level `code`.
- The same `403` / `code: "demo_read_only"` refusal guards the other execution
  surfaces (their flat envelope carries no `valid` field):

  | Surface | What the refusal prevents |
  | --- | --- |
  | `POST /compute/api/tools/<name>/call` | Tool workspace, reservation, ToolCall row, and queue message |
  | `POST /compute/api/auth/admin/infrastructure/refresh` | Readiness probe pass and its worker enqueue |
  | `POST /compute/api/auth/admin/gpu-credit/reconciliation` | Allocation reconciliation enqueue; the read-only `GET` still answers |
  | `POST /compute/api/cancel/<md5sum>` | Cancellation claim, `cancel_compute_resources` dispatch, Celery revoke, and artifact removal |
  | `POST /compute/api/results/<md5sum>/archive` | `build_results_archive` enqueue |
  | `DELETE /compute/api/delete/<md5sum>`, `POST /compute/api/delete` | Cleanup claim, artifact purge, reservation release, and Celery revoke |

  The refusal is decided from the deployment profile, not from whether the
  named Task, tool family, or image exists, so a crafted request to an unknown
  id is refused the same way.
- Admin accounting and policy writes answer the same `403` /
  `code: "demo_read_only"` before any ledger, allowance, reset, quota, or
  policy-audit row is written:

  | Surface | What the refusal prevents |
  | --- | --- |
  | `POST .../users/<id>/gpu-credit/adjustments` | GPU-credit adjustment entry |
  | `PUT .../users/<id>/gpu-credit/allowance` | Monthly-allowance change |
  | `POST .../users/<id>/gpu-credit/reset` | Per-user compensating reset entry |
  | `POST /compute/api/auth/admin/gpu-credit/reset` | Global reset batch |
  | `PUT .../users/<id>/storage-quota` | Durable-storage quota policy |

  Read-tier accounting and readiness GETs continue to answer, and user, access,
  and account management are unchanged.
- Two adjacent surfaces differ by design. The Admin Runner-operator action
  (`POST /compute/api/auth/admin/runners/<runner_family>/actions`) is refused by
  `OperatorService` with `409` and `This demo deployment is preview and replay
  only; Runner operations that change host or Task state are disabled.`; its
  read-tier status/doctor actions still answer. Operator-job cancellation
  (`POST /compute/api/auth/admin/operator/jobs/<job_id>/cancel`) only updates
  the job store and starts no host work, so it is not an execution surface.
- Worker passes repeat the refusal at each function boundary, not only in the
  boot caller. `_execute_compute_task` fails an inserted Task row without
  publishing a result or charging storage, and starts no Runner;
  `tool_runtime.execute_tool_call` fails a queued ToolCall
  before acquiring a runtime or touching its workspace;
  `_recover_orphaned_tasks` returns without failing, publishing, charging,
  re-enqueuing a workflow, or stopping a scheduler job; and
  `_reconcile_pending_storage_charges`, `_reconcile_slurm_allocations`, and
  `_reclaim_abandoned_reservations` return their zero outcomes before any
  ledger or reservation write. The pulse calls the pending-charge repair every
  cycle, so the guarantee holds when `_on_worker_ready` is not the caller. A
  database restored from another deployment is therefore never settled,
  charged, or re-enqueued by a demo worker.
- Leave `RESOURCE_MAINTENANCE_SECONDS` unset in a demo deployment (the default
  is 0, and `.env.demo.example` does not set it). The opt-in
  resource-maintenance pass would additionally run purge, purge-retry, and
  stale-reservation expiry through `resource_lifecycle.reconcile_resources`,
  outside the worker function guards above; enabling it in demo is not
  supported.
- Demo routes answer only while the deployment loaded a replay index. In a
  production process `GET /compute/api/demo/replays` and every scenario route
  return `404` and read nothing from disk. Production `/compute/api/types`
  semantics are unchanged.
- The demo owns its Compose project, state roots, auth database, Redis volume,
  port, and session key. It must never share a path, credential, cookie scope,
  or volume with a production deployment.

## Replay bundle sourcing and validation

A replay bundle is the repository's test-format capture of one completed
result: the served ResultManifest v3 plus the artifact bytes the renderers need,
with each payload re-hashed from its source. Its format, digest, payload
identity, and provenance rules are owned by `revocompute/replay_bundle.py`. The
demo module (`revocompute/demo.py`) is a consumer; it never reads a result
directory or invents a manifest.

The developer contract for a bundle is in
[Testing and CI](testing.md#replaying-a-captured-real-runner-result). The demo
adds a deployment-local index:

1. The tracked `demo/replays/index.json` (version 1) names curated scenarios.
   Each entry carries `id`, `title`, `summary`, `task_type`, and a `source`
   path inside `tests/data/`.
2. The controller copies only those source files into
   `SERVER_DIR/demo/replays/<id>.json`, writes a resolved index whose entries
   carry `bundle`, and validates the staging tree with the same loader the
   server uses. A source outside `tests/data/`, a path escape, an unreadable
   bundle, or a Task-type disagreement aborts the restart before the live tree
   is replaced. The staging tree replaces the live one atomically.
3. At startup in demo mode, `revocompute.app` loads and validates the installed
   index. An invalid index or bundle aborts startup rather than serving a
   partial catalog.

Validation is the canonical `load_bundle` contract: bundle version and kind,
recomputed digest, Task identity, OpenAPI conformance of the served manifest, a
`sha256` and size check for every captured payload against the manifest, every
required view source present, every logical-file identity resolvable, and no
undeclared host path.

### Provenance labels

The label is derived from what the capture itself recorded under
`provenance.capture.mode`; a caller cannot supply it.

| Capture record | Label kind | Browser label |
| --- | --- | --- |
| `reproduced_real_result` | `recorded_verified` | Recorded result · verified provenance |
| `synthetic` | `synthetic` | Synthetic scenario · labeled fixture |
| No recorded mode | `recorded_legacy` | Recorded result · legacy capture, provenance not machine-verified |

A `recorded_verified` bundle is accepted only when it also carries the capture's
own task source, manifest digest and size, and publication revision. A
`synthetic` bundle is an explicitly labeled stand-in, never a claim that a
Runner ran.

### What a scenario serves

A scenario's served manifest rewrites every route under the captured Task's
`/compute/api/results/<task_id>` prefix to
`/compute/api/demo/replays/<scenario_id>`. The demo therefore serves the
ResultManifest response, artifact and download bytes, logical-file bytes, paged
tables, and bounded numeric projections through demo-scoped routes:

| Route | Purpose |
| --- | --- |
| `GET /compute/api/demo/replays` | Scenario catalog with provenance and bundle digest |
| `GET /compute/api/demo/replays/<scenario_id>` | Served ResultManifest v3 |
| `GET .../artifacts/<path>` | Captured artifact bytes; `?download=1` sets the filename |
| `GET .../files/<file_id>?index=<n>` | Logical-file bytes resolved from the captured map |
| `GET .../tables/<path>` | Paged CSV/TSV with the server's offset and limit bounds |
| `GET .../ndarrays/<path>` | Bounded numeric projection of a captured array |
| `POST .../archive` | Always `409`; a recorded result cannot be re-archived |

A payload the bundle excluded is never fabricated. The artifact route answers
`404` with the path and the recorded reason, such as exceeding the per-file
payload budget or being binary or host-path-bearing text that was not checked
in. A missing or mismatched payload is a visible failure, not a blank success.

### No Storyboard execution

The demo replaces any declared Storyboard with `null` and appends the
limitation "Demo replay does not execute Storyboard code carried by a recorded
result." The Result Workspace renders the declared shared views instead. This is
the same trust decision as the
[Local Result Workspace](local-result-workspace.md): archived code is never
fetched, imported, or evaluated. An absent Storyboard renderer is a supported
limitation, not a defect to fix by executing the archive.

### Curated scenario index

The tracked index is authoritative; this table records its current contents.

| Scenario id | Task type | Provenance kind |
| --- | --- | --- |
| `gremlin-lh-couplings` | `gremlin_lh_fit` | `recorded_legacy` |
| `fpocket-pockets` | `fpocket` | `recorded_legacy` |
| `bioemu2-ensemble` | `bioemu2_equilibrium` | `recorded_verified` |
| `alphafold3-tiny` | `alphafold3` | `synthetic` |

Adding a scenario is an index change plus a checked-in bundle that passes the
capture and load contracts. It is not a reason to enable execution or to accept
an unrunnable fixture as a Task.

## LCU runbook

This runbook is the evidence procedure. A journey is evidence only when the
browser was actually observed; the commands below prepare that observation but
do not replace it.

1. **Identify the deployed revision.** Read the demo checkout's
   `config/.deploy-stamp` and compare its recorded commit and dirty flag with the
   revision under review. When no stamp exists, `git -C <demo checkout> rev-parse
   HEAD` identifies what a fresh `--mode=dev` restart would build; do not treat
   an unstamped checkout as the deployed revision.

   ```bash
   python -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("commit"), d.get("dirty"))' \
     "<demo checkout>/config/.deploy-stamp"
   ```

2. **Start the demo** with the controller commands in
   [Demo Deployment](../operator-guide/demo-deployment.md). Confirm the health
   and environment probes before opening a browser.

3. **Sign in with the demo account.** The profile's `ADMIN_USERS` account is
   created on the first start; its generated password is printed once by the
   controller. Keep it out of logs, screenshots, and the evidence record. The
   demo session authorizes the demo deployment only.

4. **Reserve the browser.** The Commander allocates one Chrome profile and tab
   as a lease. Do not let concurrent agents operate the same profile. End the
   lease after the bounded check.

5. **Run the three journeys.**

   - **Catalog → Task detail → demo input → validation.** Open the catalog, open
     a method, then preview its form and load a declared example. Confirm that
     typed input roles and parameters come from the task contract, that
     invalid input is reported, and that the run action is disabled and labeled
     as preview-only.
   - **Recorded result → view/metric → artifact.** Open **Demo playground** in
     the Compute navigation, open a recorded result, switch between declared
     views, page or inspect a metric or table as the manifest permits, and
     follow one artifact or download. Confirm the provenance label, the
     recorded-result identity, and that a missing payload reports its reason.
   - **Unavailable Runner → explicit preview → no submit.** Choose a method that
     is not executable here. Confirm the page states preview-only, the form
     still validates, and no submission is offered. An attempted direct submit
     is refused; no Task row, reservation, Slurm job, or charge appears.

6. **Capture evidence.** Record the viewport size, route, scenario id, source
   revision, interaction steps, and the observed behavior for each journey.
   Screenshots and reports stay outside Git. Redact account details and any
   proprietary input before sharing.

7. **Check the boundaries.** Repeat the three journeys at desktop and mobile
   widths, and check keyboard focus, accessible labels, dialog behavior, long
   content, error states, and the light/dark themes the shell supports.

A browser contract test can complement an LCU walkthrough, but it does not
replace it. LCU cannot substitute for backend security tests, and neither can
stand in for Runner scientific acceptance.

## Resource requirements

The profile needs Docker Compose and the server image build, a writable demo
state root, and a loopback port. It runs no GPU workload, no Apptainer build, no
SIF, no Slurm submission, and no model weights or reference databases. The
curated replay bundles are checked-in files; their per-file and total payload
budgets are enforced at capture time.

No measured CPU, host-memory, GPU-memory, disk, or startup-time figure has been
recorded for this profile in this page. During the first live deployment, record
effective usage with `docker stats` and `df` and store it with the deployment
evidence; do not publish an estimate as a measurement.

## Capability and scenario coverage

| Surface | Mode | Available here | Depends on real execution |
| --- | --- | --- | --- |
| Shell, catalog, Task detail | Preview | Yes | No |
| Create Task form, declared demo inputs, validation | Preview | Yes | No |
| Demo playground landing and provenance cards | Preview + Replay | Yes | No |
| Recorded Result Workspace (four curated scenarios) | Replay | Yes | No |
| Captured artifact, logical-file, table, and ndarray routes | Replay | When the bundle captured them | No |
| Local Result Workspace (`/compute/local_results`) | Browser-local, not a demo mode | Yes | No |
| Dashboard task history, quota ledger, live logs | Live | Empty or unavailable | Yes |
| Runner fleet readiness and live infrastructure probes | Live | Not meaningful without an executor | Yes |
| Submission, preflight, task lifecycle, Live Runner | Live | **Absent** | Yes |

The demo is a playground for the surfaces that do not require an execution
receipt. A page whose content is a real Task's lifecycle state is present as an
empty or explicitly unavailable surface, not as simulated data.

## Failure and rollback

- **Invalid replay content fails closed.** An unreadable index, an unsafe source
  path, a duplicate id, a tampered payload, or an OpenAPI-invalid manifest
  aborts `setup`/`restart` or server startup. The previous installed replay tree
  is not replaced unless the staged tree validates.
- **Replay content rollback.** Revert the intended change to
  `demo/replays/index.json` (and the bundle it names), then run `setup` and
  `restart`. Materialization is atomic; there is no partial tree to repair.
- **Deployment rollback.** Check out the previous revision in the demo checkout
  and restart in `--mode=dev`. The demo owns no durable state worth preserving
  across revisions other than its auth database.
- **State reset.** Stop the demo stack and remove only the demo-owned state
  roots named by its env file. Never remove a production path. Re-running
  `setup` recreates the materialized trees and the bootstrap account, and prints
  a new password once.
- **Ingress failure.** Probe the gateway on loopback before changing the tunnel
  or access policy. An ingress problem is not a reason to disable application
  authentication or to expose the origin.

## Limitations

- Live execution, task lifecycle, live logs, and real Runner readiness are not
  available. The profile is preview and replay only.
- The result catalog is the curated set. A result that is not captured cannot be
  opened, and an excluded payload is reported rather than retrieved.
- Replay proves frontend compatibility with authentic or labeled recorded
  output. It is not a scientific acceptance receipt and creates no target-host
  evidence.
- Storyboard code in a replay bundle is not executed; only declared shared views
  render.
- A replay bundle cannot build or download a result archive.
- The playground demonstrates the deployment and browser contract, not
  production data, production quotas, or production scheduling.
- The demo does not weaken `ENABLED_TASKRUNNERS`, Runner admission, input
  validation, authorization, or publication rules. It refuses execution at the
  boundary those rules would otherwise reach.

## Using the playground in a Design Exploration Campaign

A future Design Exploration Campaign can use this profile without changing its
trust model:

- Treat catalog and form work as **Preview**: change `task.yaml`,
  `demos.yaml`, or frontend presentation, rebuild, and exercise the real
  contract. The campaign does not invent parameter defaults or a second schema.
- Treat result work as **Replay**: add a validated bundle to the curated index
  when a new scientific shape is needed, and label synthetic scenarios
  explicitly. Do not add a fake Task or a forged Runner receipt to produce a
  screen.
- Keep every page's honest label: preview-only, recorded result, synthetic
  scenario, or unavailable. A design change that needs a real execution receipt
  belongs to a Live deployment and its acceptance procedure, not to this
  playground.
- Keep one browser lease per check and record evidence against the exact
  deployed revision. The campaign may change presentation and composition; it
  must not relax the submission refusal, the replay validation, or the
  Storyboard rule.
