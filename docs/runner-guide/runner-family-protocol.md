# Runner Family Protocol

Each family under `docker/runners/<family>/` owns its manifests, task contracts,
direct Apptainer definition, runtime script, `test.yaml`, and result handling.
The direct-SIF lifecycle is Doctor, build, live acceptance, receipt, and
promotion; scientific behavior remains family-owned and generic server code
must not branch on Runner names.
