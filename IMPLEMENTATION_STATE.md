# Runner Adaptation Wait List Task State

## Completion checklist

- [x] Inspect existing README, runner/runtime docs, adapter guides, and roadmap documents.
- [x] Add a focused wait-list planning record without implementing or enabling candidates.
- [x] Record all 12 requested upstream projects and distinguish wait-list status from support.
- [x] Mark unverified license, asset, hardware, presentation, and runtime-family facts as TBD/not assessed.
- [x] Link the wait list from the nearest runner documentation index.
- [x] Verify repository links, candidate count, documentation build, and diff cleanliness.

## Verification

- Wait list: `RUNNER_ADAPTATION_WAIT_LIST.md`.
- Runner index link: `docker/runners/README.md`.
- MkDocs wrapper/navigation link: `docs/runners/wait-list.md` and `mkdocs.yml`.
- `mkdocs build --strict`: passed (upstream Material warning only).
- URL/count check: 12 GitHub URLs and 12 `Wait list` entries.
- `git diff --check` and `bash -n run/restart.sh`: passed.
- AF2 was rebuilt from current local upstream revision `e5c2cdd59c87df41d1f0b9e49c3820a267726766`, with refreshed pipeline patch, `uv` installs, explicit OpenMM 8.2.0 and pdbfixer 1.12.0, then passed live acceptance and was promoted.
- Staged SIFs for AF3, ColabFold AF2, ESM dynamic, FreeBindCraft, MPNN, OpenDDE, Placer-RFdiffusion, Prime, Gremlin, and Pythia DDG passed live acceptance and were promoted on 2026-09-06. Gateway is live and submissions resumed.
- BioEmu initially attempted an unprovisioned AF2 weight download; correcting its cache mount to `/home/yinying/.cache/colabfold` allowed the pre-provisioned parameters to be used and its live test passed.
- ESM extraction initially lacked a result contract; an evidence-bundle view for the emitted `.pt` artifact was added and the full ESM smoke collection passed.
- EasIFA moved from Bullseye to Bookworm after repeated Bullseye security mirror 404s, then built and passed live acceptance. Its ESM checkpoint mount was corrected to `/home/yinying/.cache/torch/hub/checkpoints`.
- All 14 enabled Runner families now have passing live receipts and promoted SIFs. The full prepared deployment completed on 2026-09-06, maintenance mode was lifted, and submissions resumed. The scheduler `USER` is `yinying`; `unknown-user` appears only in application log filenames.

## Scope note

This task intentionally makes no Runner runtime, container, registry, policy, or
server integration changes. Existing broader documentation-system work in the
worktree predates this focused request and should be reviewed or split
separately.
