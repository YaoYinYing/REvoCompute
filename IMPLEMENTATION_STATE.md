# Implementation State — Active Runner Upstream-HEAD Refresh

Branch: `campaign/2026-11-04-active-runner-head-refresh` (Draft / NO MERGE).
Base: `main` `6d726f54113bed4b9eb8328db0d649c1b8582050`.
Policy: Maintainer direction 2026-11-05 and Commander reclassification. Old-result
numeric parity and perfect transitive hash closure are not gates; executed source
identity, recorded environment, native inference, input refusal and output-schema
acceptance are.

## Completed

- BioEmu2: source `6d1ca744fa8ed285edafae7b98da65205bf00fd3` installed over a
  regenerated hash-locked CUDA 12.6 dependency closure; release version stays
  `0.1.0rc0`; source SHA in `.def`, `%test` and `upstream.json`; checkpoint/config
  SHAs and all three Task semantics unchanged.
- OpenDDE: source `9d0d9c975178074c1ce722d2d6eefac8b7057062` (v1.2.0) installed over
  a generated hash-locked closure; `pred` retained; unguided `contact`/`epitope`
  constraints refused; effective precision/TFG/constraint settings published as
  `inference_settings.json`; explicit fp32/TF32 Task defaults retained while the
  upstream BF16/TF32-off change is recorded.
- FreeBindCraft: source `8a10b93a9b42487e7218ad1435a6a25d0e91afc8` (v1.0.7);
  upstream `installation/linux-cuda12-requirements.txt` is the environment manifest;
  CUDA 12.9 base, Python 3.12, OpenMM CUDA; PyRosetta-free relaxation policy
  recorded.
- ESMFold2: source `8f0834cbc350aeaf507f755475873f7c61fa44a1` (v3.4.2); dependency
  closure regenerated without cuEquivariance and with Triton 3.6; backend vocabulary
  mapped to reference/fused/fast with `fused` default and `fast` opt-in; ESMC bf16
  deliberately retained against upstream's fp8 default and published per prediction.
- AlphaFold3: source `37e3c57fe123fc51f6d96236320b8b657afb11ac` (v3.0.5+); three
  pinned HMMER patches applied; `uv sync --frozen`; native dependency revisions
  recorded; `build_data` MessagePack CCD data loaded in `%test`.
- Foundry: retained executable commit `d078b24d6d0e6f8607e9a0311128f4a897f83953`
  named as git source; unpublished `rc-foundry==1.0.0` distribution claim removed
  from provenance, labels, tests and docs; upstream delta confirmed docs-only.

## Verification performed

- `revocompute doctor --config-root docker/runners --runner <family> --strict`:
  bioemu2, opendde, freebindcraft, esmfold2, alphafold3, foundry all OK.
- `make runner-fast`: 662 passed (`-p docker.runner_testkit.pytest_plugin --import-mode=importlib`).
- Focused server result-contract tests: 120 passed, 1 skipped.
- `tests/fleet -m "not browser" -q -p no:cacheprovider`: 160 passed, 1 skipped,
  189 deselected. The OpenDDE synthetic result tree now includes the
  unconditionally published `inference_settings.json`.
- Test-boundary check: clean. `mkdocs build --strict` (system binary): exit 0.
- `bash -n` on `opendde/run.sh`; shellcheck reports only pre-existing informational
  warnings (dynamic source, unused exported runscript path).
- FreeBindCraft environment dry-run against `x86_64-manylinux_2_34` (required by the
  pinned OpenMM 8.6.1 wheel) did not finish in a 300 s local budget; resolution is
  deferred to the candidate-image build rather than claimed.

## Contract notes

- OpenDDE `inference_settings.json` is written unconditionally on every
  successful inference, so it is declared as a required published artifact. The
  only conditional behavior is the pre-inference refusal of an unguided
  `contact`/`epitope` constraint.

## Not performed (host-gated, do not claim)

- No SIF build, `%test` execution, Slurm/Apptainer/GPU run, model-weight download,
  receipt creation, promotion, deployment or merge.
- No candidate-image verification of ESMFold2 checkpoint-config compatibility,
  BioEmu2 `pdbx_formal_charge` consumer handling, FreeBindCraft production-GPU fit,
  or AF3 no-MSA/supplied-MSA/template paths.

## Current phase

Source-level implementation and local validation complete. Next concrete action:
request an authorized candidate-SIF build and representative inference window for
each family, starting with BioEmu2, then record exact receipts. Every family is
**NOT READY / NO PROMOTION** until that evidence exists.
