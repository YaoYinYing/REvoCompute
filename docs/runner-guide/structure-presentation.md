# Structure Presentation Contract

Structure artifacts are presented by one persistent browser viewer with a small
fixed vocabulary. A Runner declares what its files mean; the client never guesses
from a filename or extension.

## Confidence colouring is declared, never inferred

The viewer offers its `Confidence` colouring only when the server publishes
`confidence_encoding: plddt_bfactor` on that structure artifact. The value comes
from the owning view's `mapping` in `task.yaml`:

```yaml
result_workspace:
  views:
  - plugin: candidate-collection
    id: ranked_models
    role: primary
    sources:
      candidates:
      - glob: '*/ranked_*.pdb'
        required: true
    mapping:
      confidence_encoding: plddt_bfactor
```

Declare `plddt_bfactor` **only** when the structure's B-factor column really
carries per-residue pLDDT on the 0–100 scale. A prediction tool that writes
occupancy, a norm, or an arbitrary score into the B-factor column must not
declare it; the viewer would then present a scientifically wrong colouring.
Omitting the mapping is always correct and simply hides `Confidence`.

`plddt_bfactor` is currently the only accepted encoding. CIF and PDB both carry
B-factors, so nothing about the extension grants or forbids confidence colouring:
a plain CIF without the mapping is never labelled pLDDT, and a PDB with it is.

## Result formats

Prefer structured, machine-readable artifacts — `summary.json`, CSV/TSV, JSON,
PNG/SVG, PDF, and PDB/CIF/SDF — over standalone HTML reports. HTML artifacts are
published as downloads only and are never embedded as an active result
application; see [Results](../user-guide/results.md). Register the presentation
for each artifact through the owning view, not through a filename heuristic.

## Related pages

- [Task Contract](task-contract.md) — the manifest shape these mappings live in.
- [Result View Plugin Contract](../developer-guide/result-view-plugins.md) — the
  server-owned view boundary and lifecycle.
