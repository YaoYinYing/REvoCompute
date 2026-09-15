# TODO: Platform Trust, Preflight, Observability, GPU Credits & Runner Onboarding

## 0. Scope and architecture invariants

This phase improves the REvoCompute control plane. It must not redesign scientific Runner contracts, ResultStoryboard semantics, Slurm scheduling policy, or Project Dashboard responsibilities unless required by the work below.

### 0.1 Core invariants

* [ ] Keep scientific behavior family-owned.
* [ ] Keep security validation Core-owned.
* [ ] Keep `task.yaml` the authoritative source of user-facing scientific parameters and input roles.
* [ ] Never load arbitrary validator code from a Runner family into the trusted preflight boundary.
* [ ] Never let browser validation become authoritative.
* [ ] Keep entitlement, readiness, capacity, and GPU-credit availability as separate concepts.
* [ ] Keep Runner readiness derived from current evidence rather than mutable operator flags.
* [ ] Keep product progress separate from operational observability.
* [ ] Never write raw sequences, structures, SMILES, uploaded JSON, credentials, email addresses, or other scientific/user content into operational logs.
* [ ] Preserve the rule that compute runtime code does not open the user authentication database.
* [ ] Preserve immutable per-Task input snapshots.
* [ ] Preserve user ownership boundaries for Task and Artifact storage.

### 0.2 New invariants

* [ ] **Security preflight precedes durable Task creation.**
* [ ] **GPU credits control admission to new GPU allocations, not termination of already-running allocations.**
* [ ] **Actual GPU allocation time is the accounting source of truth.**
* [ ] **Queue time and CPU-only stages never consume GPU credits.**
* [ ] **Every important admission/allocation decision is traceable through stable IDs.**
* [ ] **Infrastructure readiness and transient resource capacity are reported separately.**

---

# 1. Infrastructure Readiness

## 1.1 Define infrastructure readiness model

Introduce a platform-level readiness model independent of Runner readiness.

Initial status vocabulary:

```text
READY
DEGRADED
UNAVAILABLE
```

* [x] Define typed infrastructure component states.
* [x] Define stable `reason_code` values.
* [x] Define human-readable messages.
* [x] Define `checked_at`.
* [x] Define optional `next_action` for administrators.
* [x] Define which failures produce `DEGRADED` versus `UNAVAILABLE`.
* [x] Keep current Runner readiness model unchanged.

Candidate components:

```text
web_api
redis
celery_worker
task_database
user_database
task_storage
result_storage
scratch_storage
slurm_controller
slurm_submission
gpu_inventory
```

## 1.2 Add infrastructure probes

* [x] Web/API process health.
* [x] Redis connectivity.
* [x] Celery worker availability.
* [x] Task database read/write health.
* [x] Required user database read health where appropriate.
* [x] Workspace filesystem availability.
* [x] Result filesystem availability.
* [x] Free-space threshold checks.
* [x] Scratch backend availability.
* [x] Slurm command availability.
* [x] Slurm controller/query availability.
* [ ] Slurm submission-path sanity.
* [x] GPU inventory visibility on compute nodes where feasible.
* [x] Configurable warning/critical disk thresholds.

Do not make expensive scientific live tests part of routine infrastructure polling.

## 1.3 Separate readiness from capacity

Explicitly model:

```text
readiness = can the service correctly perform this class of work?
capacity  = is compute capacity immediately available?
```

Examples:

```text
GPU READY + BUSY
SLURM READY + QUEUED
Runner READY + no free GPU
```

* [x] Do not mark infrastructure unavailable merely because the GPU is occupied.
* [x] Do not mark a Runner unready because jobs are queued.
* [ ] Expose queue/capacity data independently.

## 1.4 User-facing projection

Provide a compact projection suitable for Runner pages and task submission.

Example:

```text
Infrastructure       READY
Scheduler            Available
GPU                  Busy
Worker               Healthy
Storage              Healthy
```

* [x] Expose only safe, useful information.
* [x] Do not expose internal hostnames, filesystem paths, Slurm configuration details, or credentials.
* [x] Include current timestamp.
* [x] Include stale-data handling.

## 1.5 Admin-facing projection

Admin view may include:

* component;

* state;

* reason code;

* message;

* last check time;

* check duration;

* failure count;

* operator next action.

* [x] Add infrastructure readiness panel.

* [x] Support manual refresh.

* [x] Preserve the last known evidence when a probe itself fails.

* [x] Clearly identify stale evidence.

## 1.6 Infrastructure readiness API

Add a stable server-owned endpoint, e.g.:

```text
GET /compute/api/infrastructure
```

Public/authenticated scope should be decided conservatively.

* [x] Add OpenAPI schema.
* [x] Add response contract tests.
* [x] Add failure-mode tests.
* [x] Add stale-evidence tests.

---

# 2. Core Preflight

## 2.1 Establish the trust boundary

Preflight must execute in REvoCompute Core.

The Runner must not participate in deciding whether arbitrary user input is safe.

Target flow:

```text
untrusted request
      ↓
bounded quarantine
      ↓
security validation
      ↓
contract validation
      ↓
admission evaluation
      ↓
immutable Task snapshot
      ↓
Task persistence
      ↓
Celery
      ↓
Slurm / Apptainer
      ↓
Runner
```

* [x] Move authoritative hostile-input validation before Task snapshot creation.
* [x] Move validation before `task.json` publication.
* [x] Move validation before Task DB insertion.
* [x] Move validation before Celery submission.
* [x] Ensure failed preflight leaves no durable Task.
* [x] Ensure temporary quarantine data is deleted after rejection.

## 2.2 Build a shared preflight service

Create one reusable Core path used by both:

```text
POST /compute/api/preflight/<task_type>
POST /compute/api/post
```

Submission must not maintain a second validator implementation.

Conceptually:

```text
PreflightService
├── SecurityValidator
├── ContractValidator
└── AdmissionEvaluator
```

* [x] Define typed preflight result.
* [x] Define errors versus warnings.
* [x] Define blocking/non-blocking findings.
* [x] Define stable finding codes.
* [x] Return normalized/resolved parameters.
* [x] Return safe input summaries.
* [x] Never return internal paths.

## 2.3 Security validation layer

Security validation asks:

> Is this untrusted input safe for REvoCompute to accept and inspect?

It does not ask whether the input is scientifically appropriate.

Validate at least:

### Path and filename security

* [ ] Reject absolute paths.
* [ ] Reject `..` traversal.
* [ ] Reject path separators in role-local filenames where forbidden.
* [ ] Handle Windows path separators.
* [ ] Normalize Unicode before path-policy decisions.
* [ ] Reject NUL bytes.
* [ ] Reject unsafe control characters.
* [ ] Reject dangerous empty/ambiguous path components.
* [ ] Reject symlink traversal.
* [ ] Reject hard-link/path escape where applicable.
* [ ] Verify artifact-reference ownership before reuse.

### Upload resource limits

* [ ] Enforce request body limits before parsing.
* [ ] Enforce per-file size limits.
* [ ] Enforce total upload size limits.
* [ ] Enforce file-count limits.
* [ ] Bound decompression if compressed uploads are ever introduced.
* [ ] Do not recursively unpack user archives during preflight unless a dedicated safe archive contract exists.

### Content/extension mismatch

* [ ] Do not trust browser MIME.
* [ ] Do not trust extension alone.
* [ ] Perform bounded content sniffing.
* [ ] Reject binary content masquerading as text where inappropriate.
* [ ] Reject unsupported content before scientific parsing.

### Complexity limits

Preserve and expand current safeguards for:

* [ ] FASTA sequence count.
* [ ] FASTA residue count.
* [ ] A3M complexity.
* [ ] PDB line count.
* [ ] PDB record length.
* [ ] mmCIF atom count.
* [ ] mmCIF record length.
* [ ] JSON bytes.
* [ ] JSON nesting depth.
* [ ] JSON node count.
* [ ] SDF molecule count where relevant.
* [ ] MOL2/PDBQT structural complexity.
* [ ] pathological numeric/text fields.

## 2.4 Parser isolation

Some third-party parsers can be expensive or unsafe against adversarial input.

* [ ] Classify validators as `safe_inprocess` or `isolated`.
* [ ] Keep simple bounded text validators in-process.
* [ ] Run complex parsers in a Core-owned validation subprocess where appropriate.
* [ ] Apply strict CPU time limit.
* [ ] Apply memory limit.
* [ ] Disable network access.
* [ ] Use a restricted temporary directory.
* [ ] Do not mount Runner databases or weights.
* [ ] Do not invoke shell commands derived from user content.
* [ ] Treat timeout/OOM/parser crashes as validation failure, not server failure.

This remains Core preflight, not Runner execution.

## 2.5 JSON-specific hardening

JSON requires more than successful `json.loads()`.

* [ ] Apply byte/node/depth caps before/while decoding.
* [ ] Validate expected top-level shape.
* [ ] Reject unexpected path-like values where the task contract prohibits paths.
* [ ] Reject arbitrary URL/external resource references unless explicitly supported.
* [ ] Reject attempts to reference host paths.
* [ ] Audit AlphaFold 3 input semantics specifically.
* [ ] Ensure upstream JSON cannot cause arbitrary host file reads.
* [ ] Ensure upstream JSON cannot broaden network access.
* [ ] Ensure generated JAAG JSON obeys the same server validation as uploaded JSON.

## 2.6 Contract validation layer

After security acceptance, validate against TaskType.

* [ ] TaskType exists and is enabled.
* [ ] Input role exists.
* [ ] Role cardinality matches.
* [ ] Declared format matches.
* [ ] Logical input profile passes.
* [ ] Parameter names are allowlisted.
* [ ] Parameter JSON Schema passes.
* [ ] Defaults resolve exactly once from `task.yaml`.
* [ ] Unknown parameters fail closed.
* [ ] Required parameters are present.
* [ ] Cross-field constraints are checked through trusted Core logic where required.
* [ ] Workspace payload references only declared capability IDs.
* [ ] Referenced previous artifacts remain authorized and immutable.
* [ ] Normalized values are returned for final review.

## 2.7 Admission evaluation layer

Preflight should report current admission state without creating a Task.

Evaluate:

* [ ] authentication state where required;
* [ ] Runner entitlement;
* [ ] Runner readiness;
* [ ] infrastructure readiness;
* [ ] GPU permission;
* [ ] GPU credits;
* [ ] user concurrency policy;
* [ ] resource-policy validity.

Transient capacity should usually be informational rather than blocking.

Example response:

```json
{
  "valid": true,
  "security": {
    "status": "passed"
  },
  "contract": {
    "status": "passed"
  },
  "admission": {
    "allowed": true,
    "runner_ready": true,
    "infrastructure_ready": true,
    "gpu_credit_sufficient": true
  },
  "warnings": [],
  "errors": []
}
```

## 2.8 Preflight API

Candidate:

```text
POST /compute/api/preflight/{task_type}
```

* [x] Match normal submission input semantics.
* [x] Do not create a Task ID intended for durable tracking.
* [x] Do not consume GPU credits.
* [x] Do not enqueue Celery work.
* [x] Do not invoke Slurm.
* [x] Do not invoke Apptainer.
* [x] Do not invoke Runner scripts.
* [x] Add request-rate protection if needed.
* [x] Add request size enforcement.
* [x] Add OpenAPI documentation.

## 2.9 Submission reuse

Submission should conceptually do:

```text
validated = preflight(...)
if not validated.allowed:
    reject

persist(validated.normalized_request)
enqueue(...)
```

* [x] Reuse exact security validator.
* [x] Reuse exact contract validator.
* [x] Re-run admission checks authoritatively.
* [x] Never trust a previous client-visible preflight token/result blindly.
* [x] Avoid TOCTOU assumptions for readiness/credit/access.

---

# 3. Preflight Adversarial Security Test Suite

Create a dedicated suite separate from scientific Runner smoke tests.

## 3.1 Path attacks

* [ ] `../../etc/passwd`
* [ ] nested traversal
* [ ] absolute Unix paths
* [ ] Windows drive paths
* [ ] UNC paths
* [ ] mixed slash/backslash paths
* [ ] percent-like encoded strings where relevant
* [ ] Unicode normalization tricks
* [ ] symlink escape
* [ ] dangling symlink
* [ ] repeated separators
* [ ] hidden/control-character filenames

## 3.2 Format attacks

* [ ] binary-as-FASTA
* [ ] HTML/script-as-text scientific input
* [ ] executable renamed `.pdb`
* [ ] ZIP renamed `.cif`
* [ ] malformed CIF loops
* [ ] absurdly long PDB records
* [ ] huge FASTA header
* [ ] millions of tiny FASTA records
* [ ] invalid molecule records
* [ ] malformed SDF terminators
* [ ] corrupted MOL2/PDBQT

## 3.3 Parser/resource attacks

* [ ] deeply nested JSON.
* [ ] extremely wide JSON.
* [ ] huge JSON strings.
* [ ] excessive JSON node counts.
* [ ] pathological scientific numeric values.
* [ ] parser timeout.
* [ ] parser memory exhaustion.
* [ ] repeated malformed records.
* [ ] third-party parser crash isolation.

## 3.4 Submission-boundary tests

Prove rejected input creates:

* [x] no durable Task row;
* [x] no immutable snapshot;
* [x] no `task.json`;
* [x] no Celery task;
* [ ] no Slurm job;
* [ ] no Runner invocation;
* [x] no residual quarantine file.

## 3.5 Fuzzing

* [ ] Add lightweight property/fuzz tests for path normalization.
* [ ] Fuzz text validators.
* [ ] Fuzz structured scientific formats with bounded input sizes.
* [ ] Add regression corpus for every discovered parser/security bug.

---

# 4. Structured Observability

## 4.1 Define canonical event envelope

All structured events should support:

```text
timestamp
level
event
request_id

task_id
task_type
runner_family
stage_id

celery_task_id
slurm_job_id

reason_code
duration_ms
```

Fields are optional where context does not exist.

* [x] Freeze naming convention.
* [x] Freeze field types.
* [x] Freeze redaction rules.
* [x] Add JSON-line formatter.
* [x] Keep ordinary human-facing progress separate.

## 4.2 Request correlation

* [x] Accept safe incoming `X-Request-ID` where valid.
* [x] Generate one when absent.
* [x] Propagate through request handling.
* [x] Attach Task ID after Task creation.
* [x] Propagate relevant IDs into Celery context.
* [x] Record Slurm job ID when known.
* [x] Preserve correlation across error paths.

## 4.3 Initial event vocabulary

### HTTP

```text
http.request.started
http.request.finished
http.request.failed
```

### Preflight

```text
preflight.started
preflight.security_rejected
preflight.contract_rejected
preflight.admission_denied
preflight.passed
```

### Infrastructure

```text
infrastructure.check.completed
infrastructure.readiness.changed
```

### Task

```text
task.submission.started
task.submitted
task.cancelled
task.failed
task.finished
```

### Celery

```text
worker.task.started
worker.task.failed
worker.task.finished
```

### Slurm

```text
slurm.allocation.requested
slurm.allocation.granted
slurm.allocation.finished
slurm.allocation.failed
slurm.allocation.cancelled
```

### Runner

```text
runner.stage.started
runner.stage.progress
runner.stage.finished
runner.stage.failed
```

### Artifacts

```text
artifact.validation.started
artifact.validation.failed
manifest.published
archive.requested
archive.completed
```

### GPU accounting

```text
gpu.credit.checked
gpu.credit.denied
gpu.usage.started
gpu.usage.settled
gpu.credit.adjusted
```

## 4.4 Privacy/redaction rules

Never log:

* [ ] raw sequence;

* [ ] FASTA headers unless explicitly sanitized and necessary;

* [ ] SMILES;

* [ ] raw JSON input;

* [ ] PDB/mmCIF content;

* [ ] uploaded filename when unnecessary;

* [ ] password/token/API key;

* [ ] Authorization header;

* [ ] email;

* [ ] filesystem path containing private identities;

* [ ] secret environment variables.

* [x] Add tests asserting sensitive fields are absent.

* [x] Sanitize control characters in any user-derived message.

* [x] Bound all user-derived log fields.

## 4.5 Operator tooling

First version does not require Grafana/Loki.

* [x] Make JSON logs usable with `jq`.
* [x] Document common queries by `task_id`.
* [x] Document common queries by `slurm_job_id`.
* [x] Document failure tracing.
* [x] Leave Loki/Grafana integration as optional follow-up.

---

# 5. GPU Credit Accounting

## 5.1 Policy

Default policy:

```text
1000 GPU credits / user / calendar month
1 GPU credit = 1 GPU-minute
```

Credits do not roll over unless explicitly changed later.

GPU credit is independent of `allow_gpu_use`.

Permission asks:

```text
May this user use GPU resources?
```

Credit asks:

```text
How much GPU allocation may this user consume?
```

Both must pass before a new GPU allocation starts.

## 5.2 Accounting unit

Internally use integer GPU-seconds.

```text
1000 credits = 60,000 GPU-seconds
```

Benefits:

* deterministic arithmetic;
* no floating-point drift;
* exact accounting;
* natural multi-GPU extension.

Displayed credits may use decimals.

## 5.3 Usage formula

```text
gpu_seconds_used =
    allocated_gpu_count × allocation_duration_seconds
```

Do not charge:

* [ ] queue time;
* [ ] preflight;
* [ ] upload;
* [ ] CPU-only workflow stages;
* [ ] waiting for dependencies;
* [ ] Celery waiting;
* [ ] Slurm pending state.

Charge:

* [ ] actual active GPU allocation time;
* [ ] successful GPU runs;
* [ ] failed GPU runs;
* [ ] user-cancelled GPU runs up to cancellation;
* [ ] timeout runs up to termination.

## 5.4 Active-task exhaustion behavior

Canonical rule:

> GPU credit is checked before a new GPU allocation. An already-running GPU allocation is never terminated solely because credit reaches zero.

Example:

```text
remaining = 100 credits
task starts
actual GPU usage = 137 min
final balance = -37 credits
```

* [ ] Allow bounded negative balance from an already-started stage.
* [ ] Record full actual usage.
* [ ] Never silently clamp usage at zero balance.
* [ ] Block the next GPU allocation while balance is ≤ 0.

## 5.5 Multi-stage workflows

For:

```text
CPU stage
→ GPU stage
```

check credit immediately before GPU stage.

For:

```text
GPU stage 1
→ CPU stage
→ GPU stage 2
```

* [ ] check before GPU stage 1;
* [ ] settle stage 1;
* [ ] check again before GPU stage 2.

If credit becomes insufficient between stages, do not start the next GPU allocation.

## 5.6 Keep resource-policy termination separate

Credit exhaustion must not disable normal safeguards.

Tasks may still terminate because of:

* walltime;
* Slurm limit;
* admin cancellation;
* resource-policy violation;
* infrastructure failure;
* safety issue.

Credit alone does not kill an active allocation.

## 5.7 Ledger design

Do not maintain only a mutable `balance` field.

Use an append-only accounting ledger.

Conceptual record:

```text
GPUCreditLedger

id
user_id
period
kind
gpu_seconds
task_id
stage_id
slurm_job_id
actor_user_id
reason
created_at
```

Kinds:

```text
monthly_grant
usage
admin_adjustment
reversal
migration_adjustment
```

* [ ] Ledger entries are immutable.
* [ ] Corrections use compensating records.
* [ ] Every admin adjustment records actor and reason.
* [ ] Usage records reference Task/stage/Slurm allocation where available.
* [ ] Balance is derived.

## 5.8 Monthly allocation

* [ ] Default monthly allowance = 60,000 GPU-seconds.
* [ ] Define period using server policy timezone or UTC; document explicitly.
* [ ] Create grant lazily or deterministically.
* [ ] Make grant idempotent.
* [ ] Prevent duplicate monthly grant.
* [ ] No rollover in first implementation.
* [ ] Support per-user monthly allowance override if useful.

## 5.9 Admin adjustment

Admin user-management interface should expose:

```text
Monthly allowance
Used
Adjustments
Remaining
```

Actions:

```text
Add credits
Remove credits
Set monthly allowance
```

Recommended behavior:

* [ ] Require adjustment reason.
* [ ] Show resulting balance before confirmation.
* [ ] Record admin actor.
* [ ] Record timestamp.
* [ ] Add audit/event entry.
* [ ] Never mutate historical usage.

Example:

```text
+200 credits
Reason: approved additional allocation for collaboration run
```

## 5.10 User-facing credit UI

Profile/dashboard:

```text
GPU Credits
September 2026

Monthly allocation       1000
Admin adjustments        +200
Used                      346.8
Remaining                 853.2
```

* [ ] Show current period.
* [ ] Show remaining credit.
* [ ] Explain `1 credit = 1 GPU-minute`.
* [ ] Explain queue time is free.
* [ ] Explain running tasks are allowed to finish if balance reaches zero.
* [ ] Show recent usage history.
* [ ] Do not expose unrelated users.

## 5.11 Admission checks

Check GPU credit:

### Preflight

Informational/current-state evaluation.

### Submission

Authoritative admission evaluation.

### Immediately before GPU allocation

Authoritative final check.

* [ ] Re-check current balance.
* [ ] Re-check `allow_gpu_use`.
* [ ] Re-check entitlement.
* [ ] Re-check relevant readiness.
* [ ] Handle concurrent usage atomically enough for current one-GPU deployment.

## 5.12 Current one-GPU concurrency model

For the first implementation:

* [ ] Do not implement complex reservations.
* [ ] Allow one active allocation to overdraft.
* [ ] Prevent a subsequent GPU allocation if current balance is ≤ 0.
* [ ] Document this behavior.

Future multi-GPU work may add:

```text
estimate
→ reserve
→ run
→ settle actual
→ release unused reservation
```

but this is explicitly deferred.

## 5.13 Database ownership

Do not make `task_runtime.py` open the authentication/user database.

Preferred design:

```text
users.sqlite
    user identity
    allow_gpu_use

compute/accounting database
    gpu ledger
    usage
```

* [ ] Link by immutable user ID.
* [ ] Project credit data into admin user-management UI.
* [ ] Keep accounting transaction boundaries explicit.

---

# 6. GPU Accounting Failure and Recovery

GPU usage must remain correct across worker/server interruption.

* [ ] Record allocation start as soon as real Slurm allocation is confirmed.
* [ ] Record Slurm job ID.
* [ ] Record requested GPU count.
* [ ] Record stage identity.
* [ ] Settle usage when allocation exits.
* [ ] Make settlement idempotent.
* [ ] Detect unsettled historical allocations.
* [ ] Reconcile against Slurm accounting where available.
* [ ] Prevent double charging after Celery retry.
* [ ] Handle server restart during active GPU stage.
* [ ] Handle user cancellation.
* [ ] Handle Slurm timeout.
* [ ] Handle node failure.
* [ ] Handle missing final event.
* [ ] Add admin-visible reconciliation status.

If authoritative runtime cannot be recovered automatically:

* [ ] mark ledger item for review;
* [ ] do not silently guess;
* [ ] expose enough evidence for admin correction.

---

# 7. Onboarding and Example Runner

## 7.1 Create canonical Example Runner

Create:

```text
docker/runners/example/
```

The example should be:

* CPU-only;
* deterministic;
* fast;
* scientifically plausible;
* dependency-light;
* safe for CI/live testing.

Suggested task:

```text
FASTA
→ sequence statistics
→ TSV + JSON
```

Possible output:

```text
sequence_id
length
molecular_weight
aa_composition
```

## 7.2 Example family contents

Demonstrate the complete normal path:

```text
example/
├── plugin.yaml
├── runner.yaml
├── example.def
├── run.sh
├── test.yaml
├── README.md
├── fixtures/
└── tasks/
    └── sequence_statistics/
        └── task.yaml
```

Include:

* [ ] family metadata;
* [ ] pinned runtime/build contract;
* [ ] one input role;
* [ ] one optional parameter;
* [ ] one stage marker;
* [ ] one deterministic fixture;
* [ ] one expected output tree;
* [ ] one ResultStoryboard;
* [ ] artifact metadata;
* [ ] test plan;
* [ ] Doctor validation;
* [ ] direct SIF build;
* [ ] smoke/live acceptance.

## 7.3 Standard onboarding path

Rewrite the first-run documentation around:

```text
1. Copy Example Runner
2. Define plugin.yaml
3. Define task.yaml
4. Implement run.sh
5. Define test.yaml
6. Run Doctor
7. Build SIF
8. Run smoke/live test
9. Inspect receipt
10. Promote
```

The first onboarding page should not require understanding every advanced extension.

## 7.4 Advanced onboarding

Separate documentation for:

* multi-stage workflows;
* custom workspace capabilities;
* custom ResultStoryboard;
* unusual parsers;
* restricted software/access policy;
* large model weights;
* databases;
* network-requiring stages;
* GPU tasks;
* docking;
* complex artifact associations.

## 7.5 Agent onboarding

Document the minimum material an AI coding agent needs to adapt a Runner:

```text
upstream repository
pinned revision
license
official usage example
expected input
expected output
weights/database requirements
CPU/GPU requirements
canonical scientific test case
```

Then instruct agents to use Example Runner as structural reference.

---

# 8. Documentation

## 8.1 Add architecture documentation

Document:

```text
Security preflight
Contract validation
Admission
Infrastructure readiness
Runner readiness
Capacity
GPU credit
```

with explicit boundaries.

## 8.2 Update API docs

Document:

```text
GET  /compute/api/infrastructure
POST /compute/api/preflight/{task_type}
GET  /compute/api/gpu-credit
```

plus appropriate admin endpoints.

## 8.3 Update user guide

Explain:

* what preflight checks;
* preflight does not run the scientific method;
* infrastructure readiness;
* Runner readiness;
* GPU credits;
* queue time versus GPU time;
* credit exhaustion behavior;
* failed jobs and billing;
* admin adjustments.

## 8.4 Update operator guide

Explain:

* infrastructure probes;
* readiness evidence;
* GPU usage reconciliation;
* monthly grant behavior;
* credit adjustment audit;
* security-validator boundaries;
* parser-isolation policy.

---

# 9. UI Work

## 9.1 Create-task final review

Add preflight state:

```text
Input security       Passed
Scientific contract Passed
Runner               Ready
Infrastructure       Ready
GPU access           Granted
GPU credits          842.5 remaining
```

* [ ] Show warnings separately.
* [ ] Disable Run on blocking failure.
* [ ] Preserve one final Run action.
* [ ] Re-run authoritative checks on submission.

## 9.2 Runner detail page

Show:

```text
Runner readiness
Infrastructure
CPU/GPU requirement
Current capacity
```

Avoid exposing operator implementation details.

## 9.3 Profile

Add GPU credit panel.

## 9.4 Admin user management

Add:

* GPU permission;
* monthly allowance;
* current balance;
* current-month usage;
* adjustment history;
* adjustment action;
* required adjustment reason.

## 9.5 Admin operations

Add:

* infrastructure readiness overview;
* unsettled GPU usage records;
* reconciliation warnings;
* failed probes;
* stale readiness evidence.

---

# 10. Tests

## 10.1 Preflight unit tests

* [ ] security validator.
* [ ] contract validator.
* [ ] admission evaluator.
* [x] error/warning serialization.
* [x] normalized parameter output.
* [x] temporary-file cleanup.

## 10.2 Preflight integration tests

* [x] valid request.
* [x] malicious request.
* [ ] invalid TaskType.
* [x] bad role.
* [ ] bad cardinality.
* [ ] invalid parameter.
* [ ] unauthorized Runner.
* [ ] unready Runner.
* [ ] unavailable infrastructure.
* [ ] insufficient GPU credit.
* [ ] CPU Task with zero GPU credit still accepted.

## 10.3 Infrastructure tests

* [ ] Redis down.
* [ ] worker unavailable.
* [ ] Slurm unavailable.
* [ ] result storage unwritable.
* [ ] low disk.
* [ ] GPU busy.
* [ ] GPU unavailable.
* [ ] stale evidence.
* [ ] probe timeout.

## 10.4 Observability tests

* [x] request ID propagation.
* [x] Task ID propagation.
* [x] Slurm job ID propagation.
* [x] expected event emission.
* [x] failure event emission.
* [x] sensitive scientific input absent.
* [x] control-character sanitization.
* [x] bounded message length.

## 10.5 GPU credit tests

* [ ] monthly grant exactly once.
* [ ] credit calculation.
* [ ] admin addition.
* [ ] admin subtraction.
* [ ] correction/reversal.
* [ ] queue time not billed.
* [ ] CPU stage not billed.
* [ ] GPU stage billed.
* [ ] failure billed for actual runtime.
* [ ] cancellation billed to cancellation.
* [ ] zero-credit submission rejected.
* [ ] active task allowed to overdraft.
* [ ] next GPU allocation blocked after overdraft.
* [ ] multi-stage recheck.
* [ ] concurrent settlement.
* [ ] Celery retry does not double-charge.
* [ ] recovery does not double-charge.
* [ ] admin actions are audited.

## 10.6 Example Runner tests

* [ ] Doctor.
* [ ] SIF `%test`.
* [ ] test plan.
* [ ] API submission.
* [ ] worker execution.
* [ ] Slurm/Apptainer live test.
* [ ] output acceptance.
* [ ] ResultStoryboard.
* [ ] artifact download.

---

# 11. Security Review Gate

Before release:

* [ ] Review every preflight parser.
* [ ] Confirm no Runner code executes during security preflight.
* [ ] Confirm no arbitrary network access.
* [ ] Confirm quarantine cleanup.
* [ ] Confirm traversal/symlink protection.
* [ ] Confirm resource bounds.
* [ ] Confirm raw scientific data does not enter logs.
* [ ] Confirm rejected requests create no durable Task.
* [ ] Confirm artifact reuse respects ownership.
* [ ] Confirm admin GPU adjustment endpoints require admin authorization.
* [ ] Confirm users cannot modify their own allowance/ledger.
* [ ] Confirm ledger records cannot be rewritten through public API.

---

# 12. Delivery Order

## Phase 0 — Observability foundation

* [x] Canonical event schema.
* [x] Request correlation.
* [x] JSON logging.
* [x] Privacy/redaction tests.

## Phase 1 — Infrastructure readiness

* [ ] Component probes.
* [ ] readiness aggregation.
* [ ] user projection.
* [ ] admin projection.
* [ ] API.

## Phase 2 — Security-first preflight

* [ ] Quarantine flow.
* [ ] security validators.
* [ ] parser isolation.
* [ ] contract validation.
* [ ] admission evaluation.
* [ ] preflight endpoint.
* [ ] submission reuse.
* [ ] adversarial test suite.

## Phase 3 — GPU credits

* [ ] ledger.
* [ ] monthly grant.
* [ ] usage accounting.
* [ ] allocation-time enforcement.
* [ ] overdraft behavior.
* [ ] admin adjustment.
* [ ] user/admin UI.
* [ ] recovery/reconciliation.

## Phase 4 — Onboarding

* [ ] Example Runner.
* [ ] standard path.
* [ ] advanced path.
* [ ] agent adaptation guide.

## Phase 5 — Production acceptance

* [ ] security review.
* [ ] concurrency tests.
* [ ] failure/restart tests.
* [ ] real Slurm GPU accounting test.
* [ ] complete Example Runner live receipt.
* [ ] documentation review.
* [ ] production rollout.

---

# 13. Explicit Non-goals

This phase does not include:

* Project Dashboard implementation;
* cross-user artifact sharing;
* global scientific-result comparison;
* Runner marketplace;
* runtime-downloaded plugins;
* arbitrary Runner-provided validation code;
* redesign of ResultStoryboard;
* redesign of Expected File Tree;
* redesign of Slurm scheduling/QoS;
* GPU credit purchasing/payment;
* monetary billing;
* credit rollover;
* complex GPU-credit reservation;
* predictive runtime/credit estimation;
* terminating an active GPU job solely because credit reached zero;
* generalized workflow/DAG engine.

---

# 14. Acceptance Criteria

This phase is complete when all of the following are true:

1. A malicious upload cannot reach durable Task storage, Celery, Slurm, Apptainer, or Runner execution before Core security validation.
2. [x] `/preflight` and real submission use the same authoritative validation path.
3. Infrastructure readiness is visible independently from Runner readiness and queue capacity.
4. [x] Operational events allow an operator to trace one request through Task, Celery, Slurm, Runner stage, and result publication without logging scientific inputs.
5. Every user receives 1000 GPU credits per month by default.
6. One GPU credit corresponds to one actual GPU allocation minute.
7. Queue time and CPU stages consume zero GPU credit.
8. An active GPU allocation is not terminated solely due to credit exhaustion.
9. Actual usage may create a negative balance; subsequent GPU allocations are blocked until credit becomes positive.
10. Admins can adjust user GPU credits with an immutable audited reason.
11. GPU usage settlement is idempotent and recoverable across process/server failure.
12. A new developer can adapt a conventional Runner primarily by copying the Example Runner and following the Standard Runner guide.
13. The Example Runner passes Doctor, build, smoke/live execution, artifact acceptance, and ResultStoryboard verification.
14. Existing scientific Runner behavior remains compatible unless explicitly migrated for security correctness.
