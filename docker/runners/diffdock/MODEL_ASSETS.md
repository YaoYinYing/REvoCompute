# DiffDock Model Assets

Provision the official DiffDock-L v1.1 model archive outside the SIF at
`/mnt/db/weights/revocompute/diffdock`:

```text
https://github.com/gcorso/DiffDock/releases/download/v1.1/diffdock_models.zip
archive sha256: 5a95b6a1555be47ab1d6f0a8ffd25152f7fe32f5956005bb821e13e7a37d4a3d
```

Extract the archive so `score_model/` and `confidence_model/` are immediate
children of that directory. `model-assets.sha256` records every runtime file.
The wrapper verifies those hashes before inference and copies the manifest into
the result evidence. The upstream repository releases code and model weights
under the MIT license.

DiffDock also uses the existing read-only ESM cache at `/mnt/db/weights/esm` to
embed the residue sequence parsed from the supplied PDB. This does not predict
or alter the protein structure. `esm-assets.sha256` pins the ESM2-650M model and
contact-regression checkpoint already shared with other Runner families.
