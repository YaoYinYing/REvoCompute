# REvoCompute

REvoCompute is a Flask and Celery service for multi-user protein computation.
Task schemas, runtime ownership, resource policy, and scientific result
contracts are server-owned and configuration-driven.

Use the navigation to find the operational path you need:

- [Deployment control](operations/deployment-control.md) covers build,
  validation, promotion, restart modes, and recovery.
- [Operations and task adapters](operations/task-adapters.md) explains the
  Docker, SLURM, and Apptainer path and the contract for adding a task type.
- [Server API](server-api.md) lists the public task, status, result, and access
  routes.
- [Runtime families](runners/runtime-families.md) maps tasks to pinned runtime
  stacks; the [runner catalog](runners/catalog.md) documents family contracts.
- [Result view plugin contract](dev-guide/result-view-plugins.md) defines the
  server-owned scientific result composition boundary.

For repository setup and development commands, see the root `README.md` in the
source repository.
