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

> A filename extension identifies serialization, not the complete scientific
> meaning of an input. Runner task contracts may select a Core-owned logical
> validation profile appropriate to that scientific dialect.

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
- No compressed upload format or archive extraction contract is accepted by
  preflight. Compressed data disguised as a scientific format is rejected;
  any future compressed-input contract must add explicit decompression bounds.
- Text formats require UTF-8 and reject NUL and unsafe control bytes. JSON and
  YAML carry 1 MiB pre-parse ceilings plus node/depth caps; YAML aliases are
  rejected. Parquet inputs must have the standard leading and trailing magic.
- Each text input role selects a Core logical profile through its owning
  `task.yaml`. AlphaFold 3 and OpenDDE specifications require their expected
  top-level shape and reject external paths and URLs. Foundry specifications
  may name separately uploaded assets only through confined relative
  references. AlphaFold 3's upstream `*Path` fields are forbidden, so MSA,
  template, and user-CCD content must be inline. Browser-generated
  specification documents are ordinary role uploads and pass through this same
  validation.
- A role may select a dialect of a physical format where the serialization
  carries more than one scientific language. Standard protein FASTA stays
  strict: the `protein_sequence` and `alignment` profiles keep the residue
  alphabet, so a ligand SMILES or a modification bracket is still rejected
  there. The `chai_entity_specification` profile validates the FASTA *framing*
  Chai-1 uses for protein, RNA, DNA, ligand, and glycan entities — supported
  entity types, a name label, balanced and non-empty modification blocks,
  non-empty records, and size ceilings — and leaves canonical semantic parsing
  to Chai itself. The `boltz_specification` profile covers both of Boltz's
  serializations: a YAML document and the `>CHAIN|TYPE[|MSA]` FASTA, whose
  `ccd` and `smiles` entity payloads are not protein residues. Both FASTA
  dialects are registered as physical-format dialects, so they *replace* the
  strict `validate_fasta` for their logical type rather than running after it;
  every other FASTA role keeps the protein alphabet. The Boltz profile requires
  every chain to resolve to one of the three upstream MSA modes: an uploaded
  `.a3m` or `.csv` asset named through a confined relative reference, explicit
  single-sequence `msa: empty`, or the default online ColabFold service.
  A reference that is an absolute path, a traversal, or a URL is rejected, and
  the Runner re-resolves each reference against the server-resolved input
  manifest before invoking the model. The online service is a declared
  network capability: `boltz_predict` sets `requires_network`, so the type API
  and the submission UI do not present sequence-transmitting behaviour as
  offline.
- Network access is a declared Runner/Workflow capability, not inherently
  forbidden. A stage that needs the network declares `requires_network`, and
  network-dependent preprocessing fails the Task normally when it fails.
  Model weights and core model assets stay locally provisioned. The
  declaration is *enforced*, not merely advertised: a Task without
  `requires_network` is launched with Apptainer's `--net --network none`,
  which gives the container its own network namespace with loopback only.
  This matters because `--containall` does **not** create a network
  namespace — without the explicit flag the container would share the
  worker's host namespace, where the Celery broker on `127.0.0.1:6380` and
  the gateway on `127.0.0.1:8080` are reachable. A Task that does declare
  the capability keeps the host namespace: an isolated *egress* namespace
  needs a root- or suid-configured Apptainer bridge, so that remains a
  deployment choice this adapter cannot assume.
- Runner containers run as the account that submits the Slurm allocation
  (the configured `RUNNER_UID`/`RUNNER_GID` service identity, never root) and
  share one filesystem. Runner output is untrusted content, but a Runner
  escape is not the trust boundary to rely on for cross-user isolation:
  keep every runner-owned mount read-only unless a specific family has a
  documented write requirement, and treat any new runner that needs a
  writable host mount as a design review item.
- Validators are explicitly classified as `safe_inprocess` or `isolated`.
  Bounded Core/standard-library checks run in-process. The third-party YAML
  parser runs in a fresh Core worker with static arguments, an inherited
  read-only input descriptor, a private temporary working directory, Python
  isolated mode, a sanitized environment, disabled socket construction, and
  CPU, address-space, output-file, descriptor, and wall-clock limits. A timeout,
  resource-limit termination, crash, or malformed worker response is a normal
  validation rejection and cannot create a Task.
