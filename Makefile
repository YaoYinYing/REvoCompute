.PHONY: test test-all test-unit test-browser test-cov test-registry-xdist test-docker-full-stack

PYTEST ?= python -m pytest
COV_REPORT ?= term-missing
BROWSER_WORKERS ?= 2
REGISTRY_REPEATS ?= 5
REGISTRY_WORKERS ?= 4

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

# The registry/discovery determinism regression: repeatedly exercise discovery
# and the AF3 workflow-composer path under parallel workers. Any residual
# dependence on test scheduling order surfaces here.
test-registry-xdist:
	@for run in $$(seq 1 $(REGISTRY_REPEATS)); do \
		echo "== registry determinism run $$run/$(REGISTRY_REPEATS) =="; \
		$(PYTEST) tests/test_registry_determinism.py tests/test_plugin_discovery.py \
			tests/test_workflow_composer.py tests/test_workspace_plugin_architecture.py \
			-n $(REGISTRY_WORKERS) --dist=load -q -p no:cacheprovider || exit 1; \
	done

test-docker-full-stack:
	bash tests/run_full_stack_test.sh
