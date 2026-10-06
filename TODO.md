# Deterministic Runner Fleet Control Plane and Admin Operations

## Objective

Establish one canonical, typed, auditable Runner control plane with two first-class operator surfaces:

> **CLI for agents, automation, bootstrap, recovery, and expert operations; Web Admin UI for safe, accessible, routine human operations.**

The CLI remains a supported first-class interface and keeps its current command grammar wherever practical. The Web UI must not reimplement shell commands or readiness logic. Both surfaces must call the same control/readiness core.

This PR also eliminates the recurrent nondeterministic Runner/plugin discovery failure seen under pytest-xdist, including the recurring AlphaFold3 `Unknown task type: 'alphafold3'` failure. A readiness/control plane is not trustworthy until registry construction is deterministic.

The design principles are:

- **one control plane, two operator surfaces;**
- **readiness is derived from evidence, never set by an operator flag;**
- **readiness, transient capacity, and user access are separate states;**
- **typed operations, never arbitrary shell execution;**
- **routine Web administration should not require SSH;**
- **bootstrap, destructive recovery, secrets, and break-glass operations remain CLI-only;**
- **every privileged mutation is attributable, bounded, auditable, and fail-closed.**

This is not a generic observability platform, not a remote shell, and not a redesign of Slurm, Apptainer, the task scheduler, or Runner scientific contracts.

---

## 0. Campaign position and dependencies

This PR begins after the Soft Precision frontend work has merged.

At implementation start:

1. read `CLAUDE.md` and `docs/agents/long-task-handling.md`;
2. fetch/prune and inspect current `main`;
3. inspect the final merged state of PR #46 and PR #47 if they have landed;
4. reconcile only the surfaces actually affected by those PRs;
5. create/use one PR-scoped implementation worktree and keep the repository root as Commander control plane.

Preserve:

- #46 result-contract / authentic-artifact semantics;
- #47 persistent/OOM provenance semantics;
- the Soft Precision visual language already merged;
- existing CLI command names and operator workflows unless a change is required for correctness.

Do not mechanically rebase merely because `main` advances.

---

## 1. Fix registry ownership before building the control plane

The recurring AF3 xdist failure is evidence that current plugin/TaskType discovery has nondeterministic mutable-state ownership.

Investigate and fix the root cause rather than adding a local `discover_plugins()` call to one AF3 test.

Required invariant:

> A test, request, CLI command, or service must never depend on another process/test/request having populated a module-global registry first.

The solution should make registry construction explicit, deterministic, and context-scoped.

Acceptable implementation directions include a canonical registry snapshot/factory or an explicit discovery context. Choose the smallest design compatible with the existing architecture.

Do not create a second plugin system.

### Registry acceptance

Prove that:

- the same Runner tree/configuration produces the same registry snapshot;
- isolated discovery does not leak into another test/request;
- parallel tests cannot remove/replace another worker's Runner registration;
- repeated discovery is idempotent;
- an enabled-family set is honored deterministically;
- unknown family/task lookup fails deterministically;
- AF3 workflow-composer tests no longer depend on xdist scheduling order.

Add a focused repeated xdist/random-order regression. Prefer repeatedly exercising the relevant registry/workflow tests over repeatedly running the complete test suite.

A single green run is not sufficient evidence for this previously intermittent defect.

---

## 2. Extract one canonical Runner readiness/control core

The repository already has Runner readiness concepts and `runner-status`. Do not duplicate them for the Web UI.

Create/refactor a canonical service boundary that can be called by:

- `revocompute_ctl` CLI;
- production submission admission;
- Admin API;
- tests.

Conceptually:

```text
Runner manifests + deployment config + Doctor + artifact provenance
+ runtime bundle + execution contract + resource policy + test plan
+ target-host live-test receipts
                         |
                         v
            canonical Runner control/readiness core
              /              |               \
             /               |                \
            v                v                 v
        CLI JSON        admission gate      Admin API
```

The names/classes may differ; do not add abstraction solely to match this diagram.

### Readiness remains derived

Preserve the current state vocabulary unless current code proves a change is needed:

- `NOT_CONFIGURED`
- `NOT_BUILT`
- `BUILD_STALE`
- `NOT_VALIDATED`
- `VALIDATION_STALE`
- `READY`

There must be no API such as:

```text
set_ready(true)
```

Administrators maintain evidence and initiate corrective operations. The evaluator derives the resulting state.

### Cross-surface identity invariant

For the same evidence snapshot:

> CLI status == Admin API status == admission decision.

State, reason code, and relevant evidence identity must agree.

Do not let the Web layer derive readiness independently.

---

## 3. Keep readiness, capacity, and access physically separate

Do not collapse these into one "available" flag.

The control/API/UI model must distinguish:

### Operational readiness

Whether the deployed Runner family has current, valid evidence required for new submissions.

### Capacity

Transient execution availability such as scheduler/GPU occupancy.

Capacity changes must not mutate readiness.

### Access

Whether a user is entitled to submit to a restricted Runner.

Access changes must not mutate readiness.

The Admin UI should be able to show states such as:

```text
Readiness   READY
Capacity    No GPU currently free
Access      Restricted
```

or:

```text
Readiness   VALIDATION_STALE
Capacity    4 GPUs idle
Access      Allowed
```

without implying contradiction.

Existing `InfrastructureReadiness` is also distinct from per-Runner readiness. Reuse it where useful but do not merge the concepts.

---

## 4. Introduce typed operator actions, never an arbitrary command API

Web administration may operate the existing control-module capabilities, but it must do so through typed actions.

A valid control API looks conceptually like:

```text
runner.status
runner.doctor
runner.prepare
runner.build
runner.live_test
runner.promote
runner.repair
```

The exact action set should be derived from existing safe control-module capabilities.

An invalid design is:

```text
operator.exec(command: str)
POST /admin/run-command
{"command": "..."}
```

Do not expose shell text, arbitrary argv, arbitrary environment variables, arbitrary paths, or arbitrary executables to the browser.

### Web operation scope for this PR

The Web Admin surface should support the routine Runner lifecycle when the existing control module already provides a safe underlying operation:

- inspect current status/evidence;
- run/refresh Doctor;
- prepare/build a Runner candidate;
- run bounded smoke/live validation;
- promote a validated candidate;
- request the shortest valid "repair readiness" plan and execute it;
- inspect bounded logs/receipts/history;
- cancel a cancellable in-flight operator job.

Only expose service reload/restart if it can be represented as a narrow existing typed operation with a safe host boundary.

Keep the following CLI-only unless there is an already-existing narrow, well-tested primitive that clearly makes Web exposure safe:

- initial machine/bootstrap setup;
- secret management;
- password reset/bootstrap credentials;
- database reset/destructive recovery;
- arbitrary filesystem migration;
- arbitrary service/process control;
- arbitrary command execution.

The CLI remains the break-glass/recovery surface and must not be removed.

---

## 5. Host Operator Executor boundary

Many control operations are host-level while the Web server may run inside a container.

Do not solve this by giving the Web application:

- a Docker socket;
- arbitrary host filesystem access;
- passwordless unrestricted sudo;
- a generic host shell;
- unrestricted Slurm/Apptainer command construction from request data.

If Web-triggered operations require a host-side component, add the smallest dedicated **Operator Executor** boundary.

It must:

- accept only typed allowlisted operations;
- accept canonical Runner IDs resolved from the registry;
- validate every parameter against a strict schema;
- use fixed executable/action mappings;
- construct argv without `shell=True` or string interpolation;
- use an allowlisted environment;
- use bounded, owned working directories;
- authenticate/authorize local requests;
- fail closed when identity, plan, lease, or evidence is stale;
- return structured progress/result records;
- emit bounded/redacted logs;
- never accept arbitrary command text.

Prefer local-only IPC or an equivalently narrow deployment boundary; do not create a generally reachable remote administration daemon.

Reuse existing deployment lease semantics instead of inventing a competing concurrency model.

---

## 6. Plan before execute

Dangerous or long-running Web actions must have an explicit plan.

Example:

```text
Runner: SimpleFold
Current state: VALIDATION_STALE
Reason: RUNTIME_BUNDLE_CHANGED

Plan:
- reuse active SIF
- reuse model assets
- run smoke validation
- write a new receipt
- recompute readiness

Will not:
- rebuild SIF
- restart server
- cancel running scientific tasks
```

The control core should expose a typed plan with:

- target;
- requested operation/intent;
- current state;
- reason;
- ordered effective actions;
- expected state-changing effects;
- operations explicitly not required;
- lease scope;
- whether explicit confirmation is required;
- immutable plan/evidence digest.

At execution time, revalidate the plan against current evidence.

If the relevant evidence changed after the plan was produced, reject the stale plan and require replanning.

Do not silently execute a different high-impact plan.

---

## 7. Operator Jobs for long-running work

Do not keep an HTTP request open for a SIF build or live test.

Represent Web-triggered mutations as bounded Operator Jobs with an explicit lifecycle, for example:

```text
QUEUED
RUNNING
SUCCEEDED
FAILED
CANCELLING
CANCELLED
```

Use the repository's conventions where possible.

An Operator Job is not a scientific Task and must not be stored as one merely for convenience.

Persist enough information to recover/audit:

- job id;
- action;
- target Runner;
- actor/user id;
- request timestamp;
- plan/evidence digest;
- effective operation;
- lease scope;
- current stage;
- start/end timestamps;
- structured result;
- resulting evidence/receipt identity;
- failure category;
- bounded log reference.

Server restart must not make a completed operator action disappear from history.

Do not build a general workflow engine.

---

## 8. Concurrency, leases, cancellation, and idempotency

Use explicit operation scopes.

Examples:

```text
runner/simplefold     exclusive for build/validate/promote
deployment            exclusive for deployment-wide mutation
read-only status       concurrent
```

Prove:

- conflicting mutations cannot run concurrently;
- read-only status/Doctor inspection is not unnecessarily blocked;
- retries with the same idempotency key do not duplicate a mutation;
- a repeated request with the same key but different body is rejected;
- cancellation kills only the owned bounded process/job scope;
- cancellation cannot accidentally cancel scientific Tasks;
- a stale lease cannot authorize a later unrelated operation.

---

## 9. Admin Fleet Readiness UI

Use the merged Soft Precision design language. Do not create a separate "ops dashboard" visual system.

The Admin configuration/control surface should provide a fleet-level view with, at minimum:

- Runner family;
- enabled/deployed state;
- readiness;
- machine-readable reason rendered as understandable human copy;
- transient capacity as a separate field;
- access restriction as a separate field;
- active artifact/runtime identity;
- last validation time/evidence;
- evidence freshness;
- recommended corrective action;
- in-flight operator action, if any.

Support useful filtering/sorting such as readiness state, stale/failed, enabled, and family name.

Avoid decorative charts unless the repository has real aggregate data that genuinely benefits from one.

### Runner detail

A Runner detail/operator drawer/page should expose evidence lanes such as:

```text
Doctor
Build / active SIF identity
Runtime bundle
Execution contract
Resource policy
test.yaml / required smoke coverage
Live-test receipt
Target host / scheduler identity
Current invalidation reason
```

Where reliable evidence already exists, also show clearly separate non-operational evidence such as result-contract coverage or scientific/reference evidence.

Do not manufacture new "PASS" badges when no authoritative source exists.

### Corrective actions

Actions shown in the UI must be state-aware.

Examples:

```text
VALIDATION_STALE + RUNTIME_BUNDLE_CHANGED
→ Validate now
→ no rebuild required

BUILD_STALE
→ Prepare/rebuild candidate
→ validate
→ promote
```

Provide an intent-level "Repair readiness" flow only when the canonical control core can produce a safe plan.

Admin should understand the planned impact before confirmation.

---

## 10. Readiness and operator history

Add/reuse a bounded append-only operational history sufficient to answer:

> Why was this Runner READY yesterday and not READY now, and what operation restored it?

Prefer existing operational-event/audit infrastructure.

Record meaningful transitions and operations, not every polling refresh.

A useful timeline can contain:

```text
READY
→ runtime bundle changed
→ VALIDATION_STALE
→ admin requested repair
→ live-test started
→ receipt written
→ READY
```

Each mutation entry must include actor, action, target, timestamps, before/after evidence/state, outcome, and relevant receipt/job identity.

Do not create a second general event platform.

---

## 11. Security model and multi-level test coverage

Security acceptance is a first-class merge gate.

Implement layered tests. Do not rely on one browser test or one route-level authorization assertion.

### Level 0 — pure schema/state-machine tests

Test the lowest-level typed control model without HTTP/process execution.

Required cases:

- action names are a closed enum/registry;
- unknown actions fail closed;
- Runner IDs must resolve canonically from the discovered registry;
- illegal state transitions are rejected;
- plans are deterministic for identical evidence;
- stale plan/evidence digests are rejected;
- operation parameters have explicit type/range/length bounds;
- no action model contains generic command/argv/env/path injection fields;
- logs/events apply control-character normalization and secret redaction;
- operator job state transitions reject impossible regressions.

### Level 1 — API authentication/authorization tests

For every privileged mutation endpoint prove:

- anonymous request -> rejected;
- authenticated non-admin -> rejected;
- admin without the required strong mutation-auth boundary -> rejected;
- authorized admin -> only allowed typed operation;
- wrong HTTP method -> rejected;
- malformed body -> rejected;
- extra/unknown fields -> rejected where practical;
- oversized body/parameter -> rejected or bounded;
- invalid/stale idempotency key semantics -> rejected;
- sensitive evidence is omitted from non-admin projections.

Preserve the repository's existing bearer-auth requirement for privileged admin mutations. Do not weaken an existing state-changing route to session-only authorization merely for UI convenience.

### Level 2 — injection and input-boundary tests

Use adversarial parameter cases, including at least:

```text
;
&&
|
$(...)
`...`
newline / CRLF
../
absolute paths
slashes in Runner IDs
leading dash
Unicode confusables where relevant
NUL/control characters
very long identifiers
URL-encoded traversal forms
```

Prove these values cannot:

- select another Runner;
- inject an argv element;
- add an environment variable;
- alter a path outside the owned root;
- forge a log line/event;
- reach a shell.

Do not add a generic shell parser to "sanitize" arbitrary commands; arbitrary commands must not exist in the API.

### Level 3 — executor/process/IPC boundary tests

If a host Operator Executor is introduced, test:

- only allowlisted operations are accepted;
- forged/unauthenticated local requests fail;
- stale plan digests fail;
- Runner identity is re-resolved server-side;
- argv is fixed/structured and never shell-evaluated;
- environment is allowlisted;
- working directory is bounded and symlink-safe;
- output/log size is bounded;
- secrets/tokens/environment credentials do not appear in returned logs;
- timeout terminates the whole owned process group;
- cancellation cannot kill unrelated processes;
- executor unavailable -> Web operation fails closed with no partial readiness mutation.

### Level 4 — concurrency/idempotency tests

Test:

- two conflicting mutations on one Runner;
- build vs promote race;
- validate vs promote race;
- duplicate submission/retry;
- stale lease recovery;
- non-conflicting read while mutation runs;
- restart/recovery of an Operator Job record;
- no double receipt/promotion from retries.

### Level 5 — server/integration tests

Prove with real control-core objects that:

- CLI JSON, Admin API, and admission evaluate the same readiness state/reason/evidence;
- receipt invalidation changes `READY -> VALIDATION_STALE`;
- build-input change changes readiness according to the existing contract;
- valid revalidation restores `READY`;
- capacity changes do not mutate readiness;
- access changes do not mutate readiness;
- infrastructure readiness changes do not silently rewrite Runner readiness;
- an operation that fails midway leaves evidence in a safe, explainable state.

Use fakes for expensive external execution where the contract is what is under test. Do not require real GPU/SIF merely to test authorization and orchestration.

### Level 6 — browser acceptance

Using the existing browser/fixture harness, cover at least:

- non-admin cannot enter/use the operator surface;
- Admin fleet table shows distinct readiness/capacity/access;
- READY, NOT_BUILT, BUILD_STALE, NOT_VALIDATED, VALIDATION_STALE, NOT_CONFIGURED render with meaningful corrective guidance;
- a plan is displayed before a state-changing routine operation;
- confirmation is required for activation/promotion-class actions;
- an Operator Job progresses through state without blocking the page;
- failure/cancellation is visible and actionable;
- stale evidence forces replanning;
- history shows the resulting transition;
- no arbitrary text field accepts a shell command.

### Level 7 — deterministic parallel-registry regression

Add a focused CI regression that repeatedly exercises discovery and the AF3 workflow-composer path under xdist/parallel execution.

The regression should fail if plugin state depends on test scheduling.

Do not mask the failure with retries that merely rerun until green.

---

## 12. Permission tiers

Document and enforce a conservative Web/CLI capability matrix.

Suggested model:

| Capability | CLI | Admin Web |
| --- | --- | --- |
| status/evidence | yes | yes |
| Doctor | yes | yes |
| live/smoke validation | yes | yes |
| prepare/build | yes | yes, typed job |
| promote/activate | yes | yes, explicit confirmation |
| readiness repair plan | yes | yes |
| bounded logs/history | yes | yes |
| service-wide restart | yes | only if a narrow safe primitive already exists |
| bootstrap/setup | yes | no |
| secrets | yes/operator-only | no |
| destructive reset/recovery | yes/break-glass | no |
| arbitrary shell | no control API requirement | never |

The CLI may remain more powerful because it operates in an explicit operator/SSH context.

Do not remove CLI capability merely because Web coverage exists.

---

## 13. API contract

Expose the smallest typed Admin API necessary for:

- fleet readiness list;
- family detail/evidence;
- readiness history;
- operation planning;
- operation creation;
- operator job status/logs;
- cancellation where supported.

Keep schema ownership in OpenAPI and regenerate checked-in frontend types.

Never hand-edit generated TypeScript.

Do not expose host paths, secret values, raw environment dumps, unrestricted command lines, or sensitive credentials in API responses.

Use stable machine-readable reason/action/state codes and let the frontend localize explanatory copy.

---

## 14. CLI compatibility

The existing control CLI remains first-class.

Where implementation is refactored into the shared control core:

- preserve existing command names and documented flags unless correctness requires otherwise;
- preserve stable JSON output contracts where already documented/consumed;
- preserve agent-friendly non-interactive execution;
- do not require Web/server availability for CLI bootstrap/recovery commands;
- preserve the ability to diagnose a server that cannot start.

CLI must not become an HTTP client to the running Web application for operations that need to work during Web/server failure.

---

## 15. Documentation

Update durable docs to explain:

- one control plane / two surfaces;
- the Runner readiness derivation model;
- readiness vs capacity vs access vs infrastructure;
- CLI vs Admin Web permission boundary;
- typed operator actions;
- Operator Job lifecycle;
- plan/execute/revalidate semantics;
- lease/concurrency semantics;
- audit/history;
- recovery when the Web UI or executor is unavailable;
- which operations intentionally remain CLI-only;
- security threat model and trust boundaries.

Do not duplicate the complete CLI manual into the Admin guide.

---

## 16. Explicit scope exclusions

Do not:

- remove or deprecate the CLI;
- add a generic shell/command endpoint;
- expose Docker socket or unrestricted sudo to the Web app;
- build a generic workflow engine;
- build a new scheduler;
- redesign Slurm;
- redesign Apptainer/SIF packaging;
- redesign Runner scientific contracts;
- make queue occupancy part of readiness;
- make user entitlement part of readiness;
- make infrastructure readiness equivalent to Runner readiness;
- add Prometheus/Grafana merely for this feature;
- bulk-"fix" every unaudited Runner from #46;
- add new scientific Runners;
- reopen Soft Precision visual redesign;
- silently mark a Runner READY from an admin button.

---

## 17. Test and quality gates

At minimum run the affected:

- registry/plugin discovery tests;
- AF3 workflow-composer regression repeatedly under xdist;
- Runner readiness/admission tests;
- control CLI tests;
- Admin auth/security tests;
- Operator Executor/job tests;
- concurrency/idempotency tests;
- OpenAPI/type generation checks;
- frontend unit tests;
- Admin browser tests;
- ServerComposeFullStack where the host/executor boundary changes;
- `mkdocs build --strict`;
- `git diff --check`.

Do not waive a new security failure as a flaky test.

The known historical AF3 xdist failure is part of this PR's target and may no longer be treated as an unrelated accepted flake after this PR claims to fix it.

---

## 18. Pre-final review cell

Before `READY_FOR_FINAL_REVIEW`, run three independent reviews at the exact implementation-complete head:

1. **Security / privilege-boundary review**
   - authentication/authorization;
   - command injection;
   - host boundary;
   - least privilege;
   - logs/secrets;
   - concurrency/idempotency;
   - fail-closed behavior.

2. **Control/readiness correctness review**
   - registry determinism;
   - readiness derivation;
   - CLI/API/admission equivalence;
   - invalidation/restoration semantics;
   - evidence ownership.

3. **Admin UX / integration review**
   - usable routine operations;
   - plan/execute clarity;
   - readiness/capacity/access separation;
   - browser acceptance;
   - Soft Precision consistency;
   - no frontend-owned operational truth.

Reviewers are independent until findings are submitted. Consolidate findings into one bounded correction set. Use targeted rechecks after fixes.

A security reviewer may block the PR even when functional tests are green.

---

## 19. Definition of done

This PR is complete when the repository can prove all of the following:

> Plugin/Runner discovery is deterministic under parallel test execution.

> Runner readiness has one canonical evaluator used by CLI, admission, and Admin API.

> Admin can inspect and maintain routine Runner readiness through a usable Web UI without SSH.

> CLI remains available, automation-friendly, and more powerful for bootstrap/recovery.

> Web-triggered control operations are typed, planned, auditable Operator Jobs rather than arbitrary shell commands.

> Readiness is derived from current evidence and cannot be manually toggled.

> Readiness, transient capacity, access entitlement, and infrastructure state remain separate.

> Privileged operations are protected by multiple independent layers of authentication, authorization, schema validation, executor isolation, lease/idempotency controls, bounded/redacted output, and adversarial tests.

> A failed or unavailable executor fails closed and cannot silently create READY evidence.

> For one representative Runner, an Admin can observe a stale state, inspect why, obtain a corrective plan, execute the allowed remediation, watch progress, inspect evidence/history, and observe the same final readiness in Admin UI, CLI JSON, and submission admission.

The final PR report must include:

- exact final head;
- registry/AF3 repeated parallel-regression evidence;
- security test matrix and results;
- CLI/API/admission equivalence evidence;
- representative Admin repair-flow browser evidence;
- any deliberately CLI-only operations;
- known limitations;
- three-way pre-final review disposition.

Do not merge.

---

## 20. Operational resilience, rollback, and failure-drill requirements

The control plane must remain understandable and recoverable when operations fail, the Server restarts, the executor disappears, or evidence changes mid-flight.

The governing invariant is:

> **No operator action may leave REvoCompute in a state that is less explainable than before the action.**

After any build, validate, promote, repair, cancel, crash, restart, timeout, or executor failure, an administrator must still be able to answer:

- what state the Runner is in now;
- why it is in that state;
- which operation was requested;
- which effective actions actually ran;
- how far the operation progressed;
- whether the active artifact changed;
- which evidence/receipt was created or invalidated;
- what the next safe corrective action is.

These requirements are part of the merge gate.

### 20.1 Promotion atomicity and rollback

Treat activation/promotion as an atomic control-plane transition.

A promotion must bind:

```text
previous active identity
candidate identity
validation receipt identity
expected evidence digest
new active identity
```

The candidate validated must be the candidate promoted.

Reject the operation if the candidate, receipt, runtime bundle, policy, or relevant evidence identity changes between plan and execution.

A partially completed promotion must never leave admission pointing at an artifact whose provenance cannot be reconstructed.

Where the existing runtime/deployment model can support it safely, expose a typed rollback to the immediately previous **known validated** active artifact.

Rollback must:

- target only a control-core-known artifact identity;
- never accept an arbitrary filesystem path;
- preserve provenance of the rollback source and destination;
- not affect already-running scientific Tasks;
- apply only to later submissions;
- require explicit confirmation in Web;
- record actor, reason, before/after identities, and outcome.

Do not invent a generic artifact browser merely to support rollback.

If safe rollback cannot be implemented within the existing deployment model, keep it CLI-only and document the limitation rather than approximating it unsafely.

### 20.2 Snapshot identity and stale-page protection

Every Runner readiness/detail response used for planning a mutation must expose a stable current snapshot identity, such as:

```text
evaluated_at
evidence_digest / revision
```

The exact representation may follow existing repository conventions.

Plans must bind to that snapshot identity.

Before execution, the server/control core must re-evaluate relevant evidence and reject a stale plan if the snapshot changed.

This protects against:

- an Admin tab left open for a long time;
- a second administrator changing the same Runner;
- an agent/CLI operation occurring between plan and confirm;
- a new receipt being written;
- a runtime bundle or policy change;
- deployment reconciliation changing active identity.

The Web UI must surface stale-plan rejection as:

> State changed; review the new plan.

Do not silently re-plan and execute a materially different mutation under the old confirmation.

### 20.3 Operator Job restart/orphan reconciliation

Persisted Operator Jobs must have explicit recovery semantics.

After Server or executor restart, a job previously recorded as `RUNNING` must not:

- remain permanently RUNNING without investigation;
- be blindly marked FAILED;
- be automatically executed again;
- repeat a promotion or receipt-writing side effect.

On recovery, reconcile the durable job record with the actual owned execution/evidence state.

Use a state such as `RECONCILING` / `ORPHANED` only if useful to the existing state model; do not add states merely to mirror this wording.

Recovery must determine, where possible:

- whether the owned process/job still exists;
- whether the operation completed before the restart;
- whether a candidate/receipt/promotion was actually produced;
- whether a lease is still valid;
- whether cancellation was requested;
- whether a retry is safe.

Irreversible or idempotency-sensitive operations must never be repeated automatically without proof that the prior attempt had no effect.

### 20.4 Executor unavailable is a supported degraded mode

The Admin control surface must remain useful when the Host Operator Executor is unavailable.

In that state:

- readiness/evidence/history remain viewable when their server-side sources are available;
- mutation actions are disabled/fail closed;
- the UI clearly reports `Operator executor unavailable`;
- no existing READY evidence is fabricated, cleared, or rewritten merely because the executor is offline;
- no long-running HTTP retry loop blocks the Admin page.

Executor availability is an operational capability, not Runner readiness itself.

Do not make the whole Admin configuration page depend on the executor being online.

### 20.5 Bounded operator queue and anti-flood behavior

Protect the control plane from accidental operation floods, browser retries, automation loops, and multiple administrators.

Add bounded controls appropriate to the existing architecture, including:

- one conflicting mutation lease per Runner scope;
- a bounded global/operator queue;
- idempotency for mutation creation;
- rejection or coalescing of duplicate in-flight intents where safe;
- conservative request/rate bounds for mutation endpoints;
- no unbounded job creation from repeated clicks or network retries.

This is operational safety, not user-throttling policy.

Do not create a general rate-limiting framework if a small bounded mechanism is sufficient.

### 20.6 Requested intent versus effective actions

Audit/history must record both what the operator requested and what the control core actually executed.

Example:

```text
requested_intent = repair_readiness
effective_actions = [live_test]
```

Do not collapse this into only:

```text
repair succeeded
```

For each mutation record, preserve where applicable:

- requested intent;
- plan identity;
- effective action sequence;
- target;
- before snapshot;
- after snapshot;
- actor;
- timestamps;
- outcome;
- created/invalidated artifact or receipt identities;
- cancellation/timeout/failure reason.

This is especially important for agent-driven CLI operations and later forensic review.

### 20.7 Equivalent CLI visibility

Where a Web operation has a stable existing CLI equivalent, the Admin plan/detail view may show it as **read-only reference text**.

This is for operator understanding and handoff between human/Web and agent/SSH workflows.

It must never be used as the execution mechanism and must never become an editable shell field.

The Web implementation still calls the typed control core / Operator Job path, not the displayed command.

Do not fabricate an equivalent CLI string when no stable CLI operation exists.

### 20.8 Prefer bounded polling over new realtime infrastructure

Operator Job progress must be usable without introducing a new realtime stack.

Prefer bounded polling using the existing frontend/API architecture.

Do not add WebSocket/SSE infrastructure solely for this PR unless evidence demonstrates that polling cannot satisfy the required UX or load envelope.

### 20.9 End-to-end failure drill

In addition to the successful representative repair flow required above, add one representative failure/recovery acceptance path.

It should prove a sequence equivalent to:

```text
VALIDATION_STALE
→ plan repair
→ start Operator Job
→ effective validation begins
→ operation fails
→ no false READY state is produced
→ failure and partial progress are recorded
→ active artifact identity remains explainable
→ Admin obtains a fresh plan
→ retry/recovery succeeds
→ new receipt is recorded
→ READY
```

The test may use bounded fakes/reference execution where the control contract is the subject under test.

It must not require a real GPU or large scientific runtime merely to prove control-plane failure semantics.

### 20.10 Additional security/resilience tests

Extend the multi-level security matrix with explicit cases for:

- TOCTOU between plan and execute;
- candidate/receipt mismatch at promotion;
- rollback to an unknown/unvalidated artifact;
- duplicate promotion request;
- Server restart during an Operator Job;
- executor restart during an Operator Job;
- orphaned RUNNING job reconciliation;
- executor unavailable before job creation;
- executor loss during execution;
- stale browser snapshot;
- two Admins planning/executing against the same Runner;
- mutation flood / repeated-click behavior;
- audit log preservation of requested versus effective action;
- secret redaction after subprocess failure;
- cancellation followed immediately by a conflicting mutation;
- active-artifact invariants after failed promote/rollback.

At least one integration/browser path must demonstrate that a failed privileged operation leaves the Admin UI with an accurate, explainable state and a safe next action.

### 20.11 Supplement to Definition of done

Before `READY_FOR_FINAL_REVIEW`, additionally prove:

> Promotion cannot activate an artifact different from the one validated by the accepted plan.

> Stale plans fail closed rather than silently executing against new evidence.

> Server/executor restart cannot duplicate an irreversible operator action.

> Executor unavailability degrades mutation capability without destroying observability.

> Failed/cancelled operations preserve an explainable active-artifact/readiness state and auditable requested/effective history.

> Routine Admin operation floods and conflicting mutations are bounded by leases, idempotency, and queue limits.

> One failure drill demonstrates failure → no false READY → replan/retry → successful evidence restoration.

These additions strengthen the existing control-plane scope; they must not be used as justification to introduce a generic workflow engine, remote shell, new scheduler, or unrelated deployment framework.

