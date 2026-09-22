# Platform Trust Implementation State

## Science Input Contracts and Runner Batch

- Branch: `feat/scientific-input-contracts-runner-batch`
- Design: `TODO.md` (scientific input contracts and the next Runner batch)
- Base: `0916a3d`

### Completion checklist

- [x] Separate physical serialization from scientific dialect in Core input validation.
- [x] Repair the Chai-1 rich-FASTA validation bug without loosening the standard FASTA alphabet.
- [x] Restore upstream Boltz's three MSA modes (local, explicit single-sequence, online server).
- [x] Upgrade OpenDDE to 1.1.1 and ColabFold to 1.6.3 with real provenance and conservative kernel defaults.
- [x] Live-validate and enable RFdiffusion2 on the target host.
- [x] Live-validate Foundry (all three task types) on the target host.
- [x] Live-validate GeoDock on the target host.
- [ ] Audit the pinned AlphaFold 3 / AlphaFold 2 revisions (done: no upgrade available; see below).
- [ ] Promote the prepared SIFs and restart in `--mode=prepared`.
- [x] Adapt the new pocket/validation/docking Runner batch (P2Rank, fpocket, DeepPocket, MolProbity, FRODOCK).
- [x] Record the BoltzGen and Pallatom-Ligand intake outcome (deferred; see below).
- [x] Suspend Boltz and FRODOCK with their defects recorded (see "Suspended families").
- [ ] Run the final gates and open the pull request.

### Input dialects

Two bugs exposed one design error: Core dispatched on the file extension alone, so a
serialization's syntax was treated as its scientific meaning. Validation now separates
physical format, logical type, and Runner dialect.

**Chai-1 rich FASTA.** Chai reuses FASTA framing for protein, RNA, DNA, ligand SMILES,
and glycan entities, so modification brackets and SMILES punctuation are legal input that
the strict protein alphabet rejected (`FASTA sequence contains invalid character '('`).
A Core-owned `chai_entity_specification` dialect now checks framing, supported entity
types, the name label, balanced and non-empty modification blocks, non-empty records, and
size ceilings, and leaves canonical semantic parsing to Chai. `validate_fasta` is
unchanged, so standard protein FASTA stays strict and the same punctuation is still
rejected for every other FASTA role.

**Boltz MSA.** The integration omitted `--use_msa_server` and therefore accepted only a
local alignment or `msa: empty`, which did not match upstream's real capabilities
(`RuntimeError: Missing MSA's in input and --use_msa_server flag not set.`). A
`boltz_specification` profile now covers both of Boltz's serializations — YAML and the
`>CHAIN|TYPE[|MSA]` header FASTA — and `use_msa_server` restores the third mode. A local
reference must be `empty` or a confined relative path and must name an uploaded asset;
the Runner re-resolves it against the server-resolved manifest before invoking the CLI,
so an unresolvable reference fails before expensive execution. Explicit single-sequence
inference stays explicit: nothing injects `msa: empty`.

Dialect selection is a keyword on the existing dispatcher, `validate_input_file(path,
filename, *, logical_type=None)`, with `_DIALECTS` mapping `(format, logical_type)` to a
reviewed Core parser. Runner families still cannot register executable validators in the
trusted boundary, and no runner name appears in Core.

### Runner upgrades

**OpenDDE 1.0.3 → 1.1.1** (2026-09-02). The dependency set is identical between the two
releases, so no new CUDA/cuEquivariance/Triton exposure is introduced. The PyTorch
triangle-kernel flags and `--enable_fusion false` still exist and remain required: the
production image deliberately ships no C toolchain for the runtime Triton launcher. The
writable-snapshot workaround was retained on verified evidence rather than on upstream
prose — 1.1.1 redirects its MSA preprocessing JSON under the output directory, but
template search still writes beside a path derived from user JSON and still fetches
missing mmCIFs beneath `$OPENDDE_ROOT_DIR/search_database/mmcif`. `model_name:
opendde_abag` was dead in both releases (`model_registry` has only `opendde_v1`), so the
antibody-antigen checkpoint is now selected through a `checkpoint` parameter that maps to
`--load_checkpoint_path`.

**ColabFold 1.6.2 → 1.6.3** (commit `84c27d9cc500489fd9b97545d2325b9d00f251d5`,
2026-09-14) with `alphafold-colabfold==2.3.20` and OpenMM 8.5.2. The NVRTC 12.6 pins stay:
the OpenMM 8.5 CUDA platform still compiles PTX at runtime and clamps the architecture
through `nvrtcGetSupportedArchs`. `--use-fast-kernels`, `--kernel-backend`, and
`--compile-mode` are exposed with conservative defaults and are never enabled implicitly.
1.6.3 emits ipSAE/pDockQ2 for complexes only; they are preserved in the upstream score
files and flattened for the result protocol by a Runner-owned normalizer that runs after
the structure check, so a missing interface score never discards predictions. ColabFold2
preview was out of scope and was not added.

**AlphaFold 3 and AlphaFold 2: audited, no change.** AlphaFold 3 is pinned to
`c0f97eda2f1f482fd94d3a38bece18c7069b4a5c`, which is the current tip of upstream `main`
and 16 commits *ahead* of the newest stable tag `v3.0.4`; the runner depends on
`--hmmsearch_n_cpu`, which does not exist at that tag, so the newest release is a
downgrade and the pin is correct. AlphaFold 2 consumes a post-`v2.3.2` fork head
(`e5c2cdd59c87df41d1f0b9e49c3820a267726766`) whose `--run_stage` staging patch applies to
that tree and no other; DeepMind has published no tag since `v2.3.2` (2023-03-27), so
there is no stable release to move to. No checkpoint changed for either family, the
result selectors still resolve against the real output layouts, and the Core
`alphafold3_specification` profile remains a correct superset for the pinned revision.

### Runner enablement

Live acceptance ran through the production API, worker, Slurm, and Apptainer path; every
SIF rebuild used `--use-proxy`, and no foreign job was interrupted at any point.

| Runner | Cases | Receipt | Evidence |
| --- | --- | --- | --- |
| RFdiffusion2 | 2/2 | `1789916975004238246-smoke.json` | Slurm 20193 (96.3 s, 4251 MiB, 81%), 20201 (94.6 s, 2205 MiB, 52%) |
| Foundry | 3/3 | `1789924356900992219-smoke.json` | Slurm 20685 (rfd3), 20693 (rfd3na), 20701 (rf3, 3483 MiB) |
| GeoDock | 1/1 | `1789925268248807377-smoke.json` | Slurm 20764 (76.0 s, 3183 MiB, 46%), GPU ledger settled |
| DeepPocket | 1/1 | `1789965152526850883-smoke.json` | 598.3 s on the real pinned CUDA stack |
| P2Rank | 1/1 | `1789967964393780736-smoke.json` | 253.1 s |
| fpocket | 1/1 | `1789966528066848484-smoke.json` | 250.5 s |
| MolProbity | 1/1 | `1789976300550039451-smoke.json` | 204.4 s, provisioned rotarama + GeoStd |
| FRODOCK | 1/1 | `1790002848761056235-smoke.json` | 116.1 s, five ranked poses |

RFdiffusion2 is enabled in the deployment env and remains gated by
`rfdiffusion2_academic_only`. Foundry and GeoDock have current PASS receipts whose
`sif_sha256` match the staged `.sif.next` files; promotion is the next step. The
pocket/validation/docking batch has PASS receipts for all five families but is not
yet in `ENABLED_TASKRUNNERS`.

**Resource-marker defect.** The RFdiffusion2 run initially failed with
`RESOURCE_OBSERVATION_FAILURE` despite finishing successfully. Upstream output ended with
a bare ANSI reset and no trailing newline, so the allocation wrapper appended
`REVODESIGN_RESOURCE_BEGIN` to that unterminated line; `_resource_capture_text` could not
find the marker, `accounting_available` stayed false, and the Task failed before its
resource evidence was read. The wrapper now emits a newline before the marker, so it
always starts its own line. This is a shared defect that would have failed any GPU Task
whose upstream output lacked a final newline;
`tests/test_slurm_runner.py::test_resource_markers_start_a_line_after_output_without_a_trailing_newline`
fails against the old line and passes against the new one.

**Foundry fixture defects.** `foundry_rfd3na_design` needed two real fixes. RFD3NA's
`SampleDiffusionConfig` has no `n_recycle` field, so the shared override raised
`ConfigCompositionException: Could not override 'inference_sampler.n_recycle'`; it is now
emitted for RFD3 only. RFD3NA also rejects a `contig` with no `input` — an atom array must
exist before selections parse — so the smoke case now scaffolds onto a small RNA
template, which is the only form the pinned revision accepts.

**Model assets.** The Foundry weight directory was mode `750 yinying:staff`, so the
service account could not read `model-assets.json`; it is now `755` with `444` files,
matching every other family. All three checkpoints were re-hashed against the operator
manifest (`rfd3` 2690316669 B, `rfd3na` 2690139762 B, `rf3` 3038876446 B) and match.

### Pocket, validation, and docking batch

Five families were added with their read-only resources provisioned and their smoke
cases accepted on the target host. Four of them failed first for reasons worth
recording, because each was a shared class of defect rather than a local slip.

**The HTTPS apt rewrite.** Every new definition exported the build proxy *and*
rewrote the distributor's archive URLs to `https`. The build proxy terminates TLS
with a CA the base image does not trust, so every `apt-get` fetch failed with
`Certificate verification failed ... [IP: 127.0.0.1]`. The working families keep the
plain-HTTP URLs; the rewrite was removed from all five definitions.

**JRE versus JDK.** P2Rank's Gradle 9.0 build needs `com.sun.tools.javac.util.Context`
on `:compileGroovy`, which a JRE does not contain. The base image is now
`eclipse-temurin:17-jdk-jammy`.

**cctbx import order.** MolProbity's `%test` segfaulted (exit 139) with no diagnostic.
Bisection in a throwaway SIF showed `import rdkit` before `mmtbx` aborts under
`cctbx-base==2025.11`; importing molprobity first, or rdkit afterwards, does not. The
adapter never imports rdkit, so rdkit was removed from the image rather than left in
an order-dependent state.

**cctbx reference data is not in the wheel.** `mmtbx.rotamer` resolves
`chem_data/rotarama_data` and refuses to score without it; `mmtbx.monomer_library`
needs `chem_data/geostd` and fails with "Cannot find CCP4 monomer library" otherwise.
Both are provisioned read-only under `/mnt/db/weights/revocompute/molprobity`, and the
definition creates `<prefix>/chem_data` as a symlink to the single mount so both
resolvers find it without a second copy in the image. One artifact is generated rather
than downloaded: `mmtbx.rebuild_rotarama_cache` was run once inside the built image
against that mount, producing `rotarama.dlite` and 23 `.pickle` files. They carry the
absolute source paths of the grids they were built from, so the cache must be
regenerated if the mount path ever changes. `chem_data/chemical_components` is a
symlink to `geostd`, which is the second path the resolver probes.

**FRODOCK ships as built.** The release archive contains the full C++ sources as well
as prebuilt binaries, so a from-source rebuild was worked through in a container rather
than assumed away. The four executables this Runner uses do compile after retargeting
the Eclipse-generated makefiles from `icpc` to `g++`, but rebuilding buys nothing: they
already link only `libstdc++`, `libm`, `libgcc_s`, and `libc`, all present in the base
image. The archive cannot be fully rebuilt either — `libnmafit` includes
`libnma/include/libnma_time.h` and `libnma` is not shipped, and `libfrodockcluster`'s
GNU build tree is misspelled `Relase_gcc`. The definition therefore fetches the pinned
archive and removes the three binaries that cannot run here: the plain `frodock` needs
Intel MKL, and the `_mpi_gcc` pair needs the OpenMPI 2 `libmpi.so.20` runtime.

**DeepPocket drives the pinned upstream stack.** The published checkpoints store
`module.*` keys, so the segmentation model is wrapped in `DataParallel` before
`load_state_dict`, exactly as upstream's own entry point does. Two further fixes came
from working against the real pinned versions rather than the published instructions:
`molgrid`'s Boost.Python bindings abort at import unless `torch` is imported first, and
ProDy 2.4.1 — the version upstream itself pins — rejects the `resindex A or resindex B`
selection form the upstream pocket writer builds, so the adapter constructs the same
selection in the list form. fpocket is compiled into the same SIF as DeepPocket's own
candidate generator rather than chained as a separate Task.

### Suspended families

Two families in this batch are suspended with a recorded defect. Both are implemented
and have passing target-host smoke receipts; neither is a support commitment until its
defect is fixed, and neither is enabled in the deployment env.

**Boltz — the FASTA dialect is registered in the wrong pass.** Core runs a physical
validator and then a logical one (`routes.py:1172`→`:1176`). The Chai dialect replaces
the physical pass, because it is registered in `_DIALECTS`; the Boltz FASTA dialect was
registered only in `validate_logical_input`, so the strict `validate_fasta` still runs
first and applies the protein alphabet. The pinned parser
(`boltz/data/parse/fasta.py`, inside `boltz_v1.sif`) accepts `>CHAIN|smiles` and
`>CHAIN|ccd` entities whose payloads are not that alphabet, so ligands only ever
worked for alphanumeric SMILES — `>L|smiles|\nc1ccccc1` is rejected with "invalid
character 'c'" and `C(=O)O` with "'('". The YAML dialect is unaffected, and the MSA
work is correct and live-accepted. The fix is to register the FASTA dialect in
`_DIALECTS` as the Chai dialect is and drop the duplicate branch; the test helper
`_boltz_error` must exercise the production physical-then-logical order, which is why
this escaped — it calls `validate_logical_input` alone. Boltz must be removed from
`ENABLED_TASKRUNNERS` in the deployment env, since that env is gitignored.

**FRODOCK — the search-effort control is not exposed.** The Task contract exposes
`pose_count`, `clustering_rmsd`, and `interaction_type`, but not `--bw`, the
spherical-harmonic bandwidth that the source turns directly into the rotational step
size (`frodock_input.rd = 180.0 / frodock_input.bw`, `libfrodock/frodock.cpp:116`;
32 gives roughly 11°). Every other search variable (`--st`, `--lw`, `--th`, `--lmin`,
`--lmax`, `--np`, `--nt`, `--td`) and the four energy-term weights are fixed too.
Against the contract's own criterion in `docs/runner-guide/docking-runners.md` — a
Task forms the search effort so the Slurm allocation stays finite — `bandwidth` is the
one omission that removes real capability rather than pinning an irrelevant default. A
from-source rebuild was evaluated and rejected; see `docker/runners/frodock/MODEL_ASSETS.md`.

### Intake outcomes
**BoltzGen and Pallatom-Ligand are deferred, not implemented.** BoltzGen is MIT at commit
`a3149cf18eeb58648d1abbb27539bd73f746cdda`, but every checkpoint and data artifact is
fetched from the Hugging Face `boltzgen/*` namespaces with no published model terms.
Pallatom-Ligand publishes no license file at all and its checkpoints are Google Drive
links with unstated terms; the provisioned `params_Pallatom.npz` belongs to the separately
licensed `levinthal/Pallatom` family and does not satisfy these loaders. Enabling either
would mean asserting rights that cannot be established from the published terms, so the
intake rule is to keep the blocker recorded instead.

### Remaining

Run the final gates (`make test`, `make test-cov`, `mkdocs build --strict`, plugin
discovery, doctor), then open the pull request. P2Rank, fpocket, MolProbity, and
DeepPocket have current PASS receipts and provisioned assets but are not yet in
`ENABLED_TASKRUNNERS`; enable them in the deployment env as a separate operator step.
That step must also **remove Boltz**, which is enabled there today and is suspended
until its FASTA dialect defect is fixed. FRODOCK and Boltz both stay out of the enabled
set. The parameter-surface audit for the remaining families was not completed: three
review attempts produced no usable output, so only FRODOCK's gap is established, by
hand. Do not claim complete upstream parameter coverage for the rest of the batch.

## Baseline

- Branch: `docs/platform-trust-plan`
- Design: `TODO.md`
- Delivery PR: <https://github.com/YaoYinYing/REvoCompute/pull/20>

## Completion checklist

- [x] Add structured, privacy-safe operational events with request/Task/Celery/Slurm correlation.
- [x] Add Core-owned infrastructure readiness probes, aggregation, API, and user/admin projections.
- [x] Put uploaded files through bounded Core quarantine and security validation before durable Task storage.
- [x] Make `/compute/api/preflight/{task_type}` and submission reuse one authoritative validation path.
- [x] Add adversarial preflight and no-side-effect boundary coverage.
- [x] Add append-only, idempotent GPU-credit accounting and allocation-time enforcement.
- [x] Add user/admin GPU-credit APIs and UI, adjustments, and reconciliation.
- [x] Add append-only, idempotent administrative GPU-credit reset for one user and for all current users.
- [x] Add the canonical CPU-only Example Runner and standard onboarding documentation.
- [x] Complete security, failure/restart, Slurm GPU-accounting, and Example Runner live acceptance.
- [x] Promote the prepared Runner deployment and verify it through the public API on the target host.

## Current phase

Phase 5 production acceptance. The shared preflight boundary enforces request, per-file, aggregate-byte, and file-count
limits while hashing uploads into bounded quarantine. Core format dispatch fails closed and covers every production
format. Each validator is classified as `safe_inprocess` or `isolated`; the third-party YAML parser runs through a
static Core worker with CPU, address-space, output-file, descriptor, timeout, environment, temporary-directory, and
Python-network restrictions. Timeout, OOM-like termination, protocol failure, and parser crashes fail validation.
Task-owned JSON logical types now select Core semantic profiles: AlphaFold 3 and OpenDDE prohibit external paths and
URLs, while Foundry accepts only confined references to separately uploaded assets. AlphaFold 3's upstream file-path
fields are rejected, and both JAAG builders emit the pinned upstream `dialect`/`version` shape before generated files
pass through the same preflight endpoint as uploads.

## Current action

No bot review or deployment is being triggered. The Example Runner now has target-host acceptance through API
submission, worker dispatch, Slurm job 4797, Apptainer execution, output validation, artifact download, and a signed
PASS receipt for the exact candidate SIF. Receipt contract version 2 requires completed resource evidence with elapsed
time, allocated CPU/GPU resources, CPU time, peak resident memory, and GPU memory/utilization for GPU cases,
invalidating older weaker receipts. GPU live cases also seed isolated authorization and credit, then require exact
Slurm allocation, settlement, ledger, and balance-delta evidence before issuing a PASS receipt. The remaining live GPU
acceptance is deferred while the target accelerator is occupied by another user's unlimited-duration production
molecular dynamics job. Because Slurm accounting storage is disabled on this cluster, GPU allocations now sample only
their Slurm-assigned devices through `nvidia-smi` and retain bounded peak memory/utilization evidence from a host-only
capture directory; the existing `sacct` accelerator metrics remain accepted when available. Production rollout remains
intentionally pending.

The submission boundary now quarantines and completes Core file security validation before invoking Runner-owned
workspace normalization or validation. The Compose full-stack gate also refreshes infrastructure evidence through the
admin API and seeds live-test evidence with the current receipt/scheduler identity contract.

## Review follow-up

The Platform Trust review comments are resolved in this branch:

- Core preflight no longer executes Runner-owned workspace normalizer/validator entrypoints at all. The read-only
  preflight endpoint performs declarative Core checks only, and a successful preflight proves zero Runner calls; Runner
  workspace semantics run during real Task preparation. The boundary tests now match the namespaced capability id, which
  the earlier weaker test did not.
- Infrastructure admission is resource-specific: CPU-only Slurm work depends on the scheduler/worker/storage path, and
  only GPU work additionally depends on GPU inventory. The global aggregate still drives the operator overview.
- The worker-readable GPU authorization projection now unions overlapping grants by effective expiry (indefinite wins,
  otherwise the longest valid expiry) instead of keeping whichever grant was iterated last.
- The multipart `workspace` document passes the same shared bounded Core JSON decoder (bytes/depth/nodes, fail-closed
  `RecursionError`) as an uploaded JSON file before Runner code can inspect it.
- A GPU settlement failure is isolated from the scientific outcome: the finish callback records review evidence and a
  `gpu.usage.settlement_failed` event, and never rewrites a completed Runner as a failed Task.
- Lost-finish recovery uses one best-effort `scontrol show job <jobid>` query with no `sacct`/SlurmDBD dependency;
  ambiguous evidence is marked `review`, never estimated.
- GPU capacity is derived from configured GRES minus allocated `GresUsed`, not from node state.
- Cross-month policy is explicit (whole allocation charged to its start month), and the Example Runner now ships a named
  contract test that newer families copy.
- Administrative GPU-credit reset is implemented for one user and for all current users. `delta = effective_monthly_allowance
  - current_remaining` is computed and appended as one `admin_reset` entry inside a single `BEGIN IMMEDIATE` transaction;
  usage and prior adjustments are untouched, per-user allowance overrides are respected, GPU permission is independent,
  zero-delta resets append a durable zero-value marker (hidden from the user's own history) so the idempotency key is
  reserved, and both operations reuse an idempotency key so retries do not duplicate entries.
  The global batch shares one `batch_id` embedded in the ledger idempotency key (no new column/migration).

## Verification

- `python -m pytest tests/server/test_preflight_boundary.py tests/test_input_validation.py tests/server/inputs/test_typed_contract.py tests/test_artifact_references.py -q` — 68 passed.
- `python -m pytest tests/server/test_preflight_boundary.py tests/test_security.py -q` — 38 passed.
- `python -m pytest tests/server/test_preflight_boundary.py tests/test_input_validation.py tests/server/inputs/test_typed_contract.py tests/test_artifact_references.py tests/server/tools/test_api.py -q` — 79 passed.
- `python -m pytest tests/test_tasks.py tests/test_security.py tests/test_auth.py tests/test_runner_access_routes.py tests/server/test_preflight_boundary.py -q` — 187 passed.
- `python -m pytest tests/server/test_preflight_boundary.py tests/test_input_validation.py tests/test_tasks.py tests/test_runner_access_routes.py -q` — 143 passed.
- `mkdocs build --strict` — passed.
- `python -m pytest tests/server/test_operational_events.py tests/server/test_preflight_boundary.py tests/test_admin.py tests/test_log_rotation.py -q` — 53 passed.
- `python -m pytest tests/test_tasks.py tests/test_workflow_composer.py tests/test_slurm_runner.py tests/server/test_operational_events.py tests/server/test_preflight_boundary.py tests/test_admin.py tests/test_log_rotation.py -q` — 175 passed.
- `python -m pytest tests/test_tasks.py tests/test_workflow_composer.py tests/test_slurm_runner.py tests/test_scientific_result_protocols.py tests/server/test_operational_events.py -q` — 131 passed.
- `python -m pytest tests/server/test_infrastructure_readiness.py -q` — 13 passed.
- `python -m pytest tests/server/test_infrastructure_readiness.py tests/server/test_operational_events.py tests/server/test_preflight_boundary.py tests/test_admin.py tests/test_security.py tests/test_tasks.py -q` — 159 passed before the final four focused probe cases were added; the final focused readiness suite passed separately.
- `python -m json.tool revocompute/static/openapi.json` — passed.
- `mkdocs build --strict` — passed.
- `python -m pytest tests/test_playwright_scalability.py::test_configuration_infrastructure_panel_and_refresh tests/test_playwright_scalability.py::test_configuration_tasktype_filter -q` — 2 passed.
- `python -m pytest tests/test_admin.py::test_configuration_page_script_initializes_theme_and_admin_data tests/test_browser_contracts.py::test_js_modules_load_in_correct_order -q` — 2 passed.
- Desktop (1440x1000) and mobile (390x844) Chromium screenshots of the Infrastructure tab — visually inspected; no clipping or overlap after responsive row stacking.
- `python -m pytest tests/server/test_infrastructure_readiness.py tests/server/test_preflight_boundary.py tests/test_tasks.py::test_public_api_docs_expose_the_client_openapi_contract -q` — 25 passed.
- `python -m pytest tests/server/test_infrastructure_readiness.py tests/server/test_preflight_boundary.py tests/test_runner_access_routes.py tests/server/test_operational_events.py tests/test_tasks.py -q` — 115 passed.
- `python -m pytest tests/server/test_infrastructure_readiness.py tests/server/test_preflight_boundary.py tests/test_runner_access_routes.py -q` — 40 passed after moving scheduler probes to worker-published evidence.
- `python -m pytest tests/test_tasks.py tests/server/test_operational_events.py tests/server/test_infrastructure_readiness.py tests/server/test_preflight_boundary.py tests/test_runner_access_routes.py -q` — 116 passed.
- `python -m pytest tests/test_playwright_scalability.py::test_failed_sequence_submission_does_not_leak_generated_file_into_retry -q` — 1 passed.
- `python -m pytest tests/server/test_infrastructure_readiness.py -q` — 18 passed after adding the non-allocating Slurm `srun --test-only` submission sanity probe.
- `python -m pytest tests/server/test_preflight_boundary.py -q` — 19 passed after adding adversarial path cases; the subsequent NUL policy case passed in the broader run.
- `python -m pytest tests/server/test_preflight_boundary.py tests/test_security.py tests/test_security_advanced.py tests/test_artifact_references.py -q` — 104 passed.
- `python -m pytest tests/test_input_validation.py tests/server/inputs/test_formats.py tests/server/test_preflight_boundary.py -q` — 73 passed after removing the executable validator plugin hook.
- `mkdocs build --strict` — passed after updating the Core validator ownership documentation.
- `git diff --check` — clean.
- `python -m pytest tests/server/test_gpu_credits.py tests/test_schema_epoch.py tests/test_slurm_runner.py tests/test_workflow_composer.py -q` — 65 passed.
- `python -m pytest tests/test_tasks.py tests/server/test_preflight_boundary.py tests/server/test_operational_events.py -q` — 96 passed.
- `python -m pytest tests/server/test_gpu_credits.py tests/test_tasks.py::test_public_api_docs_expose_the_client_openapi_contract tests/test_admin.py::test_admin_can_list_users tests/test_auth.py::test_profile_page_requires_login -q` — 13 passed.
- `python -m pytest tests/test_playwright_runner_access.py::test_profile_renders_self_scoped_gpu_credit_ledger tests/test_playwright_runner_access.py::test_admin_applies_reasoned_gpu_credit_adjustment -q` — 2 passed in Chromium at mobile widths.
- `mkdocs build --strict` — passed after documenting the GPU credit API and UTC reset semantics.
- `python -m pytest tests/server/test_gpu_credits.py tests/server/test_preflight_boundary.py tests/test_admin.py tests/test_auth.py tests/test_tasks.py -q` — 200 passed.
- Desktop (1440x1000) and mobile (390x844) Chromium screenshots of the Profile GPU Credits panel — visually inspected; no clipping or overlap.
- `python -m pytest tests/server/test_gpu_credits.py tests/server/test_preflight_boundary.py tests/test_admin.py tests/test_auth.py tests/test_tasks.py tests/test_workflow_composer.py tests/test_slurm_runner.py tests/server/test_operational_events.py -q` — 267 passed after adding Slurm-backed GPU allocation reconciliation.
- `python -m json.tool revocompute/static/openapi.json` — passed after documenting the admin reconciliation API.
- `mkdocs build --strict` — passed after documenting authoritative settlement and review behavior.
- `git diff --check` — clean.
- `python -m pytest tests/server/test_gpu_credits.py tests/server/test_preflight_boundary.py tests/test_admin.py tests/test_runner_access_routes.py tests/test_workflow_composer.py tests/test_slurm_runner.py tests/test_schema_epoch.py -q` — 152 passed after adding the worker-readable GPU authorization projection.
- `python -m pytest tests/server/test_gpu_credits.py tests/server/test_preflight_boundary.py::test_gpu_preflight_reports_credit_without_consuming_it tests/test_admin.py::test_admin_can_enable_own_gpu_access_with_unchanged_role -q` — 22 passed after the final idempotent allocation retry adjustment.
- `mkdocs build --strict` — passed after documenting the allocation-time authorization boundary.
- `python -m py_compile revocompute/db.py revocompute/routes.py revocompute/task_runtime.py tests/server/test_gpu_credits.py` — passed.
- `git diff --check` — clean.
- `python -m pytest tests/server/test_gpu_credits.py tests/test_slurm_runner.py tests/test_workflow_composer.py tests/server/test_preflight_boundary.py tests/test_admin.py tests/test_runner_access_routes.py tests/test_schema_epoch.py -q` — 153 passed after adding allocation-time Runner readiness enforcement.
- `python -m pytest tests/runners/example/test_analyze.py -q` — 6 passed, including named-role and resolved-parameter Runner execution.
- `python -m pytest tests/test_doctor.py tests/test_live_test_protocol.py tests/test_result_storyboard.py tests/test_scientific_result_protocols.py -q` — 32 passed.
- `python -m revocompute doctor --config-root docker/runners --runner example --task sequence_statistics --strict` — passed with no diagnostics.
- Production plugin discovery plus expected-file and storyboard parsing for `sequence_statistics` — passed.
- `apptainer build /tmp/revocompute-example-v1.sif example/example.def` from `docker/runners/` — passed, including `%test`; SHA-256 `6d24415ee0e5ff1e2f000dff9371bb59f103b7efbf5ee9c810d118895b563937`.
- `apptainer inspect /tmp/revocompute-example-v1.sif` and independent `apptainer test /tmp/revocompute-example-v1.sif` — passed.
- `mkdocs build --strict` — passed after publishing the Example Runner-based 10-step onboarding path.
- `bash -n docker/runners/example/run.sh`, Python compilation, and `git diff --check` — passed.
- `make test-unit` — 972 passed, 5 skipped, and 36 browser tests deselected.
- `python -m pytest tests/test_input_validation.py tests/server/inputs/test_formats.py tests/server/inputs/test_typed_contract.py tests/server/test_preflight_boundary.py -q` — 103 passed after fail-closed format coverage and bounded upload/parser checks.
- `python -m pytest tests/test_security.py tests/test_security_advanced.py tests/test_artifact_references.py -q` — 84 passed.
- Python compilation and `git diff --check` — passed; `ruff` is not installed in this environment.
- `make test-unit` — 992 passed, 5 skipped, and 36 browser tests deselected after the security-hardening changes.
- `mkdocs build --strict` — passed after documenting fail-closed formats and upload limits.
- `python -m pytest tests/server/test_preflight_boundary.py tests/server/test_operational_events.py -q` — 34 passed after tracing request-size rejection.
- `python -m pytest tests/server/inputs/test_parser_isolation.py tests/test_input_validation.py tests/server/inputs/test_formats.py tests/server/inputs/test_typed_contract.py tests/server/test_preflight_boundary.py -q` — 109 passed with isolated YAML parsing.
- `python -m pytest tests/test_input_validation.py tests/server/test_preflight_boundary.py -q` — 109 passed after adding task-specific JSON semantic profiles and generated-input boundary coverage.
- `node tests/js/test_contracts.js` — 64 passed, including both JAAG builders' AlphaFold 3 serialization contract.
- `python -m pytest tests/runners/alphafold3/test_runner.py tests/runners/foundry/test_runner.py tests/runners/opendde/test_opendde_protocol.py tests/test_plugin_discovery.py tests/test_doctor.py tests/test_browser_contracts.py -q` — 49 passed.
- `mkdocs build --strict`, Python compilation, and `git diff --check` — passed for the JSON-hardening checkpoint.
- `python -m pytest tests/test_input_validation.py tests/server/inputs/test_formats.py tests/server/test_preflight_boundary.py -q` — 124 passed after malformed mmCIF/SDF, hidden-path, and deterministic bounded-fuzz coverage.
- `python -m pytest tests/test_input_validation.py tests/server/inputs/test_formats.py tests/server/test_preflight_boundary.py tests/test_artifact_references.py tests/server/test_gpu_credits.py tests/test_slurm_runner.py -q` — 205 passed after hard-link, concurrency, and cancellation-settlement coverage.
- `python -m pytest tests/test_playwright_runner_access.py::test_admin_applies_reasoned_gpu_credit_adjustment -q` — passed in Chromium at 430px with the resulting-balance preview.
- `mkdocs build --strict`, JavaScript/Python syntax checks, and `git diff --check` — passed for the adversarial-security checkpoint.
- `python -m pytest tests/server/test_gpu_credits.py tests/test_tasks.py::test_public_api_docs_expose_the_client_openapi_contract -q` — 24 passed after adding immutable per-user monthly allowance policy.
- Two mobile Chromium GPU-credit admin workflows passed for resulting-balance preview and monthly-allowance updates.
- `make test-unit` — 1,030 passed, 5 skipped, and 37 browser tests deselected after all locally executable TODO work.
- `mkdocs build --strict`, OpenAPI JSON validation, and `git diff --check` — passed after the final documentation review.
- `python -m pytest tests/integration/test_example_runner_delivery.py -q` — passed through API submission, real Example
  Runner execution, Core output acceptance, and authenticated artifact download with only scheduler transport replaced.
- `python -m pytest tests/test_live_test_protocol.py tests/test_live_test_executor.py tests/test_runner_live_worker.py
  tests/test_workflow_composer.py tests/test_slurm_runner.py tests/server/test_gpu_credits.py
  tests/server/test_operational_events.py -q` — 119 passed after making GPU live receipts require exact accounting
  evidence and fixing GPU workflow authorization to use its owning runtime family.
- `make test-unit` — 1,035 passed, 5 skipped, and 37 browser tests deselected after the GPU workflow and live receipt
  accounting changes.
- `python -m pytest tests/test_live_test_protocol.py tests/test_live_test_executor.py tests/test_runner_live_worker.py
  tests/test_runner_readiness.py tests/test_restart_ctl.py tests/test_slurm_runner.py tests/server/test_gpu_credits.py -q`
  — 205 passed with versioned, fail-closed Slurm resource observations.
- `python -m pytest tests/test_live_test_protocol.py tests/test_live_test_executor.py tests/test_runner_live_worker.py
  tests/test_runner_readiness.py tests/test_restart_ctl.py tests/test_slurm_runner.py tests/server/test_gpu_credits.py -q`
  — 209 passed after adding the allocation-wrapper resource fallback and bounded terminal stdout envelope.
- `REVODESIGN_SERVER_ENV=.env.production.v7-slurm bash run/restart.sh live-test --runner example --collection smoke`
  — passed on the target host through Slurm job 4797 and Apptainer using candidate SIF SHA-256
  `947de01244f31d476022b42c22194d259e81ced0b3ba50df8ec9589599448ff8`; the receipt records 8 allocated CPUs,
  0.84 seconds elapsed, 0.71 seconds user CPU, 0.15 seconds system CPU, and 42,924 KiB peak RSS. The versioned report
  is `/mnt/data/srv/revodesign/server-slurm/images/live-tests/example/1789497278243513148-smoke.json`.
- `python -m pytest tests/test_live_test_protocol.py tests/test_live_test_executor.py tests/test_runner_live_worker.py
  tests/test_runner_readiness.py tests/test_restart_ctl.py tests/test_slurm_runner.py tests/server/test_gpu_credits.py -q`
  — 212 passed with bounded allocation-wrapper GPU memory/utilization observations and the `sacct` fallback.
- `make test-unit` — 1,045 passed, 5 skipped, and 37 browser tests deselected after allocation-wrapper GPU
  observation support.
- `python -m pytest tests/server/test_preflight_boundary.py tests/test_runner_readiness.py
  tests/test_live_test_protocol.py -q` — 80 passed after moving Runner-owned workspace code behind Core file security.
- `python -m pytest tests/test_full_stack_smoke.py tests/server/test_preflight_boundary.py -q` — 38 passed.
- `make test-docker-full-stack` — passed through authenticated infrastructure refresh, submission, Celery, mocked Slurm
  and Apptainer execution, result acceptance, ranged artifact download, and archive verification.
- `make test-unit` — 1,047 passed, 5 skipped, and 37 browser tests deselected after the preflight and full-stack fixes.
- Shell syntax and `git diff --check` — passed for the full-stack and preflight checkpoint.

## Known blockers

- Slurm accounting storage is disabled on the target cluster (`sacct` returns no rows), so receipts rely on the
  allocation wrapper's own bounded observations plus `scontrol` metadata. The wrapper fallback added here covers the
  GPU case; the `sacct` path is retained for clusters that enable accounting.

## Post-merge deployment checkpoint

Promoted the prepared deployment on 2026-09-17 (`restart --mode=prepared --keep-gateway`) onto commit `7666991` plus
this branch's fixes. All 27 enabled Runner families reported `READY` (Doctor PASS, current SIF, current live test)
before and after promotion, and all six Compose services (`redis`, `web`, `gateway`, `maintenance`, `worker`,
`tool-worker`) were running when the prepared restart completed. The deploy stamp records `mode=prepared`, 25 promoted
families, and no rebuilt server image beyond the one rebuilt below.

### Fixes

**Slurm GPU allocation receipts.** The cluster exports `CUDA_VISIBLE_DEVICES=0` but neither `SLURM_JOB_GPUS` nor
`SLURM_GPUS_ON_NODE`, so scientifically successful GPU jobs failed receipt validation with
`RESOURCE_OBSERVATION_FAILURE`. The shared Slurm wrapper now reads `SLURM_JOB_GPUS` when present and falls back to
`CUDA_VISIBLE_DEVICES`, derives the GPU count from the explicit Slurm value or from the comma-separated device IDs, and
preserves `NoDevFiles` handling. Evidence: `tests/test_slurm_runner.py::test_gpu_wrapper_samples_assigned_device_and_emits_resource_evidence`
exercises the fallback with only `CUDA_VISIBLE_DEVICES` set.

**Proxy forwarding for live-test image builds.** `live-test --use-proxy` was accepted but ignored while preparing the
one-off server image. `resolve_proxy_args` is now shared with `build`, resolved in the live-test command, and forwarded
through `run_live_tests` and `prepare_live_test_server_image` into `build_web_images`. Runtime output now confirms
`Using configured proxy for dependency downloads (credential redacted).` The behavior test is
`tests/test_runner_live_worker.py::test_live_test_refreshes_submission_attestations_after_receipt_update`.

**Pre-stop sweep against an already-stopped worker.** `pre-stop-sweep-slurm` ran unconditionally before
`docker compose stop`, so a partially-stopped or crashed deployment aborted the restart with
`service "worker" is not running` before any service was touched. The sweep now checks that the compute `worker`
container itself is running and skips when it is not; `tool-worker` deliberately does not count, since it can
neither see nor cancel compute jobs and `compose exec worker` would still abort the restart (boot-time orphan
recovery in `task_runtime` handles leftover records). Evidence:
`tests/test_restart_ctl.py::test_slurm_sweep_skips_when_no_worker_container_is_running` and
`::test_slurm_sweep_skips_when_only_tool_worker_is_running`.

**Infrastructure evidence pulse.** Scheduler/GPU probes run in the compute worker and publish to
`$SERVER_DIR/readiness/infrastructure.json`, but only the worker's boot-time `worker_ready` hook refreshed that
snapshot. Within one `INFRA_STALE_SECONDS` (60 s) of a restart every Slurm submission was refused with
`slurm_controller is unavailable or stale`. A daemon thread started from `worker_ready` now re-probes and
republishes on `INFRA_REFRESH_SECONDS`, matching the documented "automatic infrastructure probe pass".

The pulse deliberately does **not** go through the Celery task queue. `run_compute_task` blocks inside
`SlurmJob.poll()` for the whole job, so on a fully occupied worker pool a queued probe would wait behind long
scientific tasks and let the evidence go stale under ordinary load — reintroducing the refusal without any crash.
`worker_ready` is emitted on the worker's *parent* process (celery `WorkController.on_consumer_ready`), so the
thread runs outside every task slot. `slurm_enabled` is re-read on every pulse, because an admin can enable SLURM
through the configuration API without restarting the worker. `INFRA_REFRESH_SECONDS` keeps the meaning the rest of
the infrastructure contract already uses: positive is the interval, `0` disables the automatic pulse (admin and
force refresh still work), negative is a configuration error. Zero must disable rather than spin — the same value
feeds `Event.wait`, where `0` returns immediately and would probe the Slurm controller in an unbounded busy loop.
Evidence: `tests/test_maintenance_manager.py::test_infrastructure_pulse_probes_while_slurm_is_enabled` and
`::test_infrastructure_pulse_stays_idle_while_slurm_is_disabled` (saturated-pool precondition: the pulse runs
without any Celery slot being consumed), plus `::test_zero_refresh_interval_disables_the_pulse_instead_of_spinning`
and `::test_negative_refresh_interval_is_rejected`.

**`INFRA_*` settings reach the containers.** `INFRA_REFRESH_SECONDS`/`INFRA_STALE_SECONDS` and the two disk
thresholds were documented and read by the code but never passed into any Compose service, so a value set in the
deployment env silently had no effect. They are now in the shared `x-task-env` anchor, which both the web
admission service and the worker pulse read; covering the disk thresholds keeps that pair's
critical ≤ warning invariant checkable from the same source.

### Public API acceptance

Server image rebuilt with `build --use-proxy --server-only` (proxy line confirmed above) and the prepared restart
rerun. `runner-status --all` reported all 27 enabled families `READY`. Both tasks below were submitted through
`https://revocompute.yaoyy.com`-equivalent `/compute/api/post` against the deployed gateway on `127.0.0.1:8081` with a
real Bearer session, and tracked through the public status, result, artifact, and input endpoints.

- CPU: `pythia_ddg`, task `1f1e07d85e92445d5e46719e59e46165`, Slurm job `4871`, `finished` in 23.3 s. Immutable input
  snapshot hash matches the submitted `tests/data/pdb/2KL8.pdb`
  (`035c78fb64880cfac5f721a1831ea45a54b453741fbbc4785d738be83c19c15e`). Receipt: 8 allocated CPUs, 1 task, exit 0,
  23.1 s elapsed, 22.6 s user CPU, 3.86 s system CPU, 496,388 KiB peak RSS. Primary artifact `2KL8_pred_mask.csv`
  downloaded through the authenticated endpoint with a matching SHA-256
  (`85fb6f251bbdbe1cb328b4173e876c0e982a041d29fa5611fa0342b1ada5c01b`).
- GPU: `esm_extract`, task `cef3bbf2d11d5c8b02f99e42feb8154e`, Slurm job `4913`, `finished` in ~24 s. Receipt proves
  the GPU-accounting fix: `gpus=1 ids=0 visible=0`, peak GPU memory 3,155 MiB, peak GPU utilization 70%. The credit
  ledger recorded allocation `settled` with 26 GPU-seconds and the matching append-only usage entry
  (`usage:4913`, `-26`). Primary artifact `2KL8.pt` downloaded with a matching SHA-256
  (`9aac9acb6dab94912792acddcf775d89a1706974e4629507ac0a8057a300421f`).

Infrastructure readiness reported `READY`, `stale: false` for scheduler, GPU, worker, and storage throughout the
acceptance window. The stale `server` Compose project from an earlier product revision was drained after its services
were confirmed to serve nothing; only the `server-slurm` project remains running.

### Gates

- `python -m pytest tests/test_maintenance_manager.py tests/server/test_infrastructure_readiness.py tests/test_restart_ctl.py -q`
  — 105 passed (includes the three new sweep/probe cases).
- `python -m pytest tests/test_live_test_protocol.py tests/test_live_test_executor.py tests/test_runner_live_worker.py
  tests/test_runner_readiness.py tests/test_restart_ctl.py tests/test_slurm_runner.py tests/server/test_gpu_credits.py -q`
  — 243 passed.
- `make test` and `make test-cov` — see the pull request description for the recorded results.
- Live: `live-test --runner frustrampnn --collection smoke --use-proxy` — PASS,
  `/mnt/data/srv/revodesign/server-slurm/images/live-tests/frustrampnn/1789687388426610392-smoke.json`.
