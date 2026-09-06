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
- BioEmu live test failed during runtime because its first-run path attempted to download 3.47 GB AF2 weights; provisioning/entitlement is unresolved and it was not promoted.
- ESM MSA passed, but ESM extraction failed artifact acceptance because its output contract is not configured; it was not promoted.
- EasIFA remains unbuilt after repeated Bullseye security mirror 404s (`libc-dev-bin`/`linux-libc-dev`); this is an external package-mirror blocker, not a guessed dependency change.
- The authoritative full-fleet validation is therefore incomplete until EasIFA, BioEmu, and ESM have resolved build/runtime/contract evidence. The current scheduler `USER` is `yinying`; `unknown-user` appears only in application log filenames.

## Scope note

This task intentionally makes no Runner runtime, container, registry, policy, or
server integration changes. Existing broader documentation-system work in the
worktree predates this focused request and should be reviewed or split
separately.
