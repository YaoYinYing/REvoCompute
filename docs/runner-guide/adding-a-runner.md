# Adding a Runner

Start with an intake record: upstream URL and pinned commit, license/access
terms, model/database assets, expected inputs and outputs, CPU/GPU and memory
needs, dependency versions, and resource limits. Decide whether an existing
family can safely host the stack; create a new family when ABI, accelerator,
license, or dependency isolation requires it.

Create the complete family tree under `docker/runners/<family>/`: plugin and
task manifests, `runner.yaml`, direct Apptainer definition, `run.sh`, family
`test.yaml`, fixtures, and focused contract tests. Keep the server generic and
put scientific behavior in the family. Run Doctor, build a candidate SIF
directly with Apptainer, execute the real smoke collection, inspect the receipt,
then promote only through prepared restart. Record effective walltime, CPU,
host/GPU memory, and GPU utilization for future limits.

Each task manifest must fully describe every user-facing parameter with Draft
2020-12 JSON Schema type, default or required semantics, constraints, and
scientific description. Confirm the anonymous
`GET /compute/api/task-parameters/<task-type>` response matches the manifest;
adapters must read resolved values without supplying fallback defaults. After
activation, confirm that `/compute/api/types` discovers the enabled TaskTypes.
The stable `/skills.md` guide requires no per-Task update.

Declare every input as a named role in the owning `task.yaml`:

```yaml
inputs:
  structure:
    title: Protein structure
    type: protein_structure
    formats: [pdb, cif, mmcif]
    cardinality: {min: 1, max: 1}
```

Role IDs are the stable Runner contract; labels are presentation only. Add a
common format parser under `revocompute/input_validators/` only for reusable
syntax/container validation, and add a logical profile only for broadly shared
role semantics. Scientific repair, protonation, topology generation, or other
lossy preparation stays in the Runner and writes outside immutable inputs.

Write pytest coverage only for executable helper behavior. Put it in
`tests/runners/<family>/`; rely on the family smoke plan and target-host live
acceptance for the scientific runtime itself.
