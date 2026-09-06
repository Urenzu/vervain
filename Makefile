# Vervain — Linux-native backend.
#
# The backend targets Linux. Verified on Ubuntu 26.04 / CPython 3.14 with
# manylinux_2_28 wheels; no compiler required. macOS works via the same code
# path. Windows is supported by the source but is not the reference platform.

VENV    ?= .venv
PY      := $(VENV)/bin/python
PIP     := $(VENV)/bin/pip
PYTHONPATH_SIM := PYTHONPATH=sim

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

$(PY):
	python3 -m venv $(VENV)
	$(PIP) install -q --upgrade pip

.PHONY: setup
setup: $(PY) ## Create the venv and install Python dependencies
	$(PIP) install -q -r requirements.txt
	@$(PYTHONPATH_SIM) $(PY) -c "from vervain.solve.engine import ensure_bngpath; \
	  p = ensure_bngpath(); print('BioNetGen:', p or 'NOT FOUND - set BNGPATH')"

.PHONY: web-setup
web-setup: ## Install frontend dependencies
	cd web && npm install

.PHONY: test
test: ## Run the Python test suite
	$(PYTHONPATH_SIM) $(PY) -m pytest tests -q

.PHONY: typecheck
typecheck: ## Typecheck the frontend
	cd web && npx tsc -b

.PHONY: check
check: test typecheck ## Everything CI runs

.PHONY: serve
serve: ## Run the solver + websocket server (pre-warms the slider grid, ~30s)
	$(PYTHONPATH_SIM) $(PY) -m vervain.server.app

.PHONY: web
web: ## Run the frontend dev server
	cd web && npm run dev

.PHONY: sweep
sweep: ## Print the interferon sweep across the outcome boundary
	@$(PYTHONPATH_SIM) $(PY) -c "from vervain.validate.sweep import main; main()"

.PHONY: clean
clean: ## Remove the venv and Python caches
	rm -rf $(VENV) .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
