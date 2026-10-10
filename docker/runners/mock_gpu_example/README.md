# Mock GPU Example Runner (test/reference only)

This CPU-only family is a **test/reference artifact**. It exists so the
persistent multi-input lifecycle, the bounded adaptive-OOM recovery ladder, and
the per-attempt recovery provenance can be exercised **end to end without a
GPU and without a production SIF**. It is not science.

It has the *shape* of a folding Runner, so the real shared machinery runs
unmodified:

- `initialize_runtime` loads a runtime once per task (here: a configurable
  pseudo-device and a deterministic pseudo-model);
- one FASTA record is one work item;
- `run_item` fabricates a memory demand that grows with sequence length and with
  the number of samples drawn *concurrently* (the grouping), and returns a real
  OOM outcome when that demand exceeds the pseudo-device;
- on that OOM the **real** `common/runtime/persistent_runner.py` walks the
  declared, bounded fallback ladder — dropping no-op plans and refusing any plan
  that names a scientific parameter.

The pseudo-model is deterministic, which is what makes it a comparator: the
artifact bytes depend only on the **effective scientific parameters**
(`num_samples`, `seed`, the resolved `kernel_backend`, and the sample grouping).
A resource-only recovery never reaches them; a backend or grouping recovery
does, and is reported as such.

## Evidence layers

| Layer | Artifact | Proves | GPU/SIF |
| --- | --- | --- | --- |
| 1. Mechanism | this family + `docker/runners/mock_gpu_example/tests/fast/` | persistent lifecycle, recovery ladder, provenance, resume, projection | none |
| 2. Model science | real ESMFold2 / SimpleFold runtime | model-specific scientific equivalence | GPU |
| 3. Deployment | production SIF + Slurm live test | packaging / integration | GPU + SIF |

Layer 1 is complete in-repo and runs in CI. It never substitutes for layers 2
and 3: a real Runner that cannot execute on the available accelerator records a
concrete, measured infeasibility instead.

## Configuration

The pseudo-device is set by the caller through the environment, so one test can
choose the VRAM envelope that makes a chosen recovery path walk:

| Variable | Meaning |
| --- | --- |
| `MOCK_DEVICE_MODEL` | pseudo-device model name (default `mock-gpu-8gb`) |
| `MOCK_DEVICE_VRAM_MB` | pseudo-device total VRAM (default `8192`) |
| `MOCK_DEVICE_FREE_VRAM_MB` | free VRAM the item must fit in (default = total) |

The pseudo-model memory model (all in MiB) is:

```
demand = BASE(128) + 4 * residues + 512 * first_group_size
         * 0.5 if cpu_offload, * 0.8 if kernel_backend == reference
         - 64 if chunk_size, - 32 if token_budget
```

`cache_clear` deliberately relieves nothing (it changes *when* memory is
released, not how much is asked for), so a `cache_clear`-only plan is a no-op
that the lifecycle drops before it consumes an attempt.

## Running it

```bash
uv run pytest docker/runners/mock_gpu_example/tests/fast/
uv run python -m revocompute doctor --config-root docker/runners --runner mock_gpu_example --strict
```

The family follows the [Example Runner](../example/README.md) layout and the
[Adding a Runner](../../../docs/runner-guide/adding-a-runner.md) change-impact
model. It declares no build inputs and delivers its code as a Runtime Bundle.
