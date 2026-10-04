# Machine-generated Production API Acceptance Receipt

## Objective

Turn the post-deploy evidence demonstrated manually in PR #40 into a small,
generic, machine-generated production acceptance receipt.

The receipt must answer, from observed system state rather than handwritten
claims:

```text
what revision was deployed?
which Runner/task was submitted?
what immutable input/parameter snapshot was admitted?
which Slurm job actually executed it?
what lifecycle did the public API expose?
which ResultManifest was published?
which logical/artifact files were published?
what hashes and selected factual observables were observed?
```

This PR is about **provenance and observation**, not scientific equivalence.
PR #40 intentionally stopped at summary-level evidence. Do not recreate the
stronger artifact-comparison work that has not been requested.

The initial real acceptance case is the existing GREMLIN_LH 2KL8 scientific
case because it already has a known production/API path and a clear evidence
history.

---

## 0. Campaign position and dependencies

This is a **Wave 1** PR and may begin from the current `main`.

It is independent of the workflow-stage-marker PR at the implementation level,
but both may need access to shared deployment state. Follow the Campaign
deployment-lease protocol from `LONG_TASK_HANDLING.md`.

The real deployment/API acceptance must be run against one exact head SHA.
Do not redeploy or mutate the target while another PR owns the live-test lease.

---

## 1. Preserve existing architecture

Build on the existing REvoCompute sources of truth:

- public/API task projection;
- task store;
- Slurm/job metadata already recorded by REvoCompute;
- ResultManifest v3;
- Runner manifests and immutable input snapshots;
- existing `revocompute_ctl` operator tooling where it is the correct owner.

Do not add a second task database, second result manifest, production mock mode,
or a Runner-specific API endpoint.

Prefer a narrow operator/test utility that composes existing APIs and stored
evidence.

The implementation must remain generic enough that another Runner can later use
the same receipt path without adding `if runner == "gremlin_lh"` branches.

---

## 2. Define one canonical receipt document

Introduce one machine-readable receipt format for a completed production API
submission.

At minimum record:

### Repository/deployment identity

- receipt schema/version;
- repository revision / deployed revision when observable;
- server/runtime build identity that the production instance exposes;
- capture timestamp;
- target identity in a non-secret, host-neutral form.

### Submission identity

- task id;
- task type;
- submitted/started/finished timestamps as actually observed;
- immutable input snapshot identity and hashes where already available;
- normalized/effective task parameters from the admitted task snapshot;
- submitting user only when safe and already part of existing non-secret
  acceptance evidence; do not leak credentials or private profile fields.

### Scheduler/execution identity

- Slurm job id;
- terminal Slurm state / exit code where available;
- elapsed/runtime fields;
- peak memory/resource observations when they already exist in canonical
  execution evidence;
- exact Runner/SIF/runtime-bundle identity where the platform records it.

### Result identity

- ResultManifest version;
- declared result views;
- logical files/artifact inventory;
- size and sha256 for bounded published files;
- stable metadata required to prove the receipt refers to the exact published
  result rather than another task.

### Observed factual summaries

For the GREMLIN_LH initial case, it is acceptable to record factual values that
can be read from the published artifacts, such as:

- sequence count;
- alignment length;
- effective sequence count;
- final loss;
- excluded-column count;
- declared parameters.

These are observations only. The receipt must not label them scientific
equivalence unless an independent comparator actually establishes that.

---

## 3. Derive facts; do not hand-copy them

The PR #40 review found two classes of errors that machine collection should
eliminate:

- an impossible manually stated lifecycle duration;
- transposed 6 x 79 input dimensions.

The new receipt generator must derive lifecycle values from canonical API/task
timestamps and scheduler evidence.

Dimensions and scientific summary fields must be parsed from the relevant
published artifact or manifest field, not restated from prose.

Do not encode expected values merely so the generated receipt can repeat them.

---

## 4. Integrity and canonicalization

The receipt must be deterministic for the same captured task evidence apart
from explicitly volatile capture metadata.

Use stable ordering and canonical JSON serialization.

Hashes must be computed from the bytes actually published for that task.

Reject or visibly mark:

- a task that is not terminal;
- a missing ResultManifest;
- a ResultManifest whose task identity disagrees with the requested task;
- a logical file that resolves outside the task result root;
- a missing required artifact;
- inconsistent task/scheduler identity;
- malformed timestamps or negative lifecycle intervals.

Do not silently omit an inconsistency and still report PASS.

---

## 5. Secrets, privacy, and portability

The checked-in receipt/evidence must be safe to publish in the repository.

Never store:

- API tokens;
- cookies/session credentials;
- Authorization headers;
- passwords;
- private filesystem paths that are not already an intentional public
  deployment contract;
- proxy credentials;
- raw environment dumps.

Use the project's existing sanitization utilities where appropriate.

Add a regression test that feeds representative secret-bearing headers or
fields and proves they cannot enter the persisted receipt.

---

## 6. CLI/operator workflow

Provide one clear operator path that can capture a receipt for an existing
finished task or for a newly submitted acceptance task.

Prefer composition with current `revocompute_ctl` commands instead of a new
parallel CLI framework.

The operator should be able to provide the task identity and obtain:

```text
machine-readable receipt
human-readable one-screen summary
non-zero exit on inconsistent or incomplete evidence
```

Do not require editing Markdown by hand to establish the machine evidence.

---

## 7. GREMLIN_LH production acceptance

Exercise the existing 2KL8 scientific input/profile through the public
production API using an exclusive deployment/live-test lease.

Record:

- exact deployed head;
- task id;
- Slurm job id;
- real API lifecycle timestamps;
- SIF/runtime identity where available;
- ResultManifest v3 identity;
- full bounded artifact inventory and hashes;
- derived 6-sequence x 79-position dimensions;
- observed Neff/final-loss and other existing summary fields.

Then verify the generated receipt agrees with the facts already known from the
task itself.

**Do not claim artifact-level or upstream scientific equivalence in this PR.**
Hashing a production artifact proves identity of that artifact, not agreement
with a scientific reference.

---

## 8. Documentation ownership

Update only the minimum durable documentation needed to explain:

- what the receipt proves;
- what it explicitly does not prove;
- how an operator captures one;
- how another Runner can reuse it.

Do not add another long acceptance narrative that duplicates the generated
receipt.

Where existing GREMLIN_LH acceptance prose is updated, point to the machine
receipt and keep the previous scientific-reference distinction intact.

---

## 9. Required tests

Add focused coverage for:

- canonical serialization/determinism;
- task/manifest identity mismatch;
- unfinished task rejection;
- missing required artifact;
- artifact hashing;
- path containment;
- lifecycle derivation;
- malformed timestamp handling;
- secret sanitization;
- GREMLIN_LH receipt parsing from deterministic fixture evidence.

Run the relevant non-browser suite for the touched operator/server modules.

If documentation changes, run:

```bash
mkdocs build --strict
```

Run `git diff --check`.

A production acceptance receipt from the exact final head is required before
`READY_FOR_FINAL_REVIEW` because production observation is the purpose of this
PR.

---

## 10. Scope exclusions

Do **not**:

- implement artifact-level scientific equivalence;
- redesign ResultManifest;
- add production mock endpoints;
- redesign live-test receipts globally unless a small compatible extension is
  necessary;
- modify GREMLIN_LH fitting science;
- change Runner parameters merely to make the receipt easy to collect;
- retrofit every Runner;
- reopen frontend/backend architecture;
- introduce a telemetry system.

---

## 11. Definition of done

The PR is complete when a reviewer can take one checked-in machine receipt and
trace:

```text
exact deployment
  -> admitted task snapshot
  -> Slurm execution
  -> API lifecycle
  -> ResultManifest
  -> exact published artifacts
  -> factual observed summaries
```

without relying on manually copied numbers, while the receipt makes no stronger
scientific claim than the evidence supports.
