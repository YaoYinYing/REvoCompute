# PR-1a — TODO

- [ ] Record main exact head, current Nginx configuration, multipart `/post` + preflight handling, 16 MiB limits and upload receipts.
- [ ] Benchmark raw response/upload paths and choose a single negotiated per-file gzip contract; Adviser sign-off before code.
- [ ] Implement selective Nginx response compression with ETag/Vary and range exclusion; measure real wire savings.
- [ ] Implement server-supported encoded file-part metadata with bounded decompression before existing quarantine/scientific validation; preserve legacy identity.
- [ ] Implement browser adaptive CompressionStream + identity fallback, AbortSignal and original/transfer progress labels.
- [ ] Test original SHA and duplicate receipts, invalid/truncated/double encoded bodies, bombs, limits, temp cleanup, API clients and auth.
- [ ] Run end-to-end browser and proxy tests on the exact head; collect before/after bytes, latency and screenshots.
- [ ] Independent Adviser, Examiner and separate final Acceptance Auditor PASS; update CHANGELOG.md [Unreleased]; maintainer-only merge/deploy.