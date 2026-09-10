# Submitting Tasks

Clients may inspect scientific capabilities before authentication. Use
`GET /skills.md` as the stable agent API bootstrap, `GET /compute/api/types`
for the current Task catalog, and
`GET /compute/api/task-parameters/<task-type>` for the canonical Draft 2020-12
parameter schema. These public contracts do not grant execution access;
submission still enforces authentication, Runner entitlement, readiness, and
input validation.

Use the server API documented in the [API reference](../server-api.md). Task schemas and available runner families are server-owned; clients should discover them rather than duplicating configuration.
