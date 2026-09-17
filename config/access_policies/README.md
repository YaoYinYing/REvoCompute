# Deployment-owned Runner access policies

This directory is the **deployment-owned overlay** for Runner access policies.
It is optional. The policy documents that a Runner family ships with live in
`docker/runners/common/policy/`, and the server registers them from that
family's `plugin.yaml`.

Files placed here are validated by deployment preflight together with the
Runner-shipped documents, and they participate in the deploy stamp's
deterministic configuration-contract digest. Because the server registers
policies only from the Runner family manifests, a policy that must be active at
runtime has to be referenced from `plugin.yaml` as well — a file that exists
only here is not enough. See
[`docs/reference/access-policies.md`](../../docs/reference/access-policies.md).

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

Register the stable policy ID from the runtime family's `plugin.yaml`: list the
document under `access_policies`, attach the ID to `runtime.access_policy`, and
declare it as an `access_policies` contribution. All three are required.

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
user-facing facts, not legal advice. Add loader and admission tests with the
Runner. The server operator remains responsible for verifying who satisfies
external terms.
