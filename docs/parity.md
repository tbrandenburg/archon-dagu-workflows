# Fidelity and current limitations

The delivery business rules are based on pinned Archon source. Original prompts, reducer, outcome/reporting and live publication/thread scripts are retained. This does not establish full runtime or feature parity.

| Area | Current implementation |
|---|---|
| Business verdicts and four-round cap | Original `round.ts`; 4096 generated decision comparisons |
| Review, CI, thread corrections and discoveries | Fixture-tested across both live entrypoints with explicit test transports |
| Independent review | Simple runs selected lenses sequentially; detailed exposes parallel DAGU steps |
| Models/providers | Configurable fresh CLI calls; not Archon's aliases, usage accounting or full provider layer |
| Reviewer isolation | Instructions plus after-the-fact checkout checks; not complete preventive sandboxing |
| Human continuation | Root human task, finish or request changes; no reproduction of the attention agent's recommendations/manual-ready action |
| Recovery/publication | Live PR create/reuse and comment recovery evidence exists; ambiguous writes require operator reconciliation. Delivery crash recovery remains unaccepted; see [supported scope](/docs/recovery.md) |
| Distributed execution | Not implemented for shared checkout/artifact transfer; intended for one host |
| Live end-to-end operation | Experimental; CI never runs real agents or GitHub mutations |

A head race during reshape re-review fails closed for reconciliation, where Archon can return a typed ask result. Human-authorized batches have separate artifact directories and are not identical to Archon's continuation storage.

DAGU requires human tasks at the root, and children need explicit working directories and artifact paths. Those are structural constraints, not blockers for the delivery loop. The repository uses explicit root tasks and path parameters.

The source contains a stale reporting caveat saying forge review threads are not checked, although its executable thread script supports forge operations. The pinned source is preserved and the inconsistency is disclosed.

## What each test proves

- `test`: fast contracts, typed booleans, original decisions, artifact escape rejection, dry boundary and source integrity.
- `parity`: 4096 combinations checked against original reducer code.
- `scenarios`: 26 scenarios × two live entrypoints executing the actual YAML commands with a local dependency harness. Real-mode external effects are explicitly mocked and reports are marked simulated.
- `validate`: actual DAGU binary validates three definitions (two entrypoints plus the shared child) and previews both live entrypoints. Previews do not run stage commands.
- `native-smoke`: actual DAGU scheduling of the same simple/detailed live entrypoints with mock effects for ready, CI repair and simplify/re-review. No local-harness substitution is permitted.

Native engine CI is valuable evidence for orchestration, not proof of a live coding agent's judgments, GitHub behavior, crash recovery or human resume semantics. Further disposable-repository tests are required before unattended live use.

Round exhaustion and other not-ready outcomes are covered by the local command scenarios, including their waiting human task. Native **delivery** finish/request-changes semantics still need an operator trial; native issue-response wait/reject/approve and standalone ruling/new-run behavior have been exercised separately. Standalone/composed fixture/live workflows remain available; only `simple-dry` and `detailed-dry` delivery entrypoints are removed. See [standalone](/docs/standalone.md), [composed](/docs/composed.md), and [acceptance evidence](/docs/live-acceptance.md). Closing the scoped acceptance issues does not certify unattended operation or the untested delivery protocol.

The DAGU port selects the original GitHub CLI path explicitly. Archon application/CLI/plugin services are not dependencies. Exact upstream prompt files remain unchanged; rendered prompts append DAGU runtime guidance overriding Archon CLI and rerun examples.
