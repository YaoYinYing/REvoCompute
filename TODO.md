# REvoCompute Experience & Release Governance Campaign — TODO

This document is the **execution checklist** for the 2026-11-12 Campaign.
It is not a claim that tasks are implemented. Normative design: docs/developer-guide/experience-modernization-campaign.md and docs/developer-guide/release-governance.md. User intent: ORIGINAL_DESIGN.md.

Starting point (2026-11-12): main 2890609942680e29ce17b3d83f546569434c5247; zero open PRs when inspected. Re-fetch current main, open PRs, exact heads, CI and review threads before every new child PR or merge review.

## Campaign rules

- [x] Read existing main and verify repository baseline; do not equate static 0.1.0 package metadata with a released product version.
- [x] Record complete user intent and versioning proposal.
- [ ] Commander loads current branch and PR discussion, delegates bounded implementation and keeps the independent Adviser active.
- [ ] All subsequent PRs start from an explicitly checked base and have one owning workstream. Avoid a single monolithic feature PR.
- [ ] Every technical finding lives in its owning PR thread. The commander summarizes merge/no-merge, blocker category, owner, independent review state and exact head evidence.
- [ ] Maintainer performs final squash-merge decision for every PR. Merge, tag, release and production deployment are four separate decisions.
- [ ] Every user-visible feature has accessibility checks, negative tests, release-note disposition and (for UI work) before/after screenshots.
- [ ] Update this campaign checklist as each child PR actually merges; do not check off items merely because a design was approved.

## PR-0 — Release Governance (start first; this Draft Campaign PR provides its design)

- [ ] Keep pyproject.toml version as the one editable application version; validate SemVer and explicit development/pre-release semantics.
- [ ] Provide deterministic sync/check for frontend/package.json and frontend/package-lock.json; no separate manually edited version source.
- [ ] Add regression tests that deliberately desynchronize each frontend version and prove CI rejects both.
- [ ] Implement immutable full build-time Git SHA, historical development display version `0.1.0+<SHA[:7]>`, and safe missing-revision state; maintain base `0.1.0` in packaging until a formal release is approved.
- [ ] Backfill `CHANGELOG.md` from merged Git history at the verified main snapshot `2890609` with only high-information user-facing milestones. Preserve historical commit-derived versions without inventing prior tags or release dates.
- [ ] Implement authenticated `GET /compute/api/version` for signed-in regular users and admins with build metadata and bounded changelog content; reject anonymous/invalid/expired credentials without leaking data.
- [ ] Implement dedicated login-protected `/compute/version` frontend AND server route, reachable from signed-in navigation, with direct refresh/deep link support, history, and accessible dark/mobile layout.
- [ ] Test authenticated API/page route parity, unauthenticated redirects/401, stale session, response cache/privacy, Markdown safety and return-to-login behavior.
- [ ] Check the version API and page against the same immutable frontend/backend build SHA; present mixed or unknown build identities explicitly.
- [ ] Ensure built frontend/backend identities match; test mixed/stale assets without corrupting normal page load.
- [ ] Add OCI labels or the nearest existing deploy image equivalent; no new version registry.
- [ ] Confirm Keep a Changelog **1.0.0** (not 1.1.0), dated version headings, standard change categories, and version comparison links; reuse REvoDesign `docs/agents/RELEASE.md` module-scoped terse bullet style.
- [ ] Preserve original user-facing `Unreleased` workflow; use an explicit, stage-safe release-cut process adapted from REvoDesign without silently pushing tags.
- [ ] Do not invent historical **formal releases**; source-derived `0.1.0+<SHA7>` snapshots and their curated baseline are not official release tags.
- [ ] Introduce a release tag gate for vX.Y.Z (optional prerelease), exact metadata equality and changelog section existence; evidence tags remain separate.
- [ ] Document explicit manual release and rollback procedure, including deployment SHA, image digest and existing Runner provenance separation.
- [ ] Run API contract, server unit and frontend build tests at exact head. Document failed checks truthfully.
- [ ] Obtain independent architecture review and maintainer approval before merging. No automatic tag/release/deploy.

## PR-1a — Response and upload transport compression

- [ ] Benchmark current API and structure-response wire bytes/latency under a repeatable throttled network profile.
- [ ] Introduce selectively negotiated ingress response compression; preserve caching, ETag/Vary and range semantics. Never compress precompressed binary data on principle.
- [ ] Specify one narrowly scoped upload request-compression capability with client/server negotiation and backward-compatible uncompressed API.
- [ ] Implement adaptive browser-side gzip where worthwhile, preserve original filename/format and give upload progress/cancel feedback.
- [ ] Reject malformed encodings, double compression, compressed-body expansion abuse, size/time/disk budget violations, and inconsistent digests.
- [ ] Verify exact original SHA and upload authorization/preflight/immutable input validation equivalence for compressed vs identity uploads.
- [ ] Test browser without CompressionStream, offline/cancel/racing upload and large incompressible XTC fallback.
- [ ] Capture before/after transfer sizes and CPU/wall-time; do not claim performance improvement from unit tests alone.

## PR-1b — Resumable and shareable artifact download

- [ ] First capture existing GET Range/206/416 behavior and test gaps instead of rewriting an already functional range path.
- [ ] Add/verify HEAD, Content-Length, ETag, If-Range and byte-exact 206/416 semantics, including independent and parallel Range requests.
- [ ] Design bounded artifact-scoped signed bearer URL issuance with expiry, access check, revoke/regenerate path and audit trail.
- [ ] Ensure IDM-compatible unauthenticated GET/HEAD works until expiry while other APIs stay protected.
- [ ] Validate no query-token leakage via logs/referrer/caches/analytics, safe filename handling, no symlink/path escape, and invalidation after deletion.
- [ ] Test token tampering, expiry, revoked task, multiple ranges, partial retry, slow transfer, missing artifact and concurrent deletion.

## PR-2 — Mol* viewer interaction and presentation contract

- [ ] Audit input MolecularViewer and result viewer-contract/structure-controller; merge capabilities without breaking trajectory or structure plugins.
- [ ] Define typed authored atom/residue identity, topology revision, crosshair XYZ (Angstrom), selection, box center+dimensions and change events.
- [ ] Implement set-zero and whole-structure-COM initialization; distinguish COM from geometric centroid.
- [ ] Test atom subsets, mass availability, altloc/insertion code, empty selection, unit/frame correctness and controlled two-way updates.
- [ ] Make normal/expand/maximize modes reuse one viewer state; ensure WebGL lifecycle and cleanup.
- [ ] Verify keyboard, focus trap/restore, reduced motion and mobile/tablet/desktop layout; save screenshots.

## PR-3 — CAVER input form integration (requires PR-2)

- [ ] Audit pinned CAVER 3.0.2 accepted include/exclude directives; never expose unsupported options in a schema.
- [ ] Verify start_group vs start_residue_number behavior against runner code and browser; no duplicated fields.
- [ ] Bind current CAVER seed to common seed control and preserve deterministic task submission.
- [ ] Expose atom, residue, group, ligand and manual XYZ via shared molecular picker, with authored source identities.
- [ ] Populate residue names from current structure, invalidate on file change and refuse ambiguous/invalid mappings.
- [ ] Add supported include/exclude residue IDs/names/atom numbers, full typing and config validation.
- [ ] Compare generated Runner config/provenance and snapshot selection to UI, including rejection tests for chainless/insertion-coded/altloc cases.

## PR-4a — Task history search and incremental loading

- [ ] Define authorized task list query, server-side search/filter/sort, stable cursor, bounded page size and precise tie breakers.
- [ ] Ensure search applies to the full authorized dataset before pagination, with no matches skipped by client-only filtering.
- [ ] Provide incremental page loading, request cancellation, loading/error/empty states and bounded DOM footprint.
- [ ] Keep live status refresh independent from historical pagination; choose bounded polling or SSE based on measured need.
- [ ] Test permission filtering, duplicate timestamps, concurrent status changes, stale cursor, fast search typing, network failure and mobile UI.

## PR-4b — Clone & Reuse, placeholders and persistent submit

- [ ] New draft rehydrates compatible parameters from one authorized existing Task, never mutating source.
- [ ] Compare old and current Task schema, parameter name/type/enum/ranges, file roles, input permissions, resource entitlements and current constraints.
- [ ] Show incompatible/missing values in a visible warning with explicit revalidation; never silently reuse old defaults or inaccessible inputs.
- [ ] Add schema-owned optional example placeholder distinct from default/required input validation; update API client types only from OpenAPI.
- [ ] Make submit control viewport-bottom sticky with desktop/tablet/mobile safe area, keyboard and validation/error visibility.
- [ ] Test two-way navigation, empty placeholder, all incompatible cases, preview screenshots and keyboard-only submission.

## PR-5 — MD topology/trajectory conversion Tool (depends on trusted upload boundary)

- [ ] Audit exact supported parser/writer combinations for GRO+XTC, Amber, CHARMM/NAMD, LAMMPS and OpenMM. Do not promise every pairing.
- [ ] Implement a bounded, isolated Tool that takes topology plus trajectory and validates atom count/order/identity, frame limits, units and PBC handling.
- [ ] Enforce <=100 MB original/decompressed trajectory input with independent CPU/disk/frame caps; decompress size is authoritative.
- [ ] Generate consistent PDB snapshots for CAVER according to its actual runner input contract; preserve order, frame times and provenance.
- [ ] Reject malformed/ambiguous conversions and expose clear, actionable errors without arbitrary user shell commands.
- [ ] Compare converted frames against reference trajectories on representative fixtures and record scientific constraints.

## PR-6 — Trajectory visualization fit and export (requires PR-2)

- [ ] Inspect current Mol* binary trajectory loader, stage and playback before extending the viewer contract.
- [ ] Provide selected-atom alignment with reference frame, Kabsch rigid fit and explicit PBC/weight semantics.
- [ ] Apply only local browser preview transforms, allow reset, preserve immutable source artifact.
- [ ] Bound client memory and main-thread work, add progress/cancel and test alignment numerics on small fixtures.
- [ ] Export an actually supported preview trajectory format; do not label a PDB export XTC/DCD.
- [ ] Capture UI screenshots and compatibility checks across browsers.

## Campaign completion / release

- [ ] Every implemented PR contains exact-head test evidence and relevant release-note disposition.
- [ ] All blockers in canonical PR threads resolved, independent Adviser review remains documented.
- [ ] Changelog Unreleased is complete for approved user-facing behavior.
- [ ] Explicit release-cut PR selects version; tag and GitHub Release happen only after release gates.
- [ ] Maintainer separately approves production deployment; verify build identity, rollout and rollback.
