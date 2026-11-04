# BioEmu2 propagation fixture

`propagation_start.cif` is the real 2KL8 production topology captured from
finished task `4d77ffccf4519b73f73cb9cf2cd8ac28` (`bioemu2_equilibrium`, run
2026-10-21) and stored in `tests/data/bioemu2_replay/2kl8_production_4d77ffcc.json`.
It is not synthetic: the bytes are exactly the payload upstream's
`sample_equilibrium` wrote, decoded with Latin-1, 57760 bytes, sha256
`9387643c18139995991d57991ec1521ecdb46f26b06e91a7a060714e9c4a15dd`.

It is used as the starting structure for the propagation smoke case. Its atoms
must match the system BioEmu2 infers from it; the fixture is a 79-residue
protein from a single-chain equilibrium run on this host, so it is a minimal
contract demonstration rather than a scientific trajectory.
