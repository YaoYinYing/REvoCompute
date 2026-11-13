# Task Lifecycle State

`tasks.status` is the single authority for what may still happen to a Task.
`revocompute/task_state.py` names the vocabulary once — the states, the groups
consumers actually mean, the legal transitions, and the disposal lanes — and
`TaskDatabase` enforces the transition on every guarded write. No other module
spells a Task status literal, except `revocompute/api_receipt.py`, whose
`TERMINAL_SUCCESS_STATUS` belongs to the receipt vocabulary and whose bytes are
hashed into checked-in acceptance receipts; replacing that literal changes the
collector identity those receipts assert.

This page is the counterpart of [Execution Stage State](execution-stage-state.md):
StageRuns describe *attempts inside* a Task, this page describes *the Task*.

## Two axes in one column

```text
pending -> queued -> running -> finished
   |         |         |- failed
   |         |         \- cancelled
   |         \-(recovery) -> pending
   \- failed / cancelled

{active, outcome} -> deleting:finished|cancel -> cleaned:*  (retention)
                                             \-> deleted:*  (user deletion)
```

The execution axis decides the outcome. The disposal axis retires a Task that
has an outcome, or one the user abandons while it is still live. Disposal is
never entered from `deleting:*` in the other lane: the lane is a property of the
outcome the Task had.

`deleted:finshed` is a durable wire value that predates this contract. It stays;
the correctly spelled `deleted:finished` is not a state.

## Groups

| Group | Members | Means |
| --- | --- | --- |
| `ACTIVE` | pending, queued, running | still live; cancellable |
| `EXECUTING` | queued, running | a scheduler allocation is expected |
| `OUTCOMES` | finished, failed, cancelled | the outcome is decided; only republication may promote failed |
| `DISPOSAL_CLAIMS` | deleting:* | a retire owns the artifacts |
| `DISPOSED` | cleaned:*, deleted:* | artifacts are gone; the row is audit |
| `SETTLED` | outcomes, claims, disposed | the run is no longer executing |
| `LOCKED` | cancelled, claims, disposed | no field write may target the row |
| `POLLING_COMPLETE` | outcomes, disposed | clients stop polling |
| `RESULT_WRITES_REFUSED` | cancelled, claims, disposed | the result tree is owned by a cancel or retire |
| `PUBLISHED_RESULTS` | finished, failed | a published result may be read |

`SETTLED`, `LOCKED`, and `POLLING_COMPLETE` are three different questions that
used to share the word "terminal": whether the run is decided, whether the row
may still be written, and whether a poller should stop. A `deleting:*` claim is
settled (its outcome will not change) but is not complete (its purge is still
running), which is why the polling set excludes it.

`finished` and `failed` are settled but deliberately absent from `LOCKED`: a
`failed` Task that recorded no allocation may be retried by resubmitting the
identical content, and a failed run may be promoted once its result is published.

## Transitions

```text
pending   -> queued, running, failed, cancelled, deleting:cancel
queued    -> pending, running, finished, failed, cancelled, deleting:cancel
running   -> pending, finished, failed, cancelled, deleting:cancel
finished  -> deleting:finished
failed    -> pending, finished, deleting:cancel
cancelled -> deleting:cancel
deleting:finished -> cleaned:finished, deleted:finshed
deleting:cancel   -> cleaned:cancel,   deleted:cancel
cleaned:*, deleted:* -> (none)
```

Two edges look like regressions and are recovery:

- `queued|running -> pending` is the recovery claim. It takes the row out of
  the recovery scan so exactly one recoverer acts on it.
- `pending -> running` is a start observation arriving after recovery returned
  the row to `pending`. The StageRun attempt, not the Task status, decides
  whether that observation still owns the work.

`failed -> pending` is the retry of a handle-less failure, not a resurrection: a
`failed` row that still records a scheduler or container handle is reserved
before any retry can reach it. `failed -> finished` is the republication
recovery: a run that completed but could not publish its result is recorded as
failed, and the authority that republishes promotes it. A `finished` or
`cancelled` Task never moves back.

## Enforcement

Every Task write that changes status goes through one of the store's guarded
methods:

- `update_task` admits a status only from `task_state.accepted_from(target)`,
  and a field-only write only while the row is not `LOCKED`.
- `claim_task_recovery`, `claim_task_execution`, `claim_task_cancellation`,
  `claim_task_cleanup`, and `complete_task_cleanup` are compare-and-set
  predicates whose source set is the canonical group. A cleanup claim or
  completion must match the lane of the status it names.

A write that loses a race — or names an illegal transition — changes zero rows
and returns `False`; it never raises and never corrupts the row. That is why a
late allocation callback cannot resurrect a finished or cancelled Task.

## Disposal

A retire is two durable steps: the `deleting:*` claim, then one terminal state.
Retention settles to `cleaned:*` (audit row kept, artifacts gone) and a user
deletion settles to `deleted:*`. Both are hidden from history.

The claim is the crash boundary. A process that dies after claiming leaves a
`deleting:*` row, and a repeated deletion request, resource maintenance, or
retention resumes its purge through the data lifecycle, never races a live
`PURGING` claim, and settles the Task only when that lifecycle records `PURGED`;
a claim stale for `PURGE_STALE_SECONDS` is reclaimed. A purge that completed
before the process died leaves `PURGED` with its claim still in place; resource
maintenance finishes that status write without touching the removed data.
Deleting an already-`DISPOSED` Task succeeds without touching the row.

## What consumers must do

- Poll until the API's `terminal` flag is true; do not mirror the vocabulary.
- Offer cancel only for `ACTIVE`; offer delete unless the artifacts are already
  gone (`DISPOSED`). A `deleting:*` claim is offered so the request can resume it.
- Read results only from `PUBLISHED_RESULTS`, and then only when the result
  publication state says they are available.
- Write status through the store methods; never construct a status string.
