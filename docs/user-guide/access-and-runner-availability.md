# Access and Runner Availability

Three independent decisions determine whether your submission runs. A failure in
any one of them produces a different message, and fixing one does not fix the
others.

| Decision | Question | Signal |
| --- | --- | --- |
| Authentication and role | Is your account active and permitted to submit? | Auth API and your profile |
| Runner entitlement | Are you entitled to this restricted scientific resource? | Access API for the task type |
| Runner readiness and capacity | Is the family READY and is a scheduler slot free right now? | Operator `runner-status`, Slurm queue |

Readiness and access are deliberately separate. A family can be `READY` while
your account lacks entitlement, or you can hold the entitlement while the
family is `NOT_VALIDATED` — submission is refused either way. Likewise, a
READY family with a full GPU partition accepts the task into `queued` rather
than rejecting it.

`READY` means the family has a current SIF and a matching live-acceptance
receipt. It does not imply an idle GPU, a short queue, or an available
partition.

## Where the details live

- [Restricted Runner Access](../operator-guide/runner-access.md) — how
  entitlement is recorded and enforced, and what `allow_gpu_use` gates.
- [Runner Readiness](../operator-guide/runner-readiness.md) — the derived
  readiness states and what each one requires.
- [Task States and Result Delivery](task-states.md) — what `queued` means once a
  submission is accepted.
- [Server API](../reference/server-api.md) — the runner-access and status
  routes.
