# Changelog

All notable changes to REvoCompute will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
for **future formal releases**.

This repository previously did not have formal application releases. Historical development
builds are identified as `0.1.0+<commit[:7]>`; the historical entry below documents
the source snapshot, **not a tagged release or deployment**. Build identifiers for
other historical commits are derived from their own Git SHAs, without assigning
invented release numbers or dates.

## [Unreleased]

### Added
- MD trajectory conversion Tool:
  - Add the opt-in `mdconvert` Tool family: one GROMACS GRO topology and one
    XTC trajectory become a CAVER reference PDB plus at most 50 ordered
    single-model snapshots and a `conversion_manifest.json`.
  - Pin MDAnalysis 2.9.0 and every dependency wheel by exact version and hash
    in the family's isolated image; do not install that stack into the Server
    or a Runner SIF.
  - Record source digests, parser identity, the GRO nm-to-Angstrom unit
    contract, atom map, selection, original frame times, unit cells, periodic
    treatment, warnings and output hashes. Unsupported format pairs and
    unwrapping without bond evidence are refused with typed diagnostics. GRO's
    missing chain and element identity is recorded as a warning; atoms whose
    chain/residue/atom identity would collide under PDB chain `X` are refused.
  - Add a Tool-scoped input tier: `limits.request_bytes` cannot exceed the
    deployment `TOOL_REQUEST_MAX_BYTES`, and `limits.input_bytes` bounds each
    role separately. `mdconvert`'s `tool.yaml` declares 100,000,000 decoded
    trajectory bytes, 8,000,000 topology bytes and 108,000,000 bytes in
    aggregate; those manifest-owned limits are authoritative and are projected
    by the Tool API. The Core GRO/XTC transport caps are independent limits.
    Ordinary Tools keep the 16 MiB budget.
  - Charge verified Task-artifact references to the same per-role and aggregate
    decoded budget as uploads.
  - Publish a child-declared typed failure as the Tool call's `error_class` and
    `error`.
  - Gate the mdconvert scientific and CAVER compatibility tests in CI with the
    exact hashed Tool stack.
- Task inputs:
  - Bind a finished, same-user Tool output to a declared input role through
    `tool_output_references`/`tool_output_roles`; submission checks role names,
    cardinality, file count and the server-owned declared-size quota before it
    reads any output bytes, verifies the bytes against the Tool result
    manifest, and preserves the Tool call provenance in the immutable input
    snapshot.
  - Admit server-owned Tool-output references under a separate
    `MAX_TOOL_OUTPUT_INPUT_BYTES` quota equal to `TOOL_OUTPUT_MAX_BYTES`, so a
    complete 32 MiB Tool output can reach a Task without raising the 16 MiB
    browser-upload budget. Preflight projects structured provenance instead of
    rejecting it as a string map.
- Input validation:
  - Add Core transport validators for GRO and XTC containers; scientific frame
    decoding remains in the pinned Tool parser. Deploy note: the validator
    content revision moves, so drain queued/pending submissions before
    deploying or they fail closed with `input_snapshot_mismatch`.
- Transport:
  - Accept declared per-file-part `gzip` uploads through a bounded decode path
    that validates the gzip stream, enforces encoded/decoded/per-file/total and
    expansion limits, and admits the decoded original bytes under their original
    SHA-256. Existing clients that send no declaration remain identity.
  - Advertise the per-file-part encoding contract, including the Server's
    accepted decoded/encoded expansion ratio, on the Task Type projection, and
    let the browser gzip eligible text-like PDB/mmCIF/GRO/specification files
    with an `AbortSignal` and identity fallback (including when the compressed
    ratio would exceed that Server bound).
  - Negotiate gateway response `gzip` for text-like types with
    `Vary: Accept-Encoding`, leaving 206 ranges, binary containers, archives and
    error responses uncompressed.
  - Project live scientific artifact media types (PDB/mmCIF/GRO and text-like
    structures) from one server-owned table so they are eligible for that
    compression even though the runtime image carries no host MIME database.
  - Enforce the aggregate decoded upload cap inside the shared decoder before
    an overage is written, and project the decoded original cap separately from
    the encoded body cap.
  - Deploy note: the new input-encoding reason codes move the content-derived
    `validator_revision`. Drain queued/pending submissions before deploying, or
    they fail closed with `input_snapshot_mismatch` and need resubmission.
  - Add a per-location `TOOL_CLIENT_MAX_BODY_SIZE` gateway cap for Tool calls,
    independent of the ordinary 16 MiB Task submission limit.
- Task history:
  - Server:
    - Paginate `GET /compute/api/tasks` with bounded `limit`, an opaque signed
      `cursor`, literal search, domain/date filters and submitted/finished
      keyset sorts. Visibility is resolved from the authenticated user before
      search, sort and limit, so an ordinary caller never scans another
      user's Tasks; the owner filter is administrator-only.
    - Return `{tasks, next_cursor, has_more, returned, cursor_reset, query}`
      without an unbounded complete-list default or a fabricated filtered
      total.
  - Frontend:
    - Fetch the Dashboard register page by page with 250 ms debounced search,
      request cancellation, an accessible Load more fallback and a bounded DOM.
    - Poll only visible non-terminal Tasks and reconcile their state in place,
      without re-sorting the history traversal.
    - Replace the browser regular-expression filter with plain literal search.
- Release governance:
  - Server:
    - Add the signed-in `GET /compute/api/version` projection and the
      `/compute/version` page, both behind the existing login boundary, with the
      canonical changelog parsed into bounded structured plain text.
    - Report a missing or dirty build commit as `revision_status: "unknown"`
      instead of inventing a revision, and expose the full forty-character SHA
      when one is verified.
  - Frontend:
    - Add the Version destination to the signed-in Account navigation, showing
      the display version, short and full revision, build time, release state and
      the changelog, and diagnosing mixed or stale frontend/server assets.
    - Add one typed molecular scene contract shared by the Create Task
      inspector and the Result workspace: stable authored atom/residue
      identity, immutable topology revision and source digest, Angstrom
      coordinates, stale-selection rejection, crosshair and axis-aligned box
      overlays, geometric centroid and mass-weighted centre of mass with an
      explicit hydrogen policy, and origin-tagged selection events that
      suppress form/viewer echoes.
    - Add Normal, Expand, and Maximize display modes to the one mounted
      molecular stage, with a focus trap, Escape and focus return, native
      fullscreen where available, a labelled fallback otherwise, and the
      camera, selection, trajectory frame, and overlays preserved across modes.
    - Add preview-only trajectory recentering and fitting to the Result
      workspace: weighted Kabsch rigid-body fits of a whole-frame or typed
      scene selection to an explicit reference frame, a bounded Web Worker with
      progress, cancellation and a generation token, a reversible display
      transform with raw reset, a labelled preview RMSD, per-frame
      periodic-boundary warnings that never unwrap, and a validated
      single-model PDB export with provenance sidecar metadata.
  - Workflow:
    - Make `pyproject.toml` the one editable version source, with deterministic
      `check`/`sync` for the frontend manifest and lockfile, `uv.lock` and the
      OpenAPI version, and a CI drift gate that always runs.
    - Add the `revocompute-release` release commands and a `v*` tag gate that
      reads the tagged Git tree; they never commit, tag, push, publish or deploy.
  - Build:
    - Bake the immutable commit, build time and opaque build identifier into the
      server image labels/runtime environment and the frontend bundle; a release
      build refuses a dirty tree.
- Clone & Reuse:
  - Server:
    - Add authenticated, read-only `POST /compute/api/tasks/{id}/clone-plan` and
      the owner-scoped `GET /compute/api/clone-plans/{plan_id}` reference. The
      plan resolves only explicitly recorded values against the current schema,
      reports removed/renamed parameters, unavailable enum choices, and type,
      choice, range, format, length and array-rule changes, missing roles, and
      unverifiable input snapshots by field, and never mutates the source,
      derives a Task ID, or reserves resources.
    - Record optional non-sensitive `cloned_from` provenance on submission after
      checking that the caller can see the source.
    - Validate a reviewed `x-ui-placeholder` schema annotation on optional string
      fields during Task discovery; it is presentation only and is never a
      default, required declaration, or submitted parameter.
  - Frontend:
    - Add Clone & reuse to dashboard cards and the remote Result page, opening a
      fresh draft from an opaque plan reference with a keyboard-accessible
      reconciliation panel, re-upload guidance, reset-to-defaults, and revert.
      Blocked recorded settings are shown with the recorded value and must be
      explicitly resolved (edited or kept) before the draft can run; an edited
      field is no longer reported as coming from the source, and Clear ends the
      clone relationship.
    - Pin the existing Task Snapshot submit rail to the visible viewport bottom,
      respecting safe-area insets, the mobile visual viewport, and reduced
      motion, without adding a second submit control.

### Fixed
- Tools:
  - Reclaim a submitting user's terminal workspaces when only the per-user
    storage share is exhausted, while leaving running calls and other tenants'
    terminal workspaces untouched.
  - Make workspace deletion idempotent when a concurrent reclaimer already
    removed the same call directory.
  - Translate the documented comma-separated `resid` selection form into the
    pinned parser's accepted expression grammar.
- Input validation:
  - Stop deriving the minimum XTC size from uncompressed atom coordinates;
    compressed XTC frames are now admitted under the byte cap and the pinned
    parser remains responsible for frame decompression and truncation.
- Task inputs:
  - Refuse expired Tool-output references instead of accepting them until the
    call row is physically removed.
- Documentation:
  - Retire the PR campaign DESIGN/TODO notes into the canonical Tool runtime,
    operator Tool and Task-contract pages, and point operators at the Tool API
    for the manifest-owned byte limits instead of restating them.

## [0.1.0+2890609] - 2026-11-12

Historical development snapshot of `main` at commit
[`2890609942680e29ce17b3d83f546569434c5247`](https://github.com/YaoYinYing/REvoCompute/commit/2890609942680e29ce17b3d83f546569434c5247).
The following is a curated summary of changes merged by this commit, **not** a chronological
release series.

### Added
- Server:
  - Authenticated multi-user Task execution with typed inputs, scientific result manifests, Docker/Slurm-Apptainer backends, Runner readiness checks, and permission-gated access.
  - Auditable resource accounting, GPU-credit/quota controls, admission and placement decisions, and Admin operations.
- Workflow:
  - Composable scientific stages with dependency tracking, gated Nextflow execution, and provenance-checked artifact reuse.
- Runners:
  - Broad scientific Task fleet including AlphaFold, molecular docking, CAVER tunnel analysis, Boltz-2, Mol-1, RFD4-Proteina and Proton-PottsMPNN; availability remains subject to individual readiness evidence.
- Frontend:
  - Responsive scientific workspace with Mol* inspection, schema-driven Task forms, result Storyboards, local-result preview, and failure diagnostics.
- Integration:
  - Authenticated MCP and Tool interfaces for agent-driven scientific workflows.

### Changed
- Runtime:
  - Separate Runner scientific environments from runtime execution bundles, retaining input, output, image and evidence provenance.
- Release safety:
  - Strengthen fleet contracts, stage-state transitions, and reproducible deployment/readiness verification.

### Fixed
- Security:
  - Harden uploaded input and published artifact trust boundaries, authorization, and result access controls.
- Operations:
  - Correct deployment snapshot isolation and Runner evidence attribution; improve diagnosis of failed scientific jobs.

### Removed
- AlphaFold3:
  - Remove the redundant dedicated single-sequence Task; no-MSA inference remains available through the general AlphaFold3 JSON input.

[Unreleased]: https://github.com/YaoYinYing/REvoCompute/compare/2890609942680e29ce17b3d83f546569434c5247...HEAD
[0.1.0+2890609]: https://github.com/YaoYinYing/REvoCompute/tree/2890609942680e29ce17b3d83f546569434c5247
