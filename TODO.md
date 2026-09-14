# TODO.md — Typed Task Inputs and Test Architecture Cleanup

## 0. Scope

This PR addresses two related architectural problems:

1. REvoCompute currently treats task inputs primarily as an ordered list of uploaded files rather than typed, named task inputs.
2. The test suite mixes Server behavior, Runner behavior, static repository assertions, smoke specifications, integration behavior, and actual unit-testable Runner scripts.

These issues should be addressed together because input contracts are one of the main boundaries that Server tests must exercise.

This PR is a refactor of responsibility boundaries, not a feature expansion.

Do not add unrelated Runners.

Do not redesign Slurm scheduling, QoS, Result Workspace, deployment versioning, or Runner readiness unless directly required by this refactor.

Backward compatibility with obsolete internal positional-input assumptions is not a priority if preserving them would complicate the new contract.

---

# 1. Core design principle

Establish the following invariant:

> A task consumes named input roles, not an ordered list of files.

File ordering may remain relevant inside a collection belonging to one role, but file position must no longer define task semantics.

Replace conceptual behavior such as:

```text
files[0] = primary
files[1:] = auxiliary
```

with:

```text
inputs["receptor"]
inputs["ligands"]
inputs["structure"]
inputs["sequence"]
inputs["trajectory"]
inputs["topology"]
```

depending on the Runner contract.

The role name is part of the task contract.

The physical upload order is not.

---

# 2. Separate five concepts that are currently conflated

The implementation and documentation must distinguish:

```text
physical file
    ↓
file format
    ↓
logical data type
    ↓
task input role
    ↓
Runner scientific preparation
```

Example:

```text
protein.cif
    ↓
mmCIF
    ↓
protein_structure
    ↓
receptor
    ↓
Vina receptor preparation
```

Another example:

```text
ligand.sdf
    ↓
SDF
    ↓
small_molecule_3d
    ↓
ligand
    ↓
Gnina / Vina-specific preparation
```

Do not merge these concepts into one `input_extension` abstraction.

---

# 3. Introduce typed task input contracts

Replace or supersede the current flat input declarations such as:

```text
input_extensions
primary_input_extensions
min_input_files
max_input_files
allow_multiple_inputs
```

with explicit named input specifications.

A conceptual example:

```yaml
inputs:
  receptor:
    title: Receptor
    type: protein_structure
    cardinality:
      min: 1
      max: 1
    formats:
      - pdb
      - mmcif

  ligands:
    title: Ligands
    type: small_molecule_3d
    cardinality:
      min: 1
      max: 32
    formats:
      - sdf
      - mol2
```

Exact schema naming may follow existing project conventions.

Do not retain two equally authoritative contracts.

The typed input declaration must become the source of truth.

---

# 4. Input role cardinality

Each named input role must declare its own cardinality.

Examples:

```text
receptor
    min = 1
    max = 1

ligands
    min = 1
    max = 32

trajectory
    min = 1
    max = 1

topology
    min = 1
    max = 1

optional_reference
    min = 0
    max = 1
```

Do not use global `min_input_files` to express role semantics when role-specific cardinality is available.

Overall task file-count limits may still exist as transport/security limits, but they are not a substitute for role cardinality.

---

# 5. Role binding must be explicit at submission

The API must know which file belongs to which role.

Do not infer role from multipart order.

Conceptually:

```json
{
  "inputs": {
    "receptor": [
      {"upload_id": "upload-1"}
    ],
    "ligands": [
      {"upload_id": "upload-2"},
      {"upload_id": "upload-3"}
    ]
  }
}
```

Exact transport representation may remain multipart plus metadata.

The important invariant is:

```text
upload order != task role
```

---

# 6. Artifact reuse must use the same input contract

Artifact reuse must not have a separate positional semantic model.

An artifact from another task should bind to an explicit role exactly like a local upload.

Conceptually:

```json
{
  "inputs": {
    "receptor": [
      {
        "source": "artifact",
        "task_id": "...",
        "artifact_path": "model.pdb"
      }
    ]
  }
}
```

A task should be able to combine:

```text
receptor from previous task
+
locally uploaded ligand
```

without role meaning changing according to submission order.

This is an important acceptance criterion.

---

# 7. Preserve original task inputs

The immutable task snapshot must preserve the user's original inputs.

Do not replace original files with converted/prepared versions.

Conceptually:

```text
task/
├── inputs/
│   ├── receptor/
│   │   └── original.cif
│   └── ligands/
│       └── aspirin.sdf
│
├── prepared/
│   ├── receptor.pdbqt
│   └── aspirin.pdbqt
│
└── outputs/
```

Exact paths may differ.

The provenance relationship must remain inspectable:

```text
original input
    ↓
validation
    ↓
normalization/preparation
    ↓
runtime input
    ↓
result
```

---

# 8. Introduce an input manifest

Materialize a stable task input manifest before Runner execution.

Conceptually:

```json
{
  "inputs": {
    "receptor": [
      {
        "original_name": "protein.cif",
        "path": "inputs/receptor/protein.cif",
        "format": "mmcif",
        "logical_type": "protein_structure",
        "sha256": "..."
      }
    ],
    "ligands": [
      {
        "original_name": "ligand.sdf",
        "path": "inputs/ligands/ligand.sdf",
        "format": "sdf",
        "logical_type": "small_molecule_3d",
        "sha256": "..."
      }
    ]
  }
}
```

Runner execution should consume this typed manifest or an equivalent stable representation.

Avoid reconstructing semantic roles from filenames.

---

# 9. Separate validation into layers

Do not use one generic `validate_input_file()` concept for everything.

Define clear responsibility boundaries.

The pipeline should be conceptually:

```text
Raw Asset
   ↓
Transport Validation
   ↓
Format Detection / Format Validation
   ↓
Role Binding
   ↓
Role Validation
   ↓
Optional Neutral Normalization
   ↓
Immutable Task Input Snapshot
   ↓
Runner Scientific Preparation
   ↓
Runner Execution
```

Each layer must have a distinct purpose.

---

# 10. Transport validation belongs to Server

Server-owned upload validation should cover safety and transport concerns such as:

```text
file size
file count
path traversal
unsafe filenames
duplicate destination paths
symlinks where relevant
archive safety
hash calculation
storage constraints
declared content size
```

Do not mix scientific assumptions into this layer.

---

# 11. Remove global rejection of binary files

Binary data must not be globally considered invalid.

Future and existing scientific formats may legitimately be binary, including:

```text
XTC
TRR
DCD
NPY
NPZ
PT
other scientific artifacts
```

Whether binary content is accepted must depend on the declared input format/type.

Do not use:

```text
binary == invalid upload
```

as a Server-wide invariant.

---

# 12. File format validation belongs to common file infrastructure

Format validation should answer:

> Is this file actually a valid instance of the claimed format?

Examples:

```text
PDB
mmCIF
FASTA
SDF
MOL2
PDBQT
JSON
CSV
```

The implementation should be reusable across Runners.

Do not add:

```python
if task_type == "gnina":
```

to generic validators.

Prefer logical format/type handlers.

---

# 13. Do not trust filename extension alone

The extension may participate in format detection, but it must not be the only evidence where practical.

For supported structured formats, attempt an actual parse.

Examples:

```text
.pdb  → parse structural records
.cif  → parse mmCIF
.sdf  → parse molecular records
.json → JSON parser
.fasta → sequence parser
```

Report actionable errors.

---

# 14. Introduce logical validation profiles

Task input roles may declare reusable logical validation profiles.

Examples:

```text
protein_structure
small_molecule_3d
protein_sequence
nucleic_acid_sequence
trajectory
topology
alignment
```

Conceptually:

```yaml
receptor:
  type: protein_structure
  validation:
    profile: protein_structure
```

A logical profile may check properties such as:

```text
structure is not empty
contains coordinates
contains expected molecule class
ligand has atoms
ligand has 3D coordinates when required
sequence contains supported alphabet
```

Profiles must remain generic.

Runner-specific scientific preparation does not belong here.

---

# 15. Separate neutral conversion from scientific preparation

Establish a hard distinction:

```text
format normalization
!=
scientific preparation
```

Scientific preparation includes operations such as:

```text
adding hydrogens
protonation
charge assignment
atom typing
rotatable-bond assignment
receptor preparation
ligand preparation
force-field assignment
solvation
energy minimization
```

These operations affect scientific interpretation and belong to the Runner or an explicitly selected scientific preprocessing step.

Do not hide them inside generic Server upload handling.

---

# 16. Treat PDBQT preparation as Runner behavior

Examples:

```text
PDB → PDBQT
SDF → PDBQT
```

must not be presented as trivial generic file conversion.

For Vina/AutoDock-GPU, this belongs to Runner-owned preparation.

Preserve:

```text
original input
prepared input
preparation logs
```

where appropriate.

---

# 17. Avoid silent lossy conversions

Do not silently convert between formats when information may be lost or semantics may change.

For example:

```text
mmCIF → PDB
```

can have representation limitations.

If a Runner requires a narrower runtime format, either:

```text
perform an explicit documented normalization step
```

or:

```text
reject with a meaningful compatibility error
```

depending on the chosen product behavior.

The conversion must be visible in provenance.

---

# 18. Update the task creation UI

The UI must render named input slots.

Do not instruct users to upload files in semantic order.

Replace interfaces conceptually like:

```text
Upload receptor first, then ligand
```

with:

```text
Receptor
[ drop PDB/mmCIF ]

Ligands
[ drop SDF/MOL2 ]
1–32 files
```

The role must be visible to the user.

---

# 19. Support artifact selection per role

The same UI slot should eventually support:

```text
local upload
existing task artifact
future compatible external source
```

without changing the role contract.

The role remains:

```text
receptor
```

regardless of where the data came from.

---

# 20. Runner execution must not depend on upload order

Audit Runner wrappers.

Remove assumptions such as:

```bash
INPUTS[0]
INPUTS[1]
```

when they express semantic roles.

Runner wrappers should receive explicit role-resolved paths.

Collections such as `ligands` may remain ordered if the order itself is useful, but that order is internal to the role.

---

# 21. Do not create a giant universal file-conversion framework

This PR should establish boundaries and contracts.

Do not turn REvoCompute into a generic molecular-format conversion service.

Implement only the common parsers/validators/normalizers required to establish the architecture.

Leave scientifically meaningful preparation inside individual Runners.

---

# 22. Repository-wide testing policy

Add an explicit testing policy to `CLAUDE.md`.

Core principle:

> Test behavior, not repository text.

Agents are forbidden from adding tests whose purpose is to assert the static contents of repository files.

This applies repository-wide.

---

# 23. Ban static-content assertions

Do not add tests that read repository files merely to assert the presence or absence of:

```text
strings
YAML keys
fixed YAML values
JSON values
dependency names
dependency versions
SIF directives
Dockerfile fragments
shell source fragments
JavaScript fragments
CSS selectors
CSS properties
HTML text
documentation text
workflow YAML text
specific file paths
static metadata
```

Examples of prohibited patterns:

```python
source = path.read_text()
assert "something" in source
```

and:

```python
data = yaml.safe_load(path.read_text())
assert data["some_key"] == "some_static_value"
```

when the sole purpose is to mirror static repository declarations.

---

# 24. Do not replace static assertions with snapshots

Snapshot tests of:

```text
task.yaml
plugin.yaml
test.yaml
SIF definitions
deps
HTML
CSS
JS source
```

are also prohibited if they merely freeze static repository content.

Do not rename the same anti-pattern.

---

# 25. Allow real parsers, linters, builders, and executors

The static-content ban does not prohibit real validation.

Valid examples include:

```text
bash -n script.sh
Python import
JSON Schema validation
YAML schema parser
JavaScript syntax parser
CSS linter
HTML parser
Apptainer build
Apptainer %test
runtime invocation
public API behavior
browser behavior
```

The difference is:

```text
consume the asset using the real system
```

instead of:

```text
assert its text looks familiar
```

---

# 26. If something is not behavior-testable, document it

Do not invent source-text tests merely because a requirement exists.

If an invariant is architectural/documentary and cannot reasonably be validated through:

```text
behavior
execution
parser
schema
linter
build
public interface
```

then document it.

Do not manufacture fake regression confidence.

---

# 27. Coverage is not a goal of this cleanup

The cleanup may substantially reduce pytest test count and line coverage.

This is acceptable.

Do not preserve low-value tests to maintain historical coverage numbers.

Do not add trivial tests to compensate for removed static assertions.

Meaningful behavioral confidence takes priority over numerical coverage.

---

# 28. Reorganize test directories

Move toward:

```text
tests/
├── server/
├── runners/
└── integration/
```

Subdirectories may be introduced as useful.

Conceptually:

```text
tests/server/
    api/
    auth/
    tasks/
    scheduler/
    readiness/
    artifacts/
    inputs/
    registry/

tests/runners/
    <runner-name>/

tests/integration/
    task_submission/
    runner_dispatch/
    artifact_reuse/
```

Do not move tests mechanically.

Classify them by responsibility first.

---

# 29. Define Server test ownership

A test belongs under `tests/server/` when it validates Server behavior.

Examples:

```text
API request handling
authentication/authorization
TaskType loading
input contract resolution
input validation
task creation
task persistence
Slurm command construction
scheduler adapters
readiness state machine
receipt handling
artifact indexing
Runner snapshot behavior
server-side result routing
```

A test may mention Runner concepts and still be a Server test.

---

# 30. Use synthetic Runner fixtures for Server tests

Server tests should not depend unnecessarily on production Runners.

Avoid:

```python
assert "gremlin" in registry
assert "alphafold3" in registry
```

Instead create minimal temporary fixture plugins:

```text
fixture_runner/
├── plugin.yaml
└── tasks/
    └── example/
        └── task.yaml
```

Then test:

```text
discovery
contract loading
validation
readiness behavior
```

This prevents the Server test suite from being coupled to the installed Runner catalog.

---

# 31. Define Runner test ownership narrowly

Runner unit tests should exist only when a Runner contains actual executable logic worth testing.

Typical examples:

```text
result parser
input conversion script
parameter builder
command generator
small preprocessing helper
output normalizer
postprocessing script
Runner-owned JavaScript logic with meaningful behavior
```

These belong under:

```text
tests/runners/<runner-name>/
```

---

# 32. Runner declarations do not need unit tests

Do not create pytest tests merely because a Runner contains:

```text
plugin.yaml
task.yaml
test.yaml
deps
SIF definition
run.sh
storyboard
static JS
static CSS
metadata
citations
```

These assets should be validated through their real consumers where necessary.

A Runner with no independently testable script logic may legitimately have:

```text
no pytest unit tests
```

That is expected.

---

# 33. `run.sh` normally does not need source-content unit tests

Do not assert:

```text
specific command strings
specific flags
specific binaries
specific environment variables
```

inside `run.sh`.

Instead use:

```text
shell syntax checks
mocked external-command behavior only when meaningful
smoke/live acceptance
```

If substantial logic accumulates in `run.sh`, move that logic into a testable helper rather than expanding shell-text assertions.

---

# 34. Move complex Runner logic out of shell

Where a Runner has nontrivial logic such as:

```text
output parsing
score extraction
file transformation
manifest processing
complex validation
result normalization
```

prefer a small Runner-owned Python script.

That script may then have real unit tests under:

```text
tests/runners/<runner-name>/
```

Keep shell wrappers orchestration-focused.

---

# 35. Do not pytest-test Runner `test.yaml`

Runner smoke/live specifications are inputs to the live-test system.

Do not write tests like:

```python
smoke = yaml.safe_load(test_yaml)
assert smoke["collections"]["smoke"]["cases"][0]["task"] == "foo"
```

Instead:

```text
test.yaml
    ↓
live-test loader
    ↓
schema validation
    ↓
execution
```

If the `test.yaml` is invalid, the loader should reject it.

Do not duplicate its declarations into pytest.

---

# 36. Separate smoke/live acceptance from pytest

Runner runtime validity is primarily established through:

```text
SIF build
SIF %test
Doctor
smoke test
target-host live acceptance
scientific output verification
exact runtime receipt
```

Do not use pytest to pretend that an external scientific runtime has been validated.

Pytest tests Runner helper logic.

Live acceptance tests the real Runner.

---

# 37. Define integration test ownership

`tests/integration/` should cover boundaries spanning multiple components.

Examples:

```text
HTTP submission → task materialization
typed inputs → Runner manifest
artifact reuse → role binding
Runner discovery → task submission
result artifacts → workspace/API
```

Integration tests should still avoid executing expensive scientific models unless the test is explicitly an integration/live environment test.

---

# 38. Clean current repository-wide static tests

Audit the full `tests/` tree.

Search for patterns such as:

```text
read_text(
read_bytes(
yaml.safe_load(
json.load(
assert ... in source
assert ... not in source
assert fixed YAML value
assert fixed JS/CSS/HTML fragment
```

Do not blindly delete every occurrence.

Classify each test according to what it actually proves.

---

# 39. Test classification procedure

For each existing test, classify as one of:

```text
KEEP
MOVE
REWRITE
DELETE
```

Use these criteria.

## KEEP

The test verifies meaningful behavior at the correct responsibility boundary.

## MOVE

The test is useful but currently located in the wrong Server/Runner/integration area.

## REWRITE

The requirement is valid, but the current test verifies static content instead of actual behavior.

## DELETE

The test only mirrors repository static content or provides no meaningful regression protection.

---

# 40. Preserve meaningful file-consuming tests

Do not mistake all file reads for static assertions.

This is valid:

```text
create fixture file
    ↓
load through production parser
    ↓
execute production behavior
    ↓
assert resulting state/output
```

This is not:

```text
read repository file
    ↓
assert expected literal text
```

The distinction must be documented in `CLAUDE.md`.

---

# 41. Rework Runner registry tests

Server registry tests should validate general discovery behavior.

Use temporary fixture Runners.

Test cases should include:

```text
valid plugin is discovered
invalid plugin is rejected
duplicate IDs are handled correctly
task contract can be loaded
disabled/unavailable state behaves correctly
```

Do not assert that the current production Runner list contains specific names.

Production inventory is not a Server unit-test invariant.

---

# 42. Rework readiness tests

Keep meaningful readiness state-machine tests.

Examples:

```text
runtime identity changes → previous acceptance becomes stale
missing receipt → not ready
matching tested runtime → ready
snapshot mismatch → stale/not ready
```

These are Server behaviors.

They belong under:

```text
tests/server/readiness/
```

Use synthetic Runner fixtures where possible.

Do not assert static SIF/task file contents.

---

# 43. Rework frontend tests

Delete tests that read HTML, JS, or CSS source files and assert fixed strings.

Frontend tests should use, as appropriate:

```text
JavaScript unit behavior
DOM behavior
Playwright
HTTP-rendered pages
accessibility checks
syntax/lint/build validation
```

Do not pytest source text.

---

# 44. Rework workflow tests

Do not read GitHub Actions YAML and assert that particular command strings are absent or present.

If an architectural constraint such as:

> CI must never issue production acceptance receipts

needs enforcement, prefer enforcing the security boundary in executable code/credentials/permissions so CI cannot perform the operation.

Then test that behavioral boundary.

Do not rely on grep-style workflow assertions as the security mechanism.

---

# 45. Runner test directory migration

Move legitimate Runner tests into:

```text
tests/runners/<runner-name>/
```

Examples:

```text
tests/runners/autodock_vina/test_parse_results.py
tests/runners/gnina/test_parse_results.py
tests/runners/diffdock/test_result_normalization.py
```

Place Runner-specific fixtures adjacent to that Runner's tests:

```text
tests/runners/<runner-name>/data/
```

Avoid a central giant:

```text
tests/test_docking_runners.py
```

if the tests actually belong to separate Runner implementations.

---

# 46. Do not require every Runner to have a test directory

Do not create empty directories or placeholder tests.

If a Runner has no unit-testable scripts:

```text
tests/runners/<runner>/
```

does not need to exist.

Smoke/live acceptance remains its validation mechanism.

---

# 47. Future Runner repository compatibility

Do not split the Runner repository in this PR.

However, structure Runner tests so that a future extraction is straightforward.

The desired conceptual portability is:

```text
server repo
    tests/server/
    tests/integration/

runner repo
    tests/runners/
```

Avoid new cross-directory assumptions that would make this future split difficult.

---

# 48. Add testing policy to CLAUDE.md

Add a dedicated section with clear agent instructions.

At minimum include:

> Test behavior, not repository text.

> Do not add test cases or assertions for static Runner or Server content, including deps, SIF definitions, YAML declarations, JS, CSS, HTML, workflow text, dependency pins, or documentation.

> Runner unit tests are only expected for Runner-owned executable logic such as parsers, converters, normalizers, or other scripts.

> Runner runtime correctness is established through build, smoke, and live acceptance, not by pytest assertions about static declarations.

> Server tests must exercise Server-owned behavior and should use synthetic Runner fixtures where practical.

> A decrease in test count or coverage caused by removing meaningless static tests is acceptable.

---

# 49. Add input-contract policy to CLAUDE.md

Document:

> Task inputs are named roles, not positional files.

> Do not introduce new code that assigns semantic meaning based solely on upload order.

> File format, logical data type, task role, and Runner scientific preparation are separate concepts.

> Generic Server validation must not silently perform scientifically meaningful preparation.

> Preserve original user inputs for provenance.

---

# 50. Preserve source-of-truth ownership

After this PR, avoid duplicate sources of truth.

Examples:

```text
task.yaml declares accepted task inputs
```

Tests should verify behavior produced by that declaration.

They should not replicate it.

Likewise:

```text
test.yaml declares smoke cases
```

The live-test engine consumes it.

Pytest should not duplicate it.

And:

```text
SIF definition declares build/runtime environment
```

The build system validates it.

Pytest should not grep it.

---

# 51. Typed input contract tests

Add behavioral tests for typed inputs.

Use synthetic task types.

Cover at minimum:

```text
required role present → accepted
required role missing → rejected
too many files for role → rejected
wrong format for role → rejected
multiple roles supplied in arbitrary multipart order → correctly bound
artifact reference + upload combination → correctly bound
unknown role → rejected
optional role absent → accepted
```

These are Server input-contract tests.

---

# 52. Format validator tests

Where generic file parsers exist, test the parser itself using small fixtures.

Examples:

```text
valid PDB → accepted
invalid PDB → rejected
valid SDF → accepted
malformed SDF → rejected
```

These are meaningful parser tests.

Do not test:

```text
".sdf" is listed in some task.yaml
```

---

# 53. Role-validator tests

Where reusable logical validation profiles exist, test them directly.

Examples:

```text
empty structure → rejected as protein_structure
valid protein coordinates → accepted
empty SDF → rejected as small_molecule_3d
2D ligand when 3D required → appropriate rejection
```

Use clear error messages.

Avoid Runner-specific conditionals inside generic validators.

---

# 54. Scientific preparation tests belong to Runner scripts

If a Runner owns preparation code, test the preparation helper.

Examples:

```text
input molecule
    ↓
Runner preparation helper
    ↓
expected structured output/properties
```

Do not test external scientific binaries by recreating their entire behavior.

Mock only the external process boundary where useful.

Real runtime behavior belongs to smoke/live acceptance.

---

# 55. Error messages are part of the contract

Typed input validation should produce role-aware errors.

Prefer:

```text
Input role 'receptor' requires exactly one protein structure.
```

over:

```text
Invalid number of files.
```

Prefer:

```text
Input role 'ligands' does not accept FASTA.
```

over:

```text
Unsupported extension.
```

Tests should validate error classes/semantic results where practical rather than brittle full prose strings.

---

# 56. Do not overfit tests to exact wording

Even behavioral tests can become brittle.

Prefer checking:

```text
error code
error category
role name
structured validation result
```

instead of asserting entire human-facing sentences.

Avoid replacing static-file brittleness with error-message brittleness.

---

# 57. Define structured validation results

Where useful, introduce structured internal validation errors such as:

```text
code
role
format
path
message
```

Conceptually:

```json
{
  "code": "input_role_cardinality",
  "role": "receptor",
  "message": "Exactly one receptor is required."
}
```

This improves API/UI behavior and makes tests less dependent on exact prose.

Do not over-engineer a large validation framework beyond current needs.

---

# 58. Migration strategy

Audit existing task types.

Map old positional declarations to named roles.

Do not attempt to invent rich semantics for every Runner in one pass if doing so would make the PR unmanageable.

Prioritize a coherent migration strategy.

At minimum, establish typed contracts for representative classes such as:

```text
single sequence
single structure
structure + ligand
multiple ligands
artifact + uploaded input
```

If all current Runners can be migrated cleanly in this PR, do so.

Otherwise, make the new model authoritative and migrate remaining Runners in a tightly defined follow-up.

Do not leave ambiguous dual semantics indefinitely.

---

# 59. Docking should be a reference implementation

Use the docking Runners as an important test case for the new typed input model.

Conceptually:

```text
AutoDock Vina
    receptor: exactly 1 protein structure
    ligands: 1..N small molecules

AutoDock-GPU
    receptor: exactly 1 protein structure
    ligands: 1..N small molecules

Gnina
    receptor: exactly 1 protein structure
    ligand: exactly 1 small molecule

DiffDock
    receptor: exactly 1 protein structure
    ligand: exactly 1 small molecule
```

Do not encode these roles using file position.

---

# 60. Think ahead to MD without implementing MD-specific workflow logic

The design should naturally support future contracts such as:

```text
structure
topology
trajectory
index
optional reference
```

Do not hard-code a docking-specific abstraction.

Likewise, future structure prediction should naturally support:

```text
sequence
optional_templates
optional_msa
```

The generic abstraction is:

```text
named typed role + cardinality + accepted formats
```

---

# 61. Keep Server generic

Server may understand reusable scientific file types.

Server must not know:

```text
how Vina protonates receptors
how Gnina defines scoring
how DiffDock embeds residues
how Rosetta prepares poses
```

Those belong to Runner implementations.

The Server understands:

```text
this is a protein structure
this role requires one structure
this file parses correctly
this task snapshot binds it as receptor
```

---

# 62. Keep Runner preparation explicit

Runner preparation should be visible in:

```text
logs
prepared artifacts
result provenance
```

Where scientific preparation changes the user's input, preserve enough information to understand what happened.

Do not silently overwrite original inputs.

---

# 63. No central scientific-preparation registry

Do not create a large registry such as:

```text
ProteinPreparationEngine
DockingPreparationRegistry
UniversalMoleculeConverter
```

unless a demonstrated shared need emerges later.

Keep preparation local to each Runner or to genuinely reusable scientific utilities.

This PR is about boundaries, not framework proliferation.

---

# 64. Test execution groups

After restructuring, provide clear commands for meaningful groups.

Conceptually:

```text
pytest tests/server
pytest tests/runners
pytest tests/integration
```

If the project uses Make targets, expose equivalent targets as appropriate.

Do not make all Runner smoke/live acceptance part of normal pytest.

---

# 65. CI restructuring

Normal CI should primarily run:

```text
Server unit tests
Runner script unit tests
integration tests
schema/parser/lint checks
safe build validation
```

Do not require production GPU or Slurm for ordinary CI.

Target-host acceptance remains separate.

---

# 66. Avoid CI tests of production inventory

CI should not fail because a production Runner was intentionally added, removed, disabled, or reorganized unless the Server contract itself is invalid.

Test the discovery mechanism.

Do not freeze the catalog.

---

# 67. Review every current test before deletion

Before removing a suspicious test, identify what requirement it was originally trying to protect.

If the requirement is still valid:

```text
rewrite as behavioral test
```

If the requirement is obsolete or already guaranteed by another mechanism:

```text
delete
```

Do not mechanically delete useful behavioral coverage merely because the file contains `read_text()`.

---

# 68. Avoid duplicate integration coverage

After restructuring, look for multiple tests proving the same API/task lifecycle through slightly different production Runners.

Prefer one strong synthetic integration fixture over many Runner-specific copies.

Runner-specific differences belong in Runner helper tests or live acceptance.

---

# 69. Remove empty ceremony tests

Delete tests that effectively prove:

```text
file exists
directory exists
YAML contains expected key
Runner name appears in file
dependency name appears in deps
CSS class appears in stylesheet
documentation URL appears in template
```

unless the existence itself is an actual runtime contract consumed through production behavior.

---

# 70. Do not assert implementation details unnecessarily

Even legitimate unit tests should prefer public/helper behavior over private implementation structure.

Do not create a new generation of brittle tests that assert:

```text
specific helper function name
specific internal dict structure
specific filesystem implementation detail
```

unless it is a real contract.

---

# 71. Establish a small testing philosophy section

Document the intended testing pyramid for REvoCompute:

```text
Server unit tests
    test REvoCompute-owned logic

Runner script unit tests
    test small Runner-owned logic

Integration tests
    test Server/Runner boundaries

Smoke tests
    test candidate runtime can execute representative task

Live acceptance
    test exact target-host runtime end-to-end
```

Do not make one layer substitute for another.

---

# 72. Runner readiness remains independent

Do not weaken Runner readiness while reorganizing tests.

A Runner can have:

```text
zero pytest tests
```

and still be production-ready if:

```text
contract valid
runtime built
self-test valid
live acceptance valid
receipt valid
```

Likewise:

```text
100% pytest coverage
```

must never imply that a Runner is production-ready.

---

# 73. Update developer documentation

Update relevant documentation to explain:

```text
how to declare typed inputs
how to add a file-format validator
how to add a logical validation profile
what belongs in Server
what belongs in Runner
where Runner unit tests belong
when not to write a unit test
how smoke/live tests differ from pytest
```

Keep examples small and representative.

---

# 74. CLAUDE.md must prevent regression

Explicitly instruct coding agents:

* Do not assign task roles by upload order.
* Do not add `primary_input_extensions`-style positional semantics to new features.
* Do not silently perform scientific preparation in Server validation.
* Do not add static-content assertions.
* Do not write Runner unit tests merely to increase coverage.
* Do not pytest-test `task.yaml`, `plugin.yaml`, `test.yaml`, SIF, deps, JS, CSS, or docs as static content.
* Use synthetic Runner fixtures for Server tests.
* Put actual Runner helper tests in `tests/runners/<runner-name>/`.
* Accept reduced test count/coverage when deleting meaningless tests.
* Use smoke/live acceptance for actual Runner runtime correctness.

---

# 75. Preserve the previously agreed scheduler-agent rule

Do not lose the operational rule discussed for GPU availability.

`CLAUDE.md` must also retain:

```text
squeue
    ↓
identify blocker
    ↓
scontrol show job
    ↓
infer likely duration
```

For unclear jobs:

```text
sleep 600
```

then inspect once more.

For clearly long production workloads such as MD:

```text
defer GPU-dependent live acceptance for the current delivery
```

Do not enter long polling loops.

This is orthogonal to this refactor but should remain in the same agent policy document.

---

# 76. Security considerations

Typed input handling must preserve or strengthen:

```text
path traversal prevention
filename sanitization
upload size limits
role cardinality limits
artifact authorization
artifact ownership/access rules
immutable snapshot behavior
hash/provenance tracking
```

Do not allow role metadata to become a path component without sanitization.

Do not trust client-supplied detected format without Server verification.

---

# 77. Performance considerations

Avoid repeatedly parsing large files unnecessarily.

Where practical:

```text
upload
    ↓
hash
    ↓
validate once
    ↓
record validation metadata
```

Do not re-run expensive generic validation at every API read.

However, Runner scientific preparation may independently parse the input as required.

---

# 78. Validation metadata

Consider storing compact validation metadata with the task input snapshot.

Conceptually:

```json
{
  "format": "pdb",
  "logical_type": "protein_structure",
  "validation": {
    "status": "valid"
  }
}
```

Do not store excessive parser-internal state.

The purpose is provenance and avoiding redundant validation.

---

# 79. File names must not define semantics

Do not infer:

```text
"receptor" in filename → receptor
"ligand" in filename → ligand
```

unless offered only as a UI suggestion that the user can explicitly confirm.

The authoritative binding is the task role.

---

# 80. Extensions must not define task roles

Likewise:

```text
.pdb does not automatically mean receptor
.sdf does not automatically mean ligand
```

A PDB could be:

```text
receptor
reference
template
starting_structure
```

Role belongs to the task contract.

---

# 81. Define role identity independently from display labels

Use stable internal role IDs such as:

```text
receptor
ligands
structure
sequence
```

and separate human-facing labels:

```text
Receptor structure
Ligands
Input structure
Protein sequence
```

Do not use UI prose as internal identifiers.

---

# 82. Role ordering is presentation only

The task contract may specify display order for UI.

That order must not affect runtime semantics.

Example:

```text
display:
    receptor first
    ligands second
```

does not mean:

```text
multipart file 0 = receptor
```

---

# 83. Structured task manifest becomes Runner boundary

Aim for a Runner invocation boundary in which the Runner can inspect something conceptually like:

```json
{
  "task": "...",
  "parameters": {...},
  "inputs": {...}
}
```

The Runner should not need to rediscover role semantics from the filesystem.

This will also simplify eventual Runner repository extraction.

---

# 84. Future repository split readiness

Do not implement the split now.

But avoid Server tests that import Runner-specific implementation modules directly.

Runner-specific helper tests may do so.

The eventual separation should conceptually allow:

```text
REvoCompute
    Server contract + integration protocol

REvoCompute-Runners
    Runner implementations + Runner-owned helper tests
```

The typed manifest is a useful future protocol boundary.

---

# 85. Remove obsolete test helpers

After deleting static tests, audit helper functions and fixtures used only by those tests.

Delete dead:

```text
static-file readers
text assertion helpers
Runner inventory fixtures
snapshot helpers
hard-coded production Runner lists
```

Do not leave unused testing infrastructure.

---

# 86. Rename misleading tests

Where useful tests remain, rename them according to responsibility.

Avoid vague names like:

```text
test_runner_architecture.py
test_tasks.py
```

when the actual subject is:

```text
readiness
registry
input_contract
task_submission
```

Directory structure should communicate intent.

---

# 87. Keep fixtures small

Runner script fixtures should be minimal.

Examples:

```text
one compact Vina log
one small SDF
one tiny PDB
one synthetic summary
```

Do not commit large model outputs merely for unit tests.

Large scientific validation belongs in smoke/live environments.

---

# 88. No fake scientific success tests

Do not claim a Runner works because:

```text
command string assembled
expected output filename predicted
static SIF contains binary name
```

These may be useful small helper tests only if they test real helper behavior.

They are not substitutes for live acceptance.

---

# 89. Update contribution guidance

A future Runner contribution should answer:

```text
Does this Runner contain custom executable helper logic?
```

If no:

```text
no pytest Runner tests required
```

If yes:

```text
put focused tests in tests/runners/<runner-name>/
```

Always:

```text
provide smoke/live acceptance specification
```

according to current Runner conventions.

---

# 90. PR review checklist

Before finishing the PR, review specifically for regressions of the old patterns.

Search for newly added:

```text
files[0]
files[1]
primary_input_extensions
read_text + literal assert
production Runner names in Server tests
pytest tests for test.yaml
pytest tests for SIF/deps/CSS static content
```

Not every occurrence is automatically wrong.

Inspect semantics.

No new positional-role dependency or static-content test should remain.

---

# 91. Expected test suite after cleanup

The test suite should be smaller and easier to explain.

A reviewer should be able to answer:

```text
Why does this test exist?
What production behavior does it protect?
Who owns that behavior?
```

If those questions cannot be answered clearly, reconsider the test.

---

# 92. Verification

Run the reorganized suites independently.

Conceptually:

```text
pytest tests/server
pytest tests/runners
pytest tests/integration
```

Also run the repository's normal aggregate test target.

Run relevant:

```text
schema validation
linters
shell syntax
JS syntax/build checks
Apptainer-safe build tests where available
docs validation
git diff --check
```

Do not reintroduce static-content pytest assertions just to satisfy an old test count.

---

# 93. Document removed tests

In the PR description, summarize test cleanup by category rather than enumerating every deleted assertion.

Example:

```text
Removed:
- static HTML/CSS/JS source assertions
- static Runner manifest assertions
- static smoke-test YAML assertions
- production Runner inventory assertions

Replaced with:
- synthetic Server registry tests
- typed input contract behavior tests
- focused Runner parser/helper tests
- existing smoke/live acceptance pipeline
```

This makes the intentional coverage reduction understandable.

---

# 94. Definition of done

This PR is complete when:

1. Task input semantics are role-based rather than positional.

2. Input role, file format, logical type, and scientific preparation are represented as separate concepts.

3. Artifact reuse binds artifacts to explicit roles.

4. Multipart upload order no longer determines scientific meaning.

5. Original user inputs are preserved in the immutable task snapshot.

6. Runner-prepared files remain distinct from original inputs.

7. Generic Server validation is separated into transport, format, and role/logical validation.

8. Binary scientific formats are no longer globally rejected merely for being binary.

9. Scientific preparation remains Runner-owned.

10. The UI renders named input roles instead of instructing users to upload in semantic order.

11. The Runner execution boundary receives role-resolved inputs.

12. Existing repository-wide static-content tests have been audited and unnecessary ones removed.

13. No test asserts static Runner deps, SIF, YAML, JS, CSS, HTML, workflow text, dependency pins, or documentation merely as repository content.

14. Server tests live under `tests/server/` or the agreed equivalent.

15. Runner-specific unit tests live under `tests/runners/<runner-name>/`.

16. Only Runner-owned executable helper logic is unit tested.

17. Runners without testable helper logic are not forced to have pytest tests.

18. Runner `test.yaml` smoke definitions are consumed by the live-test system rather than pytest-tested as static YAML.

19. Server tests use synthetic Runner fixtures where production Runner identity is not part of the behavior being tested.

20. Cross-component behavior is separated into integration tests.

21. Meaningful readiness, registry, API, scheduler, artifact, and input-contract tests remain intact.

22. Reduced pytest count or code coverage caused by removing meaningless tests is accepted and documented.

23. `CLAUDE.md` contains explicit rules preventing reintroduction of positional input semantics and static-content tests.

24. `CLAUDE.md` retains the bounded scheduler inspection rule using `scontrol show job`, including immediate deferment for clearly long production MD/GPU workloads.

25. The final test structure is compatible with a future split in which Runner implementations and their tests move to a dedicated repository.

26. Normal CI passes.

27. No production scientific readiness requirement is weakened as part of the test cleanup.

28. The PR description explains the architectural boundary change and why fewer tests can represent stronger testing.
