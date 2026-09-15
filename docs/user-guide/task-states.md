# Task States and Result Delivery

How a task moves from submission to a published, inspectable result, and
what `finished` does and does not guarantee.

## Task lifecycle states

Current server states:

- `pending`
- `queued`
- `running`
- `finished`
- `failed`
- `cancelled`
- `deleting:finished`
- `deleting:cancel`
- `cleaned:finished`
- `cleaned:cancel`
- `deleted:finshed`
- `deleted:cancel`

Deletion is tracked in sqlite (soft-delete). Task records remain for audit/debug.
The `deleting:*` states are short-lived maintenance claims that prevent a
concurrent resubmission from reusing artifacts while cleanup is in progress.
The final `cleaned:*` states identify automatic retention cleanup; `deleted:*`
states remain reserved for explicit user deletion.
The `deleted:finshed` spelling is intentionally preserved for runtime compatibility.

## Result delivery

`finished` means `manifest.json` has been atomically published in the
uncompressed result tree. Individual manifest-listed files are previewed or
downloaded through authenticated endpoints and can be streamed by Nginx. A
full ZIP is an optional asynchronous cache created only after an explicit
archive request. It contains only files published by the manifest and is not
part of task completion.

The dedicated result page consumes scientific manifest schema version 3. Runner-owned
Expected File Trees resolve logical output identities into a task ResultContext;
trusted runner ResultStoryboards provide task-level meaning while server-owned
FileViewers provide format-level inspection and Files & diagnostics remains the fallback. The
manifest records safe run provenance, task-owned limitations, explicit artifact
roles, a technical output check, and resolved local scientific views. The output
check proves only that configured files are present, non-empty, and structurally
mappable; it does not establish scientific or experimental validity.

Legacy server-allowlisted view shapes compose unmigrated results without task-name logic
in JavaScript: candidate collections, entity tables optionally linked to a
structure, evidence bundles, alignments, trajectories, metric series, matrices,
and scalar summaries. The first primary view opens as the principal result.
Candidate and entity selection remains available for linked scientific views.
Limitations, effective parameters, input hashes,
citations, and timestamps remain available under the reproducibility record.
The living artifact and semantics audit is the
[scientific result inventory](../developer-guide/result-inventory.md).

All manifest-approved artifacts remain searchable and individually downloadable
under **Files & diagnostics**. The lifecycle-aware local file-viewer host
resolves file previews, aborts stale renders, and
preserves download as the universal fallback. Images, bounded CSV/TSV tables,
and text use local preview plugins. PDB/mmCIF files use the pinned Mol\* Viewer
5.11.0 bundle with subresource-integrity verification; if that asset or WebGL is
unavailable, the page offers a local alpha-carbon trace. pLDDT coloring is shown
only when trusted task metadata declares pLDDT in the structure B-factor field.
Native SVG/canvas renders bounded quantitative data without a plotting
dependency. XTC/DCD coordinates require an explicitly declared topology and are
transferred through the authenticated parent into the sandboxed Mol\* shell.
Inline image and structure previews retain size limits so large artifacts are
downloaded instead of loaded wholesale into browser memory.

## SLURM task states

SLURM tasks use an additional `queued` status:

- **`queued`** — `srun` is waiting for a SLURM allocation (resource contention)
- **`running`** — the allocation wrapper has started on a compute node

When the worker captures the wrapper's numeric job-ID line, it invokes the
stage callback with the first declared stage as a liveness signal. Later
`REVODESIGN_STAGE:` lines advance progress normally; a repeated first marker
is deduplicated.
