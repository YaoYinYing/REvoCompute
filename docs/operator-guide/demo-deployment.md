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

Run these on the host before attaching any ingress:

```bash
PORT=8082  # the candidate port; use the demo env file's value
curl -sS "http://127.0.0.1:${PORT}/compute/health"
curl -sS "http://127.0.0.1:${PORT}/compute/api/environment"
curl -sS "http://127.0.0.1:${PORT}/compute/api/demo/replays"
```

The expected observations, from the code, are:

- health answers with the deployment's readiness response;
- environment reports `demo_mode: true` and `execution: "preview_only"`;
- the replay catalog lists the installed scenarios with provenance labels and
  bundle digests.

Record the actual responses with the deployment evidence. The three commands
above, and the authenticated submission-refusal check in the next paragraph,
have not been observed on the candidate host described below; they are the
procedure, not a receipt.

A signed-in crafted submission to `/compute/api/post` or
`/compute/api/preflight/<task_type>` must answer `403` with
`code: "demo_read_only"` and create no Task row. Verify this through the API with
a demo session, not only through the disabled browser control.

## Candidate deployment coordinates

These coordinates are the planning values in the PR's implementation record. They
are **not yet deployed or observed**; replace them with the values the host
actually uses and record the deployment evidence.

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
- **Ingress does not answer.** Re-run the loopback health, environment, and
  replay probes. Repair the tunnel or access policy; do not disable application
  authentication to make the page load.
- **Port or project conflict.** Stop and correct the demo env file. Never stop
  another deployment's containers to free the demo's port.
