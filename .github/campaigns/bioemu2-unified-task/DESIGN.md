# BioEmu2 — unified scientific Task contract

**Status:** DESIGN ONLY · Draft PR · implementation is not authorized yet.
**Baseline:** `21b62a2c7fd6ce4862d05cf88fbdd111ac0af6d4` (main after #147 and #148).
**Maintainer decision:** one visible Task **BioEmu2** (`id: bioemu2`), required System YAML, optional starting mmCIF at the Task level, with a single form mode selector: `equilibrium`, `structure_prediction`, `propagate`. Deprecate FASTA as a submitted input role. Do not revive the old three-Task presentation.

## Source-of-truth reconciliation

The deployed BioEmu2 SIF installs microsoft/bioemu2 at `6d1ca744fa8ed285edafae7b98da65205bf00fd3`. Its `src/bioemu2/cli.py` requires `--system` or `--pdb-id` for `sample-equilibrium` and `predict-structure`; `propagate` requires `--x0-cif` and may infer its system from that CIF. This Task intentionally strengthens upstream's optional-YAML inference route: **all three modes require explicit System YAML**, with `--x0-cif` only for propagation. The current equilibrium/structure `sample.py` Python adapter wraps FASTA in `System.from_description(proteins=[...])`; that can run single proteins but misrepresents the full upstream molecular system contract. Distinguish *bad public contract* from *wholly nonfunctional executable*.

JAAG `YaoYinYing/JAAG` already implements a `bioemu2` System YAML serializer and exposes a REvoCompute builder via `integration/revocompute/jaag-builder/index.js` and `dist/jaag-builder.revo.js`. JAAG's README states that contact conditioning is not currently collected and custom file-backed/userCCD components are rejected. Respect those limitations; do not falsely expose capabilities or relax server-side acceptance.

## One user-facing Task, explicit scientific modes

| Property | Contract |
| --- | --- |
| Family ID | `bioemu2` (unchanged) |
| New Task ID / display name | `bioemu2` / **BioEmu2** |
| Required input role | `system`: exactly one YAML/YML, `supporting_data` or a reviewed more specific logical validator |
| Optional input role | `starting_structure`: zero or one all-atom mmCIF; never a substitute for the YAML |
| Scientific mode | Task parameter `mode`: `equilibrium` (default), `structure_prediction`, `propagate` |
| Mode-specific rule | `propagate` **requires** starting mmCIF; the other two modes **reject** supplied starting mmCIF rather than silently ignoring it |
| Sampling | Keep existing normalized `sampler`, `num_samples`, `seed`, `physicality_mode`, `num_steps`, and `batch_size` where pinned upstream supports them |
| Propagation-specific | `lag_time_ns` mandatory/defaulted only for `propagate`; do not send it in other modes |
| CLI mapping | `equilibrium -> bioemu2 sample-equilibrium --system ...`; `structure_prediction -> bioemu2 predict-structure --system ...`; `propagate -> bioemu2 propagate --system ... --x0-cif ...` |

**Do not repurpose** REvoCompute's graph-level `execution_modes` unless the present server and UI contract proves it models scientific modes; the simplest solution is a schema enum `parameters.mode` with Task-specific conditional rules. Conditional file-role cardinality is not currently represented by the shared `NamedFileRole` (static min/max). Introduce a small **declarative server-enforced input constraint** tied to the schema mode, with an OpenAPI/browser projection, or an equivalently explicit validated cross-role rule. Do not implement a UI-only requirement, a BioEmu2-specific permission bypass, or a second Task catalog. Update `docs/runner-guide/adding-a-runner.md` to allow this proven conditional-input exception to the usual split-Task guidance.

## Workflow and scientific identity

The form displays **BioEmu2** once, a mode selector, System YAML upload and a JAAG System-builder action. The CIF field is shown/required **only for propagation**. Switching away from propagate must visibly warn that an already selected CIF will be discarded and must not submit it. JAAG builder output must bind to the canonical `system` role, and an uploaded YAML must remain an equal first-class path. Pin the copied/packaged JAAG integration revision, checksum and license; no remotely executed mutable UI script. Do not duplicate JAAG's complete form in a second custom implementation. The server's own role validation and Task snapshot remain authoritative.

At preflight: validate upload byte/format limits, roles and mode-dependent requiredness before submitting a scheduler job; reject missing/extra CIF. The Runner must parse the YAML using the **pinned upstream** `System.from_yaml` / `load_system_and_contacts`, including scientific syntax, chain IDs, contacts/bonds, and fail closed for malformed or unsupported entities; no arbitrary YAML object construction on the Server. For propagate, enforce atom mapping/order and compatibility between the exact YAML and mmCIF **before model load**. Reject terminal OXT mismatches and loss of explicit bonds; do not silently alter chemistry or invent atoms.

Reuse #148 CCD retry + verified task-local HF steering asset without forcing all modes to depend on it. Audit whether ligand steering is also exercised by other modes for liganded Systems before freezing the final asset rule; **do not assume the original propagation-only distinction remains correct after expanding the input model**.

## Results, migration and provenance

Unify the required result files where actually common: `topology.cif`, `samples.xtc`, `system.yaml`, `physicality.json`. Retain `command.txt` as an optional diagnostic if only some CLI modes produce it; remove the new Task's FASTA echo requirement. Match mode-specific frame semantics (independent equilibrium samples, predicted folded structures, or propagation endpoints—not continuous MD). Show selected mode and file hashes in the Task snapshot, metadata and result page.

Do not rewrite historical DB Task IDs. Historical `bioemu2_equilibrium`, `bioemu2_structure_prediction`, and `bioemu2_propagate` records, artifacts, archive links and result views must remain readable. New submissions use only `bioemu2`. Inspect registry/deprecation behavior and migrations before removing the old Task manifests; if compatibility needs hidden legacy descriptors, they must not appear as selectable new Tasks.

## SIF and promotion

The current image has the pinned BioEmu2 CLI/API. The contract redesign targets Task manifest, runtime overlay, UI, Core declarative input-condition checks, validation, provenance and tests. **Do not rebuild the SIF** unless pinned-source/dependency/ABI evidence proves a build-input change. Any Runner manifest/overlay update invalidates bundle identity and live-test receipt. Preserve maintainer-only promotion; #149 is not a production deployment.

## Acceptance and regression evidence

Use independently reviewed fixtures made by the *actual JAAG serializer*, validated against the pinned upstream parser. Test single protein, two-chain system, a supported ligand, modified residues, representative disulfide/explicit contacts, invalid YAML, unsupported CCD, wrong chain IDs, broken bond, CIF/YAML atom mismatch and a valid ligand-bearing propagate case. The test matrix is **all 3 modes × (YAML only / YAML+CIF / CIF only / neither)** with required/forbidden behavior; test submissions through the real server and CLI, not only mock `bioemu2`. Preserve units, molecular composition, frame semantics and output digest audit. Include headless/mock fast tests, real pinned-upstream import/CLI smoke on available SIF, one authorized live-science receipt before READY and JAAG builder browser interaction + screenshots. Do not claim a scientific pass from fake upstream fixtures.

## Non-goals and dependencies

No upstream version bump, new GPU image, generic user-auth changes, arbitrary script execution or unrelated Runner rewrites. This PR can start independently of the experience campaign's frontend viewer work, but touches shared input role validation; coordinate with subsequent form-related PRs to avoid concurrent edits. Complete the #148 production provisioning and live receipt separately.

## Review controls

Single-PR Campaign Protocol, maximum **4 concurrent agent slots**: Commander, Owner, Independent Adviser, Examiner; appoint a *new* independent Acceptance Auditor after a slot releases. All technical findings and accepted risks belong on this PR; exact-head CI, Examiner and Adviser evidence precede Auditor PASS. Only maintainer can squash-merge, tag, publish or deploy.