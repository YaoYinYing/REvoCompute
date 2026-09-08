# Plugin Manifest

Every Runner family is self-contained under `docker/runners/<family>/`.
`plugin.yaml` is the server-discovered declaration of its stable identity and
contracts; it is not a deployment override.

At minimum declare the family name/version, runtime definition and build
inputs, task manifests, access-policy references, and any result/workspace
extensions. Keep paths relative to the family tree and pin upstream revisions.
The manifest must be deterministic: no host secrets, mutable download URLs, or
machine-specific absolute paths. `runner.yaml` supplies machine-local mounts,
environment, limits, and defaults separately.

Doctor validates the manifest before a family can be built. Changes to the
manifest change the task/runtime identity and invalidate existing receipts.
