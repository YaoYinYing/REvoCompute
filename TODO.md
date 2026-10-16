# TODO — Scientific Parameter Semantics Remediation

> Planning Draft. Remove root TODO.md before merge. Draw confirmed findings from PR #92; do not independently invent a full Runner parameter inventory.

## Invariant

Each visible Task parameter must have a documented, effective scientific interpretation. The `task.yaml` JSON Schema is the sole authoritative parameter vocabulary; normalized defaults and constraints are applied once. No control may appear to change a computation while the adapter silently discards it.

## Known case

`docker/runners/foundry/tasks/foundry_rfd3na_design/task.yaml` declares `num_recycles` while `docker/runners/foundry/launch.py` explicitly forwards `inference_sampler.n_recycle` only for `rfd3` (fixed by the RFD3NA checkpoint). Determine whether RFD3NA should remove the user-facing control or model it as a truthful read-only/derived property. Do not simply forward an invalid CLI arg.

## Tasks

- [ ] For each proposed fix, cite pinned upstream code/docs, task schema, launcher and a realistic input; distinguish fully exposed, partially exposed, unsupported and internal-only flags.
- [ ] Confirm actual CLI/Hydra/API behavior with a minimal argument capture or available local runtime. Mark changes requiring unavailable weights as unverified.
- [ ] Remove or clarify no-op controls and misleading descriptions. Respect model-specific conditional applicability and device/resource limits.
- [ ] Apply the canonical Task Schema to parameter defaults, input validation, UI projection and manifest provenance; do not duplicate defaults in scripts.
- [ ] Ensure accepted parameter values are actually forwarded once, type/range validated, and preserved in immutable run provenance. Reject unsupported knobs explicitly.
- [ ] Check relevant selected high-impact families (Foundry RFD3/RFD3NA/RF3 and any additional evidence-backed PR #92 priority), not a speculative global flag-exposure expansion.
- [ ] Add focused executable command-builder tests demonstrating each changed parameter changes or intentionally does not change the upstream invocation; cover defaults and edge cases.
- [ ] Update scientific help/documentation only to match verified semantics; no UI makeover.
- [ ] Classify changes through Build/Runtime Bundle/Execution/Presentation identities and invalidate or rerun live-test receipts as required by existing policy.
- [ ] Keep existing published tasks and input/result artifact semantics stable. Do not reinterpret older provenance retroactively.

## Acceptance

- [ ] No demonstrably ignored adjustable knob remains in the remediated TaskTypes.
- [ ] No unsupported flag is forwarded upstream or hidden as a harmless no-op.
- [ ] Evidence-backed minimal and nondefault parameter tests pass.
- [ ] No side effects on admission, credit accounting or file authorization.
- [ ] Report other unverifiable families as backlog, rather than pretending fleet-wide exhaustiveness.
- [ ] No Foundry 1.0 version change in this PR; synchronize after version-upgrade decision.
- [ ] Root TODO removed before merge.

No merge/deploy/force-push without owner authorization.
