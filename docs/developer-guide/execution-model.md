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
