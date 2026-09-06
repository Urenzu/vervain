# Vervain — coarse-grained MD of SARS-CoV-2 entry.
#
# The pipeline runs under WSL (Ubuntu). GROMACS and martinize2 both assume a
# POSIX toolchain, so native Windows is not a supported path.

VENV    ?= .venv
PY      := $(VENV)/bin/python
PIP     := $(VENV)/bin/pip
PYPATH  := PYTHONPATH=sim

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

$(PY):
	python3 -m venv $(VENV)
	$(PIP) install -q --upgrade pip

.PHONY: setup
setup: $(PY) ## Create the venv and install Python dependencies
	$(PIP) install -q -r requirements.txt

.PHONY: gromacs
gromacs: ## Build GROMACS with CUDA and AVX2 (long; the packaged one has neither)
	bash scripts/setup-gromacs-cuda.sh

.PHONY: doctor
doctor: ## Report what the toolchain can actually do on this machine
	@$(PYPATH) $(PY) -m vervain.doctor

.PHONY: structures
structures: ## Download every structure in the catalogue
	@$(PYPATH) $(PY) -m vervain.structures fetch

.PHONY: catalogue
catalogue: ## List the structure catalogue
	@$(PYPATH) $(PY) -m vervain.structures list

.PHONY: test
test: ## Run the Python test suite
	$(PYPATH) $(PY) -m pytest tests -q

.PHONY: typecheck
typecheck: ## Typecheck the viewer
	cd web && npx tsc -b

.PHONY: web
web: ## Run the viewer dev server
	cd web && npm run dev

.PHONY: check
check: test typecheck ## Everything CI runs

.PHONY: clean
clean: ## Remove the venv and Python caches
	rm -rf $(VENV) .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
