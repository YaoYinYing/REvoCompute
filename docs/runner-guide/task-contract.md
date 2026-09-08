# Task Contract

A task manifest is the complete scientific API for one TaskType. Define its
input schema and validation, typed parameters and defaults, resource/network
requirements, runner arguments, execution stages, output files, and result
parser/artifact contract. Keep task-specific knowledge in the owning family;
Core should only orchestrate generic schemas and plans.

Inputs are copied into an isolated task workspace and outputs are accepted only
when the declared artifact contract passes. Reject unknown or unsafe paths and
avoid implicit downloads in the execution step. Version contract changes and
update the family's required smoke cases; the changed identity invalidates
previous live receipts until revalidated.
