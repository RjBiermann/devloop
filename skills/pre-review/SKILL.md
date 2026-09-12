---
name: pre-review
description: Review an agent-built PR against its spec before the human sees it, pushing fixes within the round budget. Use when a devloop PR exists.
---

# Pre-review

The AI pre-review exists to spare the human from slop, not to replace the human.

## Steps

1. Read the **spec issue first**, then the diff. The spec is the yardstick — not the diff's internal logic.
2. Check in order: (a) does it meet the acceptance condition, (b) is the evidence (FINDINGS-<n>.md, gate output) real and sufficient, (c) is the diff minimal — anything speculative gets cut, not commented.
3. Fixes go as commits on the PR branch, within the round budget (default 2). Round budget exhausted with issues remaining → label the PR `ready-for-human` with a summary of what's unresolved.
4. Every round leaves one visible artifact: a PR comment listing what changed and why.

## Hard limits

- Never merge, never approve, never close. Those buttons are human-only, by design and by code.
- If the PR contradicts its spec, say so plainly in one comment — do not silently rewrite it into something else the human didn't ask for.
