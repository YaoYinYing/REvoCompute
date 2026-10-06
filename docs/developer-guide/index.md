# Developer Guide

This section is for people changing Core server behavior: architecture,
execution boundaries, extension contracts, and the test policy.

## Architecture and execution

- [Architecture](architecture.md) — ownership boundaries, plugin discovery, and
  the server stack.
- [Plugin Kernel](plugin-kernel.md) — manifest discovery, validation, and the
  typed registry.
- [Execution Model](execution-model.md) — from API request to Slurm/Apptainer
  execution and parsed outputs.

## Extension contracts

- [Result View Plugin Contract](result-view-plugins.md) — the server-owned
  scientific result composition boundary.
- [Result View Protocols (Design Record)](result-view-protocols.md) — the
  viewer protocol design and its completion record.
- [Scientific Result Inventory](result-inventory.md) — the living artifact and
  semantics audit.
- [Input and Result Workspace (Design Record)](input-result-workspace.md) — the
  pluggable input/result workspace design and its status.
- [Frontend Design Language](frontend-design-language.md) — the visual
  vocabulary (colour, surface, type, radius, shadow, control and status roles)
  that frontend changes are judged against.
- [Frontend Art Direction — Cared-for Precision](frontend-art-direction.md) —
  the material quality, artistic references, and authored character that sit
  above individual tokens.
- [Frontend Visual Ancestry](frontend-visual-ancestry.md) — the historical
  REvoDesign/REvoCompute screens and decisions worth preserving as evidence.
- [Frontend Taste Review](frontend-taste-review.md) — the practical composition
  and taste rubric used during rendered frontend review.
- [Authenticated Tool Runtime](tool-runtime.md) — typed, ephemeral Tool calls
  and their isolation model.

## Contributing

- [Testing and CI](testing.md) — what belongs in pytest and what does not.
- [Writing Documentation](documentation.md) — documentation ownership, page
  conventions, and the local build gate.
- [Goal: GMX-MMPBSA](gmx-mmpbsa.md) — the reference intake plan for a new
  family.
