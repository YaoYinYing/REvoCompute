# Test Plan

Each family owns `test.yaml`, its executable acceptance declaration. The plan
names the cases that a target-host `live-test` runs through the production Task
definition, worker, Slurm, Apptainer, parser, and artifact contract. It does not
declare output contracts, resource policy, weights, or defaults; the worker
resolves those from the owning manifests and deployment configuration.

## Declaration

`test.yaml` accepts only `version: 1` and a non-empty `collections` mapping.
Every collection contains only `cases`; every case declares exactly `id`, `task`,
`input.roles`, and optional `parameters`:

```yaml
version: 1
collections:
  smoke:
    cases:
    - id: minimal-sequence-statistics        # unique identifier across the family
      task: sequence_statistics
      input:
        roles: {sequence: [tests/data/example/sequences.fasta]}
      parameters: {mass_precision: 2}
```

- `input.roles` is required. Each key is a role declared by the owning
  `task.yaml`, and each value is a non-empty list of repository fixtures. The
  run refuses an undeclared role, an incompatible format, or a cardinality
  violation.
- Fixtures MUST be immutable regular files under `tests/data/`; paths outside it
  are refused.
- `parameters` is validated against the Task's canonical Draft 2020-12
  parameter schema. It carries no defaults the schema already owns.
- Case IDs and collection names are stable identifiers. Duplicate case IDs are
  refused.

## Collections

`smoke` is mandatory and is the release collection. It must cover every
TaskType the family accepts, and its required cases are what readiness and
promotion evaluate. A narrowed `--task` pass validates only what it selected; a
receipt that does not cover every required smoke case cannot activate.

A family may add a `scientific` collection for pinned numerical reference cases.
That collection documents scientific acceptance and is run explicitly; it is
not a substitute for `smoke` and does not by itself satisfy the release gate.

## Scientific mode coverage

`smoke` must represent every registered TaskType and the release-critical
scientific paths actually advertised by that Task. A passing default case
does not establish that a non-default input format or execution mode works.
For material alternatives such as single-sequence inference, uploaded MSAs,
side-chain packing, or all-atom starting structures, add a small real case
with assertions about the *meaning* and integrity of its outputs. A cheap
release-critical case belongs in `smoke`; a costly numerical or scientific
reference case may belong in `scientific` and must be run explicitly before
its capability is called verified. `scientific` is not promotion evidence.

Where a new upstream version changes scientific semantics, re-evaluate old
goldens and output selectors against observed data rather than merely updating
the expected string or weakening a result contract. Tests of command dispatch
with a fake upstream program are useful, but they do not establish support for
a scientific mode. An unexercised mode remains **unverified**, not certified.

## Evidence

Changing the plan, a case, or a fixture digest changes the test-definition
digest and invalidates the prior receipt. The live-test loader validates plan
shape; do not duplicate these declarations in pytest. CI may exercise the
generic loader with synthetic plans, but only target-host execution produces a
promotable receipt. The evidence levels and the release gate are owned by
[Runner Family Protocol](runner-family-protocol.md); the live-test command is
owned by [Live Testing and Receipts](../operator-guide/live-testing.md).
