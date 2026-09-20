# TODO — Scientific Input Contracts and Runner Expansion

## Goal

Fix scientific-input validation boundaries, restore correct online/local MSA semantics, update OpenDDE and ColabFold, and adapt, validate, and enable the next Runner set with reproducible assets, complete result protocols, and target-host acceptance tests.

---

# 0. Scope

This PR intentionally combines two related pieces of work:

1. repair scientific input contracts exposed by Chai-1 and Boltz;
2. expand the Runner host with the next batch of validated scientific capabilities.

Target Runner work:

* RFdiffusion2
* Foundry
* GeoDock
* BoltzGen
* Pallatom-Ligand
* P2Rank
* fpocket
* DeepPocket
* MolProbity
* FRODOCK

Existing Runner follow-up:

* OpenDDE
* ColabFold / AlphaFold2
* Chai-1
* Boltz

Do not mix this work with Project Dashboard, Project semantics, workflow-editor development, AI integration, or unrelated frontend redesign.

Keep REvoCompute project-neutral.

---

# 1. Baseline audit before editing

Before implementation:

* pull the latest remote `main`;
* inspect all currently open/merged Runner-related work;
* create a dedicated branch for this PR;
* record the current passing baseline;
* inspect `IMPLEMENTATION_STATE.md`;
* inspect the Runner protocol and current enabled Runner list;
* inspect current task/result workspace conventions;
* inspect current security/input-validation architecture;
* inspect current model-resource conventions;
* inspect access-entitlement policies.

Run the existing unit/integration/documentation checks before editing so regressions can be distinguished from existing failures.

Do not reimplement infrastructure already present on `main`.

---

# 2. Fix the Chai-1 rich FASTA validation bug

## Problem

REvoCompute currently dispatches `.fasta`, `.fa`, and `.faa` inputs through the standard FASTA residue-alphabet validator.

Chai-1 uses FASTA framing for a richer entity specification containing:

* protein;
* RNA;
* DNA;
* modified polymers;
* ligand SMILES;
* glycans.

Therefore legal Chai inputs may contain characters such as:

```text
(
)
[
]
=
#
@
```

and other syntax that is invalid in a standard protein FASTA sequence.

The current failure:

```text
FASTA sequence contains invalid character '('
```

is therefore a Core validation bug.

## Required architecture

Separate:

```text
physical serialization
```

from:

```text
scientific dialect / logical input contract
```

Do not loosen the global standard FASTA alphabet.

Standard protein FASTA must remain strict.

Introduce a Core-owned logical/dialect profile for Chai entity FASTA, conceptually:

```text
fasta
    ├── standard protein FASTA
    └── chai entity FASTA
```

The trusted Core remains responsible for preflight validation.

Runner directories must not be allowed to inject arbitrary executable validators into the trusted upload boundary.

## Chai validation requirements

Preflight should validate enough structure to reject obviously malformed input while leaving canonical semantic parsing to Chai itself.

Validate at least:

* FASTA framing;
* non-empty records;
* supported Chai entity headers;
* `protein`;
* `ligand`;
* `rna`;
* `dna`;
* `glycan`;
* obvious malformed bracket syntax;
* reasonable input-size ceilings.

Do not attempt to fully reimplement Chai's upstream parser.

## Regression tests

Add tests proving:

```text
standard FASTA containing "("
    -> rejected

Chai ligand record containing SMILES with "()=#"
    -> accepted

Chai modified polymer record such as AGT(ASP)TG
    -> accepted

malformed Chai entity type
    -> rejected

unbalanced modification delimiters
    -> rejected
```

Also add a Chai Runner submission-level regression test using a ligand-containing input.

---

# 3. Fix Boltz MSA handling

## Problem

Current REvoCompute Boltz integration deliberately omits:

```text
--use_msa_server
```

and therefore accepts only:

```text
local MSA
```

or:

```text
msa: empty
```

However upstream Boltz legitimately supports online MSA generation.

The current runtime failure:

```text
RuntimeError: Missing MSA's in input and --use_msa_server flag not set.
```

shows that the REvoCompute input contract does not match the Runner's real capabilities.

## Required behavior

Support all three upstream scientific modes:

```text
1. local uploaded MSA

2. online MSA server

3. explicit single-sequence mode (`msa: empty`)
```

Online MSA is allowed.

Do not treat network access itself as an architectural violation. OpenDDE and ColabFold already demonstrate that network-assisted feature generation and local inference can coexist.

## Parameter contract

Prefer a simple Runner-level control matching upstream semantics.

For example:

```text
use_msa_server: boolean
```

with an appropriate documented default.

Avoid inventing a large MSA policy engine.

Expected semantics:

```text
local MSA reference
    -> reconstruct and use uploaded asset

msa: empty
    -> preserve explicit single-sequence request

MSA missing + use_msa_server=true
    -> allow Boltz to generate the missing MSA online

MSA missing + use_msa_server=false
    -> reject before expensive execution
```

Do not silently inject `msa: empty`.

Explicit single-sequence inference is a scientific choice and must remain explicit.

## Cross-file validation

For local MSA references:

* require the referenced `.a3m` or `.csv` to exist in uploaded assets;
* resolve only confined relative paths;
* reject missing references;
* reject traversal/absolute-path tricks;
* reconstruct specification + assets in the task-private prepared tree.

## Network behavior

Allow Boltz MSA-server traffic when requested.

Keep model weights and core model assets locally provisioned.

Do not allow arbitrary user-controlled MSA-server URLs unless there is a strong requirement.

Prefer the upstream/default trusted MSA service.

Document the network dependency.

## Tests

Cover:

```text
local MSA -> success

msa: empty -> success

missing MSA + online server enabled -> correct CLI contains --use_msa_server

missing MSA + online server disabled -> preflight/admission failure

missing local MSA asset -> failure before model execution
```

The fake Runner test must no longer universally assert that `--use_msa_server` is absent.

---

# 4. Generalize scientific input profiles

The Chai and Boltz bugs expose the same architectural issue.

Current validation must evolve from:

```text
extension
    -> generic validator
```

toward:

```text
physical format
    +
logical scientific type
    +
Runner-specific dialect profile
    +
cross-file constraints where necessary
```

Keep this implementation small.

Do not introduce a generic schema language unless existing code clearly requires it.

Extend the existing Core logical profile infrastructure rather than creating a second validation system.

Examples that should coexist cleanly:

```text
FASTA + protein_sequence
FASTA + chai_entity_specification
FASTA/YAML + boltz_specification
JSON + alphafold3_specification
JSON + opendde_specification
JSON + foundry_specification
```

Document the distinction in the security/developer documentation.

---

# 5. OpenDDE upgrade

## Current state

REvoCompute currently installs:

```text
opendde[gpu]==1.0.3
```

Current upstream release:

```text
OpenDDE 1.1.1
2026-09-02
```

## Upgrade target

Upgrade to:

```text
OpenDDE 1.1.1
```

unless target-host validation discovers a concrete regression.

Important upstream changes since 1.0.3 include:

* Fold-CP improvements;
* lower peak inference memory;
* bounded/dynamic chunking improvements;
* safer multi-sample and multi-seed execution;
* earlier input validation;
* atomic prediction directories;
* improved read-only-input preprocessing behavior;
* improved output permissions;
* CUDA cleanup fixes;
* MSA/template routing fixes;
* OXT-coordinate repair;
* host PyTorch-state restoration after inference.

These are relevant to a hosted compute service.

## Required work

* update pinned version;
* rebuild image;
* inspect dependency changes;
* verify CUDA/cuEquivariance/Triton behavior;
* retain PyTorch triangle-kernel fallback unless accelerated kernels are proven stable on target hosts;
* verify existing checkpoint compatibility;
* verify existing result paths;
* verify multi-seed output collection;
* verify current writable-snapshot workaround;
* simplify the workaround only if 1.1.1 demonstrably makes part of it unnecessary;
* do not delete defensive code merely because upstream claims read-only-input improvements.

## Acceptance tests

At minimum:

* protein monomer;
* small mixed-complex case if already available;
* MSA-enabled case;
* template-enabled case;
* multiple seeds;
* at least two samples if affordable.

Verify result protocol selectors after the upgrade.

---

# 6. ColabFold upgrade

## Current state

REvoCompute currently uses an older ColabFold commit corresponding to the 1.6.2 generation and pins:

```text
alphafold-colabfold==2.3.18
```

Upstream released:

```text
ColabFold 1.6.3
2026-09-14
```

with:

```text
alphafold-colabfold 2.3.20
```

and newer runtime requirements.

## Upgrade

Move the Runner to the reproducibly pinned ColabFold 1.6.3 release/commit.

Update relevant dependency pins.

Do not blindly move to arbitrary `main`.

## Evaluate new upstream capabilities

Inspect and, where appropriate, expose:

```text
--use-fast-kernels
--kernel-backend
--compile-mode
```

Do not enable new fused kernels globally without target-host validation.

Target hardware includes modern NVIDIA GPUs, so fast kernels are worth testing.

Keep a conservative fallback.

## Result protocol

Recent ColabFold development includes additional complex-quality metrics such as:

```text
ipSAE
pDockQ2
```

Inspect the actual 1.6.3 output schema.

If these metrics are emitted:

* preserve them;
* expose them through result protocol when meaningful;
* do not synthesize missing values;
* keep old result files compatible where practical.

## Relaxation regression

Explicitly retest the historical OpenMM relaxation failure.

Test:

```text
num_relax = 0
num_relax = 1
```

and verify that:

* structure prediction succeeds;
* relaxation succeeds when requested;
* an OpenMM failure is reported clearly;
* failure does not destroy unrelaxed prediction artifacts.

## ColabFold2 preview

Upstream added `ColabFold2_preview` on 2026-09-19.

This is explicitly **out of scope** for this PR.

Do not treat a new experimental notebook as a replacement for the production `colabfold_af2` Runner.

Track separately after its architecture, licensing, model assets, and scientific role stabilize.

---

# 7. RFdiffusion2 — graduate staged implementation

Current REvoCompute already contains substantial RFdiffusion2 implementation.

Do not rewrite it.

## Tasks

Validate and enable the existing:

```text
rfdiffusion2_motif_scaffold
rfdiffusion2_ligand_binder
```

Confirm:

* pinned upstream revision;
* checkpoint identity;
* asset checksum;
* academic-access policy;
* deterministic input preparation;
* task schema;
* result protocol;
* output inventory;
* no accidental W&B/network dependency;
* SLURM/Apptainer compatibility.

## Live acceptance

Run at least:

### Motif scaffolding

Use a small canonical motif-scaffolding case.

Verify:

* PDB output;
* TRB/provenance output;
* expected number of designs;
* non-empty coordinates;
* task completion marker.

### Ligand binder

Use a small ligand-containing PDB with the required ORI convention.

Verify:

* generated binder backbone;
* ligand retention;
* metadata;
* result-view selectors.

After successful target-host tests, move from staged/disabled state to enabled while retaining the academic entitlement gate.

---

# 8. Foundry — complete acceptance and enable

Current implementation already provides:

```text
foundry_rfd3_design
foundry_rfd3na_design
foundry_rf3_fold
```

Do not collapse these into a generic Foundry command.

## Tasks

* provision official checkpoints;
* validate exact asset sizes/hashes;
* record immutable asset identities;
* validate current upstream pin;
* verify Foundry JSON logical profile;
* verify separately uploaded file references;
* keep external URL/path protections;
* verify task-specific output protocols;
* verify entitlement policy.

## Live acceptance

Run one small valid case for each:

```text
RFD3
RFD3NA
RF3
```

A Runner must not be enabled merely because its image builds.

Enable only after all declared task types pass acceptance or clearly document any task remaining disabled.

---

# 9. GeoDock — complete acceptance and enable

Current implementation already exists.

Do not rewrite the adapter unless target-host tests expose a real defect.

## Tasks

* validate upstream pin;
* validate all three model resources;
* validate checksums;
* validate academic-use entitlement;
* run live PPI docking;
* verify both partners remain identifiable;
* verify docked structure;
* verify confidence records;
* verify optional minimization behavior if currently supported;
* verify result protocol.

Use two small protein partners for the acceptance case.

Enable after live target-host success.

---

# 10. BoltzGen — new Runner

Canonical upstream:

```text
HannesStark/boltzgen
```

Perform a fresh Runner intake.

## Intake

Determine and record:

* exact upstream revision;
* code license;
* model/checkpoint terms;
* checkpoint source;
* runtime dependencies;
* GPU requirements;
* expected VRAM;
* supported input schema;
* supported design modes;
* output layout;
* whether network is required;
* citation.

Do not infer runtime compatibility from Boltz merely because of the name.

## Initial capability

Prefer one coherent initial design capability instead of exposing every experimental upstream mode.

Preserve BoltzGen's structured design specification rather than reducing it to dozens of unrelated CLI flags.

## Results

At minimum preserve:

* generated structures;
* generated sequences where produced;
* scores/rankings;
* configuration/specification;
* seed/provenance;
* model identity.

Add Runner-owned result views using existing generic workspace plugins.

---

# 11. Pallatom-Ligand — new Runner

Canonical upstream:

```text
levinthal/Pallatom-Ligand
```

## Assets

Inspect the official checkpoint files and record:

* source;
* size;
* SHA-256;
* license/usage terms.

Provision weights outside the image.

## Scientific contract

Initial Runner should focus on Pallatom-Ligand generation:

```text
ligand SDF
    ->
ligand-conditioned all-atom protein generation
```

Expose scientifically important controls such as:

* sequence length;
* number of samples;
* batch size;
* secondary-structure condition where supported;
* SASA condition;
* seed.

## Important boundary

Upstream can optionally invoke LigandMPNN for redesign.

Do **not** silently embed a second REvoCompute Runner workflow inside Pallatom-Ligand.

For the first adaptation:

```text
Pallatom-Ligand generation
```

should remain the Runner's responsibility.

LigandMPNN redesign can later be expressed as an explicit composed workflow:

```text
Pallatom-Ligand
    ->
LigandMPNN
```

where each Task retains independent provenance.

## Acceptance

Use at least one upstream/example ligand and verify ligand retention and non-empty generated structures.

---

# 12. P2Rank — new pocket-detection Runner

Canonical upstream:

```text
rdk/p2rank
```

Pin a tested release or commit rather than following `develop` implicitly.

## Scientific contract

Input:

```text
protein structure
```

Output should preserve:

* ranked pockets;
* pocket scores;
* pocket centers;
* pocket residues;
* pocket points where available;
* upstream raw prediction tables.

## Result views

Use existing generic result components where possible.

Prefer:

```text
pocket ranking table
+
structure-associated pocket/residue data
+
raw downloadable output
```

Do not build P2Rank-specific logic into server Core.

---

# 13. fpocket — new pocket-detection Runner

Canonical upstream:

```text
Discngine/fpocket
```

## Initial scope

Adapt:

```text
fpocket
```

only.

Do not expand this PR into full:

```text
mdpocket
dpocket
tpocket
```

support.

Those may become separate task types later if there is demand.

## Inputs/outputs

Support validated protein structure input.

Preserve:

* pocket ranking;
* fpocket scores;
* volume/geometry descriptors;
* pocket residue/atom outputs;
* raw fpocket output tree.

Normalize enough metadata for the result workspace to present ranked pockets without destroying upstream output.

---

# 14. DeepPocket — new Runner

Canonical upstream:

```text
devalab/DeepPocket
```

Weights have already been downloaded under:

```text
/mnt/db/weights/deeppocket
```

## Asset handling

Do not re-download blindly.

Inspect the existing weight ZIP.

Record:

* filename;
* file size;
* SHA-256;
* expected extracted layout;
* upstream source/version.

Keep the original downloaded archive immutable.

Prepare a reproducible read-only runtime layout.

## Runtime relationship to fpocket

DeepPocket uses fpocket as an algorithmic dependency.

This is different from chaining two independent REvoCompute Tasks.

It is acceptable for the DeepPocket runtime to contain the fpocket executable required by the DeepPocket method.

Pin the fpocket dependency/version used by DeepPocket.

## Results

Preserve:

* initial candidate pockets where useful;
* DeepPocket reranking;
* pocket scores;
* segmentation output;
* pocket/residue spatial information;
* raw upstream outputs.

## Acceptance

Use the same small protein structure used for P2Rank/fpocket where practical.

This gives us a useful three-method comparison fixture:

```text
P2Rank
fpocket
DeepPocket
```

without requiring the server Core to understand pocket consensus.

---

# 15. MolProbity — new structure-validation Runner

Do not create a generic `cctbx` Runner.

The exposed scientific capability is:

```text
MolProbity
```

with CCTBX as its runtime/dependency source.

Canonical source:

```text
cctbx/cctbx_project
```

## Initial outputs

Preserve and expose where available:

* MolProbity score;
* clashscore;
* Ramachandran statistics;
* Ramachandran outliers;
* rotamer outliers;
* C-beta deviations;
* geometry/peptide validation;
* other structured validation tables emitted by the current implementation.

Do not reduce MolProbity to one scalar score.

## Acceptance

Use at least:

```text
one reasonably clean structure
one deliberately problematic structure
```

and confirm the result protocol distinguishes the expected validation signals.

---

# 16. FRODOCK — new docking Runner

Canonical upstream candidate:

```text
chaconlab/FRODOCK
```

Verify this remains the authoritative distribution during intake.

## Intake

Confirm:

* source/license;
* redistribution terms;
* binary/source build process;
* required databases/assets if any;
* CPU requirements;
* supported input constraints.

Do not infer terms from historical FRODOCK publications.

## Scientific contract

Initial task:

```text
protein partner A
+
protein partner B
    ->
ranked docked complexes
```

Preserve:

* ranked poses;
* scores;
* raw docking metadata;
* exact input partner identities;
* executable/upstream provenance.

Use the same general two-partner contract style as GeoDock where scientifically appropriate, without forcing them into the same runtime.

---

# 17. Pocket-method result consistency

P2Rank, fpocket, and DeepPocket should remain independent Runners.

However, make their result presentation conceptually comparable.

Where upstream information exists, expose analogous concepts:

```text
rank
method score
pocket center
residue set
geometry/volume
```

Do not invent values that a method does not provide.

Do not introduce a global `Pocket` database model in this PR.

Do not add Project Dashboard consensus logic.

The result protocol should simply make future cross-Runner comparison possible.

---

# 18. Common requirements for every new Runner

Every newly adapted Runner must include the current REvoCompute Runner contract components.

Use existing examples rather than inventing a second structure.

Expected materials include, as applicable:

```text
plugin.yaml
runner.yaml
task.yaml
run.sh / launcher
container definition
upstream provenance
model-resource documentation
asset checksum manifest
test.yaml
unit/integration tests
result workspace declaration
citation metadata
```

Each Runner must explicitly define:

* scientific purpose;
* input roles;
* supported formats;
* parameters;
* output artifacts;
* resource requirements;
* GPU/CPU behavior;
* network requirements;
* model assets;
* access/license policy;
* stage markers;
* result views;
* smoke/acceptance tests.

No Runner-specific behavior should be added to generic server routes.

---

# 19. Licensing and entitlement review

Before enabling each new Runner:

* record code license;
* separately record model/checkpoint terms;
* distinguish code redistribution from model use;
* identify academic/non-commercial restrictions;
* use existing entitlement infrastructure where required.

Do not assume:

```text
public GitHub repository == unrestricted hosted service
```

If terms cannot be established confidently, keep the Runner staged rather than weakening the access model.

---

# 20. Model/resource handling

Model weights must not be baked into images unless the existing project policy explicitly allows it.

Prefer:

```text
read-only mounted external assets
+
recorded upstream source
+
size
+
SHA-256
+
asset manifest
```

Reuse existing model-resource conventions.

Do not redownload already provisioned assets unless validation proves them invalid.

For DeepPocket specifically, start from:

```text
/mnt/db/weights/deeppocket
```

and inspect the existing ZIP before doing anything else.

---

# 21. Target-host acceptance

A passing mocked unit test is not sufficient for enablement.

For every GPU or scientific binary Runner:

1. build the image;
2. run container self-test;
3. run local/mock adapter tests;
4. run a real target-host task;
5. inspect outputs scientifically;
6. verify result protocol selectors;
7. verify server task lifecycle;
8. verify failure behavior;
9. only then enable.

Record acceptance command/case and representative task ID where project conventions permit.

---

# 22. Failure behavior

A Runner must fail clearly when:

* required model asset is missing;
* asset checksum is wrong;
* input role is absent;
* local referenced asset cannot be resolved;
* output structure is absent;
* expected scoring/result files are absent;
* upstream exits unsuccessfully;
* network-dependent preprocessing fails;
* entitlement is absent.

Do not create `task_finished` merely because the upstream command returned zero if required scientific artifacts are absent.

---

# 23. Result protocols

For all new/updated Runners:

* preserve raw outputs;
* expose the primary scientific result;
* expose meaningful evidence;
* preserve provenance;
* use explicit units;
* define whether higher/lower scores are preferable where upstream defines this;
* represent missing metrics honestly;
* do not synthesize scores;
* do not infer ranking semantics not defined by upstream.

Update the scientific result inventory.

---

# 24. Enablement and registry cleanup

After target-host validation:

* enable successful new Runners;
* graduate RFdiffusion2 / Foundry / GeoDock from staged status as appropriate;
* retain entitlement gates where required;
* update Runner catalog;
* update runtime-family documentation;
* update model-resource documentation;
* update implementation-state documentation;
* update wait-list/adaptation-status documentation.

Do not leave a successfully enabled Runner simultaneously described as "wait list".

---

# 25. Tests

Add or update focused tests for:

## Input validation

```text
standard FASTA
Chai entity FASTA
Boltz YAML
Boltz FASTA
Boltz local MSA references
Boltz online MSA mode
```

## Existing updated Runners

```text
Chai-1
Boltz
OpenDDE 1.1.1
ColabFold 1.6.3
RFdiffusion2
Foundry
GeoDock
```

## New Runners

```text
BoltzGen
Pallatom-Ligand
P2Rank
fpocket
DeepPocket
MolProbity
FRODOCK
```

Tests should cover adapter behavior without requiring production weights in normal CI.

Heavy target-host tests should remain explicit smoke/acceptance cases rather than ordinary CI requirements.

---

# 26. Documentation

Update at least the relevant:

```text
Runner guide
runtime-family reference
security/input-validation documentation
model-resource documentation
result inventory
IMPLEMENTATION_STATE.md
wait-list / adaptation-status document
```

Document the newly clarified rule:

> A filename extension identifies serialization, not the complete scientific meaning of an input. Runner task contracts may select a Core-owned logical validation profile appropriate to that scientific dialect.

Also document that network access is a declared Runner/workflow capability, not inherently forbidden.

---

# 27. Keep the PR bounded

Despite the large Runner batch, do not introduce unrelated infrastructure.

Specifically do not implement:

* Project Dashboard;
* Project membership;
* AI agents;
* MCP;
* generalized workflow editor;
* pocket consensus analysis;
* mdpocket;
* HADDOCK;
* HDOCK;
* new sequence-search products;
* ColabFold2 preview;
* new organization/team authorization;
* generic scientific ontology.

If a new Runner exposes a missing generic capability, implement only the smallest reusable primitive required by the current batch.

Prefer simplification over speculative frameworks.

---

# 28. Final verification

Before opening/updating the PR:

* run focused Runner tests;
* run full Python test suite;
* run JS/browser contract tests;
* run plugin discovery tests;
* run doctor/Runner validation;
* run documentation build with strict mode;
* run Python compilation/static checks currently used by the repository;
* run `git diff --check`;
* inspect all newly added executable files;
* inspect active configuration for stale Runner names;
* inspect generated docs/catalog;
* confirm no Project-domain coupling was introduced.

For each enabled Runner, verify that all mandatory result selectors resolve against a real accepted output set.

---

# 29. Final PR report

The PR description/final agent report must summarize:

1. Chai rich-FASTA bug and its architectural fix.
2. Boltz online/local/single-sequence MSA behavior.
3. OpenDDE version before/after and acceptance results.
4. ColabFold version before/after and acceptance results.
5. ColabFold 1.6.3 result-protocol changes.
6. RFdiffusion2 enablement status.
7. Foundry enablement status.
8. GeoDock enablement status.
9. BoltzGen adaptation status.
10. Pallatom-Ligand adaptation status.
11. P2Rank adaptation status.
12. fpocket adaptation status.
13. DeepPocket adaptation status and exact weight identity.
14. MolProbity adaptation status.
15. FRODOCK adaptation status.
16. Any Runner intentionally left staged and the concrete blocker.
17. Added/changed access policies.
18. Added/changed mounted model resources.
19. Target-host acceptance cases executed.
20. Complete test results.

The PR is complete only when "implemented", "tested", "accepted", and "enabled" are clearly distinguished for every Runner.

