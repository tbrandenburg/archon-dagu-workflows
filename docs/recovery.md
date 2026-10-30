# Operator-supervised operation and reconciliation

## Accepted scope

One host, one explicit operator-owned run at a time per target repository, trusted
accepted work, disposable/isolated checkout, no merge, no deployment, and **no
automatic replay of an uncertain write**. The operator owns the run until it is
terminal or explicitly abandoned, including while it waits for a decision. This
is an operating policy, not a new enforced cross-run lock or security sandbox.

The scoped #16/#18 acceptance establishes measured publication/validation and
human-gate behavior, not universal crash recovery. PR #20 carries the timeout and
runtime guidance changes; issue closure does not mean that PR was merged or that
the original broader acceptance matrices passed. Raw evidence stays ignored,
because prompts and tool traces can contain private repository content.

| Path | Evidence | Operating boundary |
|---|---|---|
| PR create/reuse | Native real-agent runs, independently read-back PR #203 | Operator checks final head, base and draft status |
| Review and continuation | Historical full ready review and path-corrected ready run; new native same-ID update remained not-ready on execution-prefix interpretation | Never override not-ready or assume DAGU success means readiness; latest identity guidance has no post-fix live ready evidence |
| Stale publication | Valid captured old-head scope, real GitHub head advance, unchanged original publisher refusal | Controlled-input integration evidence, not a second full model review |
| Composed uncertain PR create | Real #209 create, successful response deliberately dropped; journal refused replay; explicit reconciliation reused PR | No automatic retry; not delivery-protocol recovery |
| Issue reply | Native wait/reject/approve, exact approved bytes, receipt reuse; real comment response loss followed by refusal | Inspect the actual GitHub comment before any recovery |
| Target binding | Credential-free repository/issue tamper cases reject before a post attempt; live draft tamper refused | Not a live target-tamper claim |
| Standalone ruling | Native ruling saved, fresh explicit run required | Completing the task does not continue work automatically |
| Delivery cancellation | Real local process tests for deadlines, signals and process-group cleanup | Not remote-write recovery or deliberate-detach containment |

The issue-response native evidence is retained under
`.worktrees/issue-18-live/.runs/issue18-live/20261029T203519Z/`:
`native-commands.md`, `case-approved/`, `case-write-drop/`, approval snapshots and
independent GitHub read-backs. Issues #204–#208 were closed; evidence comments were
retained. A docs-only investigation was inconclusive; it diagnosed no application
SSE defect. See [the publication campaign](/docs/live-acceptance.md) for PR evidence.

## Status, stop, and decision

Use the **same DAGU home/config** as the original run. Help for these command
shapes was checked against the installed pinned CLI. Replace placeholders with
the recorded identifiers; do not omit `--run-id` when stopping a run.

```bash
uv run .tools/bin/dagu status --dagu-home /absolute/run/dagu-home --run-id RUN_ID DAG_NAME
uv run .tools/bin/dagu stop --dagu-home /absolute/run/dagu-home --run-id RUN_ID DAG_NAME
```

Read `report.json`, `nodes/`, `status/`, `journal/`, `effects/` and nested
`delivery/`, not just the scheduler badge. After stopping, verify the captured
run-owned child PIDs exited. A stop request does not undo a submitted GitHub write.
Never kill by broad process-name matching, and never stop unrelated services.

For issue-response, use the native DAGU root approval/rejection UI. Waiting and
rejection must not post; approve only the saved exact target and draft. For
standalone questions, record the ruling and explicitly start a fresh run with
that ruling in its input. Do not use a local harness as a live approval substitute.
Delivery finish/request-changes is a separate, unaccepted lifecycle protocol.

## Recovery decision tree

1. **Waiting:** retain ownership. Inspect the snapshot/report and choose reject,
   approve, or a ruling using the workflow's native decision. No auto-approval.
2. **Certified receipt exists:** inspect the receipt, target and actual remote
   state first. Standalone/composed successful-step reuse is not evidence that
   delivery stages implement the same protocol.
3. **Started journal but no certified receipt, or lost response:** stop. Save the
   checkout HEAD/status, journal, publisher claim, output logs and exact target.
   Inspect Git/GitHub directly before touching journals or retrying.
4. **Effect found:** record its exact PR/comment/commit ID and SHA/bytes. Hand it
   off or deliberately reconcile the existing object; do not create a replacement
   merely because the workflow returned failure. The #209 probe's explicit
   publisher reconciliation is not automatic composed-stage resume.
5. **Effect absent or uncertain:** absence in one eventually consistent read is
   not proof that no write was submitted. Retain the uncertain state and require
   operator reconciliation. A fresh state directory does not make replay safe.
6. **Red, incomplete, stale head, timeout, or failed child delivery:** remain
   non-ready. Preserve the parent and child reports. Repair the underlying cause
   or abandon the run; do not edit a verdict to green.
7. **Cleanup:** independently read back owned PRs/branches/comments, preserve
   evidence and commits, close PRs unmerged, then remove only inventoried inactive
   worktrees/branches. Never broad-clean operator-global DAGU state.

## Explicitly outside acceptance

- Automatic uncertain-write replay, exactly-once GitHub semantics, and exhaustive
  pre-effect/post-effect/post-receipt interruption coverage across three protocols.
- Delivery remote-write interruption/recovery and native finish/request-changes.
- Unattended operation, overlapping writers, alerts, terminal-loss survival,
  stale ownership recovery, and a new spending/accounting system.
- Live ship/upkeep mutation and package-manager/model judgment acceptance.
- Live readiness after the latest execution-prefix clarification; the canonical
  update passed, but that continuation's not-ready verdict remains unchanged.
- Preventive sandboxing or containment of children that deliberately detach.

These are not silently waived pilot gates: #17 retains ship/upkeep acceptance;
#19 retains unattended-operation and relevant recovery evidence before enabling
those paths. Existing #4 owns persistent queues/distributed lifecycle. Closing
the narrower evidence issues does not unblock an unrestricted unattended pilot.
