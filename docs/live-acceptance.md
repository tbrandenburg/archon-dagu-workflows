# Live PR, review, and validation acceptance

Live acceptance is an operator-run evidence campaign, not a fixture or a claim
that the workflow is ready for unattended writes. It may push branches, open or
update PRs/comments, and incur provider charges. Do not merge any test PR.

## Standing authorization and safety bounds

Live runs are authorized at any time for repository work and validation, including
real provider calls and workflow-owned GitHub writes. No additional per-run owner
approval, campaign authorization, or provider spending ceiling is required.
Configured provider charges and subscription usage are permitted without a
repository-imposed dollar ceiling. This policy supersedes historical campaign
restrictions, including the preflight record below. It does not bypass workflow
human-decision gates, credentials, target permissions, or accepted work scope.

Before the first model-backed run, record in a unique ignored
`.runs/issue16-*` directory:

- UTC deadline and maximum run attempts per matrix case;
- the effective configured provider/model and any optional run-specific budget;
- repository identity, disposable branch, base/head SHA, and exact intended
  GitHub writes;
- DAGU, agent CLI, `gh`, Bun and workflow revision; do not copy credentials;
- baseline checks and a read-back/cleanup plan for every test-owned artifact.

Use `tbrandenburg/playground` artifacts with a unique, conspicuous issue16 test
prefix. Inspect existing branches/PRs first. Do not reuse or clean up anything
that cannot be positively identified as created by this campaign. Preserve the
run directory and all reports before closing test PRs/issues or deleting owned
branches. Never merge.

Stop without a provider call if the configured model is unavailable,
authentication/target permissions are uncertain,
the disposable target cannot be identified, or evidence storage is unavailable.
An execution cap alone is not a provider spending cap; a dollar ceiling is optional.
Do not substitute a
fixture, manually perform a workflow-owned GitHub write, or change models after
a failed call and count that as live acceptance.

## Native run evidence

Use fresh absolute state directories and native DAGU, not `dagu dry` or the local
fixture harness. Current project examples use `uv run .tools/bin/dagu start`
with the relevant `*-live.yaml` entrypoint. Save the exact command, complete
rendered prompts, typed listings, agent tool-call trace, step statuses, report,
and relevant receipts. Sanitize credentials and personal data from retained
traces. Distinguish DAGU lifecycle status from the workflow's business result.

Git worktrees do not inherit ignored `.tools/` binaries or `config/*.local.json`.
Before a campaign launched from a worktree, install the pinned tools there and
explicitly select/verify the effective agent configuration; do not assume the
coordinator checkout's ignored config is present. Never copy provider credentials
into the run directory.

| Case | Independent acceptance evidence |
|---|---|
| PR create | Workflow-owned push/create; independently read back repository, PR number, head/base, exact head SHA and draft state. |
| PR reuse | A second unchanged run reuses the exact open PR; independently query the head and verify no duplicate. |
| Full review | Normal non-continuation review reaches a justified ready result; retain route, every selected-lens status, typed listing, synthesis prompt and report. A forced override is failure. |
| Review continuation | After a small correction, continuation uses the prior report/cursor and updates the same canonical comment ID; independently read the comment. |
| Stale-head refusal | Advance only the disposable remote head after review scope is captured. Verify publication refuses the stale certification and makes no incorrect write. Preserve and reconcile the test-owned head. |
| Real validation | Through the live validate workflow, run an actual passing check, a deliberately failing check, and an unstartable/environment check. Retain declared argv, exit codes/logs and classification. Red or environment failure must not become green. |

For each row record: run ID; exact command; start/end HEAD; expected and
observed business outcome; report/receipt paths; GitHub or process-level
read-back; and cleanup disposition. A missing deterministic setup is a blocked
case, not a simulated pass. If a result is ambiguous, inspect GitHub and the
retained effects before any retry.

## Historical preflight record (2026-10-29)

The issue authorizes disposable GitHub artifacts in `tbrandenburg/playground`;
no artifact was created by this preflight. GitHub CLI authentication and access
to the repository were confirmed, but no live write was attempted.

Context7 was attempted for Dagu documentation and returned its monthly-quota
error. The current official [Dagu CLI reference](https://docs.dagu.sh/getting-started/cli)
documents `dagu start [options] DAG_NAME_OR_FILE [-- PARAMS...]`, plus run status
and history commands; official workflow guidance distinguishes `dry` (plan
preview) from `start` (execution). The project pins Dagu 2.24.0
(`docs/standalone.md`); the official [Dagu v2.24.0 source/release](https://github.com/dagucloud/dagu/releases/tag/v2.24.0)
was located. Exact pinned CLI help/source was not locally available, so the
current web reference is not treated as version-specific evidence.

This preflight ran from the isolated `.worktrees/issue-16` checkout. Its ignored
`.tools/` and `config/*.local.json` were absent; the coordinator checkout has the
pinned `.tools/bin/dagu` and an ignored local agent config. The campaign must
verify its actual project/config root rather than infer the coordinator's setup.

`make doctor` in the issue worktree reported the built-in `config/commands.json`, agent command
`python -m archon_dagu.opencode --agent build`, and model “inherited from
OpenCode”; it explicitly said authentication/model access was unverified. The
local `.tools/bin/dagu` executable was absent there. `opencode models` listed
multiple providers/models but did not establish which model the issue worktree
would use. Therefore no provider spend could be bounded for this campaign. These
are preflight stop conditions, not workflow defects.

**Historical campaign disposition:** deadline 2026-10-29 23:59 UTC; at most one
attempt per case; recorded provider spending ceiling: **$0**. No paid model calls
or live workflow runs occurred in that preflight. Its matrix cases were
**not run / blocked by preflight**; this is not acceptance evidence or a current
restriction on live runs. New runs use the standing authorization above, verify
the configured provider/model and pinned DAGU, and record a deadline and attempt cap.

Detailed preflight command/output evidence is retained in the ignored run
directory `.runs/issue16-20261029-preflight/`.

## Measured evidence and reduced acceptance scope

The preflight above was superseded by an owner-authorized live campaign using
`openai/gpt-6-luna`, without a dollar ceiling. It remains a historical no-spend
record, not the current campaign result. The owner subsequently authorized a
simpler closure scope: **operator-supervised PR/review/validation, explicit
reconciliation, no unattended-write certification**. This changes acceptance
expectations, not the pinned business rules or readiness checks.

The original campaign's sanitized index is retained in
`.worktrees/issue-16-live/.runs/issue16-live/final-matrix.json`; each case directory
contains its exact command, native run ID, reports and read-back. The index's
early path diagnosis is superseded by the corrected diagnosis here: the agent
read `typed/nodes/code.json`, but the existing record was `nodes/code.json`.

| Live case | Native run ID | Observed result |
|---|---|---|
| Workflow-owned PR create | `034oUK0jKylzV8ckvugsuD` | Draft PR #203 created at `db1db31f036837ec71f3e125a255336eefae0e13` |
| Workflow-owned reuse | `034oUMGEAA1tgnR6dqQMpN` | Same PR, no duplicate |
| Full review | `034oUNzj4jp2AUE2Vo34PM` | Justified ready at that head; canonical comment `6506450826` |
| Continuation | `034oUUw6n2EQl9TVhfuqvr` | Same comment ID updated; not-ready due to incorrect artifact-path read |
| Post-guidance continuation | See retained `pathfix-continuation-20261029T202500Z` report | Correct `nodes/code.json` read and ready; no prior comment existed for this run |
| Passing validation | `034oT5uAlmbTzWUe2fgwfm` | Actual check passed |
| Deliberately red validation | `034oUh0cjaiDtiPFDXcXaC` | Non-green, actual exit 1; classifier invented a different command/exit. Final-summary hardening now preserves runner facts; no new model classification is claimed |
| Unstartable validation | `034oUiqChFjjwg3Y5uiap8` | Incomplete/non-green, as the source runner specifies; not a completed red environment classification |

The original stale trial advanced the head before valid scope capture and did
**not** test publication refusal. A separate controlled-input integration probe
in `.runs/closure-campaign/20261030T062314Z/` captured a valid old-head scope,
successfully published and updated one canonical comment, advanced only its
disposable source branch, waited for GitHub's PR-head read-back, then invoked the
unchanged publisher from the old checkout. It refused with “not pushed”; the
complete comment read-back was unchanged. This used real Git/GitHub and the
original publisher, **not native DAGU or a model review**.

The same probe created real draft PR #209 while a one-use wrapper forwarded
`gh pr create` and discarded its successful response. The composed stage refused
replay. After independent remote read-back, an explicit operator reconciliation
invoked the original publisher, which reused #209. This is not an automatic
recovery recipe or delivery-protocol interruption evidence.

`validation-evidence-replay.json` in that directory records the retained live
runner/classifier inputs passed to the hardened final result stage: non-green,
actual exit 1, raw inaccurate analysis retained and labelled unverified. It is an
evidence replay, not a fresh provider-backed classification trial.

A new native light continuation, `closure-continuation-20261030T062426Z`, used the
same model and the corrected artifact paths. It updated existing canonical
comment **6516435845** on #209 without a duplicate. Its prior report was the
explicitly controlled publisher probe, not a previous live model review. It
remained **not-ready**: synthesis compared producer path `code` to mode path
`mode` instead of comparing their shared empty include prefix. The saved
`typed/root.json`, `nodes/code.json` and `status/code.json` establish that the
selected lens was present and succeeded. A local runtime clarification now
explains sibling-node identity and still requires the correct lens, loop path,
current-run listing and readable record. No subsequent paid run verifies that
clarification; no readiness override or guaranteed-model-readiness claim is made.

PR #203 was closed without merging and its branch/comment removed after evidence
capture. PR #209 was also closed unmerged; its remote/local test branch and
canonical comment were removed after read-back. The two owned worktrees were
removed only after preserving commit history in `owned-commits.bundle`.
`cleanup-result.json`, the before/after GitHub reads and native continuation
results remain alongside `inventory.json` and `results.json`. Preserve that
evidence until diagnosis is finished.

The original six-row matrix is a stronger future campaign, not a claim that each
row passed as originally specified. See [recovery and exclusions](/docs/recovery.md)
before treating closure of #16/#18 as a prerequisite for #17 or #19.
