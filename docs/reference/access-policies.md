# Runner access policies

An access policy is a portable YAML document that restricts a Runner family to
users holding named entitlements. Runner-shipped policies live with the family
under `docker/runners/common/policy/<id>.yaml`; deployment-owned policies live in
`config/access_policies/`. Server startup and deployment preflight use the same
validator; unknown fields, malformed identifiers, unsupported match modes, and
runtime references to missing policies are fatal before prepared activation stops
the existing service. Policy documents also participate in the deploy stamp's
deterministic configuration-contract digest.

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

Register the policy from the runtime family's `plugin.yaml`: list its document
under `access_policies`, attach its stable ID to `runtime.access_policy`, and
declare the ID as a contribution so Doctor and deployment preflight can resolve
it. All three are required — a `runtime.access_policy` reference with no matching
`access_policies` document prevents the server from starting.

```yaml
# docker/runners/<family>/plugin.yaml
id: example
runtime:
  image_artifact: example_v1.sif
  access_policy: example_academic_runner
access_policies:
  - common/policy/example_academic_runner.yaml
contributions:
  access_policies:
    - example_academic_runner
```

Choose lowercase entitlement IDs that describe the durable authorization, not a
user, task, or deployment. A policy may require multiple IDs; the first
implementation uses `match: all`. `requestable: false` means only an
administrator may directly grant it. Notice and license metadata are optional
user-facing facts, not legal advice.

If software, model weights, databases, or other runtime material is not available
to every REvoCompute user, declare the policy under
`docker/runners/<family>/` (`common/policy/` plus the `plugin.yaml` references
above) instead of hardcoding authorization in Python or JavaScript. Add loader
and admission tests with the Runner. The server operator remains responsible for
verifying who satisfies external terms. Existing Runner names alone are not
evidence of a restriction, so no current production Runner is restricted by
default.
