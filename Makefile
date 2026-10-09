.PHONY: test server-test runner-fast test-all test-unit test-browser test-cov test-registry-xdist test-docker-full-stack

PYTEST ?= python -m pytest
COV_REPORT ?= term-missing
BROWSER_WORKERS ?= 2
REGISTRY_WORKERS ?= 4

SERVER_TESTS := $(shell find tests -type f -name 'test*.py' ! -path 'tests/runners/*' | sort)

server-test:
	$(PYTEST) $(SERVER_TESTS) -v

runner-fast:
	$(PYTEST) docker/runners/*/tests -m "runner_contract and not scientific_acceptance" -q -p no:cacheprovider

test:
	$(PYTEST) $(SERVER_TESTS) -v

test-all:
	$(PYTEST) tests/ -v

test-unit:
	$(PYTEST) $(SERVER_TESTS) -m "not browser" -v

test-browser:
	$(PYTEST) $(SERVER_TESTS) -m browser -n $(BROWSER_WORKERS) --dist=load -v

test-cov:
	$(PYTEST) $(SERVER_TESTS) -m "not browser" -v \
		--cov-config=.coveragerc --cov=revocompute \
		--cov-report=$(COV_REPORT)

# The registry/discovery determinism regression: repeatedly exercise discovery,
# the AF3 workflow-composer path, and the AF3 runner file the fix edits, under
# parallel workers. run-to-run order variance is the point, so each repeat uses
# a different xdist distribution; a residual dependence on test scheduling order
# surfaces here instead of intermittently in CI.
REGISTRY_DISTS ?= load loadscope loadfile
test-registry-xdist:
	@run=0; for dist in $(REGISTRY_DISTS); do \
		run=$$((run + 1)); \
		echo "== registry determinism run $$run/$$(echo $(REGISTRY_DISTS) | wc -w) (--dist=$$dist) =="; \
		$(PYTEST) tests/test_registry_determinism.py tests/test_plugin_discovery.py \
			tests/test_workflow_composer.py tests/test_workspace_plugin_architecture.py \
			-n $(REGISTRY_WORKERS) --dist=$$dist -q -p no:cacheprovider || exit 1; \
	done

test-docker-full-stack:
	bash tests/run_full_stack_test.sh
