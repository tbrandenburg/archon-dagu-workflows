# Archon delivery for DAGU

[![CI](https://github.com/tbrandenburg/archon-dagu-workflows/actions/workflows/ci.yml/badge.svg)](https://github.com/tbrandenburg/archon-dagu-workflows/actions/workflows/ci.yml)

Two live ports of [Archon's delivery workflow](https://github.com/coleam00/Archon/blob/72817c50dc51bb91773f71e5448bb7d387bfc8dd/.archon/workflows/sdlc/deliver/archon-deliver-block.yaml):

| Workflow | Behavior |
|---|---|
| [simple-real](workflows/simple-real.yaml) | Compact controller handles the delivery loop; selected review lenses run sequentially. |
| [detailed-real](workflows/detailed-real.yaml) | Closest source mapping: visible rounds and stages, with parallel review lenses in the shared round DAG. |

**Accepted work → implement → draft PR → review → simplify → CI → fix findings → ready PR.**

Both use the same pinned Archon prompts, business rules, four-round limit, and live integrations. `archon-round.yaml` is an internal child used by detailed delivery, not a third public workflow. OpenCode is the default agent; the agent and model remain configurable.

Delivery starts after work is decided. It does not triage, create an initial product plan, merge, or deploy. Not-ready results ask for a developer's decision. Detailed delivery preserves source behavior as closely as this port supports; it is not proven full runtime/feature parity. Read [the walkthrough](docs/workflow.md) and [limitations](docs/parity.md).

Only the two **delivery dry variants** are removed. Other workflow types remain supported with their fixture/live entrypoints. The immutable 186-file upstream SDLC pack is retained for relative imports and provenance, not as additional supported DAGU entrypoints.

## Other workflows

| Family | Workflows | Documentation |
|---|---|---|
| Standalone developer steps | Validate, investigate, plan, triage, implement, standup | [Prompts, inputs and examples](docs/standalone.md) |
| Composed workflows | Review, simplify, PR creation, ship, upkeep, approved issue replies | [Stages, approval and examples](docs/composed.md) |

Each has `*-live.yaml` and `*-fixture.yaml` definitions. There are 27 YAML definitions: 26 public entrypoints plus delivery's shared round child. Only delivery is restricted to real variants; non-delivery fixtures stay available.

All live workflows use OpenCode's `build` profile by default and GitHub CLI directly, without Archon installed. With the built-in standalone/composed config, a saved `make configure-agent MODEL=provider/model` selection is inherited from `config/commands.local.json`. A workflow-specific custom/local config keeps its own explicit agent settings.

```bash
make standalone-demo WORKFLOW=investigate
make composed-demo COMPOSED_WORKFLOW=review
make standalone-scenarios composed-scenarios
make standalone-native composed-native
```

These demo/scenario targets mock model and forge effects; the live entrypoints and their required parameters are documented in the guides above.

For live review readiness gaps, see [typed-listing diagnostics](/docs/composed.md#recovery-and-fidelity)
before cleaning up the run evidence.

Before model-backed PR, review, or validation trials, follow the [live acceptance checklist](docs/live-acceptance.md).
The accepted operating scope is **operator-supervised, one writer, no automatic
uncertain-write replay**. See the [reconciliation procedure](/docs/recovery.md).
This is not acceptance of unattended delivery, ship/upkeep mutation, or automatic
human continuation.
Delivery adapter deadlines are limited to 24 hours; cancellation remains terminal
even during timeout cleanup, and raw stderr survives malformed output. See
[adapter timeouts](/docs/workflow.md#adapter-timeouts-and-cancellation).

## Run delivery

DAGU runs the workflow, OpenCode runs agent steps, and `gh` handles GitHub operations. No Archon installation is required.

Requirements: [uv](https://docs.astral.sh/uv/), Python 3.12+, Node.js 24, Bun, DAGU, authenticated GitHub CLI (`gh`), and configured OpenCode/provider credentials. Linux/macOS are supported by the tool installer; use WSL on Windows.

```bash
make setup tools
# Install OpenCode using https://opencode.ai/docs/ if it is not already installed.
opencode auth login
opencode models
make configure-agent MODEL=provider/model  # choose an available model; agent defaults to build
make doctor                               # tool/config check; no model call
make agent-smoke                          # tiny REAL model call; no delivery/forge stage
```

`configure-agent` saves your choice in ignored `config/commands.local.json`; no manual JSON editing is needed. `doctor` shows the exact selected command and explains missing tools. Authentication and model access are checked by `agent-smoke`, not inferred from installed binaries. Alternative agents and advanced settings are documented in [agent setup](docs/agents.md).

Put the accepted task in a text file, then run delivery against an explicitly isolated Git checkout:

```bash
make deliver REPO=/absolute/isolated-checkout WORK_FILE=/absolute/accepted-work.md
make deliver VARIANT=detailed-real REPO=/absolute/isolated-checkout WORK_FILE=/absolute/accepted-work.md
```

Run one variant per intended delivery. The default is `simple-real`; detailed delivery exposes stages and parallel review. Both invoke actual agents and configured forge operations: they can commit, push, publish PRs/comments, and change draft status. Neither merges. The launcher snapshots the selected config and creates a unique state directory under `.runs/live/`; override it with `STATE_DIR=/absolute/new-run` and select another config with `COMMANDS=/absolute/commands.json`. Existing state directories and `test_transport` configs are refused by the live launcher.

Make and Task accept the same names/variables, for example `.tools/bin/task deliver VARIANT=detailed-real REPO=/absolute/isolated-checkout WORK_FILE=/absolute/accepted-work.md`. Configuration and paths are passed through environment/argv rather than interpolating work text into a shell command.

Direct DAGU operation remains supported. Pass `project_dir`, `state_dir`, `repo`, `commands`, and `work` explicitly as shown in [agent setup](docs/agents.md). Supply `pull_request`, `branch`, `part`, or `errors` directly for advanced operation. Inspect the report and uncertain remote effects before retrying.

## Examples without external effects

`fixture-demo` (and its compatibility alias `demo`) prints an explicit no-agent banner. Examples execute those same live definitions with a test-only transport and a disposable local checkout. No model or GitHub operation is invoked; reports carry `simulated: true`. There are no separate dry workflow files.

```bash
make fixture-demo                  # simple-real, mocked CI repair, local harness
make demo VARIANT=detailed-real CASE=four_round_cap
make test parity                   # contracts and 4096 reducer comparisons
make scenarios                     # 52 cases across both live entrypoints
```

The local harness executes workflow commands/dependencies but is not the DAGU runtime. For actual DAGU scheduling:

```bash
make validate                      # validate 3 definitions; preview 2 live entrypoints
make demo VARIANT=detailed-real CASE=fix_ci EXECUTOR=dagu
make native-smoke                  # 6 DAGU runs with mocked external effects
```

Native examples use `ready`, `fix_ci`, or `simplify_then_rereview` so they can finish unattended. Not-ready outcomes reach the real human task and are checked by the local scenarios instead. `dagu dry` is only a wiring preview, not a model or stage execution. Hosts that forbid Unix sockets cannot run native DAGU; CI requires actual native execution.

Task exposes the same targets and variables:

```bash
.tools/bin/task --list
.tools/bin/task demo VARIANT=detailed-real CASE=fix_ci EXECUTOR=dagu
.tools/bin/task ci
.tools/bin/task ci-native
```

## Developer commands

| Make / Task target | Purpose |
|---|---|
| `configure-agent`, `doctor`, `agent-smoke`, `deliver` | Save agent/model, check tools, test actual agent, start real delivery |
| `setup`, `tools` | Install locked Python dependencies / verified DAGU, Task and Bun |
| `generate`, `generated-check` | Regenerate workflows, schemas, prompts and config / detect drift |
| `format`, `lint`, `source-check` | Format, check style, verify upstream hashes |
| `test`, `parity`, `scenarios` | Contracts, 4096 reducer comparisons, 52 delivery mock-effect scenarios |
| `validate`, `native-smoke` | Native previews / six delivery DAGU executions with mock effects |
| `standalone-demo`, `standalone-scenarios`, `standalone-native` | Standalone fixtures locally / native validation and execution |
| `composed-demo`, `composed-scenarios`, `composed-native` | Composed fixtures locally / native validation and execution |
| `fixture-demo`, `demo` | Select `VARIANT`, `CASE`, `EXECUTOR=local` or `dagu` |
| `ci`, `ci-native` | Credential-free quality suite / native engine suite |
| `clean` | Remove `.runs/` only |

## Layout

- `workflows/`: two live delivery entrypoints, their round child, and the restored standalone/composed entrypoints.
- `src/archon_dagu/`: delivery controller, live/OpenCode integrations, test transport and local harness.
- `prompts/`: original delivery prompts; `examples/fixtures/`: named mock outcomes.
- `tests/`, `scripts/`: contracts, generation, parity, examples, tooling and native checks.
- `vendor/archon/`, `SOURCE.json`: upstream source, license and immutable hashes, pinned to `72817c50dc51bb91773f71e5448bb7d387bfc8dd`.

Live agent and public-forge behavior remains experimental. CI uses no provider or GitHub-write credentials. See [development](CONTRIBUTING.md), [attribution](NOTICE.md), and [MIT license](LICENSE).
