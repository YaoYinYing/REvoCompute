# PR32 Phase 1 Implementation State

`TODO2.md` is the authoritative architecture and acceptance contract. `TODO.md`
is preserved only as the scientific, Mol*, and Result UX context that Phase 1
must retain. Tests and named acceptance commands are the machine-verifiable
truth.

## Active phase

**Phase 1A: establish the HTTP/OpenAPI boundary and independent frontend
application shell.** The current lane is limited to the minimal backend contract
needed for a Result frontend to reconstruct task and result state from the URL.
No Result presentation model belongs in the backend.

## Preservation audit

Audit basis: `main...HEAD`, the complete dirty worktree, and the two named
interrupted-review stashes. Neither stash may be popped wholesale.

### KEEP

- Manifest-approved artifact identity, authorization, range/download delivery,
  archive delivery, and inert handling of unsafe HTML.
- Same-origin session-cookie, Bearer, and X-API-Key authentication behavior.
- Pinned Mol* dependency/build provenance and direct `MolecularViewer` adapter;
  migrate it into the frontend application rather than replacing it.
- Runner-owned expected-file and Storyboard contracts and their scientific
  semantics.
- Bounded projection authorization and limits, subject to API cleanup before
  frontend adoption.
- Existing behavioral tests for downloads, Mol* lifecycle, fullscreen,
  responsive rail behavior, scientific plots, and Runner contracts.
- Stash 0 projection assertions/tests, selectively reworked for the final API.

### ADAPT

- `988e0e1`, `bbbd5b3`, and Mol* work in `e70f8f2`: move build, adapter, and
  lifecycle ownership into Vite/TypeScript. Root package ownership is not final.
- `469b193` and Result workspace work in `e70f8f2`: preserve download,
  fullscreen, panel, and lifecycle behavior while replacing `task-results.js`
  and Jinja-owned application state.
- `5d74882`: retain bounded authorized projections, document the stable OpenAPI
  schema, and avoid repeated source parsing.
- `995c17c`, current Result docs, and the old execution ledger: retain evidence,
  not their superseded single-page architecture or completion claims.
- `task_results.html`: compatibility route/shell only until frontend ownership;
  remove injected business state.
- Scientific primitives and Storyboards: preserve proven behavior, then move
  state and API consumption into the frontend Result feature.
- Stash 0 projection tests and stash 1 bounded categorical projection and AF3
  synchronization ideas: apply selectively after matching TODO2. Stash 1's
  `task-results.js` edits require migration, not restoration.
- Any dirty bounded aggregate/categorical projection and PairMatrix work:
  preserve as interrupted evidence, rebase onto the documented API contract,
  and exclude from this documentation checkpoint.

### DROP

- Stash 0 deletion of the ColabFold storyboard.
- Restoration of iframe/viewer-shell/postMessage, runtime Mol* CDN, or a second
  Mol* backend.
- Backend Result presentation models, Runner-name branches, and frontend
  inference from server filesystem layout.
- Stash 1 edits that deepen `task-results.js` as the long-term Result owner.
- Root-level frontend scaffolding as the final application shape; TODO2 requires
  the independent application under `frontend/`.
- Claims that working legacy/static behavior proves TODO2 Phase 1 complete.

## Phase 1 completion checklist

### Preserve and define the boundary

- [x] Audit `main...HEAD`, worktree, and both interrupted-review stashes.
- [x] Record KEEP/ADAPT/DROP without resetting or popping a stash wholesale.
- [ ] Migrate every retained behavior before deleting its legacy implementation.
- [ ] Frontend depends only on documented HTTP/OpenAPI contracts.
- [ ] Backend Result code contains no DOM, Mol*, layout, panel, or Storyboard
      presentation state.
- [ ] Frontend contains no Python/database/Celery/Slurm/filesystem/plugin-manifest
      assumptions.

### Independent frontend and deployment

- [ ] Add `frontend/package.json`, lockfile, TypeScript, Vite config, `src/`, and
      frontend tests.
- [ ] Keep the implementation framework-free unless a need is recorded.
- [ ] Frontend builds and typechecks independently and reproducibly.
- [ ] Vite development proxies `/compute/api/*` to the backend.
- [ ] Production serves frontend routes/assets and APIs on one origin.
- [ ] No CORS, second API host, separate auth origin, or frontend byte streaming
      for large artifacts.

### OpenAPI and URL reconstruction

- [ ] Audit task, task-type, result-manifest, artifact, download, archive, and
      current-session API behavior.
- [ ] Document task/status identity and running/failed/partial result state.
- [ ] Document artifact identity, display metadata, media type, role, size,
      presentation capability, authorized URLs, and availability.
- [ ] Document session expiry, unauthorized, and not-found behavior.
- [ ] Generate/validate small TypeScript types and add a thin API client.
- [ ] Add only genuinely missing backend fields/endpoints.
- [ ] Result shell is `<div id="app"></div>` plus the current URL.
- [ ] Route-derived task identity reconstructs on refresh/copied URLs without
      Jinja-injected state; existing URLs remain usable or deliberately redirect.

### Frontend-owned Result workspace

- [ ] Move Result header, files, preview, diagnostics, Storyboard, and molecular
      viewer ownership under `frontend/src/features/results/`.
- [ ] Frontend owns selection, expansion, search, panels, sizing, fullscreen,
      preview, Mol*, and Storyboard lifecycle state.
- [ ] Backend remains authoritative for task state, manifest, provenance,
      diagnostics, artifact authorization, and downloads.
- [ ] Integrate pinned Mol* directly with one deterministic PluginContext and
      preserve loading, controls, theme, selection, resize, export, disposal,
      failure isolation, and no runtime CDN.
- [ ] Remove iframe/viewer-shell/postMessage only after the new path works.

### Fullscreen, files, and responsive layout

- [ ] Fullscreen targets the actual molecular workspace; UI exit and Esc restore
      layout and viewer sizing without duplicate toolbar or stale state.
- [ ] Desktop rail returns width; tablet/mobile uses a non-obscuring treatment.
- [ ] Preserve search, hierarchy, diagnostics, selection, and keyboard access.
- [ ] Display basename separately from immutable relative-path/API identity.
- [ ] Verify wide desktop, laptop, tablet portrait/landscape, and narrow mobile:
      no overflow, obscured viewer, unreachable controls, or unusable wrapping.

### Manifest capability, Storyboards, and downloads

- [ ] Manifest is the primary renderer-capability source with the minimal
      vocabulary: molecular structure, table, plot, image, text, archive,
      download-only, unknown.
- [ ] Filename/media-type inference is legacy fallback only.
- [ ] Mol* consumes artifact metadata without Runner branches.
- [ ] Preserve individual artifact, structure, archive, and authorized
      failed/partial downloads without frontend Blob buffering.
- [ ] Remove decorative taxonomy not backed by manifest semantics.
- [ ] Preserve Storyboard behavior and synchronize tree/structure/Storyboard
      candidates with stale-response rejection.

### Authentication, security, and scope

- [ ] Preserve same-origin HttpOnly sessions without token storage or new auth
      framework; handle logout/session expiry through documented semantics.
- [ ] Use authorized artifact identities/URLs only; no privileged remote URL
      proxy, eval, dynamic server source, unsafe HTML, or path escape.
- [ ] Keep Dashboard, catalog, Create Task, profile, admin, and auth pages working
      on legacy infrastructure.
- [ ] No unrelated Core, Celery, Slurm, Runtime Bundle, OOM, Runner, credit, or
      execution architecture refactor.
- [ ] Enforce non-goals: no repository/domain/service split, CORS, microservices,
      global frontend rewrite, auth redesign, Runner redesign, new scientific
      Runner, or unrelated backlog work.

### Inherited Result and scientific debt

These are unresolved requirements inherited from `TODO.md`. They must be
implemented through the TODO2 Presentation/Control boundary, not patched only
in the legacy Result page.

#### Lane A: server-owned contracts and bounded data

- [ ] Match AlphaFold 3 candidates to real manifest artifact `name` identities;
      do not infer a candidate from an unrelated path or array position.
- [ ] Publish bounded AlphaFold 3 and ColabFold evidence with an atomic
      latest-candidate identity so a consumer cannot combine generations.
- [ ] Make bounded projection parse/decompress each source at most once per
      aggregate request while retaining authorization, source-byte, element,
      response, and memory limits; do not add an unbounded persistent cache.
- [ ] Extend that projection narrowly to bounded categorical chain-ID vectors
      for JSON/CSV only, with per-value and aggregate byte limits; NPY/NPZ stay
      numeric-only and the schema distinguishes numeric from categorical data.
- [ ] Keep partial and failed artifacts downloadable only through manifest-
      approved identities, with state and availability explicit in OpenAPI.

#### Lane C: frontend lifecycle, synchronization, and visualization

- [ ] Dispose the molecular viewer when navigating structure -> Storyboard and
      create exactly one fresh viewer when navigating Storyboard -> structure.
- [ ] Reject an older successful structure response after a newer candidate was
      selected; abort is an optimization, generation identity is authoritative.
- [ ] Make teardown bfcache-aware so pagehide/navigation cannot leak a viewer or
      destroy state needed by a persisted page restore.
- [ ] Clear OpenDDE candidate-dependent panels immediately on candidate change
      and keep them empty on a failed replacement instead of showing stale data.
- [ ] Give PairMatrix usable geometry below 320 CSS pixels and reject pointer
      input outside the actual plotted matrix rather than clamping it to an edge
      cell.
- [ ] Keep structure, metrics, local confidence, pair matrices, entity summary,
      and interface evidence on one candidate generation; reject every stale
      asynchronous completion.
- [ ] Preserve PairMatrix responsive resize, axes, chain/entity borders,
      keyboard navigation, selection/readout, and cross-view focus without
      assuming that every index represents a protein residue.
- [ ] Show metric, alignment, and entity views only for published evidence;
      never invent empty metrics, infer an MSA from a scalar/configuration, or
      silently rescale uncertain confidence values.
- [ ] Isolate Mol*, plot, ndarray, MSA, and Storyboard failures so files,
      authorized downloads, ZIP, run metadata, and provenance remain usable.
- [ ] Preserve direct-download-before-preview, no whole-file browser buffering,
      accessible file-tree search/disclosure, stable entity colors, and the
      selection/focus loop without circular updates.

#### Cross-lane regression gates

- [ ] Preserve the generic authentication failure wording for Bearer and
      X-API-Key credentials and verify valid Bearer, valid API key, invalid
      credential, cookie/session expiry, and hidden foreign-task behavior.
- [ ] Exercise candidate synchronization with deliberately reordered responses,
      structure/Storyboard reopen, bfcache navigation, sub-320 PairMatrix input,
      failed OpenDDE replacement, bounded categorical projection, and
      partial-result downloads in behavior-level tests.

### Workflow, tests, cleanup, and documentation

- [ ] Document frontend, backend, and full-stack development commands.
- [ ] Backend gates cover Result API, authorization, manifest, state variants,
      and OpenAPI schema.
- [ ] Frontend gates cover typecheck/build, API client/types, renderer selection,
      state, and Mol* helpers.
- [ ] Browser/full-stack gates cover direct URL/refresh, tree/search, structure
      preview/switching, downloads, fullscreen, rail, failed/partial/empty states,
      mobile, and session expiry.
- [ ] Existing BrowserContracts and ServerComposeFullStack remain green.
- [ ] Retain Jinja/static infrastructure for unmigrated pages; remove obsolete
      viewer boundary code and duplicate helpers only when proven unused.
- [ ] Document Presentation (`frontend/`), Control (backend), and Execution
      (Runner/Celery/Slurm/Apptainer) planes, coexistence, and later migration
      order without hard future PR numbers.

## Acceptance checklist

- [ ] Independent frontend app exists and owns Result Workspace source.
- [ ] Mol* mounts directly; no iframe is required.
- [ ] URL plus APIs reconstruct Result state and OpenAPI is authoritative.
- [ ] Existing Result URL compatibility is deliberate and tested.
- [ ] Structure viewing/switching, downloads, fullscreen, files/diagnostics, and
      responsive behavior work.
- [ ] Manifest metadata drives rendering and Mol* has no Runner branches.
- [ ] Legacy pages and same-origin authentication remain intact.
- [ ] No runtime Mol* CDN; frontend, backend, browser, and full-stack gates pass.
- [ ] Obsolete boundary code is removed and architecture docs are current.
- [ ] Final reviews find no backend presentation model, Jinja-injected Result
      state, filesystem assumptions, Runner frontend branches, iframe remnants,
      duplicated semantics, or large-byte frontend buffering.

## Evidence and gates

- Direct Mol* adapter/build and strict-CSP work exist, but are not yet owned by
  an independent frontend application.
- Manifest-approved artifact, download/range, archive, and projection tests
  exist. Result behavior tests cover downloads, fullscreen, rail geometry,
  lifecycle, Storyboards, and scientific plots.
- Historical branch evidence includes 1,484 non-browser tests passed and 19
  skipped plus focused build/server gates. This does not prove TODO2 complete.
- A prior Chromium attempt failed with `sandbox_host_linux.cc: Operation not
  permitted`; that is historical evidence only. Retry both Chromium and Docker
  full-stack gates under the current execution environment before completion.

## Next concrete gate

Define and test the smallest OpenAPI-backed task/result/artifact/session contract
that lets the frontend reconstruct running, failed, partial, and completed Result
states from a URL task ID. Then scaffold the frontend API client against it.
