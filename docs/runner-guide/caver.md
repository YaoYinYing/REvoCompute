# CAVER Tunnels

`docker/runners/<family>/` is the CAVER 3.0.2 tunnel-analysis family. Its
`tasks/caver/task.yaml` is the sole authoritative source for start-point modes,
parameters, accepted formats, and user-facing help; the pinned distribution and
JAR digests live in the family's `upstream.json`. This page records the
cross-cutting behavior and acceptance evidence that a maintainer cannot read
from those declarations.

## Start-point ownership

CAVER explores tunnels from one point inside the structure. The Task declares
`point`, `atom`, `residue`, `ligand`, and `group` modes and their conditional
fields; the Runner resolves the authored identity against the submitted PDB
instead of trusting the client.

- `point` carries explicit Angstrom XYZ. The selected source distinguishes a
  typed point, a viewer crosshair, and an explicit centroid or centre-of-mass
  conversion; the last two also require the selected residues, atom serials, and
  reference digest.
- An explicit `centroid` is the arithmetic mean of the recorded atoms, and the
  Runner recomputes it within 0.01 Angstrom. An explicit `com` is the client's
  declared mass-weighted method with its hydrogen policy; the Runner records
  that method and does not recompute it.
- Neither conversion renames CAVER's own residue or group centre. Native
  `atom`, `residue`, `ligand`, and `group` selections keep CAVER's directives.
- An insertion code, an ambiguous alternate location, a chainless residue beside
  named chains, or a serial outside the retained atom set is refused rather than
  guessed.
- A `start_selected_serials` range or list longer than the structure's atom
  count is refused before expansion, so a schema-valid huge range cannot
  exhaust the worker.

The generated config, immutable input snapshot, published provenance, and
`data/origins.pdb` must identify the same point. The picker design is in
[Input and Result Workspace](../developer-guide/input-result-workspace.md#typed-start-point-selection).

## Include and exclude directives

The pinned CAVER 3.0.2 build accepts `include_residue_ids`,
`include_residue_names`, `include_atom_numbers`, and the corresponding
`exclude_*` directives, and accepts all six together in one config. The upstream
guide states that includes select the atom set first, excludes then remove from
it, and file order does not matter. The observed run below is an acceptance
check, not a formal precedence proof.

Because both families exist in the pinned executable, the Task offers both and
validates every include token against the reference structure exactly as it
validates exclusions. Residue names come from the loaded structure; the upstream
`20_AA` alias is not offered because it names no residue in the file.

## Acceptance evidence

The filter-directive evidence comes from the pinned distribution, its shipped
user guide, and an observed run of the pinned JAR with all six directives on
`tests/data/3fap_hf3_A_short.pdb` (exit 0). The run used **host JDK 17 and the
same JAR bytes the SIF pins, not the SIF's JRE 8**. A SIF/JRE-8 reproduction is
an external heavy-window item and is not claimed.

## Scope boundaries

The family does not replace the CAVER engine, add a second generic structure
viewer, or ingest MD trajectories. #156 provides topology and trajectory input
as ordered CAVER-compatible PDB snapshots in a separate change with its own
scientific proof.
