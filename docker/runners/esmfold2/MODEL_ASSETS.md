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

Provision snapshots only from the official Hugging Face repositories at the immutable revisions recorded in `predict.py` and `assets.json`. The manifest's `files` object maps each relative path to its exact `size` and `sha256`; the runner verifies every consumed file before model loading. The ESMFold 2 head, CCD data, and ESMC-6B backbone are MIT-licensed upstream assets. Do not copy them into the SIF or a task workspace.
