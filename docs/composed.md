# Review, publish, ship, upkeep, and approved issue replies

These six ports address issue #3 on top of the standalone building blocks from #2. Both batches use Archon commit `72817c50dc51bb91773f71e5448bb7d387bfc8dd`. Every workflow has separate `*-fixture.yaml` and `*-live.yaml` entrypoints. They do not merge pull requests.

## Developer behavior and prompts

| Workflow | Stages | What its original prompts ask for |
|---|---|---|
| `review` | scope → fix reviewed commit/mode → route → parallel selected lenses → synthesis → canonical comment → result/cleanup | Verify the contract and PR head first. Review seams, code, tests, errors, and docs as selected; verify findings adversarially; report missing coverage; preserve prior findings on continuation. |
| `simplify` | structure review → scratch cleanup | Prove a smaller design preserves the accepted outcome. Recommend changes in `shape.md`; edit no delivered code. |
| `pr` | forge check → prepare intent → publish/read back | Choose the qualified target, head/base, title, and artifact-backed body. The script owns pushing, creation/reuse, optional managed description, and verification. |
| `ship` | forge → triage → optional investigation or intel/planning → reconcile caller/triage PR → delivery → source outcome/report | Recheck inherited issue claims, choose the least speculative route, then deliver only a direct/continue route, rooted investigation, or executable plan. |
| `upkeep` | forge → dependency assessment → optional delivery → outcome | Inspect locked/current versions, affected usage, breaking changes and alternatives. Update one dependency with its package manager and lockfile, or explain why no update is owed. |
| `issue-response` | classify → investigate/draft → snapshot → root approval → exact publication | Skip unsuitable issues. For actionable bugs, draft an evidence-backed response without editing code or writing to GitHub. Publish only the exact approved response. |

Exact copied prompts are in [`prompts/composed`](../prompts/composed). `COMPOSED_SOURCE.json` records the source node, dependencies, conditions, schemas, include bindings, and prompt/script definitions. The SDLC files are already covered by `SOURCE.json`; the additional proactive example has its own pinned hash. The compiler expands triage, investigation, and planning includes into visible DAGU steps. Ship/upkeep reuse the existing delivery controller with its original four-round reducer and fixture/live adapters.

## Reproducible examples

```bash
uv sync --frozen
make tools
make composed-demo
make composed-demo COMPOSED_WORKFLOW=ship COMPOSED_CASE=plan
make composed-demo COMPOSED_WORKFLOW=review COMPOSED_CASE=light
make composed-demo COMPOSED_WORKFLOW=pr COMPOSED_CASE=uncertain
make composed-demo COMPOSED_WORKFLOW=issue-response COMPOSED_CASE=reject
make composed-scenarios
make composed-native
```

Task exposes the same commands and variables:

```bash
.tools/bin/task composed-demo COMPOSED_WORKFLOW=upkeep COMPOSED_CASE=already-current EXECUTOR=dagu
```

There are 39 new scenarios. Native CI previews all twelve entrypoints and executes every fixture through DAGU, using Bun for the original TypeScript scripts. The local command harness runs the same commands/dependencies but is not DAGU. On restricted hosts, `COMPOSED_FIXTURE_CONFIG=config/standalone-node.local.json` can select the explicit test-only Node shim described in [standalone testing](standalone.md#restricted-host-test-aid). The local harness refuses workflows containing approval gates; it cannot silently approve them.

Fixtures replace model responses, forge preflight, PR publication effects, and GitHub targets. Review fixtures still execute the original review-mode, working-diff publication/cursor, inline result, and scratch cleanup scripts. Ship/upkeep fixtures execute the existing delivery controller and original reducer/report scripts. They never contact GitHub. `external_effects: simulated` identifies these runs.

The offline project at [`examples/projects/dependency-update`](../examples/projects/dependency-update) uses a local npm file dependency. A controlled test installs it offline, upgrades the dependency to a breaking API, verifies the old consumer fails, repairs the consumer, and verifies both the test and updated package lock. This proves local upgrade/check mechanics; it does not prove an LLM selected the right upgrade or fix. Fixture cases labelled breaking-upgrade/lockfile simulate the workflow's decisions.

## Live operation

Copy `config/composed.json` to ignored `config/composed.local.json`. The agent CLI reads the rendered prompt on stdin and returns the original stage output directly: JSON where the source declares a schema, raw text for review lenses/intel. There is no provider-envelope repair, automatic model selection, or permission bypass. Configure authenticated `gh` or Archon's forge source yourself. Live model/forge behavior is experimental; fixture success does not establish live parity.

```bash
uv run .tools/bin/dagu start workflows/review-live.yaml -- \
  project_dir="$PWD" state_dir="/absolute/runs/review-001" \
  repo="/absolute/checkouts/widgets-feature" scope="42" \
  config="config/composed.local.json"

uv run .tools/bin/dagu start workflows/ship-live.yaml -- \
  project_dir="$PWD" state_dir="/absolute/runs/ship-001" \
  repo="/absolute/checkouts/widgets" input="Address issue #42" \
  config="config/composed.local.json"

uv run .tools/bin/dagu start workflows/upkeep-live.yaml -- \
  project_dir="$PWD" state_dir="/absolute/runs/upkeep-001" \
  repo="/absolute/checkouts/widgets" input="Assess and update the vulnerable dependency" \
  config="config/composed.local.json"
```

Ship/upkeep require an explicit request and create a new branch/worktree from the clean target checkout. Review/simplify/PR use a detached worktree at its HEAD. Standalone review defaults its scope to the target checkout's branch, when one exists; a requested PR whose head differs returns `ask` before lenses/publication. Fetch/advance the target yourself, then start a new run. PR creation passes the original branch explicitly to the publisher; pass `branch` yourself when the source checkout is detached. Review/simplify accept `input` as the work order. `base_branch` defaults to `main` for the simplify prompt and can be overridden.

For continuation review, pass an absolute `prior_report` path whose sibling `reviewed-head` was written by the previous publication. The original mode script verifies ancestry; `light=true` on a continuation selects only code. The original publisher rechecks the checkout and remote head before writing, stamps the reviewed commit, and updates one canonical marked comment. Its documented upstream risk remains: a write with a lost/transient response can leave two comments; the next upsert refuses duplicates and requires reconciliation.

PR options are `draft=true`, `publish_description=false`, `pull_request`, and `branch`. Ship additionally forwards `publish`, `part`, `errors`, `pull_request`, and `branch`. A caller's PR and triage's different PR refuse before delivery. Upkeep forwards `errors`. Triage label publication remains opt-in.

Ship/upkeep's compact delivery step uses `config/commands.json` as its transport map and the composed config's `agent_argv`. Optional `delivery` settings in the composed config override that map/settings for an operator's adapter. `delivery_timeout_seconds` defaults to 86400; advisory agent timeout defaults to the existing 3600 seconds. These operator limits are runtime concessions. Delivery artifacts are retained in `state_dir/delivery/`; advisory reports stay at the parent root, with explicit absolute paths in the work order. This differs from Archon's single artifact store. Do not use a test transport as evidence of real delivery.

## Approved issue responses and event input

```bash
uv run .tools/bin/dagu start workflows/issue-response-live.yaml -- \
  project_dir="$PWD" state_dir="/absolute/runs/response-001" \
  repo="/absolute/checkouts/widgets" repository="owner/widgets" issue_number="42" \
  config="config/composed.local.json"
```

`approval.json` contains the qualified repository, issue number, and exact draft. Its digest is saved before the root DAGU approval gate. Approve in DAGU's UI/API to permit publication; reject ends the DAGU run without posting. This is DAGU `Rejected`, rather than Archon's `cancel` result. A classifier skip skips the gate and post; the success handler records the no-op report. On rejection, DAGU retains the rejection record and approval snapshot; downstream report/publication steps do not run.

Publication verifies the snapshot, current draft, and target still agree, then passes the original bytes directly to `gh` as an argv value. Shell-looking text is never evaluated. The publisher has a started journal and success receipt. If posting may have landed, it stops for reconciliation instead of automatically repeating the comment. `--approved` is the explicit operator entrypoint used by the downstream DAGU step, not a cryptographic authorization boundary. Run the live file through DAGU to obtain the approval gate; invoking the CLI manually with that flag is a deliberate manual approval. Checkout checks and worktrees are not a security sandbox for an agent with credentials.

[`scripts/issue_event.py`](../scripts/issue_event.py) converts a **trusted** GitHub issues/opened JSON event to explicit `repository` and `issue_number` parameters:

```bash
uv run python scripts/issue_event.py event.json \
  --repository owner/widgets --output normalized-event.json
```

It refuses a different repository and filters edits/PRs. It does not run an HTTP server, verify webhook signatures, enqueue DAGs, or deduplicate deliveries. An authenticated upstream webhook/action must perform those duties and launch a unique run. This is the trigger-adapter concession; the source example also depends on separately installed trigger bindings. No schedule or unattended live binding is installed by this PR.

## Recovery and fidelity

The same explicit worktree retention and human-ruling/new-run approach from [standalone operation](standalone.md#retry-questions-and-cleanup) applies. Stage receipts avoid replaying completed work. An interrupted journal entry refuses another attempt. Inspect GitHub, the checkout, `effects/`, source publication records, and `delivery/` before starting another run; a new state directory alone does not prove an uncertain write did not land. A failed nested delivery retains its original report and makes the parent fail after relaying that report.

| Surface | Preserved | Concession / evidence limit |
|---|---|---|
| Prompts, schemas, conditions, includes | Pinned source definitions and explicit input bindings | DAGU steps record source skips as null receipts; the command step can be green while the business result is negative |
| Parallel review and continuation | Selected lenses, exact reviewed commit/cursor, original publication/result scripts | Failed selected lenses are disclosed and force not-ready; native fixture runs use working-diff publication, not GitHub |
| Canonical review comment | Unchanged original marker upsert and head checks | Controlled local `gh` tests verify POST→PATCH and stale-head refusal; no real GitHub publication is claimed |
| Simplify cleanup | Original registered-worktree removal on success/failure | Parent worktrees remain for inspection; no Archon lifecycle/worker ownership service |
| PR create/reuse/uncertain outcome | Original publisher used in live mode; durable receipts/uncertain journal | Fixture publication is simulated; original real push/create/recovery is not end-to-end validated |
| Ship/upkeep routes and spend gates | Original child verdicts, continues/outcome/report scripts, existing delivery reducer | Includes expanded into parent steps; delivery uses a nested artifact directory and compact controller |
| Dependency upgrade | Original assessment/work order and lockfile requirements | Local offline npm regression proves mechanics; model choices and remote package/advisory lookups untested |
| Human approval | Saved exact target/draft, native approval before any post, tamper checks | Reject lifecycle differs; live gate resume/reject needs an operator trial |
| Triggers and cross-run recovery | Explicit event normalization, no automatic replay of uncertain effects | No hosted webhook, signature checking, delivery deduplication, queue state, provider/accounting parity or distributed recovery claim |

No real model or public forge operation runs in CI. Controlled transport doubles and offline examples are labelled as such. The repository's existing 104 delivery scenarios, 36 standalone scenarios, and 4096 reducer comparisons remain required checks.
