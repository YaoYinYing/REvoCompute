# PR-4a — TODO

- [x] Baseline current /api/tasks, dashboard query and TaskStore visibility/indexes with large dataset.
- [x] Specify bounded query schema, literal search semantics, admin owner scope, signed keyset cursor and consistency policy.
- [x] Implement indexed authorized SQL search/filter/sort BEFORE LIMIT; no per-request full list materialization.
- [x] Extend OpenAPI/generated API client; migrate the dashboard and the admin placement consumer; no unbounded server default.
- [x] Add dashboard incremental fetch, cancellation, accessible Load More and bounded DOM.
- [x] Separate visible Task status polling from history pagination; bulk selection scoped to loaded IDs.
- [x] Permission/cursor/stale/search/date/sort/tie/mutation tests with multi-user DB fixtures.
- [x] EXPLAIN evidence recorded (SQLite 3.53.1):
  - user submitted: `SEARCH tasks USING INDEX idx_tasks_submitter (submitted_by_user_id=? AND uploaded_at<?)`, then a temp B-tree for the `md5sum` tie term.
  - admin submitted: `SEARCH tasks USING INDEX idx_tasks_uploaded_at (uploaded_at<?)`, then the same tie term.
  - finished sort: `SEARCH tasks USING INDEX idx_tasks_submitter (submitted_by_user_id=?)`, then a temp B-tree for `finished_at DESC NULLS LAST, md5sum DESC`.
  - substring search: same submitter-index scope, then the literal `LIKE` filter; a leading-`%` substring cannot use a B-tree.
  - No schema migration, hence no rollback is required. A composite `(submitted_by_user_id, finished_at, md5sum)` index is deferred until production-volume EXPLAIN shows the scoped finished sort is a bottleneck.
- [ ] Browser/network metrics and screenshots are the Examiner's acceptance step (not run by the Owner).
- [ ] Server-side rate limiting of history requests: not added; the endpoint keeps the existing authenticated boundary and bounded response size. Decide with the Commander whether a pacing gate belongs in this PR.
- [ ] Adviser/Examiner/Auditor exact-head evidence.
- [ ] No merge or deployment without maintainer decision.
