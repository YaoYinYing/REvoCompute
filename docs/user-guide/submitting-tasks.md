# Submitting Tasks

Clients may inspect scientific capabilities before authentication. Use
`GET /skills.md` as the stable agent API bootstrap, `GET /compute/api/types`
for the compact current Task catalog, `GET /compute/api/types/<name>` for one
selected method's scientific and input/output guidance, and
`GET /compute/api/task-parameters/<task-type>` for the canonical Draft 2020-12
parameter schema. These public contracts do not grant execution access;
submission still enforces authentication, Runner entitlement, readiness, and
input validation.

Use the server API documented in the [API reference](../server-api.md). After a
validated submission, follow its returned status URL and use the result manifest
to discover artifacts rather than guessing filenames. Task schemas and available
Runner families are server-owned; clients should discover them rather than
duplicating configuration.
