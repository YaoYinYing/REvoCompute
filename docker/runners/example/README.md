# Example Runner

This CPU-only family is the canonical minimal REvoCompute Runner. It turns a
protein FASTA file into deterministic TSV and JSON sequence statistics using
only the Python standard library. It has no weights, databases, host mounts,
network access, or accelerator dependency.

Copy this directory when adapting a conventional Runner, then replace the
family identity, Task contract, executable logic, fixture, result contracts,
and scientific metadata. Keep user-facing parameters and input roles in the
owning `task.yaml`; keep deployment-only values in `runner.yaml`.

The family ships its focused contract test at
`tests/runners/example/test_analyze.py`. It executes the real `run.sh` against a
`task.json` contract and proves the Runner consumes the declared named input
role and the server-resolved parameters. Copy that test alongside the family and
adapt it to the new role/parameter vocabulary.

Follow the [Adding a Runner](../../../docs/runner-guide/adding-a-runner.md)
guide for Doctor, direct SIF build, live-test receipt, and promotion steps.
