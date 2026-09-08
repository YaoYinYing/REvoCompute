# Runner access policies

Put one YAML file per restricted runtime/software family in this directory. Server startup and deployment preflight use
the same validator; unknown fields, malformed identifiers, unsupported match modes, and runtime references to missing
policies are fatal before prepared activation stops the existing service. Policy documents also participate in the deploy
stamp's deterministic portable-configuration digest.

```yaml
id: example_academic_runner
label: Example academic access
description: Access is limited to users explicitly authorized by the server operator.
requires:
  - example_academic
match: all
requestable: true
notice:
  title: Restricted access
  summary: This Runner requires operator approval.
license:
  name: Example Academic License
  url: https://example.invalid/license
```

Reference the stable policy ID once from its entry under `runtime_families` in `config/task_types.yaml`:

```yaml
runtime_families:
  example:
    access_policy: example_academic_runner
    # existing runtime fields...
```

Choose lowercase entitlement IDs that describe the durable authorization, not a user, task, or deployment. A policy may
require multiple IDs; the first implementation uses `match: all`. `requestable: false` means only an administrator may
directly grant it. Notice and license metadata are optional user-facing facts, not legal advice.

If software, model weights, databases, or other runtime material is not available to every REvoCompute user, declare a
policy here instead of hardcoding authorization in Python or JavaScript. Add loader and admission tests with the Runner.
The server operator remains responsible for verifying who satisfies external terms. Existing Runner names alone are not
evidence of a restriction, so no current production Runner is restricted by default.
