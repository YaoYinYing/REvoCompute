# TODO.md — Restart Safety and Compact Dashboard Regression Fix

## Goal

This follow-up fixes two issues discovered during final review of the frontend hardening work:

1. **P1 operational correctness:** the restart pre-stop sweep can import newer Runner task metadata using older running server code, causing TaskType discovery to fail before in-flight tasks are preserved.
2. **P2 frontend regression:** Compact Dashboard mode hides the real Download action after the recent Results/Download visual hierarchy change.

Do not redesign the frontend or Runner parameter system.

The governing rule is:

> A running REvoCompute instance must operate on a self-consistent, immutable set of server code and Runner metadata for the lifetime of that instance.

---

# 1. P1 — Fix restart pre-stop code/manifest version skew

## Observed failure

During restart:

```text
Preserving workflows and finalizing other in-flight tasks before stopping the stack...
Pre-stop sweep failed to mark in-flight tasks; they may remain queued/running:

ValueError: Task type 'bioemu' contains an unsupported parameter UI control
````

The failure occurs while importing:

```text
revocompute.task_runtime
  -> discover_plugins(...)
  -> _load_task_params(...)
  -> _load_ui_control(...)
```

The currently deployed BioEmu task metadata uses the new structured UI contract:

```yaml
base_seed:
  type: integer
  x-ui-control:
    kind: seed
```

Current server code accepts this representation.

Older server code only accepted the previous scalar representation:

```yaml
x-ui-control: seed
```

The restart process therefore appears capable of combining:

```text
old running server code
+
newly updated Runner task.yaml files
```

This is an invalid deployment state.

---

# 2. Define the server-instance immutability contract

A running server instance must not discover Runner metadata directly from a mutable repository tree whose revision can change underneath it.

For the lifetime of one running server instance, these must belong to the same deployment revision:

```text
server Python package
Runner manifests
TaskType task.yaml files
Runner-owned presentation metadata
storyboards / runner frontend assets
other discovery-time Runner configuration
```

* [ ] Document this invariant in the relevant deployment/restart documentation.
* [ ] Identify every path used by `discover_plugins()` at runtime.
* [ ] Identify whether those paths currently resolve to:

  * image-baked files;
  * copied server-instance files;
  * bind-mounted SOURCE_ROOT files;
  * symlinked repository files.
* [ ] Remove any lifecycle path where a `git pull` can mutate TaskType definitions visible to an already-running server process.

Do not implement compatibility by downgrading the new seed metadata.

---

# 3. Establish an immutable Runner snapshot per server instance

Use the existing runner-deployment model rather than introducing release-ID complexity.

At server build/startup, enabled Runner metadata should be copied into or otherwise frozen inside the server instance.

A suitable structure is conceptually:

```text
server instance
├── revocompute/
└── runners/
    ├── bioemu/
    ├── alphafold3/
    ├── simplefold/
    └── ...
```

The exact path may follow current configuration.

Requirements:

* [ ] The running server discovers TaskTypes from its own immutable Runner snapshot.
* [ ] The snapshot contains only enabled/deployed Runners where appropriate.
* [ ] A later repository update does not mutate the running snapshot.
* [ ] A newly started instance receives the new snapshot.
* [ ] Restart/rebuild replaces the old instance with a new internally consistent snapshot.
* [ ] No release-ID/version-database system is required unless already present and necessary.

Prefer copying or immutable container contents over live mutable mounts for discovery metadata.

Large model weights/databases remain external read-only mounts and are not part of this snapshot.

---

# 4. Separate mutable runtime data from immutable deployment metadata

Do not confuse Runner metadata with runtime data.

These may remain external/mounted:

```text
task database
uploads
results
logs
model weights
shared databases
scheduler state
runtime temporary directories
```

These should be immutable for one application instance:

```text
Python application code
TaskType declarations
Runner manifests
Runner storyboard/frontend metadata
Runner-owned JS/CSS needed for discovery/rendering contracts
```

* [ ] Audit Compose/Apptainer/server mounts accordingly.
* [ ] Do not copy large model caches into the server image merely to obtain immutability.

---

# 5. Make the pre-stop sweep use the current instance snapshot

The restart script must preserve/finalize tasks using the **currently running instance's own code and Runner metadata**.

It must not:

```text
git pull
→ mutate SOURCE_ROOT
→ run old container Python
→ import new SOURCE_ROOT task.yaml
```

Required lifecycle should be equivalent to:

```text
1. Current instance is still intact.
2. Run pre-stop preservation using current instance code + current instance Runner snapshot.
3. Stop old stack.
4. Update/build/copy new deployment revision.
5. Start new instance using new code + new Runner snapshot.
6. Run normal startup reconciliation.
```

* [ ] Inspect the restart script ordering.
* [ ] Move repository update/build operations after pre-stop if currently necessary.
* [ ] Ensure pre-stop command executes inside the current instance or against its immutable deployment tree.
* [ ] Do not source Runner definitions from the newly updated repository during pre-stop.

---

# 6. Harden pre-stop failure behavior

The current warning says tasks “may remain queued/running”.

That is an important operational failure and should not be treated as an ordinary cosmetic warning.

* [ ] Make pre-stop preservation failure highly visible.
* [ ] Return a non-zero status from the preservation step.
* [ ] Decide explicitly whether restart should abort when preservation fails.
* [ ] Default toward aborting before stopping the old stack if task-state preservation cannot be completed safely.
* [ ] Do not silently continue into destructive shutdown when preservation guarantees have failed.

If an operator deliberately forces restart after failure, make that an explicit action.

---

# 7. Keep restart task preservation independent from optional Runner loading where possible

Evaluate whether the pre-stop sweep truly needs full TaskType/Runner discovery.

If its only purpose is to inspect and transition task records, importing `task_runtime` may be unnecessarily coupled to Runner plugin discovery.

Investigate a cleaner dependency boundary:

```text
restart preservation
    -> task store / DB
    -> scheduler adapter
    -> task-state transition logic

not necessarily
    -> full Runner registry initialization
```

* [ ] Determine which task-runtime functions the pre-stop script actually needs.
* [ ] If feasible, move task-state preservation behind a small module that does not import/discover every Runner.
* [ ] Reuse existing task-store/scheduler abstractions.
* [ ] Avoid duplicating state-transition business logic in shell/Python snippets.

This is a secondary hardening measure, not a substitute for deployment immutability.

---

# 8. Verify in-flight task semantics

Define exactly what restart should do with tasks in each state.

At minimum inspect:

```text
pending
running
finished
failed
cancelled
cleanup states
```

* [ ] Preserve finished/failed terminal records unchanged.
* [ ] Ensure pending/running tasks receive the intended restart-safe transition.
* [ ] Ensure scheduler jobs are not accidentally orphaned.
* [ ] Ensure startup reconciliation can correctly continue from the pre-stop result.
* [ ] Confirm REQUEUE/SLURM behavior remains unchanged unless the restart workflow already requires it.

Do not redesign scheduler semantics in this PR.

---

# 9. Add restart/version-skew regression coverage

Add a test reproducing the actual failure class.

## Required scenario

Construct:

```text
old application parser
+
newer Runner manifest syntax
```

or an equivalent fixture representing a repository update after current-instance startup.

Verify that the restart lifecycle does **not** feed the newer manifest into the old instance.

Tests should prove:

* [ ] current instance pre-stop uses its own Runner snapshot;
* [ ] SOURCE_ROOT may advance without affecting current-instance discovery;
* [ ] in-flight preservation still executes;
* [ ] new instance loads the new Runner metadata successfully;
* [ ] old and new snapshots cannot be accidentally mixed.

Also retain direct TaskType contract tests for:

```yaml
x-ui-control:
  kind: seed
```

and:

```yaml
x-ui-control:
  kind: seed
  random:
    minimum: 1
```

---

# 10. Add restart-script integration coverage

Where practical, add a test around the restart script or extracted lifecycle helpers.

Use mocked Docker/Compose/SLURM boundaries where necessary.

Verify ordering:

```text
preserve old instance
→ stop old instance
→ update/build new instance
→ start new instance
```

The test should fail if repository mutation happens before preservation when the old instance reads from that repository.

Do not require a real SLURM cluster or Apptainer installation.

---

# 11. P2 — Restore Download in Compact Dashboard mode

## Regression

The frontend hardening PR changed Results from the old `.download` class to `.results`.

Compact mode currently contains:

```css
.board[data-layout="compact"] .actions > :not(.details):not(.results) {
    display: none;
}
```

This preserves:

```text
Open details
Results
```

but hides the actual:

```text
Download
```

action.

That violates the intended Compact Dashboard contract.

---

# 12. Define Compact mode action contract

Compact task cards should expose the minimum useful action set without requiring the detail overlay.

For completed/result-bearing tasks preserve:

```text
Open details
Results
Download
```

For active tasks preserve whatever lifecycle action is already part of the established Compact contract, if applicable.

Do not expose every detailed-mode action merely because it exists.

* [ ] Restore the real Download action in Compact mode.
* [ ] Keep Results visually distinct from Download.
* [ ] Ensure transient Download states (`Preparing…`, `Started`) remain visible in Compact mode.
* [ ] Preserve stable card geometry during transient states.
* [ ] Keep destructive actions quiet/hidden according to the existing Compact product decision.
* [ ] Do not reintroduce the previous Results-as-Download class confusion.

Prefer semantic classes/data attributes over selectors that accidentally encode visual history.

For example, if useful:

```html
data-action="results"
data-action="download"
```

can be used as the product-level contract instead of relying only on CSS class names.

---

# 13. Add Compact mode regression tests

Add browser coverage for a finished task in Compact layout.

Verify:

* [ ] Open details is visible.
* [ ] Results is visible.
* [ ] Download is visible.
* [ ] Results invokes result workspace behavior.
* [ ] Download invokes archive/download behavior.
* [ ] Download enters `Preparing…` without disappearing.
* [ ] row/card geometry remains stable.
* [ ] Delete visibility matches the intended Compact contract.

This test must distinguish Results from Download explicitly.

---

# 14. Re-run frontend hardening review

After the two fixes above, re-review PR #13 for regressions introduced by the hardening pass.

Pay particular attention to:

```text
Dashboard detailed mode
Dashboard compact mode
Dashboard table mode
Runner Access
Landing hero
Swagger dark mode
theme switching
mobile layouts
```

Do not broaden into unrelated frontend redesign.

---

# 15. Architecture audit

Before completion, search the final tree for risky deployment coupling.

Audit:

```text
SOURCE_ROOT
runners_dir
discover_plugins
task_runtime
restart
pre-stop
docker compose
bind mounts
task.yaml
x-ui-control
```

Determine for every production reference whether it points to:

```text
immutable instance data
or
mutable repository state
```

No running instance should consume mutable deployment metadata unintentionally.

Also audit Dashboard Compact CSS/JS selectors for:

```text
.details
.results
.download
data-action="results"
data-action="download"
```

to ensure the product contract is explicit.

---

# 16. Verification gates

Before merging:

* [ ] restart/version-skew focused tests pass;
* [ ] TaskType discovery tests pass;
* [ ] seed UI metadata tests pass;
* [ ] restart-script mocked integration tests pass;
* [ ] Compact Dashboard regression test passes;
* [ ] existing frontend-hardening Playwright tests pass;
* [ ] `make test` passes;
* [ ] `make test-cov` passes;
* [ ] Docker Compose configuration renders;
* [ ] JavaScript syntax/static checks pass;
* [ ] `git diff --check` passes;
* [ ] current-head CI is green.

---

# Non-goals

Do not include:

* rollback of structured `x-ui-control`;
* compatibility hacks converting new seed metadata back to scalar strings;
* new Runner integrations;
* scheduler-priority redesign;
* SLURM QoS changes;
* model-weight relocation;
* release-ID/version-management framework;
* frontend redesign;
* API redesign unrelated to deployment consistency;
* broad task-state-machine changes.

---

# Definition of done

This work is complete when:

1. A running server instance cannot observe newer Runner metadata than its own application code.
2. Restart pre-stop preservation executes before the current instance is invalidated or replaced.
3. Repository updates cannot break pre-stop TaskType discovery.
4. Failure to preserve in-flight tasks prevents or clearly gates unsafe shutdown.
5. The new structured seed UI metadata remains canonical.
6. Compact Dashboard mode exposes both Results and Download correctly.
7. Transient Download states remain stable in all supported layouts.
8. Focused and full test suites pass.
9. PR #13 has no remaining P1/P2 correctness regression.
