# REvoCompute Runner Change Impact and Image Freshness Contract

## Goal

Define, document, and test a clear Runner change-impact model so REvoCompute can distinguish between:

```text
1. image/build changes
2. execution-contract changes
3. presentation-only changes
```

A Runner image must be rebuilt **only** when its actual image/runtime inputs change.

A scientific live-test must be repeated **only** when executable behavior or the execution contract changes.

Presentation-only metadata changes must not trigger expensive image rebuilds or unnecessary scientific revalidation.

This work must make the rule obvious to both human developers and coding agents adapting future Runners.

---

# Core invariant

Every Runner change belongs to one of three impact classes:

```text
BUILD IDENTITY
    changed
       ↓
REBUILD SIF
       ↓
LIVE TEST


EXECUTION CONTRACT IDENTITY
    changed
       ↓
KEEP EXISTING SIF
       ↓
LIVE TEST


PRESENTATION IDENTITY
    changed
       ↓
KEEP EXISTING SIF
       ↓
KEEP EXISTING LIVE VALIDATION
```

The implementation, documentation, Example Runner, readiness state machine, and tests must agree on this model.

---

# Phase 1 — Audit current freshness behavior

## 1. Document current build provenance

Confirm the current Runner build provenance inputs.

At minimum inspect:

```text
run/revocompute_ctl/registry.py
run/revocompute_ctl/readiness.py
run/revocompute_ctl/live_test.py
run/revocompute_ctl/artifact_evidence.py
```

Current behavior is expected to include approximately:

```text
Runner family identity
family version
definition path
definition SHA256
declared runtime.build_inputs SHA256
Apptainer version
```

Record the exact current behavior before changing it.

---

## 2. Audit validation identity

Determine exactly which Runner/Task files contribute to:

```text
configuration_digest
test_definition_digest
validation receipt identity
submission attestation identity
```

Pay particular attention to:

```text
plugin.yaml
task.yaml
runner.yaml
test.yaml
expected_files.yaml
storyboard
access policies
resource policy
```

Do not assume every YAML change is scientifically meaningful.

---

## 3. Add a temporary developer-facing mapping

Before implementation changes, create a concise internal mapping of:

```text
file / field
→ build impact
→ validation impact
→ presentation impact
```

Use this mapping to drive the later canonical documentation and tests.

---

# Phase 2 — Define the canonical three-layer model

## 4. Build Identity

Build Identity represents everything whose content materially determines the generated SIF.

Typical members:

```text
Runner .def
requirements.txt / requirements.lock / constraints
run.sh
preprocessing code copied into the image
inference wrappers
scientific execution scripts
postprocessing code executed inside the image
patches
compiled helper code
model-code fingerprints when used during image creation
shared runtime helpers copied into the image
```

Changing Build Identity means:

```text
BUILD_STALE
→ rebuild candidate SIF
→ validate candidate
→ live-test candidate
→ promote only after valid receipt
```

---

## 5. `runtime.build_inputs` is authoritative

The Runner manifest must explicitly declare all source files whose content contributes to image behavior.

Example:

```yaml
runtime:
  definition: example.def
  image_artifact: example_v1.sif
  build_inputs:
    - example/run.sh
    - example/analyze.py
    - example/requirements.lock
    - common/task_context.sh
    - common/task_context.py
```

The contract is:

> Every mutable repository file whose content is copied into, imported by, executed from, or otherwise materially affects the SIF must be represented in `runtime.build_inputs`, unless its content is already captured by the `.def` itself or another declared immutable digest.

`build_inputs` must not be treated as documentation.

It is a correctness boundary.

---

# Phase 3 — Guard against missing build inputs

## 6. Audit existing Runner families

Review existing Runner families for obvious omissions.

Examples to inspect:

```text
run.sh
predict.py
launch.py
prepare_input.py
normalize_results.py
validate_assets.py
patch files
requirements / constraints
model asset digest files
shared common helpers
```

Do not add arbitrary files merely because they live in the Runner directory.

Only files that materially affect built/runtime image behavior belong in Build Identity.

---

## 7. Add Doctor validation where practical

Consider whether Doctor can detect common build-input mistakes.

Possible bounded checks:

```text
declared build_inputs exist
paths remain inside Runner tree
duplicates rejected
directories rejected unless explicitly supported
definition exists
```

Do not attempt static import analysis of arbitrary Python.

Do not create a fragile dependency scanner.

---

## 8. Add an explicit documentation warning

The Runner guide must clearly explain the dangerous failure mode:

```text
predict.py changed
but predict.py is absent from build_inputs

→ build provenance remains unchanged
→ active SIF may be incorrectly considered current
→ old scientific code continues running
```

This is more serious than unnecessary rebuilding and must be highlighted accordingly.

---

# Phase 4 — Execution Contract Identity

## 9. Define Execution Contract Identity

Execution Contract Identity represents Core-side/task-side information that materially determines:

```text
what input is accepted
what parameters are accepted
what values are passed to the Runner
what commands/stages are executed
what resources are required
what outputs are expected
how successful execution is validated
```

Typical members include scientifically meaningful portions of:

```text
task.yaml
expected_files.yaml
result parser contract
resource requirements
stage/argument declarations
input role contract
parameter forwarding
execution-affecting defaults
test.yaml
```

Changing this identity means:

```text
active SIF remains build-current
existing validation receipt becomes stale
live-test is required
image rebuild is NOT required
```

---

## 10. Preserve the existing BUILD_STALE vs VALIDATION_STALE distinction

Readiness must retain a clear distinction:

```text
BUILD_STALE
```

means:

```text
the SIF itself no longer corresponds to declared build inputs
```

whereas:

```text
VALIDATION_STALE
```

means:

```text
the SIF may still be correct,
but its previous scientific/operational validation no longer proves the current execution contract
```

Never collapse these into one generic stale state.

---

# Phase 5 — Presentation Identity

## 11. Define Presentation Identity

Presentation Identity includes metadata that changes what users see but not how computation executes.

Typical examples:

```text
display name
short summary
long description
use_when
input/output prose
parameter help text
citations
BibTeX presentation data
documentation links
UI hints
layout hints
viewer labels
category labels
non-scientific presentation metadata
```

Changing only Presentation Identity must result in:

```text
no SIF rebuild
no live-test invalidation
normal server/config deployment only
```

---

## 12. Do not use whole-file hashing when semantics differ

`task.yaml` contains both execution and presentation information.

Therefore this rule is insufficient:

```text
task.yaml changed
→ validation stale
```

The system should distinguish meaningful semantic projections.

Prefer:

```text
Task contract
    ├── execution projection
    └── presentation projection
```

instead of treating the raw file as one indivisible identity.

---

# Phase 6 — Canonical projections

## 13. Add deterministic execution projection

Create a deterministic projection of the parsed TaskType containing only fields that materially affect execution or validation.

Conceptually:

```text
execution_projection(task)
```

may contain:

```text
task id where relevant
input roles
input formats
cardinality
semantic validation profile
scientific parameters
execution-affecting defaults
parameter constraints when they affect valid invocation
arguments
stages
network requirement
resource requirements
expected outputs
result parser / acceptance configuration
runtime-specific task contribution
```

Use parsed objects, not YAML text.

---

## 14. Add deterministic presentation projection only if useful

A separate presentation digest may be useful for diagnostics/deployment stamps.

If implemented:

```text
presentation_projection(task)
```

may contain:

```text
display_name
summary
use_when
help
citations
category
UI hints
presentation metadata
```

This digest must not influence image or live-test freshness.

Do not add a presentation digest merely for architectural symmetry if it has no operational consumer.

---

# Phase 7 — Parameter semantics

## 15. Distinguish execution-affecting parameter changes

Not every parameter-schema edit has the same impact.

Examples:

Changing:

```yaml
default: 5
```

to:

```yaml
default: 10
```

is validation-relevant if the resolved default is actually passed to the Runner.

Changing:

```yaml
help: "Number of samples"
```

to:

```yaml
help: "Number of diffusion samples"
```

is presentation-only.

---

## 16. Bounds require semantic judgment

Changing:

```yaml
maximum: 100
```

to:

```yaml
maximum: 200
```

may or may not require scientific revalidation depending on the contract.

Use a conservative rule initially:

```text
parameter names
types
defaults
execution bounds
enum values
argument mapping
```

belong to Execution Contract Identity.

Presentation strings do not.

Avoid clever field-level optimization unless it is clearly safe and maintainable.

---

# Phase 8 — `family.version`

## 17. Audit `family.version` participation in Build Identity

Current build provenance includes family version.

Determine whether `family.version` itself materially changes SIF contents.

If the version is only:

```text
release metadata
protocol metadata
human-visible revision identity
```

then changing it alone should not force a SIF rebuild.

---

## 18. Separate audit metadata from rebuild inputs

If appropriate, preserve:

```json
{
  "family_version": "2"
}
```

in evidence records for audit/debugging while excluding it from the digest used to determine:

```text
sif_stale()
```

Do not lose useful provenance information merely to avoid rebuilds.

---

## 19. Keep version in Build Identity only if justified

If a Runner `.def` or runtime explicitly consumes the family version during image creation, document that behavior.

Otherwise metadata version bumps must not masquerade as image changes.

---

# Phase 9 — Example Runner as executable documentation

## 20. Make Example Runner the canonical reference

The Example Runner must visually and structurally demonstrate the three impact layers.

Recommended structure:

```text
docker/runners/example/
├── plugin.yaml
├── example.def
│
├── example/
│   ├── run.sh
│   ├── analyze.py
│   └── requirements.lock
│
├── tasks/
│   └── example/
│       ├── task.yaml
│       ├── expected_files.yaml
│       └── storyboard/
│
├── test.yaml
└── README.md
```

---

## 21. Annotate Example Runner build inputs

The Example Runner `plugin.yaml` should contain a clear nearby comment such as:

```yaml
runtime:
  definition: example.def
  build_inputs:
    # Every mutable repository file baked into or executed from the SIF
    # must be listed here. Presentation-only Task metadata does not belong here.
    - example/run.sh
    - example/analyze.py
    - example/requirements.lock
    - common/task_context.sh
    - common/task_context.py
```

Do not duplicate long explanatory prose in YAML.

The full explanation belongs in README/docs.

---

## 22. Add Example Runner README section

Add:

```text
## Change impact and image freshness
```

Explain with concrete examples:

```text
Edit example.def
→ rebuild + live-test

Edit example/analyze.py
→ rebuild + live-test

Edit execution parameter default in task.yaml
→ no rebuild + live-test

Edit citation in task.yaml
→ no rebuild + no live-test

Edit summary/help text
→ no rebuild + no live-test
```

---

# Phase 10 — Canonical documentation

## 23. Add `Runner Change Impact Model` to Standard Runner guide

Make this a prominent section, not a footnote.

Include the canonical matrix:

| Change                                 | Rebuild SIF | Re-run live-test |
| -------------------------------------- | ----------: | ---------------: |
| `.def`                                 |         Yes |              Yes |
| requirements / lockfiles               |         Yes |              Yes |
| `run.sh`                               |         Yes |              Yes |
| preprocessing code inside SIF          |         Yes |              Yes |
| scientific wrapper code                |         Yes |              Yes |
| postprocessing code inside SIF         |         Yes |              Yes |
| shared runtime helper inside SIF       |         Yes |              Yes |
| Task argument forwarding               |          No |              Yes |
| execution-affecting parameter defaults |          No |              Yes |
| Task input/output execution contract   |          No |              Yes |
| resource/runtime execution contract    |          No |              Yes |
| `test.yaml`                            |          No |              Yes |
| display name                           |          No |               No |
| summary / use_when / help              |          No |               No |
| citations                              |          No |               No |
| UI/presentation hints                  |          No |               No |

This table becomes canonical.

Other documentation should link to it rather than maintaining copies with different semantics.

---

## 24. Update deployment/readiness docs

Ensure deployment docs explicitly explain:

```text
BUILD_STALE
```

and:

```text
VALIDATION_STALE
```

using the three-layer model.

The operator should understand:

```text
VALIDATION_STALE does not imply rebuild.
```

---

## 25. Update Runner onboarding checklist

Add a mandatory self-check:

```text
For every Runner file or manifest field:

1. Can changing it alter SIF contents or code executed inside the SIF?
   → Build Identity.

2. Can changing it alter how Core invokes, validates, or accepts the computation?
   → Execution Contract Identity.

3. Can changing it only alter what a user sees?
   → Presentation Identity.
```

---

# Phase 11 — Tests

## 26. Add direct build provenance tests

Using Example Runner or a minimal fixture, prove:

```text
baseline provenance
```

then:

```text
change .def
→ build provenance changes
```

then:

```text
change declared run.sh
→ build provenance changes
```

then:

```text
change declared analyze.py
→ build provenance changes
```

---

## 27. Prove Task presentation does not rebuild

Modify presentation-only fields such as:

```text
summary
help
citation
display label
```

Assert:

```text
build provenance unchanged
sif_stale == false
```

---

## 28. Prove execution-contract change does not rebuild

Change an execution-relevant Task field such as:

```text
parameter default
argument mapping
input role
expected output contract
```

Assert:

```text
build provenance unchanged
```

but:

```text
validation identity changes
```

and readiness becomes:

```text
VALIDATION_STALE
```

---

## 29. Prove presentation-only change preserves validation

This is the key missing behavior if current validation hashes whole Task objects.

Starting from a valid receipt:

```text
READY
```

change:

```text
summary
citation
help text
```

and assert:

```text
READY
```

remains true.

No candidate build and no new scientific live-test should be required.

---

## 30. Prove execution change invalidates validation

Starting from:

```text
READY
```

change an execution-contract field.

Assert:

```text
SIF build provenance remains current
readiness == VALIDATION_STALE
```

---

## 31. Prove build change takes precedence

Starting from:

```text
READY
```

change a build input.

Assert:

```text
readiness == BUILD_STALE
```

not merely:

```text
VALIDATION_STALE
```

Build freshness continues to take precedence.

---

## 32. Test `family.version`

Whichever semantics are chosen must be explicit.

If version becomes audit-only:

```text
family.version changes
→ build provenance digest unchanged
```

If there is a separate validation/release identity, test that independently.

---

# Phase 12 — Deployment stamp and diagnostics

## 33. Improve diagnostic explanation

Where useful, readiness/debug output should communicate why a Runner is stale.

Examples:

```text
BUILD_STALE
  changed build identity:
  example/analyze.py
```

or at minimum:

```text
current build provenance != active build evidence
```

For validation:

```text
VALIDATION_STALE
  execution contract changed
```

Avoid requiring operators to infer that `task.yaml` changed from a generic hash mismatch.

Do not build a large diff engine merely for diagnostics.

---

## 34. Keep presentation changes visible to deployment audit

Presentation-only changes may still appear in:

```text
deployment stamp
repository revision
configuration digest
```

for audit purposes.

That does not mean they should invalidate SIF or live-test receipts.

Audit identity and freshness identity are separate concerns.

---

# Phase 13 — Non-goals

Do not use this work to redesign:

```text
TaskType schema
Runner plugin architecture
Runner access policies
resource accounting
Slurm behavior
scientific Runner implementations
artifact storage
result workspace
deployment topology
```

Do not introduce:

```text
automatic AST dependency discovery
recursive Python import hashing
container introspection dependency scanning
generic build systems
Bazel/Nix-like dependency graphs
```

Explicit `build_inputs` is preferred because it is understandable and reviewable.

---

# Acceptance criteria

The work is complete when:

```text
[ ] Runner documentation defines Build / Execution / Presentation identity.

[ ] The Standard Runner guide contains one canonical change-impact matrix.

[ ] Example Runner visibly demonstrates the model.

[ ] Example Runner plugin.yaml clearly documents build_inputs responsibility.

[ ] Every mutable file that materially affects Example Runner SIF behavior is declared.

[ ] Existing Runner build_inputs receive a bounded audit for obvious omissions.

[ ] Changing .def makes the Runner BUILD_STALE.

[ ] Changing a declared executable build input makes the Runner BUILD_STALE.

[ ] Changing an execution-relevant Task contract does NOT make the SIF BUILD_STALE.

[ ] Execution-contract change makes previous live validation stale.

[ ] Presentation-only Task changes do NOT rebuild the SIF.

[ ] Presentation-only Task changes do NOT invalidate scientific live-test receipts.

[ ] Citations are presentation-only unless they somehow participate in execution.

[ ] Help text / summaries / labels are presentation-only.

[ ] BUILD_STALE and VALIDATION_STALE remain distinct readiness states.

[ ] BUILD_STALE takes precedence when both build and execution identities changed.

[ ] family.version semantics are explicitly decided, documented, and tested.

[ ] family.version does not cause meaningless SIF rebuilds unless it genuinely affects image construction.

[ ] Deployment/readiness docs explain that VALIDATION_STALE usually means live-test only, not rebuild.

[ ] Runner onboarding asks developers to classify every new file/field by change impact.

[ ] CI contains regression tests for all three impact classes.

[ ] No speculative dependency-scanning framework is introduced.
```

---

# Expected end state

After this work, a developer should be able to predict deployment consequences before making a change.

For example:

```text
"I changed predict.py."
→ predict.py is a build_input.
→ rebuild + live-test.

"I changed the default inference parameter."
→ execution contract changed.
→ keep image + live-test.

"I corrected a citation title."
→ presentation only.
→ deploy metadata only.
```

The system should reach the same conclusion automatically.

The guiding rule is:

> Rebuild the image because the image changed, not because a nearby YAML file changed.
>
> Revalidate the science because execution semantics changed, not because presentation text changed.
