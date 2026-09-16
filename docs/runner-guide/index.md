# Runner Guide

This section is for people authoring or maintaining a scientific runtime family.
Start with the [Adding a Runner](adding-a-runner.md) walkthrough and the
CPU-only `docker/runners/example/` reference family. Runner families are
self-contained under `docker/runners/<family>/`; each owns its manifests,
direct Apptainer definition, test plan, and runtime script.

## Pages

- [Runner Family Protocol](runner-family-protocol.md) — what every family owns
  and the direct-SIF lifecycle.
- [Plugin Manifest](plugin-manifest.md) — the `plugin.yaml` contract.
- [Task Contract](task-contract.md) — `task.yaml` roles, formats, and
  cardinality.
- [Runner Weights and Model Assets](model-resources.md) — provisioning,
  mounting, and validating large pretrained assets.
- [Test Plan](test-plan.md) — the family `test.yaml` smoke/live plan.
- [Access Policy](access-policy.md) — declarative entitlement for restricted
  families.
- [Adding a Runner](adding-a-runner.md) — the standard Example Runner-based onboarding path.
- [Docking Runners](docking-runners.md) — the molecular docking suite.
- [Adaptation Wait List](wait-list.md) — families queued for adaptation.
