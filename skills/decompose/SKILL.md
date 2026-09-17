---
name: decompose
description: After clarify agreement, propose epics/stories/sub-issues from the decisions, get approval, then finalize the spec with all tasks laid out.
---

# Decompose

Input: the decision record (from the clarify skill). Output: an agreed task
tree and a finalized spec. Nothing is built in this skill.

## Steps

1. **Propose the breakdown** as an issue comment:
   - **Epics**: only if the work has 3+ distinct phases or deliverables.
     Otherwise skip straight to stories — no ceremony.
   - **Stories**: one independently verifiable unit each, phrased as
     "As the system, when X, Y must happen" or "Add/fix/change … so that …".
     Every story carries its own acceptance condition.
   - **Sub-issues**: implementation steps under a story *only when* they'd be
     reviewed by a different person or on a different day.
   - **Touch-sets**: every story issue body carries a `Touch-set:` line
     listing the paths it will change (see the partition skill). Overlapping
     stories get merged or sequenced — the human is approving the conflict
     plan too.
2. Mark the proposal with `devloop: status=propose` and wait.
3. On the human's explicit `approved` reply: **finalize**.
   - Create one issue per story (and sub-issues where applicable), each with
     its acceptance condition in the body, each **unlabeled**.
   - Rewrite the parent issue body into the final spec: intent, decision
     record, the full task tree with links to the created issues.
   - End with `devloop: status=ready`.

## Rules

- Creating issues is allowed; applying trigger labels is not. The human
  chooses which stories to build now (that's their `ai-fix`/`ai-build`
  call) — the decomposition only lays out the map.
- Every task must trace to a decision. If you can't trace it, it's scope
  creep — cut it or ask.
- A story the human can't verify is not a story yet; send it back through
  clarify instead of guessing at its acceptance condition.
