# Runner Adaptation Implementation State

This file is the durable execution ledger for `TODO.md`. The definition of done
and candidate-specific requirements remain authoritative in `TODO.md`.

## Current phase

Batch A and four Batch B families are deployed. Boltz, SimpleFold, ESMFold 2,
and Chai-1 joined the 19 existing families in the validated 23-family production
deployment and report READY. Eight projects remain on the adaptation wait list:
Protenix plus the seven Batch C candidates. Authenticated production submissions
for the four new families are pending a protected test credential; Protenix is
blocked on its official asset host.

## Completion checklist

- [ ] Complete intake, immutable source/model pins, license review, and family placement for all 17 candidates.
- [ ] Implement every scientifically distinct inference capability as a native TaskType.
- [ ] Keep all production weights outside SIFs and record immutable asset manifests.
- [ ] Add direct Apptainer definitions, owned wrappers, artifact contracts, and one smoke case per TaskType.
- [ ] Add focused parser/adapter tests and pass repository static/schema gates.
- [ ] Build and test every candidate SIF on the target host.
- [ ] Run Task -> Slurm -> Apptainer -> artifact acceptance for every TaskType and retain exact-runtime receipts.
- [ ] Promote only validated runtimes to READY and update inventory/wait-list documentation.
- [ ] Run final regression gates, commit the branch, push it, and open the PR.

## Candidate ledger

| Candidate | Current evidence | Next action |
|---|---|---|
| CodonTransformer | Code `v1.6.7` / `895970e960cc8b558b9dd337e112411a543ba3f3`; Apache-2.0. Model revision `9744dcc920d813066391fc828d7a590207f148e8`; Apache-2.0; six model/tokenizer files provisioned read-only with verified upstream fingerprints. Dedicated CPU family implemented with one codon-optimization TaskType. Post-review Task -> SLURM -> Apptainer acceptance passed for SIF `sha256:b60c0df1f5b68c6cd93e17249304ef85471911eebaf8199d82403be1377310ad` (job `4639`), followed by production API acceptance. | Enabled and READY; monitor production evidence. |
| Boltz | Dedicated CUDA 12.1/Torch 2.4.1 family implemented for Boltz 0.3.2 commit `2355c62c957e95305527290112e9742d0565c458` (MIT). The Boltz-1 checkpoint and CCD cache under `/mnt/db/boltz` are identified by exact size and SHA-256; the offline task contract covers FASTA/YAML input, uploaded MSA/templates, diffusion controls, structures, confidence, PAE/PDE, and provenance. Corrected Task -> SLURM -> Apptainer acceptance passed for SIF `sha256:f73758d09faf3e6c73fc0d5f7aba3efa51a9a7e675a2115971eaf9247a2ea2bc` as job `4651`, producing 14 artifacts under the scoped 64 GB / four-hour policy. | Enabled and READY; run authenticated production API acceptance. |
| SimpleFold | Dedicated CUDA 12.6/Torch 2.7.1 family implemented for commit `c7a5570a6be9f5c695126e27c804e77567209934` (MIT code; research-only model license). Exact external identities are recorded for the 1.6B/3B/pLDDT checkpoints, reused Boltz CCD, and ESM-2 3B weights. The inference closure is hash-locked and excludes upstream notebook/UI packages. Task -> SLURM -> Apptainer acceptance passed for SIF `sha256:8ab1bb866362178c35afa730f14ccda27785e2ae4eea82790fd77b799e49e427` as job `4650`, producing 11 artifacts under the scoped 64 GB / four-hour policy. | Enabled and READY under its research-only policy; run entitled production API acceptance. |
| ESMFold 2 | Dedicated CUDA 12.8/Torch 2.11 family implemented for Biohub ESM 3.4.1 commit `bf343ba264b650dff7a073643725f9aaa1fdbe8d` (MIT). Standard/fast ESMFold 2 and ESMC-6B revisions are immutable, the dependency closure is hash-locked, and all 13 official assets are provisioned and verified by exact size and SHA-256. Jobs `4652`, `4654`, `4655`, and `4656` drove production fixes for host CUDA compatibility, pinned CCD selection, adapter imports, and upstream's mixed-precision contract. Final Task -> SLURM -> Apptainer acceptance passed for SIF `sha256:54dc46fe085c69bc713b3b65be0a832c41815187171cd76255538052f0af9360` as job `4657`, producing 11 artifacts under the scoped 128 GB / four-hour policy. | Enabled and READY; run authenticated production API acceptance. |
| Protenix | Dedicated CUDA 12.8/Torch 2.7.1 family implemented for Protenix 2.0.0 commit `2475421477ab414b571149ad4a875c390ff8a35d` (Apache-2.0). The offline JSON contract covers local MSA/templates, molecular entities, sampling, kernels, confidence, constraints, and provenance; pinned-source API signatures and the required Kalign executable were verified. Official asset provisioning is blocked because the ByteDance TOS endpoint terminates TLS through the configured proxy for curl, wget, and aria2. | Retry the official host through the proxy; after provisioning and checksum inventory, build the candidate SIF and run live acceptance. Do not use a mirror. |
| Chai-1 | Dedicated CUDA 12.1/Torch 2.5.1 family implemented for Chai Lab 0.6.1 commit `8d5ac0f93e9b6ea4c3a6545c253a6381c0f3694b` (Apache-2.0 code/model statement). All eight official Chai assets (6,979,394,752 bytes) are provisioned through the proxy and locally SHA-256 verified; the offline contract covers multi-entity FASTA, uploaded MSA/restraints, sampling, confidence arrays, ranked structures, and provenance. After proxy-environment hardening, Task -> SLURM -> Apptainer acceptance passed for SIF `sha256:1228d3c1e7c166af051aa9e7ef7c9b407576095b246ec0de572a49ac9ea4e472` as job `4658`, producing 16 artifacts under the scoped 128 GB / eight-hour policy. Separate asset-level license provenance was not found for `conformers_v1.apkl`. | Enabled and READY; retain the conformer-license evidence and run authenticated production API acceptance. |
| frustraMPNN | Code `3a03cdc300bfe24c4bb70e60207118532bc73b3b`; BSD-3-Clause. Dedicated CPU family with both task checkpoints and the original ProteinMPNN backbone provisioned by exact size and SHA-256. Acceptance passed for SIF `sha256:985e4d070fb15c99310bdbb22853e655037d0cc27c40726d77d256a5a2befbaf` (job `4632`) and through the production API. | Enabled and READY; monitor production evidence. |
| dynamicMPNN | Code `af351ee737bdb2ca2804a308d9abc8fd7c303270`; MIT. Dedicated CPU family reusing the checksummed original ProteinMPNN checkpoint selected by upstream `get_model_params.sh`. Acceptance passed for SIF `sha256:589715c62dbcd140a1f605a39efd2aa5060502e4e0c0b14ef7aaa53266898052` (job `4629`) and through the production API. | Enabled and READY; monitor production evidence. |
| FAMPNN | Code `aaf788b1502ad95d5c5a84455cfc53f2544f3b45`; MIT. Dedicated CUDA 12.1/Torch 2.4.1 family with three read-only pinned checkpoints. Design, pack, and score passed acceptance for SIF `sha256:f8f56f67c1dad9de1d7e42596919f132ec7a55f8ef34d933291fff4a2492f59d` (jobs `4636`, `4637`, and `4638`) and all three production API cases. | Enabled and READY; monitor production evidence. |
| GREMLIN_LH | Notebook commit `6b8a6beb426fd31bb10c3fdd398abd3355b782f9`; embedded Beerware notice retained. Dedicated CPU/JAX family persists the complete model, matrices, ranked pairs, sequence statistics, history, provenance, and plot. Acceptance passed for SIF `sha256:982eb43c151b6d2986f2f443ebf8dc870bbcfacb94c389e5bbf30b2c276d1f16` (job `4640`) and through the production API. | Enabled and READY; monitor production evidence. |
| EvoSplit, RFdiffusion2, foundry, PPIformer, Mu-Protein, Pallatom, GeoDock | Pinned upstream intake, runtime-family placement, license evidence, and external-asset requirements are recorded in both wait-list mirrors. | Resolve asset licensing/provisioning blockers before implementation. |

## Verification log

- 2026-09-10: read `TODO.md`, `docs/runner-guide/model-resources.md`, and `LONG_TASK_HANDLING.md` in full.
- 2026-09-10: confirmed the starting branch was clean and all requested candidates were wait-list entries.
- 2026-09-10: created branch `feat/runner-adaptation-batch`.
- 2026-09-10: observed provisioned Boltz and SimpleFold filenames; no scientific identity is claimed from filenames alone.
- 2026-09-10: provisioned the pinned CodonTransformer model snapshot under `/mnt/db/weights/revocompute/codontransformer/model`; all six SHA-256 fingerprints match upstream.
- 2026-09-10: first CodonTransformer SIF build found an upstream Poetry package-name/case mismatch; the definition now runs the immutable checkout directly on `PYTHONPATH` and will be rebuilt.
- 2026-09-10: rebuilt `/tmp/codontransformer_v1.sif` successfully (`sha256:96b041e8da1fe29806cd120c70f009bf912f6c09f18b3e2475bc4fe03f00204d`); `%test` passed.
- 2026-09-10: real network-disabled SIF inference and the task-manifest `run.sh` path both produced `optimized_sequences.fasta`, `results.json`, and the wrapper completion marker for the immutable smoke fixture.
- 2026-09-10: fixed stale live-test admission publication and atomically refreshed deployment attestations; all 14 deployed families and the running web admission resolver report READY.
- 2026-09-10: pinned and audited frustraMPNN, dynamicMPNN, and FAMPNN; implemented five TaskType contracts across three dedicated families, with model downloads disabled during normal tasks.
- 2026-09-10: projected all 164 unique pinned CodonTransformer organism names into the Task schema; large enums render as editable autocomplete comboboxes and both browser and API validation reject unlisted strings.
- 2026-09-10: corrected live testing to build selected candidate SIFs and to include not-yet-enabled families; this restores the required validation-before-enablement workflow. Successful live tests now republish admission attestations so the API does not retain stale unavailability state.
- 2026-09-10: finalized CodonTransformer passed real Task -> SLURM -> Apptainer artifact acceptance as job `4603`; the exact candidate receipt records SIF `sha256:5e542ac79f2dadf94e297d56c966a14110c1c54283a44ce47339b43b22de698c`.
- 2026-09-10: completed the headless GREMLIN_LH notebook transcription with a fully pinned dependency closure and solid output artifacts; real live acceptance passed as job `4602` for SIF `sha256:b0a48a9a887f9b050c3db2aef686e1522ae6d25be8c36354965cf6cec2951648`.
- 2026-09-10: broad non-browser regression reached 776 passed and 4 skipped; its sole failure collected the GREMLIN requirements filename during the agent's final lockfile rename, and the finalized affected gate subsequently passed (22 tests).
- 2026-09-10: completed citation metadata for all 31 TaskType manifests; Pythia-ddG now publishes its method citation, ESMDynamic and other user-facing titles preserve publication capitalization, and API/result/BibTeX regression coverage passes.
- 2026-09-10: documented scoped server-state ACL backup, application, verification, and rollback for the operator and service accounts; no host permission command was executed.
- 2026-09-10: final `make test` passed with 793 tests passing and 4 skipped, including all Chromium workspace contracts.
- 2026-09-11: post-review candidate acceptance passed for CodonTransformer job `4639`, GREMLIN_LH job `4640`, dynamicMPNN job `4629`, frustraMPNN job `4632`, and FAMPNN jobs `4636`-`4638`; every declared output contract passed.
- 2026-09-11: the final non-browser regression gate passed with 789 tests and 4 skips. Twelve of thirteen Chromium tests passed; the real Mol* CDN case timed out during the external network outage, while the organism combobox, citation, title, and local result-view tests passed.
- 2026-09-11: PR checks passed, prepared preflight validated all 19 families, and the production restart promoted only the five receipted SIFs. All services restarted successfully and all 19 families report READY.
- 2026-09-11: seven serial submissions through the public API passed terminal-status, nonempty-artifact, and output-contract checks. The credential-free report is `/mnt/data/srv/revodesign/server-slurm/images/live-api-tests/1789062915059294625-five-family.json`; the temporary GPU-enabled account was deactivated and its API key revoked and removed.
- 2026-09-11: started Batch B on `feat/runner-adaptation-remaining`; implemented focused contracts for Boltz, SimpleFold, and ESMFold 2. The combined runner, citation-resolver, and registry gate passes 27 tests. SimpleFold now uses a 95-package SHA-256 lock with the required `fairscale` runtime and without notebook/UI-only dependencies.
- 2026-09-11: completed Batch B implementations for Chai-1 and Protenix; aligned every CUDA-qualified Torch pin between the human-maintained input and generated hash lock. The combined Batch B runner/citation/registry gate passes 46 tests.
- 2026-09-11: provisioned and checksum-verified all ESMFold 2 and Chai-1 assets from official origins through the configured proxy. Protenix's official TOS host failed TLS negotiation through that proxy across 20 bounded curl attempts plus wget, forced-TLS curl, and aria2 checks; no mirror or direct bypass was used.
- 2026-09-11: Boltz Task -> SLURM -> Apptainer acceptance passed as job `4648` with 14 artifacts and all declared output contracts satisfied for SIF `sha256:f73758d09faf3e6c73fc0d5f7aba3efa51a9a7e675a2115971eaf9247a2ea2bc`.
- 2026-09-11: corrected an inherited global memory value of `64` with scoped Batch B task policies instead of changing the global default; the consistent pre-change database backup is `/tmp/revocompute-manage-pre-batchb.sqlite`. Boltz job `4651` and SimpleFold job `4650` passed with 64 GB / four-hour receipts, while Chai-1 job `4653` passed with 128 GB / eight hours.
- 2026-09-11: ESMFold 2 live DBTL exposed and fixed CUDA-driver, CCD-path, adapter-import, and mixed-precision mismatches. Final job `4657` passed all output contracts with 11 artifacts for SIF `sha256:54dc46fe085c69bc713b3b65be0a832c41815187171cd76255538052f0af9360` under its 128 GB / four-hour policy.
- 2026-09-11: a further three bounded Protenix official-origin attempts through the configured proxy reproduced `SSL_ERROR_SYSCALL`; no mirror or direct bypass was used and no partial assets were retained.
- 2026-09-11: normalized Chai-1's runtime proxy clearing, rebuilt the direct SIF, and passed exact candidate acceptance as job `4658` with 16 artifacts for SIF `sha256:1228d3c1e7c166af051aa9e7ef7c9b407576095b246ec0de572a49ac9ea4e472`.
- 2026-09-11: the 23-family prepared dry run and production resource audit passed; the restart promoted only Boltz, Chai-1, ESMFold 2, and SimpleFold, restored all services, lifted maintenance mode, and left all 23 families READY with valid active receipts.
- 2026-09-11: the public catalog exposes 35 TaskTypes, CodonTransformer exposes exactly 164 allowed organisms, and deployed Pythia-ddG, ESMDynamic, and AlphaFold runner pages render correctly cased titles and DOI citations. Authenticated production submissions are waiting on authorization for a protected test credential.
- 2026-09-11: the sandbox-compatible regression gate passed with 831 tests and 4 skips. Thirteen Playwright tests could not launch Chromium because the execution sandbox denied Chromium's sandbox-host shutdown operation; the direct launch reproduced the same host restriction.

## Known blockers

- Eight candidate projects remain on the wait list. Protenix's official asset host still cannot complete a TLS handshake through the configured proxy and has no production assets or live receipt.
- Authenticated production API acceptance for the four newly enabled families requires either a current bearer/API key or authorization to make and fully restore a temporary test-account credential and SimpleFold entitlement.
- Publishing the branch and opening its PR requires confirmation that `https://github.com/YaoYinYing/REvoCompute` is the intended trusted remote; the current GitHub CLI token is also invalid.

## Prior delivery state retained from the previous ledger

The previous `feat/full-fleet-restoration` work completed parameter-contract
hardening and exact-current live validation for all 14 then-enabled families.
Its recorded gates were 743 non-browser tests, 756 coverage tests, 12 browser
contracts, strict Doctor with no diagnostics, strict docs, Compose rendering,
and full-fleet receipts after the OpenDDE scratch-copy correction. Promotion was
still waiting on target `CONFIG_DIR` synchronization. Earlier project-scope
removal was completed and delivered through PR #7; its detailed history remains
available in Git.
