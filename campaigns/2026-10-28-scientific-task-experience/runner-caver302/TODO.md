# TODO — feat(runner): headless CAVER 3.02 tunnel analysis and spatial input

> **Status:** CPU-side Runner implemented on branch `campaign/2026-10-28-runner-caver302`.
> SIF build, `%test`, authentic CAVER 3.0.2 execution on 1SUO and target-host live acceptance are done;
> the latest acceptance PASSED at 3a88c2f (receipt `38444ad3….receipt.json`, Slurm job 407515) and the
> candidate is staged awaiting promotion. Both R1 reviews returned R1_BLOCK at 782447f; all blocking
> and major items are fixed through 3a88c2f, and a fresh live acceptance is required at the final
> fix-round head. The viewer remains deferred to PR #117. See the
> local `IMPLEMENTATION_STATE.md` for exact provenance and test evidence.
> **Initial main:** 17e80ed1dbd00f1389f3ec7047e5661b85ed52eb. Re-check exact main and PR head before any coding/review.

## Goal
Integrate official upstream CAVER 3.0.2 CLI as an online CPU Runner with a scientifically meaningful interactive molecular starting-point selector, trajectory inputs, tunnel geometry and statistics; prove that Core can validate the UI-derived input.

## Grounded context
- Official upstream distribution specified by maintainer: https://www.caver.cz/fil/download/caver30/302/caver_3.0.2.zip — do not use or redistribute the PyMOL fork's bundled JAR.
- Official CAVER site lists CAVER 3.02 as the current command-line release; CAVER supports tunnels in static structures and multiple trajectory snapshots, with clustering and geometric profiles.
- User fork https://github.com/YaoYinYing/caver-pymol-plugin is a GPL-3.0 workflow/UX reference only; no direct PyMOL/headless-GUI dependency.
- Official CAVER CLI invokes Java with -home, -pdb input directory, -conf file, -out results; exact archive layout and parameter names must be inspected from the pinned downloaded distribution before implementation.
- The upstream archive could not be fetched in this design environment. DO NOT invent its SHA256, contents or source/binary compliance facts.

## Implementation checklist
- [x] Download CAVER 3.0.2 **only from the exact upstream maintainer-provided URL** as a pinned build input, never from the plugin repository or transient mirror. Record retrieval date, archive byte count, checksum (SHA-256) and archive file inventory in documented provenance; verify reproducibly. (2026-10-28T15:46:08Z..15:51:47Z, 33,303,568 bytes, `2d819541…0ee1e`, 1,146 members; see `upstream.json`.)
- [x] Inspect upstream ZIP before extracting: enforce safe archive extraction, zip-slip/symlink constraints, expected JAR/lib/home/config presence, license and third-party notices. If official URL is inaccessible or archive differs, STOP with a transparent blocker; do not silently substitute binaries. (`%post` and the audit script refuse unsafe members; all expected members present.)
- [~] Review applicable GPL-3.0 obligations for the official JAR, dependency libraries and combined distribution. Preserve license notices and source-availability provenance; downloading direct from upstream does not by itself waive redistribution duties. (Reviewed: CAVER GPL-3.0, kd LGPL-3.0, Weka ml.jar GPL-3.0. **Unresolved:** Sun `vecmath.jar` is JRL/JDL and is not mentioned by `license.txt`; `AverageLinkClustering.jar` has no separate notice. No compliance claim is made.)
- [x] Build a headless Java Runner Family with versioned JRE/JAR/libs, CPU-only default resource policy, bounded Java heap (`-Xmx`), timeout, snapshot count limits, temp file isolation, read-only distribution mount and no unintended network. (Direct Apptainer build of `caver302.def` succeeded: 114,708,480 bytes, SHA-256 `ce3c6746…c759be`, `%test` passes on `openjdk 1.8.0_504`.)
- [x] Implement initial Task `CAVER` / `Transport tunnel analysis` accepting PDB (and other types only through validated conversion) plus optional series of snapshots with stable atom/residue mapping; define ordering/frame indexing and input limits. (PDB only; reference = frame 1, uploads follow in order, 0..50 snapshots, topology checked.)
- [x] Introduce **canonical typed spatial selectors** for the Task form: manual x,y,z in Å, selected atom, residue/atom group centroid, ligand/cofactor center, and optionally manual pocket marker; every mode resolves to a visualized immutable coordinates+selection provenance record. (Typed controls only; resolution and provenance implemented.)
- [ ] Provide molecule viewer interaction for click-to-pick atoms/residues, multi-select, hovering tooltip, numerical coordinates, chain/insertion-code resolution, selection highlight and a draggable or editable 3D start-point marker when supported. Avoid speculative claims about geometry before reading the input structure. (Deferred: PR #117 owns the create-task surface.)
- [x] Expose relevant tunnel settings as validated typed controls: shell/probe radius, clustering threshold, maximum tunnels/frames, start-point optimization and residue exclusions. Use exact upstream parameter vocabulary, default values and constraints; do not invent one-to-one mappings to PyMOL UI names. (38 parameters, upstream names/defaults/constraints; average-link clustering is the only mode CAVER can publish, so no clustering-algorithm choice is offered.)
- [x] Translate spatial selections to a canonical server-owned start-point definition; verify selected atom identifiers against source structure, enforce Å units and coordinate bounds, and make view->form->configuration roundtrip lossless. (Typed selection -> upstream `starting_point_*`; viewer roundtrip deferred.)
- [x] Generate the upstream CAVER config in a confined task directory from an allowlisted parameter model. No user-supplied arbitrary file path/config directives, absolute template paths or Java arguments. All Runner execution must use safe argv not shell evaluation.
- [x] Inspect and model CAVER outputs as strict files/roles (tunnels, profiles, clusters, bottlenecks, statistics, optional frames, actual version/config and complete logs), discovering real output names from the authentic ZIP/tool, not guessed globs.
- [ ] Render tunnel centerlines/sphere or surface representations overlayed on the input structure when feasible; show geometry and metrics like minimum radius, length, curvature, throughput and cluster frequency with scientifically correct units and definitions. (Metrics are published as tables; the 3D overlay needs a viewer and is deferred.)
- [x] Support static single structure as MVP and bounded multiple-snapshot inputs with coherent clustering. Do not pretend arbitrary MD trajectories in XTC/TRR are supported unless a validated converter is deliberately added. (PDB snapshots only; no XTC/TRR claim.)
- [x] Ensure ResultManifest provenance links source structure, selected starting site, parameter snapshot, CAVER release hash, JAR inventory, frames, tunnels and cluster identifiers. No remote or pre-signed arbitrary file URLs. (`provenance.json`/`summary.json`.)
- [~] Add an approved example dataset with known tunnel geometry and parameter defaults (upstream sample or license-reviewed fixture), plus screenshot-based browser interaction evidence. (Smoke case uses 1SUO + HEM; parser fixtures are authentic upstream guided-example output. Screenshots deferred.)
- [x] Treat the viewer as an input-control projection; Core validates and signs the resulting scientific coordinates. Define reusable form capability only if it is genuinely generic to other structural Tasks, otherwise keep it Runner-owned. (Typed parameters only; no new viewer capability.)
- [x] Use project visual language, not a copy of Tamarind AutoDock box UI. Reference its intent (direct molecular spatial selection), not its assets or implementation. (No UI added.)

## Acceptance / tests
- [x] Verify upstream distribution URL and pinned SHA-256 at build; altered or missing ZIP must fail. Preserve GPL/third-party licensing evidence and upstream citations. (Enforced in `caver302.def` `%post`/`%test`; the build itself is pending the live window.)
- [x] Run `java` CLI in candidate SIF on a known CAVER sample and verify completed tunnel/stats outputs with authentic files, not only process exit 0. (Real 1SUO runs in the SIF: a serial-only `starting_point_atom` exits 0 with zero tunnels and a swallowed NPE, while `starting_point_atom <serial> <x> <y> <z>` produces the full output set in 3.72 s; success is judged from the output tables. Normalization of that real output succeeds.)
- [ ] Browser tests of manual XYZ, atom click, residue centroid, ligand pocket and edits, including mutation of the selection, empty/malformed selection, chain ambiguity, altloc/insertion code and high-DPI/mobile layouts. (Deferred with the viewer.)
- [x] Roundtrip test: click selection → form state → snapshot → generated CAVER config → actual result; compare coordinates and units to original structure with documented tolerance. (Typed selection → config → authentic-output normalization is covered end to end with a contract stand-in; the click step is deferred.)
- [x] Reject huge/NaN/Inf coordinates, missing residues, frame inconsistency, unsafe archives, Java/config injection, path traversal, unbounded heap/frames and malicious structure names. (Fast tests cover each rejection path.)
- [x] Check CPU resource estimation, cancellation, memory OOM, missing JAR, non-zero tool exit, zero tunnels and incomplete output; no false-success task. (Bounded `-Xmx`, internal timeout, missing-JAR preflight, nonzero-exit and incomplete/empty-output failures tested. No resource-estimation model is declared.)
- [x] Verify tunnel cluster/profiles metrics against a pinned upstream example, scientific units and trajectory frame labels, ResultManifest and storyboard render. (Parsers are tested against the distribution's guided-example output with explicit Angstrom units; storyboard/render evidence is deferred.)
- [ ] Run existing server/manifest validations, doctor --strict, scientific smoke, frontend screenshot/keyboard regression and exact-head CI with evidence. (Fleet and fast suites pass locally; doctor/scientific smoke/CI run on the pushed head.)
- [x] Run one target-host live acceptance through the public API and record walltime, CPU time, host-memory peak, published artifacts and receipt. (PASS on Slurm job 407515 with receipt `38444ad3….receipt.json`, which records the case walltime, CPU time, host-memory peak and the published artifact match; `readiness/caver302.json` was refreshed with `CANDIDATE_AWAITING_PROMOTION`.)

## Non-goals
- No PyMOL server dependency, embedded JAR copied from the plugin repo, or privileged direct GUI connection.
- No blind identification of CAVER as docking or free energy prediction; it computes pathways and their geometry.
- Do not claim GPL compliance from mere presence of an upstream download URL; verify full distribution duties.
- No unrestricted host file access, arbitrary Java options or unreviewed trajectory converters.

## Dependencies
Independent Runner. The 3D spatial input capability must be reviewed for architecture ownership by the independent Adviser; may later be reused by docking or active-site Tasks.

## Campaign protocol
- [ ] Read CLAUDE.md, LONG_TASK_HANDLING.md and Single-PR Campaign Protocol, then this complete TODO, before editing.
- [ ] Commander appoints one PR owner. Independent Campaign Adviser checks science, architecture and merge-readiness without becoming worker.
- [ ] Maintain an IMPLEMENTATION_STATE.md when implementation begins, preserving milestone status, exact-head tests and blockers.
- [ ] Detailed findings, CI and scientific evidence belong in the PR thread; chat report is short merge/no-merge, blockers and owner.
- [ ] Before ready-for-review, prove scientific behavior in authentic execution, security boundaries, input/result contract and browser UX.
- [ ] Maintainer alone decides squash-merge; no agent merges automatically.
