# Create Task — complete parameter fidelity & Seed UX

**Status:** PLANNED / DESIGN BRANCH ONLY. No implementation evidence yet. **Base:** main at `14ea7441fd1aeeccb2abf37a217c1bbf42ab0e6e`.
**Owner:** `frontend/src/features/create-task/`, single owning `task.yaml` files only when source is scientifically wrong, narrow server/API projection or tests if necessary.
**Reported symptoms:** AF3's Runner detail shows `max_template_date`, `resolve_msa_overlaps`, `conformer_max_iterations`, `fix_standalone_glycans`, `num_recycles`, `num_diffusion_samples`, `save_embeddings`, `save_distogram` but Create Task shows only the JSON upload. Seed control's old dice was replaced by a standalone “Randomize seed” text button.

## R0 — reproduce & map semantics
- [ ] Read CLAUDE.md § Task input contracts and `docs/developer-guide/frontend-design-language.md`; inspect `docker/runners/alphafold3/tasks/predict/task.yaml`, `run.sh`, `frontend/src/features/runners/index.ts`, `create-task/api.ts`, `InputWorkspace.ts`, `builtins.ts`, `parameter-controls.ts`.
- [ ] Reproduce AF3 detail vs Create Task discrepancy on built frontend with canonical backend schema. Record all eight names/types/defaults/min/max/description and whether the runtime `scientific_args` consumes them, distinguishing feature/model stages.
- [ ] Identify the actual missing workspace parameter capability; establish invariant **every executable user-editable parameter in canonical task.yaml is discoverable and edit-accessible even when the task's workspace declares only files/review**, except explicitly server-declared read-only or hidden parameters.
- [ ] Map params that a workspace's specialized plugin already owns; prevent duplicate fields and ambiguous precedence. Schema projection remains server-authoritative.

## Implementation
- [ ] Render a canonical automatically projected parameter area (basic first, Advanced in disclosure) for every task type, including AF3 with `files` + `review` only. Prefer a reusable Workspace capability/projection path over per-runner hacks; do not write a second AF3 schema in TS.
- [ ] Honor JSON Schema: boolean, integer, number, string/date, enum, inclusivity/exclusivity, default-vs-omitted semantics, empty values and optional flags. Do not materialize absent optional defaults as scientific changes.
- [ ] All presented parameter values must pass through the same submission collection, server preflight and Runner execution; preserve immutable input and provenance contracts. No silent parameter loss when capability is absent.
- [ ] Restore **Seed [editable value | dice icon inside field] / Reset at label edge / descriptive help below** as existing approved screenshot. Only change seed-enabled controls; retain keyboard and screen-reader support. Dice updates value + validation and leaves unrelated form fields intact.
- [ ] Secure random integer sampling with `crypto.getRandomValues` and rejection sampling where range introduces modulo bias. Respect declared min/max and integer precision; do not use `Math.random`, hardcode the value from the mock, or introduce an extra visible “Randomize seed” line.
- [ ] Reuse the *layout and behavior* of conversational demos, not their DIL mock code or example numbers. Use existing REvoCompute TS/DOM/CSS, i18n, design tokens and server schema.

## Acceptance
- [ ] Real AF3 schema: assert eight parameters appear, supported values are editable, defaults/omission are unchanged, and preflight/submission carry the explicit changed values into the actual task/Runner contract.
- [ ] Runtime/Runner scientific tests for feature vs model flags and stage precedence; validate no behavior drift.
- [ ] A synthetic Runner without declared parameter component still presents all canonical editable parameters; a specialized parameter plugin renders no duplicates.
- [ ] Seed component test: click dice changes one bounded seed (including edge bounds), Reset restores declared default, no reset if none; keyboard/label/aria and 280/320 px reflow.
- [ ] Run frontend typecheck/unit/build, Playwright canonical acceptance, and required Runner/server gates as appropriate.
- [ ] Remove TODO and temporary visual/test artifacts before final review. No merge without owner authorization.
