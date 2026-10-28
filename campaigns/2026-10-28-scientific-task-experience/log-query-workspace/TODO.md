# TODO — feat(logs): lazy log loading, indexed search and viewer UX

**Planning PR; not implemented or merge-ready.**

## Goal
Build bounded, authorized lazy log retrieval and searching with safe regex, syntax highlighting, contextual navigation and virtualized rendering. Preserve the merged #116 diagnostics contract.

## Initial evidence
- PR #116 merged into this main and fixes bounded/redacted Slurm stderr capture; do not duplicate it.
- Current user report: streaming currently loads full logs and has no bounded server-side search.
- Stage markers and logs are observational data; neither is an authoritative StageRun state transition.

## Work checklist
- [ ] Audit current live/final log producers, publication snapshots, authenticated reads, redaction policies, Slurm failure diagnostics and UI. Document actual log sources.
- [ ] Design a backward-compatible paged query contract with cursor/byte-range, log identity, monotonic offsets, line boundaries, max bytes/lines and EOF/truncation metadata.
- [ ] Implement bounded range retrieval and live-follow with incremental updates, backpressure, reconnection/resume and cancellation; no full-file browser retention.
- [ ] Keep running and immutable finalized logs distinct; never expose host-only scheduler files or permit arbitrary filesystem paths.
- [ ] Implement server-side literal search plus opt-in bounded regex (safe linear-time engine or rigorously enforced complexity, time and byte budget), rate limits, authenticated scope, result caps and pagination.
- [ ] Apply authorization, redaction and terminal-control sanitization before search, preview, snippet, highlighting or export; avoid side-channel leakage of hidden matches.
- [ ] Support UTF-8 boundaries, long lines, CRLF, duplicated timestamps, rotated/truncated logs, mixed sources, multiple allocation attempts and error paths.
- [ ] Build a compact log viewer with virtual scrolling, source tabs, follow/pause, scroll anchoring, search/regex toggle, match navigation, contextual snippets, severity/token highlighting, export of approved excerpts and accessibility.
- [ ] Retain existing evidence and diagnostic authority; ensure StageRun-compatible log identity is optional until Stage State PR #118 lands.
- [ ] Document API schema, size/time/rate limits, privacy controls, operator behavior and localized labels.

## Acceptance and regression
- [ ] Bounded memory/response under synthetic GB-scale logs; no automatic full-history fetch; cursor stability on append and truncation.
- [ ] Security regression: credentials/PEM blocks, malicious HTML/ANSI, regex denial-of-service, search-count leakage, unauthorized user scope and private paths.
- [ ] Correct stdout/stderr attribution and #116 error publication; multi-attempt ordering and network reconnection.
- [ ] Browser tests for keyword and regex hits, scrolling, pause/follow, error/empty states, mobile and keyboard; exact-head CI.

## Explicit non-goals
- No secondary logging database or replacement for Slurm/diagnostic publication.
- Do not let user regex execute unbounded Python re against arbitrary-sized text.

## Dependencies
Independent after merged PR #116; optionally adapt to #118 stage API in a separate small follow-up.

## Agent protocol
- [ ] Read current CLAUDE.md, LONG_TASK_HANDLING.md and Single-PR Campaign Protocol before implementation.
- [ ] Assign one owner and maintain an independently active Campaign Adviser. Maintainer retains final squash-merge authority.
- [ ] Keep IMPLEMENTATION_STATE.md current once implementation starts; evidence and exact head in PR thread are canonical.
- [ ] Add regression evidence, docs, scientific rationale and fail-path tests; perform independent exact-head merge-level review.
- [ ] Remain draft until all requirements are met; do not merge on a planning-only commit.
