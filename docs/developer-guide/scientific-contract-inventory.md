# Runner scientific contract audit

This page is the human-facing owner of the distributed-Runner contract audit. It
records *what evidence exists* for each shipped TaskType and *what each piece of
evidence does and does not establish*. It is a coverage and defect report, not a
clean bill of health, and it is regenerated from the fleet rather than maintained
by hand.

The machine-readable inventory is produced by
`tools/audit_runner_scientific_contracts.py` (inspect-only, like
`tools/audit_runtime_sizes.py`: it never builds, pulls, or runs an image). The
tool consumes the loaders production already uses — `task_types.isolated_discovery`
for task, input-role, parameter and view declarations; `result_audit.audit_fleet`
for the result contract; `result_storyboard` for the result tree and storyboard;
`live_tests.load_live_test_plan` for each family plan; and the `input_validators`
registries for the format and logical-type lifecycle. It is therefore not a second
semantic registry: a row cannot disagree with what the Server accepts, and it
reruns against another fleet revision without editing a roster.

```bash
python tools/audit_runner_scientific_contracts.py          # human table
python tools/audit_runner_scientific_contracts.py --json   # machine-readable
```

The structural invariants of the report are pinned by
`tests/fleet/test_fleet_scientific_contract_inventory.py`. Those tests assert
coherence — a partition that sums, a classification that is total, a corpus whose
labels are decided by provenance — never scientific validity.

## Coverage states

A Task's coverage state answers whether its result contract could be evaluated at
all. The four states are exhaustive and mutually exclusive, and they reconcile
with the result audit's `covered` / `unaudited` partition.

| State | Meaning | Audit bucket |
|---|---|---|
| `tree_audited` | Ships a declared result tree **and** a required view source, so the required-source and renderer-kind invariants were evaluated | covered |
| `no_required_source` | Ships views, but every required source is optional (or exempt), so the Task imposes no tree obligation | covered |
| `no_views` | Declares no result workspace at all | covered |
| `tree_absent` | Requires a view source but ships no `expected_files.yaml`, so nothing can be checked against a declared identity | unaudited |

`no_required_source` is a real state and is **not** "has a tree". A family may
publish an `expected_files.yaml` while declaring no view (`no_views`, e.g. the
PSSM-GREMLIN family); conversely a view may declare every one of its sources
optional.

Coverage and defect status are independent. A `tree_audited` Task can carry a
concrete defect, and the report always exposes both, so a clean defect set can
never be read as "the whole fleet passed": the defect set is currently empty
while 36 Tasks remain unaudited (see [Known defects](#known-defects)).

## Evidence levels

Each family is recorded at the strongest evidence level it has actually reached,
from weakest to strongest. The levels are **never summed and never substituted**:
a static contract is not a fake-runner contract, a fake-runner contract is not a
real CLI run, and a real local run is not target-host Slurm+Apptainer acceptance.

| Level | What it establishes | What it does not |
|---|---|---|
| `static_contract` | The Task's declarations are internally satisfiable and the loader accepts them | that any Runner executed |
| `fake_runner_contract` | A family test runs the real adapter (executes `run.sh`/`predict.py`) against a fake executable and asserts behavior | that the real upstream program ran |
| `declared_scientific_acceptance` | A family scientific module carries the `scientific_acceptance` marker | that anything executed — a marker is a declaration, and a module that replaces the upstream program with a fake declares an intention, not a run |
| `real_runner_cli` | A checked-in replay bundle covers the family and its provenance re-verifies | that the cluster scheduled it — a family that really runs the program but ships no bundle is deliberately under-claimed |
| `target_host_slurm_apptainer` | A result captured from the canonical finished task store whose production API acceptance receipt re-verifies through the canonical receipt parser | that the science is correct, or that the recorded run was *complete* — the receipt's own `complete` flag is not part of the predicate, so a successful but partial run reaches this label |

`real_runner_cli` is decided by **one class of artifact only**: a re-verified replay
bundle. The scanner *reads* test files and never runs them, so no fact it extracts
from test text can decide that a real program ran. A substring is not a call — a
comment or docstring naming `subprocess.run` proves nothing — and the *absence* of a
substitution is not establishable by a token scan either, because `MagicMock`,
`mocker.patch.object`, and a plain lambda assignment all replace the upstream program
without naming a mocking library. A marked family that mocks upstream is therefore
reported at `declared_scientific_acceptance` and never one level higher, and a family
that genuinely runs the program but ships no bundle is under-claimed rather than
over-claimed. The level never claims more than a re-verifiable artifact proves.

Two families currently reach `real_runner_cli`: one through the same re-verified
bundle that reaches the strongest level, one through a capture recorded without a
scheduler allocation. Only one family reaches `target_host_slurm_apptainer`. That is
the point of the table: most of the fleet's strongest available evidence is static or
fake-runner, and the report says so instead of implying uniform validation.

## Evidence corpus

The evidence corpus is the set of checked-in artifacts that can be replayed
through the production frontend. It is **derived from disk** — every
`tests/data/*_replay/*.json` bundle is loaded through the real
`capture_replay_bundle` / `load_bundle` path — and each item's label is decided by
*that item's own re-verified provenance*, never by a list on this page. The label
therefore cannot drift into claiming more than the artifact proves.

| Label | Decided by | Scientific claim |
|---|---|---|
| `real_target_host_slurm_apptainer` | The bundle's `production_receipt` pointer re-verifies through `frontend_fixtures.provenance.production_receipt_pointer` against the cited receipt. The receipt's own `complete` flag is not part of the predicate, so a successful but partial run reaches this label | replayed Runner output |
| `real_runner_local_no_scheduler` | The capture records a real Runner run with no batch-scheduler allocation | replayed Runner output |
| `synthetic_mock` | Fixture bytes captured with `require_finished=False`, which stand in for a result rather than reproduce one. No fleet bundle reaches this label today; it is declared for the class | **none** |
| `unverified_declaration` | A declaration whose provenance could not be re-verified | **none** |

A replay bundle proves **frontend compatibility with authentic Runner output**. It
does not prove the science, and it is not an acceptance receipt; the
synthetic-fixture, real-result-replay, and scientific-reference claims remain
separate. No mock is ever presented as scientific validation, and the boundary is
the existing `tests/frontend_fixtures` replay infrastructure — there is no second
mock backend. See
[Testing and CI](testing.md#replaying-a-captured-real-runner-result) for the
bundle contract and [Live Testing and Receipts](../operator-guide/live-testing.md)
for what owns scientific acceptance.

## Parameters and inputs

The audit reports, per Task, the declared parameter vocabulary, the named input
roles with their logical type, the Core lifecycle class that enforces each type's
semantics, and whether each declared format falls inside the Core upload security
boundary. It also reports **parameter-forwarding candidates**: declared parameters
whose name appears nowhere in the family's executable adapter assets.

Two caveats are load-bearing and are carried in the report itself:

- **A candidate is not a verdict.** The Server owns no param → upstream-flag
  mapping; the mapping is arbitrary adapter code (string concatenation, an
  allow-list, a conditional branch). A static scan can therefore only surface
  *candidates* for a parameter that never reaches upstream — it cannot prove
  forwarding, and it must not be read as proving its absence. It also produces
  false positives: a parameter a family forwards through a `for key in …` loop or
  a dict it builds internally is not "absent" in the scientific sense.
- **The only executable forward-path evidence is a family's own `tests/fast`
  case** that runs the real adapter against a fake executable and asserts the
  exact argv. That is the form a behavioral forwarding verdict must take; a
  scanner over adapter text is not a substitute.

## Known defects

The audit's defect set is orthogonal to its coverage partition, and it is
currently **empty**: `defective: []`, `ok: true`, with the coverage partition
unchanged at 20 covered / 36 unaudited. An empty defect set is not a clean bill
of health — all 36 unaudited Tasks still report
`result.required_source_undeclared_tree`, because no shipped tree exists to check
their required sources against.

The one concrete defect recorded on this base is now **resolved**, and the
resolution is a declaration change rather than an allowlist entry:

- **`foundry_rfd3_design` / `foundry_rfd3na_design`: primary candidates had no
  declared identity.** Both design Tasks publish a `candidate-collection` primary
  view over `*.cif.gz`, while the family's single shared `expected_files.yaml`
  declared only the RF3 fold spelling (`*_model.cif`) under `structures`, so the
  design Tasks' primary candidates matched no declared logical file and the shared
  storyboard resolved no structures for them. The task-scoped result contract
  resolves it: each design Task now ships its own `expected_files.yaml` declaring
  the compressed `*.cif.gz` design tree, beside its own `storyboard/`. The
  `result.required_source_unaddressed` finding is absent for both, neither is
  defective, and both remain `tree_audited` and covered.

A second discrepancy was recorded as a **parameter** finding rather than a result
contract defect, and the parameter-semantics follow-on closed it:
`foundry_rfd3na_design.num_recycles` was declared, range-validated and recorded in
the run's provenance, but the launcher forwards it only for the RFD3 model; the
follow-on removed the control and made the launcher fail closed, so the two no
longer diverge.

## Regenerating this page

The page is prose about a machine-generated report; keep the two in sync by
rerunning the tool and the fleet tests after any family, `expected_files.yaml`,
`storyboard.yaml`, `test.yaml`, or `runner.yaml` change:

```bash
python tools/audit_runner_scientific_contracts.py
make test-fleet
```

`make test-fleet` includes the inventory invariants; a family that gains a tree,
loses a required source, or changes its evidence level will fail there rather than
silently changing the numbers on this page.
