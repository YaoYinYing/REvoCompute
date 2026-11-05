# RFD4 Proteina

Pinned source: `RosettaCommons/RFD4-Proteina` at `68058693cb88762a8aaf806571e13b291ce6318a` (BSD-3-Clause). The bounded Task uses the pinned Hydra CLI (`rfd4-generate inputs=... out_dir=... num_replicates=... seed=... generation.args.nsteps=...`) with a native YAML/JSON condition specification plus scaffold, or a native annotated CIF. It publishes the upstream annotated CIF designs under `inference_samples/` and selects no inline metrics. Condition satisfaction is computational; it does not establish biochemical activity, binding, or function. The Task requires a GPU (`gpus: true`) because the pinned model runs on an accelerator.

## ASSET_BLOCKED

No model bundle is installed at `/mnt/db/weights/rfd4-proteina/`. The upstream TODO records a Hugging Face bundle of approximately 1.7 GB including the autoencoder. Required individual paths and SHA256 values have not yet been obtained from the immutable revision and are deliberately unspecified rather than invented. Provision the complete licensed bundle read-only at the mount path, record every file's SHA256 and provenance, then validate model loading and output semantics against the pinned upstream. Runtime downloads are disabled.

A target-host scientific smoke test and readiness receipt are pending. This family is not READY.
