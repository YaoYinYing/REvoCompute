# MolProbity licence notes

The Runner executes the open-source `cctbx-base` distribution of cctbx, which
carries the LBNL BSD-3-Clause licence in `LICENSE.txt` and, in the published
wheel metadata, additionally aggregates BSD-3-Clause, BSL-1.0, LGPL-2.0-only,
LGPL-2.1-only, LGPL-3.0-only, MIT, and LGPL-2.0-or-later WITH
WxWindows-exception-3.1 components.

Two consequences the operator must keep in mind:

- **No Phenix.** The `phenix.molprobity` driver, the separate Duke
  `reduce`/`probe` executables, and any Phenix-only validation feature require a
  commercial Phenix licence. This Runner installs none of them; it calls only
  the open-source `molprobity.ramalyze`, `molprobity.rotalyze`,
  `molprobity.cbetadev`, `molprobity.omegalyze`, and `molprobity.clashscore2`
  console scripts plus `mmtbx.validation.utils.molprobity_score`. Clash
  detection and hydrogen placement run through the `mmtbx.probe` (Apache-2.0,
  preserved at `/opt/molprobity/probe-LICENSE.txt`) and `mmtbx.reduce` C++
  extensions bundled in the same wheel.
- **Reference data is separately licensed.** The Top8000 contour tables come from
  `rlabduke/reference_data` under CC-BY-4.0 (attribution required), and the
  restraint dictionary comes from `phenix-project/geostd` under the LBNL
  BSD-3-Clause licence. Neither is redistributed in the image; the operator
  provisions them from their official repositories, and the SIF records their
  licence files at `/opt/molprobity/reference-licenses/`.
