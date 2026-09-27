# Example Runner

This CPU-only family is the canonical minimal REvoCompute Runner. It turns a
protein FASTA file into deterministic TSV and JSON sequence statistics using
only the Python standard library. It has no weights, databases, host mounts,
network access, or accelerator dependency.

It is also the reference implementation of the persistent multi-item
lifecycle: `analyze.py` normalizes every FASTA record into a work item and
drives `common/persistent_runner.py` through `common/work_items.py`. One task
loads the runtime once, analyzes each record, commits each record's artifacts
into its own directory, resumes from `work_items.json`, and continues after an
item-level failure. The task-level rollup lands in `task_summary.json`. The
protocol itself is documented, with nothing duplicated here, in
[Persistent Execution](../../../docs/runner-guide/persistent-execution.md).

It also demonstrates the three change-impact paths:

| Change | Example files | Required freshness action |
| --- | --- | --- |
| Build identity | `example.def` or a file in `runtime.build_inputs` | Rebuild the SIF, then repeat the live test |
| Execution contract identity | execution fields in `task.yaml`, `runner.yaml`, `expected_files.yaml`, `test.yaml`, or its fixtures | Keep the SIF and repeat the live test |
| Presentation identity | display/help/citation fields in `task.yaml` or `storyboard/` | Keep both the SIF and live-test receipt |

The canonical matrix with the full field list is in the
[Runner change-impact model](../../../docs/runner-guide/adding-a-runner.md#runner-change-impact-model).

`runtime.build_inputs` is a correctness boundary, not an inventory of the
directory. If `analyze.py` changed without being listed there, build provenance
would not notice and an old scientific implementation could remain active.
Now that the family drives the shared lifecycle, `common/persistent_runner.py`
and `common/work_items.py` are build inputs for the same reason: they are copied
into the image and executed there. Conversely, presentation files must not be
added merely to make the list look complete.

Copy this directory when adapting a conventional Runner, then replace the
family identity, Task contract, executable logic, fixture, result contracts,
and scientific metadata. Keep user-facing parameters and input roles in the
owning `task.yaml`; keep deployment-only values in `runner.yaml`.

The family ships its focused contract test at
`tests/runners/example/test_analyze.py`. It executes the real `run.sh` against a
`task.json` contract and proves the Runner consumes the declared named input
role and the server-resolved parameters, commits one directory per FASTA record,
and resumes and reports partial success. Copy that test alongside the family and
adapt it to the new role/parameter vocabulary.

From the repository root, exercise the executable contract and parsed manifest
validation with:

```bash
uv run pytest tests/runners/example/test_analyze.py
uv run python -m revocompute doctor --config-root docker/runners --runner example --strict
```

Follow the [Adding a Runner](../../../docs/runner-guide/adding-a-runner.md)
guide for Doctor, direct SIF build, live-test receipt, and promotion steps.
