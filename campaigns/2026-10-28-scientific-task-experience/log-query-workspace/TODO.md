# TODO — feat(logs): retained-excerpt reading and search

**Planning PR; implementation narrowed after re-grounding the premise.**

## Goal
Let an authorized reader inspect and search the bounded, redacted failure evidence
without leaving the failure panel, and keep that evidence sanitized. Preserve the
merged #116 diagnostics contract.

## Premise re-grounding (2026-10-28)

The initial premise — "streaming currently loads full logs and has no bounded
server-side search" — is false for the diagnostics path:

- Evidence is failure-only (`execution_diagnostics.py`, `diagnostic_payload`:
  a non-`failed` task returns an `unavailable` payload). A running task has no
  log read at all.
- The adapter record is capped (`MAX_RECORD_BYTES`) and read only through a
  verified manifest artifact whose digest and Task identity must match.
- Each stream is redacted, bounded (`MAX_LOG_BYTES`), and further reduced to a
  tail `preview` (`PREVIEW_BYTES`). The download endpoint returns that same
  bounded excerpt.
- The frontend performs one GET per open/retry and renders the preview; it does
  not stream, poll, or read a full log.
- The only other log read is the artifact text preview, bounded by a `Range`
  request and byte ceiling.

No live stream, full-log retention, unbounded search input, or GB-scale viewer
exists to build against. See `IMPLEMENTATION_STATE.md` for file/line evidence.

## Implemented increment

- [x] Audit the real producers, publication, authorization and UI reads.
- [x] Keep the #116 record, bounds, redaction and authorization contract.
- [x] Server: strip Unicode bidi/zero-width format controls with the existing
      terminal-control sanitization before the excerpt is published.
- [x] Frontend: load the already-bounded, already-redacted excerpt on request
      (no automatic fetch) and render it with excerpt-relative line numbers.
- [x] Frontend: literal, case-insensitive search with match count, next/previous
      navigation, keyboard handling (Enter, Shift+Enter, Escape) and a bounded
      match/render cap. No user-authored regular expressions.
- [x] Failure state keeps the preview and download available; aborting the panel
      discards a pending excerpt.
- [x] Document the user contract in `docs/user-guide/task-states.md`.

## Deliberately not built (no corresponding real input or authority)

- [x] Live-follow, reconnection and backpressure — there is no running-task log
      stream to follow.
- [x] Byte-range paging and virtual scrolling of GB logs — the retained record
      is bounded and no full log is exposed to the browser.
- [x] A server-side search endpoint — the whole retained stream is bounded and
      already downloadable by the same authorized reader, so server search would
      duplicate the payload without adding safety.
- [x] Regex search, a logging database, or a second persistence store.
- [x] StageRun log identity — optional until the Stage State PR lands; not
      needed by this increment.

## Verification

- [x] Unit: excerpt bounds, path validation, authorization refusal, literal
      search, metacharacters, match/render caps, failure and abort disposal.
- [x] Server: redaction/bidi sanitization through the real API, existing
      diagnostics/slurm suites, boundary check.
- [x] Browser: readable/searchable excerpt, keyboard navigation, redaction,
      desktop and mobile layout, exact head.
- [ ] Independent exact-head review and final acceptance (campaign roles).
