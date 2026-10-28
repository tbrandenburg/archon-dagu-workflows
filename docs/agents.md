# Agent setup and model selection

Every live entrypoint defaults to OpenCode through:

```json
"agent_argv": ["python", "-m", "archon_dagu.opencode"]
```

Install OpenCode using its [official instructions](https://opencode.ai/docs/), configure provider credentials using `opencode auth login` or the provider's supported environment variables, and select an available model. Run `opencode models` to see identifiers. The adapter targets the `opencode run --format json` event contract inspected at **v1.19.4**. OpenCode is an operator-installed live prerequisite; `make tools` does not install it and fixture CI does not require it.

The wrapper sends the full prompt on stdin, runs in the workflow checkout, and inherits credentials/configuration from the operator's environment. Each invocation starts a fresh session: no `--continue`, `--session`, shared-server attachment, or automatic permission approval is added. Configure OpenCode's execution permissions for the intended project. Noninteractive permission requests may be rejected by OpenCode; inspect the result and diagnostics.

Copy `config/commands.json` to ignored `config/commands.local.json` for either delivery entrypoint.

The wrapper inherits OpenCode's configured default model/agent. To choose explicitly, change `agent_argv` in that local file (replace `provider/model` with an installed model identifier):

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
