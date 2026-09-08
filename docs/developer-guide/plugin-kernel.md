# Plugin Kernel

Discovery scans family-owned `plugin.yaml` manifests, validates their declared
TaskTypes and extensions, and exposes a typed registry to the server. There is
no hand-maintained central task registry and no runner-name branching in Core.

The kernel owns loading, schema validation, version/provenance identity, and
extension boundaries. A plugin may provide task definitions, result parsers,
or workspace/result-view extensions, but it cannot bypass authorization,
resource policy, isolation, or artifact acceptance. Invalid manifests fail
Doctor and are excluded from production readiness.
