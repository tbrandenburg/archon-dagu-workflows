# Agent setup and model selection

Every live entrypoint defaults to OpenCode through:

```json
"agent_argv": ["python", "-m", "archon_dagu.opencode", "--agent", "build"]
```

Install OpenCode using its [official instructions](https://opencode.ai/docs/), configure provider credentials using `opencode auth login` or the provider's supported environment variables, and select an available model. Run `opencode models` to see identifiers. The adapter targets the `opencode run --format json` event contract inspected at **v1.19.4**. OpenCode is an operator-installed live prerequisite; `make tools` does not install it and fixture CI does not require it.

The wrapper sends the full prompt on stdin, runs in the workflow checkout, and inherits credentials/configuration from the operator's environment. Each invocation starts a fresh session: no `--continue`, `--session`, shared-server attachment, or automatic permission approval is added. Configure OpenCode's execution permissions for the intended project. Noninteractive permission requests may be rejected by OpenCode; inspect the result and diagnostics.

Use the setup commands for either delivery entrypoint:

```bash
make configure-agent MODEL=provider/model AGENT=build
make doctor
make agent-smoke
make deliver REPO=/absolute/isolated-checkout WORK_FILE=/absolute/accepted-work.md
```

`configure-agent` creates/updates ignored `config/commands.local.json`, preserves the stage command map and other settings, and selects the OpenCode adapter, agent and model explicitly. It does not install OpenCode, store credentials, or infer a paid model. Install/authenticate OpenCode first; model availability depends on your provider account. With a custom config, set `COMMANDS=/absolute/config.json`. A missing explicitly selected config is an error.

`doctor` only checks configuration and executable availability; it does not authenticate, contact a provider or verify tool versions. `agent-smoke` invokes the selected CLI with a tiny JSON prompt from a new empty directory, checks its result and writes a report under `.runs/agent-smoke/`. It invokes no delivery or forge stages, but the CLI still has its configured tools/credentials: the no-tools prompt is not a security sandbox. Provider errors surface as failures; there is no fallback to mock responses. A successful smoke is not proof of delivery behavior or GitHub-write permissions.

`deliver` uses the saved local config automatically (or the built-in live config if none exists), snapshots it into a unique run directory and starts the selected live DAGU definition. It refuses test transports and existing state directories. Fixture commands remain separate and always replace the agent as well as forge stages; running a real agent with a fake forge is not implemented by these shortcuts.

For manual configuration you may still copy `config/commands.json` to `config/commands.local.json`.

Delivery explicitly selects OpenCode's `build` agent. The model is inherited from OpenCode until you pin it with `configure-agent`. To choose explicitly, change `agent_argv` in that local file (replace `provider/model` with an installed model identifier):

```json
"agent_argv": ["python", "-m", "archon_dagu.opencode", "--model", "provider/model", "--agent", "build"]
```

Optional `--variant` forwards the provider's reasoning variant. This selects one configuration for the whole run; per-stage provider routing is not built in.

For a local adapter smoke test with a real model:

```bash
printf '%s\n' 'Return exactly {"ok":true} with no prose.' | \
  uv run python -m archon_dagu.opencode --model provider/model
```

This invokes a real provider and may incur usage charges. It is not part of fixture CI.

## Output and failure handling

The wrapper separates OpenCode's newline-delimited events from the Archon stage result. It ignores tool/reasoning events and earlier assistant messages, concatenates text parts of the final assistant message, and writes that text unchanged to stdout. The existing workflow then parses JSON and validates the source schema where required; the wrapper preserves raw text when used directly. Markdown fences, invalid stage JSON, and missing artifacts are not repaired.

Nonzero OpenCode exits, error events, malformed event JSON, missing text, and explicitly abnormal final finish reasons fail the adapter without emitting a stage answer. OpenCode versions can omit the final `step_finish` event, so its absence alone is not treated as a failure. Process exit plus stage/schema/artifact checks are the available evidence; the event stream is not proof of a complete model run. Diagnostics go to stderr. The wrapper inherits the caller's process group so workflow cancellation reaches OpenCode too.

## Using another CLI

The agent remains selectable. For example, replace `agent_argv` with `["claude", "--print"]` for a CLI returning the stage answer directly. In delivery config, replace `opencode` in `requires` with your CLI's executable.

Other CLIs must read stdin and return the original stage output without a provider envelope. Permission settings and provider authentication remain the operator's responsibility. There is no fallback to another agent if OpenCode fails.

## Verification boundary

Credential-free tests exercise the adapter as a subprocess against a controlled OpenCode-shaped CLI, including large stdin prompts, cwd/model/agent/variant forwarding, event extraction, errors, and nonzero exits. Existing fixture tests still use canned agent responses. Neither test establishes real OpenCode/model/GitHub behavior; a disposable-repository live trial remains necessary.

References: [OpenCode CLI](https://opencode.ai/docs/cli/), [v1.19.4 run implementation](https://github.com/anomalyco/opencode/blob/v1.19.4/packages/opencode/src/cli/cmd/run.ts).


## Direct DAGU operation

```bash
uv run .tools/bin/dagu start workflows/detailed-real.yaml -- \
  project_dir="$PWD" state_dir="/absolute/artifacts/new-run" \
  repo="/absolute/isolated-checkout" commands="config/commands.local.json" \
  work="Implement the accepted change" pull_request="42"
```

The shortcuts do not change the original delivery state machine. Fake issue text alone does not disable public forge operations.


## GitHub without Archon

DAGU is the workflow runtime. Delivery uses the pinned scripts' `gh` path directly; no Archon CLI, server, account or forge plugin is required. Runtime configuration sets `forge_source` to `gh` and ignores inherited `ARCHON_SDLC_FORGE=forge` / `ARCHON_CLI_COMMAND` settings. The Archon-named environment keys retained by the source scripts are compatibility bindings, not a service dependency.

Existing local configs using this repository's built-in `archon_dagu.live_stage` command map are normalized when loaded: the obsolete `archon` prerequisite and `archon_argv` setting are removed in memory. Your saved `agent_argv`, including model selection, is preserved. Re-running `configure-agent` persists the normalized config. Direct DAGU runs receive the same normalization. Custom command adapters are left unchanged. An explicit `forge_source=forge` is refused for the built-in transport.

Run `make doctor` again after updating. `make agent-smoke` checks only agent prerequisites and does not need `gh` or Archon. It can therefore check provider/model access before full delivery tools are installed. GitHub authentication and repository permissions are checked separately by the original forge preflight/operations.
