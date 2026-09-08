# Runner Readiness States and Invalidation

Readiness is derived from current evidence, never from a mutable flag. The
shared status contract compares strict Doctor results, active SIF provenance,
the runtime/task/test identity, public resource policy, and required live-test
coverage. `runner-status` is diagnostic, while production admission uses this
same contract and fails closed for a non-READY family.

| State | Interpretation | Corrective action |
|---|---|---|
| `NOT_CONFIGURED` | Doctor contract is invalid | Correct family or machine configuration |
| `NOT_BUILT` | No active SIF exists | Build and stage a candidate |
| `BUILD_STALE` | Active SIF provenance no longer matches | Rebuild and validate |
| `NOT_VALIDATED` | No receipt exists for the active SIF | Run target-host live-test |
| `VALIDATION_STALE` | Receipt no longer matches current identity, policy, or coverage | Re-run live-test; rebuild if provenance changed |
| `READY` | All current checks and required smoke cases pass | Eligible for new submissions, subject to authorization |

Changing a task schema, runner manifest, image hash, mount, resource limit,
service identity, or required test invalidates the receipt. Queue congestion or
an idle/occupied GPU does not change readiness. Readiness changes do not cancel
already-running tasks; only new submissions are denied until evidence is
restored.
