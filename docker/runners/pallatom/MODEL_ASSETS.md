# Pallatom model assets

This family pins the official `levinthal/Pallatom` repository at commit
`b27d70054dec6ce2f5ceadf8977de3d3baf00663` (2025-06-03). Upstream stores its
released model parameters directly in Git. REvoCompute deliberately removes the
bundled `params/` directory while building the SIF and provisions the checkpoint
as an immutable, read-only deployment resource instead.

Canonical runtime layout:

```text
/mnt/db/weights/revocompute/pallatom/
└── params/
    └── params_Pallatom.npz
```

| Field | Value |
| --- | --- |
| Model | Pallatom |
| Source repository | `https://github.com/levinthal/Pallatom` |
| Source commit | `b27d70054dec6ce2f5ceadf8977de3d3baf00663` |
| Source path | `params/params_Pallatom.npz` |
| Expected bytes | `71,002,706` |
| SHA-256 | `57dff1c37cb1d99984ab664a7dc96e2a44afb100ea6f1f3c397dbe838124bc2f` |
| Local path | `/mnt/db/weights/revocompute/pallatom/params/params_Pallatom.npz` |
| Consumer | `pallatom` Runner family |

Normal Tasks are offline. The adapter verifies the full checkpoint checksum
before loading it and writes that identity into `generation_metadata.json`.

Both the upstream source and released parameters are distributed under
[CC BY-NC-SA 4.0](https://github.com/levinthal/Pallatom/blob/b27d70054dec6ce2f5ceadf8977de3d3baf00663/LICENSE).
The non-commercial and ShareAlike terms apply; deployments must grant the
`pallatom_noncommercial` entitlement only after reviewing the intended use.

Citation: Qu et al., *P(all-atom) Is Unlocking New Path For Protein Design*,
bioRxiv (2024), doi:10.1101/2024.08.16.608235.
