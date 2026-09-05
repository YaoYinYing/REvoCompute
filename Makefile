.PHONY: test test-all test-cov test-docker-full-stack

PYTEST ?= python -m pytest
COV_REPORT ?= term-missing

test:
	$(PYTEST) tests/ -v

test-all:
	$(PYTEST) tests/ -v

test-cov:
	$(PYTEST) tests/ -v \
		--cov-config=.coveragerc --cov=revocompute \
		--cov-report=$(COV_REPORT)

test-docker-full-stack:
	bash tests/run_full_stack_test.sh
