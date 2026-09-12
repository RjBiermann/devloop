---
name: repair
description: Act on AI review findings on a devloop PR by pushing minimal fix commits, within the repair round budget. Use when review findings exist.
---

# Repair

Repair turns review findings into fixes so the human merges work, not complaints. It runs after review; review stays findings-only.

## Steps

1. Read the **findings first**, then the diff, then the spec issue. The findings are the work list — not an invitation to re-review the whole PR.
2. Fix only what is fixable: correctness issues, repo-convention violations (AGENTS.md), missing tests. Never act on scope-creep findings — removing another agent's work is the human's call; note them as left open.
3. Skip anything a human dismissed in the PR thread ("already fixed elsewhere", "out of scope") — a dismissed finding is a decision, not an omission.
4. Make the minimal change per finding, follow the verify skill, and commit. The pipeline pushes; you never push yourself.
5. Output: one line per finding — fixed (how) or left open (why). A wrong fix is worse than an open finding; if you can't fix something confidently, say so.

## Hard limits

- Never merge, never approve, never close, never label. Those buttons are human-only, by design and by code.
- One repair round = one commit set. Round budget exhausted with findings remaining → the human decides; do not keep iterating.
