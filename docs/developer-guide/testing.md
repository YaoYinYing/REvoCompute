# Testing and CI

Server tests exercise REvoCompute-owned behavior with synthetic Runner fixtures.
Runner pytest tests belong under `tests/runners/<family>/` only when they execute
small Runner-owned parsers, adapters, or preparation logic. Cross-component
contracts belong under `tests/integration/`.

Do not pytest-test static YAML, Apptainer definitions, dependency pins, shell,
JavaScript, CSS, HTML, workflows, or documentation. Real parsers, linters,
builders, shell/JS syntax checks, and browser behavior remain valid gates.

`docker/runners/<family>/test.yaml` is an executable smoke/live plan, not a unit
test fixture. Smoke proves a candidate runtime can execute a representative
task; only target-host live acceptance can issue promotable receipts or prove
Runner readiness. Fewer pytest cases are expected when static assertions are
removed.
