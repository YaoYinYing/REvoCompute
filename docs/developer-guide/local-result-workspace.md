# Local Result Workspace — PR #86 Design Record

> **Status: implemented as a bounded slice in PR #86; not deployed.** The
> earlier documentation-only parking decision is superseded by PR #86's
> maintainer-directed Campaign. Result deletion, quota semantics and production
> promotion remain separate decisions.

This record covers the **post-PR #104 Result Workspace**. See
[Single-PR Campaign Protocol](../agents/single-pr-campaign.md) and
[Evidence Retention](evidence-retention.md). The remote ResultManifest v3,
Task Storyboards and shared renderers are not automatically portable to a ZIP.
A local ZIP is untrusted; it never inherits server publication authority.

## Observed archive contract

Captured 2026-10-22 from the production API as the authorized test account:
six finished Tasks across six task types (AlphaFold 3, GREMLIN-LH, AutoDock
Vina, LigandMPNN, BioEmu, ESMDynamic), each requested through
`/compute/api/results/<id>/archive` and downloaded. In all six:

- every member is `ZIP_STORED`, and the members other than `manifest.json` are
  exactly `manifest.artifacts[*].path` — no extra files, no missing ones;
- `manifest.json` is schema version 3 and carries the serve-time-free fields
  only: `task_id`, `task_type`, `created_at`, `run`, `outcome`, `limitations`,
  `output_check`, `total_size`, `artifacts`, `views`, and an optional
  `storyboard`;
- each artifact carries `path`, `role`, `capability`, `preview`, `media_type`,
  `size` and `sha256`;
- the serve-time envelope the Result page needs — `status`, `terminal`,
  `error`, `archive`, artifact `url`/`table_url`/`ndarray_url`, logical-file
  `url`/`name`/`id`, `storyboard.entrypoint_url` — is **absent**;
- two task types declare a Storyboard (`alphafold3-result`,
  `gremlin-lh-result`) by `identifier`/`entrypoint`/`requires`/`optional`; the
  other four declare none.

Two of the six declare logical files (`result.files`: 8 and 14 entries). The
rest declare none, so their file list is the artifact list.

## What the slice does

The user need is unchanged: a reader who downloaded and extracted a result
should be able to keep inspecting it locally instead of retaining a second
copy on the server.

1. Finish a REvoCompute Task and inspect its results as usual.
2. Download the completed result ZIP.
3. Extract it into a folder on their own computer.
4. Optionally delete the server-side task artifacts to recover quota, subject to
   the actual server deletion policy (unchanged by this slice).
5. Open **Local result** in the Compute navigation, choose the extracted
   folder, and continue browsing scientific data without uploading it.

The page is `/compute/local_results`, one explicit Flask route beside
`/compute/quota` that returns the same inert frontend entry behind
`login_required`, and is named in the navigation's Compute region. It carries
no server state: the folder is chosen in the browser and nothing about it
reaches the server.

The folder is read as a **projection of the same ResultManifest v3** the Server
publishes (`frontend/src/features/results/local-source.ts`), handed to the
ordinary `ResultWorkspace` — one workspace, two sources. The projection
supplies only what the Server adds at serve time: `status: finished`,
`terminal: true`, `error: null`, an empty archive record, per-artifact and
per-logical-file `blob:` URLs, and the literal Task identity `local`.

### Identity and truthfulness

- The badge reads **Local**, and the identity line reads `<method> · <folder>`,
  so a local result is never presented as a server-published Task.
- The Task the archive was exported from is provenance only, shown in the run
  record as *Exported from task*; no route is composed for it and no server
  authority is claimed.
- The archived Storyboard is reported by **identifier only**. Its code is never
  fetched, imported or executed; the page states that the declared views below
  are shown instead of the Storyboard.

### Verification and refusals

A folder is refused before anything renders when it does not match its own
manifest. Declared paths must be relative (`/`, `\`, NUL, empty, `.` and `..`
segments are refused), two files may not share a path, the manifest must be
schema version 3 and at most 8 MiB, and the selection (or the folder it sits
in) must contain exactly one manifest.

Every declared artifact must be present and match its declared size; every file
at or below 8 MiB must also match its declared SHA-256. A refusal names the
paths that differ, up to five plus a count. Files past the hash budget are
reported as verified by size only, so the page never overstates what it checked.

### Transport

- Each declared path becomes one `blob:` object URL created from the reader's
  own file; no copy is uploaded, and every URL is revoked when the workspace is
  closed or the page is left.
- Nothing in the folder is imported, evaluated, navigated to or framed. An
  archived HTML report stays download-only, as it is for a remote result.
- Shared table views read the local file through the bounded local reader in
  `table-page.ts` (same row, column and page-byte ceilings as the remote path).

### Measured CSP prerequisite

Reading local artifacts goes through the shared renderers, which `fetch()` the
`blob:` URL a local file is exposed at. Measured in the repository's Chromium:
the app CSP in `revocompute/app.py` had `default-src 'self'` with
`img-src 'self' data: blob:` and `worker-src 'self' blob:` but **no
`connect-src`**, so a `fetch()` of a `blob:` URL fell back to `default-src` and
was blocked, while `<img src=blob:>` already worked. The slice adds the single
directive `connect-src 'self' blob:` to that policy; no other header changes.

### Accepted limitations

- A local result's Storyboard is not run: there is no app-bundled,
  versioned, allowlisted local renderer for it yet.
- Local ndarray projections await a bounded browser-side reader design.
- Candidate FASTA has no decided 1 MiB bound.
- One structure stage at a time: the workspace keeps a shared
  `StructureController`.
- Restoring a prior Storyboard selection is not available for local sources.
- This is **local-source preview**, not a fully offline application: the page
  shell and its viewers are still served by the Server, and the browser
  re-asks for the folder after a reload or a revoked permission. The page never
  claims otherwise.

### Quota and deletion

Local browsing and server quota reclamation remain **separate** capabilities.
This slice offers no deletion action, does not change what deleting a Task does
to metadata, result links, downloads, provenance or quota accounting, and does
not imply that a local disk or backup will stay reliable.

Related current documentation:

- [Results](../user-guide/results.md) — existing manifest, ZIP, and viewers
- [Result View Plugin Contract](result-view-plugins.md) — rendering and trust
  boundaries
- [Input and Result Workspace Design Record](input-result-workspace.md) —
  historical workspace architecture
- [Personal Task Storage and Artifacts](../operator-guide/personal-task-storage.md)
  — server storage and artifact publication guarantees
