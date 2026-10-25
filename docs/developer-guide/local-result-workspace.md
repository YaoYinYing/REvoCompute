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
supplies only what the Server adds at serve time: `terminal: true`,
`error: null`, an empty archive record, per-artifact and per-logical-file
`blob:` URLs, and the literal Task identity `local`.

The archive carries no lifecycle status, and the folder does not invent a
`finished` one: the Server writes `output_check.state: not_assessed` exactly
when the run itself failed, so that state is projected as `failed` and any
other is `finished`. A logical file's renderer capability is re-derived from
its declared `type` with the Server's own projection rule, because the archived
record inherited an extension-guessed capability that the Server replaces when
it serves the same manifest.

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
schema version 3 and at most 8 MiB, and one selection holds one result: the
manifest is taken from the folder that holds it, a manifest nested deeper is
not opened, and two manifests at the same depth are refused as ambiguous.
Picking a directory *above* the result folder is refused too — the declared
paths are relative to the manifest's own folder, so every one of them misses.

Every path a view can reach must be present and match its declared size, and
every such file at or below 8 MiB must also match its declared SHA-256. That is
the union of `manifest.artifacts` and the logical files under `result.files`,
and a path both lists name must satisfy both records. A refusal names the
differing paths, up to five plus a count. Files past the hash budget — and every
file where the browser has no `crypto.subtle`, as on a non-secure origin — are
reported as checked by size only, so the page never overstates what it checked.

Verification is a single pass when the folder is opened. A view then reads the
file it was handed: the text readers bound its size against the size declared
here, and the bounded table reader holds the same row, column and page-byte
ceilings as the remote path. Neither re-hashes per read.

The chooser itself is gated by a browser contract. It selects a real extracted
folder from disk through the page's own `input[webkitdirectory]`, so the browser
produces each `webkitRelativePath` rather than the test stubbing one; it asserts
the declared matrix and entity-table views render from the folder's bytes under
the production CSP, including `connect-src 'self' blob:`; and it asserts the page
made no request to `/compute/api/results`. Selecting the result folder directly
opens it, while selecting one level above it is refused with the missing declared
paths.

### Transport

- Each declared path becomes one `blob:` object URL created from the reader's
  own file; no copy is uploaded, and every URL is revoked when the workspace is
  closed or the page is left.
- A download control points straight at that handle. The Server's `?download=1`
  flag means nothing to a `blob:` URL, and Chromium cancels a download whose
  blob URL carries a query, so a local download is the bare handle.
- A `blob:` handle carries no filename, so each local download control names the
  file itself in its `download` attribute; a Server route keeps relying on its
  own `Content-Disposition`, whose filename is the artifact's basename.
- Nothing in the folder is imported, evaluated, navigated to or framed. An
  archived HTML report stays download-only, as it is for a remote result.
- A citation becomes a link only at an absolute `https:` address, or at the
  `https://doi.org/` locator derived from its DOI. Any other scheme a folder's
  manifest names is shown as plain text, so a crafted archive cannot hand a
  reader a click-to-execute address inside this origin.
- Shared table views read the local file through the bounded local reader in
  `table-page.ts` (same row, column and page-byte ceilings as the remote path).
  Because the file is untrusted bytes rather than a Server-parsed page, the
  16 KiB cell ceiling and the column ceiling are enforced while a field and a
  row are accumulated, and a row the page skips by `offset` is checked too: a
  single oversized cell, or an unterminated quoted field that never ends, is
  refused as soon as the field passes 16 KiB rather than being buffered whole.

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
- The directory-chooser browser contract runs the repository's Chromium; another
  browser's `webkitdirectory` implementation is not exercised.
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
