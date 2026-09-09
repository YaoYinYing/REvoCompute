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
before exposing content. A user may reference an artifact from another one of
their finalized tasks with `@<task-id>/<logical-path>`. The server verifies the
manifest entry and copies an immutable downstream input snapshot; execution
never reads a mutable upstream result path. Provenance records the source task,
logical artifact path, digest, size, media type, and timestamp without carrying
authorization state.

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
