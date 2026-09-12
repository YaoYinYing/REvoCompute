# Runner access policies

This directory owns reusable server access policies. Runner manifests reference
the exact policy file under `common/policy/`; policy YAML must not be duplicated
inside a Runner family.

Missing or invalid referenced policy files fail plugin discovery and Doctor, so
a Runner with an announced restriction cannot be enabled without its policy.

## RosettaCommons audit

RosettaCommons is a mixed-license organization, not a license classification.
Apply `rosetta_software_noncommercial` only to a runtime that actually contains
or invokes classic Rosetta or PyRosetta. The current Runner inventory has no
such runtime.

- `placer-rfdiffusion` uses the original RFdiffusion repository, whose license
  expressly applies BSD-3-Clause terms to the source and referenced weights; it
  does not receive the classic Rosetta policy.
- `rfdiffusion2` uses BSD-3-Clause source without PyRosetta or the separately
  restricted Chai subtree. REvoCompute operates it only for entitled academic
  users through `rfdiffusion2_academic_only`.
- `foundry` uses BSD-3-Clause source without Rosetta/PyRosetta. REvoCompute
  operates its checkpoint-backed services only for entitled academic users
  through `foundry_academic_only`.
- `geodock` uses MIT source and externally provisioned model assets.
  REvoCompute operates it only for entitled academic users through
  `geodock_academic_only`.

Official references:

- https://github.com/RosettaCommons/rosetta/blob/main/LICENSE.md
- https://github.com/RosettaCommons/rosetta/blob/main/LICENSE.PyRosetta.md
- https://rosettacommons.org/software/licensing-faq/
- https://github.com/RosettaCommons/RFdiffusion/blob/main/LICENSE
- https://github.com/RosettaCommons/RFdiffusion2/blob/main/LICENSE.md
- https://github.com/RosettaCommons/foundry/blob/production/LICENSE.md
