# Experience and Network Reliability Campaign

Status: **design / coordination**, not evidence that any runtime feature has been implemented. This is the canonical scope document for the 2026-11-12 experience feedback. See root TODO.md for handoff gates and ORIGINAL_DESIGN.md for the original requirements and resolved terminology. Release/versioning is specified separately in release-governance.md.

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

## Recommended PR breakdown

The planning Draft PR is docs-only until Commander implements the **first** change; no giant implementation branch.

- PR-0: Release Governance — version source, changelog, build identity, manual release gates. No runtime deployment.
- PR-1: Transport — response/request compression, range audit, signed artifact URLs. Split into response/upload and download sub-PRs if the exact diff grows.
- PR-2: Shared Molecular Interactions — one viewer contract, coordinates/box/selection, three presentation modes.
- PR-3: CAVER — schema+Runner adaptation and typed forms; depends on PR-2.
- PR-4a: Task history — server filters, cursor pagination and incremental updates.
- PR-4b: Submission experience — Clone & Reuse, placeholder, persistent submit rail; independent except for any shared versioned draft API.
- PR-5: MD topology/trajectory conversion Tool; depends on trust contract from PR-1 and scoped Task adapters from PR-3 if CAVER is first consumer.
- PR-6: Browser trajectory fit/export; depends on PR-2 and the actual result trajectory adapter.

PR-4a and PR-4b can run after PR-0. PR-1 and PR-2 can begin independently. PR-3 and PR-6 must not race the shared viewer adapter without agreed type contracts.

## Cross-cutting release gates

- Existing input/artifact authorization and publication trust boundaries unchanged except for narrowly reviewed extensions.
- Unit, integration, Playwright and end-to-end contract tests cover failure injection: dropped connections, bad encodings, compression bombs, expired bearer links, conflicting search results, invalid molecular selections and stale Task schemas.
- Run frontend typecheck, unit tests, API contract generation checks, server tests, Runner-family fast tests and browser tests relevant to each changed boundary.
- Capture reproducible network and rendering metrics and **before/after browser screenshots** for UI PRs across desktop, tablet and mobile.
- Preserve exact head SHA and test evidence in each PR. Independent Campaign Adviser should check architecture and scope separately from implementing subagents.
- Do not squash-merge, publish official release, rebuild a production SIF, or deploy production without an explicit maintainer decision.
