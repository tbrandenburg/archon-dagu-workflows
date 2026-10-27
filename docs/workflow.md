# Delivery in developer terms

Give the workflow accepted work: a plan, change request, findings, or a PR to finish. It ends with a ready PR or an explanation of why work stopped. Triage, initial planning, merging and deployment are outside this Archon workflow.

1. **Check GitHub access.** Refuse before spending on an agent when the configured forge cannot act.
2. **Implement.** Read the accepted work, prior review, CI evidence and open threads. Fix the cause, run focused checks, commit and record what happened. Each implementation can have five fresh turns.
3. **Publish the draft PR.** Prepare an accurate description, push explicitly, reuse/create the qualified PR and verify it. Never force-push or rebase.
4. **Review the exact head.** Confirm the checkout matches the remote PR. Select code, tests, seams/interfaces, errors and docs lenses as warranted. Reviewers do not own implementation.
5. **Combine and publish findings.** Check every acceptance item; return correct, replan or ask. A failed selected reviewer cannot silently count as approval.
6. **Simplify once.** After review passes, identify unnecessary structure that can be removed without changing required behavior. The implementer adopts or declines findings with evidence, then a light review checks the delta.
7. **Judge old review threads.** Verify proposed fixes/declines and prepare evidenced replies. The thread agent does not post them itself.
8. **Wait for and diagnose CI.** Check head and mergeability. Some repositories require taking the PR out of draft to start CI. Wait for checks on that head; distinguish PR-caused defects from external failures. Restore draft status on red.
9. **Publish thread replies and reread.** Original scripts reply, resolve and verify. Threads arriving during CI count too. Missing or unreadable evidence is not “all clear.”
10. **Choose another round or stop.** Correctable review/CI/thread findings repeat. Replan/ask/external CI trouble stop. The fourth repeatable failure becomes `round_cap`, a valid not-ready outcome.
11. **Correct the final description and report.** Preserve human edits, disclose actual validation, link issues appropriately and relay remaining contract items/discoveries.
12. **Ask a person when needed.** The real root workflow supports finish or request changes for another bounded batch. PR merge remains external.

The full original prompts are in `prompts/`. For example, `implement.md` owns implementation behavior; `implement-delivery-context.md` supplies delivery-specific work. `review-code.md` asks for evidenced defects, `review-tests.md` checks meaningful missing proof, and `ci.md` specifies diagnosis and readiness handling. Short explanations here do not replace those prompts.

## Try these cases

```bash
make demo CASE=ready
make demo CASE=fix_ci
make demo VARIANT=detailed-dry CASE=four_round_cap
make demo VARIANT=detailed-dry CASE=fix_ci EXECUTOR=dagu
```

The default local executor uses the exact workflow commands with fixture responses. It does not run a model or mutate GitHub. `EXECUTOR=dagu` runs the actual engine. Artifacts and reports are written beneath `.runs/examples/` with unique names.

`ready: false` is distinct from a process failure. For example, a capped batch completed its decision-making correctly but still needs a developer. A publishing crash remains a failed execution and must retain whatever PR identity was already recorded.

Read [parity.md](parity.md) before moving to live operation.
