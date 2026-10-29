# Live PR, review, and validation acceptance

Live acceptance is an operator-run evidence campaign, not a fixture or a claim
that the workflow is ready for unattended writes. It may push branches, open or
update PRs/comments, and incur provider charges. Do not merge any test PR.

## Safety gate and campaign bounds

Before the first model-backed run, record in a unique ignored
`.runs/issue16-*` directory:

- UTC deadline and maximum run attempts per matrix case;
- the explicit provider/model and an enforceable total spending ceiling;
- repository identity, disposable branch, base/head SHA, and exact intended
  GitHub writes;
- DAGU, agent CLI, `gh`, Bun and workflow revision; do not copy credentials;
- baseline checks and a read-back/cleanup plan for every test-owned artifact.

Use `tbrandenburg/playground` artifacts with a unique, conspicuous issue16 test
prefix. Inspect existing branches/PRs first. Do not reuse or clean up anything
that cannot be positively identified as created by this campaign. Preserve the
run directory and all reports before closing test PRs/issues or deleting owned
branches. Never merge.

Stop without a provider call if the selected model or budget cannot be pinned,
the budget cannot be bounded, authentication/target permissions are uncertain,
the disposable target cannot be identified, or evidence storage is unavailable.
An execution cap alone is not a provider spending cap. Do not substitute a
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

## Preflight record (2026-10-29)

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

**Campaign disposition:** deadline 2026-10-29 23:59 UTC; at most one attempt per
case; total provider spending ceiling for this campaign: **$0**. No paid model
calls and no live workflow runs are authorized under that ceiling. All matrix
cases remain **not run / blocked by preflight**; the campaign must not imply
acceptance. Begin a new bounded campaign only after pinning a provider/model,
setting a positive explicit spend ceiling, installing/verifying pinned DAGU,
and recording a new deadline and attempt cap.

Detailed preflight command/output evidence is retained in the ignored run
directory `.runs/issue16-20261029-preflight/`.
