# BioEmu2 propagation fixture

`propagation_start.cif` is the real 2KL8 production topology captured from
finished task `4d77ffccf4519b73f73cb9cf2cd8ac28` (`bioemu2_equilibrium`, run
2026-10-21) and stored in `tests/data/bioemu2_replay/2kl8_production_4d77ffcc.json`.
It is not synthetic: the bytes are exactly the payload upstream's
`sample_equilibrium` wrote, decoded with Latin-1, 57760 bytes, sha256
`9387643c18139995991d57991ec1521ecdb46f26b06e91a7a060714e9c4a15dd`.

It is used as the starting structure for the propagation smoke case with
`propagation_start.yaml`, which declares the same 79-residue single chain as a
BioEmu2 System. All three YAML fixtures here (`propagation_start.yaml`,
`equilibrium_system.yaml`, and `ligand_system.yaml`) were serialized by the
pinned JAAG `jaag-core` builder (`bioemu2` target, JAAG commit
`6bc0ff50d6dbe98093b08d3f4287afa2e799d415`); the propagation sequence was read
from the captured CIF. `ligand_system.yaml` declares the same protein chain plus
one `NAG` CCD ligand on chain `B`, so it exercises the pinned upstream parser's
ligand entity path. The fixtures are minimal contract demonstrations rather
than scientific trajectories. Pinned-upstream `validate_x0` compares its atoms
and their order against the declared system before loading the model.
