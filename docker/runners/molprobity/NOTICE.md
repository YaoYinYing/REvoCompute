# MolProbity third-party notices

The SIF installs the PyPI `cctbx-base` wheel and redistributes a subset of its
Python and compiled modules, so the wheel's licence aggregation is carried into
`/opt/venv/lib/python*/site-packages/cctbx_base-*.dist-info/` unchanged. The
LBNL licence text is preserved at `/opt/molprobity/LICENSE.txt`.

The reference data is **not** redistributed:

- `rotarama_data` — CC-BY-4.0, `https://github.com/rlabduke/reference_data`
- `geostd` — BSD-3-Clause-LBNL, `https://github.com/phenix-project/geostd`

Their licence files are recorded under `/opt/molprobity/reference-licenses/` so
an operator can confirm the terms of the mounted data without leaving the
container.
