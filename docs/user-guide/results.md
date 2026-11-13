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
remains a normal disclosure below the result.

The molecular stage offers three display modes from its toolbar: **Normal**,
**Expand**, and **Maximize**. Expand presents the same stage as a modal overlay
that traps focus, closes with Escape, and returns focus to the control that
opened it. Maximize uses the browser's native fullscreen where it is available, and its
accessible name changes from **Enter fullscreen** to **Exit fullscreen** while
active; where native fullscreen is not available, the page says so and uses the
expand overlay instead. All
three modes reuse the already-mounted viewer, so the selected candidate,
representation, colour, camera, trajectory frame, overlays, and scientific
selection survive when the mode changes. The mode buttons are keyboard
reachable, and the stage reflows for narrow screens and both themes.

Trajectory views add a preview-only fitting row. Choose the fit atoms (the whole
frame or the current typed selection), a reference frame, and either **Center
only** or **Fit and preview**. The browser fits each frame to the reference with
a weighted rigid-body least-squares transform in a background worker and applies
a reversible display transform; **Reset preview** restores the exact source
coordinates and **Cancel fit** stops a running job. The reference and selection
controls stay locked for the duration of a fit, and a completed preview is
always labelled and exported with the reference it was actually fitted to. The
reported RMSD is a preview metric on the fit selection, not simulation dynamics
or a stability claim. Each frame's own declared unit cell is used, with a
warning when positions span it; the periodic check covers the whole topology at
the reference frame and the fit selection on every frame against that frame's
cell, and the exported sidecar states the exported frame's own cell. The browser
never unwraps coordinates, reconstructs chains, or changes topology, and such a
wrapped preview carries no scientific claim. **Export PDB + sidecar** writes the
current aligned frame and the JSON provenance record together. The export is a
new local derived artifact, not a server-published result and not authenticated
Tool output, and a text PDB is never given a binary trajectory extension. A
topology the fixed PDB columns cannot represent is refused rather than
truncated.

The manifest records a *technical* output check: configured files are present,
non-empty, and structurally mappable. That check does not establish scientific
or experimental validity. Task-owned limitations are recorded alongside the
result and should be read before drawing conclusions.

## Local result folders

A downloaded ZIP can be extracted and read again without uploading it. Choose
**Local result** in the Compute navigation, then **Open local result folder** and
pick the extracted folder — the one containing `manifest.json`.

- The page is marked **Local** and shows the folder's name instead of a Task
  id. The Task the archive came from is listed in the run record as *Exported
  from task*, as provenance only.
- Every declared file must be present and match the size and SHA-256 the
  manifest records; otherwise the page names the files that differ and opens
  nothing. Files past the browser's hashing budget — and every file on a
  non-secure origin, where the browser cannot hash — are checked by size only,
  and the page says so.
- Declared views, files and downloads work as they do for a remote result, and
  a download keeps the file's own name. A declared Storyboard is named but not
  run: its code is not loaded from a folder, so the declared views are shown
  instead. A citation links only to an `https:` address or a DOI, so a crafted
  folder cannot hand you an executable link.
- Nothing is uploaded and no Task, Runner or Tool is started. The browser asks
  for the folder again after a reload.

See [Local Result Workspace](../developer-guide/local-result-workspace.md) for
the archive contract and its limitations.

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
