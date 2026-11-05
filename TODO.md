# Active Runner Upstream-HEAD Refresh — Temporary Campaign TODO

> Draft PR working plan. Source baseline: `main` `6d726f54113bed4b9eb8328db0d649c1b8582050` after #134.
> Remove this TODO before final independent review. All long-lived knowledge belongs to the owning Runner Family and existing docs.
> These are **audited upstream commits on 2026-11-04/05**, not a promise of perpetual "latest". Reconfirm immutably before building.

## Acceptance policy (Maintainer direction, 2026-11-05)

Upstream evolution is the goal. **Retired gates:** byte equality of old-vs-new structures/scores/confidence, identical GPU timings, preservation of old internal kernels or old upstream defaults, and complete hashing of every transitive dependency when the environment builds, is recorded, and executes reliably. The old pinned runtime is a rollback reference, not a golden-answer oracle.

**Retained gates:** executed source revision and model-checkpoint identity; an auditable installed-environment record (direct pins, resolved snapshot/build logs, CUDA/Python/driver compatibility); a representative upstream-native inference on the candidate image; correct input/parameter pass-through and clear refusal of invalid or unsafe input; acceptance of the new native output schema without loss or false PASS; license and known resource constraints; precision/algorithm default changes recorded with the Task/result.

**Release authority is unchanged.** No invented receipt, no unapproved target-host GPU run, no model-weight download, no SIF promotion, deployment, or Runtime Bundle activation. Source may merge as Draft under unambiguous `NOT READY / NO PROMOTION` when host assets are unavailable.

## Goal and constraints

Upgrade the actual pinned upstream **execution code** for OpenDDE, FreeBindCraft, BioEmu2, ESMFold2 and AlphaFold3 to audited upstream commits, with sound package/image/weight provenance, backward-compatible or explicitly versioned Task semantics and real scientific acceptance. Do **not** just edit a manifest string while the container still installs old code. Runner Families automatically register their own Task contracts. Core must not acquire Runner-specific scientific logic.

**Foundry is source NO-OP but its provenance is corrected:** the executable pin `d078b24d6d0e6f8607e9a0311128f4a897f83953` is a retained git-source pin installed from that commit. No published Foundry package version is claimed. The upstream default-branch delta through `0d0b0ba44fab7ca76aa4b625c014ce5964c7d284` deletes one documentation file and changes no executable code, so no rebuild is justified. This is a retained pin, not exact-HEAD parity.

## Source targets and installed changes

| Runner | Installed before | Target and installed commit | Adaptation and status |
| --- | --- | --- | --- |
| BioEmu2 (`microsoft/bioemu2`) | PyPI wheel `bioemu2[cuda12]==0.1.0rc0` | `6d1ca744fa8ed285edafae7b98da65205bf00fd3` (`main`) | Source installed with `--no-deps` over the hash-locked CUDA 12.6 closure; version stays `0.1.0rc0` because upstream published no newer wheel. Retained checkpoint/config SHAs unchanged. All three Task semantics preserved. **Source-level ready; SIF build and inference host-gated.** |
| OpenDDE (`aurekaresearch/OpenDDE`) | PyPI `opendde[gpu]==1.1.1` | `9d0d9c975178074c1ce722d2d6eefac8b7057062` (`v1.2.0`) | Source installed over a generated hash-locked closure. `pred` remains and still preprocesses MSA/template internally; `prep`/`inputprep` and `pred` already coexisted before v1.2.0, so this is an additive CLI, not a new split. The now-validated `constraint` field is passed through; a non-empty `contact`/`epitope` without TFG guidance is refused rather than run unguided. The Task keeps explicit fp32/TF32 values and records upstream's BF16/TF32-off change in `upstream.json` and the result. **Source-level ready; SIF build, valid/invalid-constraint smoke and target-host inference host-gated.** |
| FreeBindCraft (`cytokineking/FreeBindCraft`) | git `8b8d4c46` | `8a10b93a9b42487e7218ad1435a6a25d0e91afc8` (`v1.0.7`) | Not docs-only: installs upstream's validated Linux CUDA 12.9/Python 3.12 pip profile (`installation/linux-cuda12-requirements.txt`) and records it as the environment manifest. PyRosetta-free mode is OpenMM relaxation + PDBFixer + open-source scoring (FASPR/FreeSASA/sc-rs); recorded with the Task. Upstream validated on RTX 5090 only. Adapter CLI and output selectors unchanged. **Source-level ready; SIF build and GPU acceptance host-gated.** |
| ESMFold2 (`Biohub/esm`) | git `bf343ba2` (3.4.1) | `8f0834cbc350aeaf507f755475873f7c61fa44a1` (`v3.4.2`) | Adapter maps the removed cuEquivariance backend to upstream `reference`/`fused`/`fast`; default `fused` is bit-exact against reference and `fast` (approximate BF16 MSA triangle path) is opt-in. Upstream moves ESMC to fp8; the adapter deliberately retains bf16 and publishes `esmc_precision: bf16`. Provisioned standard/fast/ESMC-6B weights and revisions unchanged. **Source-level ready; SIF build, config-compatibility check and GPU inference host-gated.** |
| AlphaFold3 (`google-deepmind/alphafold3`) | git `c0f97eda` | `37e3c57fe123fc51f6d96236320b8b657afb11ac` (v3.0.5+) | Applies all three pinned HMMER patches; `uv sync --frozen` from the commit's lock; native deps remain SHA-pinned URL archives (pybind11/abseil/libcifpp/dssp plus three pinned transitive archives). `build_data` now writes `ccd.msgpack`/`chemical_component_sets.msgpack`; the image `%test` loads them. No old pickle CCD mount assumed. **Source-level ready; SIF rebuild plus no-MSA/supplied-MSA/template revalidation host-gated.** |
| Foundry (`RosettaCommons/foundry`) | git `d078b24d` | Retained `d078b24d6d0e6f8607e9a0311128f4a897f83953` | `upstream.json` and run provenance now name the commit only; the fictitious `rc-foundry==1.0.0` distribution label is removed. **No-op; no rebuild.** |

## M0 — provenance and source review

- [x] Recheck upstream commits and inspect the target source trees, CLI/API deltas, licenses and native dependency pins.
- [x] Keep parent Runner Family identity, Task registration, parameter semantics and result views unless the new upstream program forced a change.
- [ ] Reconfirm the audited commits and model asset identities immediately before any build on an authorized host.

## M1 — exact executable pin and asset closure

- [x] BioEmu2: install source `6d1ca744` over a hash-locked dependency closure, record the source SHA in the image and `upstream.json`, retain the checkpoint/config SHAs, and keep the adapter API compatible.
- [x] OpenDDE: install source `9d0d9c97`, record the dependency closure, keep `pred`, refuse unguided contact/epitope constraints, publish effective precision/constraint settings.
- [x] FreeBindCraft: install immutable `8a10b93a`, record upstream's pinned Linux CUDA profile, update the CUDA/OpenMM environment, keep adapter CLI and output layout.
- [x] ESMFold2: install `8f0834cb`, remove the obsolete cuEquivariance dependencies, map backend names, record the bf16/fused choices, keep provisioned weights explicit.
- [x] AlphaFold3: install `37e3c57f`, apply the pinned HMMER patches, build and load MessagePack CCD data, record native dependency revisions.
- [x] Foundry: correct provenance to the git commit; no `.def`, lock, SIF or checkpoint edits.
- [x] Reconcile every changed `upstream.json`, version label, `.def` and adapter with what the image actually installs.

## M2 — verification and release gating

- [x] Strict Doctor for all six families; family fast tests for BioEmu2, OpenDDE, ESMFold2 and Foundry; shell syntax for the changed adapter.
- [ ] Build each candidate SIF directly with Apptainer and run `%test` (host-gated).
- [ ] Run a representative upstream-native inference per family on an authorized target host, including:
  - BioEmu2: all three Tasks and native `topology.cif`; verify the consumer of `pdbx_formal_charge` CIF metadata under HEAD's stricter CIF parsing.
  - OpenDDE: valid and invalid `constraint` cases plus BF16/TF32 selections.
  - FreeBindCraft: one accepted design and the published metrics/output selectors.
  - ESMFold2: both model variants, reference/fused backends and the bf16 path.
  - AlphaFold3: no-MSA, supplied-MSA and template input paths.
- [ ] Measure CPU/RSS/GPU memory/time and record exact receipts. **No green CI or adapter smoke certifies an upgraded runtime.**
- [ ] Invalidate affected stale receipts without touching queued or running Tasks. Promotion and deployment remain maintainer-only.

## Completion

All changed source pins are installed by their images at the audited commits, with recorded environments, explicit precision/algorithm choices and preserved Task semantics. Host builds, representative inference and receipts are **NOT DONE**, so every family remains **NOT READY / NO PROMOTION** until an authorized candidate-SIF and target-host acceptance run completes. No scientific inference default or model identity changed silently; no viewer-driven science conversion. This PR is independent of the separate Boltz-2 new-Family PR.
