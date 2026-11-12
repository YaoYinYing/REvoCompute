# Release Governance — Version, Changelog and Authenticated Version Page

Status: **implemented**. The version module, the signed-in API and page, the
build identity, the release commands and the tag gate exist in this repository.
Creating a tag, publishing a GitHub Release and deploying remain separate
maintainer decisions; this page describes the gates, not an authorization.

## Verified inputs and precedents

- REvoCompute `main` at `2890609942680e29ce17b3d83f546569434c5247`
  (2026-11-12) declares `0.1.0` in both `pyproject.toml` and
  `frontend/package.json`; no formal application release tags were found.
  Existing `pr-*-evidence` tags/releases are test evidence, not app versions.
- Required changelog specification:
  [Keep a Changelog **1.0.0**](https://keepachangelog.com/en/1.0.0/).
  Follow its `[Unreleased]` header, descending dated version headings,
  `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`
  categories as needed, and link reference definitions. Never create empty
  headings or invent release dates.
- Workflow/style precedent:
  [REvoDesign docs/agents/RELEASE.md](https://github.com/YaoYinYing/REvoDesign/blob/main/docs/agents/RELEASE.md).
  Reuse its concise **module-scoped bullets** (`- Server:`, `- Qt:`, etc.;
  REvoCompute modules should use `- Server:`, `- Runner:`, `- Frontend:`,
  `- Workflow:`, `- Security:` as appropriate), its Unreleased-first
  discipline, and its principle that behavior changes update affected docs in
  the same PR. A `## TEMPLATE` block may be supplied only if kept completely
  empty and cannot be parsed as actual release notes.
- **Do not blindly copy REvoDesign's `make tag` implementation**, which
  requires the version bump to remain unstaged so an unstaged diff parser can
  detect it. Provide an explicit version transition/release-cut command that
  works with normally staged commits, validates the exact tested SHA, and does
  not publish tags automatically.

## Identity model — do not conflate three timelines

**Development snapshot (historic and while base remains at 0.1.0):**
`0.1.0+<git_commit_sha[:7]>`. E.g., the verified 2026-11-12 main snapshot is
`0.1.0+2890609`. Every older commit has its own display version derived from
its actual SHA; this does **not** mean every commit is a tagged release or
requires its own Changelog section.

**Formal application release (future):** maintainer-approved version bump
following SemVer `MAJOR.MINOR.PATCH` (with optional prerelease), with annotated
`vX.Y.Z` tags, verified changelog and explicit GitHub Release. The first
future version is decided during release cut, not retroactively assigned
to old commits. For non-tagged builds after formal release, use a separately
recorded commit/revision or a SemVer build suffix without changing the
canonical released version number in packaging.

**Scientific execution provenance:** independently pin Runner family/Task
schema and execution protocol, SIF/container digests, model weights, resource
policy and relevant evidence. The platform display version is contextual
metadata only; it never replaces these identities.

### Canonical source and build rules

1. The only **editable** base application SemVer source is
   `[project].version` in `pyproject.toml`. Current baseline remains `0.1.0`.
   At request time the server resolves the base version from
   `REVOCOMPUTE_BASE_VERSION` (set by the builder from `pyproject.toml`), then
   the source `pyproject.toml`, then installed package metadata. Source wins over
   metadata so a stale editable install cannot report the wrong version.
2. `frontend/package.json`, both version entries in
   `frontend/package-lock.json`, `uv.lock`'s `revocompute` package entry and the
   OpenAPI `info.version` mirror the canonical base version. They are written only
   by `revocompute-release sync` and rejected on drift by `revocompute-release
   check`; none is an independent source. `uv.lock` is edited textually in its
   existing package block; `uv lock` is never run by the release command.
3. The build captures the **full immutable source SHA** once, and only when the
   working tree is clean. A dirty tree or an unavailable Git records no SHA, so
   the API reports `revision_status: "unknown"` and
   `app_version: "<base>+unknown"`; it never claims the commit of a checkout that
   contains uncommitted code. A build with `REVOCOMPUTE_RELEASE_CHANNEL=release`
   refuses to start unless it is clean and has an exact commit.
   Generate the display version from the base version and that SHA, never from a
   live mutable `main` ref, current browser cache, wall clock or runtime
   `git log`. Bake the same fields into frontend and server assets to detect
   mismatches.
4. Use OCI image labels for source revision and base version where feasible;
   image digest, `built_at`, deployment/environment and release channel
   remain separate fields. The builder records an opaque
   `build_id` (`<sha7>-<UTC compact>`) only beside a verified commit; the image
   digest stays deployment-stamp evidence and is never put in the API. For a
   development build with no trustworthy SHA, report `revision_status:
   "unknown"` and do not synthesize a false seven-character commit. A qualified
   release fails if build identity is unavailable.
5. `app_version` may be the public display string `0.1.0+<sha7>` for
   development snapshots, while Python/NPM package metadata retains `0.1.0`.
   Expose `base_version` separately to avoid confusing package management,
   API compatibility or release automation with a unique build identity.
6. Existing `pr-*-evidence` tags remain evidence-only and must fail the
   formal application-release tag gate.

## Logged-in version page and API

This is **not** a public about page.

### Server

- Introduce `GET /compute/api/version` in the curated OpenAPI contract.
  It uses the existing `login_required` boundary; there is no separate
  decorator. A request without a `text/html` `Accept` header (the API client
  case) receives the standard generic 401 JSON and no protected data. A request
  whose `Accept` header contains `text/html` inherits the standard 302 redirect
  to the login page, with `return_to` naming the requested path; the redirect
  body carries no version data. There is no admin-only requirement.
- Return bounded, server-owned version information with at least:
  `base_version`, `app_version` (display),
  `git_sha` (full SHA when verified), `revision_status`,
  `release_channel`, `built_at` (nullable UTC),
  and immutable `build_id`/image digest when known. Include a bounded,
  safely represented historical changelog payload (or a typed summary list
  built from the checked-in CHANGELOG.md) sufficient to render the version
  page without an unauthenticated second endpoint. The parser reads the
  repository-root `CHANGELOG.md` (`/app/server` in the image) first and the
  installed `share/revocompute/CHANGELOG.md` data-file second. A missing
  changelog is a bounded empty payload with `source_sha256: null`,
  `truncated: false` and `sections: []`, never a 500. The response includes the
  SHA-256 of the bytes it parsed.
- Do not expose paths, credentials, internal environment, private git
  remotes, host details or arbitrary files. Bound changelog length and
  sanitize/untrust rendered Markdown. Use `Cache-Control: private, no-store`,
  and keep the version API out of unauthenticated OpenAPI try-it-out success
  examples. Public source availability is not a substitute for an auth gate.
- Authentication/authorization tests: unauthenticated, invalid bearer,
  expired/invalid session, valid regular user and valid admin; both users
  see the same non-sensitive fields. Contract tests verify no bypass through
  HTML routing, proxies, cache or static SPA prefetch.

### Frontend

- Introduce a **dedicated route** `/compute/version` protected in both
  `frontend/src/app/router.ts` and the server's direct-navigation route
  handler. The existing server-protected account-page pattern can guide the
  implementation; route and navigation parity tests must cover reload and
  deep links.
- Link the page from authenticated navigation or the signed-in shell footer,
  not only via an obscure dialog. Sign-out redirects using the existing
  return-to mechanism and does not show cached protected content.
- Page content: prominent **display version**, short and full commit revision,
  build time if known, release/development state, and a readable
  reverse-chronological changelog. Historical baseline must be clearly labeled
  as a **development snapshot**, not a release. Show absent build fields
  explicitly instead of inventing values.
- Render Markdown without executable HTML, perform loading/error/retry states,
  respect keyboard/screen-reader, dark mode and desktop/tablet/mobile sizing.
  The page uses the existing app shell/navigation/design system and a single
  API response; do not create a parallel frontend version registry.
- Check API identity against baked frontend build identity. If stale/mixed
  deployment is detected, show a diagnostic and offer refresh rather than
  quietly asserting the two revisions match.

## Changelog — curated history, not a Git log

Root `CHANGELOG.md` is the canonical human-readable changelog. It follows
Keep a Changelog **1.0.0**, *not 1.1.0*. Use only its standard change-type
headings; `Breaking` and `Notes` are not extra top-level change categories.
Explain breaking compatibility within `Changed`/`Removed` entries.

- The first backfill is a **single snapshot** section:
  `## [0.1.0+2890609] - 2026-11-12`, explicitly labeled historical
  development snapshot of the source commit.
- Backfill **only verifiable, high-information user/product changes** from
  merged PRs and commit history. Summarize modules and major architecture
  milestones; omit cosmetic polish, CI churn, individual fix-up commits,
  unmerged PRs, and a one-to-one copy of every commit log.
- Historical builds before that snapshot continue to display
  `0.1.0+<their-own-sha7>`; do not retroactively create formal release
  sections, tags, or fabricated changelog dates for each build.
- Use the REvoDesign module-scoped style with brief one-line sub-bullets.
  Write substantive new user-visible changes to `[Unreleased]` when merged.
  Each PR must declare a release-note disposition; internal-only changes
  may be omitted if justified.
- On a formal release cut, move Unreleased changes to one dated
  `## [X.Y.Z] - YYYY-MM-DD` section, recreate `[Unreleased]`,
  and add valid version comparison links. Keep historical snapshot links
  bound to immutable commits.
- If a historic claim cannot be supported by merged code or the resulting
  documented product contract, leave it out rather than guessing.

## Release commands

`revocompute-release` (or `python -m revocompute.release_governance`) is the one
release tool. It never commits, tags, pushes, publishes or deploys.

```bash
# Validate the editable version and every mirror (CI runs this always).
revocompute-release check

# Write every mirror from pyproject.toml deterministically.
revocompute-release sync
```

### Release cut

1. Maintainer selects a SemVer version and explicitly approves release scope.
2. Move the `[Unreleased]` notes to one dated
   `## [X.Y.Z] - YYYY-MM-DD` section and recreate `[Unreleased]` with valid
   comparison links.
3. Update any architecture, developer, operator or agent docs describing
   changed behavior **in the same PR**.
4. Commit the changelog and docs, then run the release cut against the exact
   tested commit:

   ```bash
   revocompute-release prepare-release --version X.Y.Z --sha <tested-commit>
   ```

   It refuses a dirty tree, a HEAD that is not the supplied commit, an existing
   `vX.Y.Z` tag, an invalid SemVer and a missing dated section for today. On
   success it updates `pyproject.toml`, `frontend/package.json`, the frontend
   lockfile, `uv.lock` and OpenAPI `info.version`, and commits nothing.
5. Commit the version bump and run the relevant API, frontend, server, Runner
   contract and deployment safety tests at that exact head.
6. Build with `REVOCOMPUTE_RELEASE_CHANNEL=release`. The build refuses a dirty
   tree or an unavailable exact commit, and the resulting `app_version` is the
   base version with no development suffix.
7. Validate the prospective tag **before creating it**:

   ```bash
   revocompute-release verify-tag --tag vX.Y.Z --sha <tested-commit>
   ```

   The command reads `pyproject.toml` and `CHANGELOG.md` from the commit's own
   Git tree, not the working tree, so local edits cannot make a tag look valid.
   It accepts only `vMAJOR.MINOR.PATCH` with an optional prerelease; evidence
   tags such as `pr-*-evidence` are rejected.
8. Create the annotated `vX.Y.Z` tag and push it explicitly. Never auto-push
   tags or publish merely because a version command ran. The `Release Tag Gate`
   workflow re-runs the same validation on the tagged commit as an audit.
9. Publish the GitHub Release when independently approved; preserve Runner
   readiness and source/asset evidence for the deployed build. Document a
   rollback target and any schema/data migration constraints. Deployment remains
   a separate maintainer decision.

## Acceptance criteria

- `pyproject.toml`, frontend package metadata, both lockfile entries,
  `uv.lock` and OpenAPI `info.version` remain consistent under drift tests.
- A dirty or unversioned build reports `revision_status: "unknown"` and never a
  commit it does not contain; a release-channel build refuses a dirty tree.
- Historic development snapshots render `0.1.0+<correct SHA7>` and never
  impersonate real releases; full SHA remains available for audit.
- One signed-in-only version API and one signed-in-only version page work for
  ordinary users; bypass/redirect/cache tests reject anonymous reads.
- Page renders the high-signal Keep a Changelog **1.0.0** historical backfill,
  reverse chronology and live version/build identity.
- Unit, OpenAPI, browser and full-page-reload tests confirm auth and
  frontend/backend consistency at exact head.
- Release gates accept only explicit SemVer product tags, and never treat
  evidence tags or historical snapshot section as a formal release.
- No existing Runner scientific provenance or operational deployment authority
  is weakened. Draft PR is not merge, tag, GitHub Release or deployment
  authorization.
