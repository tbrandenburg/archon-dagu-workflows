# Standalone developer workflows

Issue #2 adds six workflows beside the existing delivery port. Each has a `*-fixture.yaml` entrypoint with fake agents/forge data and a separately selected `*-live.yaml` entrypoint. These are ports of the pinned Archon workflows, not newly invented issue-resolution prompts.

## What each run does

| Workflow | Stages visible in DAGU | Main input | Result |
|---|---|---|---|
| `validate` | discover checks → execute check groups → classify only a red gate → result | `scope` | `green`, `red_cause`, summary, `validation.md`, per-check logs |
| `investigate` | investigate → derive verdict | `input` (issue, symptom, failing command) | rooted/refuted/inconclusive, `rooted`, `investigation.md` |
| `plan` | load policy → plan | `input`, optional `prior_report`, `related` | `ready`, `open_questions`, `plan.md` |
| `triage` | load policy → triage → derive labels/verdict | `input`, optional `publish=true` | contract, route, related work, proposed edits/blockers/closure, `triage.md` |
| `implement` | up to five fresh agent turns | `input` (decided work, plan, findings, CI failure) | `done`, `green`, `red_cause`, commits, `implementation.md` |
| `standup` | gather git/GitHub/context in parallel → synthesize → persist | checkout and local maintainer profile | dated brief plus next-run state |

A completed workflow does not necessarily mean the work is ready. An inconclusive investigation, blocked plan, blocked triage, or incomplete implementation is a valid business outcome. Read `report.json` and its original `result`, not just DAGU's green lifecycle badge. A five-turn implementation cap returns `outcome=false`, `reason=iteration_cap`; a child process or schema error fails the run.

### Prompts, in developer wording

The exact source prompts are checked in under [`prompts/standalone`](../prompts/standalone). The transport substitutes their declared inputs once, appends bound input context and the original JSON Schema, and launches a fresh configured CLI process. A literal token in user input is not substituted again.

| Stage | What the original prompt asks the agent to do |
|---|---|
| Validate discovery | Read the repo's own configuration; declare actual check argv arrays and independent groups. Do not invent a generic gate. |
| Validate classification | Use recorded failures to distinguish introduced, inherited, and environment causes. Classification never turns red into green. |
| Investigate | Reproduce the symptom and prove the causal chain, or explain why it was refuted or remains inconclusive. Leave code unchanged. |
| Plan | Verify current code, choose an approach and reject alternatives with reasons, then write verifiable steps and acceptance checks. Stop on a decision that belongs to the owner. |
| Triage | Reconcile issue claims with current code, prior attempts, open PRs, and project direction. Decide whether the contract is actionable and where it should go. |
| Implement | Build only the accepted work, commit coherent changes, run focused checks, and write a durable next-session handoff. Preserve unrelated discoveries without widening scope. |
| Standup | Cross-reference collected changes, PRs, issues, direction, profile, and prior state; produce a P1–P4 brief and a state block for tomorrow. |

`STANDALONE_SOURCE.json` maps every stage to its source node and copied prompt. Schemas and deterministic script paths are read directly from the pinned YAML; they are not maintained as hand-written copies. `SOURCE.json` covers the existing 186-file SDLC pack; `STANDALONE_SOURCE.json` additionally hashes the eight maintainer files imported at the same revision.

## Fixture examples

Requirements: uv, Python 3.12+, Node.js 24, and the tools installed below. Bun runs the original TypeScript scripts; it is not an agent.

```bash
uv sync --frozen
make tools
make standalone-demo WORKFLOW=investigate
make standalone-demo WORKFLOW=triage STANDALONE_CASE=blocked
make standalone-demo WORKFLOW=implement STANDALONE_CASE=cap
make standalone-demo WORKFLOW=standup STANDALONE_CASE=prior-state
make standalone-scenarios

# Actual DAGU execution, rather than the local command harness:
make standalone-demo WORKFLOW=validate STANDALONE_CASE=red-introduced EXECUTOR=dagu
make standalone-native
```

Task exposes the same names and variables, for example:

```bash
.tools/bin/task standalone-demo WORKFLOW=plan STANDALONE_CASE=blocked EXECUTOR=dagu
```

There are 36 checked-in scenarios. Fixture runs create a disposable Git repository under their state directory; they do not open the supplied target repository or invoke an agent/forge transport. They execute the original validation runner, result/triage scripts, standup context reader, and standup persistence script. Validation fixtures deliberately run small local Python commands so exit statuses, group short-circuiting, logs, and unstartable commands are tested. Triage publication is forcibly disabled; standup git/GitHub facts are injected. The reports say `external_effects: simulated`.

`dagu dry` only previews command wiring. It does not run the agents or prove their output contracts. CI separately executes every fixture with `dagu start`, using Bun, and checks the expected report including deliberately failed runs. It also retains the existing delivery checks.

## Live examples

Live agent and public-forge behavior is experimental. No paid model or real tracker writes are tested in CI. Controlled subprocess tests exercise the live transport and isolated Git commits; they do not establish model or real GitHub parity.

OpenCode `build` is the default through the included JSON-event adapter; see [agent setup and model selection](agents.md). Copy `config/standalone.json` to `config/standalone.local.json`. To use another agent, configure `agent_argv` for a noninteractive CLI that accepts the full prompt on stdin and returns the requested stage value on stdout. SDLC stages return a bare JSON object; standup returns its raw brief and delimited state block. Other provider envelopes require an operator-supplied adapter. The port adds no permission-bypass or automatic approval flags. Script execution defaults to Bun; `make tools` installs checksum-verified Bun 1.4.4, DAGU 2.24.0, and Task 3.54.0.

```bash
# Start from a clean, existing repository. Use an absolute, unique state directory.
uv run .tools/bin/dagu start workflows/investigate-live.yaml -- \
  project_dir="$PWD" \
  state_dir="/absolute/runs/investigation-001" \
  repo="/absolute/checkouts/widgets" \
  input="Investigate why an empty configuration crashes" \
  config="config/standalone.local.json"

# Replace the entrypoint and request to plan or implement decided work:
uv run .tools/bin/dagu start workflows/implement-live.yaml -- \
  project_dir="$PWD" \
  state_dir="/absolute/runs/implementation-001" \
  repo="/absolute/checkouts/widgets" \
  input="Implement the plan at /absolute/runs/plan-001/plan.md" \
  config="config/standalone.local.json"
```

Live investigation, planning, triage, and implementation require a nonempty `input`: DAGU has no Archon trigger message to supply an omitted request.

For validation, pass `scope=package-or-check-name` when narrowing is wanted. For planning, `prior_report` should be an absolute report path and `related` is a JSON list of `{url, relation}`. Triage defaults to `publish=false`; explicitly setting `publish=true` lets the original verdict script verify the issue identity, apply label deltas, and read them back through the selected `gh`/Archon forge source. Triage does not close the issue or start delivery.

Live SDLC workflows create a Git worktree from the target's current HEAD. Investigation, plan, triage, and validation use detached worktrees. Implementation gets a new `dagu/implement-<run-directory-name>` branch; it can commit but does not create a PR. The original checkout must be clean so uncommitted work is never silently omitted. Configure the agent's execution policy for the privileges it needs. A worktree contains edits; it is not a security boundary preventing a CLI from writing elsewhere or using its credentials.

Advisory agent stages compare checkout contents, modes, symlinks, Git state, and HEAD before/after and refuse a changed checkout. This is detection after execution, not preventive isolation. Validation's original declared project commands can legitimately generate build files. Review those commands as the project's own gate.

### Standup's explicit in-place behavior

The original standup is project-specific: it fetches `origin/dev`, fast-forwards only a clean local `dev`, reads `.archon/direction.md` and `.archon/maintainer-standup/profile.md`, and writes state and dated briefs under `.archon/maintainer-standup/`. It does not automatically switch to `main`. These assumptions are preserved, including its warnings and empty-data fallbacks on failed GitHub reads. A brief can therefore be partial; inspect the facts and stderr.

Set `standup_in_place=true` in private configuration to enable live standup. Use a state directory **outside** its checkout; that checkout holds the profile, prior briefs, and state. A claim in Git's common directory prevents two port standup runs from gathering/persisting concurrently. The claim is released on normal report or handled failure, and a hard-killed run needs explicit reconciliation. This claim does not coordinate with an independently running Archon standup.

```bash
uv run .tools/bin/dagu start workflows/standup-live.yaml -- \
  project_dir="$PWD" \
  state_dir="/absolute/runs/standup-001" \
  repo="/absolute/checkouts/widgets-dev" \
  config="config/standalone.local.json"
```

## Retry, questions, and cleanup

Cancellation is forwarded from the Python step to the running command process group. The original validation runner also stops its check process tree on termination. A cancelled/interrupted attempt remains journaled for reconciliation.

Every stage has an atomic output receipt and a started journal entry. Retrying a successful step reuses and revalidates its receipt, rather than repeating agent or forge effects. Reusing a state directory with different inputs/config is refused. A started stage without a certified result is ambiguous: the process may have committed, written labels, or persisted part of standup state. The port stops instead of replaying it. Inspect the stage's effects, then start a fresh run, or explicitly reconcile and clear the affected journal entry and failure report before a deliberate retry. Do not blindly remove those files.

A live blocked investigate/plan/triage/implement run reaches a root `human.task` with a required ruling. The original result stays in `report.json`. Completing that task records the ruling; it does not edit inputs or rerun work. Start a new run with the ruling included in `input`. This is a concession from Archon's richer attention/recommendation continuation, not feature parity. The stage graphs contain no child human tasks.

Worktrees and implementation branches are retained for inspection and handoff. Remove a finished advisory worktree using `git -C /absolute/checkouts/widgets worktree remove /absolute/runs/investigation-001/checkout`. Preserve implementation commits before cleanup. `make clean` refuses to remove `.runs` while it contains registered Git worktrees; resolve them first. No remote branches are deleted.

## Fidelity matrix

| Behavior | Status | Evidence / concession |
|---|---|---|
| Original prompts and JSON schemas | Preserved | Byte-identical prompt copies; source hashes and generated drift check; full JSON Schema validation including triage union branches |
| Investigation, validation and triage result rules | Preserved with validation-summary concession | Original pinned scripts execute; a red validation result uses runner facts rather than classifier prose, retaining the classifier's cause as an agent assessment and its raw analysis in `nodes/classify.json` |
| Implementation sessions and five-turn bound | Preserved with reporting concession | Fresh CLI process per executed turn, artifact/commit handoff, skip after `done`; cap exposed as completed workflow with false business outcome |
| Parallel standup facts and state parser | Preserved | Three DAGU siblings; original reader/persist parser including JSON-wrapper fallback; GitHub facts mocked in fixtures |
| Advisory checkout contract | Adapted | Dedicated worktrees plus after-the-fact content checks; no Archon container policy or preventive filesystem/network isolation |
| Human questions | Adapted | Root task records ruling; explicit new run rather than Archon's full attention continuation |
| Model/provider routing, token accounting | Not ported | Configured CLI; no equivalent claim |
| Worktree lifecycle | Adapted | Explicit worktree creation; retained for operator inspection, no Archon automatic lifecycle or distributed ownership |
| Retry/recovery | Conservative concession | Successful receipts reused; uncertain attempts require reconciliation rather than automatic replay |
| Live agents, real label writes, live standup | Not established | Controlled CLI tests and fixtures; needs disposable-repository/operator trials |
| Native DAGU scheduling | CI requirement | All twelve previews plus all 36 fixture executions; no local-runner substitution in native job |

Validation has two different non-green states. A command that **starts and fails**
produces `red` and is classified as introduced, inherited, or environment. A command
that **cannot start**, or a gate that times out, is `incomplete`; its classifier
does not run. Do not relabel an unstartable command as `environment` to satisfy an
acceptance checklist. `validation.md`, `validation/*.log`, `nodes/discover.json`
and `nodes/run.json` are the execution evidence. Classifier prose is not proof of
the command, exit code, or cause. The final red summary preserves the runner's
facts and labels the cause as an agent assessment; the raw analysis is retained
for diagnosis rather than silently discarded.

### Restricted-host test aid

Some execution sandboxes forbid Unix sockets and abort Bun before user code runs. `tests/support/bun_compat.mjs` is a **test-only** Node shim for the small Bun API surface these scripts use. It loads unchanged vendored files with Node's TypeScript transformation and maps `import.meta.dir` in memory. It is not the live default and does not prove Bun/native-DAGU execution. To run local fixtures on such a host, create an ignored config whose `script_argv` is `["node", "--experimental-transform-types", "--import", "/absolute/repository/tests/support/bun_compat.mjs"]`, then set `STANDALONE_FIXTURE_CONFIG` to its path when running `make standalone-scenarios`. CI uses the real Bun runtime for the fixture suites; unit tests also exercise the explicit shim.


## Shared agent selection and runtime

These workflow types remain supported; only delivery's separate dry variants were removed. Live runs using the built-in config inherit `make configure-agent` selections from `config/commands.local.json` if that file exists. Explicit workflow-specific config paths keep their own agent settings. The runtime selects the pinned scripts' `gh` path and strips inherited Archon CLI/plugin settings. No Archon installation is required. Exact source prompts remain pinned; rendered prompts include DAGU/gh invocation guidance.
