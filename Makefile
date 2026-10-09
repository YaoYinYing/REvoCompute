.PHONY: test server-test runner-fast test-fleet test-all test-unit test-browser test-cov test-registry-xdist test-boundaries test-docker-full-stack

PYTEST ?= python -m pytest
COV_REPORT ?= term-missing
BROWSER_WORKERS ?= 2
REGISTRY_WORKERS ?= 4

# Generic Server collection is independent of the production fleet. Fleet
# projection contracts have a separate, explicitly named collection boundary.
SERVER_TESTS := tests --ignore=tests/fleet
RUNNER_FAST_TESTS := $(sort $(wildcard docker/runners/*/tests/fast))
RUNNER_PYTEST := $(PYTEST) -p docker.runner_testkit.pytest_plugin --import-mode=importlib

server-test test test-unit:
	$(PYTEST) $(SERVER_TESTS) -m "not browser" -v

runner-fast:
	$(RUNNER_PYTEST) $(RUNNER_FAST_TESTS) -q -p no:cacheprovider

test-fleet:
	$(PYTEST) tests/fleet -m "not browser" -q -p no:cacheprovider

test-all: test runner-fast test-fleet test-browser

test-browser:
	$(PYTEST) tests -m browser -n $(BROWSER_WORKERS) --dist=load -v

test-cov:
	$(PYTEST) $(SERVER_TESTS) -m "not browser" -v \
		--cov-config=.coveragerc --cov=revocompute \
		--cov-report=$(COV_REPORT)

test-boundaries:
	python tools/check_test_boundaries.py

# Exercise synthetic discovery and multistage composition under different
# worker schedules. Production Runner modules are never imported here.
REGISTRY_DISTS ?= load loadscope loadfile
test-registry-xdist:
	@for dist in $(REGISTRY_DISTS); do \
		$(PYTEST) tests/test_registry_determinism.py tests/test_plugin_discovery.py \
			tests/test_workflow_composer.py tests/test_workspace_plugin_architecture.py \
			-n $(REGISTRY_WORKERS) --dist=$$dist -q -p no:cacheprovider || exit 1; \
	done

test-docker-full-stack:
	bash tests/run_full_stack_test.sh
