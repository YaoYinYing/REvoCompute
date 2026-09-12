# SimpleFold model resources

SimpleFold is pinned to Apple `ml-simplefold` revision
`c7a5570a6be9f5c695126e27c804e77567209934` (package version `0.1.0`).
The code is MIT licensed. The released model checkpoints are governed by the
Apple Machine Learning Research Model License Agreement and are restricted to
research purposes. The upstream repository does not assign a separate semantic
version to the checkpoint set, so the immutable download URL, byte size, and
SHA-256 fingerprint identify each provisioned revision.

## SimpleFold checkpoints

The authoritative host root is `/mnt/db/weights/simplefold`, mounted read-only
at the same container path.

| File | Bytes | SHA-256 | Authoritative source |
| --- | ---: | --- | --- |
| `simplefold_1.6B.ckpt` | 6,354,525,226 | `aaac2d73dcc59c61153c58a1d56e74a8ada9d6057d67000f7836f3c87325312b` | `https://ml-site.cdn-apple.com/models/simplefold/simplefold_1.6B.ckpt` |
| `simplefold_3B.ckpt` | 11,460,066,894 | `88d4c7a240bf3815cb35342b4ddc1128ac243a2ea0256eb8a4df1209125868b5` | `https://ml-site.cdn-apple.com/models/simplefold/simplefold_3B.ckpt` |
| `plddt.ckpt` | 462,812,900 | `cb32fa9cdc9e80406b793a8c09a929077534d9991a1d08f4c159d2e4ed81315f` | Renamed local copy of `https://ml-site.cdn-apple.com/models/simplefold/plddt_module_1.6B.ckpt` |
| `plddt_module_1.6B.ckpt` | 462,812,900 | `cb32fa9cdc9e80406b793a8c09a929077534d9991a1d08f4c159d2e4ed81315f` | `https://ml-site.cdn-apple.com/models/simplefold/plddt_module_1.6B.ckpt` |

The two pLDDT files are byte-identical. The pinned upstream loader expects the
short name `plddt.ckpt`; the longer duplicate is inventoried but not required by
the Runner. pLDDT inference also loads `simplefold_1.6B.ckpt` as its latent
feature model, even when the selected folding model is 3B.

## Boltz CCD dependency

SimpleFold incorporates Boltz-derived FASTA parsing and atom featurization. It
requires only `/mnt/db/boltz/ccd.pkl` from the shared Boltz resource root:

| File | Bytes | SHA-256 | Authoritative source |
| --- | ---: | --- | --- |
| `ccd.pkl` | 345,859,128 | `2d3b2f03a3c5665944adba51e33263511e51b21c9cd05d902f9c4b7c1e58d2f4` | `https://huggingface.co/boltz-community/boltz-1/resolve/main/ccd.pkl` |

The upstream download helper also fetches `boltz1_conf.ckpt`, but SimpleFold's
inference path never consumes that checkpoint. The REvoCompute adapter bypasses
the overbroad helper and routes parsing directly to the provisioned CCD, so it
does not copy or require unused Boltz model weights.

## ESM-2 dependency

SimpleFold always uses ESM-2 3B sequence representations. The Runner mounts the
existing `/mnt/db/weights/esm` root read-only and resolves the two required files
through a task-local `TORCH_HOME`; the pinned ESM source revision
`2b369911bb5b4b0dda914521b9475cad1656b2ac` is code inside the SIF.

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `checkpoints/esm2_t36_3B_UR50D.pt` | 5,678,116,398 | `7de8b4082ba15891959ab368b77ce3886697af1efb16d3c9e9e7b0c5d3f07500` |
| `checkpoints/esm2_t36_3B_UR50D-contact-regression.pt` | 6,759 | `4da500eab246481dc9c8c95bc7b1d02f2803d761c380b0e95186d4a07d0fc84e` |

Normal task execution clears proxy variables and enables framework offline
modes. Missing files fail preflight; no runtime download is permitted.
