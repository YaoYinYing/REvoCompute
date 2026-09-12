# Runner Adaptation Implementation State

This file is the durable execution ledger for `TODO.md`. The definition of done
and candidate-specific requirements remain authoritative in `TODO.md`.

## Current phase

PR #11 release-candidate correctness remediation is in progress. The candidate
fixes are published through `731d3a96ef12bc140fe20e70f40cd64d2869a613`;
the final readiness invalidation fix remains to be committed and reviewed.

Batch A, Batch B, and the validated EvoSplit, PPIformer, and Pallatom families
are deployed. The production inventory contains 26 enabled families.
RFdiffusion2, Foundry, and GeoDock are now explicitly academic-only and await
entitled live acceptance before promotion. Mu-Protein and Protenix were
abandoned by operator decision and their Runner implementations were removed.

## Completion checklist

### PR #11 release-candidate gate

- [x] Keep deployment Runner enablement unchanged by scoped builds and live tests.
- [x] Bind build provenance and live-test receipts to family + exact SIF SHA-256.
- [x] Preserve active evidence while a candidate is built and validated.
- [x] Promote only an exact validated candidate and publish actual post-promotion readiness.
- [x] Enforce exact checkpoint identity for FAMPNN, frustraMPNN, RFdiffusion2, and audit sibling runners.
- [x] Clean disk scratch and wrapper files after every pre-submission failure.
- [x] Document and implement a bounded, allocation-safe RAM scratch startup sweep.
- [x] Make multi-family promotion failure semantics truthful and tested.
- [x] Add the complete staged-lifecycle controller regression test.
- [x] Scope task-policy readiness invalidation and ignore no-op admin saves.
- [ ] Pass focused tests, full pytest, citation, strict docs, Runner Doctor, shell/static, and CI gates.
- [ ] Obtain a fresh current-head review with no P1/P2 correctness finding and freeze both PR heads.
- [ ] Squash-merge PR #10 then PR #11 without deploying intermediate `main`; verify final tree identity.

Focused verification: 170 controller, evidence, scratch, checkpoint, and Runner
tests passed locally. The non-browser suite passed with 922 tests and 4 skips;
the external citation check also passed. Strict docs, Doctor, final static checks,
CI, and fresh review remain.

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
| Protenix | Rejected/deferred by operator decision. Pinned-source intake identified the separate `checkpoint/protenix-v2.pt` weight and exact `common.tar.gz` inventory, but the official ByteDance endpoint is inaccessible. In issue `bytedance/Protenix#296`, an upstream collaborator stated that v2 checkpoint accessibility is under company-level internal review and provided no timeline. The third-party Hugging Face backup is not an official source. | No implementation remains. Reconsider only after ByteDance publishes an accessible official checkpoint. |
| Chai-1 | Dedicated CUDA 12.1/Torch 2.5.1 family implemented for Chai Lab 0.6.1 commit `8d5ac0f93e9b6ea4c3a6545c253a6381c0f3694b` (Apache-2.0 code/model statement). All eight official Chai assets (6,979,394,752 bytes) are provisioned through the proxy and locally SHA-256 verified; the offline contract covers multi-entity FASTA, uploaded MSA/restraints, sampling, confidence arrays, ranked structures, and provenance. After proxy-environment hardening, Task -> SLURM -> Apptainer acceptance passed for SIF `sha256:1228d3c1e7c166af051aa9e7ef7c9b407576095b246ec0de572a49ac9ea4e472` as job `4658`, producing 16 artifacts under the scoped 128 GB / eight-hour policy. Separate asset-level license provenance was not found for `conformers_v1.apkl`. | Enabled and READY; retain the conformer-license evidence and run authenticated production API acceptance. |
| frustraMPNN | Code `3a03cdc300bfe24c4bb70e60207118532bc73b3b`; BSD-3-Clause. Dedicated CPU family with both task checkpoints and the original ProteinMPNN backbone provisioned by exact size and SHA-256. Acceptance passed for SIF `sha256:985e4d070fb15c99310bdbb22853e655037d0cc27c40726d77d256a5a2befbaf` (job `4632`) and through the production API. | Enabled and READY; monitor production evidence. |
| dynamicMPNN | Code `af351ee737bdb2ca2804a308d9abc8fd7c303270`; MIT. Dedicated CPU family reusing the checksummed original ProteinMPNN checkpoint selected by upstream `get_model_params.sh`. Acceptance passed for SIF `sha256:589715c62dbcd140a1f605a39efd2aa5060502e4e0c0b14ef7aaa53266898052` (job `4629`) and through the production API. | Enabled and READY; monitor production evidence. |
| FAMPNN | Code `aaf788b1502ad95d5c5a84455cfc53f2544f3b45`; MIT. Dedicated CUDA 12.1/Torch 2.4.1 family with three read-only pinned checkpoints. Design, pack, and score passed acceptance for SIF `sha256:f8f56f67c1dad9de1d7e42596919f132ec7a55f8ef34d933291fff4a2492f59d` (jobs `4636`, `4637`, and `4638`) and all three production API cases. | Enabled and READY; monitor production evidence. |
| GREMLIN_LH | Notebook commit `6b8a6beb426fd31bb10c3fdd398abd3355b782f9`; embedded Beerware notice retained. Dedicated CPU/JAX family persists the complete model, matrices, ranked pairs, sequence statistics, history, provenance, and plot. Acceptance passed for SIF `sha256:982eb43c151b6d2986f2f443ebf8dc870bbcfacb94c389e5bbf30b2c276d1f16` (job `4640`) and through the production API. | Enabled and READY; monitor production evidence. |
| EvoSplit | Dedicated CUDA 12.6/Torch 2.8 family implemented for commit `6eedfcd5a0551bd1fecf9c51818be19f9e730e19` (Apache-2.0). Target-host live test `evosplit/smoke` passed; authenticated API task `cfdb6b26809f9cfee42c2afe61263f72` finished with 14 artifacts. | Enabled and READY. |
| RFdiffusion2 | Dedicated CUDA 12.1/Torch 2.4 family implemented for canonical commit `d365cbf4db3958814a9f8e4f6f94fa309dfebc2b` (BSD-3-Clause). The official `RFD_173.pt` is provisioned read-only with exact size and SHA-256; motif-scaffold and ligand-binder contracts are separate TaskTypes. Direct SIF validation passed for `/mnt/data/srv/revodesign/server-slurm/images/validation/rfdiffusion2_v1.sif` (`sha256:7bc282b6d44a25b4c10a402ef922aadb364c39ef116ace08612d7386fa79dbcc`). | Academic-only policy accepted; run entitled live acceptance before enablement. |
| foundry | Dedicated multi-capability family implemented for commit `b02eed6a6bdf8f44d14a80cc36e3da13c9f2291c`, with separate RFD3, RFD3NA, and RF3 TaskTypes and actual RF3 early-stop artifact handling. The source closure is hash-locked and direct SIF validation passed for `/mnt/data/srv/revodesign/server-slurm/images/validation/foundry_v1.sif` (`sha256:e81459d680ab52b4612b279dae0d915158f3269af2c6a72b4b11ff4775ebca8f`). Official checkpoints are provisioned read-only and validated against `model-assets.json`: RFD3 `9b3f85923e0d51e9453e15cdd2f8c666e7ce096a60577f57d11bbc54ae6d67c1`, RFD3NA `e8802fbc008cb4cf5a9a04985a331fb068288bdd9a5fcc6deb0861b09699039a`, RF3 `364ef592fd8042a9cf4176d045015190f8322f961ccca38d891b20ca578d3bb0`. | Academic-only policy accepted; run entitled live acceptance before enablement. |
| PPIformer | Dedicated CUDA 11.8/Torch 2.1 family implemented from canonical commit `e324f5f30dd0dae55d194ac6b4d18c772219c3ee`. Target-host live test `ppiformer/smoke` passed; authenticated API task `23cea9909517475282632fa8cd896740` finished with 8 artifacts. | Enabled and READY. |
| Mu-Protein | Rejected/deferred by operator decision after secure-conversion intake could not establish a working pinned inference closure or reproduce an unambiguous upstream score. | No implementation remains. |
| Pallatom | Dedicated restricted CUDA 12.6/JAX 0.4.34 family implemented for commit `b27d70054dec6ce2f5ceadf8977de3d3baf00663`. Target-host live test `pallatom/smoke` passed; the catalog exposes `pallatom_noncommercial` and the supplied tester remains denied without entitlement. | Enabled and READY, restricted to entitled users. |
| GeoDock | Dedicated CUDA 11.8/Torch 2.0.1/PyG family implemented for commit `df8d1f4c24ae2946655f27e7411ba2ffabf3d350`; its bundled checkpoint and ESM2 assets are provisioned read-only with exact hashes. Direct SIF validation passed for `/mnt/data/srv/revodesign/server-slurm/images/validation/geodock_v1.sif` (`sha256:756ce3a95c6796f896a2f31b562ae6a3dd9f39fa85c6d2529e7ed501cc8b7b89`). | Academic-only policy accepted; run entitled live acceptance before enablement. |

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
- 2026-09-11: implemented Batch C contracts for EvoSplit, RFdiffusion2, Foundry, PPIformer, Pallatom, and GeoDock plus a non-runnable Mu-Protein secure conversion boundary. The combined family/registry/workspace gate passes 88 tests before the final review fixes.
- 2026-09-11: provisioned exact official assets for RFdiffusion2, PPIformer, GeoDock, Pallatom, and both Mu-Protein checkpoints through the configured proxy; all recorded byte sizes and published checksums match, and local SHA-256 identities are recorded.
- 2026-09-11: the Batch C review caught and fixed EvoSplit's real MSA Transformer singleton batch axis, Foundry RF3's actual ranking-score early-stop artifact, direct-wrapper unknown parameters, Pallatom task-type validation, and a PPIformer fork URL. Canonical PPIformer revision `e324f5f30dd0dae55d194ac6b4d18c772219c3ee` was verified directly.
- 2026-09-11: moved all production access-policy documents to `docker/runners/common/policy`; manifests reference central policy paths without adding them to image `build_inputs`. Discovery and Doctor now fail closed on missing announced policies, covered by the plugin-discovery regression gate.
- 2026-09-11: audited RosettaCommons-related runtimes. Classic Rosetta/PyRosetta is covered by non-requestable `rosetta_software_noncommercial`; RFdiffusion2 and Foundry use separate non-requestable checkpoint-review policies because BSD source licenses do not establish external checkpoint terms. Official references and scope are recorded in `docker/runners/common/policy/README.md`.
- 2026-09-11: target-host live tests passed for EvoSplit (`evosplit/smoke`), PPIformer (`ppiformer/smoke`), and Pallatom (`pallatom/smoke`). Authenticated API acceptance finished EvoSplit task `cfdb6b26809f9cfee42c2afe61263f72` with 14 artifacts and PPIformer task `23cea9909517475282632fa8cd896740` with 8 artifacts; Pallatom remains denied for the unentitled tester.
- 2026-09-11: direct validation passed for RFdiffusion2, GeoDock, and Foundry SIFs; Foundry's hash-locked CUDA-12.8 closure was rebuilt successfully. The combined Batch C runner/architecture gate passes 141 tests with one expected Mu-Protein skip.
- 2026-09-11: reconciled Protenix's `common.tar.gz` inventory against the pinned source and documented the separate model checkpoint and intentional exclusion of `seq_to_pdb_index.json` for uploaded-MSA inference; the official checkpoint remains absent because the host still fails TLS through the configured proxy.
- 2026-09-11: reviewed the user-provided Hugging Face `TMF001/protenix-v2-weights` page. It is an independently owned "Private Backup," not a ByteDance-controlled publication, and remains excluded under the official-sources-only rule. Upstream issue `bytedance/Protenix#296` confirms that official v2 checkpoint access is under company-level internal review with no timeline. By operator decision, the Protenix Runner, tests, fixtures, and provisioning tooling were removed.
- 2026-09-11: operator disposition set RFdiffusion2, Foundry, and GeoDock to academic-only access using separate requestable central policies. Foundry's three official IPD checkpoints were provisioned read-only and validated against an external manifest. Mu-Protein was abandoned and its conversion implementation, tests, and policy were removed; previously provisioned host assets were left untouched.

## Known blockers

- RFdiffusion2, Foundry, and GeoDock require exact-runtime live acceptance before academic-only enablement. Mu-Protein and Protenix are rejected/deferred rather than active.
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
