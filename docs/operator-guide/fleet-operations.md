# Fleet Operations

Treat the enabled fleet as one inventory with independently validated family
artifacts. Start each shift by inspecting all families and recording any
non-READY state:

```bash
REVODESIGN_SERVER_ENV=.env.production bash run/restart.sh runner-status --all
```

For a family that is `NOT_BUILT` or `BUILD_STALE`, prepare a candidate. For
`NOT_VALIDATED` or `VALIDATION_STALE`, run its required collection on the target
cluster. Compare the receipt's hashes and policy digest before promotion.

Do not enable a task merely because its family is configured: `enabled !=
READY`. Restricted families also require an access-policy entitlement. Review
disk space, SIF ownership, Slurm partitions, database mounts, and receipt age
before a prepared restart. Keep maintenance mode active when any enabled
family cannot satisfy the production contract, and report the exact state and
failed evidence.

## The Admin control plane

The same control core has two surfaces. The CLI (`run/restart.sh`) remains
first-class and is the break-glass path: it works during a server, web, or
executor failure, and it holds capabilities the Web deliberately does not
(service restart, `setup`, secrets, and destructive recovery). The Admin Web
surface is a narrower, typed view for routine operations and is never a
prerequisite for recovery.

Both surfaces read the *same* derived readiness. `GET
/compute/api/auth/admin/runners` and `restart.sh runner-status --json` resolve
the same evaluator, so a family cannot be READY on one and unavailable to a
submission on the other.

### What the Admin surface does

- Reports readiness, transient **capacity**, and **access** as three separate
  facts. A READY family with no free compute shows both; neither rewrites the
  other, and neither rewrites readiness.
- Plans a typed action, then executes it. A privileged action is never run from
  a bare request: the server first returns a content-addressed plan naming the
  target, the current state, the ordered effective actions, the operations it
  will *not* perform, the lease it will hold, and the evidence snapshot it was
  computed against. Execution carries the plan digest, and the server re-checks
  it against current evidence; if anything moved, the request is rejected
  (`409 stale_plan`, "State changed; review the new plan") rather than silently
  running something different.
- Records an Operator Job for each mutation. A job is its own durable record
  (`QUEUED` → `RUNNING` → `SUCCEEDED`/`FAILED`/`CANCELLING`/`CANCELLED`), not a
  scientific Task, and it holds one exclusive lease per Runner family so two
  mutations cannot race. A read action runs inline and is not recorded as a job.
- Keeps requested intent beside effective actions. History answers "what did the
  operator ask for, what actually ran, and why is this not READY now" without
  re-deriving it.

### Degraded mode

When the host executor is unreachable, readiness, capacity, access, and history
stay available and mutation actions fail closed. No existing READY evidence is
fabricated, cleared, or rewritten because the executor is offline. The UI
reports `Operator executor unavailable` and disables mutations; it does not
retry in a loop.

### Planned but not yet implemented

A representative end-to-end failure drill — a stale-validation repair that
starts an Operator Job, fails, produces no false READY state, records the
failure and partial progress, keeps the active artifact identity explainable,
then succeeds on a fresh plan — is planned and not yet implemented. It may use
bounded fakes where the control contract is the subject under test, and it must
not require a real GPU or a large scientific runtime merely to prove
control-plane failure semantics.

### Permission boundary

The CLI may remain more powerful than the Web surface, because it runs in an
explicit operator/SSH context. Neither may ever expose an arbitrary shell.

| Capability | CLI | Admin Web |
| --- | --- | --- |
| Status / readiness / evidence | yes | yes |
| Doctor diagnostics | yes | yes |
| Live / smoke validation | yes | yes, typed job |
| Prepare / build a candidate | yes | yes, typed job |
| Activate (promote) | yes | no — refused |
| Rollback to the previous validated artifact | yes | no — refused |
| Readiness repair plan | yes | yes |
| Bounded logs / operator history | yes | yes |
| Service-wide restart | yes | no |
| Bootstrap / setup / secrets | yes, operator-only | no |
| Destructive reset / recovery | yes, break-glass | no |
| Arbitrary shell | never | never |

### Actions that intentionally stay CLI-only

Activation and rollback are **refused** on the Web surface, not approximated.
Their correctness is bound to host artifact identities (candidate hash, the
receipt that validated it, the artifact it replaces) rather than to derived
readiness, so the Web planner declines to stand in for them and the UI offers
them as unavailable. Operators run them through the CLI, where the deployment
controller already preserves the replaced artifact and re-verifies every
identity before the swap. `setup`, service restarts, secrets, and
destructive recovery are likewise CLI-only.

## Operational notes

- Restrict Docker socket access to trusted operators only.
- Task visibility and operations are always restricted to the owner or an
  administrator.
- Regularly back up sqlite and finalized result trees. Optional ZIP files are derived caches.
- If a task is deleted, result artifacts are removed, but the sqlite record remains for audit.
- Liveness probing: `GET /compute/health` returns an empty 200,
  unauthenticated.
