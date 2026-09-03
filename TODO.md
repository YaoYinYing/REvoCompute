# Finish PR3: Complete the REvoCompute Ownership Inversion

You are continuing work on PR #3 in:

```text
/repo/REvoCompute
```

Current branch:

```text
refactor-plugin-kernel-doctor
```

Do not start a new architecture beside the old one.

The existing PR has introduced useful scaffolding:

```text
revocompute.plugins
PluginManager
ContributionRegistry
PluginManifest
ExecutionPlan
JSON Schema validation
DoctorReport
doctor CLI code
```

However, the migration is **not complete**.

The current production path still depends on the old centralized architecture:

```text
config/task_types.yaml
    ↓
revocompute.task_types.load_registry()
    ↓
TaskType / RuntimeFamily / RunnerConfig
    ↓
task_runtime
```

That is the core problem to fix.

The goal of this continuation is:

> **Complete the ownership inversion so that runner families and tasks become the only source of scientific/task-specific knowledge, while REvoCompute Core becomes ignorant of concrete runners and task types.**

Do not optimize for minimum diff.

Do not preserve old abstractions merely because tests currently depend on them.

Backward compatibility with the centralized task registry is not a goal.

---

# 1. The target dependency direction

The final production architecture must be:

```text
docker/runners/<runner-family>/
    ↓
plugin.yaml
    ↓
tasks/<task>/task.yaml
    ↓
PluginManager / ContributionRegistry
    ↓
generic task contracts
    ↓
REvoCompute Core
    ↓
ExecutionPlan
    ↓
JobExecutor
    ↓
ContainerRuntime
```

The following architecture must disappear:

```text
config/task_types.yaml
    ↓
load_registry()
    ↓
central RuntimeFamily registry
    ↓
central TaskType registry
```

The plugin system must not coexist indefinitely with the old registry.

It must **replace it**.

---

# 2. Non-negotiable architectural invariant

REvoCompute Core must not know:

```text
alphafold3
alphafold
gremlin
rosetta
opendde
jaag-builder
bioemu
mpnn
rfdiffusion
or any other concrete runner/task identifier
```

Core must also not know concrete parameter names such as:

```text
max_template_date
```

or task-owned enum values such as:

```text
alphafold3
opendde
```

inside generic validation code.

The rule remains:

> **Core owns grammar. Plugins own vocabulary.**

Core may understand generic concepts:

```text
RunnerFamily
TaskDefinition
TaskSchema
ExecutionPlan
ArtifactDescriptor
PresentationDescriptor
JobExecutor
ContainerRuntime
TaskState
```

but not concrete scientific implementations.

---

# 3. Delete `config/task_types.yaml`

This is a required outcome.

Do not merely shrink it.

Do not turn it into an index file.

Do not replace it with another centralized YAML file.

Do not recreate its information as a Python dictionary.

The file:

```text
config/task_types.yaml
```

must no longer be an authoritative source and should be removed by the end of the migration.

Any information currently stored there must be classified and moved according to ownership.

Use this rule:

```text
scientific/task-specific knowledge
    → task or runner-family directory

runner-family shared runtime/software knowledge
    → runner-family directory

server infrastructure configuration
    → server settings / environment

generic protocol definitions
    → Core types/contracts

obsolete compatibility metadata
    → delete
```

---

# 4. Remove `ComputeConfig.task_types_config`

The current `ComputeConfig` still contains:

```python
task_types_config: str
```

and derives:

```text
config/task_types.yaml
```

from `CONFIG_DIR`.

This must disappear.

Core settings must not point at a centralized task registry that no longer exists.

Keep only server-owned configuration.

---

# 5. Stop calling `load_registry()` in production

The current production path still does something equivalent to:

```python
from revocompute.task_types import load_registry as _load_task_registry

_load_task_registry(
    CONFIG.task_types_config,
    CONFIG.runners_dir,
    _enabled_runners,
)
```

This is a blocker.

By the end of this PR, application startup and worker startup must discover tasks through the plugin system.

The production path must no longer depend on:

```text
task_types.load_registry()
```

for runner/task discovery.

If `load_registry()` becomes unused after migration, remove it.

If parts of `revocompute.task_types` remain useful as generic data models, keep only those generic pieces.

Do not retain the old registry architecture under a new name.

---

# 6. Runner families live under `docker/runners/<family>`

The repository already contains real runner-family directories such as:

```text
docker/runners/alphafold3/
docker/runners/opendde/
docker/runners/mpnn/
...
```

These directories are the natural ownership boundary.

Do not create a parallel synthetic directory such as:

```text
config/plugins/
```

unless there is a compelling deployment reason.

The plugin discovery root should be the deployed runner-family root.

Conceptually:

```text
docker/runners/
├── alphafold3/
│   ├── plugin.yaml
│   ├── Dockerfile
│   ├── alphafold3.def
│   ├── run.sh
│   └── tasks/
│       └── predict/
│           └── task.yaml
│
├── opendde/
│   ├── plugin.yaml
│   └── tasks/
│       └── ...
│
└── ...
```

Adapt exact filenames as needed, but preserve this ownership model.

---

# 7. `plugin.yaml` must remain family-level

Do not create another giant manifest.

A family manifest should contain only family-level information and task references.

Example shape:

```yaml
api_version: 1
id: alphafold3
version: 1

runtime:
  image: alphafold3
  definition: alphafold3.def

tasks:
  - tasks/predict/task.yaml
```

Do not put every task parameter, storyboard item, result contract, and UI definition into this file.

Task-specific knowledge belongs in each task directory.

---

# 8. Each task owns its vertical slice

A task must own:

```text
input contract
parameter schema
input construction
execution-plan construction
output contract
output parsing
artifact semantics
interpretation
presentation/storyboard
citations/considerations when task-specific
```

Conceptually:

```text
docker/runners/alphafold3/tasks/predict/
├── task.yaml
├── input.py
├── execution.py
├── output.py
├── interpret.py
└── storyboard/
```

Do not force this exact file split if existing code can be organized more cleanly, but maintain the ownership boundary.

---

# 9. Migrate at least one real runner family end-to-end

Do not validate the architecture only with synthetic fixtures.

Choose at least one real existing runner family as the reference implementation.

Prefer a runner that exercises meaningful pieces of the system, such as:

```text
alphafold3
```

or another suitable existing runner.

The reference runner must be migrated completely enough to prove:

```text
runner-family discovery
task discovery
JSON Schema loading
task lookup
task submission validation
ExecutionPlan construction
result contract resolution
storyboard/presentation resolution
doctor validation
```

all work without `task_types.yaml`.

Synthetic fixtures are still useful for unit tests, but they are not sufficient.

---

# 10. Task lookup must come from plugin contributions

The runtime should resolve tasks through the contribution registry.

Conceptually:

```python
task = plugin_manager.contributions.resolve(
    "tasks",
    task_id,
)
```

or through a dedicated typed task registry backed by the plugin manager.

Do not keep:

```python
_global_task_types = {...}
```

as a second source of truth.

If existing code calls:

```python
task_types.get(task_type)
```

you may temporarily preserve a thin compatibility facade only if it resolves from PluginManager contributions.

It must not maintain an independent registry.

---

# 11. The PluginManager must become production infrastructure

The current `PluginManager` exists but is largely isolated from the server.

Fix that.

There should be one well-defined startup path that:

```text
discovers runner-family manifests
validates manifests
loads task contributions
registers tasks
makes them available to web and worker processes
```

Avoid different discovery implementations in:

```text
doctor
web server
worker
tests
```

All of them should use the same plugin discovery and validation engine.

`doctor` must diagnose the same objects that production would load.

---

# 12. Reconsider plugin activation complexity

Do not add lifecycle machinery merely because Cordis or npe2 has it.

Runner-family manifests and task declarations may be mostly declarative.

If runtime activation is needed, use it.

If plugins are fully declarative until task execution, keep activation simple.

The priority is:

```text
correct ownership
single source of truth
clear discovery
valid contracts
```

not reproducing Cordis feature-for-feature.

---

# 13. JSON Schema becomes canonical

The current PR still derives JSON Schema from legacy `TaskParam` metadata.

That is transitional behavior, not the target.

The canonical task parameter contract should live in the task definition.

For example:

```yaml
parameters:
  type: object
  additionalProperties: false
  properties:
    max_template_date:
      type: string
      format: date
```

or:

```yaml
schema:
  $schema: https://json-schema.org/draft/2020-12/schema
  type: object
  additionalProperties: false
  properties:
    max_template_date:
      type: string
      format: date
```

Choose one clean representation.

Core should validate that schema using:

```text
Draft 2020-12
FormatChecker
```

Do not make legacy `TaskParam` fields the authoritative model.

If frontend rendering still needs labels, descriptions, advanced flags, widgets, etc., keep those as presentation metadata adjacent to the JSON Schema.

Do not mix validation semantics back into custom backend fields.

---

# 14. Remove legacy schema reconstruction where possible

Current code reconstructs JSON Schema from fields such as:

```text
type
choices
minimum
maximum
required
default
```

and then merges optional `schema` overrides.

This is backwards.

Move existing task definitions to canonical JSON Schema.

Then simplify Core.

The desired direction is:

```text
task-owned JSON Schema
    ↓
generic validator
```

not:

```text
legacy TaskParam
    ↓
Core reconstructs schema
```

Keep conversion logic only as a short-lived migration helper if absolutely necessary during this PR, and delete it before completion if all tasks have been migrated.

---

# 15. Fix the JAAG configuration ownership correctly

The recent hardcode:

```python
if plugin == "jaag-builder" and options.get("target") not in {
    "alphafold3",
    "opendde",
}:
    ...
```

was correctly removed.

Do not reintroduce it elsewhere.

The JAAG input builder must own its own configuration schema.

Conceptually:

```text
jaag-builder
    configuration_schema:
        target:
            type: string
            enum:
                - alphafold3
                - opendde
```

The generic registry should only do:

```text
resolve contribution
load its configuration schema
validate options
```

The registry must not know JAAG target values.

Add regression coverage.

---

# 16. Fix execution architecture: `ExecutionPlan` must be used

The current PR defines `ExecutionPlan`, but the production runtime still directly constructs:

```text
SlurmJob
DockerJob
```

from task/runner objects.

That means `ExecutionPlan` is currently dead architecture.

Integrate it.

The intended flow is:

```text
TaskDefinition
    ↓
ExecutionBuilder
    ↓
ExecutionPlan
    ↓
JobExecutor
    ↓
Slurm
    ↓
ContainerRuntime
    ↓
Apptainer
```

The task must not instantiate a Slurm job.

The task must not invoke Apptainer.

The task produces data.

Infrastructure interprets that data.

---

# 17. Do not model Docker as a JobExecutor

The current PR introduced:

```python
job_executor in {"docker", "slurm"}
```

and pairs:

```text
docker → docker
slurm → apptainer
```

This is conceptually wrong.

Docker is a container runtime, not a scheduler/job executor.

Do not keep this model.

For the current REvoCompute architecture:

```text
JobExecutor:
    slurm

ContainerRuntime:
    apptainer
```

is the production model.

Do not add `local`.

Do not add `native`.

Do not add `docker` as a scheduler.

If existing Docker execution remains necessary only for legacy development/full-stack tests, isolate it as legacy/test infrastructure rather than making it part of the target architecture.

Do not let test convenience define production abstractions.

---

# 18. Re-evaluate whether the two environment variables are necessary

We previously discussed:

```env
REVOCOMPUTE_JOB_EXECUTOR=slurm
REVOCOMPUTE_CONTAINER_RUNTIME=apptainer
```

These are acceptable as infrastructure bindings.

However, if the system currently supports only:

```text
Slurm + Apptainer
```

and no second valid isolated deployment combination exists, do not invent multiple providers merely to justify configuration.

It is acceptable for these to remain explicit server bindings.

Do not create fake symmetry.

The important rule is:

```text
runner/task manifests cannot choose them
```

---

# 19. `doctor` must stop reading `task_types.yaml`

This is mandatory.

Current doctor behavior such as:

```python
registry_path = root / "task_types.yaml"

if not registry_path.is_file():
    E1001
```

must be removed.

An installation with zero runner families must be valid.

This must succeed:

```text
docker/runners/ is empty
→ plugin discovery returns zero families
→ available tasks = []
→ doctor reports no runner-family errors
```

The server must still initialize.

---

# 20. Doctor must diagnose the actual plugin graph

Doctor must use the same plugin discovery path as production.

Its phases should be conceptually:

```text
discover
    runner-family manifests

parse
    plugin manifests
    task manifests
    schemas

resolve
    contributions
    Python references
    assets

validate
    generic protocols
    JSON Schemas

link
    task ↔ execution
    task ↔ output
    output ↔ artifact
    artifact ↔ storyboard

probe
    low-cost infrastructure checks
```

Do not implement a second handwritten representation of runner families inside doctor.

---

# 21. Implement real doctor checks

The current doctor mainly validates YAML structure.

That is insufficient.

Add meaningful checks for:

```text
plugin manifest validity
duplicate plugin IDs
duplicate task IDs
supported plugin API version
task manifest validity
JSON Schema validity
JSON Schema format support
contribution resolution
Python import path resolution where used
ExecutionPlan construction
workspace path safety
declared image/definition existence
storyboard asset existence
artifact/storyboard reference consistency
server infrastructure configuration
Slurm command availability
Apptainer command availability
```

Use stable structured diagnostics.

---

# 22. Make `--probe` real

The current implementation does:

```python
del probe
```

This is not acceptable.

`--probe` should perform low-cost runtime probes.

Examples:

```text
command -v sbatch
command -v squeue
command -v sacct
command -v scancel
command -v apptainer

apptainer inspect <image>
```

and, where runner metadata provides a safe low-cost probe:

```text
apptainer exec <image> <binary> --version
```

Do not run expensive scientific computation.

Do not submit real expensive Slurm workloads as part of normal doctor.

---

# 23. Implement a real `revocompute doctor` command

The desired CLI is:

```text
revocompute doctor
```

not only:

```text
revocompute-doctor
```

Inspect the existing CLI architecture.

Add `doctor` as a subcommand of the main REvoCompute CLI.

If no main CLI currently exists, introduce a small coherent top-level CLI instead of creating unrelated console scripts.

Possible surface:

```text
revocompute doctor
revocompute doctor --runner alphafold3
revocompute doctor --task alphafold3.predict
revocompute doctor --probe
revocompute doctor --strict
revocompute doctor --json
```

---

# 24. Doctor output must represent success too

Do not make:

```text
No diagnostics.
```

the entire healthy output.

A doctor command should show what it checked.

For example:

```text
REvoCompute Doctor

Infrastructure
  ✓ Slurm
  ✓ Apptainer
  ✓ storage
  ✓ database

Runner families
  ✓ alphafold3
      ✓ manifest
      ✓ predict
      ✓ schema
      ✓ execution plan
      ✓ storyboard
```

Structured JSON should contain the same underlying results.

Avoid maintaining separate logic for text and JSON.

---

# 25. Storyboard ownership must move with tasks

Continue the previous storyboard architecture direction.

Runner/task-specific result presentation must stay with the task.

Do not centralize:

```text
GREMLIN result JS
AlphaFold confidence rendering
task-specific result parser behavior
```

inside generic Core/frontend modules.

Task-owned storyboard assets should be discoverable from task manifests.

Doctor must validate their references.

---

# 26. Artifact linking must be machine-checkable

Introduce or complete generic artifact descriptors.

Task output should expose generic descriptors such as:

```text
id
role
path
media_type
metadata
```

Task-specific role names remain opaque to Core.

Storyboard declarations may reference those artifact roles.

Doctor should detect mismatches.

Example failure:

```text
storyboard expects:
    confidence_plot

output contract provides:
    confidence_metrics
```

This must fail doctor before a real task runs.

---

# 27. Remove central `runtime_families`

Do not preserve a centralized `runtime_families` map.

Runner-family runtime information belongs to:

```text
docker/runners/<family>/
```

If some currently centralized fields describe:

```text
Dockerfile
Apptainer definition
image
entrypoint
mount requirements
shared assets
```

move them into the corresponding runner family.

Do not make Core maintain a list of known runtime families.

---

# 28. Reassess `categories`

If task categories are only UI/domain metadata, they belong to task manifests or a generic presentation taxonomy.

Core must not use a centralized category registry to determine whether a task is valid.

Avoid:

```python
if category not in _category_registry:
    ...
```

unless category is a truly generic protocol vocabulary with a clear reason to be Core-owned.

Prefer plugin-owned opaque category strings if the server does not need semantic understanding.

---

# 29. Reassess `workspace_templates`

Classify them.

If a workspace template is runner/task-specific, move it into the runner/task.

If it is a genuinely generic Core file type or generic workspace primitive, retain it in Core.

Do not keep mixed centralized configuration.

---

# 30. Existing runner-specific Core knowledge must be audited

Search generic Core for known runner/task identifiers.

At minimum search for:

```text
alphafold
alphafold3
gremlin
opendde
jaag
mpnn
rosetta
rfdiffusion
bioemu
```

Also search for patterns:

```text
if plugin ==
if runner ==
if task_type ==
if param.name ==
runtime_family
```

Do not mechanically delete every match.

Classify each occurrence by ownership.

Move domain knowledge outward.

---

# 31. `format_runner_identity()` currently contains GREMLIN-specific wording

Inspect existing Core errors such as:

```text
"GREMLIN runner cannot run as root"
```

If the rule is generic to all runners, make the wording generic.

For example:

```text
"Runner containers cannot run as root"
```

This is a small example of the same ownership principle.

Core should not name a concrete runner in generic infrastructure validation.

Audit for similar cases.

---

# 32. Production runtime must work with zero runner families

Add an architecture test:

```text
runner-family root exists but is empty

plugin manager initializes

server task registry initializes

available tasks == []

doctor succeeds except for unrelated infrastructure failures explicitly induced by test setup
```

No:

```text
missing task_types.yaml
missing GREMLIN
unknown runtime family
```

errors are allowed.

This test is a primary acceptance gate.

---

# 33. Add a synthetic runner without touching Core

Create a test-only runner family:

```text
demo/
├── plugin.yaml
└── tasks/
    └── echo/
        └── task.yaml
```

It should contribute:

```text
a JSON Schema
an ExecutionPlan builder
a trivial artifact/output contract
a storyboard descriptor if required
```

Then prove:

```text
PluginManager discovers it
task becomes available
submission validates
doctor validates it
no Core registry changes are required
```

This test demonstrates the actual plugin architecture.

---

# 34. Migrate a real runner in addition to the synthetic one

Synthetic tests are not enough.

At least one real runner family must use the new path.

The reference implementation should be used by normal server/runtime tests where practical.

Do not leave every real task on the legacy registry.

---

# 35. Rewrite doctor tests

Current tests that create:

```text
task_types.yaml
```

as the definition of a healthy installation are wrong for the target architecture.

Rewrite them.

A healthy minimal installation should instead create:

```text
runner-family root
plugin manifest(s)
task manifest(s)
```

or zero runner families.

Add tests for:

```text
missing/invalid plugin manifest
duplicate task contribution
invalid JSON Schema
broken task-to-family reference if such a reference exists
broken artifact/storyboard link
unsafe ExecutionPlan path
missing declared image/definition
probe unavailable command
strict mode exit code
JSON output
```

---

# 36. Rewrite plugin-kernel tests around production discovery

Current unit tests that manually call:

```python
manager.register_contribution(...)
```

are useful but insufficient.

Add tests that go through actual files:

```text
plugin.yaml
task.yaml
```

and end at production-visible task contributions.

The plugin manager must prove it can load a deployed family, not only hold in-memory objects.

---

# 37. Integrate `ExecutionPlan` into tests

Current `ExecutionPlan` tests validate only dataclass construction.

Add tests demonstrating:

```text
TaskDefinition
    ↓
build ExecutionPlan
    ↓
Slurm executor consumes plan
    ↓
external command invocation is mocked
```

Do not test a separate fake scheduler implementation.

---

# 38. Slurm tests must mock the command boundary

Use the real Slurm executor logic.

Mock:

```text
sbatch
squeue
sacct
scancel
```

or the lowest command-execution abstraction.

Verify:

```text
generated command/script
resource mapping
Apptainer invocation
workspace mounts
job ID parsing
status mapping
cancel behavior
```

Do not introduce a production `mock-slurm` backend.

---

# 39. Preserve mandatory container isolation

Do not add:

```text
native runtime
host binary execution
local subprocess task execution
```

as valid runner paths.

Every real task executes inside its runner container.

The container is part of the REvoCompute execution contract.

---

# 40. Migration may be large; do not stop after scaffolding

This PR already demonstrates why partial migration is misleading.

Do not consider the following sufficient:

```text
PluginManager exists
ExecutionPlan exists
doctor exists
JSON Schema exists
```

They must replace the old path.

A class that is not used by production does not count as migration.

A schema that is generated from the old registry does not count as canonical ownership.

A doctor that validates the old registry does not count as plugin conformance.

---

# 41. Required end-state

By the end of this PR, the following statements must be true.

### Task discovery

```text
No config/task_types.yaml exists.

No production startup code calls load_registry(task_types.yaml).

Tasks are discovered only through runner-family plugin/task manifests.
```

### Core ignorance

```text
Adding a new runner family requires zero Core Python changes.

Adding a new task requires zero Core Python changes.

Core does not contain concrete task parameter validation.
```

### Schema

```text
Task JSON Schema is canonical.

FormatChecker is enabled.

max_template_date requires no Core special case.
```

### Plugin-specific config

```text
JAAG target validation is plugin-owned.

Generic registries do not know allowed JAAG targets.
```

### Execution

```text
Tasks build ExecutionPlan.

Slurm consumes ExecutionPlan.

Apptainer launches runner containers.

No native/local task execution exists.
```

### Doctor

```text
doctor discovers the same plugins production uses.

doctor does not read task_types.yaml.

doctor validates manifests, schemas, task contracts, execution plans, containers, artifacts, and presentation links.

--probe performs real low-cost probes.

revocompute doctor is a real subcommand.
```

### Tests

```text
zero-runner installation works.

synthetic plugin works without Core changes.

at least one real runner uses the plugin path.

Slurm command boundary is mocked in tests.

legacy centralized registry tests are removed or rewritten.
```

---

# 42. Things that must be deleted if no longer needed

After migration, aggressively inspect and remove obsolete components such as:

```text
config/task_types.yaml
ComputeConfig.task_types_config
load_registry() centralized discovery logic
central runtime_families registry
central task_types registry
legacy schema reconstruction helpers
Docker-as-job-executor abstraction
unused compatibility registries
tests whose only purpose is preserving the centralized architecture
```

Do not keep dead architecture “for compatibility” unless you can show an active caller that cannot yet be migrated.

This project does not require backward compatibility with the old configuration layout.

---

# 43. Do not recreate the old architecture under different names

These are all failures:

```python
PLUGIN_TASK_TYPES = {...}
```

```python
KNOWN_RUNNERS = {...}
```

```python
RUNTIME_FAMILIES = {...}
```

```yaml
plugins:
  alphafold3:
  opendde:
  ...
```

in a new centralized Core config.

The authoritative information must remain physically and logically owned by each runner family.

---

# 44. Treat filesystem locality as ownership

A strong design rule for this repository is:

> If a file exists only because a particular runner/task exists, the file should normally live under that runner/task.

Examples:

```text
AF3 schema
    → alphafold3 task

AF3 serializer config
    → alphafold3/JAAG-owned implementation

GREMLIN JS result parser
    → GREMLIN task storyboard

Rosetta task parameters
    → Rosetta task

runner image definition
    → runner family
```

Core contains only reusable protocol code.

---

# 45. Doctor is part of the plugin protocol design

When designing a plugin/task contract, ask:

```text
Can doctor validate this without running an expensive scientific job?
```

If not, the contract probably hides too much implicit behavior.

Prefer declarative, inspectable contracts.

Good contracts allow:

```text
discover
parse
validate
resolve
link
probe
```

---

# 46. Do not over-generalize future providers

Do not spend this PR inventing:

```text
Kubernetes
PBS
LSF
Docker Swarm
native
local
Podman
```

unless current code genuinely requires them.

The problem being solved is runner/task ownership and plugin conformance.

Keep infrastructure interfaces clean, but implement only what REvoCompute currently uses.

---

# 47. CI acceptance gate

Add or update CI so a plugin family can be checked with a command equivalent to:

```text
revocompute doctor --runner <family> --strict
```

For environments without Slurm/Apptainer, separate:

```text
static conformance
```

from:

```text
infrastructure probe
```

so GHA can still validate plugin architecture without pretending it has a real HPC cluster.

Do not weaken production contract merely to satisfy CI.

---

# 48. Final architecture review

Before completion, explicitly verify:

```text
grep/search for task_types.yaml references
grep/search for load_registry references
grep/search for runtime_families
grep/search for concrete runner IDs in Core
grep/search for if plugin ==
grep/search for if runner ==
grep/search for if task_type ==
grep/search for if param.name ==
```

Classify every remaining occurrence.

There should be no unexplained runner/task-specific knowledge in generic Core.

---

# 49. Final verification

Run the repository's full relevant test suite.

Also verify:

```text
revocompute doctor --strict
revocompute doctor --json
```

where the local environment permits.

Run plugin/registry tests.

Run schema tests.

Run execution-plan tests.

Run Slurm executor tests with mocked external command calls.

Run existing non-browser server tests.

Investigate current GHA install failures as part of this PR; do not leave the branch red if they are caused by this change.

---

# 50. Completion report

When finished, report specifically:

```text
1. Which old centralized files/registries were removed.

2. Where each migrated category of data now lives.

3. Which real runner family was migrated as the reference implementation.

4. How production discovers tasks now.

5. How JSON Schema becomes canonical.

6. How ExecutionPlan enters the real execution path.

7. What doctor now checks.

8. What --probe actually executes.

9. Which runner/task identifiers remain in Core and why.

10. Which tests prove zero-runner startup and zero-Core-change plugin addition.

11. Full test/CI results.

12. Any remaining architecture debt that prevents complete ownership inversion.
```

Do not describe scaffolding as completion.

---

# Core acceptance test

Use this as the final mental test:

```text
Imagine deleting every directory under docker/runners/.

REvoCompute should still start.

It should expose zero available scientific tasks.

Core should not complain that AlphaFold3, GREMLIN, Rosetta, or any runtime_family is missing.
```

Then:

```text
Copy in a completely new runner family containing only:

plugin.yaml
task manifest/schema
runner image definition
task implementation/storyboard

Restart the server.

The new task should appear and work without editing any Core source file.
```

If either statement is false, the architecture migration is not complete.

The purpose of this PR is not to add a plugin framework.

**The purpose is to make the plugin framework the only owner and discovery path for scientific tasks.**
