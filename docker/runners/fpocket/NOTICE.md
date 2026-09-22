# fpocket third-party notices

The MIT licence in `LICENSE` covers the fpocket sources. The statically linked
components that ship inside the same source tree carry their own terms:

- `src/qhull` — Qhull. Its terms are reproduced verbatim in `QHULL_COPYING.txt`
  at the repository root.
- `plugins/LINUXAMD64/molfile/libmolfile_plugin.a` — the VMD molfile plugin
  static library. Its copyright notice (Board of Trustees of the University of
  Illinois, 1995-2006) is embedded in the public header
  `plugins/include/molfile_plugin.h` and is preserved in the image, since the
  archive ships no separate plugin licence file.

The definition copies `LICENSE`, `QHULL_COPYING.txt`, and the molfile public
header into `/opt/fpocket/` so the redistributed binary keeps the notices its
dependencies require. The SIF keeps only the `fpocket` executable; the
`tpocket` and `dpocket` binaries built by the same Makefile are deleted, because
this family exposes pocket detection only.
