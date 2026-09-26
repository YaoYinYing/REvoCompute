# Configuration and Service Identity

Configuration has three deliberate owners. The selected environment file
(`REVODESIGN_SERVER_ENV`) owns host paths, Compose settings, credentials, and
the configured service identity. A family `plugin.yaml` owns task and runtime
contracts. A machine-local `runner.yaml` owns mounts, environment, limits, and
defaults. Do not copy these values into JavaScript or a second YAML registry.

## Identity contract

The deployment operator may be different from the service identity. The
configured `RUNNER_USERNAME` and `RUNNER_GROUP` must resolve on the target host;
explicit `RUNNER_UID` and `RUNNER_GID`, when supplied, must equal those account
records. Root and silent numeric fallbacks are rejected. Validate the effective
UID/GID in web, worker, and a real Slurm smoke job before lifting maintenance.

## Safe configuration workflow

```bash
cp .env.example .env.production.example-slurm
chmod 0600 .env.production.example-slurm
export REVODESIGN_SERVER_ENV=.env.production.example-slurm
git check-ignore -v "$REVODESIGN_SERVER_ENV"
```

Keep secrets in mode-0600 files or the deployment secret store. Print only an
allowlist of paths when diagnosing configuration; never dump an environment
file, credentials, or scheduler tokens into logs or receipts. Run Doctor after
changing any identity, mount, resource, task, or access-policy setting.

## Granting state-directory access

Use POSIX ACLs when both the deployment operator and the configured service
account must manage a private server-state tree. Here `SERVER_ROLE` names the
Unix **service account** (for example, the account selected by
`RUNNER_USERNAME`), not a Unix group or an application authorization role.
Install the host package that provides `getfacl` and `setfacl`, and confirm that
the backing filesystem supports ACLs before proceeding.

Stop or quiesce writers, replace the example state path with the exact absolute
host path, and verify all three values before running the privileged block:

```bash
OPERATOR=operator
SERVER_ROLE=revodesign
SERVER_STATE=/path/to/the/server/state/storage/directory

getent passwd "$OPERATOR"
getent passwd "$SERVER_ROLE"
sudo test -d "$SERVER_STATE"
sudo find "$SERVER_STATE" -xdev -maxdepth 0 -printf '%p\n'
```

Create a private ACL backup, remove group/other mode access, grant the two
accounts access to existing entries, and set inheritable ACLs on every existing
directory:

```bash
umask 077
sudo getfacl -R -p "$SERVER_STATE" > /tmp/revocompute-acl.before
sudo chmod -R go-rwx "$SERVER_STATE"
sudo setfacl -R -m u:"$SERVER_ROLE":rwX,u:"$OPERATOR":rwX,m::rwx "$SERVER_STATE"
sudo find "$SERVER_STATE" -type d -exec \
  setfacl -m d:u::rwx,d:u:"$SERVER_ROLE":rwx,d:u:"$OPERATOR":rwx,d:g::---,d:m::rwx,d:o::--- {} +
```

This intentionally changes every existing entry below `SERVER_STATE`. The
uppercase `X` avoids making ordinary files executable: it grants traversal on
directories and execution only where it already exists. Default ACLs affect
newly created children, while the recursive access ACL covers existing content.
Do not broaden `SERVER_STATE` to a parent that contains unrelated data, and keep
the backup private because it records the complete state-tree layout.

Verify representative directories and files as both identities before
resuming writes:

```bash
sudo getfacl -p "$SERVER_STATE"
sudo -u "$SERVER_ROLE" test -r "$SERVER_STATE" -a -w "$SERVER_STATE" -a -x "$SERVER_STATE"
sudo -u "$OPERATOR" test -r "$SERVER_STATE" -a -w "$SERVER_STATE" -a -x "$SERVER_STATE"
```

To roll back, keep writers stopped and restore the saved modes and ACLs from
the same host and unchanged path tree:

```bash
sudo setfacl --restore=/tmp/revocompute-acl.before
```

Inspect the restored root with `sudo getfacl -p "$SERVER_STATE"`, then securely
remove or archive the ACL backup according to the host's operations policy.

## Environment reference

Create production env file:

```bash
cp .env.example .env.production
chmod 600 .env.production
```

Production env files contain secrets and must not be group/world-readable.
They are ignored by Git; keep them on the deployment host and never bake them
into an image.

### Env-file isolation

All restart helpers support `REVODESIGN_SERVER_ENV`:

```bash
REVODESIGN_SERVER_ENV=.env.local bash run/restart.sh restart --mode=dev
REVODESIGN_SERVER_ENV=.env.production bash run/restart.sh restart --mode=prod
```

When `REVODESIGN_SERVER_ENV` is unset, the helper uses
`.env.production` and fails clearly when that file is absent.

### Required/important variables

`.env.example` is the authoritative list of the deployment environment surface.
The table below explains the variables whose deployment semantics are not
obvious; it is a guide to the contract, not a second copy of it.

| Variable | Purpose |
| --- | --- |
| `SERVER_IMAGE` | Long-lived server image. Runtime-family SIF identities are declared in family plugin manifests. Production pull mode applies only to published server images. |
| `SERVER_DIR` | Required host root shared by web and worker for uploads, task SQLite, and result folders. Never store the user database here. |
| `RUNNER_HOST_ROOT` | Host root allowed for Runner-family bind mounts (default: parent of `SERVER_DIR`). |
| `LOG_DIR` | Host directory for Gunicorn, Celery, and `maintenance.log`. |
| `CONFIG_DIR` | Optional host root for deployment-owned access-policy documents; defaults to the checkout's `config/`. Runner-family manifests are materialized into `SERVER_DIR/docker/runners` during setup, and task definitions and runtime metadata are never loaded from this path. |
| `ENABLED_TASKRUNNERS` | Deployment-controller selector: the exact comma-separated set of Runner families to materialize, advertise, and accept. Empty (the default) enables every discovered family. An unknown name aborts the deployment before shutdown. There is no implicitly enabled family. |
| `ADMIN_USERS` | Required comma-separated bootstrap-administrator usernames. On an empty user database, the restart script creates each account and prints a distinct generated password; afterward, database roles control authorization. |
| `AUTH_TOKEN_MAX_AGE` | Token lifetime in seconds (default: 604800 = 7 days). |
| `AUTH_SECRET_KEY` | Session-signing key for auth cookies and emailed verification/reset links. `restart.sh setup` generates and persists it in the env file; keep it stable, because changing it logs out every session and invalidates outstanding links. Set explicitly only to share sessions across deployments. |
| `AUTH_DIR` | Host-side directory containing `users.sqlite3`; Compose mounts it only into web and maintenance. It must be an absolute path, outside `SERVER_DIR`, and a dedicated directory — a system root such as `/`, `/etc`, `/home`, `/root`, `/tmp`, `/usr`, or `/var` is rejected. |
| `USER_DB_PATH` | Container-side path used by web and maintenance to open the user DB. Keep the default `/var/lib/revodesign-auth/users.sqlite3` unless the Compose mount target also changes. |
| `ENABLE_REGISTER` | Set to `true` to enable self-registration; configure either SMTP or Resend email delivery. |
| `SMTP_*`, `RESEND_*` | Email delivery settings. Resend takes priority when both backends are configured. |
| `SERVER_BASE_URL` | Public base URL for email links and HTTPS-sensitive auth-cookie settings. |
| `RUNNER_USERNAME`, `RUNNER_GROUP` | Required in production: the non-root service account, which must resolve to real account records on the host. The controller derives the numeric identity from them and never falls back to a default. |
| `RUNNER_UID`, `RUNNER_GID` | Optional numeric overrides. When supplied they must equal the IDs of the configured account and group, or the deployment aborts. Published images are built for a fixed identity; see the mode contract in `.env.example`. |
| `MAXMEM` | Global GREMLIN HHblits memory cap in GiB. Per-task SLURM CPU/memory requests are configured in the management database, not runner YAML. |
| `WORKER_CONCURRENCY` | Celery worker concurrency. Must be a positive integer: the value is interpolated into the container command line. |
| `GUNICORN_WORKERS` | Gunicorn worker count. Must be a positive integer. |
| `GUNICORN_TIMEOUT` | Gunicorn request timeout in seconds (default: `120`; must be a positive integer). Result transfers are handled by Nginx and do not require a long timeout. |
| `RESULT_DOWNLOAD_MODE` | Result delivery backend: `nginx` in Compose production, or `flask` for direct local Flask development. |
| `PORT` | Public HTTP port. Published loopback-only (`127.0.0.1`) by default — the host TLS/Basic-Auth nginx is the entry point, and it must reach the gateway at `localhost:8080`. |
| `GATEWAY_BIND` | Interface the gateway publishes `PORT` on (default: `127.0.0.1`). Set `0.0.0.0` when the entry proxy terminates elsewhere or uses an interface IP (e.g. a Cloudflare Tunnel origin configured with the host IP); keep TLS/auth in front of it. |
| `REDIS_PASSWORD` | Redis `requirepass` secret. Generated and persisted into the env file by `restart.sh setup`; the compose stack applies it to `redis-server` and to the Celery broker/backend URIs. Set explicitly only for an external Redis. |
| `INFRA_REFRESH_SECONDS` | Minimum interval between automatic infrastructure probe passes (default: `15`). Admin manual refresh bypasses this cache. Set to `0` to disable the automatic pulse; negative values are rejected. |
| `INFRA_STALE_SECONDS` | Evidence age after which infrastructure results are marked stale without discarding the last known state (default: `60`). |
| `INFRA_DISK_WARNING_PERCENT_FREE` | Free-space percentage at or below which required storage is `DEGRADED` (default: `10`). |
| `INFRA_DISK_CRITICAL_PERCENT_FREE` | Free-space percentage at or below which required storage is `UNAVAILABLE` (default: `5`; must not exceed the warning threshold). |
| `AUTH_COOKIE_SECURE` | Force the auth cookie's `Secure` flag even if the proxy chain fails to report HTTPS (default: `false`). Enable on HTTPS-only deployments; plain-HTTP clients would otherwise stop receiving the cookie. |
| `RESULT_RETENTION_DAYS` | Optional positive number of days to retain terminal-task result directories and archives. Fractions are allowed (`0.1` = 2.4 hours). Leave unset to disable cleanup; task audit rows remain. |
| `BACKUP_DB_CRON` | Five-field crontab schedule for database snapshots. Leave unset to disable; recommended daily schedule: `0 0 * * *`. |
| `BACKUP_DB_PATH` | Snapshot directory inside the maintenance container. `/var/lib/revodesign-auth/backups` persists at `${AUTH_DIR}/backups` on the host. |
| `MAX_DB_BACKUP` | Maximum complete snapshot sets to retain. Leave unset for unlimited history; recommended value: `30`. |
| `ROTATE_LOG_MAX_LINENO` | Optional line-count rotation threshold; unset disables this trigger. |
| `ROTATE_LOG_PERIOD` | Optional quoted five-field crontab expression for scheduled rotation (for example, `"0 0 * * *"` for daily at midnight); unset disables this trigger. |
| `MAX_LOG_SIZE` | Optional total cap for active logs plus ZIP archives; accepts bytes or K/M/G/T suffixes and removes oldest ZIPs first. A newly created archive is retained even when it temporarily exceeds the cap. |
| `ADMIN_NOTIFY_EMAIL` | Comma-separated admin email addresses for new-user registration digests (default: empty = no notification). |
| `ADMIN_NEW_USER_INFORM` | Interval in minutes between new-user digest emails (default: `0` = disabled). |
| `ALLOWED_EMAIL_DOMAINS` | Comma-separated allowed email domains for self-registration (empty = all allowed). Also normalises plus-aliased addresses (`user+tag@domain` → `user@domain`). |
| `TZ` | Timezone for logs. |
| `CLIENT_IP_HEADERS` | Comma-separated list of HTTP headers to try for the real client IP, in priority order (default: `X-Forwarded-For, X-Real-IP`). See CDN reference below. |
| `CLIENT_COUNTRY_HEADER` | Single HTTP header carrying the client country code, e.g. `CF-IPCountry` for Cloudflare (default: empty = disabled). |

Compose also injects `RUNNERS_DIR=${SERVER_DIR}/docker/runners`. That is the
runtime plugin root the server discovers families from; it is derived, not set
in the env file, and `CONFIG_DIR` is never the plugin tree.

### Authentication storage: host path versus container path

`AUTH_DIR` and `USER_DB_PATH` describe the same storage from two different
points of view:

```text
Docker host                           web / maintenance containers
/srv/revodesign/auth/users.sqlite3 -> /var/lib/revodesign-auth/users.sqlite3
^^^^^^^^^^^^^^^^^^^^^^^                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AUTH_DIR                               USER_DB_PATH
```

With the example configuration:

```dotenv
SERVER_DIR=/srv/revodesign/server
AUTH_DIR=/srv/revodesign/auth
USER_DB_PATH=/var/lib/revodesign-auth/users.sqlite3
```

Compose applies these boundaries:

| Process | Sees `SERVER_DIR` | Sees `AUTH_DIR` | Can open the user DB |
| --- | --- | --- | --- |
| Web | Yes | Yes, mounted at `/var/lib/revodesign-auth` | Yes |
| Maintenance | Yes | Yes, mounted at `/var/lib/revodesign-auth` | Yes, for email and backup tasks |
| Celery worker | Yes | No | No |

`AUTH_DIR` is therefore not an application data path passed to Python. It is a
Docker-host path used to create a private volume mount for web and maintenance.
It must be a sibling of, rather than a child of, `SERVER_DIR`: mounting all of
`SERVER_DIR` into the worker would otherwise expose any nested auth directory
through that parent mount.

On a new installation, create `AUTH_DIR` with write access for
`RUNNER_UID:RUNNER_GID`; web creates `users.sqlite3` there on first start. Keep
`USER_DB_PATH` at its default unless you deliberately change the target side of
the Compose volume mount.

When database backups are enabled, each successful run creates one complete
snapshot set:

```text
${AUTH_DIR}/backups/20260101T000000.000000Z/
├── tasks.sqlite3
└── users.sqlite3
```

Copies are made through SQLite's online backup API and checked before the
snapshot directory is published. `MAX_DB_BACKUP` counts these complete
timestamped directories, not individual database files.

### CDN IP header reference

| Provider | IP header | Country header |
|---|---|---|
| Cloudflare | `CF-Connecting-IP` | `CF-IPCountry` |
| Akamai | `True-Client-IP` | — |
| AWS CloudFront | `CloudFront-Viewer-Address` | `CloudFront-Viewer-Country` |
| Fastly | `Fastly-Client-IP` | — |
| Azure Front Door | `X-Azure-ClientIP` | — |
| Fly.io | `Fly-Client-IP` | — |
| Netlify | `X-Nf-Client-Connection-IP` | — |
| nginx / Traefik / Caddy / GCP | `X-Forwarded-For` | — |

Put the CDN-specific header first, then fall back to `X-Forwarded-For`. Example for Cloudflare:

```bash
CLIENT_IP_HEADERS="CF-Connecting-IP, X-Forwarded-For, X-Real-IP"
CLIENT_COUNTRY_HEADER="CF-IPCountry"
```
