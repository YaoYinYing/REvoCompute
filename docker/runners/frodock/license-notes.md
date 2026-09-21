# FRODOCK licence notes

FRODOCK is distributed by chaconlab.org under a BSD 3-Clause licence whose text
lives at `https://chaconlab.org/downloads/License.txt`:

> Redistribution and use in source and binary forms, with or without
> modification, are permitted provided that the following conditions are met:
> 1. Redistributions of source code must retain the above copyright notice...
> 2. Redistributions in binary form must reproduce the above copyright notice...
> 3. Neither the name of the copyright holder nor the names of its contributors
>    may be used to endorse or promote products derived from this software...

Points an operator must keep visible:

- The GitHub mirror `chaconlab/FRODOCK` carries **no** licence file and **no**
  source — it is documentation only. The licence above comes from the
  authoritative download page, which is also where the binaries are published.
- There is no academic/non-commercial restriction in the agreement, and no
  registration is required to download. No entitlement gate is added by this
  Runner.
- `frodock3_linux64.tgz` ships other executables (`frodock_mpi_gcc`,
  `frodockgrid_mpi_gcc`, `frodockcheck_gcc`, `frodockonstraints_gcc`). This
  Runner is restricted to the four sequential stages needed for a two-partner
  rigid-body docking run and does not expose constraints or scoring tooling.
  The SIF keeps the four `_gcc` binaries and deletes the `_mpi_gcc` pair for
  runtime reasons; see `MODEL_ASSETS.md`.
