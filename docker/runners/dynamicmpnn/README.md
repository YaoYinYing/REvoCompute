# dynamicMPNN Runner family

This dedicated CPU family pins `TCoulth/dynamicMPNN` commit
`af351ee737bdb2ca2804a308d9abc8fd7c303270` (MIT). Although its Torch stack is
compatible with the established MPNN family, it has a separate family boundary
so its external checkpoint and exact live-test receipt can be admitted without
changing readiness for established MPNN TaskTypes.

Provision `proteinmpnn_v_48_020.pt` beneath
`/mnt/db/weights/revocompute/dynamicmpnn/model_params/` and record its SHA-256
before building and live testing. Runtime downloads are disabled.
