# Runner Weights and Model Assets Integration Guide

This document defines how REvoCompute Runner Families should provision, mount, resolve, validate, and consume model weights and other large pretrained assets.

The goal is to avoid a recurring class of deployment failures caused by confusing:

* model weights;
* runtime caches;
* temporary task data;
* scientific outputs;
* container image contents;
* host deployment paths.

The central invariant is:

> **Weights are immutable provisioned resources, not caches, not task data, and not container image contents. Each Runner Family should expose one explicit read-only weight namespace at a stable container path, while writable runtime state is isolated elsewhere.**

---

## 1. Resource ownership model

REvoCompute distinguishes four different storage roles:

```text
weights
    immutable
    shared
    provisioned before execution
    read-only during Tasks

cache
    regenerable
    writable
    disposable

scratch
    Task-local
    temporary
    writable

results
    Task-owned
    persistent
    scientifically meaningful
```

A Runner must not merge these roles into the same directory.

The intended layout is:

```text
HOST
└── /mnt/db/weights/<family>/
        ├── checkpoints/
        ├── configs/
        ├── tokenizer/
        └── other model assets
              │
              │ read-only bind
              ▼
CONTAINER
└── /mnt/db/weights/<family>/
        │
        └── consumed by the upstream model loader

TASK SCRATCH
└── <task-local scratch>/
        ├── tmp/
        ├── cache/
        └── compiled/intermediate state

TASK RESULTS
└── /workspace/outputs/
        └── scientific outputs
```

---

## 2. One authoritative host-side weight root per Runner Family

Each Runner Family should have one authoritative deployment-side weight root.

Examples:

```text
/mnt/db/weights/esm
/mnt/db/weights/alphafold3
/mnt/db/weights/bioemu
/mnt/db/weights/colabfold
```

The Runner should consume these resources through a stable container path.

For example:

```yaml
mounts:
  - source: /mnt/db/weights/esm
    target: /mnt/db/weights/esm
    mode: ro
```

The host-side source may vary between deployments, but the container-side path should remain stable.

The conceptual ownership is:

```text
runner.yaml
    owns host deployment location

Runner Family
    owns internal resource layout

run.sh / upstream program
    consumes stable container paths
```

Do not independently redefine the same weight path in:

```text
.env
Core Python
task.yaml
frontend code
run.sh defaults
multiple runner configuration files
```

---

## 3. Do not treat model weights as cache

A pretrained model checkpoint is not equivalent to a runtime cache.

This distinction is especially important for frameworks such as:

* PyTorch;
* torch.hub;
* Hugging Face;
* JAX;
* TensorFlow;
* upstream scientific CLIs with automatic model resolution.

For example, the following is dangerous:

```bash
export TORCH_HOME="$TASK_SCRATCH/torch"
```

if the upstream program expects a symbolic model name to resolve through:

```text
$TORCH_HOME/hub/checkpoints
```

and the actual provisioned checkpoint lives at:

```text
/mnt/db/weights/esm/checkpoints
```

Pointing `TORCH_HOME` at an empty Task-local directory can hide the provisioned model completely.

Instead, separate writable runtime state from authoritative pretrained assets.

For example:

```text
TORCH_HOME
└── task-local writable state
    └── hub/
        └── checkpoints
              ↓
              symlink
              ↓
/mnt/db/weights/esm/checkpoints
```

This preserves:

```text
temporary state
    → Task scratch

pretrained checkpoints
    → shared read-only weight storage
```

Do not copy large model weights into every Task workspace.

---

## 4. Prefer mounting the semantic resource root

Prefer mounting:

```text
/mnt/db/weights/esm
```

rather than individually mounting:

```text
/mnt/db/weights/esm/checkpoints/model.pt
/mnt/db/weights/esm/config.json
/mnt/db/weights/esm/tokenizer.json
```

Many upstream projects rely on relationships between sibling directories.

A typical model resource tree may contain:

```text
weights/
├── checkpoints/
├── configs/
├── hub/
├── tokenizer/
├── vocab/
├── params/
└── metadata/
```

Mounting the family-level resource root lets the upstream program resolve its own internal layout without Core having to understand model-specific paths.

Therefore:

> **Mount the smallest complete semantic resource root, not individual model files unless there is a strong reason to do otherwise.**

---

## 5. Avoid overlapping mount targets

Overlapping bind mounts are a major source of hard-to-debug behavior.

Avoid configurations such as:

```text
/mnt/db/weights/esm
/mnt/db/weights/esm/checkpoints
```

being mounted independently.

Also avoid hierarchical combinations such as:

```text
/data
/data/models
/data/models/esm
```

unless the overlap is explicitly required and carefully validated.

Overlapping targets can cause:

* child mounts hiding files from parent mounts;
* mount-order-dependent behavior;
* symlinks resolving differently inside and outside Apptainer;
* different filesystem views between login and compute nodes;
* Doctor seeing one resource tree while the scientific process sees another.

The preferred invariant is:

> **A Runner's mount targets should form a non-overlapping set.**

Generic deployment validation should reject accidental parent/child target collisions where possible.

---

## 6. Container images should not contain production weights

The SIF should normally contain:

```text
application code
Python packages
system libraries
CUDA runtime libraries
Runner adapter code
```

It should not contain production model weights.

The weight target inside the SIF should usually be an empty or ordinary mountpoint.

For example:

```text
SIF
└── /mnt/db/weights/esm/
        # mount target only
```

At runtime:

```text
host weights
    ↓ bind
/mnt/db/weights/esm
```

Embedding a second copy of production weights into the SIF is dangerous because the runtime bind mount hides the baked-in contents.

Without a bind:

```text
apptainer exec runner.sif ls /mnt/db/weights/esm
```

may show one dataset.

With the production bind:

```text
apptainer exec --bind ... runner.sif ...
```

the same path may show an entirely different dataset.

Keep the ownership boundary explicit:

```text
SIF
    code and dependencies

host mounts
    weights and databases

Task workspace
    inputs, scratch, and outputs
```

---

## 7. Production weights should be read-only

Model and database resources should normally be mounted:

```text
ro
```

not:

```text
rw
```

For example:

```yaml
mounts:
  - source: /mnt/db/weights/esm
    target: /mnt/db/weights/esm
    mode: ro
```

If an upstream program attempts to write:

```text
downloaded files
lock files
compiled caches
temporary indexes
metadata updates
```

into the weight directory, do not immediately make the weight mount writable.

Instead, redirect writable runtime state to Task-local cache or scratch.

Common variables requiring explicit handling include:

```text
TMPDIR
XDG_CACHE_HOME
TORCH_HOME
HF_HOME
TRANSFORMERS_CACHE
JAX_CACHE_DIR
NUMBA_CACHE_DIR
```

The general rule is:

> **If a file can be regenerated, it does not belong in the authoritative weight namespace.**

---

## 8. Runtime downloads should not be required

Production scientific execution should assume:

```text
network unavailable
weights already provisioned
```

A missing model should fail clearly rather than silently downloading from:

* Hugging Face;
* torch.hub;
* GitHub Releases;
* Google Cloud Storage;
* arbitrary upstream servers.

A useful live-test pattern is to deliberately make network fallback unavailable.

For example:

```text
HTTP_PROXY=unavailable
HTTPS_PROXY=unavailable
```

or use an environment where outbound network access is disabled.

Then execute the real upstream model loader.

A successful test demonstrates that:

```text
symbolic model identifier
    ↓
local resource resolution
    ↓
provisioned weight
```

works without hidden network dependencies.

---

## 9. Resolve symbolic model names explicitly

Many scientific programs accept model identifiers rather than filenames.

Examples:

```text
esm2_t33_650M_UR50D
some-huggingface-model-name
model_1
large
base
```

These names may trigger framework-specific lookup logic.

Therefore, validating only:

```bash
test -f /mnt/db/weights/.../model.pt
```

is insufficient.

The acceptance path should exercise:

```text
symbolic model name
    ↓
upstream loader
    ↓
framework cache/resource resolution
    ↓
actual provisioned checkpoint
```

The real upstream loading mechanism should be tested at least once during Runner acceptance.

---

## 10. Separate resource location from scientific identity

A deployment path and the scientific identity of a model are related, but they are not the same thing.

For example, these host paths:

```text
/mnt/db/weights/esm
/storage/models/esm
```

may contain identical resources.

Changing the host location should be recorded as deployment provenance, but should not necessarily imply that the scientific model changed.

A useful resource record can distinguish:

```text
family
model/version
container path
host source path
critical asset fingerprints
```

For example:

```text
host source path
    deployment provenance

container path
    Runner contract

critical asset SHA256/version
    scientific identity
```

The important principle is:

> **Effective resource contents define scientific identity; host path strings primarily describe deployment provenance.**

---

## 11. Build validation and resource validation are different

A successfully built SIF proves only that the software environment is constructible.

It may verify:

```text
Python
libraries
CUDA runtime
binaries
CLI availability
```

It does not prove that:

```text
weights
databases
model assets
tokenizers
indexes
```

are actually available on the target host.

Therefore, the Runner lifecycle should be:

```text
build SIF
    ↓
Apptainer inspect/test
    ↓
resolve deployment mounts
    ↓
validate weight resources
    ↓
real Slurm live test
    ↓
actual model load
    ↓
scientific execution
    ↓
artifact validation
    ↓
live receipt
    ↓
READY
```

Do not treat a successful SIF build as equivalent to Runner readiness.

---

## 12. Doctor should validate resource structure

Generic Doctor checks should validate deployment/resource structure without learning model-specific scientific vocabulary.

Useful generic checks include:

```text
host source exists
container target is absolute
mount targets do not accidentally overlap
resource source has expected file/directory type
weight resources are read-only by default
service identity can read the resource
declared symlinks remain inside permitted resource roots
resource is expected to be visible from compute nodes
```

Runner-owned probes may add lightweight semantic validation.

For example:

```text
load configuration
load tokenizer metadata
resolve model name
inspect checkpoint header
```

without running an expensive scientific calculation.

The division is:

```text
Doctor
    structural and deployment sanity

live-test
    actual scientific usability
```

---

## 13. Core must not know concrete model paths

Do not introduce model-specific Core logic such as:

```python
if runner == "esm":
    checkpoint_dir = "/mnt/db/weights/esm/checkpoints"
elif runner == "alphafold3":
    model_dir = "/mnt/db/weights/alphafold3"
```

Core should understand only generic concepts such as:

```text
mount
resource
read-only
probe
resource identity
execution plan
```

Concrete resource layout belongs to the Runner Family.

For example:

```text
ESM Family
    knows checkpoints/

AlphaFold3 Family
    knows model parameters/

BioEmu Family
    knows model bundle layout
```

This preserves:

> **Core owns grammar; Runner Families own vocabulary.**

---

## 14. Recommended Runner declaration pattern

A typical Runner Family should look approximately like:

```yaml
mounts:
  - source: /mnt/db/weights/example
    target: /mnt/db/weights/example
    mode: ro
```

The Runner adapter may then consume:

```text
/mnt/db/weights/example
```

or family-specific subpaths such as:

```text
/mnt/db/weights/example/checkpoints
```

The Task contract should not expose deployment paths as user-facing parameters.

Users choose scientific parameters.

Operators configure deployment resources.

---

## 15. Recommended filesystem model

The preferred production topology is:

```text
HOST
│
├── /mnt/db/weights/<family>/
│      ├── model assets
│      ├── configs
│      └── metadata
│
│       one read-only, non-overlapping bind
│                      │
│                      ▼
│
├──────────────── CONTAINER ────────────────
│
│   /mnt/db/weights/<family>/
│          │
│          └── upstream model loader
│
├──────────────── TASK SCRATCH ─────────────
│
│   <task-local scratch>/
│          ├── tmp/
│          ├── cache/
│          ├── compiled/
│          └── intermediate/
│
└──────────────── TASK RESULTS ─────────────
    /workspace/outputs/
           └── scientific outputs
```

---

## 16. Runner intake checklist

Before declaring a new weight-dependent Runner ready, verify:

* [ ] One authoritative host-side model resource root is declared.
* [ ] One stable container-side weight namespace is used.
* [ ] Weight mounts are read-only unless exceptional justification exists.
* [ ] Mount targets do not accidentally overlap.
* [ ] Production weights are not baked into the SIF.
* [ ] Task scratch and cache are separate from model resources.
* [ ] Runtime downloads are not required.
* [ ] Symbolic model identifiers resolve to local assets.
* [ ] Service UID/GID can read all required assets.
* [ ] Compute nodes can see the same mounted resource path.
* [ ] Doctor validates resource structure.
* [ ] Apptainer inspect/test passes.
* [ ] Real Slurm execution loads the actual model.
* [ ] Required scientific artifacts are produced.
* [ ] Exact resource/SIF provenance is recorded in the live receipt.
* [ ] Final `runner-status` reports `READY`.

---

## 17. Anti-patterns

Avoid the following patterns.

### Writable shared model storage

```text
weights mounted rw
```

unless there is a strong, documented reason.

### Hidden runtime downloads

```text
missing local model
→ framework downloads automatically
```

Production should fail closed instead.

### Per-Task weight copies

```text
shared 20 GB model
→ copied into every Task workspace
```

This wastes storage and complicates provenance.

### Overlapping binds

```text
/mnt/db/weights/esm
/mnt/db/weights/esm/checkpoints
```

mounted independently without an explicit requirement.

### Baked-in production weights

```text
runner.sif contains model.pt
+
production host also binds model.pt
```

This creates ambiguous resource identity.

### Empty cache replacing model lookup

```text
TORCH_HOME=/tmp/new-empty-cache
```

when the upstream model loader expects its checkpoint beneath `TORCH_HOME`.

### Core-specific model handling

```python
if task_type == ...
```

for concrete scientific resource paths.

---

## 18. Long-term invariant

REvoCompute should preserve the following architectural invariant:

> **A Runner must never rely on writable, duplicated, overlapping, or implicitly downloadable model-weight paths. Each Runner Family owns an explicit read-only weight namespace exposed at a stable container path, while all writable cache, scratch, and intermediate state is isolated from that namespace.**

A second operational invariant follows:

> **A Runner is not validated merely because its SIF builds or its weight files exist. Readiness requires the real upstream model loader to resolve the provisioned resource through the production Slurm + Apptainer execution path and successfully produce the declared scientific artifacts.**
