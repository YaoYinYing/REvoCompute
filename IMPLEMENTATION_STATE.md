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
- [ ] Redeploy with `--use-proxy` and run a live Runner test on the target host.
- [ ] Push the branch and open a pull request.

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

- `uv run python -m pytest tests/ -m "not browser" -q` → 1201 passed, 19 skipped.
- `uv run mkdocs build --strict` → clean.
- `uv run python -m revocompute doctor --config-root docker/runners --strict` → OK for all 39 families.
- `%files` sources across all 39 families audited against declared `build_inputs`: no omissions.
