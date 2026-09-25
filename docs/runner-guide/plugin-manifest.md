# Plugin Manifest

Every Runner family is self-contained under `docker/runners/<family>/`.
`plugin.yaml` is the server-discovered declaration of its stable identity and
contracts; it is not a deployment override.

At minimum declare the family name/version, runtime definition and build
inputs, task manifests, access-policy references, and any result/workspace
extensions. `definition` and `tasks` are relative to the family directory;
`runtime.build_inputs` are relative to the runner tree root (`docker/runners/`),
matching the `%files` sources in the definition. Pin upstream revisions. The
manifest must be deterministic: no host secrets, mutable download URLs, or
machine-specific absolute paths. `runner.yaml` supplies machine-local mounts,
environment, limits, and defaults separately.

Doctor validates the manifest before a family can be built. Freshness follows
the semantic field that changed, not the fact that `plugin.yaml` changed:

- definition or `runtime.build_inputs` content changes alter Build Identity;
- execution-affecting runtime/task references alter Execution Contract Identity;
- release/presentation metadata such as `family.version` alone alters neither.

See the canonical
[Runner change-impact model](adding-a-runner.md#runner-change-impact-model).
