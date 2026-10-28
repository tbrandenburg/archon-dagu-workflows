.DEFAULT_GOAL := help
UV ?= uv
VARIANT ?= simple-real
CASE ?= fix_ci
EXECUTOR ?= local
AGENT ?= build
export VARIANT MODEL AGENT COMMANDS REPO WORK_FILE STATE_DIR
.PHONY: configure-agent doctor agent-smoke deliver fixture-demo help setup tools generate format lint source-check generated-check test parity scenarios validate demo native-smoke ci ci-native clean
help: ## List common commands
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "  %-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)
setup: ## Install locked Python dependencies
	$(UV) sync --frozen
tools: ## Install checksum-verified DAGU and Task locally
	$(UV) run python scripts/install_tools.py
generate: ## Regenerate portable workflows and prompts
	$(UV) run python scripts/generate.py
format: ## Format first-party Python
	$(UV) run ruff check --fix src scripts tests
	$(UV) run ruff format src scripts tests
lint: ## Check Python style and formatting
	$(UV) run ruff check src scripts tests
	$(UV) run ruff format --check src scripts tests
source-check: ## Verify the pinned Archon source
	$(UV) run python scripts/project.py source-check
generated-check: ## Check generated workflow drift
	$(UV) run python scripts/project.py generated-check
test: ## Run fast contract and safety tests
	$(UV) run pytest
parity: ## Compare 4096 decisions against Archon
	$(UV) run python scripts/check_reducer.py
scenarios: ## Execute all 52 local mock scenarios
	$(UV) run python scripts/check_scenarios.py
validate: ## Run native DAGU validation and previews
	$(UV) run python scripts/project.py validate
demo: ## Run a live entrypoint with mock effects (VARIANT, CASE, EXECUTOR)
	$(UV) run python scripts/project.py demo --variant '$(VARIANT)' --case '$(CASE)' --executor '$(EXECUTOR)'
native-smoke: ## Run six actual DAGU fixture executions
	$(UV) run python scripts/project.py native-smoke
ci: lint source-check generated-check test parity scenarios  ## Run credential-free checks
ci-native: validate native-smoke  ## Run native engine checks
clean: ## Remove run artifacts only
	$(UV) run python scripts/project.py clean

configure-agent: ## Save OpenCode agent/model selection (MODEL=provider/model AGENT=build)
	$(UV) run python scripts/operate.py configure-agent
doctor: ## Check live agent/config/tools without invoking a model
	$(UV) run python scripts/operate.py doctor
agent-smoke: ## Invoke the actual agent with a tiny prompt; no delivery/forge stages
	$(UV) run python scripts/operate.py agent-smoke
deliver: ## Run REAL delivery (REPO, WORK_FILE, VARIANT); can push/publish
	$(UV) run python scripts/operate.py deliver
fixture-demo: demo ## Run mock effects; no agent/model/GitHub calls
