# BioEmu2 model assets

The BioEmu2 Runner is pinned to upstream `0.1.0rc0`, commit
`6d1ca744fa8ed285edafae7b98da65205bf00fd3`. The host resource root
`/mnt/db/weights/bioemu2` is mounted read-only at the identical container path.

Inference requires these immutable files:

| File | SHA-256 | Role |
| --- | --- | --- |
| `checkpoints/bioemu2-preview/checkpoint.ckpt` | `3b4ba9236b7b458f47b40b694847b6bb4110c744becd6d2c53de7b1d04c07a81` | Preview checkpoint |
| `checkpoints/bioemu2-preview/config.yaml` | `90326e3b77e524420f5aad68a777355ecbbbe07bc006ddf88f7ee921b0f772e3` | Model configuration |

The Runner verifies both against `model-assets.sha256` before dispatching the
task.

## Ligand steering dictionary

Propagation is the only BioEmu2 task that uses ligand steering. It requires the
pinned Boltz-1 CCD dictionary under the same read-only mount:

- Path: `/mnt/db/weights/bioemu2/steering/boltz-1-ccd.pkl`
- SHA-256: `2d3b2f03a3c5665944adba51e33263511e51b21c9cd05d902f9c4b7c1e58d2f4`
- Source: <https://huggingface.co/boltz-community/boltz-1/blob/main/ccd.pkl>

Provision it with the exact filename above. The default path is resolved
relative to the asset root; `BIOEMU2_STEERING_CCD` can point elsewhere.
`run.sh` checks the dictionary against `steering-ccd.sha256` before propagation
and fails closed when it is missing or altered. Equilibrium and structure
prediction never read the dictionary and do not require it.

Verify an installed copy with:

```bash
sha256sum /mnt/db/weights/bioemu2/steering/boltz-1-ccd.pkl
```

This dictionary omits some newer components, including the predicted ligand
`A1L3H`. A ligand absent from it is sampled without ligand-specific steering
constraints; the rest of the system and the physicality check are unchanged.
