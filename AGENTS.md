# Working in this repository

This repository supports two live delivery entrypoints: `workflows/simple-real.yaml` and `workflows/detailed-real.yaml`. Detailed delivery uses the internal `workflows/archon-round.yaml` child. Standalone/composed workflows also remain supported in fixture/live forms; only delivery dry variants are removed. Keep the original Archon delivery prompts and business rules; see `SOURCE.json` for the pinned source and `docs/parity.md` for limitations. Neither workflow merges PRs.

## Make targets

Run commands from the repository root. `make` or `make help` lists the available targets. Make and `Taskfile.yml` expose the same major commands; Task is installed at `.tools/bin/task` by `make tools`.

| Target | What it does |
|---|---|
| `make setup` | Install locked Python dependencies with `uv sync --frozen`. Requires uv and Python 3.12+. |
| `make tools` | Install checksum-verified DAGU, Task and Bun under `.tools/bin`. Does not install OpenCode, GitHub CLI or provider credentials. Archon is not a runtime dependency. |
| `make configure-agent MODEL=provider/model AGENT=build` | Create/update ignored `config/commands.local.json` with an explicit OpenCode model and agent profile. Preserves the stage command map and other settings. |
| `make doctor` | Show the selected configuration/agent command and explain missing executables. Makes no model call and does not verify authentication or tool versions. |
| `make agent-smoke` | Invoke the actual configured agent with a tiny JSON prompt from a new empty directory. Invokes no delivery or forge stages. This is a real provider call; the no-tools prompt is not a security sandbox. |
| `make deliver REPO=/isolated/checkout WORK_FILE=/accepted-work.md` | Launch actual delivery with the selected agent and configured forge operations. Can commit, push, publish PRs/comments and change draft status. Creates a unique state directory and snapshots the config; refuses test transports and reused state directories. |
| `make fixture-demo` | Run a fixture example with mock agent/forge responses. Defaults to the local command harness. Never invokes the configured agent or public GitHub operations. |
| `make demo` | Compatibility name for the same fixture example. `EXECUTOR=dagu` changes the execution engine, not the mock agent/forge behavior. |
| `make generate` | Regenerate delivery and standalone/composed entrypoints, shared child, prompts, schemas and source manifests. |
| `make generated-check` | Regenerate and check for drift. It can update stale generated files; inspect the diff if it fails. |
| `make source-check` | Verify immutable upstream source hashes. |
| `make format` | Apply Ruff fixes and formatting to first-party Python. |
| `make lint` | Check Ruff rules and formatting without changing files. |
| `make test` | Run unit, contract and controlled subprocess tests without provider/forge credentials. |
| `make parity` | Compare 4,096 reducer decisions against the pinned Archon implementation. |
| `make scenarios` | Run 52 local command scenarios across both live definitions with explicit mock transports. Includes not-ready outcomes waiting for human input. |
| `make validate` | Validate the three DAG definitions and preview both live entrypoints with native `dagu dry`. Previews do not run agents or stage commands. |
| `make native-smoke` | Execute six scenarios through actual DAGU, with agent/forge effects still mocked. Requires Unix-socket support. |
| `make ci` | Run lint, source/generated checks, tests, parity and all 127 local scenarios. No real model or public-forge calls. |
| `make ci-native` | Run native validation/previews and 81 native mock-effect runs (6 delivery, 36 standalone, 39 composed). |
| `make clean` | Remove `.runs/` artifacts. Refuses registered Git worktrees; inspect/preserve useful run evidence before cleanup. |
| `make standalone-demo WORKFLOW=investigate STANDALONE_CASE=happy` | Run a standalone fixture. `EXECUTOR=dagu` uses native DAGU; agent/forge responses remain mocked. |
| `make standalone-scenarios` | Run all 36 standalone fixture scenarios locally. |
| `make standalone-native` | Validate standalone definitions and execute all 36 fixtures through DAGU. |
| `make composed-demo COMPOSED_WORKFLOW=review COMPOSED_CASE=happy` | Run a composed fixture locally or with `EXECUTOR=dagu`. |
| `make composed-scenarios` | Run all 39 composed fixture scenarios locally. |
| `make composed-native` | Validate composed definitions and execute all 39 fixtures through DAGU. |

## Variables and examples

`WORKFLOW` / `STANDALONE_CASE` select standalone fixtures; `COMPOSED_WORKFLOW` / `COMPOSED_CASE` select composed fixtures. Both case variables default to `happy`. See `docs/standalone.md` and `docs/composed.md` for all live parameters. With built-in stage configs, saved `configure-agent` selections are reused; workflow-specific configs override them.

- `VARIANT`: `simple-real` (default) or `detailed-real`; used by fixture examples and live delivery.
- `CASE`: fixture name, default `fix_ci`; applies only to fixture examples.
- `EXECUTOR`: `local` (default) or `dagu`; applies only to fixture examples. The local harness is not DAGU.
- `MODEL`: an available OpenCode `provider/model` identifier for `configure-agent`; no model is guessed.
- `AGENT`: OpenCode agent profile for `configure-agent`, default `build`. Alternative CLIs remain configurable through `agent_argv` in the selected config.
- `COMMANDS`: optional path to a live command config for configuration, diagnostics, agent smoke and delivery. Defaults to the ignored local config when present, otherwise the built-in live config. An explicitly selected missing config is an error.
- `REPO`, `WORK_FILE`: required isolated checkout and accepted-work text file for `deliver`.
- `STATE_DIR`: optional new absolute run directory for `deliver`; otherwise a unique path is allocated under `.runs/live/`.
- `UV`: optional uv executable override for Make.

Fresh setup and actual agent verification:

```bash
make setup tools
# Install OpenCode separately, then authenticate and inspect available models:
opencode auth login
opencode models
make configure-agent MODEL=provider/model
make doctor
make agent-smoke
```

Fixture checks:

```bash
make fixture-demo VARIANT=detailed-real CASE=four_round_cap
make fixture-demo VARIANT=detailed-real CASE=fix_ci EXECUTOR=dagu
make ci
make ci-native
```

Unattended native examples support `ready`, `fix_ci` and `simplify_then_rereview`. Use the local harness for not-ready examples such as `four_round_cap`, since the actual workflow reaches a human task. Do not report the local harness or `dagu dry` as native execution, and do not report fixtures as real-agent evidence.

Actual delivery, using one variant for the intended change:

```bash
make deliver VARIANT=detailed-real REPO=/absolute/isolated-checkout WORK_FILE=/absolute/accepted-work.md
```

Fake issue text does not disable forge operations. A live-agent/fake-forge hybrid is not implemented. Use `docs/agents.md` for agent configuration and direct DAGU parameters such as `pull_request`, `branch`, `part` and `errors`.

## Changes and verification

Keep Make and Task targets aligned. After generator edits, run `make generate` and `make generated-check`. For code/workflow changes, use `make ci` and the applicable native checks. On hosts that block Unix sockets, record the limitation and rely on native CI rather than substituting the local harness. Do not modify pinned vendor files as part of routine changes. Keep credentials, local configuration and generated run artifacts out of commits.
