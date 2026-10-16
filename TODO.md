# TODO — Runner-owned Demo Inputs

> Planning Draft. Remove root TODO.md before merge. Coordinate API ownership with PR #92 and Task-scoped structure with the Storyboard PR; do not accidentally tie demos to a particular scientific renderer.

## Principle

`test.yaml` and `tests/data/` exist for operator/CI acceptance; a **Demo** is a scientist-facing, supported Task input preset. A reusable physical file can support both, but a live-test smoke case is NOT automatically safe, license-clean or useful as a public sample. No demo silently creates a Task.

## Contract

- [ ] Design optional Task-owned `demo/` with a bounded declarative manifest (`demo.yaml` or equivalent). Each entry has stable ID/title/purpose, exact named-role files, compatible typed params, attribution/source, license or redistribution permissions, sha256, and optional scientific context. Include max file sizes/count and digest behavior.
- [ ] Allow several demos for a single TaskType (e.g. monomer and complex), without introducing a global Task-name catalog.
- [ ] Core validates safe relative paths, symlinks, size limits, sha256, media types, ownership, permissions, and the canonical Task Schema; never trusts arbitrary URLs or executes demo scripts.
- [ ] Expose a small GET catalog + safe obtain/download API with typed OpenAPI schema, only for deployment-controlled fixtures. Do not make the server fetch remote datasets on behalf of users.
- [ ] In Daylight Create Task, provide a discoverable **Load example** affordance. It fills named input roles, parameters and relevant metadata in one deliberate action, shows what changed, and remains editable.
- [ ] Loading alone must NOT submit, reserve compute credits, create durable job identity, skip preflight, or bypass authorization/entitlement/readiness/validation.
- [ ] Define behavior for replacing unsaved user edits and restoring prior state; require confirmation before destructive replacement.
- [ ] Validate examples with the same input format/profile and parameter grammar as regular user uploads, not a second special-case implementation.
- [ ] Provide small redistributable demos for Example Runner, fpocket and GREMLIN_LH if provenance is sufficient; otherwise mark unavailable rather than fabricate. Treat Foundry RF3 as optional follow-up if input rights and host footprint permit.
- [ ] Keep large PDB/MSA/weights/model outputs out of Git. Demo reference results, smoke tests and online user examples remain distinct interfaces.
- [ ] Test anonymous/user/admin behavior, mobile accessibility, large/unsafe assets, path traversal, unknown role IDs, changed schemas, disabled TaskType and no-submit guarantee.
- [ ] Update Runner contributor guide with a canonical demo example and instructions for adding/reviewing reusable data.

## Acceptance

- [ ] One authentic Runner-owned Demo loads into Daylight as a valid editable task, without a Task being created.
- [ ] Validates through the same server-authoritative API as manually chosen inputs/params.
- [ ] No unauthorized host filesystem or internet data access; no private data/license leakage.
- [ ] No scientifically false presets; each bundled demo has provenance and justified parameter defaults.
- [ ] Preserve existing create-task flows and exact API versioning; no changed production submission logic.
- [ ] Relevant frontend/Flask/contract/browser tests pass, including clean no-demo fallback.
- [ ] Remove this temporary TODO before merge.

## Boundaries

No large dataset downloader, no CDN-backed arbitrary URL loader, no global examples table, no submission shortcuts, no upstream Foundry/SIF changes. Do not merge/deploy/force-push without authorization.
