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
  controls in a single column, followed by the Task snapshot rail directly beside
  the **Run <method>** action. There is no separate readiness panel and no
  side-track of workflow steps.
- Upload inputs with **Choose file(s)** or drag and drop. FASTA methods also accept one pasted sequence or one complete FASTA record.
- The check list in the snapshot rail next to the **Run <method>** action must be valid before that action is enabled. Error rows point at the input that needs attention.
- The Task snapshot rail stays pinned to the bottom of the visible viewport while
  the workbench scrolls, including on a phone with the on-screen keyboard open.
  It is the same rail and the same primary action, never a floating duplicate.
- Parameters may show an example placeholder supplied by the owning Task schema.
  A placeholder is a hint only: it is not a default, it is not stored, and an
  empty optional field is omitted from the submission exactly as before.
- A Task ID is derived from what you submit (method, parameters, input hashes),
  so sending the identical form again addresses the Task it already created
  instead of starting a second one. Once that Task is terminal — for example
  after you cancel it — its ID is kept and the repeat submission answers `409`
  with the existing task rather than re-running it. Start the method again from
  the create form with the parameters or inputs you want; the changed content
  gives the new run its own ID.

### Clone & reuse an earlier Task

Dashboard cards and a remote Result page offer **Clone & reuse**. It opens a new
Create Task draft seeded from one authorized earlier Task:

- Only explicitly recorded parameter values are prefilled. Values the source
  never recorded resolve through the *current* schema and are marked
  **Current default**; the current schema is always authoritative.
- A value whose parameter was renamed or removed, whose enum choice is no longer
  offered, or whose type, range, format, length or array rule no longer fits is
  reported under **Not carried over** with the recorded value, including an
  empty, `0`, or `false` value. Nothing is coerced and no other scientific mode
  is chosen silently: the field keeps the current schema default for display,
  but **Run** stays blocked until every entry in **Resolve blocked settings** is
  edited or explicitly resolved: use **Keep current value** when the parameter
  still exists, or **Acknowledge blocked setting** when it has no current field.
- Input files belong to the source Task's immutable snapshot, and a Task
  submission never references another Task's files. Every listed input is
  re-uploaded and validated normally; a file the source snapshot can no longer
  verify is called out explicitly.
- The reconciliation panel names the inputs the source recorded and lists the
  required re-uploads. **Reset to current defaults** returns every field to the current
  schema defaults, discarding the cloned values and any later edits;
  **Revert the clone** restores the form state from before the clone was
  applied. Both happen only when you choose them. A field you edit is marked
  **Edited in this draft**, not as coming from the source, and **Clear** or
  loading a task example ends the clone relationship along with the prefilled
  values.
- Opening a clone never submits. Preflight and **Run** are still the only
  submission boundary, and the resulting Task carries non-sensitive
  `cloned_from` provenance for the source Task. A cloned submission therefore
  gets its own Task identity instead of deduplicating onto the source; sending
  the identical clone draft again still returns the Task it already created.
  Resetting or reverting ends the clone relationship, so a later submit from
  that form records no provenance.

API clients can create the same plan explicitly:

```text
POST /compute/api/tasks/<source-task-id>/clone-plan
GET  /compute/api/clone-plans/<plan-id>
```

The POST is read-only against the source and returns the bounded plan plus an
opaque, owner-scoped, short-lived `plan_id`; the GET re-resolves that plan
against the current contract, so a schema change between the click and the
draft is observed. The plan is always `can_submit: false` and never contains a
source filesystem path, download URL, or file bytes. Submitting a draft may name
its source with the optional `cloned_from` multipart field.

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
