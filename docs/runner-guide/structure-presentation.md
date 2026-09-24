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

## Presentation is two axes, not one list

The viewer exposes representation and colour as separate choices. A
representation preset changes *what the model is drawn as*; a colour preset
leaves the representation alone and restyles it. Selecting a representation
keeps the active colour, because Mol* resets a representation's colour theme to
`element-symbol` whenever the representation layer is replaced — the shell
re-applies the current colour as part of the same change.

Both axes name identifiers from Mol*'s own registries rather than a private
vocabulary: `cartoon`, `ball-and-stick`, and `molecular-surface` are
representation types, and `chain-id`, `sequence-id`, and `plddt-confidence` are
colour themes. The one composed preset, `cartoon_ligand`, is Mol*'s
`polymer-and-ligand` composition (polymer cartoon + ligand ball-and-stick +
carbohydrate symbols).

A Runner does **not** declare this vocabulary: it is a fixed presentation
capability of the viewer, and the `Confidence` colour remains gated on the
`confidence_encoding` mapping above. A structure that cannot be drawn in a
requested representation simply keeps its current one; presentation never turns
a successful structure load into a failed one.

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
