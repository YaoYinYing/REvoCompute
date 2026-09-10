# Protenix-v2 Model Assets

The `protenix` family uses the upstream `v2.0.0` release at commit
`2475421477ab414b571149ad4a875c390ff8a35d`. Protenix code and released model
parameters are Apache-2.0 licensed.

Provision the following immutable files beneath
`/mnt/db/weights/revocompute/protenix/` from the official upstream URLs:

| Relative path | Official source | Role |
| --- | --- | --- |
| `checkpoint/protenix-v2.pt` | `https://protenix.tos-cn-beijing.volces.com/checkpoint/protenix-v2.pt` | Protenix-v2 model checkpoint |
| `common/components.cif` | `https://protenix.tos-cn-beijing.volces.com/common/components.cif` | PDB Chemical Component Dictionary snapshot |
| `common/components.cif.rdkit_mol.pkl` | `https://protenix.tos-cn-beijing.volces.com/common/components.cif.rdkit_mol.pkl` | Upstream RDKit CCD cache |
| `common/clusters-by-entity-40.txt` | `https://protenix.tos-cn-beijing.volces.com/common/clusters-by-entity-40.txt` | Entity clustering metadata required by inference setup |
| `common/obsolete_release_date.csv` | `https://protenix.tos-cn-beijing.volces.com/common/obsolete_release_date.csv` | Obsolete-component release metadata |
| `common/obsolete_to_successor.json` | `https://protenix.tos-cn-beijing.volces.com/common/obsolete_to_successor.json` | Template metadata, required only when templates are enabled |
| `common/release_date_cache.json` | `https://protenix.tos-cn-beijing.volces.com/common/release_date_cache.json` | Template release dates, required only when templates are enabled |

Upstream does not publish a checksum manifest for these objects. Provisioning
must therefore compute SHA-256 and byte size after downloading each official
object, then record them in `assets.json` with this shape:

```json
{
  "upstream_commit": "2475421477ab414b571149ad4a875c390ff8a35d",
  "model_name": "protenix-v2",
  "files": {
    "checkpoint/protenix-v2.pt": {
      "source_url": "https://protenix.tos-cn-beijing.volces.com/checkpoint/protenix-v2.pt",
      "size": 0,
      "sha256": "replace-with-64-lowercase-hex-digits"
    }
  }
}
```

The runtime checks every required file against this manifest before importing
Protenix. The family root is mounted read-only and no files are copied into the
SIF or per-task workspace.

Protein MSA, RNA MSA, and template-search databases are not model weights and
are deliberately absent from this family. This TaskType consumes only uploaded,
precomputed `.a3m`/`.hhr` results. A future search TaskType should declare an
independently versioned, read-only database mount rather than add those databases
to this weight namespace. Runtime network searches and upstream auto-downloads
are disabled.
