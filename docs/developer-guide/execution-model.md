# Execution Model

An API request is validated into a server-owned TaskDefinition, checked for
access and current Runner readiness, and compiled into an ExecutionPlan. The
plan names the TaskType, immutable inputs, typed parameters, resource profile,
runtime artifact, and output contract. Only after these checks does the worker
create task storage and submit to Slurm.

Slurm launches the family entrypoint inside the exact Apptainer SIF. The worker
captures status and logs, then the family parser validates declared outputs and
artifact references before marking the task complete. Failures are explicit
and retry policy is bounded; a later readiness change does not kill work that
is already running.

## Placement

The resource profile is resolved once, before submission, by the deployment's own
policy (`revocompute.resource_policy.resolve_resources`), and the result is frozen
into the Task's `input_form` beside the decision that produced it. That decision
(`revocompute.placement`) records the execution class the stage was placed into,
the policy revision it was resolved against, and a bounded machine-readable
reason. The Worker validates the same frozen snapshot, so a queued Task can never
change because an administrator edited defaults later, and a Task read months
afterwards reports the decision that was actually made rather than one recomputed
from the policy of the day.

The division of responsibility is deliberate and narrow. REvoCompute decides *what
a stage requests and why* — the class of scheduler resources it asks for, the
concrete Slurm fields that request resolves to, and the reason for the choice.
Slurm decides *when and on which eligible node the work runs*: queue order,
fair-share, backfill, and node selection belong to the scheduler, and nothing here
scores, ages, prioritizes, or simulates any of that. An accelerator requirement is
expressed semantically (a device class, and optionally a device count); the
deployment's `slurm_execution_classes` map decides which local queue that class
resolves to. A requirement the deployment cannot honour fails closed with a
bounded reason before the scheduler ever sees the request.
