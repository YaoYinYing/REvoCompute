# Boltz-2 Runner Family — Temporary Campaign TODO

> Draft PR working plan. Base `main` `6d726f54113bed4b9eb8328db0d649c1b8582050` after #134.
> Delete this temporary file before final independent review. Durable science and setup guidance belongs in the owning new family and existing Runner Guide.

## Objective

**Add** an independent `boltz2` Runner Family that exposes the scientifically distinct Boltz-2 structure and optional protein–small-molecule binding-affinity operations. **Preserve `docker/runners/boltz/` as the original Boltz-1 family** pinned to v0.3.2 `2355c62c957e95305527290112e9742d0565c458`. Never silently replace its SIF, Task ID, asset manifest, defaults, results or historic user experiments.

Upstream: `https://github.com/jwohlwend/boltz`. Latest observed default-branch commit at audit on 2026-11-04: `b1ebfc46ecf57f5414e0d1a6f9027bbb122c53bc` (2026-05-29). Most recent official stable release: `v2.2.1` (2025-09-08). Main contains unreleased subsequent bug fixes. **Pin an immutable source SHA only after verifying its program, dependencies and checkpoints.** Prefer latest `main` commit as requested if reproducible and genuinely accepted; if it is not compatible, pin the verified stable release commit with a reviewable, explicit exception. Do not use `git checkout main` in the container or a floating pip dependency.

Upstream documents Boltz-2 `boltz predict` with optional `properties: [{affinity: {binder: <ligand chain>}}]`, checkpoint overrides `--checkpoint` and `--affinity_checkpoint`, MSA modes (provided A3M/paired CSV, explicit `msa: empty`, optional hosted MMseqs2), optional structure templates and inference-time potentials. Published outputs include native predicted mmCIF, confidence JSON, per-token uncertainty arrays and optional `affinity_*.json`. Upstream affinity heads report **`affinity_pred_value` as `log10(IC50)` when IC50 is expressed in µM** and `affinity_probability_binary` as a probability-like binder-vs-decoy score. They are model predictions, **not observed binding free energy, measured pKd, or experimental validation**. See immutable upstream `docs/prediction.md` and original Boltz-2 scientific report.

## Boltz-2 implementation status — ASSET_BLOCKED

The family implementation exists under `docker/runners/boltz2/`. The host path
`/mnt/db/weights/boltz2` is absent. Required files are `ccd.pkl`, `mols.tar`,
`boltz2_conf.ckpt`, and `boltz2_aff.ckpt`, plus the extracted `mols/` tree bound by
its own deterministic SHA-256 digest; the manifest needs all five reviewed lines. The pinned
upstream does not publish those immutable hashes. Do not download or create the
assets, invent digests, receipts, or readiness. See the family README for
provisioning and next acceptance steps.

## M0 — source and resource closure

- [ ] Commander reads the existing Runner Protocol and Single-PR Campaign Protocol, checks live `main` and exact PR head, appoints one independent Runner Owner and active Independent Campaign Adviser, and leaves all production privileges with maintainer.
- [ ] Inspect the pinned upstream commit's actual CLI, `pyproject.toml`, license, wheel availability, checkpoint downloader and pinned/model asset documentation. Inspect Boltz-2 `predict` CLI options rather than copying Boltz-1 flags blindly. Verify CUDA/PyTorch/cuEquivariance ABI against the authorized A100 host.
- [ ] Inventory verified **Boltz-2 model assets** (structure/confidence checkpoint, affinity checkpoint, CCD and any required extras): official immutable source, license, size, SHA256, exact location, input contract. Confirm what is *actually provisioned* under host `/mnt/db/boltz` versus merely mentioned in documentation. No automatic runtime downloads.
- [ ] Assess whether a dedicated `/mnt/db/weights/boltz2` semantic root is preferable for a **new** family while retaining existing Boltz-1 `/mnt/db/boltz` immutable mount; never mutate or repurpose Boltz-1's directory. Declare read-only mounts in the new family's `runner.yaml`, not Core.

## M1 — new family and scientific Task(s)

- [ ] Implement `docker/runners/boltz2/` with unique `plugin.yaml`, `.def`, source-pinned dependency closure and isolated SIF, `run.sh`/family adapter, `runner.yaml`, asset validation, provenance, licenses, family README, `test.yaml`, expected-files contracts, and optional Storyboard. The plugin must contribute Tasks automatically; no Core name registry.
- [ ] Expose at least **Boltz-2 structure prediction** with upstream YAML specification, immutable named inputs, validated local MSA/template inputs or an explicit no-MSA path. Honor chain/residue/input identities; reject unconfined upstream file references and user-controlled shell interpolation. Server must bind every allowed local referenced asset from a confinement-checked snapshot, not let the process follow paths from arbitrary uploaded YAML.
- [ ] For **affinity prediction**, choose a scientifically correct contract (second Task if distinct inputs or required outputs warrant it) while preserving upstream's optional `properties.affinity` semantics. Validate one supported protein–small-molecule target/ligand, ligand chain identity, molecule size and relevant types from pinned upstream; refuse unsupported RNA/DNA/cofactor affinity interpretations. Affinity mode must actually publish affinity JSON and direction/units correctly rather than claiming confidence alone is affinity.
- [ ] Support useful upstream alternatives such as precomputed A3M/paired CSV vs `msa: empty`; mark hosted MSA as opt-in network with explicit runtime policy, or defer if stage-level network cannot be represented safely. No arbitrary remote file download, no hidden MSA calls. Verify template and potential controls before advertising.
- [ ] Preserve upstream native mmCIF and JSON/NPZ data; **never do CIF→PDB or other lossy conversion solely to satisfy Viewer**, and extend generic Viewer only if a real declared type needs it. Result Workspace must present complex structures, confidence, and optional affinity with correct units/limitations. Missing optional affinity output cannot silently pass an affinity-declared Task.
- [ ] Every result includes immutable source commit, actual selected checkpoint/asset hashes, MSA provenance, seed, relevant inference controls and result identity. Existing `boltz` family must keep its old results and operation name unchanged.

## M2 — bounded scientific and security acceptance

- [ ] Provide isolated fast tests for declared input roles, CLI arguments, opt-in network behavior, path traversal/referenced-file refusal, model-assets digest checks, missing checkpoints, bad affinity configurations, false-positive output acceptance and numerical labels. Do **not** test YAML source literals instead of behavior.
- [ ] In the new family `test.yaml`, include a release-critical **real structure-prediction smoke** and, if exposing affinity Task, an **affinity-enabled smoke** with a valid small-molecule example whose affinity JSON is actually produced; distinguish default no-MSA path and MSA-enabled alternatives.
- [ ] Build source-pinned candidate SIF, run `apptainer inspect` and `%test`, strict Doctor, full family/fleet/server tests, documentation strict build and exact-head CI. On an operator-authorized target host use real Slurm/Apptainer live-test of **both** scientific operations; record GPU memory, walltime, CPU/RSS, exact model digests and accepted artifact tree.
- [ ] No release-ready or ENABLED claim without target-host receipt, resource availability and explicit entitlement/license review. Report `NOT READY` rather than faking receipt when weights are missing or GPU execution cannot be authorized. No implicit activation of the new family when the PR merges.
- [ ] Confirm regression that existing Boltz-1 family remains unchanged and historic `boltz_predict` input/result/receipt paths remain valid. The new `boltz2` plugin and Task IDs must not shadow old ones; server discovery remains generic.
- [ ] Independent Adviser challenges scientific affinity score interpretation, sources/checkpoint licenses, model conditioning, security and whether upstream main is safe. Final independent scientific/security review, exact-head CI, and Campaign Acceptance Auditor PASS are mandatory before `READY_FOR_FINAL_REVIEW`. Retire temporary TODO. Maintainer decides squash merge; **production SIF promotion/deployment are separate explicit decisions**.

## Scope boundaries

No training pipeline, arbitrary model/tool download, unrestricted user-config scripting, unverified affinity-of-proteins claims, generic workflow builder or unrelated Core refactor. A separate PR handles OpenDDE/FreeBindCraft/BioEmu2/ESMFold2/AlphaFold3 upstream refresh; do not overlap files or bundle Boltz-1 migration into this new scientific capability.
