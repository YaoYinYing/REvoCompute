# PR-4a — TODO

- [x] Baseline current /api/tasks, dashboard query and TaskStore visibility/indexes with large dataset.
- [x] Specify bounded query schema, literal search semantics, admin owner scope, signed keyset cursor and consistency policy.
- [x] Implement indexed authorized SQL search/filter/sort BEFORE LIMIT; no per-request full list materialization.
- [x] Extend OpenAPI/generated API client; migrate the dashboard and the admin placement consumer; no unbounded server default.
- [x] Add dashboard incremental fetch, cancellation, accessible Load More and bounded DOM.
- [x] Separate visible Task status polling from history pagination; bulk selection scoped to loaded IDs.
- [x] Permission/cursor/stale/search/date/sort/tie/mutation tests with multi-user DB fixtures.
- [x] EXPLAIN evidence recorded: submitted sort uses `idx_tasks_submitter`/`idx_tasks_uploaded_at`; finished sort and substring search scope by the submitter index and sort/filter inside the authorized set. No schema migration, hence no rollback required.
- [ ] Browser/network metrics and screenshots are the Examiner's acceptance step (not run by the Owner).
- [ ] Server-side rate limiting of history requests: not added; the endpoint keeps the existing authenticated boundary and bounded response size. Decide with the Commander whether a pacing gate belongs in this PR.
- [ ] Adviser/Examiner/Auditor exact-head evidence.
- [ ] No merge or deployment without maintainer decision.
