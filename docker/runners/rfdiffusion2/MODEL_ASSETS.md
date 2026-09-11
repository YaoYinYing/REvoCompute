# RFdiffusion2 model assets

RFdiffusion2 uses one externally provisioned, read-only checkpoint. The SIF contains no model weights and runtime network access is disabled.

| Container path | Official source | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| `/mnt/db/weights/revocompute/rfdiffusion2/RFD_173.pt` | `https://files.ipd.uw.edu/pub/rfdiffusion2/model_weights/RFD_173.pt` | 1,338,843,322 | Recorded in `model-assets.sha256` |

The pinned upstream `setup.py` lists the URL and filename but does not publish an MD5 or SHA-256 digest. The digest in this family is computed from a complete download from the official IPD endpoint and must be verified before every run. The server must mount only `/mnt/db/weights/revocompute/rfdiffusion2` at the identical container path in read-only mode.

The pinned repository is BSD-3-Clause. It does not contain a separate checkpoint license or model-use notice, so deployment operators must confirm that the repository license covers their intended checkpoint use.
