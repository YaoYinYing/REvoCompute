# Experience and Network Reliability Campaign

Status: **design / coordination**. This is the canonical scope document for the 2026-11-12 experience feedback and its single execution checklist. The original requirements and resolved terminology live in [Experience Intent](experience-intent.md). Release/versioning is specified separately in [Release Governance](release-governance.md).

## Starting point

Audited at main 2890609942680e29ce17b3d83f546569434c5247 on 2026-11-12, with no open PRs at the time of inspection:
- CAVER declares point, atom, residue, ligand and group start modes. The current frontend picker maps authored residue identity into typed CAVER fields, and the Runner resolves them against the reference PDB.
- CAVER exposes a deterministic seed; the UI needs to unify that field with the common seed control.
- CAVER configuration currently handles exclude_residue_ids, exclude_residue_names, and exclude_atom_numbers. The corresponding include fields require verification against the pinned upstream executable before any new manifest promises them.
- Mol* already exists in a frontend MolecularViewer, alongside a narrower result-view viewer contract, selection callbacks and trajectory playback. Reconcile existing adapters instead of adding a third viewer subsystem.
- Result files already have bounded, authorized readers, archive routes and range-response logic. Start by testing current behavior before adding HTTP features.
- Frontend task listing currently calls the basic GET /compute/api/tasks projection; this alone does not establish complete server-side search/pagination behavior.

The implementation agent must recheck main and exact affected files before modifying code. No deployment change is authorized by the Campaign.

## Architecture boundaries

The Presentation Plane owns viewer instances, selection overlays, responsive layout, browser-local preview transformations and request cancellation.

The Control Plane owns API capabilities, authorization, upload and publication validation, immutability, search/pagination semantics, token issuance/revocation, and typed scientific Tool dispatch.

Runner families own their Task vocabulary, scientific input constraints and output interpretation. Core cannot infer CAVER scientific behavior from a generic text field. The server remains the authority for normalized submission and its recorded provenance.

A reusable **molecular interaction contract** is shared frontend infrastructure, NOT a process-global server Mol* viewer. Server APIs exchange stable topology identities and typed selections; each browser context owns its Mol* lifecycle.

## Workstream: transfer efficiency (independent PR)

### Response compression

Configure the production Nginx ingress to negotiate gzip and optional Brotli for compressible response types (API JSON, HTML, CSS, JS, PDB/mmCIF text when appropriate). Respect Vary: Accept-Encoding, ETag/caching behavior, TLS, timeouts and buffering. Do not force-compress XTC, DCD, ZIP, images or already compressed content. Avoid transforming ranged artifact responses and avoid corrupting byte offsets. Verify real network byte savings under throttling rather than assuming a compression header implies better performance.

### **Upload transport compression**, not archive upload support

Compress eligible **request payloads in transit** in the browser; recover the exact original bytes before the existing Core input validation and immutable snapshot boundary. This is explicitly NOT a requirement to let users submit ZIP files or to store their files compressed.

Prefer a narrowly scoped, negotiated compressed-upload endpoint or equivalent explicit request-encoding contract. Existing multipart callers, preflight, API/agent uploads, authorization, filename/path validation and upload receipts must remain compatible. Do not assume Nginx response gzip handles incoming request bodies. The backend must not parse an encoded multipart body before authorized decompression.

Compress PDB, mmCIF, GRO and other text-like inputs adaptively. Bypass incompressible XTC, precompressed formats, and any payload that does not achieve worthwhile reduction. Native browser gzip support and an uncompressed fallback are sufficient to start. Respect AbortSignal and user-visible original/transferred byte progress. Check both encoded and decoded size budgets, expansion ratio, CPU/time/disk limits, trailing data, malformed streams, cleanup on cancellation, original-file SHA-256 equality and duplicate upload receipt semantics. Never permit compressed requests to bypass the normal uncompressed validation route.

### Resumable download and external-tool sharing

Audit existing byte-range support first. Complete GET/HEAD, ETag, Accept-Ranges, single and optionally multiple Range requests, 206/416 and If-Range correctness in the serving path, with compression disabled for byte-exact range responses.

Issue short-lived, artifact-scoped, integrity-protected bearer URLs for IDM and similar download managers, with an explicit expiration notice and a revoke/new-link path. A download manager needs repeatable unauthenticated GET/HEAD and parallel Range requests for the same URL until expiry. The bearer token must never be treated as user authentication for other APIs. Validate exact artifact ownership/visibility at issuance, bind the token to task + artifact identity + scope + expiration, and invalidate publication access on deletion or policy revocation. Keep query tokens out of logs, referrers, analytics and general navigation; refuse directory/path traversal. Document whether active transfers continue after token expiry and how users regenerate an expired link.

## Workstream: shared Mol* interactions and display (independent PR)

Extend the existing shared MolecularViewer and result-view adapter instead of forking them. Define typed operations and events for:
- Pick residue, atom, atom serial and stable authored chain/residue identity, including alternate location and insertion code when supported.
- Read and set an XYZ crosshair, update it from selection and move the crosshair without modifying the source structure.
- Read and set a box with center XYZ and three lengths (optional orientation only with explicit frame semantics).
- Compute geometric centroid versus true mass-weighted center of mass (COM), with clear choice of atom subset, hydrogen policy, missing mass rejection, units in Angstrom, and the reference coordinate frame.
- Initialize crosshair to XYZ zero or whole-structure COM explicitly; choose no invisible default.
- Keep input form and active viewer in two-way synchronization; prevent feedback loops, stale-selection races, leaks and mismatched structure versions.

Viewer lifecycle: **normal** (embedded), **expand** (floating near-viewport stage with backdrop blur, focus trap, preserved state and close/restore), **maximize** (actual fullscreen with supported fallback). The input structure inspector and the result stage use one shared behavior. Respect reduced motion, keyboard Escape, focus return, pointer/keyboard interactions, touch viewport and full-screen limitations on mobile Safari. Preserve WebGL canvas state and dispose resources once.

No server-global WebGL or Mol* object. The platform shares contracts, not a singleton scientific visualization process.

## Workstream: CAVER form integration (depends on Mol* contract)

- Support manual XYZ, atom, authored residue, group and ligand selections by writing only parameters declared by the owning Task schema.
- Verify group selection interacts correctly with start_group and does not falsely require start_residue_number. Group center currently represents a geometric centroid; label it accurately rather than reporting COM.
- Provide explicit ligand/residue centroid and COM selection if scientifically supported; pin and record the atom selection and point source.
- Populate residue_name choices from the currently loaded reference topology, with exact capitalization, multiple chains, ligands and structure-version invalidation. Do not hard-code ligand names.
- Audit pinned CAVER 3.0.2 syntax, precedence and compatibility for include/exclude residue IDs, residue names and atom serial numbers; implement only supported directives. Expose a clear warning/refusal for unsupported combinations.
- Bind the common random-seed widget to the existing seed property; never add a second seed field.
- Preserve error handling for chainless entries, insertion codes, altloc ambiguity and groups; retain Core validation as authority.
- Add unit, headless and Playwright tests that compare authored IDs and actual generated CAVER config/provenance.

## Workstream: dashboard and submit form (independent PRs)

### Paginated history and search

Use server-side filters/sort and stable cursor-based pagination for history. Search is evaluated over **the full authorized task collection BEFORE pagination**; never pretend already-loaded browser pages cover all matches. Define searchable fields, explicit exact/partial matching, stable sort keys with tie-breaking task ID, cursor invalidation rules, permissions and bounded page sizes. Debounce requests and cancel obsolete searches. Load pages incrementally via intersection observer or explicit Load More; avoid unbounded render trees. Separate history loading from live task-status updates (SSE only if infrastructure supports it safely, otherwise bounded polling). Never require page 1 to download every Task.

### Reuse, submit and schema hints

From dashboard and result page, Clone & Reuse builds a **new draft** from a previous Task. Compare source schema version and Task type, current parameter schema/defaults, available file roles, immutable artifact/input permission and current user entitlements. Prefill only compatible values; display all incompatible/missing values as an actionable warning and require explicit revalidation. Never infer old defaults as the current ones or copy another user's unavailable files. Do not mutate the source Task.

Allow schema-authored optional placeholder examples, distinct from defaults: empty means empty, placeholder is never submitted. Keep the submit action in a viewport-bottom sticky rail across desktop/tablet/mobile with safe-area insets and virtual-keyboard avoidance; do not obscure validation, navigation, sticky footer or accessibility focus.

## Workstream: MD ingestion and conversion Tool (depends on upload trust contract)

Accept a topology plus trajectory rather than a trajectory alone. Target an audited capability matrix for GROMACS GRO+XTC, Amber, NAMD/CHARMM DCD/PSF, LAMMPS with topology, and OpenMM outputs. A specific Tool implementation should rely on proven parsers (for example MDAnalysis) with pinned versions, not shell commands assembled from user filenames.

**Enforce 100 MB per original/decompressed uploaded trajectory** for the first release, with separate frame/atom/CPU/disk limits. A 100 MB wire-compressed body is not a way to bypass that ceiling. Detect units, atom order, topology identity, periodic boxes, discontinuities, missing atoms, frame selection and malformed data; expose conversion metadata and exact input digests. CAVER requires an ordered PDB snapshot series with consistent atom mapping and a reference structure; no generic format conversion should silently rewrite scientific identity. gmx pdb2gmx is a topology-preparation workflow, not a general trajectory converter.

The conversion Tool must produce bounded canonical outputs and immutable provenance, with an operator-controlled format adapter selected by the consuming Task. No arbitrary scripts, host paths, or untrusted plugin execution.

## Workstream: browser-local trajectory fitting (depends on shared viewer)

For a chosen atom/residue selection, temporarily center and align frames against a named reference frame using a rigid-body least-squares fit (for example Kabsch) with documented weight and PBC treatment. Clearly distinguish visual rotation/translation from molecular simulation or RMSD itself. Keep original artifact immutable and allow reset/reselect.

Bound frame count and client memory, avoid blocking the main thread, and provide progress/cancellation. Export only formats backed by a validated writer and topology metadata. If an arbitrary binary trajectory cannot be written safely in the browser, offer a PDB preview export or an explicitly labeled server Tool, not a fake XTC download.

## Execution checklist

This is the one campaign backlog. The planning Draft PR was docs-only; PR-0 is
implemented, and each later change lands as its own isolated PR starting from an
explicitly checked base. A checked box means evidence exists at the exact head,
not that a design was approved.

### Campaign rules

- [x] Read existing main and verify repository baseline; do not equate static 0.1.0 package metadata with a released product version.
- [x] Record complete user intent and versioning proposal.
- [x] Commander loads current branch and PR discussion, delegates bounded implementation and keeps the independent Adviser active.
- [ ] All subsequent PRs start from an explicitly checked base and have one owning workstream. Avoid a single monolithic feature PR.
- [ ] Every technical finding lives in its owning PR thread. The commander summarizes merge/no-merge, blocker category, owner, independent review state and exact head evidence.
- [ ] Maintainer performs final squash-merge decision for every PR. Merge, tag, release and production deployment are four separate decisions.
- [ ] Every user-visible feature has accessibility checks, negative tests, release-note disposition and (for UI work) before/after screenshots.
- [ ] Update this checklist as each child PR actually merges; do not check off items merely because a design was approved.

### PR-0 — release governance

- [x] Keep pyproject.toml version as the one editable application version; validate SemVer and explicit development/pre-release semantics.
- [x] Provide deterministic sync/check for `frontend/package.json`, `frontend/package-lock.json`, `uv.lock` and OpenAPI `info.version`; no separate manually edited version source.
- [x] Add regression tests that deliberately desynchronize each mirror and prove CI rejects it.
- [x] Implement immutable full build-time Git SHA, historical development display version `0.1.0+<SHA[:7]>`, and a safe missing/dirty-revision state; maintain base `0.1.0` in packaging until a formal release is approved.
- [x] Backfill `CHANGELOG.md` from merged Git history at the verified main snapshot `2890609` with only high-information user-facing milestones. Preserve historical commit-derived versions without inventing prior tags or release dates.
- [x] Implement authenticated `GET /compute/api/version` for signed-in regular users and admins with build metadata and bounded changelog content; reject anonymous/invalid/expired credentials without leaking data.
- [x] Implement dedicated login-protected `/compute/version` frontend AND server route, reachable from signed-in navigation, with direct refresh/deep link support, history, and accessible dark/mobile layout.
- [x] Test authenticated API/page route parity, unauthenticated redirects/401, stale session, response cache/privacy, changelog safety and return-to-login behavior.
- [x] Check the version API and page against the same immutable frontend/backend build SHA; present mixed or unknown build identities explicitly.
- [x] Ensure built frontend/backend identities match; test mixed/stale assets without corrupting normal page load.
- [x] Add OCI labels or the nearest existing deploy image equivalent; no new version registry.
- [x] Confirm Keep a Changelog **1.0.0** (not 1.1.0), dated version headings, standard change categories, and version comparison links; reuse REvoDesign `docs/agents/RELEASE.md` module-scoped terse bullet style.
- [x] Preserve original user-facing `Unreleased` workflow; use an explicit, stage-safe release-cut process adapted from REvoDesign without silently pushing tags.
- [x] Do not invent historical **formal releases**; source-derived `0.1.0+<SHA7>` snapshots and their curated baseline are not official release tags.
- [x] Introduce a release tag gate for vX.Y.Z (optional prerelease), exact metadata equality and changelog section existence; evidence tags remain separate.
- [x] Document explicit manual release and rollback procedure, including deployment SHA, image digest and existing Runner provenance separation.
- [x] Run API contract, server unit and frontend build tests at exact head. Document failed checks truthfully.
- [ ] Obtain independent architecture review and maintainer approval before merging. No automatic tag/release/deploy.

### PR-1a — response and upload transport compression

- [ ] Benchmark current API and structure-response wire bytes/latency under a repeatable throttled network profile.
- [ ] Introduce selectively negotiated ingress response compression; preserve caching, ETag/Vary and range semantics. Never compress precompressed binary data on principle.
- [ ] Specify one narrowly scoped upload request-compression capability with client/server negotiation and backward-compatible uncompressed API.
- [ ] Implement adaptive browser-side gzip where worthwhile, preserve original filename/format and give upload progress/cancel feedback.
- [ ] Reject malformed encodings, double compression, compressed-body expansion abuse, size/time/disk budget violations, and inconsistent digests.
- [ ] Verify exact original SHA and upload authorization/preflight/immutable input validation equivalence for compressed vs identity uploads.
- [ ] Test browser without CompressionStream, offline/cancel/racing upload and large incompressible XTC fallback.
- [ ] Capture before/after transfer sizes and CPU/wall-time; do not claim performance improvement from unit tests alone.

### PR-1b — resumable and shareable artifact download

- [ ] First capture existing GET Range/206/416 behavior and test gaps instead of rewriting an already functional range path.
- [ ] Add/verify HEAD, Content-Length, ETag, If-Range and byte-exact 206/416 semantics, including independent and parallel Range requests.
- [ ] Design bounded artifact-scoped signed bearer URL issuance with expiry, access check, revoke/regenerate path and audit trail.
- [ ] Ensure IDM-compatible unauthenticated GET/HEAD works until expiry while other APIs stay protected.
- [ ] Validate no query-token leakage via logs/referrer/caches/analytics, safe filename handling, no symlink/path escape, and invalidation after deletion.
- [ ] Test token tampering, expiry, revoked task, multiple ranges, partial retry, slow transfer, missing artifact and concurrent deletion.

### PR-2 — Mol* viewer interaction and presentation contract

- [ ] Audit input MolecularViewer and result viewer-contract/structure-controller; merge capabilities without breaking trajectory or structure plugins.
- [ ] Define typed authored atom/residue identity, topology revision, crosshair XYZ (Angstrom), selection, box center+dimensions and change events.
- [ ] Implement set-zero and whole-structure-COM initialization; distinguish COM from geometric centroid.
- [ ] Test atom subsets, mass availability, altloc/insertion code, empty selection, unit/frame correctness and controlled two-way updates.
- [ ] Make normal/expand/maximize modes reuse one viewer state; ensure WebGL lifecycle and cleanup.
- [ ] Verify keyboard, focus trap/restore, reduced motion and mobile/tablet/desktop layout; save screenshots.

### PR-3 — CAVER input form integration (requires PR-2)

- [ ] Audit pinned CAVER 3.0.2 accepted include/exclude directives; never expose unsupported options in a schema.
- [ ] Verify start_group vs start_residue_number behavior against runner code and browser; no duplicated fields.
- [ ] Bind current CAVER seed to common seed control and preserve deterministic task submission.
- [ ] Expose atom, residue, group, ligand and manual XYZ via shared molecular picker, with authored source identities.
- [ ] Populate residue names from current structure, invalidate on file change and refuse ambiguous/invalid mappings.
- [ ] Add supported include/exclude residue IDs/names/atom numbers, full typing and config validation.
- [ ] Compare generated Runner config/provenance and snapshot selection to UI, including rejection tests for chainless/insertion-coded/altloc cases.

### PR-4a — task history search and incremental loading

- [ ] Define authorized task list query, server-side search/filter/sort, stable cursor, bounded page size and precise tie breakers.
- [ ] Ensure search applies to the full authorized dataset before pagination, with no matches skipped by client-only filtering.
- [ ] Provide incremental page loading, request cancellation, loading/error/empty states and bounded DOM footprint.
- [ ] Keep live status refresh independent from historical pagination; choose bounded polling or SSE based on measured need.
- [ ] Test permission filtering, duplicate timestamps, concurrent status changes, stale cursor, fast search typing, network failure and mobile UI.

### PR-4b — Clone & Reuse, placeholders and persistent submit

- [ ] New draft rehydrates compatible parameters from one authorized existing Task, never mutating source.
- [ ] Compare old and current Task schema, parameter name/type/enum/ranges, file roles, input permissions, resource entitlements and current constraints.
- [ ] Show incompatible/missing values in a visible warning with explicit revalidation; never silently reuse old defaults or inaccessible inputs.
- [ ] Add schema-owned optional example placeholder distinct from default/required input validation; update API client types only from OpenAPI.
- [ ] Make submit control viewport-bottom sticky with desktop/tablet/mobile safe area, keyboard and validation/error visibility.
- [ ] Test two-way navigation, empty placeholder, all incompatible cases, preview screenshots and keyboard-only submission.

### PR-5 — MD topology/trajectory conversion Tool

- [ ] Audit exact supported parser/writer combinations for GRO+XTC, Amber, CHARMM/NAMD, LAMMPS and OpenMM. Do not promise every pairing.
- [ ] Implement a bounded, isolated Tool that takes topology plus trajectory and validates atom count/order/identity, frame limits, units and PBC handling.
- [ ] Enforce <=100 MB original/decompressed trajectory input with independent CPU/disk/frame caps; decompress size is authoritative.
- [ ] Generate consistent PDB snapshots for CAVER according to its actual runner input contract; preserve order, frame times and provenance.
- [ ] Reject malformed/ambiguous conversions and expose clear, actionable errors without arbitrary user shell commands.
- [ ] Compare converted frames against reference trajectories on representative fixtures and record scientific constraints.

### PR-6 — trajectory visualization fit and export (requires PR-2)

- [ ] Inspect current Mol* binary trajectory loader, stage and playback before extending the viewer contract.
- [ ] Provide selected-atom alignment with reference frame, Kabsch rigid fit and explicit PBC/weight semantics.
- [ ] Apply only local browser preview transforms, allow reset, preserve immutable source artifact.
- [ ] Bound client memory and main-thread work, add progress/cancel and test alignment numerics on small fixtures.
- [ ] Export an actually supported preview trajectory format; do not label a PDB export XTC/DCD.
- [ ] Capture UI screenshots and compatibility checks across browsers.

### Campaign completion / release

- [ ] Every implemented PR contains exact-head test evidence and relevant release-note disposition.
- [ ] All blockers in canonical PR threads resolved, independent Adviser review remains documented.
- [ ] Changelog Unreleased is complete for approved user-facing behavior.
- [ ] Explicit release-cut PR selects version; tag and GitHub Release happen only after release gates.
- [ ] Maintainer separately approves production deployment; verify build identity, rollout and rollback.

## Cross-cutting release gates

- Existing input/artifact authorization and publication trust boundaries unchanged except for narrowly reviewed extensions.
- Unit, integration, Playwright and end-to-end contract tests cover failure injection: dropped connections, bad encodings, compression bombs, expired bearer links, conflicting search results, invalid molecular selections and stale Task schemas.
- Run frontend typecheck, unit tests, API contract generation checks, server tests, Runner-family fast tests and browser tests relevant to each changed boundary.
- Capture reproducible network and rendering metrics and **before/after browser screenshots** for UI PRs across desktop, tablet and mobile.
- Preserve exact head SHA and test evidence in each PR. Independent Campaign Adviser should check architecture and scope separately from implementing subagents.
- Do not squash-merge, publish official release, rebuild a production SIF, or deploy production without an explicit maintainer decision.
