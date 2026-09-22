# Submitting Tasks

Clients may inspect scientific capabilities before authentication. Use
`GET /skills.md` as the stable agent API bootstrap, `GET /compute/api/types`
for the compact current Task catalog, `GET /compute/api/types/<name>` for one
selected method's scientific and input/output guidance, and
`GET /compute/api/task-parameters/<task-type>` for the canonical Draft 2020-12
parameter schema. These public contracts do not grant execution access;
submission still enforces authentication, Runner entitlement, readiness, and
input validation.

Authenticated clients may send the completed multipart request to
`POST /compute/api/preflight/<task-type>` before submission. A passing response
returns the resolved parameters and safe input summaries without creating a
Task or retaining uploads. The later submission repeats these checks against
current access and readiness state.

Use the server API documented in the [API reference](../reference/server-api.md). After a
validated submission, follow its returned status URL and use the result manifest
to discover artifacts rather than guessing filenames. Task schemas and available
Runner families are server-owned; clients should discover them rather than
duplicating configuration.

## Using the web interface

The public landing page is served at `http://<server-ip>:<port>/`. It introduces
REvoDesign's human-guided enzyme redesign mission and connects the PyMOL plugin,
documentation, and REvoCompute workspace. During a deployment restart, the
gateway replaces it with a dependency-free maintenance page until the
application services are ready again.

The public runner catalog at `http://<server-ip>:<port>/runners` introduces the
scientific methods currently enabled by the active Runner families. Runtime
families, input formats, and CPU/GPU requirements are rendered from an internal
projection of the same Runner-owned TaskType objects behind the compact public
`GET /compute/api/types` catalog. Each `/runners/<task-type>` detail page
adds the registry-defined workflow stages, parameter defaults, choices, and
limits.

Interactive client API documentation is served at
`http://<server-ip>:<port>/api-docs`, with its OpenAPI 3.1 contract at
`http://<server-ip>:<port>/openapi.json`. The page accepts Bearer tokens and
`X-API-Key` credentials for live requests against the current server.
Task parameter schemas are anonymously available at
`/compute/api/task-parameters/<task-type>` and are projected directly from the
enabled TaskType's owning `task.yaml`.
Agent clients can bootstrap API navigation through the stable anonymous
`/skills.md` guide, then follow the progressive contract: compact catalog at
`/compute/api/types`, selected-method detail at `/compute/api/types/<name>`,
canonical parameters at `/compute/api/task-parameters/<name>`, submission,
status monitoring, and finally result-manifest discovery. No endpoint maintains
a duplicate parameter registry.

### Create task page

- `http://<server-ip>:<port>/compute/create_task`
- `http://<server-ip>:<port>/compute/create_task?task_type=<name>` opens the
  form with a specific enabled task type selected.
- Without a deep link, choose a method by scientific purpose, input, or expected
  output. The page does not silently select the first enabled method.
- The form is one continuous workbench: biological material and scientific
  controls in a single column, followed by the review list directly beside the
  **Run <method>** action. There is no separate readiness panel and no
  side-track of workflow steps.
- Upload inputs with **Choose file(s)** or drag and drop. FASTA methods also accept one pasted sequence or one complete FASTA record.
- The review list next to the **Run <method>** action must be valid before that action is enabled. Error rows point at the input that needs attention.
- Inputs are not reused from earlier tasks. Every submission uploads its own
  files; the previous artifact-reuse picker has been removed.

### Profile

- `http://<server-ip>:<port>/compute/profile`

The Profile page is a settings surface with one navigation strip — **Profile**,
**Security**, **API Key**, **Runner Access**, **GPU Credits**, **Metrics** — and
one active section at a time. It shows on a desktop sidebar and on a wrapping
tab strip at narrow widths. Each section calls only the data it needs, so
opening Profile does not fetch Runner access, credits, or metrics until you
switch to those sections.

### Dashboard

- `http://<server-ip>:<port>/compute/dashboard`

The Dashboard toolbar groups its filters and keeps the view mode switch
(Detailed / Compact / Table) and the current selection state in one place.
Secondary filters (owner, and the submission/finish date ranges) live behind a
disclosure so the primary row stays compact.

### Upload via curl (with token auth)

```bash
# Obtain a token first (see [Authentication and Accounts](../operator-guide/authentication.md))
TOKEN="<your-token>"

curl -H "Authorization: Bearer ${TOKEN}" \
  -X POST \
  -F "file=@/path/to/input.fasta" \
  "http://<server-ip>:<port>/compute/api/post"
```

### Batch upload via curl

```bash
for f in *.fasta; do
  curl -H "Authorization: Bearer ${TOKEN}" -X POST -F "file=@${f}" \
    "http://<server-ip>:<port>/compute/api/post"
done
```

### Delete one task (single-task API)

```bash
TASK_MD5="<task-md5>"
curl -H "Authorization: Bearer ${TOKEN}" -X DELETE \
  "http://<server-ip>:<port>/compute/api/delete/${TASK_MD5}"
```

### Delete multiple tasks (batch API)

```bash
curl -H "Authorization: Bearer ${TOKEN}" -X POST \
  -H "Content-Type: application/json" \
  -d '{"md5sums":["<task-md5-a>","<task-md5-b>"]}' \
  "http://<server-ip>:<port>/compute/api/delete"
```
