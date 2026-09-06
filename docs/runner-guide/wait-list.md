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

All entries below are **Wait list** candidates. Runtime-family placement has not
yet been decided for any entry.

## Candidates

| Project | Upstream owner | Status | Scientific purpose / workload class | License and access review | External assets | Hardware assessment | Storyboard need | Runtime-family placement |
|---|---|---|---|---|---|---|---|---|
| [EvoSplit](https://github.com/YaoYinYing/EvoSplit) | YaoYinYing | Wait list | Not assessed; evolutionary/protein-design workload to be confirmed | TBD; authoritative upstream terms required | Not assessed; TBD | Not assessed | Not assessed | Not decided |
| [frustraMPNN](https://github.com/YaoYinYing/frustraMPNN) | YaoYinYing | Wait list | Not assessed; sequence/design workload to be confirmed | TBD; authoritative upstream terms required | Not assessed; TBD | Not assessed | Not assessed | Not decided |
| [RFdiffusion2](https://github.com/YaoYinYing/RFdiffusion2) | YaoYinYing | Wait list | Not assessed; structure/design generation workload to be confirmed | TBD; authoritative upstream terms required | Not assessed; TBD | Not assessed | Not assessed | Not decided |
| [foundry](https://github.com/RosettaCommons/foundry) | RosettaCommons | Wait list | Not assessed; biomolecular modeling/design workload to be confirmed | TBD; authoritative upstream terms required | Not assessed; TBD | Not assessed | Not assessed | Not decided |
| [dynamicMPNN](https://github.com/TCoulth/dynamicMPNN) | TCoulth | Wait list | Not assessed; protein sequence/design workload to be confirmed | TBD; authoritative upstream terms required | Not assessed; TBD | Not assessed | Not assessed | Not decided |
| [PPIformer](https://github.com/YaoYinYing/PPIformer) | YaoYinYing | Wait list | Not assessed; protein-protein interaction workload to be confirmed | TBD; authoritative upstream terms required | Not assessed; TBD | Not assessed | Not assessed | Not decided |
| [Mu-Protein](https://github.com/YaoYinYing/Mu-Protein) | YaoYinYing | Wait list | Not assessed; protein modeling/design workload to be confirmed | TBD; authoritative upstream terms required | Not assessed; TBD | Not assessed | Not assessed | Not decided |
| [AlphaFold 3](https://github.com/google-deepmind/alphafold3) | google-deepmind | Wait list | Biomolecular structure prediction comparison candidate; exact REvoCompute workload TBD | TBD; code, weights, and database terms require separate authoritative review | Model weights/databases likely require separate provisioning; exact requirements TBD | Not assessed | Custom structure/confidence presentation may be needed; TBD | Not decided |
| [Boltz](https://github.com/jwohlwend/boltz) | jwohlwend | Wait list | Biomolecular structure prediction comparison candidate; exact workload TBD | TBD; authoritative upstream terms required | External model assets and databases: TBD; separate provisioning assessment required | Not assessed | Custom structure/confidence presentation may be needed; TBD | Not decided |
| [Protenix](https://github.com/bytedance/Protenix) | bytedance | Wait list | Biomolecular structure prediction comparison candidate; exact workload TBD | TBD; authoritative upstream terms required | External model assets and databases: TBD; separate provisioning assessment required | Not assessed | Custom structure/confidence presentation may be needed; TBD | Not decided |
| [Chai-1 / chai-lab](https://github.com/chaidiscovery/chai-lab) | chaidiscovery | Wait list | Biomolecular structure prediction comparison candidate; exact workload TBD | TBD; authoritative upstream terms required | External model assets and databases: TBD; separate provisioning assessment required | Not assessed | Custom structure/confidence presentation may be needed; TBD | Not decided |
| [GREMLIN_LH](https://github.com/sokrypton/GREMLIN_LH) | sokrypton | Wait list | Evolutionary coupling / sequence-landscape workload; likely MSA-oriented inputs and matrix/score outputs | TBD; authoritative upstream terms required | MSA/database requirements: TBD; separate provisioning assessment required | Not assessed | Matrix/score-oriented presentation may be needed; TBD | Not decided |

The structure-prediction entries form a comparison cluster for planning only.
Scientific similarity does not imply runtime compatibility: dependency stacks,
accelerators, system ABI, model/database assets, and licensing constraints must
be assessed independently. Restricted software and scientific assets must use
the server-owned Runner access/entitlement mechanism; this document makes no
legal eligibility determination.

AlphaFold 3 requires a particularly explicit separation between code
adaptation and access to model weights or databases. Its presence here does
not mean that REvoCompute distributes those assets.

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
