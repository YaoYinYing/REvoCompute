# Architecture Invariants

These invariants hold across every runner family and every deployment. A change
that violates one is a defect even when its tests pass.

## Single source of truth

- The server is the source of truth for task definitions, schemas, extensions,
  resource policies, and scientific constants. Do not duplicate server-owned
  YAML or Python configuration in JavaScript.
- Each owning `task.yaml` is the sole authority for user-facing Task parameter
  vocabulary and semantics. Project it through server APIs and resolved Runner
  inputs; never restate defaults or parameter help in Core, frontend code,
  `runner.yaml`, adapters, or Markdown.
- There is no hand-maintained central task registry. Discovery scans
  family-owned `plugin.yaml` manifests and validates their declared TaskTypes
  and extensions.

## Generic lifecycle, family-owned science

- Core owns the generic plugin, task, execution, resource, artifact, and
  readiness grammar. Runner families own their TaskTypes, scientific
  vocabulary, constants, runtime contract, parsers, and result semantics.
- Generic server code must not branch on runner or task names. A new family
  with new scientific vocabulary must not require Core to know its IDs.
- Adding a capability should leave an end-to-end product that can be exercised
  before more complexity is added.

## Input contracts

- Task inputs are named roles, not positional files. Never assign scientific
  meaning from upload order, filenames, or extensions alone, and do not add
  flat `primary_input_extensions`-style contracts.
- Keep transport safety, format parsing, logical role validation, neutral
  normalization, and Runner scientific preparation separate. Generic Server
  validation must not silently protonate, assign charges, atom-type, minimize,
  or otherwise alter scientific interpretation.
- Preserve original user inputs and hashes as an immutable role-resolved
  snapshot. Runner-prepared files and preparation logs are separate provenance
  artifacts and must never replace originals.

## Readiness and admission

- Readiness is derived from evidence (Doctor, current SIF, live receipt), never
  stored as a mutable flag an operator can set.
- Admission checks current readiness before durable side effects. Access
  entitlement and transient scheduler capacity are separate decisions.
- `enabled != READY`. A non-READY family fails closed before durable task,
  upload, queue, or Slurm side effects.

## Simplicity

- Keep implementations simple, end-to-end, and modular. Remove obsolete paths
  rather than adding compatibility layers or speculative abstractions.
- Prefer established, maintained libraries and existing project dependencies.
  Never vendor third-party frontend libraries.
- Do not introduce a known stopgap that is intended to be replaced later.
