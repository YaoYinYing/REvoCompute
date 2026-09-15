# Operator Guide

This section is for people who install, configure, and run a REvoCompute server.

A configured or enabled family is not necessarily READY: readiness requires
current Doctor, image, and live-test evidence. `enabled != READY`, and
`runner-status` is the operator view of the same shared readiness contract used
by production submission admission. New submissions to a technically non-READY
family fail closed before durable task, upload, queue, or Slurm side effects.
Access entitlement and transient scheduler capacity remain separate decisions.
Readiness changes do not cancel tasks that are already running.

## Get a server running

- [Installation and Host Preparation](installation.md) — host packages,
  sequence databases, and the service account.
- [Configuration and Service Identity](configuration.md) — environment files,
  the environment reference, and state-directory access.
- [Authentication and Accounts](authentication.md) — tokens, API keys, roles,
  and admin user management.
- [Public Access and TLS Termination](public-access.md) — gateway exposure,
  Cloudflare Tunnel, and host reverse proxies.

## Deploy and validate

- [Deployment Lifecycle](deployment.md) — prepare, inspect, live-test, promote,
  operate.
- [Deployment Control Reference](deployment-control.md) — commands, restart
  modes, safety flags, and failure diagnosis.
- [SLURM + Apptainer Deployment](slurm-deployment.md) — the step-by-step
  enablement checklist and runtime architecture.
- [Runner Configuration and Resource Policy](runner-configuration.md) — runner
  YAML ownership, resource policy resolution, and ordered workflows.
- [Live Testing and Receipts](live-testing.md) — what makes a PASS receipt
  promotable.
- [Runner Readiness](runner-readiness.md) — the derived readiness states.

## Operate

- [Operations and Task Adapters](task-adapters.md) — the end-to-end adapter and
  release contract.
- [Restricted Runner Access](runner-access.md) — entitlement policy and
  enforcement.
- [Personal Task Storage](personal-task-storage.md) — immutable storage,
  artifacts, and the persistent-state epoch.
- [Tool Runtime Operations](tools.md) — enabling and operating Tool families.
- [Fleet Operations](fleet-operations.md) — shift routine and operational notes.
- [Troubleshooting and Recovery](troubleshooting.md) — failure classification
  and network/proxy recovery.
