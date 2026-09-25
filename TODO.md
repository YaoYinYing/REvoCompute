# REvoCompute Comprehensive Security Review

Control document for the defensive security review of the next `main`
revision. Each workstream below records what was examined, what was found, and
the disposition.

**Reviewed revision:** `8603cec` (`feat(runner): enforce the Runner
change-impact contract (#28)`) plus the fixes committed on
`security/comprehensive-review`.

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
**Regression test:** `tests/test_auth.py::test_link_tokens_are_not_accepted_as_sessions`.

### SEC-AUTHN-3 — Verification links could not be revoked — FIXED

**Status:** confirmed weakness · **Severity:** medium
**Root cause:** the verify-email payload omitted `ver`, so the token-version
check in `load_current_user` could never fail for it — and
`validate_email_token` did not consult the user record at all.
**Impact:** logout, password change, and admin password reset
(`increment_token_version`) could not invalidate a leaked verification link
for its full 2-day life.
**Remediation:** the token carries `ver`, and `validate_email_token` accepts an
optional `UserDatabase` and compares it.
**Regression test:** covered by the token-class test above; the `ver` binding
is also exercised by `tests/test_admin.py::test_user_verify_endpoint`.

### SEC-AUTHN-4 — CAPTCHA answer disclosed in the returned token — FIXED

**Status:** confirmed vulnerability · **Severity:** medium
**Root cause:** `generate_captcha` embedded `{"answer": ...}` in the signed
token. itsdangerous payloads are base64, not encrypted.
**Impact:** the only anti-bot control on registration was defeated by decoding
the first token segment, turning registration into a pure rate-limit exercise
(3/hour/IP) and enabling scripted account creation. Prerequisite:
`ENABLE_REGISTER=true` (default false).
**Remediation:** the expected answer now lives server-side (Redis, with a
per-process fallback) keyed by the token's `jti`; the token carries only the
nonce; a Redis Lua compare-and-delete consumes it atomically.
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
or `rw`, and `/workspace` and `/tmp` are reserved container targets. All 21
production mounts pass unchanged (all `ro`, all absolute).
**Regression test:** same as SEC-RUNNER-2.

### SEC-SECRETS-1 — Deployment env file created world-readable — FIXED

**Status:** confirmed weakness · **Severity:** medium
**Root cause:** `cmd_setup` used `shutil.copy`, which preserves the tracked
`.env.example` mode (0644), and then `ensure_redis_password` appended the
generated `REDIS_PASSWORD` to that file.
**Impact:** the broker credential was readable by every local user until an
operator ran the documented manual `chmod 600`.
**Remediation:** the file is created with `O_EXCL` at mode 0600.
**Note:** `.env.production.v7-slurm` on this host is already 0600.

### SEC-PRIVACY-1 — `Proxy-Authorization` persisted with the task row — FIXED

**Status:** confirmed weakness · **Severity:** low
**Root cause:** `_REDACTED_HEADERS` was a three-entry denylist.
**Impact:** a credential injected by an authenticating forward proxy was
persisted in the task row and written to the worker log.
**Remediation:** the denylist now also covers `proxy-authorization` and CSRF
header names.
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

## False positives worth documenting

- **"`--containall` leaves the invoking account's `$HOME` mounted read-write."**
  Disproven live. `--containall` gives the container a private tmpfs `$HOME`;
  a sentinel file created in the host home was invisible inside the container,
  and `/proc/self/mountinfo` showed `home` on a 64 MiB tmpfs, not a host bind.
  The `WARNING: Error changing the container working directory … /home/<user>`
  message reflects the *host* cwd name leaking into a warning, not a mount.
  (`--no-home` was added anyway, matching the Tool runtime.)
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
5. **`AUTH_SECRET_KEY` is unset** in the shipped configuration, so the
   session-signing key is regenerated on every web-container restart. This
   invalidates sessions and email links on redeploy — an availability/UX
   property, not a leak, and the ephemeral key is what the tests assert.
6. **CI pinning.** `docs.yml` pins every Action by mutable tag, including the
   two in the `pages: write` / `id-token: write` job; `tests.yml` pins
   `setup-python` and `upload-artifact` by tag. No untrusted PR trigger, no
   `secrets.`, no cache, and no artifact download reach a privileged context,
   so the exposure is supply-chain hygiene rather than an exploit path.

---

## Tooling executed

| Tool | Scope | Result |
| --- | --- | --- |
| Bandit | `revocompute/` | 0 high; 5 medium B608 (false positive), 3 medium B108 (false positive) |
| pip-audit | server venv + all 21 runner locks | server clean; runner-image findings above |
| Manual data-flow review | auth, routing, storage, scheduler, container, frontend | findings above |
| Live Apptainer probes | this host, read-only, against deployed SIFs | netns shared before fix; fresh netns after; private `$HOME` confirmed |
| Git history secret sweep | all refs | clean |
| GH Actions review | `.github/workflows/` | no privileged untrusted trigger, no secrets |

Semgrep was unavailable on this host (no wheel for the installed glibc);
its intended role — taint tracking from request input to shell and filesystem
— was covered by the manual data-flow review instead.

---

## Verification

- `tests/ -m "not browser"`: 1205 passed, 19 skipped. The four
  `test_process_isolation.py` failures are the documented environment
  regression (`run/restart.sh` resolves `REVODESIGN_PYTHON` to a `python3`
  without project dependencies); they pass with
  `REVODESIGN_PYTHON=.venv/bin/python` and are unrelated to this change.
- New regression tests all fail against the pre-fix code.
- `bandit`, `pip-audit`, and the git-history sweep re-run after the fixes.
