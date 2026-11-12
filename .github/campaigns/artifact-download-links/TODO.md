# PR-1b — TODO

- [ ] Audit existing GET/HEAD/Range/If-Range, publication resolver and access-control behavior with byte-exact fixtures.
- [ ] Design per-artifact issuance, TTL/signature, hashed revocable grants, key rotation, token/redaction/logging and API schema.
- [ ] Implement authenticated issuance/revocation and isolated unauthenticated bearer download GET/HEAD.
- [ ] Complete Range + If-Range semantics on a shared verified artifact reader; preserve identity bytes under proxy compression.
- [ ] Add expiry/revoke/renew UX in Results with copy, warning and no-referrer boundaries.
- [ ] Adversarial unit/server/proxy/IDM-style parallel-range tests, policy-change and concurrent-deletion cases.
- [ ] Browser tests and screenshots, documentation, CHANGELOG.md [Unreleased], Independent Adviser/Examiner/Auditor PASS.
- [ ] No production promotion, tag or merge without explicit maintainer approval.