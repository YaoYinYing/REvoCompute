# Security Policy

We appreciate the community's efforts to keep REvoCompute secure. This document explains which versions receive security updates and how to responsibly report potential vulnerabilities.

## Supported Versions

REvoCompute is under active development. Security fixes are applied to the current development branch and the most recent tagged release. Older releases may not receive updates.

| Version             | Supported |
| ------------------- | --------- |
| main (development)  | ✅        |
| latest release      | ✅        |
| earlier releases    | ❌        |

## Reporting a Vulnerability

If you believe you have found a security vulnerability, please notify the maintainers privately so we can investigate and address the issue.

- Use the [GitHub Security Advisories](https://github.com/YaoYinYing/REvoCompute/security/advisories/new) interface to submit a private report.
- If that is not possible, contact a maintainer directly through email or direct message listed on their GitHub profile.

We ask that you do not disclose the issue publicly until we have confirmed and released a fix. We will make our best effort to respond within a week and keep you informed of our progress.

Your cooperation helps keep REvoCompute safe for everyone.

## Deployment security

### Docker socket

Web, maintenance, and worker services never receive `/var/run/docker.sock`.
Docker is used by the host deployment controller to build the server image and
run the Compose services. Runner SIFs are built directly with Apptainer;
production tasks are submitted through Slurm and run with Apptainer.

Security regression checks for Docker socket exposure, admin self-lockout,
banned users, and login throttling are covered by the server test suite; see
[Testing and CI](../developer-guide/testing.md) for what belongs in pytest.

### Authentication

- Authentication signing keys are ephemeral; restarting web invalidates
  existing login, verification, and password-reset tokens.
- Browser page navigations use an `HttpOnly`/`SameSite=Lax` cookie; JavaScript
  cannot read it, so logout requires the server endpoint (`POST /api/auth/logout`).
- Rate limiting: 5 login attempts/minute/IP, 3 registrations/hour/IP.
- All state-changing endpoints require a valid Bearer token or API key.
- API keys have restricted privileges (task operations only) — Bearer tokens are required for profile changes and admin actions.
- Cookie-only writes are rejected; state-changing API calls require a Bearer
  token or API key.

### Redis

- Redis is on an internal Docker network; do not expose its port publicly.
- Redis is authenticated: `restart.sh setup` generates `REDIS_PASSWORD` and
  persists it in the env file; the compose stack applies it to
  `redis-server --requirepass` and to the Celery broker/backend URIs
  (`redis://:<password>@...`). The SLURM override publishes Redis only on
  `127.0.0.1:6380` (loopback) because its host-networked worker cannot reach
  the internal Docker DNS name. Uncomment `REDIS_URL`/`BROKER_URL`/
  `RESULT_BACKEND` only for an external Redis, and include the password in
  the URI.
- Never publish a Redis port on non-loopback interfaces.

### Data

- User passwords are hashed with `werkzeug.security.generate_password_hash` (pbkdf2:sha256).
- The user database is stored under the web/maintenance-only `AUTH_DIR`. The task database,
  uploads, and results remain under `SERVER_DIR`, which web and worker share.
- All API request payloads are validated through typed Pydantic models
  (``schemas.py``) before reaching business logic — malformed input is rejected
  at the boundary.
- Environment variables that are empty strings (e.g. from docker compose
  `${VAR:-}`) are treated as unset, not as valid empty values that would
  silently resolve to CWD or bypass defaults.
- Task IDs are validated against `[a-f0-9]{32}` before any filesystem access.
- File paths are validated with `_safe_join` / `_path_is_within` to prevent directory traversal.

### Uploaded scientific inputs

Uploaded files pass a Core-owned validator tree before any runner sees them:
`revocompute/input_validators/`, a shared `common` module plus one reviewed
validator module per format family (`fasta`, `pdb`, `mmcif`, `json_file`,
small-molecule formats, and structured data), with a registry that dispatches
by file extension and fails closed for formats without a Core validator.

- Each validator returns `None` (accept) or a human-readable error string;
  the design target is transport safety and DoS/complexity caps, not scientific
  interpretation — a
  plausible real file must never be rejected.
- Runner families cannot register executable validator hooks in this trusted
  boundary. Reusable transport or format safety belongs in reviewed Core code;
  Runner-specific scientific preparation remains in the Runner.
- Multipart requests, individual files, and aggregate uploaded bytes are each
  limited to 16 MiB; a submission may contain at most 128 inputs. Limits are
  enforced before Task creation. Quarantine copies are hashed while streaming
  and are removed on every rejection path.
- Text formats require UTF-8 and reject NUL and unsafe control bytes. JSON and
  YAML carry 1 MiB pre-parse ceilings plus node/depth caps; YAML aliases are
  rejected. Parquet inputs must have the standard leading and trailing magic.
