# REvoCompute Agent Interface

REvoCompute is a self-describing scientific compute service. This document is
a stable navigation guide, not a catalog of the currently enabled scientific
Tasks. Read `GET /openapi.json` for the authoritative HTTP methods, request
encodings, authentication schemes, response schemas, and status codes.

## Agent Workflow

1. Discover supported TaskTypes with `GET /compute/api/types`.
2. Inspect one candidate with `GET /compute/api/types/{name}`.
3. Fetch its canonical parameter JSON Schema with
   `GET /compute/api/task-parameters/{task_type}`.
4. Compose and submit a validated task using `POST /compute/api/post`.
5. Read the returned `task_id` and follow-up URLs.
6. Monitor execution with `GET /compute/api/running/{task_id}`.
7. When complete, inspect `GET /compute/api/results/{task_id}` and retrieve
   required manifest-published artifacts.

Do not assume a fixed TaskType list. The collection is a compact catalog;
method-specific scientific guidance belongs to the selected TaskType detail.

## Inspect Task Parameters

Use `GET /compute/api/task-parameters/{task_type}` before constructing a
request. The anonymous, read-only response is the canonical Draft 2020-12 JSON
Schema projected directly from the TaskType's owning `task.yaml`.

Never guess Task parameters, defaults, or constraints. Always query the
parameter schema.

## Authenticate

Use `POST /compute/api/auth/login` with the JSON credentials described by
OpenAPI to obtain a time-limited Bearer token. Send it as
`Authorization: Bearer <token>`. Long-lived keys are created through the
REvoCompute Profile workflow and sent as `X-API-Key: <key>`. Never place
credentials in discovery requests or logs.

## Check Access

The public `GET /compute/api/types/{name}` response declares whether a TaskType
has an execution restriction. After authentication, use
`GET /compute/api/access` for the current user's actual Runner access state.
Where access is requestable, use `POST /compute/api/access/requests`; consult
OpenAPI for the exact request and response contract.

Public contract visibility does not grant execution access. Submission can
still be rejected by authentication, entitlement, readiness, or validation.

## Submit And Monitor A Task

Submit with `POST /compute/api/post` using multipart form data. Select a
discovered `task_type`, prepare its declared inputs or workspace, and encode
Task parameters as `params[parameter_name]`. Use OpenAPI for the exact multipart
contract rather than copying an example request.

The accepted response supplies `task_id`, `status_url`, and `results_url`; its
`Location` header also identifies the status endpoint. Query
`GET /compute/api/running/{task_id}` until the Task reaches a terminal state.
The client controls polling; this document performs no polling or execution.

## Discover And Retrieve Results

After successful terminal completion, use
`GET /compute/api/results/{task_id}` as the canonical finalized result manifest
and artifact list. Do not guess server filesystem paths.

Retrieve one manifest-published logical path with
`GET /compute/api/results/{task_id}/artifacts/{path}`. OpenAPI defines options
such as attachment or inline delivery.

To retrieve all results as an archive:

1. Request archive preparation with `POST /compute/api/results/{task_id}/archive`.
2. Download the prepared archive with `GET /compute/api/download/{task_id}`.

Archive preparation may be asynchronous. Consult OpenAPI for the `200`, `202`,
and `409` response meanings; the download endpoint does not create the archive.
