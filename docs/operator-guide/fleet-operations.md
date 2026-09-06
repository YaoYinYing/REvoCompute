# Fleet Operations

Treat the enabled fleet as one inventory with independently validated family
artifacts. Start each shift by inspecting all families and recording any
non-READY state:

```bash
REVODESIGN_SERVER_ENV=.env.production bash run/restart.sh runner-status --all
```

For a family that is `NOT_BUILT` or `BUILD_STALE`, prepare a candidate. For
`NOT_VALIDATED` or `VALIDATION_STALE`, run its required collection on the target
cluster. Compare the receipt's hashes and policy digest before promotion.

Do not enable a task merely because its family is configured: `enabled !=
READY`. Restricted families also require an access-policy entitlement. Review
disk space, SIF ownership, Slurm partitions, database mounts, and receipt age
before a prepared restart. Keep maintenance mode active when any enabled
family cannot satisfy the production contract, and report the exact state and
failed evidence.
