# CodonTransformer model assets

The family consumes one immutable Hugging Face model snapshot at the stable
container path `/mnt/db/weights/revocompute/codontransformer/model`. It is a
read-only provisioned resource and is not downloaded during Tasks.

| Field | Value |
|---|---|
| Upstream project | `Adibvafa/CodonTransformer` |
| Code revision | `v1.6.7`, commit `895970e960cc8b558b9dd337e112411a543ba3f3` |
| Model repository | `adibvafa/CodonTransformer` on Hugging Face |
| Model revision | `9744dcc920d813066391fc828d7a590207f148e8` |
| Model license | Apache-2.0, as declared by the model card |
| Canonical local root | `/mnt/db/weights/revocompute/codontransformer/model` |
| Consumer | `codontransformer` Runner family |

The pinned code revision has a Poetry package-name/case mismatch that prevents
wheel construction. The SIF retains the immutable source checkout at
`/opt/CodonTransformer` on `PYTHONPATH` and removes its `.git` directory; no
source patch or editable install is used.

Required files and known upstream fingerprints:

| File | SHA-256 |
|---|---|
| `model.safetensors` | `23994e1e7324e78c9d9da71040e8677c0a635287cf1c7c9ea5096b7eadc44dfd` |
| `config.json` | `669ad8f2f97469569e67d43ce47049a5423d01e3c064d9426985035008ac49e7` |
| `tokenizer.json` | `ed67da0846097c8ea4425c4b84fb31c18cbfb52fde30813109a0d8d32a40217b` |
| `tokenizer_config.json` | `ca1eac71db28162f532126ada424f0e0a9c7bd8010e76dbceb4a4e29f89dc818` |
| `special_tokens_map.json` | `e4a7a265361e1a1cf7986b728af2b14a3816a9b25c5e06465fc048e703263e09` |
| `generation_config.json` | `b9b2aa8011a700847d8956b689b9fe4b2689d86e396830f0c3b139d1110a495a` |

The safetensors object is 358,342,232 bytes according to the upstream Git LFS
pointer. The exact snapshot was provisioned and fingerprinted on 2026-09-10;
all files are mode `0444` and no `.git` metadata is present. Acceptance must run
the real Transformers loader with `HF_HUB_OFFLINE=1` and
`TRANSFORMERS_OFFLINE=1` before promotion.
