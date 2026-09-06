# Deployment

# Deployment Control

Deployment is a staged lifecycle: prepare the server and direct Apptainer
images, run Doctor and target-host live acceptance, then promote only candidates
with an exact receipt. `run/restart.sh` is the operator entry point.

Use `prepare` for materialization and SIF builds, `live-test` for a real SLURM
and Apptainer smoke run, and `restart --mode=prepared` for atomic promotion.
Maintenance mode protects NEW submissions during transitions; existing and
running tasks are allowed to finish. A failed build or missing receipt must be
fixed in the owning Runner Family before promotion.

The CI MkDocs build proves documentation links and syntax. It does not replace
target-host Doctor, live acceptance, or production admission checks.
