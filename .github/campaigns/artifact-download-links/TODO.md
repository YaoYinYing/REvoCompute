# PR-1b — TODO

Landing order: #150 (response compression, Nginx template) → #151. The bearer
route declares a full representation `Content-Encoding: identity` with
`Cache-Control: no-transform` so #150's compression cannot weaken the strong
artifact ETag; 206 responses were already excluded from compression by #150.
The Nginx token-log map remains #150-owned; #151 supplies the Flask-level
redacted log path (`x-log-path`) that the gateway format can consume.

- [x] Audit existing GET/HEAD/Range/If-Range, publication resolver and access-control behavior with byte-exact fixtures.
- [x] Design per-artifact issuance, TTL/signature, hashed revocable grants, key rotation, token/redaction/logging and API schema.
- [x] Implement authenticated issuance/revocation and isolated unauthenticated bearer download GET/HEAD.
- [x] Complete Range + If-Range semantics on a shared verified artifact reader; preserve identity bytes under proxy compression.
- [x] Add expiry/revoke/renew UX in Results with copy, warning and no-referrer boundaries.
- [x] Adversarial unit/server/proxy/IDM-style parallel-range tests, policy-change and concurrent-deletion cases.
- [ ] Browser tests and screenshots, independent Adviser/Examiner/Auditor PASS.
- [ ] Documentation, CHANGELOG.md [Unreleased] (updated; final review pending).
- [ ] No production promotion, tag or merge without explicit maintainer approval.