# Original Design — REvoCompute Experience Feedback (2026-11-12)

This is a durable intent record translated and consolidated from the user's feedback. It documents **what was requested**, while the linked developer guides describe **how the implementation should satisfy it**. Do not treat this as a new authority over Task scientific schemas.

## Network experience

The user reports slow structure loading on poor networks and proposes Nginx egress compression. **Upload compression means compression over the network**, not accepting user-supplied ZIP archives. The desired result is fewer transferred bytes without changing the scientific content, source format, immutable input digest or the user's upload workflow.

The dashboard/task panel should fetch Task entries incrementally/asynchronously rather than loading everything before interaction. The user asks specifically how search will work across not-yet-loaded entries: it must be server-side over the entire authorized history and combined with pagination.

Results need resumable downloads, and shareable URLs bearing expiring authorization so they can be pasted directly into IDM and comparable external download managers.

## CAVER input experience

The user wants XYZ point picking from Mol* via a graphical crosshair, residue/ligand COM selection and selected-residue centroid/COM-to-XYZ updates. They proposed a server-global Mol* read/write adaptation layer. The engineering design instead uses one **shared, typed molecular interaction interface** with viewer instances owned by their browser contexts; no server-global Mol* process is needed.

CAVER already has group support in UI; inspect interaction with start_residue_number and other start modes. Populate include/exclude residue IDs, residue names and atom numbers; residue-name choices must come from the current structure rather than a static list. Audit the actual supported CAVER directives before promising include semantics. Map the common random-seed component to the existing Runner seed.

CAVER should accept MD trajectories from common ecosystems: GROMACS GRO+XTC, Amber, NAMD, CHARMM, LAMMPS and OpenMM. Upload size for the first release should be limited to **100 MB for the original/decompressed trajectory**. A reusable Tool converts topology/trajectory to each consuming Runner's actual format requirements rather than placing every converter inside the CAVER Runner. Do not treat GROMACS pdb2gmx as an arbitrary trajectory converter.

## General form and molecular interface

Optional text fields can offer schema-authorized placeholders as examples, without changing defaults or validation.

The shared Mol* interaction interface should support:
- XYZ crosshair with explicit initial position (zero or structure center of mass);
- cube/box center XYZ and width/height/depth;
- selected residue and atom readback;
- synchronized viewer/form state.

The input structure inspection window and result visualization should have three modes:
- normal: embedded, current behavior;
- expand: enlarged floating window, with background blur;
- maximize: true fullscreen.

Keep the task submission banner pinned to the browser viewport bottom so a Task can be submitted without scrolling. Adapt it for desktop, tablet and mobile, including software-keyboard and safe-area behavior.

## Task reuse and results

Dashboard list entries and individual result pages should expose Clone & Reuse. Clicking it opens the Create Task screen with compatible parameters restored. Incompatible options and unavailable files must be visible in a warning and cannot silently be copied.

For result trajectories, provide browser-local reference/selection-based recentering and alignment similar in intent to GROMACS trjconv rotation/translation fitting. These transforms should not rewrite the original artifact. Users should be able to save a valid preview trajectory when the required output writer is supported by the browser.

## Follow-up requirements added during planning

The user observed there was no root CHANGELOG.md and no coherent application versioning. Existing Python and frontend package files contain static 0.1.0 metadata, but the repository has no formal application release series. Add a canonical version source, changelog, coherent build/deploy revision identity and controlled release procedure before releasing the other features.

## Design decisions that prevent architectural debt

- Maintain one server-authoritative Task schema and Core trust boundary.
- Avoid new duplicated Mol* classes or global server WebGL state; share typed contracts and scoped instances.
- Keep transport compression independent of scientific conversion, upload resumability and storage compression.
- Keep task history retrieval/search independent of live status updates.
- Keep platform release versions independent of Runner scientific image/model hashes and deployment identities.
- Keep maintainer squash-merge, product release and production deployment decisions explicit and separate.
- Require isolated PRs with validation rather than implementing all features inside one campaign branch.
