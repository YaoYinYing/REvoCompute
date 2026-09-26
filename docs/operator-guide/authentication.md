# Authentication and Accounts

Bearer tokens, API keys, roles, registration, and admin user management.
All state-changing endpoints require a Bearer token or API key.

The server uses Bearer-token authentication (replaces the old HTTP Basic Auth + `users.txt` model).
Login links may include a URL-encoded local path, for example
`/compute/login?return_to=%2Fcompute%2Fcreate_task%3Ftask_type%3Dgremlin`;
successful login returns there. External return URLs are rejected.

## How auth works

- **Browser access**: Logging in sets an `HttpOnly` cookie so page navigations
  (dashboard, profile, create task) are authenticated without manual header
  management.  Already-authenticated visitors to `/login` or `/register` are
  redirected to the dashboard.
- **API access**: Clients send `Authorization: Bearer <token>` for full access,
  or `X-API-Key: <key>` for long-lived programmatic access with restricted
  privileges (tasks only — no profile changes or admin actions).
- **Roles**: Three account types — `admin` (full access), `user` (registered
  user with API access), `guest` (publicly shared account, no compute).
  Guest accounts cannot submit tasks or preflight, run Tools, change
  passwords, manage API credentials, or submit compute for a Runner.
- **Logout**: `POST /compute/api/auth/logout` clears the server-side cookie on
  every path.  A cookie-only request is not granted the token-version bump
  (that write stays behind the Bearer gate as a CSRF control), so end the
  session from a page holding a session token for a full invalidation.
- **CAPTCHA**: Self-registration requires solving a math challenge to prevent
  automated signups.  The CAPTCHA token expires after 5 minutes and is
  regenerated after each failed attempt.

## Signing key

`restart.sh setup` generates `AUTH_SECRET_KEY` into the env file and every
service reads it, so the key is stable across restarts and sessions and emailed
links survive a redeploy.  When the variable is unset the app falls back to a
key generated once per process, which `--preload` shares across the forked
workers.

Gunicorn workers are started with `--preload` so that fallback key is
generated once in the arbiter before forking.  Without this, each worker
independently generates its own signing key, making tokens from one worker
fail validation on another.

Rotating `AUTH_SECRET_KEY` logs everyone out and invalidates outstanding
verification and password-reset links.  That is the intended effect of a
rotation; it is not a side effect of restarting.

## First run

If the user database is empty, every username in the required `ADMIN_USERS`
list is created automatically:

- Passwords: generated separately and printed once by
  `restart.sh`. Change each after first login.

Bootstrap passwords must not be stored in the env file. They are transient
first-boot values supplied by the restart script only.

`reset-passwd` rotates an existing account from the deployment host. It creates
a timestamped auth-database backup under `${SERVER_DIR}/backups`, invalidates
that user's existing bearer tokens, and writes the new username/password pair
to a mode-0600 file under `AUTH_DIR`. The password itself is never printed.

Set `ENABLE_REGISTER=true` and configure either SMTP or Resend to allow
self-registration. Registration requires full name, affiliation, academic
position, and PI name. These fields appear on the user's profile page and in
the admin user-control system. Users receive a verification email and must be
verified before use. Without a working email backend, use the admin API to
create accounts.

## API authentication

```bash
# Login to get a token
curl -X POST -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"..."}' \
  "http://<server-ip>:<port>/compute/api/auth/login"

# Use the token for subsequent requests
curl -H "Authorization: Bearer <token>" \
  "http://<server-ip>:<port>/compute/api/auth/me"

# Logout (clears the auth cookie)
curl -X POST -H "Authorization: Bearer <token>" \
  "http://<server-ip>:<port>/compute/api/auth/logout"
```

## Admin user management

```bash
# Admin creates a new user (requires admin token)
curl -X POST -H "Authorization: Bearer <admin-token>" \
  -H "Content-Type: application/json" \
  -d '{"username":"newuser","email":"user@example.com","password":"...","role":"user"}' \
  "http://<server-ip>:<port>/compute/api/auth/admin/users"
```

`role` may be `admin`, `user`, or `guest` and is the sole authorization
authority. Server setup creates the current user schema directly and does not
alter older database layouts.

Admins cannot ban or delete their own account.  Direct self-ban/self-delete
requests return HTTP 400, and batch Disable/Delete skips the acting admin while
still applying the requested action to other selected users.

The dashboard header also links administrators to `/compute/logs`. That
standalone page loads only the selected active Gunicorn access, Gunicorn error,
Celery worker, structured operational-event, or maintenance log and streams it
incrementally. Its lazy file tree lists rotated ZIP archives under those logs and permits
individual downloads; arbitrary filesystem paths are not exposed.

## API keys (programmatic access)

Long-lived API keys are available for scripted/programmatic access. Generate and revoke
them from the **API Key** section of the Profile page (`/compute/profile`), or via the API:

```bash
# Generate (returns plaintext key once — store it securely)
curl -X POST -H "Authorization: Bearer <token>" \
  "http://<server-ip>:<port>/compute/api/auth/me/api-key"

# Check status
curl -H "Authorization: Bearer <token>" \
  "http://<server-ip>:<port>/compute/api/auth/me/api-key"

# Revoke
curl -X DELETE -H "Authorization: Bearer <token>" \
  "http://<server-ip>:<port>/compute/api/auth/me/api-key"
```

Use the key via the `X-API-Key` header:

```bash
curl -H "X-API-Key: revodesign_<hex>" \
  "http://<server-ip>:<port>/compute/api/auth/me"
```

API keys never expire but have **restricted privileges**: they can submit tasks and
read results, but **cannot** change passwords, manage API keys, or perform admin
actions. Use a Bearer token (web login) for those operations.  **Guest accounts
cannot use API keys at all** — they are web-dashboard-only accounts.

Rate limits: 5 login attempts/minute per IP, 3 registrations/hour per IP.  The
login endpoint returns HTTP 429 with `retry_after_seconds`; the login page uses
that value to disable the submit button and count down until retry.
