# REvoCompute

REvoCompute is a Flask and Celery service for multi-user protein computation.
Task schemas, runtime ownership, resource policy, and scientific result
contracts are server-owned and configuration-driven.

Use the navigation to find the operational path you need:

- [Deployment control](operator-guide/deployment.md) covers build,
  validation, promotion, restart modes, and recovery.
- [Runner maintenance](runner-guide/adding-a-runner.md) explains the contract
  for adding a task type and family-owned runtime assets.
- [Server API](server-api.md) lists the public task, status, result, and access
  routes.
- [Runtime families](reference/runtime-families.md) maps tasks to pinned runtime
  stacks.
- [Result view plugin contract](developer-guide/result-view-plugins.md) defines the
  server-owned scientific result composition boundary.

The published site has one normative owner per audience: `user-guide/`,
`operator-guide/`, `runner-guide/`, `developer-guide/`, `reference/`, and
`agents/`. Root-level guides are source-repository references, not a second
published documentation hierarchy.
