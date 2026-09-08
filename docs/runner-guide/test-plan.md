# `test.yaml`

Each family owns `test.yaml`, which is the executable acceptance plan for its
production TaskTypes. Pin immutable fixtures under `tests/data/`, name every
required smoke case, and specify the TaskType, input fixture, parameters,
expected outputs, and resource profile. Keep cases small enough for routine
target-host validation while exercising the real parser and artifact checks.

The live-test command executes this plan through Slurm and Apptainer. A family
is not READY until every required case passes. Changing the plan or fixture
digest invalidates the prior receipt. CI contract tests can validate shape and
orchestration, but only target-host execution produces a promotable receipt.
