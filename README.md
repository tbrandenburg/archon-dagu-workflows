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

Standalone/composed ports and separate dry workflow variants have been removed. Their earlier versions remain in Git history. The immutable 186-file upstream SDLC pack is retained for relative imports and provenance, not as additional supported DAGU entrypoints.

## Run delivery

Requirements: [uv](https://docs.astral.sh/uv/), Python 3.12+, Node.js 24, Bun, DAGU, authenticated Archon/gh, and configured OpenCode/provider credentials. Linux/macOS are supported by the tool installer; use WSL on Windows.

```bash
uv sync --frozen
make tools                         # checksum-verified DAGU, Task and Bun
cp config/commands.json config/commands.local.json
```

Configure the agent/model and prerequisites in the ignored local config; see [agent setup](docs/agents.md). Use an explicitly isolated Git checkout for live work. The workflow can commit, push, create/update PRs and comments, and change draft status.

```bash
uv run .tools/bin/dagu start workflows/simple-real.yaml -- \
  project_dir="$PWD" \
  state_dir="/absolute/artifacts/delivery-001" \
  repo="/absolute/isolated-checkout" \
  commands="config/commands.local.json" \
  work="Implement the accepted plan at plans/my-change.md"
```

Replace `simple-real.yaml` with `detailed-real.yaml` for visible stages and parallel review. Use a unique state directory per run. Supply `pull_request=42` to continue a PR; `branch`, `part`, and `errors` are also forwarded. Inspect the report and any uncertain remote effects before retrying. Neither workflow merges.

## Examples without external effects

Examples execute those same live definitions with a test-only transport and a disposable local checkout. No model or GitHub operation is invoked; reports carry `simulated: true`. There are no separate dry workflow files.

```bash
make demo                          # simple-real, mocked CI repair, local harness
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
| `setup`, `tools` | Install locked Python dependencies / verified DAGU, Task and Bun |
| `generate`, `generated-check` | Regenerate workflows, schemas, prompts and config / detect drift |
| `format`, `lint`, `source-check` | Format, check style, verify upstream hashes |
| `test`, `parity`, `scenarios` | Contracts, 4096 reducer comparisons, 52 mock-effect scenarios |
| `validate`, `native-smoke` | Native previews / six actual DAGU executions with mock effects |
| `demo` | Select `VARIANT`, `CASE`, `EXECUTOR=local` or `dagu` |
| `ci`, `ci-native` | Credential-free quality suite / native engine suite |
| `clean` | Remove `.runs/` only |

## Layout

- `workflows/`: two live entrypoints and their shared round child.
- `src/archon_dagu/`: delivery controller, live/OpenCode integrations, test transport and local harness.
- `prompts/`: original delivery prompts; `examples/fixtures/`: named mock outcomes.
- `tests/`, `scripts/`: contracts, generation, parity, examples, tooling and native checks.
- `vendor/archon/`, `SOURCE.json`: upstream source, license and immutable hashes, pinned to `72817c50dc51bb91773f71e5448bb7d387bfc8dd`.

Live agent and public-forge behavior remains experimental. CI uses no provider or GitHub-write credentials. See [development](CONTRIBUTING.md), [attribution](NOTICE.md), and [MIT license](LICENSE).
