# Results

When a task reaches `finished`, the server has atomically published
`manifest.json` in the uncompressed result tree. That manifest is the contract
between the runner and every client: it lists the artifacts the task produced,
their roles, the scientific views the server resolved, and the run provenance.

## Reading results

- Individual manifest-listed files are previewed or downloaded through
  authenticated endpoints, and can be streamed by Nginx.
- A full ZIP is an optional asynchronous cache created only after an explicit
  archive request. It contains only files published by the manifest and is not
  part of task completion.
- All manifest-approved artifacts remain searchable and individually
  downloadable under **Files & diagnostics**, which is the universal fallback.
- Scientific views are composed from the manifest; a task without a migrated
  view still exposes its artifacts through the generic download path.

The manifest records a *technical* output check: configured files are present,
non-empty, and structurally mappable. That check does not establish scientific
or experimental validity. Task-owned limitations are recorded alongside the
result and should be read before drawing conclusions.

## Where the details live

- [Task States and Result Delivery](task-states.md) — lifecycle states, what
  `finished` guarantees, and how views are composed.
- [Scientific Result Inventory](../developer-guide/result-inventory.md) — the
  per-task artifact classes, declared semantics, and presentation.
- [Result View Plugin Contract](../developer-guide/result-view-plugins.md) — the
  server-owned composition boundary for new views.
- [Server API](../reference/server-api.md) — the status and result routes.
