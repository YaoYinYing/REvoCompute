# ESMFold 2 model assets

The family mounts `/mnt/db/weights/revocompute/esmfold2` read-only. Runtime inference is offline and requires this layout:

```text
esmfold2/
|-- assets.json
|-- ccd.pkl
|-- fast/
|   |-- config.json
|   `-- model.safetensors
|-- standard/
|   |-- config.json
|   `-- model.safetensors
`-- esmc-6b/
    |-- config.json
    |-- model.safetensors.index.json
    `-- model-00001-of-00006.safetensors ... model-00006-of-00006.safetensors
```

Provision snapshots only from the official Hugging Face repositories at the immutable revisions recorded in `predict.py`, `upstream.json`, and `assets.json`. The manifest's `files` object maps each relative path to its exact `size` and `sha256`; the runner verifies every consumed file before model loading. The ESMFold 2 head, CCD data, and ESMC-6B backbone are MIT-licensed upstream assets. Do not copy them into the SIF or a task workspace.

ESM v3.4.2 defaults the ESMC-6B backbone to fp8. This Runner deliberately loads it in bf16, the precision the provisioned weights were validated with, and records `esmc_precision: bf16` with every prediction. The provisioned weight files and revisions are unchanged.
