# Python and OpenCode/DAGU architecture findings

## Main conclusion

DAGU is the workflow scheduler/runtime. This repository's DAG definitions explicitly launch Python command adapters for stage execution, which is why the project has Python runtime code. Python is not required merely because DAGU cannot orchestrate these workflows.

DAGU has a native `harness.run` action with `provider: opencode` ([Harness docs](https://docs.dagu.sh/step-types/harness), [OpenCode docs](https://docs.dagu.sh/step-types/harness/opencode)). The repository pins DAGU 2.24.0 (`scripts/install_tools.py:11-13`). Running `.tools/bin/dagu validate /tmp/opencode/dagu-opencode-harness-probe.yaml` against that binary accepted a minimal `harness.run` step with `provider: opencode`; this confirms the pinned binary recognizes the action and provider syntax, but is not a real-agent execution test.

`opencode.py` is not inherently required to invoke OpenCode from DAGU. It is used because the current Python stages launch the configured `agent_argv` themselves: the delivery config maps stages to `archon_dagu.live_stage` (`config/commands.json:60-110`), `live_stage.py` calls the agent subprocess (`src/archon_dagu/live_stage.py:105-151`), and standalone/composed runtime code does likewise (`src/archon_dagu/standalone.py`, `src/archon_dagu/composed.py`). The wrapper extracts final assistant text from OpenCode JSONL and now creates/cancels a known session (`src/archon_dagu/opencode.py:24-59,91-163,165-276`). Replacing it with DAGU's native harness therefore means routing an actual DAGU step through `harness.run`; changing `agent_argv` alone will not do that. The exact cancellation/idle-verification behavior of the pinned Dagu 2.24.0 harness has not been established by the syntax-validation probe.

There is also a documentation mismatch: `docs/agents.md:11` says OpenCode calls do not use `--session`, while `src/archon_dagu/opencode.py:215-229` now passes a run-owned session ID.

## Inventory: 33 tracked Python files

### Application modules (`src/archon_dagu/`): 9

| File | Role |
|---|---|
| `__init__.py:1` | Package marker and short package description. |
| `engine.py:2-4,58-139,283-410,551-826` | Delivery controller: stage invocation, schema/evidence handling, typed listing, and delivery reducer. Delivery DAG commands call it (`workflows/archon-round.yaml:12-88`). |
| `live_stage.py:2-5,86-151,283-395` | Delivery stage adapter: renders source prompts/context, runs pinned scripts, launches configured agent, validates reports/evidence. The delivery command map routes live stages here (`config/commands.json:60-110`). |
| `opencode.py:1,24-59,91-163,165-276` | OpenCode JSONL-to-stage-output adapter and session cancellation/idle verification. Replaceable in principle by native Dagu harness steps, but used by the current Python-subprocess architecture. |
| `standalone.py:1,22-29,157-180,536-675` | Runtime for six source-backed standalone workflows; shared fixture/live contracts, checkout/artifact/retry/cancellation handling. |
| `composed.py:1,14-25,30-69,72-140,142-618` | Runtime for six composed workflows; expands source bindings/conditions and manages stages, receipts and nested delivery. |
| `runtime.py:1,7-40` | Shared GitHub CLI environment/config normalization and script-output parsing. |
| `local_runner.py:1-4,19-100` | Local YAML-command test/demo runner, explicitly not DAGU; refuses approval gates. |
| `mock_stage.py:1-10` | Test fixture transport that returns canned stage outputs and never invokes agents/forge commands. |

### CLI, generation and validation scripts (`scripts/`): 11

| File | Role |
|---|---|
| `check_reducer.py:6-77` | Compares Python delivery decisions with the pinned source across 4,096 generated cases. |
| `check_scenarios.py:1-12` | Runs delivery fixture scenarios through the local YAML runner. |
| `composed.py:1-13,16-123` | CLI for composed demos, local/native-DAGU scenarios and validation. |
| `generate.py:1-15,45-85,88-165` | Generates delivery DAGs, prompts, schemas, and source manifest from pinned upstream definitions. |
| `generate_standalone.py:1-22,47-75` | Generates standalone fixture/live DAGs and source-backed prompts. |
| `generate_composed.py:1-27,61-93` | Compiles source graphs into visible composed DAG steps and prompts. |
| `install_tools.py:1-12,21-86` | Installs pinned DAGU, Task and Bun artifacts after SHA-256 verification. |
| `issue_event.py:1-4,12-35` | Normalizes a trusted issue-opened event file to explicit DAG parameters; not an HTTP webhook service. |
| `operate.py:1,20-89,92-136,139-182` | Operator CLI for agent configuration, diagnostics, agent smoke and real delivery. |
| `project.py:1,23-56,59-82,85-189` | Shared Make/Task/CI implementation for source/generated checks, DAGU validation, demos, native smoke and guarded cleanup. |
| `standalone.py:1-15,17-126` | CLI for standalone demos, scenarios and native DAGU validation. |

### Tests (`tests/`): 13

| File | Role |
|---|---|
| `test_automation.py:8-15` | Checks Make/Task target alignment and CI workflow configuration. |
| `test_composed.py:66-447` | Composed graph contracts, bindings, approval, publication, effects and delivery cases. |
| `test_engine.py:22-161` | Delivery reducer/controller contracts, validation and rereview evidence. |
| `test_engine_cancellation.py:62-323` | Cancellation behavior through delivery and live-stage process boundaries. |
| `test_engine_cleanup.py:75-203` | Cleanup/reaping under cancellation, timeout and communication failures. |
| `test_engine_process.py:46-180` | Process-group timeout and invalid-timeout behavior. |
| `test_live_stage.py:123-301` | Live-stage prompt, evidence, large stdin and aggregate deadline behavior. |
| `test_opencode.py:19-135` | OpenCode event parsing and CLI transport contract. |
| `test_opencode_cancellation.py:125-217` | Session interruption, idle verification and fail-closed cancellation. |
| `test_operate.py:18-167` | Operator configuration, diagnostics and delivery command safety. |
| `test_runtime.py:14-78` | Runtime normalization and GitHub CLI behavior. |
| `test_standalone.py:54-449` | Standalone workflow and live transport contracts. |
| `test_workflows.py:9-63` | Pinned-source integrity and generated DAG structure. |

## Necessity distinction

- `engine.py`, `live_stage.py`, `standalone.py`, and `composed.py` implement the current custom port's stage/domain behavior; DAGU supplies scheduling, while these modules supply the command logic the DAGs invoke. DAGU-native actions could replace pieces, but not just by deleting the files.
- `opencode.py` is a custom provider adapter, not a prerequisite for DAGU/OpenCode integration. A native-harness migration should compare output/schema behavior, prompt/context binding, agent/model/variant settings, working directory and cancellation guarantees before removing it.
- `local_runner.py`, `mock_stage.py`, the scenario/parity scripts, and `tests/` are validation/demo machinery, not production workflow execution. The project does have a custom local YAML runner, but this PR did not create a test framework; it added regression coverage for production adapter behavior.
- Generator, installer and operator scripts are maintenance/setup/CLI tools. They do not act as the DAGU scheduler.

## Evidence boundary

At the time of this inventory, the merged branch was `main` at `d5aa79c` (PR #21). Local validation accepted the native Dagu harness YAML syntax; no real OpenCode model/session execution was performed as part of that check.
