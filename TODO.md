# TODO — Post-#59 Resource Governance Hotfix

## Context

PR #59 (feat(resource): unify accounting, quotas, and data lifecycle) was squash-merged as
5e3e94889bc82cb3eeca6e696f419f82a95d7041.

Its merge-grade Codex review completed after the merge and surfaced six regressions. A fresh
post-merge review against main@5e3e948 independently reproduced all six. This PR is a
bounded correctness hotfix, not a resource-model redesign.

The governing ownership model from #59 remains unchanged:

> accounting records facts; admission applies policy; telemetry describes utilization;
> data lifecycle owns retention.

Do not create a second ledger, quota model, scheduler, cleanup state machine, or deployment
configuration vocabulary.

## 1. Fix unsettled compute reserve arithmetic

Current defect: TaskDatabase._unsettled_in_connection() applies
DEFAULT_ADMISSION_QUANTUM[unit] to the resource count before multiplying by elapsed time.
For one GPU at 10 seconds this can reserve 3600 × 10 = 36000 GPU-s rather than the intended
bounded base-unit quantity.

Required behavior for known-shape allocations:
observed_quantity = resource_count × elapsed_seconds;
reserved_quantity = max(admission_quantum, observed_quantity).

For genuinely unknown shape, preserve the existing conservative non-zero/unknown behavior.

Acceptance:
- 1 GPU × 10 s and 2 GPUs × 10 s;
- elapsed below and above admission quantum;
- unknown resource_count;
- multiple unsettled allocations;
- exclude_slurm_job_id;
- no regression to settled usage or concurrent-admission race tests;
- assert exact base-unit quantities, not only booleans.

## 2. Preserve numeric multi-GPU counts in wrapper receipts

Current defect: a normal numeric SLURM_GPUS_ON_NODE=2 reaches comma-list counting and becomes 1.
The receipt can therefore persist a one-GPU allocation while the canonical start callback uses
the requested count of two, causing allocation identity mismatch.

Required behavior:
- numeric count -> preserve the numeric count;
- scheduler/device ID list -> count list members;
- NoDevFiles / empty -> zero;
- malformed value -> bounded safe fallback;
- never infer more GPUs than scheduler evidence supports.

Acceptance:
- SLURM_GPUS_ON_NODE=2 -> 2;
- SLURM_GPUS_ON_NODE=1 -> 1;
- ID-list fallback such as 0,1 -> 2;
- SLURM_JOB_GPUS fallback;
- CUDA_VISIBLE_DEVICES fallback;
- malformed/no-device values;
- end-to-end receipt -> observation -> allocation identity for a 2-GPU task.

## 3. Route age-based retention through the canonical data lifecycle

Current defect: maintenance/tasks/result_cleanup.py::cleanup_expired_task_artifacts() directly
claims the legacy task-cleanup status, removes result/workspace bytes, and completes task cleanup.
It does not run the #59 lifecycle deletion transaction. A charged ACTIVE lifecycle row can
therefore survive after its bytes are gone and keep storage quota permanently consumed.

Required behavior:
- retention policy may decide which eligible terminal task enters deletion;
- durable lifecycle request precedes destructive filesystem work;
- one purge owner claims the work;
- successful purge releases exactly the charged logical bytes once;
- partial/error cleanup keeps the charge and remains retryable;
- restart/repeated maintenance is idempotent;
- do not maintain two independent cleanup state machines for the same durable result.

Preserve existing terminal Task history/audit semantics expected by UI/API. If legacy task-status
cleanup markers remain useful for presentation, coordinate them with the canonical data lifecycle
instead of bypassing it.

Acceptance:
- charged ACTIVE result expires -> bytes removed and storage released exactly once;
- purge failure -> bytes/charge remain coherent and retryable;
- crash/retry around delete completion;
- already PURGED / already requested cases;
- repeated retention pass;
- no phantom free quota and no permanent phantom charge;
- result/workspace/archive cleanup remains path-safe.

## 4. Make published-but-uncharged storage recoverable

Current defect: after the manifest is installed, _charge_logical_storage() calls
ensure_data_lifecycle(). Any exception is logged and swallowed. This can leave a successfully
published result with no lifecycle row, no logical-storage charge, and no durable retry marker.
Current reconciliation scans existing lifecycle rows, so it cannot discover this missing row later.

Required invariant: a published user-owned result must never become permanently invisible to
storage accounting.

The scientific result should not be destroyed merely because accounting persistence is temporarily
unavailable, but the system must retain a durable, discoverable repair path.

Choose the smallest architecture-preserving implementation. Acceptable shapes include:
- a durable pending/unaccounted publication marker in server-owned state; or
- reconciliation that safely enumerates authoritative anchored publications lacking a lifecycle
  row and reconstructs the charge from trusted published metadata.

Do not reconstruct ownership from an untrusted directory-size walk. The repair path must use the
verified publication identity established by #58/#65.

Acceptance:
- manifest publication succeeds, first lifecycle write fails;
- process/restart after that split;
- reconciliation later creates exactly one lifecycle/charge;
- repeated reconciliation is idempotent;
- deletion before repair cannot manufacture a zero-byte charge;
- quarantined/unanchored/mismatched publications are never auto-charged as trusted results.

## 5. Run scheduler-evidence reconciliation where Slurm evidence exists

Current defect: resource_maintenance calls reconcile_slurm_allocations.run() locally inside the
maintenance process. In the shipped Slurm Compose topology, only the worker receives scontrol,
Slurm config, libraries, and MUNGE mounts. The maintenance container does not own that boundary.

Required behavior: keep scheduler evidence worker-owned. Prefer dispatching the scheduler-evidence
subtask to the worker rather than widening maintenance privileges, unless there is a compelling
architecture reason otherwise. Do not block maintenance indefinitely on worker/scheduler outage.

Acceptance:
- periodic maintenance invokes scheduler reconciliation in the service with the Slurm boundary;
- scheduler unavailable -> bounded unknown/review, never fabricated zero;
- queued-reservation release still requires scheduler evidence;
- retries never double-settle.

## 6. Forward resource-governance settings through Compose

Current defect: operator docs expose settings that Compose does not forward:
- RESOURCE_MAINTENANCE_SECONDS;
- TASK_SCRATCH_LIMIT_BYTES;
- TASK_SCRATCH_GUARD_SECONDS.

Required behavior:
- resource maintenance interval -> maintenance service;
- scratch limit / guard interval -> task-executing worker path;
- preserve explicit defaults and validation;
- verify docker-compose.slurm.yml layering does not shadow or lose values.

Acceptance: add/extend Compose contract tests proving deployment env values reach the intended
containers and defaults remain unchanged.

## Cross-cutting review gates

This is R3 work because it touches accounting, persistence, lifecycle, scheduler evidence, and
crash recovery.

Before READY_FOR_FINAL_REVIEW:
1. Rebase/reconcile onto current main; do not trust this TODO's starting SHA.
2. Read the post-merge findings in PR #59, including the six Codex threads and the
   maintainer-level verification comment.
3. Fix the six defects only. Avoid opportunistic resource-model refactors.
4. Add failure-injection/counterexample tests at every changed durable transition.
5. Run relevant resource/admission/lifecycle/maintenance/Slurm/Compose suites.
6. Run required exact-head CI and git diff --check.
7. Perform a fresh-context R3 review against the exact final head.
8. Explicitly challenge unknown-vs-zero, count-vs-base-unit quantity, deletion-vs-accounting
   ownership, publication-vs-storage-accounting split, scheduler evidence location, and
   restart/retry/idempotency.
9. Retire this TODO.md before final merge according to the campaign protocol.

## Out of scope

- scheduler fairness, backfill, priority policy;
- placement planning (#60);
- MCP feature work (#57);
- billing/payment;
- project/lab quota hierarchy;
- new Admin reporting UI;
- redesigning #59's canonical ledger or lifecycle vocabulary;
- unrelated cleanup/refactors.

## Merge ordering

This hotfix is a main-stability prerequisite for final merge of #57 and for implementation
continuation/finalization of #60. Those PRs may prepare isolated work, but their final exact-head
review must occur after this hotfix lands.
