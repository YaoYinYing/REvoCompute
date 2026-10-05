# Fpocket Runner Integration and Result Storyboard

## Objective

Deliver **fpocket** as a production-ready Runner Integration with a
structure-aware interactive **result storyboard**.

fpocket is a third-party C program. REvoCompute is responsible for invoking it
correctly, detecting execution failure, parsing its outputs correctly,
publishing a valid result contract, and presenting the result usefully. It is
**not** responsible for proving fpocket's pocket predictions are scientifically
or numerically correct -- that is upstream's responsibility. (This is the
opposite of GREMLIN_LH, which reimplements the method and therefore owns
upstream equivalence.)

## 1. Correct invocation

- `detect.py` runs the pinned binary with the declared parameters; each Task
  parameter maps to exactly one documented upstream flag (`-m -M -i -D -v`).
- Upstream version/revision and the parameter vocabulary stay pinned
  (`upstream.json`, `tasks/fpocket/task.yaml`).
- Covered by `tests/server/test_fpocket_result_views.py` (flag mapping) and the
  integration tests.

## 2. Correct failure handling

The normalizer fails clearly on a missing info file, a non-contiguous block, a
pocket missing its vertex/atom file, an empty vertex file, or missing
descriptors; `run.sh` fails on a non-zero exit or an absent output tree. Covered
by the failure cases in `tests/runners/fpocket/test_fpocket_integration.py`.

## 3. Correct parsing and the bounded fixture

`tests/data/fpocket/1SUO_out/` is a bounded slice of a real 1SUO run: the global
descriptor file (all 40 pockets) plus the per-pocket geometry/contact files for
`pocket1` (contacts HEM, a non-polymer residue) and `pocket2` (polymer-only
contacts) -- the two branches the parser must handle. The other per-pocket files
are omitted as fixture bulk. `tests/data/fpocket/live/pockets.csv` is the
normalized table a real production run published, reused as authentic result
data. See `docker/runners/fpocket/INTEGRATION.md`.

## 4. Result contract

`tasks/fpocket/task.yaml` declares a generic primary `entity-table`, a
`scalar-summary`, and an `evidence-bundle`; `docker/runners/fpocket/
expected_files.yaml` gives durable logical identities to fpocket's own output.
No runner-name branches; raw artifacts stay downloadable.

## 5. Storyboard (primary interpretation)

`docker/runners/fpocket/storyboard/` composes the structure-aware pocket result:
a compact ranked selector -> selected pocket descriptors, contacted residues,
structure focus, and the pocket geometry files. It binds only to logical file
identities and uses the shared `context.selection` /
`context.services.openFile|openView|focusStructure|selectStructure`. Covered by
`tests/test_playwright_fpocket_storyboard.py`.

## 6. What was removed (subtraction)

The earlier scientific-equivalence machinery (a frozen numerical golden over all
40 pockets, the independent reference extractor, the Monte-Carlo tolerance
framework, `SCIENTIFIC_REFERENCE.md`) was deleted: it asserted fpocket's
correctness rather than REvoCompute's integration.

## 7. Real-Runner evidence

`tests/data/fpocket/live/pockets.csv` is the 40-pocket table published by a real
production run (task `b546f034ffc7fafac871f21176a03c91`: API -> Server -> Slurm
-> Apptainer -> fpocket -> normalize -> ResultManifest -> artifacts). It is
evidence the path works and authentic data for the presentation, not biological
truth. No new run is required for this presentation/declaration change.

## 8. Gates

`tests/runners/fpocket`, `tests/server/test_fpocket_result_views.py`,
`tests/test_playwright_fpocket_storyboard.py`,
`tests/test_playwright_fpocket_result_acceptance.py`, `tests/runners` +
`tests/server`, `git diff --check`.
