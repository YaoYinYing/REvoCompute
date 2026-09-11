# Runner Adaptation Wait List

This is a planning record for upstream projects that have not been adapted to
REvoCompute. Nothing on this list is currently enabled, registered, or
supported by REvoCompute. A wait-list entry is not a support commitment.

## Scope and status

REvoCompute keeps these states distinct:

- **Supported/enabled:** currently present in the production Runner inventory.
- **Actively adapting:** an implementation is being developed and reviewed.
- **Wait list:** candidate only; no REvoCompute runtime contract exists yet.
- **Rejected/deferred:** not currently pursued where an explicit decision is recorded.

Entries remain unsupported until their Runner contracts are implemented,
validated, and enabled. Intake findings and provisional family placements do
not by themselves change support status.

Eight candidates remain on the wait list. Boltz, Chai-1, ESMFold 2, and
SimpleFold left this list after their validated runtimes were enabled in the
23-family production deployment on 2026-09-11.

## Candidates

| Project | Upstream owner | Status | Scientific purpose / workload class | License and access review | External assets | Hardware assessment | Storyboard need | Runtime-family placement |
|---|---|---|---|---|---|---|---|---|
| [EvoSplit](https://github.com/YaoYinYing/EvoSplit) | YaoYinYing | Wait list | MSA clustering and subsampling to separate conformation-specific coevolutionary signals; optional structure-supervised clustering, MSA extension, and contact-map generation ([paper](https://doi.org/10.1038/s42004-026-01940-9)) | Apache-2.0 code; intake revision `6eedfcd5a0551bd1fecf9c51818be19f9e730e19` | ESM-MSA-1b model and contact-regression weights are lazily resolved through `torch.hub`; upstream example MSAs/structures and publication data are separate inputs, not weights | Python 3.10, Torch 2.8/CUDA 12.6, DeepSpeed, HMMER 3.3.2, HH-suite 3.3.0; GPU-oriented contact inference, while clustering stages are CPU-capable | Clustered A3M files, contact map, and optional conformation assignments | Dedicated `evosplit` runtime; reuse the authoritative ESM asset files if byte-compatible, but the current `esm` family uses a materially different Python/Torch stack |
| [RFdiffusion2](https://github.com/YaoYinYing/RFdiffusion2) | YaoYinYing | Wait list | All-atom enzyme active-site scaffolding and small-molecule binder generation, with optional LigandMPNN sequence fitting and Chai-1 refolding ([preprint](https://doi.org/10.1101/2025.04.09.648075)) | BSD-3-Clause code; intake revision `d365cbf4db3958814a9f8e4f6f94fa309dfebc2b`; checkpoint terms still require a separate audit | Upstream setup downloads `RFD_173.pt`, `RFD_140.pt`, two LigandMPNN checkpoints, and three upstream SIFs from `files.ipd.uw.edu`; REvoCompute must provision the checkpoints externally and build its own SIF | Python >=3.11; CUDA 12.1/12.4 requirement sets include PyG compiled wheels and RAPIDS `pylibcugraphops`; documented examples are prohibitively slow without a GPU | Generated PDB/TRB trajectories plus optional sequence/refold and metric tables | Dedicated `rfdiffusion2` family; its all-atom pipeline, checkpoints, and CUDA/PyG/RAPIDS ABI differ from the existing RFdiffusion v1 runner |
| [foundry](https://github.com/RosettaCommons/foundry) | RosettaCommons | Wait list | Shared inference platform exposing distinct RFD3/RFD3NA generation, RF3 folding, and ProteinMPNN/LigandMPNN inverse-folding commands | BSD-3-Clause code; intake revision `b02eed6a6bdf8f44d14a80cc36e3da13c9f2291c`; model/checkpoint terms require separate confirmation | `foundry install` downloads registered IPD-hosted RFD3, RFD3NA, RF3, ProteinMPNN, LigandMPNN, and SolubleMPNN checkpoints into a search path; registry has URLs but no SHA-256 values | Python >=3.12, Torch >=2.2 and AtomWorks >=2.1.1; RF3 adds CUDA-12 cuEquivariance wheels, while the MPNN path is lighter | Per-command structure, sequence, confidence, and score views | Dedicated multi-capability `foundry` family; preserve its shared AtomWorks/checkpoint-registry runtime and expose separate TaskTypes rather than merging its MPNN command into the established `mpnn` family |
| [PPIformer](https://github.com/anton-bushuiev/PPIformer) | anton-bushuiev | Wait list | PPI mutation-effect (binding ddG) prediction and residue-level interface embeddings ([ICLR 2024 paper](https://arxiv.org/abs/2310.18515)) | MIT code; canonical upstream revision `e324f5f30dd0dae55d194ac6b4d18c772219c3ee`; Zenodo record `12789167` publishes the weights under CC BY 4.0 | `weights.zip` is downloaded and extracted at runtime from Zenodo record `12789167`; it contains a three-model ddG ensemble and masked-modeling checkpoint and must instead be provisioned read-only | Python 3.10, Torch 2.1, PyG 2.3.1, Graphein 1.7.6 and a forked Equiformer; code selects CUDA when present and supports CPU fallback | Mutation/ddG table with residue and chain mapping; embedding tensor for the distinct embedding TaskType | Dedicated `ppiformer` family because its older Torch/PyG/Equiformer/Graphein graph stack is ABI-sensitive and does not match an established family |
| [Mu-Protein](https://github.com/YaoYinYing/Mu-Protein) | YaoYinYing | Active intake; upstream runtime blocked | μFormer mutation-fitness prediction/model fitting and μSearch reinforcement-learning navigation of protein fitness landscapes ([paper](https://doi.org/10.1038/s42256-025-01103-w)) | MIT code at `c228769f635e066d592838018b14463720956455`. The encoder record description requires CC BY-NC 4.0 even though its Figshare metadata says CC BY 4.0, so use the more restrictive noncommercial access policy. The μSearch checkpoint record says CC BY 4.0. | The Git-LFS `pretrained/pmlm_650m.pt` pointer declares 2,723,505,310 bytes and SHA-256 `41ec3830624151782d20d41c033bd22a4a268a065ccb2dc8276ecf5d7cd62caa`. The official Figshare encoder is provisioned read-only with 8,170,009,235 bytes, published MD5 `2f7da1ebbd6ad659f6194dfa2d77dc1b`, and observed SHA-256 `6778beb3d4e278dc278666151aa6eb02f800f300573766d853ec0676cc11ce35`. The official TEM-1 μFormer checkpoint is also provisioned read-only with 8,100,983,131 bytes, published MD5 `79e07f4fb5cfe0b1b53c00cc34543a74`, and observed SHA-256 `1f8e55dd1aa57df4b427b74137f1f474064a7b548d1f35fb1686cebf9a8e1d8d`. | μFormer documents Python 3.8 and Torch 1.12/CUDA 11.3 with Fairseq 0.10.2; μSearch pins Torch 1.11/CUDA 11.3 and adds a vendored Stable-Baselines3/FLEXS stack. PyRosetta and ViennaRNA belong to other demo landscapes and are not required for the scoped μFormer-oracle workflow. | Fitness predictions and mutation tables; search trajectories and optimized sequence candidates | Keep μFormer fitting and μSearch optimization as separate TaskTypes. A shared family is acceptable only after the Torch/Fairseq/RL stack is demonstrated together. Both official checkpoints now have a checksum-gated, `weights_only` conversion path, but the pinned runtime still disables loading and μSearch references an unavailable developer-local normalization CSV; no TaskType can be registered until sanitized conversion and published-score reproduction succeed. |
| [Protenix](https://github.com/bytedance/Protenix) | bytedance | Wait list | Biomolecular structure prediction comparison candidate; exact workload TBD | TBD; authoritative upstream terms required | No candidate-specific provisioned root is recorded; weights, databases, revisions, and acquisition terms require separate assessment | Not assessed | Custom structure/confidence presentation may be needed; TBD | Dedicated-family candidate pending dependency, accelerator, ABI, asset, and execution-semantics audit |
| [Pallatom](https://github.com/levinthal/Pallatom) | levinthal | Wait list | Unconditional joint all-atom protein structure and sequence generation ([preprint](https://doi.org/10.1101/2024.08.16.608235)) | CC BY-NC-SA 4.0 code/assets; intake revision `b27d70054dec6ce2f5ceadf8977de3d3baf00663`; noncommercial access policy required | Repository contains `params/params_Pallatom.npz` (71,002,706 bytes; SHA-256 `57dff1c37cb1d99984ab664a7dc96e2a44afb100ea6f1f3c397dbe838124bc2f`); provision it outside the SIF despite upstream bundling | Upstream supports Python 3.10 with JAX 0.4.34/CUDA 12.6 (legacy path is Python 3.7/JAX 0.3.25) and also requires TensorFlow CPU, RDKit, and AlphaFold-derived modules; GPU generation expected | Generated PDB ensemble, sequence FASTA, and sampling metadata | Dedicated restricted `pallatom` JAX family; its runtime, execution semantics, and noncommercial terms do not match existing Torch structure-design families |
| [GeoDock](https://github.com/Graylab/GeoDock) | Gray Lab | Wait list | Flexible protein-protein docking from two partner structures ([Protein Science paper](https://doi.org/10.1002/pro.4862)) | MIT code; intake revision `df8d1f4c24ae2946655f27e7411ba2ffabf3d350`; bundled checkpoint has no separate upstream terms | Repository contains `geodock/weights/dips_0.3.ckpt` (SHA-256 `4a323ebaba152285a2444dcbf68de2dba7ec77f7d61a6d8b693c75169900d162`); ESM2 650M is lazily downloaded by symbolic name and must be provisioned separately | Python 3.9, Torch 2.0.1/CUDA 11.8, CUDA-specific PyG/`torch-scatter`/`torch-sparse` wheels, ESM 2.0 and OpenMM 7.7; CPU fallback exists, while upstream reports sub-second single-GPU inference | Docked PDB with partner mapping and refinement/provenance metadata | Dedicated `geodock` family because its CUDA-11.8 PyG ABI, ESM2 dependency, and optional OpenMM refinement do not match current families |

The structure-prediction entries form a comparison cluster for planning only.
Scientific similarity does not imply runtime compatibility: dependency stacks,
accelerators, system ABI, model/database assets, and licensing constraints must
be assessed independently. Restricted software and scientific assets must use
the server-owned Runner access/entitlement mechanism; this document makes no
legal eligibility determination.

### Mu-Protein security gate

The pinned official Mu-Protein revision is intentionally fail-closed. Upstream
PR `microsoft/Mu-Protein#40`, merged as
`c228769f635e066d592838018b14463720956455`, removed all executable
`torch.load` calls after security issue `#39`. The affected functions continue
to consume the undefined checkpoint value, so both μFormer evaluation and the
μFormer landscape used by μSearch fail before producing a scientific result.

REvoCompute must not silently reverse that mitigation or accept uploaded pickle
checkpoints. Promotion requires all of the following:

- download only the immutable first-party Figshare file identifiers through the
  operator preparation path and record both the published MD5 and local SHA-256;
- mount the checkpoint directory read-only and reject every unexpected asset;
- deserialize only the allow-listed operator-provisioned files in an offline,
  unprivileged conversion step, then execute Tasks from a tensor-only format;
- demonstrate that the converted state produces the upstream example scores;
- keep the target-specific TEM-1 checkpoint unavailable for unrelated reference
  sequences; and
- complete a real SLURM/Apptainer live test before reporting `READY`.

## Future promotion path

A candidate leaves the wait list only after an upstream revision is pinned and
the adaptation assessment covers:

- scientific input/output contract and executable entry point;
- dependency/runtime environment and Docker/Apptainer feasibility;
- CPU/GPU and scheduler resource needs;
- weights, databases, and other external assets;
- license and access constraints;
- result artifact types and storyboard/visualization needs;
- testing strategy; and
- runtime-family placement.

The resulting Runner must then define its scientific, runtime, resource, output,
presentation, and access-policy contracts before it can be considered for
implementation or enablement.
