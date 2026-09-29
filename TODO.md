# TODO — Result Workspace, Direct Mol* Integration, and Scientific Visualization

## Goal

Refactor the REvoCompute result page into a coherent scientific result workspace.

This work combines the previously planned Result Page improvements with a
Mol* integration refactor:

1. stop loading Mol* from a runtime CDN;
2. fetch/pin/build Mol* at server-image build time;
3. test Mol* 5.12.0 directly under REvoCompute's existing strict CSP;
4. remove the iframe/viewer-shell architecture if direct mounting passes;
5. make REvoCompute own structure-viewer controls, downloads, fullscreen,
   workspace geometry, scientific cross-selection, and responsive resizing;
6. build reusable scientific visualization primitives;
7. compose rich ResultStoryboards for xxFold-style runners and OpenDDE;
8. preserve the generic Files & diagnostics fallback and bounded artifact model.

Do not mix this work with scheduler, persistent execution, batching, OOM
recovery, Runtime Bundles, or Runner execution semantics.

Current baseline when this task was written:

    main = 83fef06032027eda8bdff6fb1a99eed5afcd0658

Rebase/check current main before implementation and adjust paths deliberately
if the repository moved.

---

# 0. Core architectural decision

The desired end state is:

    Result Page
    │
    ├── ResultStoryboard
    │
    ├── workspace/layout state
    ├── fullscreen
    ├── artifact downloads
    ├── scientific selection state
    ├── scientific visualization primitives
    │
    └── MolecularViewer adapter
          │
          └── Mol* PluginContext
                └── WebGL canvas

The preferred architecture has NO iframe.

However, removing the iframe is conditional on an actual CSP/browser
qualification test of the exact pinned Mol* build.

Do not infer compatibility from the changelog alone.

Decision gate:

    molstar@5.12.0
          ↓
    custom REvoCompute build
          ↓
    strict production CSP
    NO unsafe-eval
          ↓
    browser acceptance
          │
          ├── PASS → direct Mol* becomes canonical
          │           remove viewer-shell/iframe architecture
          │
          └── FAIL → preserve a thin iframe backend
                      and document the exact failure

Do not implement both production backends permanently.

The adapter may temporarily make the migration testable, but once direct mode
passes all acceptance tests, remove the obsolete iframe backend rather than
keeping two Mol* implementations indefinitely.

---

# 1. Introduce a frontend build boundary

REvoCompute currently does not need to commit a copy of upstream Mol*.

Add a minimal frontend dependency/build boundary.

Suggested repository layout:

    package.json
    package-lock.json

    frontend/
      molstar/
        index.ts
        viewer.ts
        presentation.ts
        selection.ts

    revocompute/static/vendor/molstar/
      # generated; not committed

Do not vendor:

    molstar.js
    molstar.css
    node_modules/
    upstream Mol* source

into git.

Pin the exact Mol* release:

    molstar: 5.12.0

Do not use:

    ^5.12.0
    latest

Commit `package-lock.json`.

Use:

    npm ci

for reproducible installation.

Node is a build dependency, not a server runtime dependency.

---

# 2. Build Mol* during the server-image build

Convert `docker/server/Dockerfile` to an appropriate multi-stage build.

Conceptually:

    Node 22 frontend-builder
        │
        ├── npm ci
        ├── build REvoCompute Mol* bundle
        └── emit generated JS/CSS
              │
              ↓
    Python runtime image
        │
        └── COPY generated assets only

The final server image must not contain:

    node_modules
    npm cache
    Mol* source tree
    Node build toolchain

unless another server feature explicitly requires them.

The runtime server must not fetch Mol* from the internet.

The browser must load Mol* only from REvoCompute's own `/static/...` origin.

---

# 3. Build a REvoCompute-specific Mol* library

Do not merely self-host the complete upstream Mol* Viewer application.

Prefer a small integration built from Mol* library APIs, using the smallest
appropriate PluginContext / PluginUIContext surface.

REvoCompute owns:

    result toolbar
    fullscreen
    downloads
    theme controls
    representation controls
    colour controls
    candidate selection
    PAE/pLDDT interaction
    file navigation

Mol* owns:

    parsing
    molecular representations
    WebGL rendering
    molecular selection/focus
    camera
    structure state

Initial required capabilities:

    initialize viewer
    load PDB
    load mmCIF
    clear/load another structure without reinitializing
    cartoon
    cartoon + ligand
    ball-and-stick
    molecular surface
    chain/entity colouring
    sequence/rainbow colouring
    pLDDT confidence colouring when declared
    residue/token selection
    entity focus
    camera reset
    theme/background update
    resize
    screenshot/export where supported
    dispose

Do not expose raw Mol* implementation details throughout the Result Page.

---

# 4. Add a MolecularViewer adapter

Create one small stable application-facing viewer abstraction.

Example shape:

    MolecularViewer
      mount(host, options)
      loadStructure(source)
      clear()
      setRepresentation(mode)
      setColor(mode)
      select(selection)
      focus(selection)
      resetCamera()
      setTheme(theme)
      captureImage(...)
      dispose()

and, if needed:

      onSelectionChanged(callback)

The adapter is the only generic Result Page module that should understand
Mol* APIs.

Storyboard code must not manipulate raw PluginContext internals directly.

Scientific primitives should talk to the adapter through stable application
semantics.

This boundary should make future Mol* upgrades local rather than forcing
changes throughout Storyboards.

---

# 5. CSP qualification MUST happen before iframe removal

The existing main-page CSP intentionally forbids:

    'unsafe-eval'
    inline executable scripts

Preserve that security property.

Build the exact Mol* bundle and run it under the actual REvoCompute main-page
CSP.

Static inspection may check for obvious regressions such as:

    eval(
    new Function(

but static grep is not sufficient.

Add a real browser CSP acceptance test.

The test must:

1. load a normal Result Page;
2. verify the response CSP still lacks `unsafe-eval`;
3. dynamically load the self-hosted Mol* bundle;
4. initialize PluginContext;
5. load a small PDB/mmCIF;
6. render a representation;
7. switch representation;
8. switch colour mode;
9. select/focus a residue or entity;
10. dispose cleanly;
11. fail on any CSP violation that prevents functionality.

No CSP relaxation is permitted merely to make Mol* pass.

Specifically, do not add:

    unsafe-eval

to the main app.

Do not weaken CSP because of:

    source-map requests
    browser extensions
    Cloudflare-injected scripts
    optional diagnostics

If direct Mol* requires unexpected permissions, diagnose the exact dependency
before changing policy.

---

# 6. If CSP qualification passes, remove the iframe architecture

Once direct mounting passes the strict-CSP browser contract, remove the old
Mol* isolation path.

Delete or retire:

    /compute/viewer-shell
    viewer_shell.html
    revocompute/static/js/viewer-shell.js

and Mol*-specific iframe lifecycle code from:

    revocompute/static/js/task-results.js

Remove:

    warmMolstar
    warmPending
    postToShell()
    shell-ready handshake
    requestId message routing
    iframe disposal protocol
    iframe-origin handling
    viewer-shell-specific CSP
    viewer-shell-specific tests
    Mol* CDN SRI constants
    jsDelivr Mol* asset loading

Update comments/documentation that still state:

    "Mol* requires unsafe-eval"

because that statement will no longer describe the pinned implementation.

Do not remove security checks merely because the old viewer-shell disappeared.

The main application CSP must remain strict.

---

# 7. Fallback only if direct Mol* genuinely fails

If and only if the pinned 5.12.0 custom build cannot run correctly under the
existing CSP after reasonable investigation:

retain a THIN Mol* iframe.

In that fallback path:

    sandbox="allow-scripts allow-downloads"

and still:

    NO allow-same-origin

The iframe must own only Mol* runtime/rendering.

The parent Result Page must still own:

    toolbar
    downloads
    fullscreen
    layout
    Storyboard state
    selection state

Record the exact blocker preventing direct mounting.

Do not choose the iframe merely because the current implementation already
exists.

---

# 8. Lazy-load Mol*

Mol* is a large optional dependency.

Do not load it for result pages that never display molecular structures.

Load the generated Mol* bundle only when:

    a structure FileViewer opens
    OR
    a ResultStoryboard mounts a StructureViewport

The first load may initialize the module; subsequent structure switches must
reuse the loaded module and active PluginContext where appropriate.

No CDN fallback.

If the local Mol* asset fails to load, display an isolated structure-viewer
failure while keeping:

    Storyboard
    plots
    Files & diagnostics
    downloads

usable.

---

# 9. Preserve one live viewer across candidate switches

Current code intentionally keeps the Mol* iframe warm.

Preserve the useful property, not the iframe implementation.

For one active StructureViewport:

    candidate 1
       ↓
    load candidate 2
       ↓
    same Mol* PluginContext

Do not:

    destroy viewer
    recreate viewer
    rebuild WebGL context

for ordinary candidate/structure changes.

A structure switch is data state, not viewer lifecycle.

Destroy the viewer only when the owning StructureViewport/result composition
is actually torn down.

---

# 10. Structure viewer controls belong to REvoCompute

Keep representation and colour as independent axes.

Representation:

    Cartoon
    Cartoon + ligand
    Sticks
    Surface

Colour:

    Chain/entity
    Rainbow
    Confidence

Do not represent Chain/Confidence as if they were representation presets.

Only expose Confidence when server/Runner metadata explicitly declares a
valid confidence encoding.

Do not infer confidence semantics from:

    file extension
    presence of B-factors
    Runner name

Keep theme controls REvoCompute-owned.

---

# 11. Implement real Result Page fullscreen

Fullscreen is owned by the parent Result Page.

Create a structure-view container such as:

    StructureViewport
    ├── REvoCompute toolbar
    └── Mol* host

Call:

    structureViewport.requestFullscreen()

Do not fullscreen only a canvas or internal Mol* element when that would omit
the REvoCompute toolbar.

The same button acts as a toggle:

    normal
      → requestFullscreen()

    fullscreen
      → document.exitFullscreen()

Also support browser Esc.

Listen to:

    fullscreenchange

and synchronize:

    button text/icon
    aria-pressed
    tooltip
    layout/resize state

Requirements:

- entering fullscreen does not recreate Mol*;
- exiting fullscreen does not recreate Mol*;
- current candidate remains selected;
- current representation remains selected;
- current colour remains selected;
- camera state should survive;
- selection should survive;
- Esc restores the normal Result Page layout.

Do not manually move/clone the viewer DOM to implement fullscreen.

---

# 12. Fix Files & diagnostics collapse geometry

Current desktop layout reserves:

    minmax(20rem, 26rem)

for the rail even when `<details>` is collapsed.

Change collapse from content visibility to workspace geometry.

Use explicit state on the workspace, for example:

    data-files-collapsed="true|false"

Expanded:

    preview | 20–26rem rail

Collapsed:

    preview | compact reopen affordance

The collapsed state must reclaim nearly all rail width for the Storyboard.

Keep a visible accessible reopen control.

Do not leave an invisible 20rem grid column.

On mobile/small-tablet breakpoints, preserve the existing single-column
disclosure behavior rather than forcing a narrow second column.

---

# 13. Add resize/reflow infrastructure

The following operations substantially change available geometry:

    rail collapse
    rail expand
    fullscreen enter
    fullscreen exit
    window resize

Every visualization must respond correctly.

Use `ResizeObserver` where appropriate.

Mol*:

    resize its canvas/render target through verified Mol* APIs or existing
    responsive behavior.

Scientific canvas/SVG primitives:

    recompute backing dimensions
    redraw axes
    redraw legends
    redraw selection overlays
    preserve correct pointer coordinate mapping

Do not merely CSS-scale a canvas while leaving its hit-testing coordinates at
the old dimensions.

---

# 14. Fix direct artifact downloads

Files & diagnostics must offer direct download without requiring the artifact
to become the active preview first.

Refactor an artifact row into two logical controls:

    [ filename / open preview ]        [ download ]

Do not nest interactive controls illegally.

Download links must use the manifest-approved authenticated artifact URL with:

    download=1

Downloads must remain independent of preview size limits.

For example:

    200 MiB file
      preview refused because it exceeds safe preview limit
      download still allowed through the server/nginx delivery path

Do not fetch a large artifact into JavaScript memory solely to download it.

Keep the current attachment/sandbox protections for untrusted result HTML.

---

# 15. Expose downloadFile() to ResultStoryboards

Current Storyboards receive roughly:

    context.services.openFile(...)

Add a generic service:

    context.services.downloadFile(artifact)

Runner Storyboards must not construct server auth/download URLs themselves.

Use this for:

    Download CIF/PDB
    Download confidence source
    Download alignment
    Download matrix source

Keep scientific-source download separate from visual export.

---

# 16. Mol* rendered exports

With direct mounting, support appropriate Mol* client-side exports without an
iframe sandbox boundary.

At minimum investigate/implement:

    image/screenshot export

and, where Mol* provides a stable meaningful export API:

    scene/state export

Do not confuse a generated screenshot with the authoritative structure
artifact.

UI should distinguish:

    Download structure
    Export image

Original result artifacts remain the scientific record.

Do not block the main refactor on advanced scene export if Mol* does not offer
a stable/simple API.

---

# 17. Preserve ZIP archive behavior

Do not regress:

    Create ZIP
    Download ZIP

The archive must continue to include only manifest-approved result artifacts.

Direct per-file downloads and archive download are complementary.

---

# 18. Build shared scientific visualization primitives

The AlphaFold2-WebGPU interface is useful as a scientific visual grammar, not
as code to copy.

Create a small set of reusable scientific primitives.

Minimum set:

    CandidateSelector
    ScalarMetricGrid
    StructureViewport
    LocalConfidenceSeries
    PairMatrix
    AlignmentCoverage
    EntitySummaryTable
    ResultSelectionStore

Do not create a generic visual DSL.

Do not introduce a frontend framework solely for this work.

Rendering mechanics belong in shared code.

Scientific meaning belongs in the Runner Storyboard.

---

# 19. ResultSelectionStore

Add a small shared scientific selection state.

Minimum conceptual state:

    candidate
    entityA
    entityB
    token/residue

Example:

    {
      candidate: null,
      entityA: null,
      entityB: null,
      token: null
    }

Use this to synchronize:

    CandidateSelector
    StructureViewport
    LocalConfidenceSeries
    PairMatrix
    EntitySummaryTable

The Result Page / Storyboard remains the state owner.

Mol* is a renderer/interaction participant, not the application state owner.

Avoid circular state updates.

---

# 20. Candidate synchronization

Candidate switching must update all candidate-dependent views consistently:

    structure
    headline metrics
    local confidence
    PAE/PDE
    entity summary
    interface metrics

Never allow visible combinations such as:

    structure candidate 3
    PAE candidate 1
    pLDDT candidate 2

Reuse the existing generation/AbortSignal principles to reject stale async
responses.

---

# 21. ScalarMetricGrid

Implement adaptive headline metric cards.

Examples:

    mean pLDDT
    pTM
    ipTM
    ranking score
    aggregate score
    gPDE
    fraction disordered
    clash
    residue/token count
    entity count
    MSA depth

Runner Storyboards declare the available metrics.

Do not create empty `N/A` cards merely to force identical layouts across
models.

Do not infer unavailable metrics.

---

# 22. LocalConfidenceSeries

Generalize the pLDDT plot into a primitive that can represent:

    residue
    token
    atom-derived/token-aggregated confidence

Runner provides:

    values
    indexing
    entity boundaries
    units/scale
    title
    semantics

For standard pLDDT use the familiar confidence bands.

Do not assume every local-confidence value is a protein residue.

Verify ESMFold2's actual persisted scale before converting/displaying it as
0–100 pLDDT.

Do not silently rescale a questionable Runner contract.

---

# 23. PairMatrix

Extract the generic matrix rendering currently embedded in the AlphaFold 3
Storyboard.

Shared functionality:

    bounded canvas rendering
    colour scale
    legend
    axes
    entity boundaries
    responsive resize
    hover/click hit testing
    keyboard navigation
    selected-cell state
    accessible readout

Runner Storyboard supplies:

    matrix values
    meaning
    unit
    direction
    token/residue mapping
    entity mapping
    title

Expected uses:

    PAE
    PDE
    contact probability
    future pairwise confidence matrices

Do not hard-code PAE into the generic component.

---

# 24. Cross-view molecular interaction

Link scientific plots to Mol* through ResultSelectionStore and the
MolecularViewer adapter.

Desired interactions:

    local-confidence residue/token
        → Mol* highlight/focus

    PairMatrix cell
        → select/focus corresponding pair when meaningful

    entity-pair block
        → focus entities A/B
        → highlight interface/entity table state

    Mol* selection
        → update external selection state where mapping is reliable

Use stable entity/token identifiers.

Keep entity colours consistent across:

    Mol*
    confidence plots
    pair matrices
    entity tables
    MSA plots

---

# 25. AlignmentCoverage

Implement a bounded interactive alignment-coverage view inspired by the useful
concepts in alphafold2-webgpu:

    A3M parsing
    query identity
    position coverage
    paired/unpaired grouping where appropriate
    entity boundaries
    bounded/sampled row display

Only show it when an actual alignment artifact exists.

Do not infer alignment coverage from:

    MSA depth scalar
    PDF
    configuration flag

Do not claim generated/external MSA exists in the result unless the Runner
actually publishes it.

---

# 26. EntitySummaryTable

Support generic entity/chain-level interpretation.

Possible derived/native fields:

    entity ID
    length/token count
    mean local confidence
    mean pairwise error
    native interface metrics

Runner-native metrics may include:

    ipTM
    ipSAE
    pDockQ2
    chain-pair gPDE
    chain-pair pLDDT

Prefer native Runner metrics over re-derived approximations with subtly
different semantics.

---

# 27. Generic ndarray support

Boltz and Chai currently expose confidence evidence through NPY/NPZ-style
arrays.

Do not add independent NPY parsers to individual Storyboards.

Add one generic bounded ndarray access layer.

Preferred server-facing model:

    artifact
      ↓
    validated ndarray reader
      ↓
    dtype + shape + key
      ↓
    bounded numeric slice/data
      ↓
    scientific primitive

PairMatrix and LocalConfidenceSeries should not care whether their source was:

    JSON
    CSV
    NPY
    NPZ

Enforce element/byte limits.

Avoid shipping multi-million-element matrices blindly into browser memory.

---

# 28. Runner Storyboards — capability-driven implementation

Implement scientific pages from actual published output capability.

Do not branch generic Core code by Runner name.

## AlphaFold2

Target where artifacts actually exist:

    structure
    pLDDT/local confidence
    pTM
    PAE
    MSA coverage
    chain/entity summary

Do not invent recycle history unless per-recycle measurements were persisted.

## ColabFold AF2

Target:

    candidate structures
    mean pLDDT
    pTM
    ipTM/ranking when emitted
    local pLDDT
    PAE
    A3M/MSA coverage
    entity summary
    ipSAE/pDockQ2 when emitted

This should be one of the richest reference implementations.

## AlphaFold 3

Preserve all current AF3 PAE browser behavior.

Refactor the generic matrix drawing out of the AF3 Storyboard.

Target:

    candidate selector
    structure
    pTM
    ipTM
    ranking score
    fraction disordered
    clash
    local confidence when published
    PAE
    token/entity boundaries

Use AF3 token semantics for mixed systems.

Do not relabel every token as a protein residue.

## ESMFold2

Target:

    structure candidates
    mean pLDDT
    pTM
    ipTM
    local token confidence
    PAE

Add MSA coverage only if a real alignment artifact is intentionally retained
and published.

Verify confidence units.

## SimpleFold

Keep intentionally sparse:

    structure
    confidence only when emitted

Do not create empty PAE/MSA placeholders.

## Boltz

Target:

    structure candidates
    confidence score
    pTM
    ipTM
    complex pLDDT
    complex PDE
    local pLDDT
    PAE when published
    PDE when published

Use generic ndarray support.

## Chai-1

Target:

    ranked structures
    aggregate score
    pTM
    ipTM
    clash
    local pLDDT
    PAE
    PDE

Use generic ndarray support.

Do not reinterpret `msa_depth.pdf` as an alignment.

## RoseTTAFold3 / Foundry

First tighten the real output contract from fixtures/live output.

Then map:

    pLDDT
    PAE
    PDE
    summary confidence

Do not build a precise Storyboard against vague wildcard evidence filenames.

## OpenDDE

Add a dedicated rich Storyboard.

Headline metrics where emitted:

    pLDDT
    pTM
    ipTM
    gPDE
    ranking score
    clash

Full confidence where available:

    atom/local pLDDT
    token-level aggregation
    PAE
    PDE
    contact probability
    chain pLDDT
    chain pTM/ipTM
    chain-pair pLDDT
    chain-pair ipTM
    chain-pair gPDE

Do not browser-load enormous `*_full_data_sample_*.json` files wholesale.

Provide bounded projection/extraction when necessary.

---

# 29. File rail UX

Files & diagnostics remains the universal fallback.

Every artifact should expose:

    path
    size
    preview/open capability
    direct download capability

File preview failure must never disable download.

Scientific Storyboards do not replace the file tree.

Search/filter must continue to work after the row-control refactor.

Folder disclosure must remain keyboard accessible.

---

# 30. Keep result-view failures isolated

Any failure in:

    Mol*
    PAE
    pLDDT
    ndarray decoding
    MSA visualization
    Storyboard

must leave accessible:

    Files & diagnostics
    raw downloads
    ZIP
    run metadata
    reproducibility information

Do not allow one rejected Promise to replace the whole Result Page with an
error state.

---

# 31. Fresh Key Diagnosis small fix

Include the previously identified small authentication diagnostic correction.

`login_required()` currently can tell API users:

    Provide a valid Bearer token via the Authorization header

although API authentication also accepts:

    X-API-Key

Change the generic wording to something equivalent to:

    Provide a valid Bearer token or X-API-Key credential.

Keep the failure intentionally generic.

Do not reveal:

    whether a key exists
    whether a digest matched
    whether it was revoked
    whether the account was suspended

Do not redesign authentication in this work.

Add focused regression coverage for:

    valid Bearer
    valid X-API-Key
    invalid credential generic response

Preserve the existing Nginx/header full-stack behavior.

---

# 32. Build and CI integration

Update GitHub Actions so generated Mol* assets are reproducibly available to
the tests that require them.

Add Node setup only to jobs that need frontend asset generation.

Suggested browser-test preparation:

    setup-node 22
    npm ci
    npm run build:molstar
    install Python/test deps
    run Playwright

Do not make unrelated Runner scientific tests install Node.

Add a build contract that fails if:

    package-lock is out of sync
    Mol* asset build fails
    generated bundle is missing
    strict-CSP Mol* acceptance fails

Do not commit generated bundle output merely to make CI pass.

Docker full-stack acceptance must build the frontend through the same
production Docker path.

---

# 33. Third-party provenance

Mol* is MIT licensed.

Keep appropriate third-party attribution without vendoring its source tree.

Document at least:

    dependency name
    pinned version
    upstream project
    license

Optionally generate/include a small third-party notices/provenance record in
the server image.

Do not download an unpinned branch or `latest` during image builds.

---

# 34. Browser tests — direct Mol* lifecycle

Replace iframe-shell assumptions after direct mode is qualified.

Verify:

    one Mol* initialization
    first structure load
    second structure load reuses viewer
    representation switch
    colour switch
    confidence availability rules
    selection/focus
    theme change
    resize
    dispose

Verify switching candidates does not initialize another Mol* instance.

Verify leaving the StructureViewport disposes resources.

Verify reopening it initializes exactly one new instance.

---

# 35. Browser tests — fullscreen

Test real Fullscreen API behavior as far as Playwright/browser support allows.

Required observable contract:

    enter fullscreen
      → StructureViewport becomes fullscreen target

    same Mol* host remains mounted
    same PluginContext remains active
    same candidate remains selected
    same representation remains selected
    same colour remains selected

    exit via control / fullscreenchange
      → normal layout restored

Also test the state synchronization path used when the browser exits through
Esc.

Do not recreate the viewer during either transition.

---

# 36. Browser tests — rail geometry

Test actual layout dimensions rather than only state classes.

Expanded:

    rail has normal desktop width

Collapsed:

    rail becomes compact
    preview width increases materially

Expanded again:

    normal two-column geometry returns

Also test:

    tablet
    mobile

The collapsed desktop rail must not leave a blank ~20rem column.

---

# 37. Browser tests — resize correctness

Exercise:

    normal
      ↓
    rail collapse
      ↓
    fullscreen
      ↓
    exit fullscreen
      ↓
    rail expand

After every transition verify:

    Mol* canvas remains valid
    PAE hit-testing remains correct
    local-confidence chart geometry remains correct
    current selection remains valid

The existing AF3 PAE pixel/axis/chain-border/readout contract must remain
green after PairMatrix extraction.

---

# 38. Browser tests — downloads

Verify:

    direct file download exists before preview
    preview-size limits do not disable download
    selected artifact Download file remains functional
    Storyboard downloadFile() works
    ZIP request/download works
    source structure download works
    screenshot/export works if implemented

For large-file download tests, verify no unnecessary whole-file browser fetch
is performed.

---

# 39. Browser tests — scientific synchronization

Use a multi-candidate fixture.

Switch candidate:

    structure
    metric cards
    local confidence
    pair matrix
    entity table

must all represent the same candidate.

Simulate delayed responses to verify stale results cannot overwrite a newer
selection.

Test cross-view selection:

    confidence point → viewer selection
    matrix/entity selection → viewer focus

where mappings are available.

---

# 40. Security regression gates

After the refactor, all of the following must remain true:

    main application:
        NO unsafe-eval
        NO executable inline scripts

    untrusted result HTML:
        inert/sandboxed

    artifact download:
        manifest-approved paths only

    Storyboard:
        declared logical result IDs only

    large result data:
        bounded / paged / sliced

    Mol*:
        self-hosted build
        no runtime CDN dependency

Do not replace the iframe by weakening the main page's security boundary.

The ability to delete the iframe is a consequence of the upstream CSP fix,
not permission to loosen REvoCompute CSP.

---

# 41. Documentation cleanup

Update Result Page architecture documentation.

New ownership model:

    Result Page
        layout
        fullscreen
        downloads
        selection state

    ResultStoryboard
        Runner scientific semantics
        composition

    shared scientific primitives
        rendering mechanics

    MolecularViewer adapter
        molecular-viewer application contract

    Mol*
        molecular parsing/rendering backend

    FileViewer
        format-level artifact inspection

    Files & diagnostics
        universal raw-result fallback

Remove documentation that describes `/compute/viewer-shell` as required if it
has been removed.

Document the build-time Mol* acquisition path.

Document that production runtime does not require npm/CDN access.

---

# 42. Keep implementation small

Before adding a new abstraction, ask whether an existing boundary already owns
the problem.

Do not introduce:

    React/Vue/Svelte application migration
    generic visualization DSL
    generic event framework
    second permanent molecular viewer backend
    task-name conditionals in Core
    duplicated pLDDT/PAE implementations
    committed third-party Mol* bundle
    runtime npm/CDN dependency

Prefer a few explicit modules with narrow responsibilities.

The purpose of this refactor is to remove complexity, not move it.

---

# 43. Suggested implementation order

## Phase A — build foundation

- add package.json/package-lock.json
- pin Mol* 5.12.0
- add minimal custom Mol* bundle
- add build script
- integrate Node builder into server Docker image
- add CI frontend-build step

Do not touch ResultStoryboard behavior yet.

## Phase B — CSP qualification

- direct-mount Mol* in a small controlled host
- run under actual main-page CSP
- add browser acceptance
- investigate all violations
- decide direct vs thin iframe from evidence

Direct mode is preferred.

## Phase C — MolecularViewer migration

If direct mode passes:

- implement MolecularViewer adapter
- migrate existing structure preview behavior
- preserve warm viewer semantics
- migrate representation/colour/theme controls
- remove viewer-shell and iframe bridge

At this checkpoint existing structure viewing must be behaviorally complete
before adding new scientific panels.

## Phase D — workspace UX

- true parent fullscreen
- responsive resize
- reclaim width when file rail collapses
- direct file downloads
- Storyboard downloadFile()
- structure download/export
- preserve ZIP

## Phase E — shared scientific primitives

- ResultSelectionStore
- CandidateSelector
- ScalarMetricGrid
- StructureViewport
- LocalConfidenceSeries
- PairMatrix
- AlignmentCoverage
- EntitySummaryTable
- ndarray access

Extract AF3 PairMatrix only after generic tests protect its existing behavior.

## Phase F — Runner Storyboards

Suggested proving sequence:

    AF3
      ↓
    ColabFold AF2
      ↓
    OpenDDE
      ↓
    ESMFold2
      ↓
    Boltz / Chai
      ↓
    AlphaFold2 / SimpleFold
      ↓
    RF3 after exact output-contract verification

AF3 proves compatibility with an existing Storyboard.
ColabFold proves the complete AF2-like visual grammar.
OpenDDE proves mixed richer confidence data.
Boltz/Chai prove ndarray support.

## Phase G — regression cleanup

- Fresh Key Diagnosis wording fix
- tests
- docs
- delete obsolete viewer-shell tests/code
- review for dead iframe/CDN paths
- review comments referring to Mol* 5.11 behavior
- run full Python, browser, docs, and Docker gates

---

# 44. Final acceptance criteria

This work is complete when:

1. Mol* is acquired reproducibly at build time from an exact pinned dependency.
2. Mol* source/bundle is not vendored in git.
3. production runtime has no Mol* CDN dependency.
4. the main Result Page still runs without `unsafe-eval`.
5. direct Mol* mounting is used if the strict-CSP qualification passes.
6. if direct mounting passes, viewer-shell/iframe/postMessage Mol* plumbing is
   removed rather than retained indefinitely.
7. switching structure candidates reuses one live Mol* instance.
8. Files & diagnostics collapse actually gives its width to the Storyboard.
9. viewer fullscreen is true browser fullscreen and exits cleanly via the same
   control or Esc.
10. fullscreen/collapse/resize do not reset molecular state.
11. every manifest-approved artifact can be downloaded directly.
12. preview-size limits never masquerade as download limits.
13. Storyboards can request downloads without constructing URLs.
14. AF3 PAE behavior remains intact through the shared PairMatrix.
15. folding/OpenDDE Storyboards show only scientifically supported outputs.
16. structure, metrics, confidence plots, matrices, and entity selection remain
   synchronized across candidates.
17. Boltz/Chai arrays use one generic bounded ndarray path.
18. failure of Mol* or any scientific visualization does not remove raw
   downloads/files.
19. the Fresh Key auth diagnostic correctly mentions Bearer or X-API-Key
   without leaking credential state.
20. all relevant Python, browser, security, docs, and Docker full-stack tests
   pass at the final commit.