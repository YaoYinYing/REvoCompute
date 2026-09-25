# Runner Change-Impact Contract Implementation State

- Branch: `feat/runner-change-impact-contract`
- Design: `TODO.md`

## Completion checklist

- [x] Record the current build, validation, receipt, and submission identity inputs.
- [x] Make Build Identity depend only on the definition and explicit `runtime.build_inputs` contents.
- [x] Define a parsed, deterministic Execution Contract Identity that excludes presentation-only fields.
- [x] Preserve `BUILD_STALE` for image-input changes and `VALIDATION_STALE` for execution/test/policy changes.
- [x] Ensure presentation-only changes invalidate neither build provenance nor live validation.
- [x] Validate declared build inputs are safe, unique, regular files and within the Runner tree.
- [x] Audit production Runner `build_inputs` for obvious executable/runtime omissions.
- [x] Clarify that `family.version` is release/presentation metadata, not automatic build freshness.
- [x] Turn the Example Runner into executable documentation of all three impact paths.
- [x] Update Runner, deployment, and readiness documentation.
- [x] Add behavior-level regression tests for build, execution-contract, and presentation changes.
- [x] Reissue build and receipt evidence written under the earlier build-identity shape.
- [x] Run focused tests, full tests, shell checks, and strict MkDocs.
- [x] Run the three-agent review pass and act on the valid findings.
- [x] Redeploy with `--use-proxy` and run a live Runner test on the target host.
- [x] Push the branch and open a pull request.
- [x] Address the reviewer findings on schema keyword position, workspace backend
      role binding, and optional workspace assets.

## Identity model

- **Build Identity** hashes the definition content, the sorted contents of every
  declared `runtime.build_inputs` file, and the Apptainer version. Runner name,
  `family.version`, the definition's path spelling, and the declaration order
  are provenance-only: they are recorded but cannot stale a SIF.
- **Execution Contract Identity** is a parsed projection: input roles and
  cardinality, the parameter schema minus JSON Schema annotations, argument and
  stage declarations, GPU/network requirements, the result-view source
  selectors and every mapping key except label/scale-only ones, the expected-file
  tree, the runtime entrypoint, resolved `runner.yaml` settings, effective
  resource policy, access-policy requirements, runner-owned workspace-plugin
  asset hashes, and the parsed `test.yaml` plus fixture hashes.
- **Presentation Identity** covers display names, summaries, `use_when`, help,
  citations, categories, and label/scale/axis mapping keys. It invalidates
  neither identity.

## Evidence rekey

Changing the hashed build identity changes the digest of every already-built
SIF, so `_rekey_legacy_build_provenance` reissues stored evidence once. A record
is rekeyed only when its own stored definition and input hashes recompute to the
current digest, so a genuinely changed image input can never be hidden; the one
family whose inputs changed stays `BUILD_STALE`. On the target store this
restores 29 of 30 active artifacts without a rebuild.

## Verification

- `uv run python -m pytest tests/ -m "not browser" -q` → 1204 passed, 19 skipped.
- `uv run python -m pytest tests/ -m browser -n 4 --dist=load -q` → 131 passed, 4 skipped.
- The schema projection is byte-identical to the previous shape on all 55
  production Task schemas, so the keyword-position fix rekeys no evidence.
- `uv run mkdocs build --strict` → clean.
- `uv run python -m revocompute doctor --config-root docker/runners --strict` → OK for all 39 families.
- `%files` sources across all 39 families audited against declared `build_inputs`: no omissions.
- Target host: `prepare --use-proxy` rekeyed 29 families; `runner-status --all`
  reports 29 `VALIDATION_STALE` (SIF current, receipt predates this change),
  `boltz` correctly `BUILD_STALE` on a real `prepare_input.py` change, and no
  runner `BUILD_STALE` for a digest-only reason.
- Live acceptance on the target host: `live-test --runner example` rebuilt its
  SIF and passed `/smoke`; `live-test --runner pythia_ddg` reused the existing
  SIF (`SIF image unchanged — skipping`) and passed, then reported `READY`.
  The passing case ran Slurm job 48003 as user `revodesign` (UID 129), parsed 8
  artifacts, and matched every declared expected file and result view.

