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
- Without a deep link, choose a method by scientific purpose, input, or expected output. The page does not silently select the first enabled method.
- Follow the method's server-declared protocol: provide biological material, define scientific intent when needed, set consequential controls, then review and run.
- Upload inputs with **Choose file(s)** or drag and drop. FASTA methods also accept one pasted sequence or one complete FASTA record.
- The final review and readiness panel must be valid before the single **Run <method>** action is enabled.

### Dashboard

- `http://<server-ip>:<port>/compute/dashboard`

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
