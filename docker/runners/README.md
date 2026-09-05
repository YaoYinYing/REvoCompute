# Runner family protocol

Each directory with `plugin.yaml` is one self-contained Runner family. The
server discovers its task manifests, runtime, optional workspace plugins,
policies, and live-test declaration from that tree. Core code has no
task-name registry.

Required runtime shape:

```yaml
runtime:
  image_artifact: example_v1.sif
  definition: example.def
  build_inputs:
  - example/run.sh
  - common/task_context.sh
  - common/task_context.py
  entrypoint: [bash, /app/revocompute/run.sh]
```

`definition` is the authoritative direct Apptainer build recipe. It may use an
upstream OCI base with `Bootstrap: docker`, but it must not depend on a local
daemon image. Declare every local file consumed by `%files` in `build_inputs`;
their hashes, the definition hash, family version, and Apptainer version form
the build provenance. Put inexpensive binary/import checks in `%test`.

Every family also owns `test.yaml`. Its required `smoke` collection must cover
every enabled TaskType and may only reference immutable repository fixtures
under `tests/data/`:

```yaml
version: 1
collections:
  smoke:
    cases:
    - id: minimal-example
      task: example
      input: {files: [tests/data/example/input.fasta]}
      parameters: {iterations: 1}
```

Do not copy weights, databases, resource policy, output contracts, or defaults
into `test.yaml`; the worker resolves those through production configuration.

Target-host workflow:

```bash
bash run/restart.sh prepare --build-sif --enabled-runners=example
bash run/restart.sh live-test --runner example --collection smoke
bash run/restart.sh restart --mode=prepared
```

The first command atomically stages `<artifact>.next`. The second runs real
`apptainer inspect`, `apptainer test`, production Task submission, Slurm,
Apptainer execution, parsing, and artifact acceptance. It writes a PASS receipt
bound to the exact SIF, provenance, test declaration, and public configuration
hash. Prepared activation refuses a changed candidate without that receipt.

Docker Compose remains the server deployment framework; Runner families do not
have Dockerfiles or local Docker image identities.
