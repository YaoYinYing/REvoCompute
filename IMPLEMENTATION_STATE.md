# Result Workspace and Direct Mol* — Implementation State

- Branch: `feat/result-workspace-molstar`
- Baseline/HEAD at inventory: `83fef06032027eda8bdff6fb1a99eed5afcd0658`
- Design: `TODO.md` (sections 0–44)
- Protocol: `LONG_TASK_HANDLING.md`
- Current phase: **Phase A — build foundation**
- Overall status: **INCOMPLETE**

This file records execution state only. `TODO.md` remains the architectural
source of truth; tests and acceptance commands are the machine-verifiable truth.

## Baseline and current worktree evidence

Inventory performed against the branch above before production changes:

- There is no `package.json`, `package-lock.json`, `frontend/`, or generated
  `revocompute/static/vendor/molstar/` build boundary.
- `docker/server/Dockerfile` is a single Python stage and installs no frontend
  assets. CI has no Node setup or Mol* asset build.
- Production structure viewing is still the old path:
  `task-results.js` → sandboxed iframe → `/compute/viewer-shell` →
  `viewer-shell.js` → jsDelivr `molstar@5.11.0`.
- The main-page CSP still excludes `unsafe-eval`; the viewer-shell route has a
  separate CSP that permits `unsafe-eval` and jsDelivr. No direct-mount
  Mol* 5.12.0 browser qualification exists.
- `task-results.js` already preserves one warm iframe/plugin across ordinary
  structure switches, bounds its structure-text cache, separates representation
  and colour state internally, and gates confidence colouring on declared
  `confidence_encoding`. These behaviors must survive the backend migration.
- The desktop workspace always reserves `minmax(20rem, 26rem)` for Files &
  diagnostics. Collapsing its `<details>` hides content but does not reclaim
  the column. There is no parent-owned Fullscreen API path or shared
  `ResizeObserver` reflow infrastructure.
- An artifact row is one preview button. The selected preview exposes a
  `download=1` link, but each row does not expose an independent direct
  download. Storyboards receive only `context.services.openFile`.
- Server artifact routes already resolve only manifest-approved paths, support
  `download=1`, range/stream delivery, and force unsafe HTML to attachment.
  ZIP creation/download already uses the manifest-approved artifact set.
- Only AlphaFold 3, Example, GREMLIN_LH, and PSSM-GREMLIN currently declare a
  Storyboard. Of the folding/OpenDDE targets, only AlphaFold 3 has one.
- The AlphaFold 3 Storyboard owns a fixed-size PAE canvas and its own scalar
  cards. Its browser test protects pixels, axes, legend, chain borders,
  keyboard navigation, and readout. No shared scientific primitive modules,
  selection store, or bounded ndarray service exist.
- AlphaFold2, ColabFold, ESMFold2, SimpleFold, Boltz, Chai-1, and OpenDDE do
  already publish server-owned result-view/output semantics in their owning
  task manifests. Those contracts are evidence to consume, not duplicate.
- Generic preview/Storyboard failures are caught locally and Files &
  diagnostics remains present; this isolation needs regression coverage as
  new visualizations are added.
- The Fresh Key wording and focused auth tests are currently being changed in
  the shared worktree; they are not counted complete until focused verification
  passes and the checkpoint is committed.
- Concurrent Phase A edits now add `package.json`, `package-lock.json`, a
  `frontend/molstar/` build, a Node builder stage, ignore rules, and browser-CI
  preparation. Concurrent Phase D edits add row downloads,
  `services.downloadFile`, and compact-rail state. These are work in progress,
  not completed checklist evidence until their owning agents report tests and a
  coherent checkpoint.

## Completion checklist

Status rule: `[x]` means current repository evidence and a named verification
prove the item. Every unchecked item is required unless the direct-mount gate
records a genuine Mol* incompatibility and selects the documented thin-iframe
fallback.

### Phase A — reproducible frontend build foundation (active)

- [ ] Add the minimal frontend build boundary and commit `package-lock.json`.
- [ ] Pin exactly `molstar@5.12.0`; use `npm ci`; do not vendor Mol* source,
      generated bundle output, or `node_modules`.
- [ ] Build a REvoCompute-specific library integration rather than self-hosting
      the complete upstream Viewer application.
- [ ] Emit generated JS/CSS only under the server static tree and lazy-load it
      only for structure preview or `StructureViewport`.
- [ ] Convert the server image to a Node 22 builder + Python runtime image; the
      final image must contain neither Node/npm cache/node_modules nor Mol*
      source and must require no runtime network fetch.
- [ ] Add Mol* 5.12.0 upstream/version/license provenance.
- [ ] Update only browser/build CI jobs with Node setup, `npm ci`, and the Mol*
      build; keep unrelated Runner tests Node-free.
- [ ] Add executable build gates for lockfile consistency, asset generation,
      missing output, and the production Docker build path.

### Phase B — strict-CSP qualification and backend decision

- [ ] Exercise the exact generated Mol* 5.12.0 bundle on a normal Result Page
      under the real main-page CSP.
- [ ] Browser acceptance must initialize, load small PDB and mmCIF inputs,
      render, switch representation and colour, select/focus, and dispose.
- [ ] Prove the main CSP still has no `unsafe-eval` or executable inline script;
      fail on functional CSP violations. Static `eval(`/`new Function(` checks
      are supplementary only.
- [ ] Record the gate outcome. PASS selects direct mount as the sole production
      backend; FAIL must record the exact unavoidable blocker before retaining
      a thin sandboxed iframe (`allow-scripts allow-downloads`, no
      `allow-same-origin`).
- [ ] Do not relax CSP or keep two permanent Mol* backends.

### Phase C — MolecularViewer production migration

- [ ] Add one application-facing `MolecularViewer` adapter; generic Result Page
      and primitives must not use raw Mol* internals.
- [ ] Cover mount, PDB/mmCIF load, clear/reload, representation, colour,
      selection/focus, camera reset, theme, resize, screenshot, disposal, and
      selection notifications where mapping is reliable.
- [ ] Keep representation (Cartoon, Cartoon + ligand, Sticks, Surface) and
      colour (Chain/entity, Rainbow, declared Confidence) as independent axes.
- [ ] Preserve one live PluginContext across candidate/structure switches;
      create/dispose only with the owning viewport lifecycle.
- [ ] Isolate local Mol* load/render failure so plots, Files & diagnostics,
      downloads, ZIP, metadata, and reproducibility remain usable.
- [ ] If direct CSP qualification passes, remove `/compute/viewer-shell`, its
      template/CSS/JS, iframe/postMessage/handshake/request routing, jsDelivr
      Mol* constants, shell CSP, and shell-specific tests/comments.
- [ ] Replace old lifecycle tests with direct-adapter browser coverage for one
      initialization, reload reuse, controls, selection, theme, resize,
      disposal, and exactly one reinitialization after reopening.

### Phase D — workspace ownership and download UX

- [ ] Implement parent-owned true fullscreen on the entire
      `StructureViewport`; the same control and browser Esc must exit it.
- [ ] Synchronize `fullscreenchange`, accessible pressed state/tooltip, and
      resize without recreating Mol* or losing candidate, representation,
      colour, camera, or scientific selection.
- [ ] Make desktop file-rail collapse reclaim nearly all rail width with an
      accessible reopen control; retain single-column disclosure on tablet/mobile.
- [ ] Add resize-safe rendering for rail toggles, fullscreen, and window
      changes. Canvas backing sizes and hit testing must be recomputed, not
      CSS-scaled.
- [ ] Split every artifact row into legal sibling preview and direct-download
      controls using the approved URL plus `download=1`.
- [ ] Keep direct download independent of preview limits and avoid loading
      large downloads into JavaScript memory.
- [ ] Add `context.services.downloadFile(artifact)`; Storyboards must not build
      auth/download URLs.
- [ ] Distinguish authoritative structure download from client-side image
      export. Implement screenshot; add scene/state export only if Mol* offers
      a stable simple API.
- [ ] Preserve manifest-only Create ZIP / Download ZIP behavior.
- [ ] Preserve artifact search/filter and keyboard-accessible folders after the
      row refactor.

### Phase E — shared scientific primitives

- [ ] Add only the required shared primitives: `CandidateSelector`,
      `ScalarMetricGrid`, `StructureViewport`, `LocalConfidenceSeries`,
      `PairMatrix`, `AlignmentCoverage`, `EntitySummaryTable`, and
      `ResultSelectionStore`; do not add a framework, DSL, or generic event bus.
- [ ] Keep rendering mechanics shared and scientific meaning Runner-owned.
- [ ] Store candidate/entityA/entityB/token-or-residue selection in the Result
      Page/Storyboard, prevent circular updates, and use stable identifiers.
- [ ] Make candidate changes atomically update structure, metrics, local
      confidence, matrices, entity summary, and interface metrics; reject stale
      async responses with generation/AbortSignal behavior.
- [ ] Support local confidence with declared indexing, entity boundaries,
      units/scale, title, and semantics; do not assume every value is a protein
      residue or silently rescale ESMFold2.
- [ ] Extract AF3 matrix mechanics into a bounded, responsive, accessible
      generic `PairMatrix` without losing its current behavior.
- [ ] Link confidence/matrix/entity interactions to Mol* through the store and
      adapter, with consistent entity colours and reverse Mol* selection only
      where mapping is reliable.
- [ ] Implement bounded A3M coverage only when a real alignment artifact is
      published; do not infer an alignment from a scalar, PDF, or flag.
- [ ] Prefer Runner-native entity/interface metrics over subtly different
      client re-derivations.
- [ ] Add one server-validated bounded ndarray path for JSON/CSV/NPY/NPZ data,
      enforcing element/byte/slice limits; primitives must be storage-agnostic.

### Phase F — capability-driven Runner Storyboards

- [ ] Preserve and migrate AlphaFold 3 first: candidates, structure, pTM, ipTM,
      ranking, disorder, clash, declared local confidence, PAE, and mixed-system
      token/entity semantics.
- [ ] Build ColabFold AF2 as the rich AF2 reference: candidates, metrics,
      pLDDT, PAE, real A3M coverage, entities, and emitted ipSAE/pDockQ2.
- [ ] Build OpenDDE from bounded projections of its emitted summary/full
      confidence data; never browser-load enormous full-data JSON wholesale.
- [ ] Compose ESMFold2 after verifying persisted confidence units; show MSA
      coverage only for a retained published alignment.
- [ ] Compose Boltz and Chai-1 through the single bounded ndarray path; never
      reinterpret Chai's `msa_depth.pdf` as an alignment.
- [ ] Compose AlphaFold2 and intentionally sparse SimpleFold only from emitted
      evidence; do not invent recycle history, PAE, MSA, or confidence.
- [ ] Tighten RoseTTAFold3/Foundry output contracts from fixtures/live evidence
      before building its precise Storyboard.
- [ ] Keep generic Core free of Runner-name branches and retain Files &
      diagnostics as the universal fallback for every family.

### Phase G — regression, security, documentation, and delivery

- [ ] Finish and verify the generic Fresh Key diagnostic: valid Bearer, valid
      X-API-Key, and invalid credential all preserve generic non-leaking behavior.
- [ ] Test direct downloads before preview, oversized preview vs download,
      Storyboard downloads, ZIP, structure source, and screenshot without a
      whole-file browser fetch for large artifacts.
- [ ] Test real layout dimensions on desktop/tablet/mobile and the transition
      sequence rail collapse → fullscreen → exit → expand.
- [ ] Test multi-candidate synchronization, delayed-response rejection, and
      supported cross-view selection mappings.
- [ ] Preserve security gates: strict main CSP, inert result HTML,
      manifest-approved artifacts, declared Storyboard logical IDs, bounded
      large data, and self-hosted Mol* with no runtime CDN.
- [ ] Update the Result Page architecture/build documentation and remove claims
      that viewer-shell or Mol* 5.11 `unsafe-eval` behavior is current.
- [ ] Audit and explain/remove every viewer-shell, iframe, postMessage, CDN,
      duplicate scientific renderer, and obsolete compatibility-path remnant.
- [ ] Run focused tests while migrating, then final `make test`, `make test-cov`,
      browser/security suites, `mkdocs build --strict`, Compose rendering, and
      Docker full-stack acceptance from the final commit.
- [ ] Redeploy with `run/restart.sh ... --use-proxy`, then run real Result Page /
      Runner live acceptance through API → worker → SLURM → Apptainer and inspect
      status, manifests, logs, downloads, ZIP, and required artifacts.
- [ ] Commit coherent checkpoints, push the feature branch, open a PR, and
      request one review pass after local verification.

## Preserved acceptance baselines

These exist today but do not prove the migration complete:

- Main application pages reject `unsafe-eval`.
- Manifest-only artifact resolution, authenticated range/download delivery,
  inert HTML attachment handling, and ZIP delivery have server tests.
- The old iframe implementation has warm-viewer, candidate-reuse, confidence
  declaration, and disposal tests. They define behavior to migrate, not an
  architecture to retain.
- AF3 PAE has a real Storyboard browser contract for drawing, axes, legend,
  chain borders, keyboard interaction, and readout.
- Existing generation/AbortSignal and preview-host teardown patterns are
  reusable for stale-response and failure isolation behavior.

## Risks and blockers

- **Decision risk, not a blocker:** direct mounting remains unproven until the
  exact 5.12.0 custom bundle runs under the production CSP in a real browser.
- **Scientific-contract risk:** ESMFold2 confidence units and
  RoseTTAFold3/Foundry output identities require evidence before presentation.
- **Data-volume risk:** OpenDDE full JSON and Boltz/Chai arrays require bounded
  server projections before rich browser views.
- **Regression risk:** replacing the iframe must preserve one-viewer reuse and
  AF3 PAE behavior while removing—not retaining—the old production path.
- **Coordination risk:** the shared worktree has concurrent scoped edits.
  Preserve unrelated changes and checkpoint only owned files.
- No external blocker is currently established.

## Verification performed for this state reset

- Read `CLAUDE.md`, all of `TODO.md`, all of `LONG_TASK_HANDLING.md`,
  `docs/runner-guide/task-contract.md`, and the supplied task brief.
- Inspected branch/HEAD/worktree, server Dockerfile, CI, CSP/routes, result
  template/CSS/JavaScript, viewer shell, Storyboard loader/declarations,
  target-family result contracts, artifact routes, auth diagnostic, and
  relevant Python/Node/Playwright tests.
- This was a read-only inventory plus this execution-state replacement; no
  production code or tests were run by this inventory task.

## Next concrete action

Complete Phase A's minimal pinned build boundary, then run the Phase B strict-CSP
browser gate. Do not edit or remove the viewer-shell production path until that
gate records a direct-mount PASS.
