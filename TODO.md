# Active Runner Upstream-HEAD Refresh — Temporary Campaign TODO

> Draft PR working plan. Source baseline: `main` `6d726f54113bed4b9eb8328db0d649c1b8582050` after #134.
> Remove this TODO before final independent review. All long-lived knowledge belongs to the owning Runner Family and existing docs.
> These are **observed upstream HEAD snapshots on 2026-11-04**, not a promise of perpetual "latest". Reconfirm immutably before building.

## Goal and constraints

Upgrade the actual pinned upstream **execution code** for OpenDDE, FreeBindCraft, BioEmu2, ESMFold2 and AlphaFold3 to the latest audited upstream default-branch commits, with sound package/image/weight provenance, backward-compatible or explicitly versioned Task semantics and real scientific acceptance. Do **not** just edit a manifest string while the container still installs old code. Runner Families automatically register their own Task contracts. Core must not acquire Runner-specific scientific logic.

**Foundry is explicitly NO-OP:** `RosettaCommons/foundry` has default branch `production`, HEAD `d078b24d6d0e6f8607e9a0311128f4a897f83953`, and REvoCompute `foundry.def`, `upstream.json` and `checkpoint-registry.json` already pin precisely that commit. Do not mistake old secondary branches/tags for the current production branch. Re-check HEAD before final signoff, but do not rebuild Foundry without a changed Build Identity.

## Upstream source targets

| Runner | Current actual installed source/pin | Latest observed default-branch HEAD | Official release and critical adaptation delta |
| --- | --- | --- | --- |
| OpenDDE (`aurekaresearch/OpenDDE`) | PyPI `opendde[gpu]==1.1.1`; `upstream.json` records package, not installed source commit | `9d0d9c975178074c1ce722d2d6eefac8b7057062` (`main`) | `v1.2.0`; constraint-guided inference with `constraint.contact/movable_chains/epitope`. **Breaking scientific defaults:** BF16 + TF32 disabled instead of earlier FP32 + TF32 enabled; previously ignored `constraint` is now interpreted and validated. Decide and test default/migration semantics explicitly. |
| FreeBindCraft (`cytokineking/FreeBindCraft`) | git `8b8d4c4627da06f084f46b7007450048fe3ca22f` in `freebindcraft.def` | `8a10b93a9b42487e7218ad1435a6a25d0e91afc8` (`master`) | `v1.0.7`; recent deltas target Apple/Metal and chunking. Confirm Linux CUDA/JAX, FreeBindCraft CLI/adapter, generated outputs and bundled helper/license compatibility; no blind assumption that Apple-specific improvements help A100. |
| BioEmu2 (`microsoft/bioemu2`) | PyPI `bioemu2[cuda12]==0.1.0rc0`, source tag commit `0d58383376d717fa0192ac02629256f8aeda095a` | `6d1ca744fa8ed285edafae7b98da65205bf00fd3` (`main`) | Only PyPI preview release `v0.1.0rc0`; HEAD has post-release sync and automation commits, **not** a new stable wheel. Build exact source commit with hash-locked compatible CUDA12.6 dependencies, or document why a valid reproducible installation cannot be built. Retain equilibrium, prediction and propagation semantics from #134; do not invent a new version number. |
| ESMFold2 (`Biohub/esm`) | git `bf343ba264b650dff7a073643725f9aaa1fdbe8d` in `esmfold2.def` | `8f0834cbc350aeaf507f755475873f7c61fa44a1` (`main`) | `v3.4.2`; fp8 ESMC path, new 2025-cutoff model, changed kernel/dependency path (cuequivariance/xformers no longer required). Examine `requirements.in`/`requirements.lock`, old provisioned `standard/fast/esmc-6b` weights, and API imports before changing defaults; newer optional/pro model assets are separate. |
| AlphaFold3 (`google-deepmind/alphafold3`) | git `c0f97eda2f1f482fd94d3a38bece18c7069b4a5c` in `alphafold3.def` | `37e3c57fe123fc51f6d96236320b8b657afb11ac` (`main`) | Stable `v3.0.5` (2026-10-30), with additional untagged mmCIF/structure optimization commits through 2026-11-04. AF3 3.0.5 uses MessagePack CCD (formerly pickle), faster MSA featurization/build_data/Jackhmmer, additional JSON validation and changed tooling; rebuild the exact SIF and preserve licensing/weights/database rules. |

**Version policy:** User requests the **latest commit**; the target for this PR is the audited immutable default-branch SHA, not an implicitly moving Git ref, unless reproducibility, source/package ambiguity, ABI, licensing, or real acceptance makes that SHA unusable. If blocked, retain the last working code, document precisely why, and seek a maintainer decision instead of performing a fictional upgrade. Always distinguish upstream default-branch HEAD, official stable tag and version actually baked into SIF.

## M0 — provenance and source review

- [ ] Recheck the live PR base/head and upstream branch HEADs. Inspect exact upstream diffs/release notes, any known API changes, licenses, checkpoint/model-data requirements, torch/CUDA/Python/ABI compatibility and cached assets on **authorized** target host. Independently inspect *real installed code* rather than trusting `upstream.json`.
- [ ] Assign an isolated owner per family or small non-overlapping cohort; Commander serializes shared docs/integration edits. Independent Campaign Adviser must challenge science, model asset/license risks and whether "latest" is actually installed.
- [ ] Preserve parent Runner Family identity and existing Task registration, operation names, user-facing parameter semantics and Result Workspace unless the new upstream program proves that they must change. Upstream native mmCIF/CIF/PDB outputs remain authoritative; **never convert for viewer convenience**. Viewer compatibility gaps are Viewer-layer defects.

## M1 — exact executable pin and asset closure

- [ ] OpenDDE: update the actual PyPI or pinned-source installation to match audited `v1.2.0` source; record precise package/wheel hash or Git commit and version; test old JSON vs valid/invalid `constraint` plus BF16/TF32 mode behavior, schema refusals and optional TFG guidance. Prevent untrusted pickle trunk-cache reuse across Task boundaries and keep immutable inputs/read-only data mounts.
- [ ] FreeBindCraft: fetch **immutable SHA** rather than branch; review change to bundled utilities, auto-paths and inference defaults, preserve Linux CUDA behavior, validate input PDB, hotspot/options and original metrics/output selectors, keep postprocessing in family. Check license and bundled binaries.
- [ ] BioEmu2: resolve source-install vs release-wheel mismatch. A requirement file declaring 0.1.0rc0 while a different HEAD is installed is **not provenance**; lock complete wheel/dependency closure, verify live `import bioemu2` reports source commit from image build provenance, maintain CUDA 12.6 and Triton prerequisites, test all three family Tasks and native `topology.cif`.
- [ ] ESMFold2: review upstream 3.4.2 dependencies and model head/ESMC import symbols, regenerate **hash-locked** dependency environment from verified distributions, provision or deliberately retain **SHA256-verified** compatible assets. Do not switch model weights, fp8 precision, or scientific default silently; certify actual structure+score outputs and resource envelope.
- [ ] AlphaFold3: update exact upstream git fetch and HMMER/CCD/pybind/C++ build preparation as warranted by upstream 3.0.5+, validate `build_data` and new MessagePack CCD artifacts, confirm input JSON with no-MSA, supplied MSA/template and physical complexes as supported, ensure current image JAX/CUDA compatibility and output format/results. Do not assume the old CCD pickle mount works.
- [ ] Foundry: record that production HEAD = current pin. No unnecessary `.def`, lock, SIF or checkpoint edits.
- [ ] Audit every changed file's `plugin.yaml.runtime.build_inputs` / `runtime_overlay` identity. Never let a git SHA-only change masquerade as current built SIF. Reconcile any `upstream.json`, version labels, source/asset hashes, `.def` and family README with what image really installs.

## M2 — verification and release gating

- [ ] Run strict Doctor, family fast tests, actual import/CLI/version test inside newly rebuilt isolated candidate SIF, replay negative cases, `test.yaml` smoke, scientific Result Workspace/expected-files verification, relevant frontend/API tests and `mkdocs build --strict`.
- [ ] For enabled families run authorized target-host `prepare --build-sif`, real Slurm/Apptainer live-test and examine measured CPU/RSS/GPU memory/time, mandatory results, digest-bound scientific receipts. **Do not** claim green CI or fake adapter smoke certifies upgraded runtime.
- [ ] Demonstrate a reliable baseline and compatible new behavior where possible; scientifically important default changes must be explicitly controlled, disclosed and tested; invalidate affected stale receipts without touching queued/running Tasks.
- [ ] Keep any candidate upgrade blocked from activation if no host access, network, verified weights, license approval or exact-identity acceptance. Source may merge only under a reviewer-approved source-only disposition with unambiguous `NOT READY/NO PROMOTION`, never falsely labelled deployed.
- [ ] Independent Adviser + independent science/security review + exact-head CI + final Campaign Acceptance Auditor PASS required. PR findings and evidence in PR comments; keep Commander's control state concise. Delete temporary TODO before final audit. Maintainer alone decides squash merge and separately authorizes every SIF promotion, Runtime Bundle activation or service restart.

## Completion

All five installed source pins are either updated to the latest audited default-branch commits **and demonstrably runnable**, or are explicitly blocked with reproducible cause and safe unchanged rollback state. Foundry current HEAD equality remains documented; no artificial changes made. No scientific inference default/model identities are silently changed; no viewer-driven science conversion. This PR is independent of the separate Boltz-2 new-Family PR.
