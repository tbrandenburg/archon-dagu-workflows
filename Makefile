.DEFAULT_GOAL := help
UV ?= uv
CONFIGURE_AGENT = $(if $(filter command line,$(origin OPENCODE_AGENT)),$(OPENCODE_AGENT),$(if $(filter command line,$(origin AGENT)),$(AGENT),build))
VARIANT ?= simple-real
CASE ?= fix_ci
EXECUTOR ?= local
AGENT ?= build
WORKFLOW ?= investigate
STANDALONE_CASE ?= happy
COMPOSED_WORKFLOW ?= review
COMPOSED_CASE ?= happy
export VARIANT MODEL AGENT COMMANDS REPO WORK_FILE STATE_DIR
.PHONY: standalone-demo standalone-scenarios standalone-native composed-demo composed-scenarios composed-native configure-agent doctor agent-smoke deliver fixture-demo help setup tools generate format lint source-check generated-check test parity scenarios validate demo native-smoke harness-native ci ci-native clean
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
harness-native: ## Run four controlled native harness contract probes (Dagu, Linux ss/ps)
	$(UV) run pytest -m native
ci: lint source-check generated-check test parity scenarios standalone-scenarios composed-scenarios  ## Run credential-free checks
ci-native: validate native-smoke harness-native standalone-native composed-native  ## Run native engine checks
clean: ## Remove run artifacts only
	$(UV) run python scripts/project.py clean

configure-agent: ## Save OpenCode agent/model selection (MODEL=provider/model AGENT=build)
	AGENT='$(CONFIGURE_AGENT)' $(UV) run python scripts/operate.py configure-agent
doctor: ## Check live agent/config/tools without invoking a model
	$(UV) run python scripts/operate.py doctor
agent-smoke: ## Invoke the actual agent with a tiny prompt; no delivery/forge stages
	$(UV) run python scripts/operate.py agent-smoke
deliver: ## Run REAL delivery (REPO, WORK_FILE, VARIANT); can push/publish
	$(UV) run python scripts/operate.py deliver
fixture-demo: demo ## Run mock effects; no agent/model/GitHub calls

standalone-demo: ## Run standalone fixture (WORKFLOW, STANDALONE_CASE, EXECUTOR)
	$(UV) run python scripts/standalone.py demo --workflow '$(WORKFLOW)' --case '$(STANDALONE_CASE)' --executor '$(EXECUTOR)'
standalone-scenarios: ## Execute all standalone fixtures locally
	$(UV) run python scripts/standalone.py scenarios
standalone-native: ## Execute all standalone fixtures through actual DAGU
	$(UV) run python scripts/standalone.py validate
	$(UV) run python scripts/standalone.py scenarios --executor dagu

composed-demo: ## Run issue-3 fixture (COMPOSED_WORKFLOW, COMPOSED_CASE, EXECUTOR)
	$(UV) run python scripts/composed.py demo --workflow '$(COMPOSED_WORKFLOW)' --case '$(COMPOSED_CASE)' --executor '$(EXECUTOR)'
composed-scenarios: ## Run all issue-3 fixture scenarios locally
	$(UV) run python scripts/composed.py scenarios
composed-native: ## Preview and execute issue-3 workflows with actual DAGU
	$(UV) run python scripts/composed.py validate
	$(UV) run python scripts/composed.py scenarios --executor dagu
