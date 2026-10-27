Investigate GitHub issue $INPUTS.issue_number in $INPUTS.repository. Read
it with `gh issue view $INPUTS.issue_number --repo $INPUTS.repository --comments`,
then read the code in this checkout to find the likely cause. Do not change
any files and do not write to GitHub; your draft is reviewed first.

Draft a comment for the issue: what you think the cause is, the files and
lines involved, and what would confirm it. Say plainly when you are unsure.
