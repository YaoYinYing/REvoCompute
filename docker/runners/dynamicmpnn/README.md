# dynamicMPNN Runner family

This dedicated CPU family pins `TCoulth/dynamicMPNN` commit
`af351ee737bdb2ca2804a308d9abc8fd7c303270` (MIT). Although its Torch stack is
compatible with the established MPNN family, it has a separate family boundary
so its exact live-test receipt can be admitted without changing readiness for
established MPNN TaskTypes.

The pinned upstream `get_model_params.sh` downloads the original ProteinMPNN
`proteinmpnn_v_48_020.pt` checkpoint. The runner therefore reuses the existing
read-only `/mnt/db/weights/ligandmpnn/` resource instead of keeping a duplicate
dynamicMPNN copy. Runtime downloads are disabled.
