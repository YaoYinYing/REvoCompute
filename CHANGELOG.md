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
    - Pin the existing Task Snapshot submit rail to the visible viewport bottom,
      respecting safe-area insets, the mobile visual viewport, and reduced
      motion, without adding a second submit control.

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
