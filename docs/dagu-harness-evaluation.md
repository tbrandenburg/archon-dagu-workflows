# Native Dagu OpenCode harness evaluation (issue #22)

## Recommendation: do not adopt on Dagu 2.24.0

Keep `archon_dagu.opencode` on the `investigate-live` path. Direct `dagu start`
cannot run a managed OpenCode session on this pin. Its CLI fallback neither
extracts the final assistant answer nor performs the repository's V2
session-specific interrupt and idle verification. A naive rendered-prompt handoff
also expands operator text a second time. These are behavior changes, not reasons
to relax certification or cancellation safeguards.

This evaluation changes no production adapter, generator, workflow or config.
The experiment uses the actual investigate prompt renderer and source schema,
then executes a **transport-only candidate** through actual Dagu with a controlled
OpenCode-shaped executable. It is not an end-to-end `investigate-live` run, a real
provider invocation, or evidence that an agent produced a valid diagnosis.
Concrete runtime incompatibility is the acceptance alternative used here.

## Versioned research

The installer pins `2.24.0` in `/scripts/install_tools.py:12`. The official tag
resolves to commit `684692b1e307e86f7f65b6a547304ede15d5784e`.
Inspect the immutable source, not just the current documentation:

- [Provider invocation](https://github.com/dagucloud/dagu/blob/684692b1e307e86f7f65b6a547304ede15d5784e/internal/runtime/builtin/harness/provider.go#L33-L85):
  OpenCode is `opencode run <prompt>`; supplementary input is separate stdin.
- [Execution topology](https://github.com/dagucloud/dagu/blob/684692b1e307e86f7f65b6a547304ede15d5784e/internal/runtime/builtin/harness/harness.go#L316-L377):
  `managed: true` requires a server/worker host; automatic mode can fall back
  before creating a session. The CLI path resolves the executable from PATH.
- [CLI environment and working directory](https://github.com/dagucloud/dagu/blob/684692b1e307e86f7f65b6a547304ede15d5784e/internal/runtime/builtin/harness/harness.go#L427-L456)
  and [process/output handling](https://github.com/dagucloud/dagu/blob/684692b1e307e86f7f65b6a547304ede15d5784e/internal/runtime/builtin/harness/harness.go#L835-L894).
- [Managed timeout](https://github.com/dagucloud/dagu/blob/684692b1e307e86f7f65b6a547304ede15d5784e/internal/runtime/builtin/harness/opencode_managed.go#L139-L146):
  calls abort with a three-second deadline, discards its error and marks the
  session aborted without a subsequent idle-verification request.
- [Managed API client](https://github.com/dagucloud/dagu/blob/684692b1e307e86f7f65b6a547304ede15d5784e/internal/runtime/builtin/harness/opencode_client.go#L159-L180)
  and [abort](https://github.com/dagucloud/dagu/blob/684692b1e307e86f7f65b6a547304ede15d5784e/internal/runtime/builtin/harness/opencode_client.go#L259-L270):
  uses V1 paths `/session`, `/session/{id}/abort`, `/session/status`, and `/event`.
  This does not implement the V2 contract used by our adapter.

Targeted official web research covered [Dagu's OpenCode
harness](https://docs.dagu.sh/step-types/harness/opencode) and the [OpenCode V2
API](https://opencode.ai/v2/docs/api). The Dagu page explicitly names OpenCode
v1.18.11 as its tested managed release and describes direct CLI fallback. The V2
API documents `/api/session/{id}/interrupt` and
`/api/experimental/session/{id}/wait`, which waits for the agent loop to become
idle. Context7 queries against `/dagucloud/dagu` and `/websites/opencode_ai/v2`
corroborated the topology and wait semantics. Context7's Dagu results reference
`main`, not the pin; its interrupt excerpts include conflicting response shapes.
Use pinned Dagu code and official V2 API documentation to resolve those limits.

## Behavior comparison

| Behavior | Current investigate adapter | Pinned native harness candidate |
|---|---|---|
| Dynamic source prompt | `Run.agent` renders bound inputs in one substitution pass and saves `prompts/investigate.md` (`/src/archon_dagu/standalone.py:283-327,365-372`). Operator-inserted tokens stay literal. | `with.prompt` can carry multiline text, but the probe's literal `$ARTIFACTS_DIR` is expanded again in both the request text and authoritative inputs. Exact prompt equality fails. A safe file/escaping handoff needs separate proof. |
| Prompt transport | Entire rendered prompt on stdin to the V2 client; large-input regression exists (`/tests/test_opencode.py:94-142`). | CLI prompt is a positional argv entry; observed stdin is empty. `with.stdin` is supplementary, not a substitute for the required prompt. Large argv limits were not tested. |
| Structured answer | `final_answer` selects last-message text and rejects error events or abnormal finish; `Run.agent` parses one JSON object and `Run.check` validates the source schema (`/src/archon_dagu/opencode.py:24-57`, `/src/archon_dagu/standalone.py:221-242,389,479-481`). | `format: json` selects CLI mode and stdout remains the complete JSONL stream, including commentary. Dagu success is not source certification. Applying the existing `final_answer` and schema validator certifies the controlled answer. |
| Sessions | Generates a known ID before create, validates returned ID and binds cwd (`/src/archon_dagu/opencode.py:171-176,196-215`). | Direct-start CLI does not create a known session or add `--session`. Managed mode has Dagu-owned lifecycle state but is unavailable on this execution path and uses a different API. |
| Timeout | Outer standalone timeout forwards TERM, lets the adapter clean up, then escalates; the adapter calls interrupt with `resume=false`, verifies response and waits for idle (`/src/archon_dagu/standalone.py:119-147`, `/src/archon_dagu/opencode.py:126-162,245-269`). | Native two-second timeout fails the step and suppresses partial stdout. No session API call is made. Controlled service-owned work remains active after client termination. Managed-source timeout discards abort failure and does not verify idle. |
| Cancellation / fail closed | Known-session interrupt and idle verification; unverified cleanup emits no answer, returns failure and identifies the session. Covered by `/tests/test_opencode_cancellation.py`. | SIGTERM yields Dagu `Aborted` (CLI exit **0** on this pin), empty step stdout and a stopped client. No interrupt/wait occurs. Do not treat CLI exit alone or client death as successful cleanup of server-owned work. |
| Working directory / isolation | Explicit clean source guard, detached checkout, advisory snapshot verification, and run identity/journal guards (`/src/archon_dagu/standalone.py:373-388,391-420,573-642`). | Explicit step cwd is honored in the controlled run. Harness does not replace checkout creation, read-only snapshot checking, identity locks or uncertain-attempt reconciliation. Managed mode is a shared service-identity boundary, not equivalent isolation. |
| Model / agent / variant | Configured argv supports saved built-in selection and explicit custom override (`/src/archon_dagu/standalone.py:37-54`, `/src/archon_dagu/opencode.py:83-88`). | The three explicit flags arrive unchanged in the controlled executable. Config selection/override translation still requires Python work; no authenticated model/config behavior was exercised. |
| Environment / credentials | Stage binds input, artifact, workflow and stage env; API uses OpenCode's own discovery/authentication without copying credential contents. | Explicit synthetic env reaches the controlled executable. This probe inherits no credential values or service discovery. Managed credentials belong to the service account; step secrets do not configure that server. Actual authentication parity remains untested. |
| Artifacts / report / decision | Nonempty current-run report pointers are checked before node persistence; source verdict script, report and inconclusive decision gate remain (`/src/archon_dagu/standalone.py:225-242,391-482,490-533`; `/workflows/investigate-live.yaml:55-82`). | Stdout capture is not artifact-pointer validation, the verdict script or final reporting. These Python/source-script responsibilities remain. No candidate output is installed as a successful workflow result. |

## Reproduction without external effects

Requires the repository's locked Python environment, installed pinned Dagu,
Linux `ss`, `ps`, and Git. Do not substitute the system OpenCode binary. The probe
creates its own executable shim under the new state directory and rejects a Dagu
version other than 2.24.0.

```bash
uv run python scripts/probe_dagu_harness.py --case jsonl
uv run python scripts/probe_dagu_harness.py --case managed
uv run python scripts/probe_dagu_harness.py --case timeout
uv run python scripts/probe_dagu_harness.py --case signal
uv run pytest tests/test_dagu_harness_probe.py tests/test_opencode.py \
  tests/test_opencode_cancellation.py tests/test_standalone.py
make harness-native                 # pytest -m native; also part of ci-native
# Equivalent native task: .tools/bin/task harness-native
make lint
```

Each invocation prints its unique `.runs/harness-probe/<case>-<id>` evidence
directory. Optional `--state-dir /absolute/new-directory` refuses an existing
directory. Evidence includes the Dagu binary SHA-256/version, port inventory,
rendered/captured prompts, candidate YAML, controlled invocation argv/cwd/env,
raw stdout, validation/start logs, native run history, `evidence.json` and
`cleanup.json`. Port inventory is read-only; the probe starts no TCP service and
does not contact the inventoried listeners. Dagu HOME/XDG/config/data/cache paths
are run-local. Git initialization/commit occurs only in a new disposable repo,
not in the working repository or a shared worktree.

Observed expected results:

| Case | Validate exit | Start exit / native result | Discriminating evidence |
|---|---|---|---|
| `jsonl` | 0 | 0 / Succeeded | Source certification false (`Extra data`), existing adapter certification true, prompt equality false. |
| `managed` | 0 | 1 / Failed | `managed OpenCode requires a Dagu server or worker execution host`; controlled CLI never starts. |
| `timeout` | 0 | 1 / Failed | Two-second deadline, empty step stdout, no API calls, simulated service-owned work still busy. |
| `signal` | 0 | 0 / Aborted | Controlled client receives TERM, empty step stdout, no API calls, simulated service-owned work still busy. |

The timeout/signal probe owns a separate session-labelled worker process whose
heartbeat models work owned by a persistent service rather than the client
process group. Its controlled session interrupt can stop that exact worker.
This is a cancellation **contract probe**, not a real OpenCode server test.
The probe terminates/reaps its worker after recording observations and reaps its
Dagu process; pytest also checks that the cancelled client is no longer active.
No provider, public forge operation, global config change, or name-based process
kill is involved. Do not interpret the controlled heartbeat as proof of a
particular real provider's post-cancellation behavior.

Five focused pytest cases cover the four actual-start paths plus source renderer
and certification guards (invalid verdict, foreign run ID and empty report).
The four actual-start cases have a registered `native` marker, excluded by default
pytest options. `make harness-native` / `.tools/bin/task harness-native` explicitly
select them with `pytest -m native`; both `ci-native` entrypoints include that gate.
The portable renderer guard remains in default pytest and requires neither Dagu
nor Linux `ss`/`ps`. This is suite routing, not conditional skipping.
These use the existing pytest framework; they do not add a new runner or alter
production output validation. The default targeted suite above passed 60 tests;
`make harness-native` passed four native cases. `make ci`
also passed: 173 default pytest cases, 4,096 reducer comparisons, 52 delivery, 36 standalone
and 39 composed local scenarios, Ruff lint/format checks, 186 pinned-source hashes
and generated-file drift checks. The four harness cases are actual native Dagu
runs; the 127 scenario runs are local command checks, not native execution.

## Smallest viable migration and remaining evidence

There is no contract-preserving drop-in migration on this pin. Calling the
existing adapter as a custom harness would retain its responsibilities, not
remove it, and does not resolve prompt transport/re-expansion by itself.

Before considering another version/topology, independently prove:

1. An exact-byte dynamic prompt handoff, including literal interpolation tokens
   and large prompts, without command execution or an additional expansion pass.
2. A V2-capable native integration with known-ID creation reconciliation,
   session-specific `resume=false` interrupt, idle verification, bounded cleanup,
   and explicit unverified status when abort/wait fails or the host disappears.
3. Native timeout and operator cancellation through the intended launch topology,
   including final-output/cancellation races; controlled subprocess death is not
   enough to certify a persistent server idle.
4. Final-message selection and schema/artifact certification before persisting a
   node or reporting success; preserve the existing failure journal and snapshots.
5. Explicit translation of configured model/agent/variant/custom agent selection,
   input/stage env and service credential boundaries without global writes.

A future investigate-only prototype would split Python prompt preparation from
output certification, retain initialization/locks/journals/snapshot checking and
the verdict/report/human gate, then change only the investigate step in
`/scripts/generate_standalone.py` and regenerate its YAML. It would require
workflow-local harness configuration, updated `/docs/agents.md` and
`/docs/standalone.md`, README guidance, and the same focused cancellation/schema
contracts. Do not migrate other workflows or remove `opencode.py` until those
proofs exist. Managed server execution, real-provider authentication, and real
provider cancellation were intentionally not exercised; they are follow-up
acceptance evidence for a separately approved migration, not blockers to this
pin-specific do-not-adopt conclusion.
