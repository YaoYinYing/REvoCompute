.PHONY: test test-all test-unit test-browser test-cov test-docker-full-stack

PYTEST ?= python -m pytest
COV_REPORT ?= term-missing
BROWSER_WORKERS ?= 2

test:
	$(PYTEST) tests/ -v

test-all:
	$(PYTEST) tests/ -v

test-unit:
	$(PYTEST) tests/ -m "not browser" -v

test-browser:
	$(PYTEST) tests/ -m browser -n $(BROWSER_WORKERS) --dist=load -v

test-cov:
	$(PYTEST) tests/ -m "not browser" -v \
		--cov-config=.coveragerc --cov=revocompute \
		--cov-report=$(COV_REPORT)

test-docker-full-stack:
	bash tests/run_full_stack_test.sh
