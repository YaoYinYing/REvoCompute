# fpocket: integration scope and evidence

fpocket is a third-party C program. REvoCompute **runs** it; it does not
reimplement its pocket-detection or druggability mathematics. This document
records what REvoCompute is therefore responsible for, and what it deliberately
does not claim.

## What REvoCompute owns

| Responsibility | Where it is exercised |
| --- | --- |
| Correct invocation of the pinned upstream binary | `run.sh` + `detect.py` (`tests/runners/fpocket`) |
| Clear failure on a non-zero exit or missing/malformed output | `run.sh` guards, `normalize_results.py` errors, `tests/runners/fpocket/test_fpocket_results.py` |
| Parsing the raw output into the declared table | `normalize_results.py` + its fixture tests |
| A valid ResultManifest and a useful result presentation | `expected_files.yaml`, `tasks/fpocket/task.yaml` views, `storyboard/` |

## Pinned upstream identity

- Repository `https://github.com/Discngine/fpocket`, revision
  `4bb0d8447f62fee77e2c3c29f54b5fcaf5e2c066` (tag `4.2.3`), MIT.
  Recorded in `upstream.json`; `detect.py` writes the same revision into
  `fpocket-run.json` so every result carries the pin.
- Method publications: `10.1186/1471-2105-10-168` (fpocket) and
  `10.1021/jm100574m` (druggability). Both are declared in
  `tasks/fpocket/task.yaml` and surfaced as citations.
- Every Task parameter maps to one upstream CLI flag: `-m`, `-M`, `-i`, `-D`,
  `-v` (see `detect.py`). The parameter vocabulary is owned by
  `tasks/fpocket/task.yaml`; `detect.py` only resolves it.

## What is NOT claimed

REvoCompute does not assert that fpocket's pocket predictions are
scientifically or numerically correct. The pocket score, druggability score,
volume, SASA, centre, and the residue/hetero contact sets are **values reported
by fpocket** for the submitted structure. No threshold is applied to the
druggability score, and a detected pocket is a candidate site, not a confirmed
binding site. Upstream's own publications are the authority for the meaning and
calibration of those numbers.

## Bounded raw parser fixture

`docker/runners/fpocket/tests/fast/fixtures/1SUO_out/` is a *bounded* slice of a real fpocket run on
PDB `1SUO`, kept so the normalizer's parsing is exercised against real upstream
output rather than a hand-written imitation:

- `1SUO_info.txt` — the global descriptor file fpocket writes, one block per
  reported pocket (all 40 here). Used to test descriptor parsing, the pocket
  count, and the ranking order.
- `pockets/pocket1_{vert.pqr,atm.pdb}` and `pockets/pocket2_{vert.pqr,atm.pdb}`
  — the per-pocket alpha-sphere centres and contacted atoms for two pockets.

The two pockets are kept because they exercise different parser branches:
`pocket1` contacts a non-polymer (hetero) residue (`HEM`), `pocket2` contacts
only polymer residues. The other 38 pockets' per-pocket files are omitted as
fixture bulk — their descriptors are fully carried by `1SUO_info.txt`. Full-tree
byte identity is deliberately not claimed.

These files are parser/adapter fixtures. They are not a frozen numerical golden
and are not a statement about which pockets are "real".

## Real-Runner evidence

`tests/data/fpocket/live/pockets.csv` is the normalized pocket table a real
production run published (task `b546f034ffc7fafac871f21176a03c91` on
lab309-westlake, via API → Server → Slurm → Apptainer → fpocket →
`normalize_results.py` → ResultManifest). It is reused as authentic result data
for the ranked-table and storyboard presentation, not as scientific truth.
