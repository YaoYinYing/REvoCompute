# Plugin Manifest

Every Runner family is self-contained under `docker/runners/<family>/`.
`plugin.yaml` is the server-discovered declaration of its stable identity and
contracts; it is not a deployment override.

At minimum declare the family name/version, runtime definition and build
inputs, task manifests, access-policy references, and any result/workspace
extensions. `definition` and `tasks` are relative to the family directory;
`runtime.build_inputs` and `runtime.runtime_overlay` are relative to the runner
tree root (`docker/runners/`). Pin upstream revisions. The manifest must be
deterministic: no host secrets, mutable download URLs, or machine-specific
absolute paths. `runner.yaml` supplies machine-local mounts, environment,
limits, and defaults separately.

`runtime.build_inputs` names what the SIF installs; `runtime.runtime_overlay`
names REvoCompute-owned executable code delivered as an immutable Runtime
Bundle instead. A path must not appear in both — one file cannot have two
identities — and Doctor rejects the overlap. See
[Runtime Bundles](runtime-bundles.md).

Doctor validates the manifest before a family can be built. Freshness follows
the semantic field that changed, not the fact that `plugin.yaml` changed:

- definition or `runtime.build_inputs` content changes alter Build Identity;
- `runtime.runtime_overlay` content changes alter Runtime Bundle Identity,
  which keeps the SIF and invalidates the validation receipt;
- execution-affecting runtime/task references alter Execution Contract Identity;
- release/presentation metadata such as `family.version` alone alters neither.

See the canonical
[Runner change-impact model](adding-a-runner.md#runner-change-impact-model).
