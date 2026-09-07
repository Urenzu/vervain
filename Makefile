# Vervain — coarse-grained MD of SARS-CoV-2 entry.
#
# The pipeline runs under WSL (Ubuntu). GROMACS and martinize2 both assume a
# POSIX toolchain, so native Windows is not a supported path.

VENV    ?= .venv-wsl
PY      := $(VENV)/bin/python
PIP     := $(VENV)/bin/pip
PYPATH  := PYTHONPATH=sim

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

.PHONY: setup
setup: ## Create the venv (on the Linux filesystem) and install dependencies
	bash scripts/setup-env.sh

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

.PHONY: repair
repair: ## Transplant a complete RBD into the spike trimer
	@$(PYPATH) $(PY) -m vervain.repair rbd

.PHONY: forcefield
forcefield: ## Download the pinned Martini 3 force-field files
	@$(PYPATH) $(PY) -m vervain.forcefield fetch

.PHONY: system
system: ## Build the coarse-grained, solvated RBD-ACE2 system
	@$(PYPATH) $(PY) -m vervain.system build

.PHONY: simulate
simulate: ## Minimise, equilibrate and run production
	@$(PYPATH) $(PY) -m vervain.run all

.PHONY: export
export: ## Trajectory -> the binary the viewer reads
	@$(PYPATH) $(PY) -m vervain.export

.PHONY: scene
scene: structures ## Build the staged entry view from deposited structures
	@$(PYPATH) $(PY) -m vervain.scene

.PHONY: first-light
first-light: forcefield structures system simulate export ## The whole chain, end to end

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
