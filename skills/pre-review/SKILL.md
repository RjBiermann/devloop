---
name: pre-review
description: Review an agent-built PR against its spec before the human sees it. Findings only — never change code. Use when a devloop PR exists.
---

# Pre-review

The AI pre-review exists to spare the human from slop, not to replace the human.

## Steps

1. Read the **spec issue first**, then the diff. The spec is the yardstick — not the diff's internal logic.
2. Check in order: (a) does it meet the acceptance condition, (b) is the evidence (FINDINGS-<n>.md, gate output) real and sufficient, (c) is the diff minimal — anything speculative is a finding, not something you cut yourself.
3. Findings only — you never change code. A separate repair phase (skills/repair) acts on what you find; keep each finding self-contained (`file:line — severity — rationale`) so the fixer can act on it without re-deriving your reasoning.
4. Round budget exhausted with issues remaining → say so plainly in the final comment; the human decides.

## Hard limits

- Never merge, never approve, never close, never change code. Those buttons — and the working tree — are human and repair-phase territory.
- If the PR contradicts its spec, say so plainly in one comment — do not silently rewrite it into something else the human didn't ask for.
