# TODO.md — Complete PR #14 and Promote CPU Docking Only

> Scope update (2026-09-14): final GPU candidate SIF completion and target-host
> GPU acceptance are follow-up work and do not block this PR or redeployment.
> The repaired GPU plugin contracts remain fail-closed, disabled, and without
> live-test receipts. AutoDock Vina remains the only docking Runner eligible for
> promotion in this delivery.



Current pull request:

```text
Repository: YaoYinYing/REvoCompute
PR: #14
Branch: feat/docking-runner-suite
Title: feat: add molecular docking runner suite
```

This is a continuation of the existing PR.

**Do not create another feature branch or another PR.**

---

# 1. Resume the existing PR branch

Begin from the current remote state.

```text
git fetch origin --prune
git checkout feat/docking-runner-suite
git reset only if required by repository guidance
git pull --ff-only
```

Confirm:

```text
origin/main
origin/feat/docking-runner-suite
PR #14 head SHA
current worktree state
current unresolved review threads
current CI state
```

Do not assume the previous session's local state is current.

Record the starting PR head in `IMPLEMENTATION_STATE.md`.

---

# 2. Do not wait for the GPU

The production GPU is expected to remain occupied for approximately one week.

This is an external infrastructure constraint, not a Runner failure.

Do not spend this session repeatedly polling:

```text
squeue
sleep
squeue
sleep
...
```

Do not make GPU availability a merge blocker for contract-complete but disabled Runner integrations.

The intended workflow is:

```text
repair GPU Runner contracts
        ↓
build candidate SIFs
        ↓
run non-GPU validation / %test where possible
        ↓
record GPU live acceptance as DEFERRED
        ↓
leave readiness fail-closed
        ↓
merge when the PR itself is otherwise correct
        ↓
production redeploy enables AutoDock Vina only
```

No GPU Runner may become READY merely because its SIF built successfully.

---

# 3. Add production-resource reasoning to CLAUDE.md

Add a concise operator rule to `CLAUDE.md` covering blocked live tests on shared production resources.

The rule must establish this sequence:

```text
required GPU unavailable
        ↓
inspect scheduler overview
        ↓
identify blocking production job
        ↓
scontrol show job <jobid>
        ↓
reason about expected duration
        ↓
wait briefly OR defer
```

The agent must not rely on `squeue` alone.

At minimum inspect useful fields exposed by Slurm, where available:

```text
JobId
JobName
UserId
JobState
RunTime
TimeLimit
StartTime
EndTime
Command
WorkDir
Reason
TresPerNode / GRES
```

Do not require every field to exist.

The purpose is to establish whether waiting is rational.

---

# 4. Define the scheduler waiting policy

Encode the following policy in `CLAUDE.md`.

## Clearly short job

If scheduler metadata strongly indicates that the blocking production task should finish soon, a bounded recheck is reasonable.

Do not poll at high frequency.

## Unclear job

If its duration cannot be inferred:

```text
sleep 600
```

Then inspect the scheduler state once more.

Use both:

```text
squeue
scontrol show job <jobid>
```

After that second inspection, make a decision.

Do not continue ten-minute polling indefinitely.

## Clearly long job

If the blocking task is evidently a long production workload, immediately defer accelerator-dependent validation for the current delivery.

Typical signals include:

```text
gmx mdrun
molecular-dynamics production job
long trajectory generation
multi-hour or multi-day TimeLimit
already-large RunTime with substantial TimeLimit remaining
job name / command / work directory clearly indicating MD
other production simulations whose expected completion is not near
```

For these cases:

```text
GPU validation = DEFERRED
```

Do not sleep for ten minutes merely to confirm what is already evident.

---

# 5. Define what "permanently pause GPU testing" means

Do not interpret this as deleting the tests or permanently abandoning the Runner.

It means:

> For the current PR/session/delivery cycle, stop attempting accelerator-dependent live acceptance until an operator or a future session explicitly revisits it after the resource becomes available.

Once classified this way, the agent must continue useful work instead of polling.

Continue with:

```text
CPU live tests
contract tests
schema tests
wrapper tests
result parser tests
SIF builds
Apptainer %test
Doctor
documentation
CI
PR remediation
CPU-only deployment
```

Do not keep an inactive terminal waiting for the GPU.

---

# 6. Never interfere with production user jobs

The agent may inspect scheduler metadata required to make an operational decision.

It must not, without explicit operator instruction:

```text
cancel another user's job
requeue another user's job
suspend another user's job
change its priority
change its QoS
preempt it manually
modify its TimeLimit
submit deliberately competing GPU jobs
```

A production user's compute task takes precedence over this feature's validation convenience.

Do not commit another user's job ID, username, command line, or working directory into repository documentation.

Repository state should record only the generic blocker, for example:

```text
GPU live acceptance deferred because the production accelerator is occupied by a long-running user workload.
```

---

# 7. Resolve all existing PR #14 review findings

Inspect all unresolved review threads before modifying code.

The current review contains at least the following blockers.

## DiffDock ESM import

The structure-only patch removed the top-level `esm` import while the retained ESM-2 embedding path still calls:

```python
esm.pretrained.load_model_and_alphabet(...)
```

Restore the ordinary `fair-esm` import required for residue embeddings.

Continue removing only:

```text
ESMFold structure generation
protein_sequence input
missing-structure fallback
OpenFold / ESMFold prediction paths
```

Do not remove ESM-2 embeddings derived from residues parsed from the submitted PDB.

Add regression coverage proving the structure-only DiffDock runtime still has a valid ESM-2 embedding dependency.

---

# 8. Repair all docking input-cardinality contracts

The public API/browser contract must agree with each wrapper.

Required cardinality:

```text
AutoDock Vina
    minimum: 2
    maximum: receptor + bounded ligand collection

AutoDock-GPU
    minimum: 2
    maximum: receptor + bounded ligand collection

Gnina
    exactly: 2

DiffDock
    exactly: 2
```

For Vina and AutoDock-GPU:

```text
allow_multiple_inputs: true
min_input_files: 2
```

Retain their bounded `max_input_files`.

For Gnina and DiffDock, the UI/API still needs to accept two files even though the scientific task is not a multi-ligand batch.

Use the repository's cardinality semantics so that:

```text
allow_multiple_inputs: true
min_input_files: 2
max_input_files: 2
```

or the current canonical equivalent.

Do not allow the browser to expose a one-file form for a wrapper that requires two files.

Add API-level/input-validation tests, not only static YAML assertions.

---

# 9. Fix Gnina search-space semantics

The current implementation uses:

```text
submitted ligand
    simultaneously as
docking ligand
    and
autobox reference
```

This is acceptable only for a specific redocking-style setup in which the ligand already has meaningful receptor-relative coordinates.

It is not a sound default contract for general docking or virtual screening.

For this first REvoCompute Gnina Runner, prefer the same explicit Cartesian search-space model used by Vina:

```text
center_x
center_y
center_z

size_x
size_y
size_z
```

Use bounded numeric JSON Schema fields with Å units.

The wrapper should invoke Gnina using the explicit search box.

Do not use the molecule being docked as an implicit pocket-definition ligand.

Do not introduce automatic pocket prediction in this PR.

Do not add a third "reference ligand" input unless the current product/input-role architecture already supports it cleanly and doing so is simpler than explicit coordinates.

The preferred contract for PR #14 is:

```text
receptor
+
ligand
+
explicit search box
```

Update documentation accordingly.

---

# 10. Preserve DiffDock's structure-only boundary

The existing architectural choice is correct.

DiffDock must accept:

```text
protein PDB
+
ligand SDF/MOL2
```

It must not expose:

```text
FASTA
raw protein sequence
protein_sequence
ESMFold
OpenFold
AlphaFold
ColabFold
SimpleFold
Boltz
implicit structure prediction
```

The retained ESM dependency is only for **language-model residue embeddings derived from the submitted PDB**.

That is not structure prediction.

Keep this distinction explicit in:

```text
task.yaml
runtime patch
tests
documentation
PR description
```

---

# 11. Add normalized docking result artifacts

The current implementation mostly exposes native poses/logs.

That is not enough for a production scientific result contract.

Each Runner should expose an additive machine-readable ranking artifact.

Prefer:

```text
scores.csv
summary.json
```

while preserving all native upstream files.

Do not build a central docking parser framework.

Each Runner owns its parser/normalization code.

---

# 12. Normalize AutoDock Vina results

For every ligand and every reported pose, extract the upstream metrics that are actually available.

A useful table is:

```text
ligand
pose_rank
affinity_kcal_mol
rmsd_lb_angstrom
rmsd_ub_angstrom
pose_file
```

Use exact native semantics.

Do not invent missing RMSD values.

For batched ligands, produce one aggregate `scores.csv`.

Preserve:

```text
native PDBQT
Vina log
prepared structures
```

---

# 13. Normalize AutoDock-GPU results

Parse the native DLG results.

Expose only meaningful native AutoDock4 quantities.

A useful table may include, where present:

```text
ligand
run
cluster_rank
binding_energy_kcal_mol
intermolecular_energy_kcal_mol
internal_energy_kcal_mol
pose/result reference
```

Use exact fields actually emitted by the pinned AutoDock-GPU version.

Do not rename AutoDock4 energy into Vina affinity.

Preserve every DLG and AutoGrid record.

---

# 14. Normalize Gnina results

Extract the Gnina SDF properties emitted by the pinned 1.3.2 binary.

Use native names or clearly mapped equivalents such as:

```text
pose_rank
minimizedAffinity
CNNscore
CNNaffinity
pose reference
```

Only include fields actually present.

Do not claim:

```text
CNNscore == physical binding affinity
```

and do not collapse `CNNscore` and `CNNaffinity` into one generic value.

Generate `scores.csv` and `summary.json`.

Preserve the original SDF and log.

---

# 15. Normalize DiffDock results

DiffDock should expose a ranking table built from its actual ranked pose outputs.

At minimum:

```text
pose_rank
confidence
pose_file
```

Use the confidence value emitted by the pinned DiffDock runtime/output naming convention.

Do not label DiffDock confidence as:

```text
binding affinity
free energy
Vina score
```

Preserve the native ranked SDF files.

---

# 16. Use small Runner-owned parsers

Do not make `run.sh` responsible for increasingly complicated text parsing.

Where parsing is nontrivial, place a small Python helper under the owning Runner, for example conceptually:

```text
docker/runners/autodock_vina/python/
docker/runners/autodock_gpu/python/
docker/runners/gnina/python/
docker/runners/diffdock/python/
```

Follow existing Runner packaging conventions.

Helpers should:

```text
read native outputs
validate expected structure
produce normalized artifacts
fail explicitly on corrupt/missing required results
```

Do not create a central `DockingResultParser`.

Add focused unit tests using compact fixtures.

---

# 17. Rebuild candidate SIFs after runtime changes

Any change to:

```text
run.sh
DiffDock patch
Runner-owned parser code
runtime definition
build input identity
```

can change candidate runtime provenance.

Rebuild the affected direct SIF.

Run its embedded `%test`.

For the GPU Runners, `%test` may run without real accelerator inference if the test itself does not require a GPU.

Do not confuse:

```text
SIF %test PASS
```

with:

```text
target-host GPU live acceptance PASS
```

These remain separate gates.

---

# 18. Strengthen DiffDock %test

The previous `%test` missed the missing `esm` import because:

```text
python -m inference --help
```

never instantiated the inference dataset.

Add a lightweight test that catches this class of runtime breakage without requiring full model inference.

For example, verify that the installed structure-only code can import and resolve its retained ESM embedding dependency.

The test should prove:

```text
fair-esm import exists
ESM-2 embedding path remains importable
ESMFold module/path remains absent
protein_sequence CLI path remains absent
```

Do not load large weights merely for this build test unless necessary.

---

# 19. Keep GPU live acceptance explicitly deferred

For:

```text
autodock_gpu
gnina
diffdock
```

record:

```text
target-host live acceptance: DEFERRED
reason: production GPU occupied by long-running user workload
```

Do not run repeated GPU submission attempts.

Do not produce an acceptance receipt.

Do not manually mark these Runners ready.

Do not weaken Doctor/readiness checks.

Expected final state:

```text
candidate image available
contract valid
%test valid
live receipt absent
READY = false
enabled = false
```

---

# 20. Re-run AutoDock Vina live acceptance on the final candidate

The existing successful job `4748` proves the initial Vina path worked.

It is **not automatically sufficient** after modifying the Runner contract, wrapper, parser, build inputs, or output requirements.

Once the final Vina candidate is complete:

```text
build exact candidate SIF
        ↓
run %test
        ↓
strict Doctor
        ↓
public API submission
        ↓
Slurm CPU task
        ↓
Apptainer execution
        ↓
validate native outputs
        ↓
validate scores.csv
        ↓
validate summary.json
        ↓
validate result workspace
        ↓
write exact-runtime live receipt
```

Only the final validated candidate may be promoted.

Record its exact SIF hash and live job evidence according to current conventions.

---

# 21. Validate the Vina scientific output

Do not count only:

```text
task_finished
artifact count
```

The live acceptance must verify that:

```text
prepared receptor exists
prepared ligand exists
pose PDBQT exists
pose is non-empty
Vina score can be parsed
scores.csv contains expected row(s)
summary.json is valid
result workspace resolves required artifacts
```

The acceptance should prove the user receives a scientific docking result, not merely a successful process exit.

---

# 22. Update focused tests

Add or update tests for:

```text
two-file admission for Gnina
two-file admission for DiffDock
minimum two files for Vina
minimum two files for AutoDock-GPU

DiffDock retained ESM import
DiffDock absent ESMFold path

Gnina explicit box schema
Gnina wrapper explicit box arguments

Vina parser
AutoDock-GPU parser
Gnina parser
DiffDock parser

scores.csv generation
summary.json generation
```

Prefer parser fixtures over expensive live execution in normal CI.

---

# 23. Run the normal repository gates

Before pushing the repaired PR head, run all applicable gates.

At minimum:

```text
focused docking tests
input-schema/API tests
Doctor tests
Runner static tests
result workspace tests
browser contracts affected by input cardinality / seed UI
make test
make test-cov
strict docs
citation verification
package-content verification
Compose render
shell syntax
JavaScript syntax
git diff --check
```

Do not remove tests to avoid failures.

Do not suppress failures caused by the new contracts.

---

# 24. Reconcile the existing review threads

After implementation:

* inspect every unresolved PR #14 thread;
* verify the underlying defect is actually fixed;
* resolve threads only after relevant tests pass;
* do not mark a thread resolved merely because the code changed nearby.

Pay particular attention to the existing P1 issues:

```text
DiffDock missing ESM import
Gnina impossible two-file submission
DiffDock impossible two-file submission
```

and the Vina/AutoDock-GPU minimum-input mismatch.

---

# 25. Update PR #14 description

The PR description should no longer imply that all four Runners are equally production-ready.

Include a matrix similar to:

```text
Runner          Hardware   SIF test   Live acceptance   Readiness   Production
AutoDock Vina   CPU        PASS       PASS              READY       enable
AutoDock-GPU    GPU        PASS       DEFERRED          NOT READY   disabled
Gnina           GPU        PASS       DEFERRED          NOT READY   disabled
DiffDock        GPU        PASS       DEFERRED          NOT READY   disabled
```

State clearly:

> GPU live acceptance is intentionally deferred because the only production GPU is occupied by a long-running user workload. No readiness exception has been introduced.

Also retain:

> DiffDock accepts an explicit protein structure only and does not perform ESMFold or other sequence-to-structure prediction.

Include final exact-head CI status.

---

# 26. Push fixes to the existing PR

Commit coherent remediation changes.

Do not open a new PR.

Push to:

```text
origin/feat/docking-runner-suite
```

Confirm PR #14 updates to the exact pushed SHA.

Wait for blocking CI jobs to finish.

This CI waiting is appropriate because CI is part of the PR lifecycle and does not monopolize the production GPU.

---

# 27. Merge policy

Production redeployment must originate from an accepted `main` revision, not from an arbitrary feature branch.

Therefore:

```text
PR repaired
    ↓
review findings resolved
    ↓
exact-head CI green
    ↓
merge PR #14 if this session is authorized to merge
    ↓
fetch exact new origin/main
    ↓
redeploy production
```

If repository/operator guidance does **not** authorize this session to merge, stop production deployment at the green PR boundary.

Do not deploy the feature branch as production merely to avoid that boundary.

---

# 28. Production redeploy must enable Vina only

During the resulting production deployment, the only newly promoted docking Runner is:

```text
autodock_vina
```

The enabled/deployed Runner snapshot must not promote:

```text
autodock_gpu
gnina
diffdock
```

merely because their plugin directories exist.

Use the existing deployment-owned Runner enablement/readiness mechanism.

Do not delete the GPU Runner source definitions.

Their code remains available for future validation.

---

# 29. Preserve existing enabled Runners

"Enable Vina only" means:

> Among the four new docking Runners, only Vina is newly enabled.

It does **not** mean disabling unrelated production Runners that are already active.

The redeployed fleet should be conceptually:

```text
previous validated production Runner set
+
autodock_vina
```

not:

```text
autodock_vina only
```

and not:

```text
previous set
+
all four docking Runners
```

---

# 30. Verify the immutable Runner snapshot

The redeploy must preserve the server-instance immutability contract introduced in PR #13.

Confirm that the new running instance receives its own consistent Runner snapshot.

Do not expose mutable repository Runner metadata to the already-running instance.

Do not modify the current production snapshot before pre-stop preservation.

Use the existing safe restart/redeploy lifecycle.

---

# 31. Post-deploy Vina verification

After redeployment verify:

```text
server healthy
strict Doctor healthy
autodock_vina discoverable
autodock_vina READY
AutoDock-GPU not enabled
Gnina not enabled
DiffDock not enabled
```

Through the public product path, verify:

```text
Runner catalog
Create Task
parameter schema
receptor + ligand submission
CPU task launch
result completion
result workspace
scores.csv
native download
```

Do not submit any GPU docking task during this deployment check.

---

# 32. Verify fail-closed GPU status after deployment

Explicitly inspect Runner status for:

```text
autodock_gpu
gnina
diffdock
```

They must not be accidentally considered READY due only to:

```text
candidate SIF presence
successful build
successful %test
plugin discovery
static tests
```

The missing GPU live receipt must continue to prevent production promotion.

If any of these Runners appears READY without real target-host GPU acceptance, treat that as a **P1 readiness regression** and stop deployment work.

---

# 33. Update IMPLEMENTATION_STATE.md

Record the final state accurately.

Do not leave wording implying that GPU validation is still being actively polled.

Use a state such as:

```text
AutoDock Vina
    production accepted and enabled

AutoDock-GPU
    implementation complete
    candidate runtime built
    GPU live acceptance deferred
    production disabled

Gnina
    implementation complete
    candidate runtime built
    GPU live acceptance deferred
    production disabled

DiffDock
    implementation complete
    candidate runtime built
    GPU live acceptance deferred
    production disabled
```

Record the GPU blocker generically.

Do not record another production user's private scheduler details.

---

# 34. Future GPU acceptance is a separate operational action

When the accelerator eventually becomes available, a future session can promote GPU Runners independently.

For each Runner:

```text
inspect current main
        ↓
rebuild/resolve exact candidate if necessary
        ↓
run real GPU Slurm acceptance
        ↓
validate scientific outputs
        ↓
write exact-hash receipt
        ↓
runner-status READY
        ↓
next redeploy enables that Runner
```

Do not require all three GPU Runners to pass together.

Promotion should remain independent:

```text
AutoDock-GPU may be enabled before Gnina
Gnina may be enabled before DiffDock
DiffDock may be enabled before either
```

provided each exact runtime satisfies its own readiness gate.

---

# 35. Do not build a GPU polling daemon

This task must not introduce:

```text
background GPU watcher
hourly polling service
scheduler monitoring daemon
automatic production-user job watcher
persistent retry loop
```

`CLAUDE.md` should teach agents how to make a bounded decision.

The rule is human-scale operational reasoning:

```text
inspect
infer
one bounded recheck if uncertain
defer when long
continue useful work
```

---

# 36. Architecture principle exposed by this incident

Document the operational lesson in `CLAUDE.md` without over-expanding it:

> Scheduler visibility is not scheduler understanding.

`squeue` answers:

```text
what is running?
```

`scontrol show job` helps answer:

```text
what kind of job is this?
how long has it run?
how long may it run?
is waiting useful?
```

Agents performing production operations must use enough scheduler context to choose a strategy.

Repeated observation without a decision is not progress.

---

# 37. Non-goals

Do not include:

```text
Foldseek
new GPU scheduler
new QoS design
preemption changes
automatic cancellation of user jobs
background GPU monitoring
forced readiness
skip-live-test production override
fake receipts
sequence input for DiffDock
ESMFold integration
automatic structure prediction
central docking framework
new project/workspace system
new deployment version framework
```

Do not use this PR to solve unrelated Runner backlog items.

---

# 38. Definition of done

This continuation is complete when all of the following are true.

1. Every current substantive PR #14 review finding is fixed and its regression coverage passes.

2. AutoDock Vina, AutoDock-GPU, Gnina, and DiffDock have internally consistent input contracts.

3. Gnina uses a scientifically valid explicit docking search region rather than using the docking ligand itself as an implicit autobox reference.

4. DiffDock remains strictly structure-input-only while retaining the ESM-2 residue embedding dependency required by inference.

5. Each Runner exposes useful normalized docking results in addition to native outputs.

6. All affected candidate SIFs pass their available build-time/runtime self-tests.

7. AutoDock-GPU, Gnina, and DiffDock remain fail-closed because real GPU live acceptance has not occurred.

8. No GPU readiness bypass, fake acceptance evidence, or temporary production exception exists.

9. AutoDock Vina passes target-host CPU acceptance using the final candidate runtime and final scientific output contract.

10. PR #14 exact-head CI is green.

11. `CLAUDE.md` requires agents to inspect `scontrol show job` and reason about long production tasks before waiting for shared accelerators.

12. An unclear blocking job receives at most one ten-minute delayed recheck before a defer/continue decision is made.

13. An obviously long task such as production MD causes GPU-dependent validation to be deferred immediately for the current delivery rather than repeatedly polled.

14. No production user's running job is cancelled, requeued, preempted, reprioritized, or otherwise modified.

15. The production redeploy, when authorized and performed from merged `main`, preserves the existing validated fleet and adds **AutoDock Vina only** among the new docking Runners.

16. AutoDock-GPU, Gnina, and DiffDock remain present in source but disabled in production.

17. The new production instance uses the existing immutable Runner snapshot lifecycle.

18. Post-deploy checks prove Vina is usable and the three GPU docking Runners have not been accidentally promoted.
