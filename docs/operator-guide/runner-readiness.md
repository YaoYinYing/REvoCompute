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
| `VALIDATION_STALE` | The SIF is build-current, but its receipt no longer matches the execution contract, test plan, policy, account, or coverage | Keep the SIF and re-run live-test |
| `READY` | All current checks and required smoke cases pass | Eligible for new submissions, subject to authorization |

Build freshness is checked first, so a definition or declared build-input
change reports `BUILD_STALE` even when the execution contract also changed.
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
