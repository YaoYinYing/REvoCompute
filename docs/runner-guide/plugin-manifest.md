# Plugin Manifest

Every Runner family is self-contained under `docker/runners/<family>/`.
`plugin.yaml` is the server-discovered declaration of its stable identity and
contracts; it is not a deployment override. This page owns the field guidance;
[Runner Family Protocol](runner-family-protocol.md) owns the lifecycle, release
gate, and identity consequences.

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
the semantic field that changed, not the fact that `plugin.yaml` changed. The
four identity classes are owned by
[Runner Family Protocol](runner-family-protocol.md#identity-classes), and the
detailed declaration and change list is in
[Runtime Bundles](runtime-bundles.md#change-impact).
