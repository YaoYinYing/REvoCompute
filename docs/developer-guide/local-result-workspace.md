# Local Result Workspace — PR #86 Campaign Design Record

> **Status: planned/authorized Campaign — not yet implemented or deployed.**
> The earlier documentation-only parking decision is superseded by PR #86's
> maintainer-directed Campaign. Result deletion, quota semantics and production
> promotion remain separate decisions.

This proposal targets the **post-PR #104 Result Workspace**. See the branch's
temporary root `TODO.md`, [Single-PR Campaign Protocol](../agents/single-pr-campaign.md)
and [Evidence Retention](evidence-retention.md). The remote ResultManifest v3,
Task Storyboards and shared renderers are not automatically portable to a ZIP.
A local ZIP is untrusted; it never inherits server publication authority.

## User need

A user wants to conserve their personal **server storage quota** without
losing the ability to inspect a previously completed scientific result.

The intended sequence is:

1. Finish a REvoCompute Task and inspect its results as usual.
2. Download a complete archive of the task's published results.
3. Extract the archive into a folder on their own computer.
4. After validating their local copy, optionally delete the server-side task
   artifacts to recover quota, subject to the actual server deletion policy.
5. Return to the REvoCompute **Result page**, select the extracted local
   result folder, and continue browsing scientific data without uploading it.

**Product promise to investigate:** result inspection should not require the
server to retain an extra copy of an already downloaded result.

This is a **local result source for the existing Result Workspace**, not a
second scientific results application.

## Intended experience

- Offer a clear **Open local result folder** entry point in or alongside the
  normal Result Workspace.
- The user grants access to an extracted folder through a browser picker.
  Reading local artifacts should be browser-local: no silent upload or
  server-side reimport.
- Render scientifically meaningful artifacts through the same result display
  concepts: structures (Mol*), tables, plots, matrices, text, associated
  files/diagnostics, and provenance where those artifacts are present.
- A result with a supported Runner storyboard should retain useful scientific
  selection/linkage (for example, choosing an fpocket pocket should identify its
  spatial location and relevant residues in the molecule), provided the
  required data and a **trusted local-capable renderer** exist.
- Indicate clearly whether the current result source is **Remote** or
  **Local**, and distinguish missing local files from server-side failures.
- A user can inspect and dismiss a local result without creating a new Task or
  consuming a Runner/SLURM allocation.
- Do not claim that a local folder will remain accessible after browser
  reloads, permission revocation, or deletion of local files.

## Proposed architectural direction (non-binding)

Separate **result interpretation/presentation** from **artifact transport**.

```text
                 Result Workspace
              ┌──────────┴───────────┐
       Remote Result             Local Result
       authenticated API         user-selected folder
              └──────────┬───────────┘
             Result/Artifact Resolver
                        │
             manifest + approved views
                        │
     Mol* / tables / plots / storyboards / provenance
```

A source-neutral artifact resolver could expose bounded read operations
and logical artifact identities to existing view/rendering interfaces, while
preserving different trust and lifecycle guarantees for remote and local
sources.

This is **not** authorization to execute arbitrary local Storyboard JavaScript
or to treat imported metadata as server-authorized publication. Keep untrusted
result content distinct from executable renderer code and server-owned policy.

### Portability contract to investigate first

The existing server result tree has `manifest.json`, while the user-facing
asynchronous ZIP is described as containing **manifest-published files**.
Before promising that existing downloaded ZIP files are self-contained, audit
what is actually in a ZIP and what the current Result page requires.

A portable local archive may need:

- a stable, versioned, self-contained result/metadata manifest;
- logical-to-relative artifact mappings that do not depend on authenticated
  URLs or server task IDs for file reads;
- file size, media type, and SHA-256 identities where supported;
- sufficient Runner/result-view metadata to render the scientific result;
- a compatibility/fallback policy for older and incomplete archives.

Prefer compatibility with **already downloaded and extracted archives** when
the authentic content permits it. If portable metadata is missing, specify an
explicit migration/export solution rather than inventing identifiers or data.

### Security, privacy, and resource boundaries

- Treat **every local archive as untrusted**, including manifests, path names,
  molecular structures, tables, and viewer configuration.
- Reject traversal, absolute-path escape, ambiguous file identities, and
  mismatched content; verify declared sizes/digests where possible.
- Never load executable scripts, active HTML reports, or arbitrary local
  Storyboard modules merely because they appear in an imported folder.
  Prefer application-shipped, versioned, allowlisted scientific renderers.
- Bound browser memory use, parsing, rendering, and large-file reads. Keep
  fallback file inventory / non-executable download access when viewers fail.
- Do not send local scientific data to the server, analytics, or third parties
  without explicit, separately scoped user action and disclosure.
- Do not let a local result impersonate a server-published task, override
  account entitlements, or inherit privileges from the server's result APIs.
- Respect browser file-access permissions and provide a fallback based on
  supported file/directory selection capabilities where available.

### Quota and deletion relationship

Local browsing and server quota reclamation are related but **separate**
product capabilities.

A future safe flow may offer local archive integrity checks before an explicit
server deletion action. Validation cannot guarantee that the user's local disk
or backup will remain reliable, and must not imply such a guarantee.

Decide separately what deleting server-side artifacts does to Task metadata,
result links, downloads, provenance, and quota accounting. No deletion
semantics are changed by this requirement record.

### What “offline” means

Two capabilities must not be conflated:

1. **Local-source preview** — the REvoCompute page has been loaded; result
   artifacts are read from a user-selected extracted folder, without a
   subsequent artifact fetch from the server.
2. **Fully offline application** — the page itself starts or remains available
   without network access, including its app shell, scientific viewers,
   dependencies, and compatible renderer modules.

**Local-source preview is the primary requirement.** Fully offline
application delivery (e.g., packaged client or carefully scoped service-worker
cache) is a separate future decision, not a promise of this document.

### Archive JavaScript and HTML stay inert

A local folder is bytes, not code. Nothing in it is imported, evaluated,
navigated to, or framed: the trusted Storyboard module stays deployment-owned,
and an archived HTML report is only ever offered as a download link.

### Measured CSP prerequisite

Reading local artifacts goes through the shared renderers, which `fetch()` the
`blob:` URL a local file is exposed at. Measured in the repository's Chromium:
the app CSP in `revocompute/app.py` had `default-src 'self'` with
`img-src 'self' data: blob:` and `worker-src 'self' blob:` but **no
`connect-src`**, so a `fetch()` of a `blob:` URL fell back to `default-src` and
was blocked, while `<img src=blob:>` already worked. The slice adds the single
directive `connect-src 'self' blob:` to that policy; no other header changes.

The page itself is served at `/compute/local_results`, one explicit Flask route
beside `/compute/quota` that returns the same inert frontend entry behind
`login_required`. It carries no server state: the folder is chosen in the
browser and nothing about it reaches the server.

## Campaign delivery and independent review

Commander captures two real downloaded ZIPs (structure/trajectory and table-
linked scientific result) before source-adapter design. Owners implement only
against the observed archive/manifest paths and trust boundaries; the Adviser
and Examiner roles and the mandatory Acceptance Auditor PASS are defined once in
the [Single-PR Campaign Protocol](../agents/single-pr-campaign.md). The
maintainer alone decides merge and deployment.

## Campaign acceptance questions

The current authorized Campaign must demonstrate:

1. Opening an authentic extracted REvoCompute result archive in the normal
   Result Workspace, using browser-local files without reupload.
2. Verifying artifact identity, sizes, and hashes; handling a missing, modified,
   malicious, or unsupported artifact with an explicit diagnostic.
3. Rendering at least a representative molecular result plus a linked
   table/selection use case from the same result without server-side
   computation.
4. No unauthorized script execution and no local-to-remote data leakage.
5. Clear Remote/Local source indicators, fallback rendering, and permission
   recovery, including large result sets.
6. Actual ZIP compatibility and behavior when portable manifests,
   storyboards, or scientific artifacts are absent.
7. Server quota and deletion behavior remaining unchanged unless a **separate**
   reviewed feature explicitly modifies it.
8. Explicitly testing browser availability/reload behavior rather than
   claiming “fully offline” on the strength of a local file picker alone.

## Implementation boundaries

This Campaign is separate from Daylight Bench art-direction work.
Implement a small vertical slice only after real ZIP feasibility and the
local-file threat model; no automatic server deletion or fully offline app.

## Deferred (P2)

Accepted limitations; none is a promise of a later slice.

- Storyboards for a local result need an app-bundled, versioned, allowlisted
  renderer module; archive JavaScript is never executed.
- Local ndarray projections await a bounded browser-side reader design.
- Candidate FASTA has no decided 1 MiB bound.
- One structure stage at a time: the workspace keeps a shared
  StructureController.
- Restoring a prior Storyboard selection is not designed for local sources.

Related current documentation:

- [Results](../user-guide/results.md) — existing manifest, ZIP, and viewers
- [Result View Plugin Contract](result-view-plugins.md) — rendering and trust
  boundaries
- [Input and Result Workspace Design Record](input-result-workspace.md) —
  historical workspace architecture
- [Personal Task Storage and Artifacts](../operator-guide/personal-task-storage.md)
  — server storage and artifact publication guarantees
