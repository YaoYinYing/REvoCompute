# Molecular Selection Capabilities Design Record

This page defines the reusable molecular-selection capabilities a workspace must
expose: the selection identity any molecular selection can express, a narrow
viewer facade, the path from a picked identity to the owning task's canonical
parameters, viewer file-format coverage, pre-submission refusal rules, and
selection provenance. It does not implement any capability, and it deliberately
does not define how a Task Type wires or consumes these capabilities: that
belongs to the pending Composable Execution Architecture.

Status: design record only. Nothing below is implemented.

## Not covered here

How a Task Type consumes these capabilities is deferred to the Composable
Execution Architecture. This record does not edit a task's `input_workspace:`,
does not add runner-owned `input_workspace_plugins`, and does not define a task's
parameter set, its generated configuration, or an end-to-end acceptance round
trip. Result-visualisation contracts tied to a runner's output shape are also out
of scope. The record introduces no new workflow abstraction, no parallel path and
no compatibility shim; the transition consumes these capabilities directly.

## Selection identity model

Any molecular selection must express: auth chain (not Mol*'s label chain), auth
residue number, insertion code, residue name, hetero flag, and, for atom mode,
atom name, altloc and serial.

Label identifiers are viewer-local and can differ from the author's PDB identity;
auth identity is what maps to the immutable source structure and to the owning
runner's parameter vocabulary. The workspace contract currently carries only
`{chain: label_asym_id, residue: label_seq_id}`, so ligand picks and blank-chain
structures cannot be expressed at all; widening it is prerequisite work, not
optional.

A selection names a residue, several residues whose centroid is the point, or a
ligand/cofactor. The picked identity and a camera-tracked origin marker are
visible in the viewer; coordinates, selection highlight, numeric form and
submission preview stay synchronized in both directions, including clear/reset
and mode switches — no stale and no silently ignored fields.

## Viewer facade

The viewer exposes select, focus and annotate and nothing more, so a caller
cannot reach into viewer internals.

## Selection-to-canonical-parameter path

A picked identity resolves to the owning task's typed parameter vocabulary, read
from the projected schema and never restated in frontend constants. A write
accessor is paired with the existing parameter read so a control edit re-places
the marker.

Manual XYZ is authoritative only where the runner does not itself resolve the
point; elsewhere the numeric form is a labelled preview of the runner's answer,
never an input the UI substitutes, and a difference is not a submission error.

Submission validates parameters before capability normalization runs, so a
parameter required without a default cannot be supplied by a picker that injects
it: normalization is not a validation bypass. The picker drives the canonical
controls through the shared context and records the raw selection through its own
value.

## Viewer file-format coverage

The viewer must preview every format the task accepts. The `.ent` gap is the
concrete case: a task accepts `pdb` and `ent` while the viewer previews only
`pdb`/`cif`/`mmcif`, so an accepted `.ent` silently loses the viewer.

## Refusal rules

Refuse before submission: mixed structures or frames, empty or ambiguous
selectors, missing residues, insertion-coded residues, unsupported altlocs,
blank-chain mismatches, and multi-model reference files.

## Provenance

Keep four facts separate: the raw selection, the centroid rule as the owning
runner defines it, the resolved point, and the runner's own origin and delta. The
workspace payload is provenance, not authority: the runner reads canonical
parameters, so acceptance asserts the submitted parameters as well as the stored
payload. The centroid rule is the runner's, not the UI's; the UI must not define
its own. The centroid and origin semantics were worked out in the PyMOL plugin
at `YaoYinYing/caver-pymol-plugin` commit `5322f22`; that is prior art, and
the owning runner remains the authority.
