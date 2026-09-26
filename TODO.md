# REvoCompute Comprehensive Security Review

Control document for the defensive security review of the next `main`
revision. Each workstream below records what was examined, what was found, and
the disposition.

**Reviewed revision:** `8603cec` (`feat(runner): enforce the Runner
change-impact contract (#28)`) plus the fixes committed on
`security/comprehensive-review`.

The review ran five rounds. Round 1 audited the HTTP, storage, scheduler, and
container boundaries (findings and dispositions in the sections below). Rounds
2–4 extended it to surfaces round 1 did not cover, one round per area; round 5
validated the deployed instance directly.

| Round | Area | Findings |
| --- | --- | --- |
| 2 | Tool runtime and validators; quotas/DoS; object-level authorization; the deployment plane | `SEC-TOOL-*`, `SEC-DOS-*`, `SEC-AUTHZ-*`, `SEC-DEPLOY-*` |
| 3 | Runner build plane (`.def`/`%post`/pinning); serialization and schema evolution | `SEC-RB-*`, `SEC-SER-*` |
| 4 | Operations and observability; task-lifecycle integrity and availability | `SEC-OPS-*`, `SEC-LIFE-*` |
| 5 | Live-instance validation: lifecycle transitions, the deployed TLS/proxy/config plane, the result-viewer chain | `SEC-LIVE-*` |

Each round fanned out read-only audit agents, then a separate set of fix
agents; every fix below was shown to fail before it was made and carries one
focused regression test. Several agent claims were disproven under live or
local reproduction and are recorded as false positives rather than fixed —
those entries are as important as the findings.

---

## Phase 0 — Security model

REvoCompute is a multi-user scientific compute service. Trust boundaries, from
untrusted to privileged:

| Boundary | Untrusted side | Privileged side | Authority at stake |
| --- | --- | --- | --- |
| HTTP | anonymous / any registered user | Flask (`routes.py`) | authentication, authorization |
| Task preparation | uploaded files, form params, workspace JSON | Core validation + `StorageResolver` | filesystem containment |
| Scheduler | task parameters, runner manifests | Slurm (`srun`) | host process creation |
| Container | runner `run.sh`, model code, user data | Apptainer → host kernel | host filesystem/network |
| Result | runner output, artifact bytes | Flask + nginx | browser same-origin script |

Security invariants that must hold:

1. Untrusted data never reaches a shell, a scheduler directive, or a container
   argv by interpretation — only by argument.
2. Every filesystem operation resolves inside a configured root, after symlink
   resolution.
3. Every object read or mutated is ownership-checked server-side before any
   data is returned.
4. A credential of one class never confers the authority of another.
5. A container's authority is the intersection of an explicit declaration and
   a fixed adapter default — never what the host happens to offer.

---

## Findings

### SEC-AUTHN-1 — API key escalated to a full web-login session — FIXED

**Status:** confirmed vulnerability · **Severity:** high
**Root cause:** `/compute/api/auth/token` issued a session bearer token for any
authenticated credential, including `X-API-Key`.
**Impact:** an API key is documented as restricted (no password change, no
API-key management, no admin actions) and is stored in scripts and CI. Minting
a session token from one granted every one of those privileges, including admin
actions for an admin account. The minted token also outlived API-key
revocation, because it carries only `uid` and `ver`.
**Remediation:** the route now requires a web-login credential
(`require_web_login()`), so an API key can never be laundered into the stronger
tier.
**Regression test:** `tests/test_auth.py::test_api_key_cannot_mint_a_bearer_session`.

### SEC-AUTHN-2 — Link tokens were accepted as session tokens — FIXED

**Status:** confirmed vulnerability · **Severity:** medium-high
**Root cause:** one `URLSafeTimedSerializer` serves four semantic token classes
(session, verify-email, reset-password, CAPTCHA) and `validate_token` checked
only signature, expiry, and the presence of `uid`.
**Impact:** an emailed verification or password-reset link, observed once
(mail scanner, proxy log, shared screen, browser history), authenticated as a
full 7-day web session and could mint a non-expiring API key.
**Remediation:** session tokens carry `purpose="session"` and
`validate_token` requires it. Each consumer already asserted its own `purpose`,
so the fix is one check at the shared entry point.
**Regression test:** `tests/test_auth.py::test_link_token_purposes_are_distinct`.

### SEC-AUTHN-3 — Verification links could not be revoked — REVERTED, NOT A FINDING

**Status:** false positive · **Severity:** informational
**Initial assessment:** the verify-email payload omitted `ver`, so
`increment_token_version` could not invalidate a leaked link for its 2-day life.
**Why the fix was reverted:** binding the link to `token_version` created a
real availability regression — `token_version` is bumped by every logout and
every password change, and nothing re-stamps it on verification, so a
self-registered user whose password-reset link was consumed before they clicked
the verification link could never verify. The action the link authorises is
only "this address is reachable", which admin approval grants anyway
(`_admin_registration_update_fields` calls `db.verify_email` on approval), so
the security benefit did not justify stranding users.
**What was kept:** the reset-password link keeps its `ver` binding via the
shared `_validate_link_token` helper — that is the token whose authority
(reset a password) warrants revocation.
**Regression test:** `tests/test_auth.py::test_verification_link_survives_an_unrelated_password_reset`.

### SEC-AUTHN-4 — CAPTCHA answer disclosed in the returned token — FIXED

**Status:** confirmed vulnerability · **Severity:** medium
**Root cause:** `generate_captcha` embedded `{"answer": ...}` in the signed
token. itsdangerous payloads are base64, not encrypted.
**Impact:** the second control on registration was defeated by decoding the
first token segment. The challenge is a visible maths question, so an attacker
can still solve it programmatically; the fix removes the *free* answer, leaving
registration bounded by the 3/hour/IP rate limit and the CAPTCHA-issuance cost
rather than by an accidental disclosure. Prerequisite: `ENABLE_REGISTER=true`
(default false). Confirmed live against production before the fix: the token
payload decoded to `{"answer":15,...}`.
**Remediation:** the expected answer now lives server-side (Redis, with a
per-process fallback only when Redis is unavailable) keyed by the token's
`jti`; the token carries only the nonce; a Redis Lua compare-and-delete
consumes it atomically, so a challenge cannot be replayed across workers.
**Regression tests:** `tests/test_auth.py::test_captcha_token_does_not_disclose_its_answer`,
`::test_captcha_is_single_use`, and the existing hardening tests.

### SEC-RUNNER-1 — Runner containers shared the host network namespace — FIXED

**Status:** confirmed vulnerability · **Severity:** high
**Entry point:** any task submission.
**Root cause:** `--containall` isolates PID, IPC, mount, and `$HOME`, but does
**not** create a network namespace. The adapter passed no `--net` flag, so
every container inherited the worker's host namespace. Verified live on this
host: `readlink /proc/self/ns/net` inside the container equals the host's.
**Impact:** every task could reach the worker's Celery broker on
`127.0.0.1:6380` (the password is in the worker's own environment, and the
Slurm override runs the worker with `network_mode: host`) and the gateway on
`127.0.0.1:8080`. Broker access is task-injection and result-read: a
root-equivalent control-plane path. The declared `requires_network` capability
was metadata only — advertised to the API and UI, enforced nowhere.
**Remediation:** a task that does not declare `requires_network` is launched
with `--net --network none`, giving it a private network namespace with
loopback only (verified live: fresh netns, only `lo` present). A task that does
declare it keeps the host namespace, because an isolated *egress* namespace
needs a root/suid-configured Apptainer bridge — that is a deployment choice the
adapter cannot assume. Also added explicit `--no-home` to match the Tool
runtime.
**Regression test:** `tests/test_slurm_runner.py::test_render_apptainer_isolates_network_unless_declared`.

### SEC-RUNNER-2 — `runner.yaml` env names were shell syntax — FIXED

**Status:** confirmed vulnerability (developer-reachable) · **Severity:** medium
**Root cause:** `_load_runner_config` accepted any mapping as `env`. The
wrapper renders `export APPTAINERENV_{key}={quoted_value}` — the value was
quoted, the name was not.
**Impact:** a crafted key (`X; touch /tmp/PWNED; #`) executes arbitrary shell
inside the Slurm allocation. Reproduced locally with the rendered line.
Reachability is the runner-manifest author, so this is an insider/defense-in-
depth issue — but the materialized runner tree lives under `SERVER_DIR`, which
is mounted writable into web/worker/maintenance, so it is a real escalation
primitive if that boundary ever weakens.
**Remediation:** env names must match `[A-Za-z_][A-Za-z0-9_]{0,127}`.
**Regression test:** `tests/test_plugin_discovery.py::test_runner_yaml_env_names_and_mounts_are_validated`.

### SEC-RUNNER-3 — `runner.yaml` mounts were unvalidated — FIXED

**Status:** confirmed weakness · **Severity:** medium
**Root cause:** `RunnerMount` carried `host_path`, `container_path`, and `mode`
straight into `--bind` argv with no validation beyond `_sh_quote` on both
sides. Quoting prevents shell syntax; it does not prevent semantics.
**Impact:** a manifest could bind `/` read-write over the container rootfs,
bind the Docker socket, or set `container_path` to `/workspace/inputs` and
shadow the immutable input snapshot the adapter binds read-only. A `mode`
outside `{ro, rw}` was also accepted (`ExecutionPlan` checked it, the loader
did not).
**Remediation:** host and container paths must be absolute, mode must be `ro`
or `rw`, and the container target is normalized before being compared against
the scheduler-owned `/workspace` and `/tmp` (the container root is rejected
too). All 39 production mounts pass unchanged (all `ro`, all absolute).
**Regression test:** same as SEC-RUNNER-2, covering `/workspace/inputs`,
`//workspace//inputs`, `/workspace/./inputs`, `/opt/../workspace/inputs`,
`/x/../tmp`, `/tmp/` and `/`.
**Review note:** the first version of this check compared the *unnormalized*
target, so `/opt/../workspace/inputs` still walked past it — the exact
shadowing outcome the finding describes. Caught by the verification pass and
fixed before delivery.

### SEC-SECRETS-1 — Deployment env file created world-readable — FIXED

**Status:** confirmed weakness · **Severity:** medium
**Root cause:** `cmd_setup` used `shutil.copy`, which preserves the tracked
`.env.example` mode (0644), and then `ensure_redis_password` appended the
generated `REDIS_PASSWORD` to that file.
**Impact:** the broker credential was readable by every local user until an
operator ran the documented manual `chmod 600`.
**Remediation:** the file is created 0600 before any secret is written to it.
**Note:** `.env.production.v7-slurm` on this host is already 0600. An
*existing* world-readable env file is not re-tightened; the operator-facing
docs still tell operators to `chmod 600` a file they created by hand.

### SEC-PRIVACY-1 — `Proxy-Authorization` persisted with the task row — FIXED

**Status:** confirmed weakness · **Severity:** low
**Root cause:** `_REDACTED_HEADERS` was a three-entry denylist.
**Impact:** a credential injected by an authenticating forward proxy was
persisted in the task row and written to the worker log.
**Remediation:** `proxy-authorization` added to the denylist.
**Regression test:** `tests/test_tasks.py` request-header test.

### SEC-WEB-1 — Storyboard JavaScript runs same-origin — DOCUMENTED, ACCEPTED

**Status:** hardening opportunity · **Severity:** medium
**Evidence:** `task-results.js` loads a runner-owned storyboard module via
dynamic `import()` at app origin, and the session bearer token lives in
`sessionStorage`. The Mol* viewer is deliberately isolated in a sandboxed
iframe; storyboards are not.
**Assessment:** storyboards are deployment-controlled runner assets, produced
by the same authors as the container images that already run arbitrary code.
A storyboard author is therefore not a distinct trust tier today. The real
exposure is *supply-chain*: a compromised or careless runner tree gains
script execution on the result page.
**Disposition:** accepted for this revision, recorded as an architectural risk
in §Remaining architectural risks. The fix (mount storyboards the way Mol* is
mounted, via the sandboxed shell) is a UI change, not a defect in the current
threat model.

### SEC-SUPPLY-1 — Broker password visible in container arguments — DEFERRED

**Status:** configuration/deployment concern · **Severity:** medium
**Evidence:** `docker-compose.yml` passes `${REDIS_PASSWORD}` through
`redis-server --requirepass`, so the value is part of the container's `Cmd`
and readable via `docker inspect`.
**Impact:** any local user in the `docker` group, or anything with host shell
access, recovers the Celery broker credential.
**Disposition:** deferred. The fix is a deployment change (Docker `secrets`, a
mounted `redis.conf`, or `--requirepass-file`) that moves past the currently
pinned `redis:7.2-alpine` compose path and the controller's env-file model;
it should be its own change with its own verification. Recorded here so it is
not lost. Until then, treat host shell access as equivalent to broker access —
which the single-tenant production topology already assumes.

---

## Round 2 — Tool runtime, quotas, authorization, deployment plane

### SEC-TOOL-1 / SEC-TOOL-2 / SEC-TOOL-3 — tool isolation and budget — FIXED

**Status:** confirmed · **Severity:** medium
**Root causes.** Three defects on the ephemeral-workspace → durable-result path:
(1) the executed child's output ceiling was *reserved* at admission
(`reserved_bytes = TOOL_OUTPUT_MAX_BYTES`) but never *enforced* while the call
ran; the real size was only reconciled at completion, and a failed call kept
`reserved_bytes=0` with the oversized files still on disk. (2) The isolated
validator installed its rlimits *inside* the new interpreter, leaving the child
unbounded between fork/exec and the first untrusted byte, and the parent's
timeout only reaped the child instead of killing the group. (3) The child's
self-declared `backend` provenance was copied verbatim into the result manifest
with no server-owned field to contradict it.
**Impact.** A Tool could write far past its admitted headroom into the shared
`/srv` volume (which also holds results, uploads, workspaces, and the SQLite
DBs) without tripping admission; a pathological upload could hold memory during
the pre-rlimit window; a compromised Tool could claim a backend it never ran.
**Remediation.** The output ceiling is enforced at copy-back from the exchange
slot, so an over-limit output is never promoted and the true size reaches the
failure accounting via the existing `_finish_failed` path. The rlimit table is
now one source of truth applied by the parent's `preexec_fn` before exec, and a
timeout `killpg`s the group (SIGTERM, then SIGKILL). The child's backend is
recorded as `provenance.declared`, with `runtime_family`/`runtime_identity`
remaining the server-owned fields.
**Regression tests.** `tests/test_tool_isolation.py::test_execute_refuses_to_promote_output_beyond_the_reserved_ceiling`,
`::test_isolated_launcher_bounds_the_child_before_exec`,
`::test_isolated_parser_timeout_kills_the_whole_child_group`,
`::test_tool_provenance_is_server_owned_and_cannot_be_shadowed`.

### SEC-DOS-1 — one tenant could hold the whole global Tool byte pool — FIXED

**Status:** confirmed · **Severity:** high
**Root cause.** `ToolCallDatabase.reserve` charged every call's full
`output_max_bytes` headroom against a single fleet-wide
`TOOL_STORAGE_MAX_BYTES` (100 MiB), and the per-user *count* check ran first,
so the per-user limit never bound the bytes. Three zero-byte reservations from
any authenticated user held 96/100 MiB and every other tenant's Tool call
answered 507.
**Remediation.** A per-user `SUM(...) WHERE submitted_by_user_id = ?` inside the
same `BEGIN IMMEDIATE` block bounds each tenant to `storage_max_bytes //
per_user_limit`, with a `max(share, required_bytes)` floor so an under-sized
pool cannot turn the share into a hard block for its one legitimate caller.
New reason `user_storage_limit`, mapped to 507 alongside `storage_limit`.
**Regression test.** `tests/test_round2_security.py::test_one_user_cannot_reserve_the_whole_tool_storage_pool`
(and `::test_an_under_sized_pool_still_admits_its_one_legitimate_caller`).

### SEC-DOS-9 — unbounded synchronous artifact-deletion loop — FIXED

**Status:** confirmed · **Severity:** medium
**Root cause.** `delete_tasks_batch` iterated a caller-supplied `md5sums` list
with no length cap, and each element ran `shutil.rmtree` on a result tree
synchronously in the request. With two gunicorn workers, two large batches
monopolise the web tier.
**Remediation.** `_MAX_BATCH_DELETE_TASKS = 100`, matching the clamp shape used
for every other caller-supplied collection.
**Regression test.** `tests/test_round2_security.py`, batch-delete cap test.

### SEC-DOS-2 / SEC-DEPLOY-9 — rate-limit identity was client-chosen — FIXED

**Status:** confirmed · **Severity:** high (deployment-dependent)
**Root cause.** `ratelimit.py` keyed every limiter on `X-Real-IP` and the app
read the audit IP from `CLIENT_IP_HEADERS` (default `X-Forwarded-For` first),
with no concept of a trusted proxy. Rotating the header minted a fresh identity
per request, bypassing all eight per-IP limits on any deployment where the
caller could reach the origin directly.
**Remediation.** One leaf module `revocompute/client_ip.py` now owns client-IP
resolution: a forwarding header is honoured only when `request.remote_addr` is
inside `TRUSTED_PROXY_IPS` (default loopback + the compose bridge, matching the
gunicorn `--forwarded-allow-ips` trust set). `X-Real-IP` leads the default
header list because both shipped proxies overwrite it with the socket peer,
while `X-Forwarded-For` is appended to. The limiter calls
`trusted_client_ip()`, and it lives in a leaf module because importing
`revocompute.app` at request time re-executes the application module when the
test loader has removed it from `sys.modules` — which wiped the discovered
plugin graph mid-request and broke unrelated tests.
**Regression tests.** `tests/test_trusted_proxy.py::test_rotating_a_forwarding_header_does_not_refresh_the_rate_limit`
and `::test_a_header_from_a_trusted_proxy_peer_is_honored`.

### SEC-AUTHZ-1 — guests could submit compute — FIXED

**Status:** confirmed · **Severity:** medium
**Root cause.** `_reject_guest()` was applied to five surfaces only. Task
submission, preflight, Tool calls, and metrics had no guest check, although
`docs/operator-guide/runner-access.md` lists "admin / user / guest role rules"
as an independent admission check. A shared guest credential could consume
GPU/CPU and mint durable task rows.
**Remediation.** The role rule is decided once at the shared submission
boundary (`_handle_submission`, which both `/compute/api/post` and
`/compute/api/preflight/<type>` funnel through) and on the Tool-call submit
route. Guests keep their auto-minted bearer — the frontend's `ensureToken()`
needs one — so the rule enforced is "no compute", not "no bearer".
**Regression test.** `tests/test_round2_security.py`, guest submission test.

### SEC-AUTHZ-2 — 403-vs-404 existence oracle — FIXED

**Status:** confirmed · **Severity:** low
**Root cause.** `_task_access_denied` answered 403 with an explicit
"does not belong to the authenticated user" message, distinct from the 404 for
an id nobody has used, so any requester could confirm a leaked task id exists
and belongs to someone else.
**Remediation.** `_task_access_denied` was **deleted** (no alias) and all eleven
call sites migrated to `_task_not_found`, which logs the server-side
distinction and returns the identical 404 body.
**Regression test.** `tests/test_round2_security.py`, oracle test.

### SEC-AUTHZ-3 — batch delete reported foreign ids as `forbidden` — FIXED

**Status:** confirmed · **Severity:** low
**Root cause.** The three-way `deleted`/`forbidden`/`not_found` outcome list let
an authenticated user enumerate, in bulk, which task ids exist for another
tenant.
**Remediation.** A foreign id now lands in `not_found`; the server-side
distinction is a `logging.warning`. No consumer read the removed key
(`dashboard.js` reads only `deleted`; the OpenAPI 200 body stays valid).
**Regression test.** `tests/test_round2_security.py`, batch oracle test.

### SEC-AUTHZ-4 — cookie-only logout never expired the cookie — FIXED

**Status:** confirmed · **Severity:** low
**Root cause.** `auth_logout` checked `require_bearer_auth()` *before* emitting
`set_cookie(..., max_age=0)`, so a cookie-only POST returned 403 and the
`HttpOnly` 7-day `auth_token` cookie was never expired — the next visitor to
that browser was logged straight in.
**Remediation.** The clearing response is built and its `Set-Cookie` set first on
every path; the bearer gate now only withholds the `token_version` bump (the
deliberate CSRF-safe behaviour) and supplies the 403 body.
**Regression test.** `tests/test_round2_security.py`, cookie-logout test.

### SEC-DEPLOY-1 — `AUTH_DIR` accepted a system root as its read-write bind — FIXED

**Status:** confirmed · **Severity:** medium
**Root cause.** `validate_auth_storage` only rejected an `AUTH_DIR` *inside*
`SERVER_DIR`, so `/`, `/etc`, `/home`, `/tmp`, `/root` all passed and rendered
as a read-write bind of that root into web/maintenance.
**Remediation.** Absolute path required, plus an explicit denylist of system
roots checked against `realpath` (so a symlink to `/etc` fails too). `/mnt`,
`/opt`, `/srv` and dedicated subdirectories remain accepted.

### SEC-DEPLOY-2 — `AUTH_SECRET_KEY` had no supported way to be set — FIXED

**Status:** confirmed · **Severity:** medium (availability)
**Root cause.** The variable was absent from the compose model entirely, so
`revocompute/auth.py`'s `secrets.token_hex(32)` fallback was the only behaviour
and every web-container recreation invalidated all sessions, verify links, and
reset links. A hand-exported value would have been silently dropped at the next
compose render.
**Remediation.** `AUTH_SECRET_KEY: ${AUTH_SECRET_KEY:-}` added to the
`x-web-auth-env` anchor (web + maintenance only; worker/tool-worker never load
`revocompute.auth`), documented in `.env.example` and
`docs/operator-guide/configuration.md`, and generated/persisted by `setup`
exactly like `ensure_redis_password`. The value is never printed.

### SEC-DEPLOY-3 — runner identity accepted non-decimal spellings of uid 0 — FIXED

**Status:** confirmed · **Severity:** medium
**Root cause.** `format_runner_identity` compared strings against `{"0","root"}`,
but Docker resolves `00`, `+0`, `0x0`, `0000` to uid 0. A `RUNNER_UID=00`
built a root runner account and ran the service containers as root.
**Reproduction (verified locally):**
`format_runner_identity('00','00') -> '00:00'` before the fix; Docker resolves
`--user 00:00` to `uid=0(root)`.
**Remediation.** Each part is canonicalized: plain decimal is re-emitted
canonically, names pass through, and anything starting with a digit or
sign but not plain decimal is rejected.
**Regression test.** `tests/test_config.py::test_format_runner_identity_accepts_only_non_root_decimal_spellings`.

### SEC-DEPLOY-4 / SEC-DEPLOY-6 / SEC-DEPLOY-7 — hardening, recorded

`SERVER_DIR` is mounted read-write into web/worker/tool-worker and only
`docker/runners` and `docker/tools` are re-mounted read-only, so the service
account can still write `SERVER_DIR/docker` and the `CONFIG_DIR` runner trees
that sit outside `SERVER_DIR`; deployment host paths appear in operator-facing
API payloads; and `maintenance` inherits the full task/auth environment
including the broker credential. None of these crosses a boundary that is not
already trusted, and each is a narrowing of a broad mount rather than a defect.
Left as-is for this revision; the intended fix is to mount only the
subdirectories each service needs.

### SEC-DEPLOY-5 — command-line counts accepted injected argv words — FIXED

**Status:** confirmed · **Severity:** low
**Root cause.** Compose interpolation is textual, and `WORKER_CONCURRENCY` /
`GUNICORN_WORKERS` were neither validated nor numeric-checked, so
`WORKER_CONCURRENCY="2 --pool=solo"` added an argv word to the Celery worker in
the host-netns container that holds the broker credential.
**Remediation.** `validate_required_settings` requires a positive integer for
the three values compose interpolates into a command line.

### SEC-DEPLOY-8 — cancel ids passed to `scancel`/`docker stop` — HARDENED, not exploitable

Verified rather than assumed: the argv is a list (no shell), and the ids are
read from the *task row*, never from the request body, so a user can only
cancel their own job. Recorded because the worker holds the Docker socket, so
any future route that let a client name an id would become a host-wide
`docker stop` primitive.

---

## Round 3 — Runner build plane, serialization, and schema evolution

### SEC-RB-1 — the allocation wrapper was a self-modifying host script — FIXED

**Status:** confirmed · **Severity:** high
**Root cause.** `SlurmJob._build_wrapper_script` wrote the bash wrapper into
`output_dir`, which is also bind-mounted **writable** into the container as
`<virtual_workspace_root>/outputs`. Bash reads a script incrementally, so a
container process could rewrite the not-yet-executed tail and have it run on
the **host** as the worker uid, outside Apptainer and outside
`--net --network none`.
**Reproduction (local, confirmed):** a background process appending
`echo "PWNED-BY-CONTAINER"` to a running bash script caused the appended command
to execute; the append is only observable to bash while it is still reading.
**Remediation.** The wrapper is rendered into a task-private sibling directory
(`<output_dir>.allocation`, 0700) outside every container bind, and removed with
that directory on exit. `srun --chdir` is unchanged. The now-unreachable
`_slurm_wrapper_*` skip in `_has_result_artifact` was subtracted.
**Regression test.** `tests/test_slurm_runner.py::test_wrapper_is_outside_the_container_writable_view`.

### SEC-RB-2 — a workflow stage silently inherited the task capability — FIXED

**Status:** confirmed · **Severity:** medium
**Root cause.** `_load_workflow` defaulted `requires_gpu`/`requires_network` to
`False` when a stage omitted them, while `task_runtime` replaced the task-level
flags with the stage values. A stage's declared capability could therefore
disagree with the container flags and the stored resource snapshot.
**Remediation.** Both keys are now required per stage (a missing key is a load
error naming the stage), and every production workflow declares them
explicitly (alphafold, alphafold3, colabfold_af2).
**Regression test.** `tests/test_plugin_discovery.py::test_workflow_stage_must_declare_both_capability_keys`
and `::test_every_production_workflow_declares_both_capability_keys`.

### SEC-RB-11 — a mount could shadow the image entrypoint tree — FIXED

**Status:** confirmed · **Severity:** low
**Root cause.** `_RESERVED_CONTAINER_PREFIXES` covered `/workspace` and `/tmp`
only, so a manifest could bind over `run.sh`, `task_context.sh`, or a family's
asset verifier under `/app`. The same class as SEC-RUNNER-3, one prefix over.
**Remediation.** `/app` joins the reserved prefixes. Exactly one of the 49
production mounts targeted `/app` — `mpnn`'s LigandMPNN weights — and moved to
its operator-data path (`run.sh` already prefers `LIGANDMPNN_MODEL_PARAMS`).
**Verified live.** `live-test --runner mpnn --collection smoke --use-proxy` on
the target host passed all six cases, including `minimal-ligandmpnn`, which
loaded `ligandmpnn_v_32_010_25.pt` from the new
`/mnt/db/weights/ligandmpnn/model_params` target (Slurm job `52094`, 18.8 s,
9 artifacts, no GPU device). `runner-status --runner mpnn` now reports `READY`.
See "Re-acceptance after the round-2–4 fixes".

### SEC-SER-1 — a deeply nested JSON body produced an unhandled 500 — FIXED

**Status:** confirmed · **Severity:** medium
**Root cause.** `json.loads` signals excessive nesting with `RecursionError`,
which `get_json(silent=True)` does **not** swallow (it only suppresses
`ValueError`), and the app had no handler for it. A 1.2 MB body of nested
objects returned a 500 with a stack trace on the unauthenticated login route.
The uploaded-file paths already caught `RecursionError`; the HTTP boundary was
missed.
**Remediation.** One `@app.errorhandler(RecursionError)` returning 400 with the
`request_size_limit` finding shape.
**Regression test.** `tests/test_round2_security.py::test_deeply_nested_json_is_rejected_as_bad_input`.

### SEC-SER-2 / SEC-SER-4 — non-finite numbers reached the Runner manifest — FIXED

**Status:** confirmed · **Severity:** medium (scientific integrity)
**Root cause.** JSON Schema `minimum`/`maximum` are both **false** for `NaN`, so
a `NaN` task parameter passed the bounds check, and `json.dump(..)` with the
stdlib default `allow_nan=True` then wrote a literal `NaN` token into the
immutable `manifest.json` — invalid RFC 8259, unreadable by `JSON.parse`, `jq`,
or any strict consumer.
**Reproduction (confirmed):** `params={"center_x": "nan"}` accepted before the
fix for both a bounded (`gnina`) and an unbounded (`autodock_vina`) number
parameter.
**Remediation.** `_coerce_param_value` rejects a non-finite float for every
number parameter, bounded or not.
**Regression tests.** `tests/test_round2_security.py::test_a_non_finite_parameter_is_rejected`
and `::test_an_unbounded_float_parameter_rejects_nan`.

### SEC-SER-3 / SEC-SER-5 / SEC-SER-6 / SEC-SER-7 — hardening, recorded

Pydantic coerces `bool` → `int` on integer fields (`gpu_seconds=True` → 1 in an
append-only ledger; `strict=True`/`StrictInt` on the three affected admin
request models is the fix, low impact because the value is already
admin-supplied); SQLite stores a bound `NaN` as `NULL` in a `REAL` column, a
latent trap with no writer today; the schema-epoch guard covers the task and
user databases but not `tool_calls`/`manage_db`; and the "hash is recomputed on
read" invariant lives in `resolve_artifact` and must be preserved by any new
artifact consumer. None is a reachable defect in this revision.

### SEC-RB-3 … SEC-RB-10, SEC-RB-13, SEC-RB-14 — runner build pinning, recorded

The build plane is unevenly reproducible: `pythia_ddg`, `freebindcraft`,
`mpnn` (12 packages), and `pssm_gremlin` (a live conda solve against three
mutable channels) install unpinned or unhashed dependencies; `alphafold` fetches
its hhsuite tarball and `stereo_chemical_props.txt` with no checksum where every
sibling verifies; `gremlin_lh` and `dynamicmpnn` install pinned versions without
`--require-hashes`; one of 39 bases is digest-pinned; and three builds do a full
`git clone` rather than a depth-1 fetch. **Declaration honesty is clean — no
family that uses runtime network or a GPU fails to declare it**, and 17 families
that load model weights without hashing them are noted in §Deferred risks. None
of these is reachable from an unauthenticated request; they are supply-chain
hygiene and belong to a per-family rebuild-and-revalidate cycle.

### SEC-RB-12 — server imports runner-authored Python at request time — RECORDED

One workspace backend (`placer-rfdiffusion`) is `exec_module`d into the web
process. No injection was found (the module path is confined and the syntax is
not user-controlled), but it is the stronger sibling of the accepted
`SEC-WEB-1` risk and is folded into that architectural entry.

### SEC-RB-15 / SEC-RB-16 / SEC-RB-17 — runner argument handling, recorded

`placer-rfdiffusion` splits free-form list parameters on `$IFS` into argv
without dash-guarding (an element like `X --output_dir /tmp/evil` reaches the
upstream parser), reaches its `contig`/`hotspot_res` values into a Hydra
override without the validator its workspace capability applies, and
`pssm_gremlin` formats a shared UniRef90 database in place next to an `ro`
mount. All three are self-inflicted (parameter integrity, own-task results) —
no shell re-parses the values — so they are recorded, not fixed, in this round.

---

## Round 4 — Operations/observability, task-lifecycle integrity

### SEC-LIFE-1 — a duplicated dispatch launched two allocations — FIXED

**Status:** confirmed · **Severity:** high
**Root cause.** Three guards each failed to make dispatch exactly-once: the
worker's entry guard *admitted* `pending|queued|running` instead of claiming the
row; the submission path answered "already queued" only for some statuses; and
finalization was a non-atomic read-then-write. Two workers on one task id
produced two Slurm allocations (two GPU charges, two nodes held), and the second
entry re-created the task record, `rmtree`-ing the input snapshot of the
still-running first execution so the loser died on its checksum verification.
**Reproduction:** two threads through the worker entry path against one row
produced two allocations.
**Remediation.** Entry is now a single atomic compare-and-set claim in
`db.py`, following the shape of the existing `claim_task_recovery` /
`claim_task_cleanup` helpers; the loser is a no-op, and the recovery
re-dispatch re-stamps the claim in the same statement.

### SEC-LIFE-2 — the monthly GPU allowance was a non-transactional read-modify-write — FIXED

**Status:** confirmed · **Severity:** medium
**Root cause.** `set_gpu_monthly_allowance` computed `delta = target - current`
from a read taken without `BEGIN IMMEDIATE` (SQLAlchemy's SQLite driver
autocommits unless told otherwise), unlike its siblings `reset_gpu_credit` and
`reset_all_gpu_credits`. Two racing updates both returned 200 and the period
allowance became the *sum* of what each administrator intended (reproduced:
290 000 where the last writer asked for 200 000).
**Remediation.** The body is wrapped in the same explicit `BEGIN IMMEDIATE`
pattern as its siblings.

### SEC-LIFE-3 — the shared content-addressed upload blob is never pruned — RECORDED

`{SERVER_DIR}/upload/{sha256}.upload` is shared by every task that submitted
those bytes, and nothing in the lifecycle removes it; the delete path cannot
reach it because `StorageResolver` has no concept of the upload root. Growth is
bounded per submission (16 MiB) but not in total, and a hand-pruned blob turns
every historical task that referenced it into a `failed` row on its next run.

### SEC-LIFE-4 — delete destroyed artifacts before the status write — FIXED

**Status:** confirmed · **Severity:** medium
**Root cause.** The user delete path removed artifacts first and persisted the
terminal status second, discarding the write outcome, where maintenance one file
over does claim → delete → complete. With the status write failing, the API
returned 500 with the artifacts already gone.
**Remediation.** The same claim/complete protocol as maintenance, so a crash
between steps leaves a `deleting:*` row that maintenance resumes.

### SEC-OPS-1 — log archives were created with the umask, not an explicit mode — FIXED

**Status:** confirmed · **Severity:** medium
**Root cause.** `zipfile.ZipFile(archive, "x")` and the two `FileHandler`
creations set no mode, so `LOG_DIR`'s POSIX default ACL silently granted a
second host account read on every rotated archive and log file. Unlike
`os.makedirs(mode=...)`, `open()` does not AND the mode into the ACL. Every
other artifact producer in the codebase (`database_backup`, the Slurm wrapper,
the Tool workspace) sets an explicit mode.
**Remediation.** `os.chmod(..., 0o600)` after each creation — `chmod`
recomputes the ACL mask, which is what actually forces owner-only.

### SEC-OPS-7 — log rotation followed a symlink out of `LOG_DIR` and truncated the target — FIXED

**Status:** confirmed · **Severity:** low (hardening)
**Root cause.** `_rotate_logs` globbed `*.log` with no symlink filter, unlike
`_prune_oldest_archives` and the web-side admin log routes. A symlink named
`evil.log` had its size read through the link and its target truncated by
`open("w")`. Reproduced locally.
**Remediation.** Symlinks and non-regular files are skipped before the size check.

### SEC-OPS-2 — the broker-URL redaction missed the common credential forms — FIXED

**Status:** confirmed · **Severity:** low-medium
**Root cause.** `re.sub(r"://:[^@]*@", ...)` only matched `redis://:pw@host`;
`redis://default:pw@host`, `redis://user:pw@host`, and `redis://pw@host` all
wrote the password into a log line the admin route serves over HTTP. A full scan
of the live logs found no occurrence (kombu redacts its own errors), so this is
a latent leak, not an observed one.
**Remediation.** `urllib.parse.urlsplit`-based reconstruction that removes the
password from the netloc for every form redis-py itself parses as a password.

### SEC-OPS-6 — an anonymous probe emitted one warning per request — FIXED

**Status:** confirmed · **Severity:** low (hardening)
**Root cause.** `_task_not_found` logged unconditionally, and it is reached from
`@optional_user` routes, so an unauthenticated caller could add one warning line
per request with no limiter on that path.
**Remediation.** The warning is emitted only when a user is authenticated; the
401/404 answer and its body are unchanged (the round-2 oracle closure is what
makes the status a 404 on the read surfaces, and the ops tests that exercise
this also depend on that change — the log suppression itself is not separately
pinned by a test that fails without it).

### SEC-OPS-8 — token-bearing URLs reached the access log — FIXED

**Status:** confirmed · **Severity:** low-medium
`/compute/reset_password?c=<token>` and `/compute/user_verify?c=<token>` carry
their credential in the query string, because they are browser-navigation links,
and both nginx and gunicorn log the full request line. The gateway's own stdout
log is also unbounded and is *not* covered by `log_rotation`.
**Remediation.** A `map`-gated `access_log ... if=$loggable` keyed on `$arg_c`
suppresses the record for those requests, and the gateway and web services now
declare a bounded `json-file` log driver. Verified by running the rendered nginx
config locally: a token request produced no access-log record.

### SEC-OPS-5 — `result_storyboard.runner_root` silently fell back to the image tree — FIXED

**Status:** confirmed · **Severity:** low
A `RUNNERS_DIR` spelling difference made the containment assertion pass against
the in-image runner tree the operator never configured. The fallback is deleted
and a root outside the configured tree now raises. Checked before removing it:
production always builds runtime roots under the configured root, and the only
three call sites that passed a different `server_dir` are consistent.
**Review note:** the fallback's removal is verified live but is **not** covered
by a test that fails without it — the shipped test asserts the raise, which the
pre-fix code also produced on that input. A test is only meaningful here with
the `RUNNERS_DIR`/root mismatch the fallback actually masked.

### SEC-OPS-3 / SEC-OPS-4 / SEC-OPS-9 — recorded

A stored `verification_resend_at = 0` is falsy and would disable the per-email
resend backoff (unreachable today — the column is only ever server-set); a
transport that accepts-then-defers for every recipient re-sends the whole
unnotified-registration backlog each digest cycle; and live-test fixture paths
are lexically validated but not symlink-resolved (harmless while the fixture
root is operator-owned and `ro`).

---

## Round 5 — live-instance validation and the deployment plane

Rounds 1–4 were source-and-local-test reviews with a small live re-acceptance.
Round 5 ran five read-only audit agents against the **deployed** instance
(`https://revocompute.yaoyy.moe/`) and this repo, then the lead reproduced every
dangerous claim locally before recording it. Dispositions below.

### SEC-LIVE-1 — a resubmission of a cancelled task id destroys a live allocation's state and dispatches a second one — FIXED

**Status:** confirmed vulnerability · **Severity:** high
**Entry point:** `POST /compute/api/post` (or `/compute/api/gremlin`).
**Root cause.** Two defects meet.
1. `_existing_upload_response` (`revocompute/routes.py:1241-1254`) only short-
   circuits `finished` (302) and `pending/queued/running`/`deleting:*` (202).
   A **`cancelled`** row falls through to `_prepare_task_record`, whose
   `shutil.rmtree` of the task's input root and output root
   (`routes.py:1273-1290`) is a *claim-free read-modify-write* — unlike the
   delete path (`routes.py:2543-2573`), which claims first — followed by an
   unconditional `upsert_task(..., status="pending")` (`routes.py:1903`).
   `update_task` refuses to resurrect a terminal row, but `upsert_task` has no
   such guard, so the row is overwritten in place.
2. Cancellation is **asynchronous**: `claim_task_cancellation` is atomic but
   `cancel_compute_resources.delay(...)` runs later and `AsyncResult.revoke`
   cannot terminate a task that is already executing (`routes.py:2345-2356`).
   A worker that has already claimed the row and launched `srun` keeps running.
**Impact.** An identical resubmission — the task id is a pure function of task
type + params + input hashes (`routes.py:1150-1172`), so the same form derives
the same id — re-enters the submit path while the first allocation is still
live. The live job's input snapshot is deleted underneath it (its wrapper
verifies inputs immediately before launch and records
`Immutable input snapshot is missing or changed`), the row is rewritten to
`pending`, and a **second** `run_compute_task` is dispatched for the same id:
two allocations for one task id, with the first one's outcome discarded by the
terminal-status guard. This is the same invariant round 4's `SEC-LIFE-1`
(duplicate dispatch) and `SEC-LIFE-4` (delete-before-status-write) were written
to establish, one transition over.
**Reproduced locally (receipt):** the staged-file/row half shows a `running`
row with `slurm_job_id=4217` becoming `pending` with the `slurm_job_id` still
present; the end-to-end half submits a real `gremlin` task, cancels it, and
resubmits the identical form — `dispatches: 2`, row status `pending`.
**Remediation.** TBD (round-5 fix agents).
**Regression test.** `tests/test_round5_lifecycle_repro.py` (to be promoted out
of scratch form once the fix lands).

### SEC-LIVE-2 — HSTS is inert on the public deployment — FIXED (config + code)

**Status:** confirmed · **Severity:** medium
**Root cause.** The app emits `Strict-Transport-Security: max-age=31536000;
includeSubDomains` only `if request.is_secure` (`revocompute/app.py:145-146`).
The live ingress chain is Cloudflare → gost → cloudflared → host:8081 → nginx
gateway → gunicorn, and it speaks **plain HTTP with no `X-Forwarded-Proto`**
(`docker/nginx/default.conf.template:47` then falls back to `$scheme`). So the
app is told `http`, emits no HSTS, and **Cloudflare substitutes the
neutralizing `strict-transport-security: max-age=0`** — which per RFC 6797
§6.1.1 actively *evicts* any stored policy.
**Impact.** HSTS is worse than absent: a previously pinned browser is unpinned,
and `http://revocompute.yaoyy.moe/compute/login` returns 200 (no redirect), so
there is a live plaintext window for sslstrip/downgrade on any non-preloaded
first visit. `AUTH_COOKIE_SECURE=true` bounds the cookie loss to the downgraded
first hop, so the realistic loss is credential capture by a network attacker.
**Evidence (verified directly).** Live header is `max-age=0`; origin without the
header emits *no* STS; origin with `-H 'X-Forwarded-Proto: https'` emits
`max-age=31536000; includeSubDomains` — the code path works and is simply not
driven.
**Remediation.** TBD (round-5 fix agents): drive `X-Forwarded-Proto` at the
tunnel/gost hop, or add an explicit HSTS-on-public-origin control.

### SEC-LIVE-3 — the origin gateway is published on every host interface, making the client-IP trust set attacker-chosen from the LAN — FIXED (config)

**Status:** confirmed config problem · **Severity:** medium (LAN-reachable)
**Root cause.** `.env.production.v7-slurm:133` sets `GATEWAY_BIND=0.0.0.0`
(required because the tunnel origin is a non-loopback address) and
`TRUSTED_PROXY_IPS` is unset, so the code default `127.0.0.1,172.16.0.0/12`
applies. That default is correct for the *compose bridge* peer, but it also
trusts **every host on the 172.16/12 LAN**.
**Impact.** Any LAN peer can reach the un-TLS'd gateway directly, and because
`CLIENT_IP_HEADERS="CF-Connecting-IP"` is honored from a trusted peer, it can
forge the header to mint a fresh rate-limit identity per request — defeating the
login (5/60 s), register (3/h), forgot-password (3/h) and submission (30/h)
limits. It also reaches the app over plaintext, bypassing Cloudflare entirely.
**Evidence (verified directly).** `ss -ltn` shows `0.0.0.0:8081`; a request to
the loopback origin with `CF-Connecting-IP: 198.51.100.250` is accepted and
appears in `gunicorn-access.log` under that forged address; `X-Forwarded-For`
is *not* trusted for this config (logged as `-`).
**Remediation.** TBD (round-5 fix agents): narrow `TRUSTED_PROXY_IPS` to the
cloudflared host address and bind the gateway to that single interface.

### SEC-LIVE-4 — the bootstrap/reset admin credential is left on disk in a directory readable by an unrelated local account — FIXED (code + operator)

**Status:** confirmed credential-disclosure weakness · **Severity:** high
**Root cause.** `run/revocompute_ctl/admin.py:150-153` and `:169-172` write
`bootstrap-admin-credentials.*` / `reset-admin-credentials.*` into `AUTH_DIR` at
`0600` and **never unlink them on the success path** (only the failure paths at
`:174/:183/:191` do). `AUTH_DIR` carries a `default:user:yinying:rwx` ACL, and
`chmod 0600` does not clear an ACL entry, so the effective mode of the
credential files is `-rw-rwx---+` (670) with `user:yinying:rw-`.
**Impact.** Three current-or-former admin passwords for the public instance sit
in cleartext, readable by an account (`yinying`, uid 1005) that holds no role in
the deployment but does hold the inherited ACL grant. The newest file is dated
2026-09-10 and no later rotation is evidenced.
**Evidence (verified directly).** `getfacl` shows `user:yinying:rw-` +
`mask::rwx`; the files are present and readable from this account without
printing their contents. Records the file names and modes only.
**Remediation.** TBD (round-5 fix agents): unlink the credential file on the
success path (or print it once and never persist it), and stop granting the ACL
to a non-deployment principal.

### SEC-LIVE-5 — the workspace-plugin asset route serves runner-authored JavaScript anonymously on the app origin — RECORDED

**Status:** confirmed hardening gap, not currently exploitable · **Severity:** low
**Root cause.** `GET /compute/api/workspace/assets/<owner>/<plugin_id>/<path:asset>`
(`revocompute/routes.py:388-410`) has **no auth decorator** and serves the
runner-tree asset with the *app* CSP (`script-src 'self' …`), not the sandbox
CSP used for `/_protected_results/`. The descriptor route
(`routes.py:362-385`) is only `@optional_user`.
**Impact.** An anonymous caller can fetch and execute runner-authored JS on the
app origin, in their own session. The privilege boundary is still the
runner-tree trust boundary (SEC-WEB-1), so this is not a new compromise today;
it is a delivery mechanism, and the missing `@login_required` is the cheap
defect. Related: `POST /compute/api/types/<name>/workspace/normalize` executes
runner-authored Python (`exec_module`, `plugins/__init__.py:264-277`) in the web
process on request input.
**Evidence (verified directly).** Anonymous `GET` returns `200
text/javascript` with the app CSP; the descriptor returns `200 application/json`.

### SEC-LIVE-6 — the `/_protected_results/` sandbox and the artifact path are sound — DISPROOF

Every path that serves runner **artifact** bytes is covered: the nginx
`/_protected_results/` block (`internal`, `disable_symlinks on`, method-gated,
`Content-Security-Policy: sandbox`, `nosniff`) and both artifact-route modes
(which set `sandbox` themselves). `resolve_artifact` matches the request path
against the task's own manifest, re-hashes, rejects symlinks and `nlink != 1`,
and `get_task_root` is keyed by the caller's `storage_key`. Anonymous
`GET /_protected_results/...` → 404. Every artifact response carries
`Cache-Control: private, no-store` and Cloudflare reports `cf-cache-status:
DYNAMIC`, so no cross-user cache leak. Encoded and literal traversal both 404.
The storyboard route is the one same-origin-script exception, and it is the
already-tracked SEC-WEB-1 (`storyboard_declaration` restricts the entrypoint to
a local `.js`, so no HTML storyboard is possible).

### SEC-LIVE-7 — the deployed F2 rate-limit bypass could not be attributed publicly — OPEN QUESTION

A forged `CF-Connecting-IP` through the public edge returns **403** (Cloudflare
blocks it before the origin); without the header the request reaches the app
normally. So no *public-internet* caller can choose the limiter identity today
— which matches `trusted_client_ip()`'s design. The LAN path in SEC-LIVE-3 is
the live one. Attribution through the public edge would require access to the
Cloudflare zone settings and the gost configuration; that is an operator
question, recorded rather than resolved.

---

## False positives worth documenting

- **"The public `/compute/api/auth/login` limiter can be bypassed by rotating a
  forwarding header."** Disproven for the public path in round 5: a request
  bearing a forged `CF-Connecting-IP` is refused by Cloudflare with 403 before
  it reaches the origin, and without the header the limiter behaves normally.
  The real exposure is the LAN-reachable origin (SEC-LIVE-3), not the public
  endpoint.
- **"`session.get()` staleness is an authorization primitive."** Disproven: the
  SEC-LIFE-2 SQLAlchemy session is used only in handlers that immediately
  `select`/`update` on it, SQLAlchemy refreshes any UPDATE'd row, and the
  session is `close()`d in `finally`.
- **"The `%post`-installed `/app` mount is still shadowable through a
  normalization mismatch."** Disproven in round 3 and still holds: the mount
  target check normalizes a copy, and all 39 production mounts are plain
  absolute paths.
- **Reachability of the runner-authored workspace-plugin JS and storyboards.**
  Neither crosses a boundary a user could not already cross by changing
  `docker/runners/`; they are recorded as delivery mechanisms, not escalations.
- **"`--containall` leaves the invoking account's `$HOME` mounted read-write."**
  Disproven live. `--containall` gives the container a private tmpfs `$HOME`;
  a sentinel file created in the host home was invisible inside the container,
  and `/proc/self/mountinfo` showed `home` on a 64 MiB tmpfs, not a host bind.
  The `WARNING: Error changing the container working directory … /home/<user>`
  message reflects the *host* cwd name leaking into a warning, not a mount.
  (`--no-home` was added anyway, matching the Tool runtime.)
- **"`apptainer exec` drops the instance's isolation, so the Tool child shares
  the host network."** Disproven live on this host. An instance started with
  `--containall --no-home --net --network none` gives `exec` a fresh netns
  (`net:[4026534780]`, only `lo`, `127.0.0.1:6380` refused) and the same
  `--containall` filesystem view. The control case confirms the mechanism: an
  instance started *without* `--net` leaks the host netns and reaches
  `127.0.0.1:6380`. `--net`/`--containall` on `exec` is accepted but a no-op.
  No `exec` argv change was made.
- **"A Tool child can replace an exchange slot with a symlink so
  `_reset_exchange` deletes through it."** The delete-through-a-symlink
  mechanism is real (reproduced: `rm -rf` of a directory a slot symlinked to),
  but not reachable by the child: the child holds `rw` only on `/tool/output`
  and `/tool/scratch` and `ro` on `/tool/input`, so it cannot replace a slot
  directory. Simulating container-only writes into those slots left the victim
  tree intact. `_reset_exchange` was not changed.
- **Bandit B608 (SQL) in `manage_db.py`.** The interpolated identifiers are
  module-level field constants or names read back from
  `PRAGMA table_info`; every value is bound.
- **Bandit B108 in `slurm_runner.py`.** The flagged `scratch_path` is
  `{task_workspace_root}/scratch` — a hardcoded sibling of `outputs`, not a
  `tempfile.mkdtemp`-ed or user-named path.
- **SSRF.** No code path in `revocompute/` or `docker/tools/` resolves a
  URL or hostname derived from user input. Every outbound destination is
  code- or operator-owned. Uploaded specifications that name URLs or absolute
  paths are rejected at parse time.
- **Committed secrets.** `git log -p` across the full history found no private
  keys, no `ghp_`/`xox*`/`sk-`/`re_` tokens. The single `AKIA` hit is the
  amino-acid substring `…QKAKIAQEVTEVIARNA…` in an alignment fixture.
- **Result-viewer XSS.** Every runner-derived string reaching the DOM goes
  through `textContent` or `escapeHtml`; page data is injected as inert
  `<script type="application/json">`; artifact bytes are served as attachments
  with `Content-Security-Policy: sandbox`. No `eval`, `new Function`,
  `insertAdjacentHTML`, or `document.write` exists in the frontend.

---

## Deferred risks

1. **Runner dependency CVEs.** Runner locks carry genuinely vulnerable pins —
   `restrictedpython==7.4` (sandbox escapes, fixed in 8.0+; the HPC-facing
   versions are 8.0–8.4), `dgl==2.4.0` (pickle-deserialization RCE, no fix),
   `transformers==4.57.6` (RCE on model init), and every `torch` pin
   (CVE-2025-32434 `weights_only=True` bypass). These live in GPU runner
   images, not the server, and each upgrade changes a scientific stack. They
   need a per-family rebuild-and-revalidate cycle, which is out of scope here.
2. **Result artifact budget.** Publish walks the whole runner output tree and
   hashes every file; every artifact read re-hashes the file with no cache and
   no size ceiling. One tenant can burn server CPU by requesting a large
   artifact repeatedly. Bounded by task admission and the 16 MiB upload limit
   but not by result size.
3. **Storyboard same-origin script trust** (SEC-WEB-1 above).
4. **Broker password in container arguments** (SEC-SUPPLY-1 above).
5. **`AUTH_SECRET_KEY` had no supported way to be set** in the shipped
   configuration, so the session-signing key was regenerated on every
   web-container restart, invalidating sessions and email links on redeploy.
   Round 2 added the compose plumbing and a `setup` generator; the remaining
   action is for the operator to run `setup` once so an existing deployment
   starts persisting a stable key (until then the value is still ephemeral).
6. **CI pinning.** `docs.yml` pins every Action by mutable tag, including the
   two in the `pages: write` / `id-token: write` job; `tests.yml` pins
   `setup-python` and `upload-artifact` by tag. No untrusted PR trigger, no
   `secrets.`, no cache, and no artifact download reach a privileged context,
   so the exposure is supply-chain hygiene rather than an exploit path.
7. **`starter-suid` is now a hard prerequisite for every Slurm task.** The
   unprivileged `--net --network none` path needs it (verified: Apptainer
   refuses `--net` with "network requires root or a suid installation with
   /etc/subuid --fakeroot" without it). The Tool runtime already required it;
   now so does every Runner task. If it is missing on a compute node, every
   task fails rather than degrading — a deliberate fail-closed choice, but a
   deployment prerequisite that must be verified before promotion.
8. **Runner mount values are validated but stored unnormalized.** The
   containment check normalizes a copy, so a manifest that passes could still
   hand Apptainer a different spelling of an allowed target. Harmless today
   (all 39 mounts are plain absolute paths); worth storing the normalized form
   when the mount type is next touched.
9. **The CAPTCHA is a visible maths question.** The fix removes the free answer
   from the token, but solving it programmatically remains trivial. It bounds
   scripted registration only in combination with the 3/hour/IP limit. A real
   challenge would be a separate design decision.
10. **Runner build reproducibility is uneven** (round 3, `SEC-RB-3…10`).
    `pythia_ddg`, `freebindcraft`, `mpnn`, and `pssm_gremlin` install unpinned
    or unhashed dependencies, `alphafold` fetches two artefacts without a
    checksum, and one base of 39 is digest-pinned, so two builds of one `.def`
    need not be the same image — which undercuts the `definition_sha256`
    provenance the receipt rests on. Needs a per-family lockfile pass.
11. **17 of the runner families load model weights without hashing them.**
    Every weight mount is `ro` (checked across all 39), so this is an
    operator-boundary integrity gap rather than a live path, but it becomes
    attacker-chosen pickle weights if a weights directory is ever writable.
    `common/verify_model_asset.sh` already exists and the remaining families
    should adopt it.
12. **The shared content-addressed upload blob is never pruned**
    (`SEC-LIFE-3`). Growth is bounded per submission (16 MiB) but not in total,
    and because it is shared by content, deleting a task cannot delete the blob
    — a sweep must delete only blobs no task row references.
13. **A log source outside `LOG_DIR` is invisible to rotation.** The gateway's
    stdout log is now bounded by a compose log driver, but `log_rotation` only
    globs `${LOG_DIR}/*.log`, so any future log source outside that tree
    inherits unbounded growth unless its own driver is set.
14. **`SEC-RB-15/16/17` runner argument handling.** `placer-rfdiffusion` splits
    free-form list parameters on `$IFS` into argv without dash-guarding and
    reaches `contig`/`hotspot_res` into a Hydra override without its workspace
    capability's validator; `pssm_gremlin` formats a shared UniRef90 database in
    place. All self-inflicted (own task's parameters and results), so recorded
    rather than fixed.

---

## Tooling executed

| Tool | Scope | Result |
| --- | --- | --- |
| Bandit | `revocompute/` | 0 high; 5 medium B608 (false positive), 3 medium B108 (false positive) |
| pip-audit | server venv + every runner lock | server clean; runner-image findings above |
| Three review agents | full diff | one P0 (admin reset 500), one availability regression, one incomplete containment check — all fixed before delivery |
| Manual data-flow review | auth, routing, storage, scheduler, container, frontend | findings above |
| Live Apptainer probes | this host, read-only, against deployed SIFs | netns shared before fix; fresh netns after; private `$HOME` confirmed |
| Live container introspection | deployed `bioemu` SIF | confirmed the hosted MMseqs2 default |
| Production benign checks | `revocompute.yaoyy.moe` | headers/CSP/HSTS/cookie flags; the CAPTCHA disclosure reproduced; origin port reachable on the private interface but not from the public host |
| Git history secret sweep | all refs | clean |
| GH Actions review | `.github/workflows/` | no privileged untrusted trigger, no secrets |
| Round 2 audit agents (4) | Tool runtime + validators; quotas/DoS; authz matrix; deployment plane | `SEC-TOOL-*`, `SEC-DOS-*`, `SEC-AUTHZ-*`, `SEC-DEPLOY-*` |
| Round 3 audit agents (2) | runner `.def`/`%post`/pinning and `run.sh` argv; serialization and schema evolution | `SEC-RB-*`, `SEC-SER-*` |
| Round 4 audit agents (2) | operations/observability/logs; task-lifecycle integrity and availability | `SEC-OPS-*`, `SEC-LIFE-*` |
| Round 2–4 fix agents (5) | the confirmed findings, each with a pre-fix failing test | all fixes below |
| Bandit (re-run) | `revocompute/` after all fixes | unchanged: 0 high, same 8 medium dispositions |
| pip-audit (re-run) | server venv + every runner lock | server clean |
| Live Apptainer probes (extended) | this host, read-only | `apptainer exec` **does** inherit the instance's netns and `--containall` (`--net` on `exec` is a no-op, not a requirement); a host-netns instance leaks `127.0.0.1:6380`; a symlinked exchange slot is only reachable by the server, not the Tool child |

Semgrep was unavailable on this host (no wheel for the installed glibc);
its intended role — taint tracking from request input to shell and filesystem
— was covered by the manual data-flow review instead.

---

## Verification

- `tests/ -m "not browser"` after all four rounds and the pre-PR review:
  **1270 passed, 19 skipped, 5 failed**
  — the five are `test_process_isolation.py` and they are **environmental, not
  code**: `run/restart.sh` resolves `REVODESIGN_PYTHON` to the system `python3`,
  which lacks the project dependencies, so the controller subprocess dies with
  `ModuleNotFoundError: No module named 'bibtexparser'`. Run with the venv, the
  whole file passes:
  `REVODESIGN_PYTHON=.venv/bin/python .venv/bin/python -m pytest tests/test_process_isolation.py -q` → **44 passed**.
  Before this work the same file failed 4 of its cases; every one of those four
  is a pre-existing environmental failure, and the fifth
  (`test_restart_accepts_integer_command_line_counts`) is a round-2 test that
  needs the same venv prefix. No code failure is hidden by the exclusion.
- Before delivery, three independent review agents examined the full diff
  (auth/request path; deploy/runner; docs and test integrity). Five findings
  were acted on: the compose `CLIENT_IP_HEADERS` default still named the
  appended, client-influenced header first (the source default had been fixed
  but the shipped value had not); the trusted-proxy tests rotated only the
  header the source default tries first, so they passed for the wrong reason;
  `TRUSTED_PROXY_IPS` was documented but unreachable from the compose file; a
  `user_storage_limit` rejection did not attempt the reclaim its global sibling
  does; and a select-all batch delete above the new cap failed wholesale instead
  of chunking. Each is fixed here. Two documentation contradictions the same
  pass found (`AUTH_SECRET_KEY` still described as ephemeral in two pages, a
  runner-root fix claimed to be covered by a test that does not fail without it)
  are corrected rather than papered over, and the latter is now recorded as
  verified-live-but-not-test-pinned.
- After rounds 3 and 4: **122 passed** on the lifecycle/ops gates, plus each
  new test confirmed to fail against the pre-fix tree (with only `revocompute/`
  stashed) before the fix landed.
- Each fix was shown to fail before it was made, by the strongest available
  evidence rather than by assumption:
  - API-key escalation and CAPTCHA disclosure were reproduced on the **pre-fix
    production deployment** (`GET /api/auth/token` with `X-API-Key` → 200;
    token payload decoded to `{"answer":15,…}`) and then re-checked on the
    redeployed revision (403; payload has no answer).
  - The network-namespace share and the mount-containment bypass were shown
    live/numerically against the old code by the verification pass.
  - **Reproduced live in this review**: the self-modifying wrapper mechanism
    (a container-writable host script executed an appended line), the
    `exec`-inherits-the-instance-namespace behaviour (control case leaked
    `127.0.0.1:6380`), the delete-through-a-symlink `_reset_exchange`
    mechanism (with the reachability disproof that makes it a false positive),
    the `NaN` parameter acceptance, the deep-nesting 500, the token-in-log
    access-log record, and the log-rotation symlink truncation.
  - The remaining regression tests were written alongside their fixes and fail
    if the fix is reverted.
- `bandit` and `pip-audit` re-run after the fixes: unchanged dispositions.
- `mkdocs build --strict` clean after every documentation change.
- No frontend file changed, so the browser contracts are unaffected; they were
  passing at baseline and were not re-run here (they need Xvfb on this host).

### Security tests added

| Test | Property |
| --- | --- |
| `test_auth.py::test_api_key_cannot_mint_a_bearer_session` | an API key never becomes a web-login session |
| `test_auth.py::test_link_token_purposes_are_distinct` | the four token classes do not interchange |
| `test_auth.py::test_verification_link_survives_an_unrelated_password_reset` | verification is not stranded by a token-version bump |
| `test_auth.py::test_captcha_token_does_not_disclose_its_answer` | the answer is not in the token |
| `test_auth.py::test_captcha_is_single_use` | challenges cannot be replayed |
| `test_admin.py::test_admin_password_reset_ends_existing_sessions` | an admin reset ends live sessions |
| `test_slurm_runner.py::test_render_apptainer_isolates_network_unless_declared` | undeclared network is isolated |
| `test_plugin_discovery.py::test_runner_yaml_env_names_and_mounts_are_validated` | env names and mount targets cannot escape their contract |
| `test_tasks.py` request-header test | credential headers are never persisted |
| `test_security_hardening.py` CAPTCHA tests | Redis and fallback paths both fail closed |
| `test_round2_security.py` (11 tests) | the batch-delete cap, the two id-existence oracles, cookie logout, the per-tenant Tool storage share, guest compute denial, deep JSON nesting, non-finite parameters |
| `test_tool_isolation.py` (5 tests) | the Tool output ceiling at copy-back, pre-exec rlimits, whole-group kill on timeout, server-owned provenance |
| `test_trusted_proxy.py` (2 tests) | a forwarded header is honored only from a trusted peer |
| `test_config.py` runner-identity tests | non-decimal spellings of uid 0 are rejected |
| `test_process_isolation.py` deploy tests | system roots rejected as `AUTH_DIR`, command-line counts must be integers, `AUTH_SECRET_KEY` reaches web only |
| `test_slurm_runner.py::test_wrapper_is_outside_the_container_writable_view` | the host allocation wrapper is not container-writable |
| `test_plugin_discovery.py` workflow tests | every stage declares both capabilities; `/app` mounts are reserved |
| `test_round4_ops.py` (6 tests) | symlink-safe rotation, owner-only archives and log files, broker-URL redaction, anonymous-probe logging, storyboard root containment |
| `test_round4_lifecycle.py` + `test_race_conditions.py` (7 tests) | exactly-once dispatch, locked allowance update, claim-before-delete ordering |

---

## Live acceptance on the target host

Redeployed the reviewed revision to the Slurm deployment:

```bash
REVODESIGN_PYTHON=.venv/bin/python \
REVODESIGN_SERVER_ENV=.env.production.v7-slurm \
  bash run/restart.sh restart --mode=dev --use-proxy --keep-gateway
```

- All six services healthy; maintenance lifted; deploy stamp written.
- Deployed code verified to be the reviewed revision (`_SESSION_PURPOSE`,
  `require_web_login` on the token route, `--net --network none` present in the
  container).
- **Both headline fixes confirmed live against the deployment:**
  - `GET /compute/api/auth/captcha` token now decodes to
    `{"purpose":"captcha","jti":"…"}` — no answer.
  - `X-API-Key` → `GET /compute/api/auth/token` returns **403** (was 200
    before the fix, which minted a full web-login session).
- `live-test --runner gremlin --use-proxy` → **PASS** (`gremlin/smoke`):
  Slurm job `49069`, walltime 174 s, exit 0, 126 artifacts, output check
  passed for `alignment` / `pssm` / `coupling_matrix`, executed as
  `revodesign` (uid 129, gid 137), max RSS 45 GB, 947 s user CPU.
  `runner-status --runner gremlin` now reports READY with a current receipt.
- The API key minted for the live check was revoked, its temp files deleted,
  and no live-test container or Slurm job was left behind.

### Re-acceptance after the round-2–4 fixes

The review's later rounds changed the runner adapter, the task lifecycle, and
the Tool path, so the target-host acceptance was re-run against the current
revision:

```bash
REVODESIGN_PYTHON=.venv/bin/python \
REVODESIGN_SERVER_ENV=.env.production.v7-slurm \
  bash run/restart.sh restart --mode=dev --use-proxy --keep-gateway
```

- All six services healthy; maintenance lifted; deploy stamp written.
- The deployed web image carries this revision (`revocompute/client_ip.py`
  present, the guest gate and the oracle closure present in `routes.py`).
- `GET /compute/api/auth/captcha` still returns a token whose payload carries
  only `purpose`/`jti` — the CAPTCHA fix is intact after the round-4 refactors.
- `live-test --runner gremlin --collection smoke --use-proxy` → **PASS**:
  Slurm job `51581`, walltime ≈178 s, 126 artifacts, receipt
  `gremlin/1790390708665350201-smoke.json` in state `PASSED`, executed as
  `revodesign` (uid 129, gid 137), 8 CPUs / 64 GB on `normal`.
- `live-test --runner mpnn --collection smoke --use-proxy` → **PASS**: all six
  smoke cases (`minimal-hypermpnn`, `minimal-proteinmpnn`, `minimal-solublempnn`,
  `minimal-ligandmpnn`, `minimal-lasermpnn`, `minimal-thermompnn`) passed,
  walltime 129 s, Slurm jobs `52088`–`52099` on `normal`, executed as
  `revodesign` (uid 129, gid 137); receipt
  `mpnn/1790398261591019869-smoke.json` in state `PASSED`, and
  `runner-status --runner mpnn` now reports `READY`. **This is the live proof
  for SEC-RB-11:** `minimal-ligandmpnn` (job `52094`, 18.8 s) loaded
  `ligandmpnn_v_32_010_25.pt` from the migrated `/mnt/db/weights/ligandmpnn/model_params`
  target and produced 9 artifacts including a packed structure. The case
  declares and uses **no GPU** (`allocated_gpus_on_node: ""`,
  `visible_gpu_devices: ""`, `accelerator_metrics_available: false`), only 8
  CPUs and 332 MiB max RSS — confirming the family is CPU-only.
- The queue was empty afterwards; no container, Slurm job, or temp credential
  was left behind.

**Deployment topology note (round 5).** Two compose projects are running on
this host: `server-slurm` (this repo, published on `0.0.0.0:8081`, the one the
public URL reaches) and a stale `server` project from `/repo/REvoDesign` whose
gateway also listens on `0.0.0.0:8080` but serves a different app entirely
(`/compute/login` → 404; its image is 4 days old). The public path is the
`server-slurm` project. The stale project is an operator cleanup item, not a
code finding, and was left untouched.

**Re-accepted here:** the `mpnn` LigandMPNN weight-path move (`SEC-RB-11`) is
live-validated above. `mpnn` is a CPU-only family — it declares no
`requires_gpu` and `run.sh` passes `--device cpu`
(`docs/reference/runtime-families.md` records it as CPU torch) — so no GPU
allocation was ever required for this validation. The `placer-rfdiffusion` and
`pssm_gremlin` argument-handling notes remain deferred for other reasons.

Note: the managed test credential was exercised only against this host's own
gateway (`127.0.0.1:8081`) to verify the fixes, from a mode-`0600` temporary
file that was deleted afterwards; no destructive or high-volume request was
made at any point.

---

## Remaining architectural risks

Ranked by what a future change would most plausibly get wrong.

1. **Runner authority is declared, and the declaration is the whole control.**
   `requires_network` is now enforced, but every other authority a Runner has
   (mounts, env, entrypoint, resource class) is likewise a declaration in a
   developer-owned manifest. The pattern works only while the runner tree is
   treated as trusted build input; anything that makes that tree writable by a
   less-trusted party turns each declaration into an escalation primitive.
2. **All tasks of all users share one uid and one filesystem.** Path
   containment is enforced logically (`safe_join`, symlink and `nlink` checks)
   but not by permissions: the result tree carries default modes and the runner
   identity owns every user's inputs and results. A Runner escape therefore
   reaches other users' data. Per-task uids or a permission boundary on the
   user roots would be the structural fix.
3. **The result viewer trusts runner-authored JavaScript same-origin**
   (SEC-WEB-1). The sandboxed viewer shell already exists and is the natural
   home for storyboards.
4. **The broker credential is passed as a process argument** (SEC-SUPPLY-1).
   `AUTH_SECRET_KEY` now has supported plumbing; the operator must run `setup`
   once for an existing deployment to start persisting it.
5. **CI Actions are tag-pinned in the privileged Pages job.**
6. **The runner build plane is not reproducible, and the declaration model
   assumes it is.** A receipt binds `definition_sha256` to a validated SIF, but
   four families resolve dependencies live at build time and one base of 39 is
   digest-pinned, so the definition hash does not actually imply the same image
   (round 3). The declaration pattern in risk 1 and the provenance pattern here
   both depend on the build being deterministic.
7. **Two dispatch-side binds couple the host and the container more than the
   isolation flags suggest.** The wrapper no longer lives in the writable output
   directory, but the task container still writes into a host directory the
   worker reads, and the worker still runs each Task's host-side steps as the
   account that owns every user's data. The structural fix is the per-task
   identity in risk 2, not another check.

---

## Manual re-checks worth performing before promotion

These are the properties this review could not close by inspection or local
test, and that a live pass should confirm:

1. `restart.sh setup` on the deployment host persists `AUTH_SECRET_KEY` and the
   key is stable across a restart (the value must appear in the env file at
   0600 and not in any log).
2. `restart.sh restart --mode=...` with the round-2 `AUTH_DIR` and
   command-line-count validation accepts the real `.env.production.v7-slurm`
   (both were tested against safe example values, not the live file).
3. `mpnn` live acceptance with the migrated LigandMPNN weights path —
   **closed** under "Re-acceptance after the round-2–4 fixes" (CPU-only family;
   no GPU allocation needed).
4. The empty `TRUSTED_PROXY_IPS` fallback: confirm the production host proxy is
   inside the default trust set (loopback or the compose bridge) so forwarded
   client addresses still distinguish users for rate limiting. If the host
   proxy is elsewhere, set `TRUSTED_PROXY_IPS` explicitly.

---

## Recommended security invariants for future Runner development

1. Declare every capability the Task can exercise on its default path — not
   only when a user opts in. Understating it now breaks the Task.
2. Bind host mounts read-only. A writable mount is a design review item.
3. Take user data through the named-role manifest (`task_input`/`_parse_param`),
   never by parsing filenames, and never `eval` a parameter.
4. Keep scientific interpretation in the Runner and transport/format safety in
   Core; do not add a second upload-acceptance path.
5. Treat everything the Runner writes as untrusted content on the way out:
   the Server hashes it, confines it, and serves it as an attachment.
6. Pin upstream revisions and weight checksums; the build provenance contract
   already requires it.
7. Assume the container has loopback-only network, no `$HOME`, a task-private
   `/tmp`, and no host environment unless the Task declared otherwise.
8. Never let a Task artifact live where the container can rewrite it. The
   allocation wrapper proved that "the worker wrote it" and "the container
   cannot write it" are different claims.
9. Reject input the schema cannot describe. JSON Schema `minimum`/`maximum` are
   both false for `NaN`, so a bound is not a finiteness check; a parse error
   the decoder reports as something other than `ValueError` (like
   `RecursionError`) is still malformed input.
10. When a new field carries authority, decide whether it is server-owned or
    caller-declared, and never let a caller-declared value sit in a
    server-owned slot (the Tool `backend` provenance).
