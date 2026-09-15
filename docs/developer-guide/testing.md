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

## Local development

```bash
# Install in editable mode with test dependencies
pip install -e ".[test]"

# Run the server-owned non-Docker suite
make test

# Run the same coverage target used by server CI
make test-cov

# Run the server directly without Docker
python -m revocompute.app
```

Security regression checks for Docker socket exposure, admin self-lockout,
banned users, and login throttling belong to this suite. The controls those
checks protect are documented in
[Deployment security](../reference/security.md).
