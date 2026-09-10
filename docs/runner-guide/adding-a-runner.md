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
