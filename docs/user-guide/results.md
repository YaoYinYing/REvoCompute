# Results

When a task reaches `finished`, the server has atomically published
`manifest.json` in the uncompressed result tree. That manifest is the contract
between the runner and every client: it lists the artifacts the task produced,
their roles, the scientific views the server resolved, and the run provenance.

## Reading results

- Individual manifest-listed files are previewed or downloaded through
  authenticated endpoints, and can be streamed by Nginx.
- A full ZIP is an optional asynchronous cache created only after an explicit
  archive request. It contains only files published by the manifest and is not
  part of task completion.
- All manifest-approved artifacts remain searchable and individually
  downloadable under **Files & diagnostics**, which is the universal fallback.
- Scientific views are composed from the manifest; a task without a migrated
  view still exposes its artifacts through the generic download path.
- Formats without a viewer — standalone HTML reports in particular — are
  download-only. Runner-produced HTML is never embedded or executed as an active
  result page; opening one shows a short message and a download link.

## Structure viewing

Structures open in a single viewer that stays mounted while you move between the
files of one result, so switching from one model to the next does not reload the
viewer. Representation (`Cartoon`, `Cartoon + ligand`, `Sticks`, or `Surface`)
and colour (`Chain/entity`, `Rainbow`, or declared `Confidence`) are independent
controls. `Confidence` appears only when the Runner declared that the
structure's B-factor column holds pLDDT; it is never inferred from the file
type. Recently viewed structures are cached in the browser, and the immediate
neighbouring structures in the file list are prefetched, both within a bounded
limit. Structure download retrieves the authoritative result artifact; image
export creates a rendered picture and is labelled separately.

On wide screens, closing **Files & diagnostics** gives that width back to the
scientific view while leaving a compact reopen control. On smaller screens it
remains a normal disclosure below the result. Fullscreen includes the
REvoCompute structure toolbar and preserves the selected candidate,
representation, colour, camera, and scientific selection when entered or
exited.

The manifest records a *technical* output check: configured files are present,
non-empty, and structurally mappable. That check does not establish scientific
or experimental validity. Task-owned limitations are recorded alongside the
result and should be read before drawing conclusions.

## Where the details live

- [Task States and Result Delivery](task-states.md) — lifecycle states, what
  `finished` guarantees, and how views are composed.
- [Scientific Result Inventory](../developer-guide/result-inventory.md) — the
  per-task artifact classes, declared semantics, and presentation.
- [Result View Plugin Contract](../developer-guide/result-view-plugins.md) — the
  server-owned composition boundary for new views.
- [Structure Presentation Contract](../runner-guide/structure-presentation.md) —
  when a structure may declare confidence colouring.
- [Server API](../reference/server-api.md) — the status and result routes.
