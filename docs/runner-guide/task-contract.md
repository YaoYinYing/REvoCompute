# Task Contract

A task manifest is the complete scientific API for one TaskType. Define its
input schema and validation, typed parameters and defaults, resource/network
requirements, runner arguments, execution stages, output files, and result
parser/artifact contract. Keep task-specific knowledge in the owning family;
Core should only orchestrate generic schemas and plans.

Under `parameters.properties`, declare every user-facing parameter's name,
JSON Schema type, default or required semantics, applicable enum/range/format
constraints, and a non-empty description of its actual scientific control.
The optional `x-ui-control: {kind: seed}` presentation hint is accepted only on
integer properties and asks browser clients to add concrete random-seed generation.
Its optional `random.minimum` and `random.maximum` define the browser-generation
domain separately from the API-valid range, so sentinels remain manually valid but
are never generated. The registry rejects invalid controls or generation bounds.
Do not generate descriptions mechanically from names. The server returns this
same Draft 2020-12 schema anonymously from
`GET /compute/api/task-parameters/<task-type>` and embeds it as
`parameter_schema` in the task form API; no Python, JavaScript, Markdown, runner
configuration, or shell adapter may become a second parameter registry.
The stable `/skills.md` bootstrap guide directs agents to the dynamic Task APIs;
it does not list TaskTypes. Keep `summary`, `use_when`, input/output guidance,
and considerations accurate because `/compute/api/types` exposes that semantic
metadata.

Inputs are copied into an isolated task workspace and outputs are accepted only
when the declared artifact contract passes. Reject unknown or unsafe paths and
avoid implicit downloads in the execution step. Version contract changes and
update the family's required smoke cases; the changed identity invalidates
previous live receipts until revalidated.
