# MCP Deployment & Contextual Guided Tours

**Status:** PLANNED / DESIGN BRANCH ONLY. **Base:** main at `14ea7441fd1aeeccb2abf37a217c1bbf42ab0e6e`.
**Dependencies:** Confirm deployment controller boundaries with PR #76 and route lifecycle hooks from PR #79 before final UI integration. Avoid concurrent writes to `frontend/src/app/shell.ts` / `main.ts`: PR #79 owns those files. This PR primarily owns MCP deployment/docs, `frontend/src/app/guided-tour.ts`, authenticated tour components, safe home docs link.
**Current truth:** `docs/user-guide/mcp-interface.md` documents a working *code-level* Streamable HTTP MCP surface `/k/mcp` with optional `mcp` extra and `MCP_ENABLED=true`. `run/restart.sh` / Compose **do not automatically enable it**. Independent host acceptance has acknowledged gaps. Do not market production endpoint before verifying a target deployment.

## MCP service enablement
- [ ] Read code `revocompute/mcp/{server,asgi,context,handles,services}.py`, `docs/user-guide/mcp-interface.md`, Compose/gateway config, `tests/mcp_live_acceptance.py` and `tests/mcp_host_receipt.py`.
- [ ] Inventory the current real deployment: optional `mcp` package, service env, gateway route to listener, auth and allowed external URL, middleware/rate limits, CSP/CSRF boundaries, CORS/Origin defense, HTTP streaming/proxy timeouts; record redacted availability evidence.
- [ ] Integrate **explicit opt-in deployment** of companion listener (container-internal default port 8081), safe gateway routing to `/k/mcp`, health/rollback instructions. Keep default disabled for non-MCP deployments; no public direct 8081 port exposure, no shadow rate limiter and no second execution plane.
- [ ] Authenticate via documented Bearer or X-API-Key; maintain existing canonical user scope, admission/readiness/quotas/result auth. MCP must **not** expose admin, host ops, GPU credits mutation or arbitrary command/path.
- [ ] Validate end-to-end on *two truly independent MCP hosts* if practical, plus inspector CLI + real streamable HTTP; log honest coverage gaps and negative auth/scope cases.
- [ ] Add clear user docs: generate API key in Account, register remote MCP endpoint with supported client, discover/inspect/preflight/submit/status/results; never include an API key value in docs/commits/screenshots.
- [ ] Surface “Connect AI agent / MCP” only when deployment capability is really reachable and enabled; otherwise documentation-only entry with transparent “not enabled” state. Do not imply GitHub code existence equals deployed support.
- [ ] Preserve original home Docs/API/GitHub link discovery, coordinate link placement with PR #79.

## Guided tours — job-oriented paths
- [ ] Inspect existing `GuidedTour` one-flow design and localStorage persistence; evolve to three independent flows with **separate progress keys**, no stale completion state. No duplicate routing or location.assign loops after PR #79.
- [ ] New user “Create your first Task”: Runner catalog -> choose method -> input roles -> parameters/Seed -> preflight/review -> Task monitoring; **never auto-submit a real Slurm job**; use read-only/synthetic demonstration if explanation needs example result.
- [ ] Results tour is **conditional on owned real finished result**, not visible by default for first-time users; if none exists offer docs/demonstration clearly labeled as synthetic, never fabricate a Task ID.
- [ ] Admin-only tour: Runner Management statuses vs capacity/access, User Control, Quota, logs; never trigger privileged mutation, reset credit, promote SIF, or expose account details.
- [ ] Tour anchor, focus, back/next, skip, restart, responsive placement, role guards, EN/ZH, history/back and route transitions. Dispose overlays/listeners at unmount.
- [ ] Avoid long generic SaaS onboarding and excessive motion; preserve Soft Precision.

## Acceptance
- [ ] MCP real client/host integration contract: wrong credential, cross-user handle, out-of-scope admin command, duplicate submit, disconnected host, token revocation, oversized artifacts and secure gateway route. Record deployment-specific receipt without secrets.
- [ ] Tour Playwright tests for new empty account, user with finished result, admin account and guest/unauthorized; no unintended POST/DELETE; no dead-link or invalid Result URL.
- [ ] Docs `mkdocs build --strict`, frontend typecheck/unit/build, integration CI, independent security and visual review.
- [ ] No production MCP enablement without environment-specific operator safety review; never merge without maintainer authorization.
- [ ] Remove temporary TODO, demo images, generated QA data and agent artefacts from final diff.
