# Archon delivery workflows for DAGU

[![CI](https://github.com/tbrandenburg/archon-dagu-workflows/actions/workflows/ci.yml/badge.svg)](https://github.com/tbrandenburg/archon-dagu-workflows/actions/workflows/ci.yml)

Four source-backed ports of [Archon's delivery workflow](https://github.com/coleam00/Archon/blob/72817c50dc51bb91773f71e5448bb7d387bfc8dd/.archon/workflows/sdlc/deliver/archon-deliver-block.yaml), with reproducible offline examples and an experimental live integration.

**Accepted work → implement → draft PR → review → simplify → CI → fix findings → ready PR.**

Delivery starts after the work has been decided. It does not triage issues, decide the product plan, merge a PR, or deploy. A successful run can report **not ready** and ask for a person's decision.

| Variant | Orchestration | External effects |
|---|---|---|
| [simple-dry](workflows/simple-dry.yaml) | One compact batch controller | Fixture agents/forge; original local decision/report scripts |
| [detailed-dry](workflows/detailed-dry.yaml) | Visible rounds and parallel review lenses | Same fixtures and business rules |
| [simple-real](workflows/simple-real.yaml) | Compact controller | Original publishing/thread scripts and configured agent CLI |
| [detailed-real](workflows/detailed-real.yaml) | Visible DAGU stages | Same live integrations |

The original prompts and 186 upstream source files are pinned to Archon commit `72817c50dc51bb91773f71e5448bb7d387bfc8dd`. Live behavior is **experimental, not a proven feature-equivalent replacement for Archon**. Read [parity and limitations](docs/parity.md) before a disposable-repository trial.

## Quick start

Requirements: [uv](https://docs.astral.sh/uv/), Python 3.12+, and Node.js 24. Task is optional; Make exposes the same targets. Linux/macOS are supported by the tool installer; use WSL on Windows.

```bash
uv sync --frozen
make demo                         # local offline rehearsal; no credentials
make demo VARIANT=detailed-dry CASE=four_round_cap
make test parity                  # contracts + 4096 source-decision comparisons
```

The local demo executes the workflow's real shell commands and dependencies through a small test harness. It **does not claim to be DAGU runtime execution**. Artifacts go to `.runs/`; no machine-specific paths or run artifacts are committed.

To run the examples with the actual engine:

```bash
make tools                        # checksum-verified DAGU 2.24.0 + Task 3.54.0
make validate                     # native validation + four dry previews
make demo VARIANT=detailed-dry EXECUTOR=dagu
make native-smoke                 # six real engine runs, all external effects fake
```

Equivalent Task commands:

```bash
.tools/bin/task --list
.tools/bin/task demo VARIANT=detailed-dry CASE=fix_ci EXECUTOR=dagu
.tools/bin/task ci
.tools/bin/task ci-native
```

Native `dagu dry` only previews a workflow; fixture execution through `dagu start` is a separate check. Hosts that prohibit Unix sockets cannot run the native smoke suite. CI fails that check rather than silently substituting the local harness.

## Developer commands

| Make / Task target | Purpose |
|---|---|
| `setup`, `tools` | Install locked Python dependencies / verified command-line tools |
| `generate`, `generated-check` | Regenerate portable workflows, schemas and prompts / detect drift |
| `format`, `lint` | Format / check first-party Python; upstream source is untouched |
| `source-check` | Verify the pinned upstream hashes |
| `test`, `parity` | Fast contract/safety tests / 4096 reducer comparisons |
| `scenarios` | 104 local command scenarios across all four variants; live effects mocked |
| `validate`, `native-smoke` | Native DAGU previews / real scheduling of six fixture scenarios |
| `demo` | Select `VARIANT`, `CASE`, and `EXECUTOR=local` or `dagu` |
| `ci`, `ci-native` | Credential-free quality suite / native engine suite |
| `clean` | Remove `.runs/` only |

Both entrypoints call the same Python command implementations. Workflow YAML uses explicit project, checkout and state paths. [Generation](scripts/generate.py) does not embed the author's home or virtualenv directory.

## Live operation

The live files can commit, push, publish PRs/comments and change draft status. They never merge. They require Bun, authenticated Archon/gh, a configured agent CLI, accepted work, and an explicitly isolated target checkout. No live workflow runs in CI.

Copy `config/commands.json` to `config/commands.local.json` to customize the agent argv and installed-tool requirements. Private local config is ignored by Git. The agent must return the requested JSON object, not a provider envelope. No permission-bypass flags are added.

```bash
uv run dagu start workflows/detailed-real.yaml -- \
  project_dir="$PWD" \
  state_dir="/absolute/artifacts/delivery-001" \
  repo="/absolute/isolated-checkout" \
  commands="config/commands.local.json" \
  work="Implement the accepted plan at plans/my-change.md"
```

Use `.tools/bin/dagu` in place of `dagu` if it is not on your PATH. Supply `pull_request=42` to continue a PR. `branch`, `part` and `errors` are also forwarded. Do not blindly retry a write whose remote result is uncertain.

## Layout

- `src/archon_dagu/`: controller, live integration, explicit mock transport, local test harness.
- `workflows/`: four entrypoints and the shared round DAG.
- `prompts/`: original Archon prompts, not rewritten approximations.
- `examples/fixtures/`: named offline outcomes, including CI repair, open threads and round exhaustion.
- `tests/`, `scripts/`: unit tests, source parity, integration scenarios, tool installation and native examples.
- `vendor/archon/`, `SOURCE.json`: immutable upstream source, license and hashes.
- `docs/`: [workflow walkthrough](docs/workflow.md), [parity](docs/parity.md), [development](CONTRIBUTING.md).

See [NOTICE.md](NOTICE.md) for upstream attribution. Project code uses the existing [MIT license](LICENSE).
