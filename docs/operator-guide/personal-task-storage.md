# Personal Task Storage and Artifacts

Every task belongs directly to the authenticated user who submitted it. The
task row records `submitted_by_user_id` for authorization and snapshots the
user's immutable `storage_key` for physical storage. Usernames are display
metadata and renaming an account does not move or reassign existing tasks.

Task outputs and immutable input snapshots use these trees:

```text
results/users/<user-storage-key>/tasks/<task-id>/
workspaces/users/<user-storage-key>/tasks/<task-id>/
```

The server derives both identities from authentication; clients cannot select
an owner or storage key. Ordinary users can read, cancel, or delete only tasks
whose `submitted_by_user_id` matches their user ID. Existing administrator
task visibility remains independent of filesystem paths.

Finished-task artifacts are published through `manifest.json`. Retrieval
validates the logical path, confinement, regular-file status, SHA-256, and size
before exposing content. The finalized manifest's own digest and size are
recorded in server-owned task state at finalization, and every retrieval checks
the on-disk manifest against that record first, so a manifest replaced after
finalization is refused rather than trusted as a new publication. A user may
reference an artifact from another one of their finalized tasks with
`@<task-id>/<logical-path>`. The server verifies the manifest entry and copies
an immutable downstream input snapshot; execution never reads a mutable upstream
result path. Provenance records the source task, logical artifact path, digest,
size, media type, and timestamp without carrying authorization state.

## Result publication states

Publication is one transition: the manifest anchor is recorded in server-owned
state before the manifest becomes visible at its canonical path, and the task is
not reported finished until both have happened. A publication whose anchor could
not be recorded is refused — no `manifest.published` event, no finished task, and
a retry publishes normally. Every read reports a bounded state:

| State | Meaning |
| --- | --- |
| `available` | The published manifest is readable and is the one Core published. |
| `not_finalized` | Nothing has been published for the task yet. |
| `unanchored` | A manifest exists with no anchor row — a result finalized before publication identity was recorded. |
| `anchor_mismatch` | The manifest bytes changed after publication. |
| `manifest_missing` / `manifest_unreadable` | A publication whose bytes are gone, or are no longer an ordinary readable file. |
| `anchor_invalid` | The recorded publication identity is malformed. |

`unanchored` is the state of results that predate this anchor. They are
quarantined and reported with their reason — through the task status payload and
the results endpoint's refusal — rather than silently disappearing, and they are
**not** re-anchored from the result tree: that tree is exactly the namespace the
anchor exists to stop trusting. The trusted way to publish such a result is to
run the task again.

Run `revocompute publications --quarantined` to list them, and
`revocompute publications --json` for the full classification. The worker also
classifies every terminal task at startup, logging and emitting
`manifest.publication_quarantined` for each quarantined result. Reconciliation
only reports; it never writes an anchor.

## Persistent-state epoch

The personal-task schema is intentionally a fresh pre-production epoch. It has
no database migration, legacy ownership columns, or fallback storage paths.
Before adopting this epoch, stop REvoCompute and perform a one-time manual
reset of the development user/task databases and old workspace/results roots.
Also archive or delete the retired `${SERVER_DIR}/collaboration.sqlite3` while
the service is stopped. Project, member, and invitation rows are not converted
into personal-task state.

Startup rejects incompatible user/task state before creating or changing
schema objects. It does not open, validate, migrate, or delete the retired
collaboration database. Ordinary restarts with current personal-task state are
non-destructive. Do not reintroduce a compatibility reader or placeholder
collaboration database.
