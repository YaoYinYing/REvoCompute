# Implementation State — Molecular Selection

Status: M1 in progress. Base `6d726f54`.

## Completed

- Successor scope restored from #128 and #130's preserved requirements.
- Confirmed `MolecularViewer` already exposes auth residue identity and insertion code to listeners.

## Next action

- Widen `structureSelections` / workspace normalization to the authored identity and add refusal tests.

## Blockers

- Browser acceptance needs the local example stack; CAVER scientific roundtrip needs an authorized runner
  receipt.
