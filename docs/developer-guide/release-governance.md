# Release Governance — Application Version and Changelog

Status: **proposed implementation contract**. The Campaign PR introduces this design and a changelog skeleton. None of the runtime, CI, tag, or deployment behavior below is claimed to exist until its acceptance checks pass.

## Baseline and purpose

As inspected on 2026-11-12 at main commit 2890609942680e29ce17b3d83f546569434c5247:
- Python project metadata declares version 0.1.0.
- Frontend package metadata declares version 0.1.0.
- The root had no CHANGELOG.md, TODO.md or ORIGINAL_DESIGN.md.
- Existing release/tag records are PR verification-evidence artifacts, not a formal application release series.
- This proposal makes no retroactive claim that version 0.1.0 has shipped.

A platform version answers which REvoCompute API and frontend build the user is running. A deployment identity answers which exact image was installed where. A Runner identity answers which independent scientific implementation and assets produced one Task. These must never collapse into one number.

## Release identity and version source

1. Use the Python project's version field in pyproject.toml as the **canonical human-facing application version**. Do not create a second editable VERSION file. The current 0.1.0 value is retained until a qualified release decision.
2. Frontend package.json and package-lock.json must mirror the canonical version. Provide one explicit synchronizer/checker; CI rejects drift, including lockfile drift. Do not add an independently editable frontend version.
3. Use Semantic Versioning for platform releases. Prior to 1.0.0, incompatible changes may be released in minor versions, but must still be prominent in release notes. Pre-release tags use accepted SemVer suffixes.
4. Annotated application tags follow vMAJOR.MINOR.PATCH (or vMAJOR.MINOR.PATCH-prerelease). Existing pr-*-evidence tags retain their separate evidence role.
5. Do not infer or silently modify the product version from Git tags at application runtime. A release gate checks tag-to-metadata equality; an immutable build bakes the verified metadata.

### Required build identity

Expose a bounded version projection to the frontend and operators, with fields:
- app_version: the canonical SemVer value;
- git_sha: the full source revision captured **at image build**;
- build_id or image_digest: immutable build provenance, when known;
- built_at: UTC build timestamp, when known;
- release_channel: development, prerelease or stable, derived at build/release time.

Use a small server-owned version module and one documented endpoint (proposed: GET /compute/api/version). It must not reveal environment variables, filesystem paths, internal deployment secrets, or Runner/model inventory. Return an explicit unknown build field for a local development build that did not inject provenance. A qualified tagged release must fail its release gate if source/build identity is missing.

Expose application version and abbreviated revision in an accessible frontend About/Version surface; both browser and server must come from the same deployment build. A mismatch or stale frontend bundle should be observable, not silently presented as a valid coherent release.

Add OCI image labels such as org.opencontainers.image.version and org.opencontainers.image.revision without making Docker labels a second source of truth.

### Independent scientific identities

Never map application SemVer directly to:
- Runner family's scientific Task schema version or Execution Protocol;
- the exact Apptainer/SIF image digest;
- model-weight digest or runtime dependency closure;
- database migration/schema epoch;
- scheduler policy revision or deployment resource topology.

Keep the current manifest/provenance ownership model. A Task receipt should retain the exact immutable scientific evidence that the runtime already generates; a platform version can be added as contextual metadata only when that is authoritative and does not overwrite historic evidence.

## Changelog contract

Root CHANGELOG.md is the human-readable source for release notes:
- Maintain one Unreleased section at the top.
- Curate substantive user-visible entries under Added, Changed, Deprecated, Removed, Fixed, Security, and Breaking where appropriate. Do not add empty headings.
- Technical PRs label a release note as user-facing, internal-only, docs-only, or no-release-note, with a short justification; a rigid release-note fragment framework is not required.
- On release, move the curated Unreleased entries into an immutable dated version heading and leave a new empty Unreleased section.
- Release notes must name any deployment migrations, API incompatibilities, data/schema compatibility limits and rollback constraints.
- Security notes must communicate impact and remediation without publishing exploitable detail prematurely.
- Do not manufacture historical release entries from merged PRs.

GitHub Releases may be generated from the curated version heading plus CI artifacts, but release evidence tags and operational prereleases must never be mistaken for product releases.

## Workflow and gates

### During development

- Code changes enter through scoped PRs with tests appropriate to the changed boundary.
- User-visible behavior changes include a proposed changelog entry or a documented reason not to add one.
- The source version remains unchanged on most feature PRs; it is bumped explicitly by the release-cut PR.
- Build metadata always records Git SHA even when the source version remains in development.

### Release cut

1. Choose SemVer increment based on behavior and compatibility, not PR count.
2. Update canonical version, synchronize frontend metadata and lockfile, finalize dated changelog section.
3. Verify OpenAPI/client generated contract, server/frontend tests, policy and schema checks, security boundaries and immutable image build.
4. Verify image's baked revision and version, qualified readiness and deployment rollback plan.
5. Create an annotated vX.Y.Z Git tag pointing at the tested release commit; publish release notes only after gates pass.
6. Make production deployment a **separate, explicit maintainer decision**. Tagging or merging must not automatically deploy.
7. Record deployment source SHA, image digest, time, environment and rollback target using the existing operator-owned process.

A simple script and CI contract test should verify metadata equality, valid SemVer, correct changelog headings, and release tag consistency. Do not introduce a new publishing framework or a private version registry merely to satisfy these gates.

## Acceptance criteria

- Exactly one editable application version; Python, frontend and lockfile agree.
- A drift test fails when either frontend metadata file is deliberately changed.
- API reports deterministic app and build identities in deployment, with safe development fallback.
- Browser About/Version surface matches server metadata for the same build.
- Root changelog records Unreleased and curated releases; test rejects missing tagged release notes.
- Evidence-only tags cannot pass for formal releases.
- Existing Task schema, Runner image/weight provenance, and runtime scheduling behavior remain unchanged by this PR.
- A release does not occur automatically when the implementation PR is merged; maintainer retains release and squash-merge authority.
