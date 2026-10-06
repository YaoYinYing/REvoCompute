.PHONY: test test-all test-unit test-browser test-cov test-registry-xdist test-docker-full-stack

PYTEST ?= python -m pytest
COV_REPORT ?= term-missing
BROWSER_WORKERS ?= 2
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
			tests/runners/alphafold3/test_runner.py \
			-n $(REGISTRY_WORKERS) --dist=$$dist -q -p no:cacheprovider || exit 1; \
	done
	@echo "== registry determinism: AF3 runner file run alone (no sibling test may install state) =="
	@$(PYTEST) tests/runners/alphafold3/test_runner.py -q -p no:cacheprovider || exit 1
	@echo "== registry determinism: AF3 preflight case run alone =="
	@$(PYTEST) tests/runners/alphafold3/test_runner.py -k preflight -q -p no:cacheprovider || exit 1

test-docker-full-stack:
	bash tests/run_full_stack_test.sh
