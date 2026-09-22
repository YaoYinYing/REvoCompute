# DeepPocket checkpoint assets

DeepPocket ships two trained networks: a 3D CNN classifier that reranks fpocket
candidate pockets, and a U-Net that segments the shape of the top-ranked
pockets. Both checkpoints reach the Runner as read-only operator-provisioned
files beneath `/mnt/db/weights/deeppocket`, mounted at the identical container
path; neither is baked into the SIF.

The authors distribute their checkpoints inside a single archive linked from the
project README. Only the two files the inference path reads are provisioned:

| Relative path | Bytes | SHA-256 |
| --- | ---: | --- |
| `checkpoints/classification_models/first_model_fold1_best_test_auc_85001.pth.tar` | 7,996,987 | `d166c8a36b2475297193dbe31e5a88ff9b853e343281ef21df537029ba053f9a` |
| `checkpoints/segmentation_models/seg0_best_test_IOU_91.pth.tar` | 207,302,525 | `aa6d29beda70e79b39504c3bdaf5b42380e9c1e5bc6b0557cb81e9075243faee` |

Both were extracted from the published archive, whose own identity is recorded
in `upstream.json`. The digests above were computed locally with `sha256sum`
from the extracted files; the upstream project publishes no digest manifest.

## Why the rest of the archive is not provisioned

The archive also carries the remaining fold models, the segmented-model set used
for the paper's sweeps, and multi-gigabyte training datasets in
`.molcache2`/`.types` form. The pinned inference path reads exactly one
classifier checkpoint and one segmentation checkpoint, so only those two are
extracted. Training and benchmark reproduction are out of scope for this Runner.

## Provisioning

```sh
install -d -m 755 /mnt/db/weights/deeppocket \
  /mnt/db/weights/deeppocket/checkpoints/classification_models \
  /mnt/db/weights/deeppocket/checkpoints/segmentation_models
install -m 444 <extracted classifier> \
  /mnt/db/weights/deeppocket/checkpoints/classification_models/first_model_fold1_best_test_auc_85001.pth.tar
install -m 444 <extracted segmentation model> \
  /mnt/db/weights/deeppocket/checkpoints/segmentation_models/seg0_best_test_IOU_91.pth.tar
```

The original archive is kept unmodified beside the extracted tree. A missing or
altered checkpoint fails the Task before any GPU work starts, with
"DeepPocket asset is missing" or "DeepPocket asset integrity verification
failed".

## fpocket

fpocket is DeepPocket's own candidate-generation step rather than a separately
chained REvoCompute Task. It is compiled from the pinned revision directly into
the image and needs no provisioned assets.
