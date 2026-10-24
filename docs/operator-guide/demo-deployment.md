# Demo Deployment

This page is the controller workflow for an isolated demo playground: a
preview-and-replay deployment that owns its own project, state, auth database,
port, and session key. It deliberately does not describe a production
deployment, and none of its commands may point at production paths or
credentials. The profile's trust model and browser runbook are in
[Demo Playground](../developer-guide/demo-playground.md).

## Prerequisites

- A checkout or isolated worktree of the revision under test, and Docker
  Compose. No GPU, Apptainer, SIF, Slurm client, or scientific weights are
  required.
- A writable parent directory for demo-owned state, outside the checkout.
- A non-root service account that resolves on the host for `RUNNER_USERNAME`
  and `RUNNER_GROUP`, as in
  [Configuration and Service Identity](configuration.md#identity-contract).
- For a public hostname, the ingress prerequisites below. DNS, Tunnel, Access
  policy, and any TLS material are maintainer-owned and are not configured by
  this repository.

The tracked `.env.demo.example` is the starting surface. The full environment
reference remains [Configuration and Service Identity](configuration.md); this
page does not repeat it.

## Create the environment file

Copy the example outside the checkout and make it owner-only before it receives
generated secrets:

```bash
mkdir -p /srv/revocompute-demo
cp .env.demo.example /srv/revocompute-demo/.env.demo
chmod 0600 /srv/revocompute-demo/.env.demo
export REVODESIGN_SERVER_ENV=/srv/revocompute-demo/.env.demo
test "$(stat -c '%a' "$REVODESIGN_SERVER_ENV")" = 600
```

Edit the file for this host. Every dedicated value below is required; a value
shared with another deployment is a defect.

| Setting | Demo requirement |
| --- | --- |
| `COMPOSE_PROJECT_NAME` | Its own project name, distinct from every other stack |
| `SERVER_IMAGE` | Its own server image name |
| `SERVER_DIR` | Its own state root; never a production state root |
| `LOG_DIR` | Its own log root |
| `AUTH_DIR` | Its own auth root, a sibling of `SERVER_DIR` and never inside it |
| `PORT` | Its own port, distinct from production |
| `GATEWAY_BIND` | `127.0.0.1` unless a proxy on another interface terminates the connection |
| `SERVER_BASE_URL` | The origin actually used to reach the gateway |
| `ADMIN_USERS` | The demo account only; its password is generated on first start |
| `ENABLE_REGISTER` | `false` for a private playground |
| `REVOCOMPUTE_DEMO_MODE` | `true` |
| `REVOCOMPUTE_JOB_EXECUTOR` | `demo` |
| `ENABLED_TASKRUNNERS` | Empty to preview every discovered family; a comma-separated list to narrow the preview |

`REVOCOMPUTE_JOB_EXECUTOR=demo` is rejected unless `REVOCOMPUTE_DEMO_MODE=true`,
and a demo deployment cannot keep the default Slurm executor, so a mistyped
executor cannot turn a production deployment into a preview-only one.

Leave `RESOURCE_MAINTENANCE_SECONDS` unset (the default is 0, and
`.env.demo.example` does not set it). The opt-in resource-maintenance pass is not
supported in the demo profile: enabling it would additionally run purge,
purge-retry, and stale-reservation expiry through
`resource_lifecycle.reconcile_resources`, outside the worker's demo function
guards.

## Initialize and start

```bash
REVODESIGN_SERVER_ENV=/srv/revocompute-demo/.env.demo bash run/restart.sh setup
REVODESIGN_SERVER_ENV=/srv/revocompute-demo/.env.demo bash run/restart.sh restart --mode=dev
```

`setup` tightens the env file, generates `REDIS_PASSWORD` and
`AUTH_SECRET_KEY` into it, materializes the enabled Runner family manifests and
Tool families, installs and validates the curated replay bundles, and prints the
bootstrap administrator's generated password once. A missing or invalid replay
bundle aborts before services start.

`restart --mode=dev` builds the server images locally and starts the Compose
stack. Because the profile has no executor, the controller does not layer
`docker-compose.slurm.yml`, does not validate SIF definitions, and does not
materialize Runtime Bundles. The completion banner states that this deployment
executes no Tasks.

Keep the generated password out of shell history, logs, commits, and evidence.
Use `restart.sh reset-passwd <username>` if it is lost.

## Probes after start

Run these on the host before attaching any ingress. `/compute/health` and
`/compute/api/environment` are public; the readiness report and every replay
route require a credential.

```bash
PORT=8082  # the candidate port; use the demo env file's value
BASE="http://127.0.0.1:${PORT}"
DEMO_ADMIN_USER=demo-admin  # the demo env file's ADMIN_USERS value

# Liveness and the public deployment profile.
curl -sS "$BASE/compute/health"            # 200, empty body
curl -sS "$BASE/compute/api/environment"

# The readiness report and replay catalog are signed-in APIs: exchange the demo
# admin password for a short-lived Bearer token. The generated bootstrap and
# reset-passwd secrets are 32 hex characters, so the JSON body needs no escaping.
read -rsp "demo admin password: " DEMO_ADMIN_PASSWORD; echo
TOKEN=$(curl -sS -X POST -H "Content-Type: application/json" \
  --data "{\"username\":\"${DEMO_ADMIN_USER}\",\"password\":\"${DEMO_ADMIN_PASSWORD}\"}" \
  "$BASE/compute/api/auth/login" | python3 -c 'import json, sys; print(json.load(sys.stdin)["token"])')
unset DEMO_ADMIN_PASSWORD

curl -sS -H "Authorization: Bearer ${TOKEN}" "$BASE/compute/api/infrastructure"
curl -sS -H "Authorization: Bearer ${TOKEN}" "$BASE/compute/api/demo/replays"
```

The expected observations, from the code, are:

- health is a liveness probe: `200` with an empty body, not a readiness answer;
- environment reports `demo_mode: true`, `execution: "preview_only"`, and the
  preview notice;
- infrastructure is the server's readiness report, the same signed-in endpoint
  the Admin readiness view reads. A demo has no execution components, so do not
  expect it to be submission-ready; record the component state it reports;
- the replay catalog is `version: 1` plus one entry per installed scenario. Each
  entry carries `id`, `title`, `summary`, `task_type`, a `provenance` object
  (`kind`, `label`, `capture_source`), a `bundle_digest` starting `sha256:`, and
  the captured `task` identity (`id`, `type`, `display_name`).

Record the actual responses with the deployment evidence. Evidence is kept
outside the repository and must be captured against the revision actually
running; an older capture is not evidence for a newer head. The authenticated
readiness and replay-catalog reads, the refusal probes on this page, and the
browser journeys in [Demo Playground](../developer-guide/demo-playground.md)
are the procedure to repeat and record on the host you maintain.

The demo routes are registered in every process, but their credential boundary
answers before their demo-profile check. An anonymous API caller therefore gets
the shared `401` JSON refusal (or the login redirect when it sends
`Accept: text/html`); only a signed-in caller reaches the demo route's `404` in
a production process. The ordering is the same inside the demo process.

A signed-in crafted submission must be refused:

- `POST /compute/api/post` answers `403` with the flat envelope
  `{"error": ..., "code": "demo_read_only", "valid": false}` and creates no Task
  row.
- `POST /compute/api/preflight/<task_type>` answers `403` with the
  `TaskPreflightResult` envelope instead: `valid: false`,
  `admission.allowed: false`, and `errors[0].code: "demo_read_only"`. It has no
  top-level `code`; the preflight model wraps the handler's refusal.

The execution surfaces listed below answer `403` with
`{"error": ..., "code": "demo_read_only"}` (no `valid` field), before creating
a row, workspace, or reservation, enqueuing work, taking a lease, purging data,
or revoking a job:

| Probe | Refused action |
| --- | --- |
| `POST /compute/api/tools/<name>/call` | Tool workspace, reservation, ToolCall row, and queue message |
| `POST /compute/api/auth/admin/infrastructure/refresh` | Readiness probe pass and its worker enqueue |
| `POST /compute/api/auth/admin/gpu-credit/reconciliation` | Allocation reconciliation enqueue; the `GET` stays readable |
| `POST /compute/api/cancel/<md5sum>` | Cancellation claim, resource-stop dispatch, Celery revoke, and artifact removal |
| `POST /compute/api/results/<md5sum>/archive` | Archive build enqueue |
| `DELETE /compute/api/delete/<md5sum>`, `POST /compute/api/delete` | Cleanup claim, artifact purge, reservation release, and Celery revoke |

Admin accounting and policy writes are refused the same way, before any ledger,
allowance, reset, quota, or policy-audit row is written:

| Probe | Refused write |
| --- | --- |
| `POST .../users/<id>/gpu-credit/adjustments` | GPU-credit adjustment entry |
| `PUT .../users/<id>/gpu-credit/allowance` | Monthly-allowance change |
| `POST .../users/<id>/gpu-credit/reset` | Per-user compensating reset entry |
| `POST /compute/api/auth/admin/gpu-credit/reset` | Global reset batch |
| `PUT .../users/<id>/storage-quota` | Durable-storage quota policy |

The answer does not depend on the id or the tool family: it is decided from the
deployment profile before either is looked up. The Task and Tool workers repeat
the refusal for a row that reaches them anyway: a Task row is failed without
publishing a result or charging storage, and no Runner is started; a queued
ToolCall is failed before a runtime or workspace is touched. The worker boot and
pulse passes also refuse at each function boundary, so a database restored from
another deployment is not settled, charged, or re-enqueued even though the pulse
runs the storage repair every cycle. The submission gates remain the primary
refusal.

Two adjacent surfaces are different by design:

- `POST /compute/api/auth/admin/runners/<runner_family>/actions` is refused by
  the Operator service, not the route helper: a non-read action answers `409`
  with `This demo deployment is preview and replay only; Runner operations that
  change host or Task state are disabled.` Read-tier status/doctor actions still
  answer.
- `POST /compute/api/auth/admin/operator/jobs/<job_id>/cancel` only updates the
  job store and starts no host work, so it is not an execution surface and is
  not refused.

Verify through the API with a demo session, not only through the disabled
browser control:

```bash
DEMO_TASK_ID=0123456789abcdef0123456789abcdef
auth=(-H "Authorization: Bearer ${TOKEN}")
code() { curl -sS -o /dev/null -w '%{http_code}' "${auth[@]}" "$@"; }

printf 'post %s\n' "$(code -X POST -d '{"task_type":"not-a-task"}' "$BASE/compute/api/post")"
printf 'preflight %s\n' "$(code -X POST -d '{}' "$BASE/compute/api/preflight/not-a-task")"
printf 'tool %s\n' "$(code -X POST -F 'parameters={}' "$BASE/compute/api/tools/structure_inspect/call")"
printf 'readiness-refresh %s\n' "$(code -X POST "$BASE/compute/api/auth/admin/infrastructure/refresh")"
printf 'reconciliation %s\n' "$(code -X POST "$BASE/compute/api/auth/admin/gpu-credit/reconciliation")"
printf 'cancel %s\n' "$(code -X POST "$BASE/compute/api/cancel/${DEMO_TASK_ID}")"
printf 'archive %s\n' "$(code -X POST "$BASE/compute/api/results/${DEMO_TASK_ID}/archive")"
printf 'delete %s\n' "$(code -X DELETE "$BASE/compute/api/delete/${DEMO_TASK_ID}")"
printf 'delete-batch %s\n' "$(code -X POST -H 'Content-Type: application/json' \
  -d "{\"md5sums\":[\"${DEMO_TASK_ID}\"]}" "$BASE/compute/api/delete")"
```

Continuing in the same shell, probe the admin accounting and policy refusals
against one target user id from the Admin listing:

```bash
DEMO_USER_ID=$(curl -sS -H "Authorization: Bearer ${TOKEN}" \
  "$BASE/compute/api/auth/admin/users" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["users"][0]["id"])')
printf 'gpu-adjust %s\n' "$(code -X POST -H 'Content-Type: application/json' \
  -d '{"gpu_seconds":60,"reason":"demo","idempotency_key":"demo-adjust"}' \
  "$BASE/compute/api/auth/admin/users/${DEMO_USER_ID}/gpu-credit/adjustments")"
printf 'gpu-allowance %s\n' "$(code -X PUT -H 'Content-Type: application/json' \
  -d '{"monthly_gpu_seconds":7200,"idempotency_key":"demo-allowance"}' \
  "$BASE/compute/api/auth/admin/users/${DEMO_USER_ID}/gpu-credit/allowance")"
printf 'gpu-reset %s\n' "$(code -X POST -H 'Content-Type: application/json' \
  -d '{"reason":"demo","idempotency_key":"demo-reset"}' \
  "$BASE/compute/api/auth/admin/users/${DEMO_USER_ID}/gpu-credit/reset")"
printf 'gpu-reset-all %s\n' "$(code -X POST -H 'Content-Type: application/json' \
  -d '{"reason":"demo","idempotency_key":"demo-reset-all"}' \
  "$BASE/compute/api/auth/admin/gpu-credit/reset")"
printf 'storage-quota %s\n' "$(code -X PUT -H 'Content-Type: application/json' \
  -d '{"state":"limited","limit_bytes":1024,"reason":"demo","idempotency_key":"demo-quota"}' \
  "$BASE/compute/api/auth/admin/users/${DEMO_USER_ID}/storage-quota")"
```

Every line in both blocks must print `403`. A `200`, `202`, `400`, `404`, or
`409` means the deployed revision does not enforce this boundary; stop and
identify the running revision before recording evidence. The
readiness-refresh and reconciliation probes use the demo admin token because
those routes are Admin-only; their refusal happens after the Admin and Bearer
checks.

## Candidate deployment coordinates

These coordinates are the PR's planning record, and the PR's own acceptance
deployment ran the stack on exactly these values. They are not a maintained
deployment's configuration of record: replace them with the values the host
actually uses and record the deployment evidence. A maintainer-owned public
hostname is still undecided; see [Private ingress](#private-ingress).

| Item | Candidate value |
| --- | --- |
| Env file | `/mnt/hdd/rcwit-pr109-demo/.env.demo`, mode 0600 |
| `SERVER_DIR` | `/mnt/hdd/rcwit-pr109-demo/server` |
| `AUTH_DIR` | `/mnt/hdd/rcwit-pr109-demo/auth` |
| `LOG_DIR` | `/mnt/hdd/rcwit-pr109-demo/logs` |
| `PORT` | `8082` |
| `GATEWAY_BIND` | `127.0.0.1` |
| `COMPOSE_PROJECT_NAME` | `revocompute-demo-109` |
| `REVOCOMPUTE_DEMO_MODE` | `true` |
| `REVOCOMPUTE_JOB_EXECUTOR` | `demo` |
| `ADMIN_USERS` | `demo-admin` |
| `RUNNER_USERNAME`, `RUNNER_GROUP` | `yinying` |

The existing shared instance must remain untouched. Its planning-record
coordinates (`server-slurm-309` on port 8081, deploy root `/opt/revocompute`,
state `/mnt/hdd/revocompute`) are context for the isolation check, not values to
copy; confirm them on the host before relying on that check.

## State isolation rules

- One Compose project per deployment. Compose scopes container names, networks,
  and the `redis-data` volume to `COMPOSE_PROJECT_NAME`; sharing a project name
  would attach the demo services to another stack's Redis and networks.
- `SERVER_DIR`, `AUTH_DIR`, and `LOG_DIR` belong to the demo. `AUTH_DIR` is a
  dedicated sibling of `SERVER_DIR`, never a child of it, and never a system
  root such as `/`, `/etc`, `/home`, `/root`, `/tmp`, `/usr`, or `/var`.
- `AUTH_SECRET_KEY` is generated into the demo env file and not shared.
  Changing it logs out every demo session and invalidates outstanding links.
- The demo's `users.sqlite3`, task store, replay index, and materialized Runner
  tree live under its own `SERVER_DIR`/`AUTH_DIR`.
- The demo env file is never `.env.production`, never sourced from the
  production checkout, and never a symlink into a production path.
- The demo never receives production credentials, a production session secret,
  a production dataset, or a production result store.

## Private ingress

Cloudflare Tunnel/DNS, an external TLS proxy, and Cloudflare Access policy are
maintainer-owned resources. This repository documents the shape; it does not
provision or record a hostname, account, tunnel id, or token. **No public
hostname, tunnel, or Access policy has been configured or observed for this
PR.**

Before a public hostname is attached, all of the following must be true:

1. The loopback probes above pass on the demo host.
2. The tunnel or proxy targets the gateway's published `PORT`, never the
   internal Gunicorn service.
3. `GATEWAY_BIND=127.0.0.1` is kept when the tunnel runs on the same host. If the
   tunnel reaches the host from another interface, `GATEWAY_BIND` is widened and
   host firewall access is restricted to the tunnel's address; the gateway
   cannot distinguish a tunnel from a LAN peer for trusted-header purposes.
4. The chain preserves or forces the HTTPS signal the app needs. Confirm
   `Strict-Transport-Security` on the public response, and set
   `AUTH_COOKIE_SECURE=true` and `FORCE_HSTS=true` only when the public URL is
   HTTPS-only. See [Public Access and TLS Termination](public-access.md).
5. The ingress authorization policy is explicit and account-scoped for this
   environment, and ordinary application authentication still applies. Ingress
   authorization never replaces the app's own permissions.
6. The origin cannot be reached directly from an untrusted network.
7. The shell shows the demo badge, and no page claims production readiness.

`noindex` or robots deterrence is a secondary discovery control, never a
security boundary.

## Restart, reset, and rollback

Restart the demo without touching another stack:

```bash
REVODESIGN_SERVER_ENV=/srv/revocompute-demo/.env.demo bash run/restart.sh restart --mode=dev
```

Reset demo-owned state only:

```bash
REVODESIGN_SERVER_ENV=/srv/revocompute-demo/.env.demo bash run/restart.sh down
# Remove only the demo SERVER_DIR, AUTH_DIR, and LOG_DIR named by the demo env file.
REVODESIGN_SERVER_ENV=/srv/revocompute-demo/.env.demo bash run/restart.sh setup
REVODESIGN_SERVER_ENV=/srv/revocompute-demo/.env.demo bash run/restart.sh restart --mode=dev
```

The first start after a reset creates the demo auth database and prints a new
bootstrap password. Removing a parent directory that contains any other
deployment's state is not a reset.

Rollback is either content rollback (revert the curated replay index or a
manifest, then `setup` and `restart`) or deployment rollback (check out the
previous revision in the demo checkout and restart in `--mode=dev`). Replay
content replacement is atomic; a failed validation leaves the installed tree in
place.

## Verify production is untouched

Run this check after the first demo start and after any change to the demo env
file:

```bash
# The demo and production must be different Compose projects, networks, and volumes.
docker compose -p "<demo project>" ps
docker compose -p "<production project>" ps
docker volume ls
docker ps --format '{{.Names}}\t{{.Ports}}'

# The recorded production roots must not be children of the demo roots.
readlink -f "<demo SERVER_DIR>" "<production state root>"
readlink -f "<demo AUTH_DIR>"

# Production still reports execution available.
curl -sS "http://127.0.0.1:<production port>/compute/api/environment"
```

Production is untouched when its project's containers, volume, port, state
roots, and environment answer are unchanged, and no demo container appears in
its project. This is a procedure; record the observed output with the
deployment evidence rather than asserting it was checked.

## Failure handling

- **Setup/restart aborts on replay content.** Read the named index or bundle
  error, fix the tracked index or bundle, and rerun. Do not bypass validation by
  editing the installed tree under `SERVER_DIR`.
- **Startup fails in demo mode.** The server validates the installed replay
  index before serving. Re-run `setup` to reinstall the curated tree, then
  inspect the container log for the named scenario.
- **A page shows a missing payload.** That is the replay bundle's recorded
  exclusion, not a server failure. The evidence record should name the scenario
  and the reported reason.
- **Ingress does not answer.** Re-run the loopback liveness, environment,
  readiness, and replay probes. Repair the tunnel or access policy; do not
  disable application authentication to make the page load.
- **Port or project conflict.** Stop and correct the demo env file. Never stop
  another deployment's containers to free the demo's port.
