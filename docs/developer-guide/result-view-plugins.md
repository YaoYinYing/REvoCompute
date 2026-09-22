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
`evidence-bundle`. Generic format viewers remain available for text, tables,
images, structures, and authenticated downloads. An artifact whose format has no
generic viewer — standalone HTML, for example — falls back to an explanatory
message plus its authenticated download link; nothing is ever embedded as an
active document.

## Structure viewer

One viewer instance stays mounted for the whole result session and is reused
across structure switches; changing the selected structure is a state change,
not a viewer restart. Structure text is cached by task, artifact path, and
`sha256` with a bounded LRU, and immediate siblings are prefetched within the
same bound.

Structure artifacts carry a server-declared `confidence_encoding` when their
B-factor column holds per-residue pLDDT. The `Confidence` colouring is offered
only from that declaration, never from the file extension. See
[Structure Presentation Contract](../runner-guide/structure-presentation.md) for
what a Runner may declare.

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
