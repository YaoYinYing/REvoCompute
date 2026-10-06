# Runner Readiness States and Invalidation

Readiness is derived from current evidence, never from a mutable flag. The
shared status contract compares strict Doctor results, active SIF provenance,
the execution/test identity, effective resource policy, and required live-test
coverage. `runner-status` is diagnostic, while production admission uses this
same contract and fails closed for a non-READY family.

| State | Interpretation | Corrective action |
|---|---|---|
| `NOT_CONFIGURED` | Doctor contract is invalid | Correct family or machine configuration |
| `NOT_BUILT` | No active SIF exists | Build and stage a candidate |
| `BUILD_STALE` | Definition or a declared build input no longer matches the active SIF provenance | Rebuild, live-test the candidate, and promote it |
| `NOT_VALIDATED` | No receipt exists for the active SIF | Run target-host live-test |
| `VALIDATION_STALE` | The SIF is build-current, but its receipt no longer matches the runtime bundle, execution contract, test plan, policy, account, or coverage | Keep the SIF and re-run live-test |
| `READY` | All current checks and required smoke cases pass | Eligible for new submissions, subject to authorization |

Build freshness is checked first, so a definition or declared build-input
change reports `BUILD_STALE` even when the execution contract also changed.
A `runtime_overlay` change reports `VALIDATION_STALE` with
`reason=RUNTIME_BUNDLE_CHANGED`: the SIF is current, only the mounted runtime
code moved, and the action is to rerun the live test against the same SIF
(see [Runtime Bundles](../runner-guide/runtime-bundles.md)).
Execution-affecting Task/runtime fields, mounts, resource limits, service
identity, `test.yaml`, fixtures, or required coverage produce
`VALIDATION_STALE` without requiring a rebuild. Presentation-only fields such
as labels, summaries, help, citations, and UI hints leave a valid receipt
current. Changing `family.version` alone is release metadata and also leaves
both freshness identities current.

Queue congestion or an idle/occupied GPU does not change readiness. Readiness
changes do not cancel already-running tasks; only new submissions are denied
until evidence is restored. Runner authors should use the canonical
[change-impact matrix](../runner-guide/adding-a-runner.md#runner-change-impact-model)
before deciding which action to take.

## Readiness is not capacity, access, or infrastructure

Four states live side by side and none may rewrite another. The Admin fleet view
(`/compute/runner_fleet`) reports them as separate fields, and the CLI resolves
the same readiness evaluator, so the two surfaces agree.

- **Readiness** — the derived six-state verdict above: whether the deployed
  family has current, valid evidence for a *new* submission.
- **Capacity** — transient execution availability (scheduler/GPU occupancy). A
  READY family can be busy, and a busy scheduler does not make a family
  non-READY.
- **Access** — whether the calling user could submit to a restricted family.
  Granting or revoking an entitlement changes access, never readiness.
- **Infrastructure** — the platform's own readiness (Redis, workers, storage,
  scheduler reachability). Infrastructure degradation does not rewrite Runner
  readiness; both are shown so an operator can tell "the family is fine but the
  platform is degraded" from "the family's evidence is stale".

`READY` therefore means "eligible for a new submission", subject to all four.

## Correcting a non-READY state

The Admin fleet view offers only the actions a family's current state permits,
and each is shown as the plan the server would run — including what it will
*not* do. A `VALIDATION_STALE` family with `reason=RUNTIME_BUNDLE_CHANGED` is
offered a live validation that explicitly will not rebuild the SIF; a
`BUILD_STALE` family is offered prepare/build before validation. Activation and
rollback are not offered from the Web surface: they are bound to host artifact
identities and run through the CLI (see
[Fleet Operations](fleet-operations.md#actions-that-intentionally-stay-cli-only)).
