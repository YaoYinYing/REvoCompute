# Result View Plugin Contract

Result views are server-declared presentation capabilities. A task publishes an
ordered `result_views` list in its result manifest; the browser selects the
first view marked `primary` and keeps every other approved view available as a
tab. A view never discovers files on the host or invents scientific meaning
from a filename.

## Required boundaries

- The server owns the view identifier, display metadata, selector values, and
  artifact references in the manifest.
- A browser plugin consumes only the manifest data and authenticated artifact
  endpoints supplied by the result page.
- Large artifacts must use bounded metadata, range requests, thumbnails, or
  streaming. Plugins must not load an unbounded result into browser memory.
- Plugin errors are isolated. A failed view leaves the artifact list and
  download fallback usable.
- Controls and labels must be keyboard accessible and must not expose host
  paths, credentials, checkpoints, or operator-only configuration.

## Manifest shape

Each view has a stable `id`, a human-readable `title`, a `kind`, and optional
`description`, `primary`, `selectors`, and `artifact_roles` fields. Artifact
roles refer to entries in the manifest's approved artifact list. The server
validates identifiers and ordering before publication; clients should treat
unknown fields as opaque and ignore unsupported view kinds.

Current composition kinds include `candidate-collection`, `entity-table`, and
`evidence-bundle`, plus the `matrix` view documented below. Generic format
viewers remain available for text, tables,
images, structures, and authenticated downloads. An artifact whose format has no
generic viewer — standalone HTML, for example — falls back to an explanatory
message plus its authenticated download link; nothing is ever embedded as an
active document.

## Structure viewer

The Result Page owns layout, fullscreen, downloads, and scientific selection.
Runner ResultStoryboards own scientific composition, while shared primitives
own bounded rendering mechanics. Storyboards and primitives use the
application-facing `MolecularViewer` adapter; only that adapter calls Mol* APIs.

Mol* mounts directly in the parent page under the normal strict CSP. One viewer
instance stays mounted for the active structure viewport and is reused across
structure switches; changing the selected structure is a data-state change,
not a WebGL restart. Structure text is cached by task, artifact path, and
`sha256` with a bounded LRU, and immediate siblings are prefetched within the
same bound. A viewer or Storyboard failure does not remove Files & diagnostics,
direct downloads, ZIP delivery, or run provenance.

Structure artifacts carry a server-declared `confidence_encoding` when their
B-factor column holds per-residue pLDDT. The `Confidence` colouring is offered
only from that declaration, never from the file extension. See
[Structure Presentation Contract](../runner-guide/structure-presentation.md) for
what a Runner may declare.

## Matrix view

A view whose declared `plugin` is `matrix` renders through the shared
`PairMatrix` primitive rather than the generic table renderer. The browser
dispatches on `plugin` alone — never on a task or runner name — through the
result feature's view renderer registry; `ResultWorkspace` registers the matrix
renderer and no view renderer branch inspects the runner.

The primitive draws from the artifact's server-supplied bounded `table_url`,
which the server supplies only for table artifacts (`.csv`/`.tsv`). A matrix
view declared over a JSON `value_path` source — the shape used by the
AlphaFold, ColabFold, ESMFold2, and RFdiffusion3 fold tasks — has no bounded
page endpoint and therefore falls back to the generic renderer; it is not a
browsable matrix.

Table pages are fetched with `matrix=1` (an 8 MiB page and up to 512 value
columns plus the one leading row-label column, i.e. 513 total) and paged with
`offset`/`limit` (`limit` ≤ 500) until `has_more` is false. The assembled
element count is checked against the shared browser budget on every page, so an
unbounded matrix stops with a stated reason instead of exhausting memory. The
declared `mapping` supplies the axis titles (`x_label`, `y_label`), `unit`, and
the `row_labels_column` that names the first CSV column of row labels.

`scale: diverging` with `center: 0` is drawn with the symmetric range
`min = -m`, `max = +m`, where `m = max(|observed min|, |observed max|)`, so zero
sits on the ramp's neutral midpoint and negatives read as negative; a
diverging ramp runs negative → neutral → positive and a `sequential` scale keeps
a monotonic ramp, both selected per theme at draw time so a theme toggle
repaints. Resize, keyboard selection, element limits, and the readout come from
the primitive. A matrix that cannot be loaded (no bounded table URL, malformed
data, over budget, request failure) states the reason and falls back to the
generic renderer for its source artifact, which stays downloadable. A
renderer's teardown runs before the next view mounts, on fallback, and on
workspace teardown, so a replaced matrix stops observing theme and resize.

Storyboards that need to reach a task's declared scientific views rather than
re-implement them receive them in the frozen mount context as
`views: ReadonlyArray<ResultView>` and navigate through
`services.openView(viewId)`, which resolves the id in the manifest and opens the
plugin-aware view.

## Mol* build and provenance

`frontend/package.json` and `frontend/package-lock.json` pin `molstar` to the exact npm 5.12.0
artifact recorded in `frontend/provenance/molstar.json`: the upstream
[`v5.12.0` source tag](https://github.com/molstar/molstar/tree/v5.12.0), MIT
license, registry tarball URL, and SHA-512 package integrity. The server
image uses a Node 22 builder stage to run `npm ci`, typecheck, tests, and the
Vite production build, then copies only `frontend/dist` into
the Python runtime image. Generated assets, upstream source, `node_modules`,
and the Node toolchain are not committed or retained in the runtime image.

Production application pages load the hashed entry from `/static/app/`.
Dashboard, Create Task, and Result import the same `MolecularViewer` source as
a lazy Vite chunk when a structure view is opened. Runtime npm or CDN access is
neither required nor used. The emitted chunk is discovered through Vite's
manifest and qualified in a real browser under the main-page CSP, which
continues to exclude `unsafe-eval` and executable inline scripts.

The server never guesses hashed asset names or parses frontend build metadata.
After task access checks, the Result route serves the generated
`static/app/index.html` unchanged; Vite owns that document's hashed scripts,
stylesheets, and lazy Result/Mol* chunks. A missing entry document makes the
Result route unavailable rather than falling back to legacy presentation. The
frontend and production-image build contracts verify the generated entry,
manifest, application assets, and lazy Mol* chunk while rejecting
the Node toolchain, npm caches, frontend source, `node_modules`, and the
superseded Mol* vendor directory.

## Lifecycle

The result page creates one host registry for artifact and scientific views.
When the selected view changes, the host cancels pending fetches, increments
its render generation, and tears down the previous plugin before mounting the
next one. A stale response must never update a newer generation. Plugin code
should keep cleanup handles local and return a teardown function when it
registers listeners, timers, or WebGL resources.

## Adding a view

1. Define the smallest manifest contract and artifact roles needed by the
   scientific question.
2. Add server-side schema and output checks, including bounded size and range
   behavior.
3. Register the browser implementation in the existing view registry and keep
   the generic artifact/download fallback intact.
4. Add a manifest fixture and a browser contract test covering primary-view
   selection, ordering, error isolation, cancellation, and teardown.

Core remains the source of truth for generic validation and orchestration;
Runner-family plugins own their scientific vocabulary and result semantics. Do
not add task-name conditionals or duplicate scientific constants in
JavaScript.
