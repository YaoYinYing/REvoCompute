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

Coverage and defect status are independent. `tree_audited` Tasks can still carry a
concrete defect: the two Foundry design Tasks ship a tree and are defective (see
[Known defects](#known-defects)). The report always exposes both, so it can never
be read as "the whole fleet passed".

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
| `real_runner_cli` | A checked-in replay bundle of a real run exists, or a family acceptance module both contains an execution primitive and does not mock the adapter | that the cluster scheduled it |
| `target_host_slurm_apptainer` | A result captured from the canonical finished task store whose production API acceptance receipt re-verifies through the canonical receipt parser | that the science is correct, or that the recorded run was *complete* — the receipt's own `complete` flag is not part of the predicate, so a successful but partial run reaches this label |

The scanner's honest limit is that it **reads** test files; it never runs them. Only
a replay bundle is an artifact whose provenance can be re-verified, so only that path
is decision-grade. The `real_runner_cli` path additionally requires an execution
primitive and the *absence* of a mocking primitive, which is why a module like
`evosplit`'s — marker set, upstream `infer_features` replaced by a fake — is reported
at `declared_scientific_acceptance` and not one level higher. That split exists so a
pytest marker can never stand in for a real CLI run.

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

The audit's defect set is orthogonal to its coverage partition. As of the recorded
base there are two concrete defects, both in the Foundry family, both reported by
the audit rather than allowlisted:

- **`foundry_rfd3_design` / `foundry_rfd3na_design`: primary candidates have no
  declared identity.** Both design Tasks publish a `candidate-collection` primary
  view over `*.cif.gz`, but the family's single shared `expected_files.yaml`
  declares only the RF3 fold spelling (`*_model.cif`) under `structures`. The
  design Tasks' primary candidates therefore match no declared logical file and
  the shared storyboard resolves no structures for them. Resolving it means giving
  the design Tasks their own result tree and storyboard, which is a family
  redesign; that work is owned by the task-scoped result-tree follow-on, not by
  this audit.

A third discrepancy is recorded as a **parameter** finding rather than a result
contract defect and belongs to the parameter-semantics follow-on:
`foundry_rfd3na_design.num_recycles` is declared, range-validated and recorded in
the run's provenance, but the launcher forwards it only for the RFD3 model, and
the live-test plan's smoke case does not distinguish the two.

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
