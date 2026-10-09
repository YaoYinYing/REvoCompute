# TODO — Close the Slurm job-ID reader race

## Context

This is a bounded post-#66 hotfix discovered by the exact-head #57 CI run on
`c373690054396088ac0a3b491cd9ef207344ecc5`.

Observed failure:

```
FAILED tests/test_slurm_runner.py::test_gpu_allocation_cancel_before_allocation_settles_nothing
RuntimeError: SLURM submission did not return a scheduler job ID
```

The failing test builds a fake srun process with stdout
`REVODESIGN_JOB_ID=4217\n`, empty stderr, and a still-running process.

## Root cause

`SlurmJob.submit()` starts independent stdout/stderr reader threads and waits on
`_job_id_event`.

Today, `_read_stdout()` sets that event when it parses a valid wrapper job-ID
line, but `_read_stderr()` also sets the same event in `finally` when stderr
reaches EOF while `_slurm_job_id` is still unset.

An empty stderr stream can therefore wake `submit()` before stdout has had a
chance to parse a valid job ID. The main thread then cancels the job and raises
`job_id_unavailable`.

The event currently conflates two different facts:

1. identity is known;
2. one candidate input stream ended without identity.

Only (1), or exhaustion of both candidate streams with no identity, may release
the wait early.

## Required invariant

- a valid job ID from either stdout wrapper evidence or the trusted srun stderr
  banner wakes `submit()` immediately;
- EOF of only stdout or only stderr never proves identity is unavailable;
- when both stdout and stderr readers are exhausted and no ID was parsed,
  `submit()` may fail immediately;
- if one/both streams remain open without yielding identity, the existing bounded
  timeout remains the fallback;
- queued stderr job identity remains identity only, never allocation-live
  evidence;
- allocation accounting, reservation, cancellation, and wrapper-gate semantics
  remain unchanged.

## Implementation

Use the smallest explicit reader-completion state.

Preferred shape:

- add one small synchronization helper/state owned by `SlurmJob`;
- each reader records its own completion in `finally`;
- the helper sets `_job_id_event` for an unsuccessful search only after both
  readers are complete and `_slurm_job_id` is still unset;
- parsing a valid ID keeps setting `_job_id_event` immediately as today.

Do not use sleeps, retry loops, polling the thread scheduler, or process timing
as correctness. Do not weaken the existing 5-second upper bound.

## Deterministic regression

Add a test that forces the failing ordering rather than hoping the scheduler
reproduces it:

1. stdout contains a valid `REVODESIGN_JOB_ID=4217`, but its first
   `readline()` is held behind a test-controlled barrier;
2. stderr reaches EOF first;
3. prove `submit()` has not failed merely because stderr ended;
4. release stdout;
5. prove `submit()` returns `4217`.

Use `threading.Event`/barriers or an equivalent deterministic synchronization
primitive. Do not use timing-only sleeps as the proof.

Also preserve/add coverage for:

- valid ID from stderr while stdout has not produced one;
- both streams exhausted without an ID -> bounded failure and srun termination;
- stdout ID + empty stderr -> success;
- queued stderr banner still does not claim allocation-live state;
- cancellation before allocation-live still settles no allocation;
- repeated `cancel()` remains idempotent.

## Validation

At minimum:

```bash
python -m pytest -q \
  tests/test_slurm_runner.py::test_gpu_allocation_cancel_before_allocation_settles_nothing \
  tests/test_slurm_runner.py::test_submit_rejects_unparseable_scheduler_id_and_terminates_srun \
  tests/test_slurm_runner.py::test_a_queued_stderr_banner_never_claims_an_allocation
```

Then run the complete `tests/test_slurm_runner.py` file and the repository's
required exact-head CI.

Because this is scheduler/core code, do not waive a failing full server/contract
gate merely because the focused race test passes.

## Scope boundaries

Do not:

- modify MCP code or #57;
- redesign Slurm accounting;
- change allocation-live semantics;
- change GPU count parsing;
- change scheduler-evidence reconciliation;
- change cancellation policy;
- add sleeps/retries as a race workaround;
- broaden this PR into scheduler placement or resource-policy work.

## Merge contract

The final PR must contain only the production synchronization fix, deterministic
regression(s), and any minimal comment/doc adjustment required to explain the
invariant.

Delete this `TODO.md` before final review.

Return the exact final head with focused-test and exact-head CI evidence. Do not
merge; maintainer final squash-merge authority remains unchanged.
