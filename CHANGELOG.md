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
