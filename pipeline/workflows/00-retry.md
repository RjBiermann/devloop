---
features:
  dangerously-disable-sandbox-agent: true
sandbox:
  agent: false
strict: false
description: "/retry <issue> — human-sanctioned re-fire: stamped reset, close stale PR"
on:
  slash_command:
    name: retry
    events: [issues, issue_comment]
  roles: [admin, maintainer, write]
imports:
  - ../shared/engine-lane.md
  - ../shared/gate.md
  - ../shared/budget.md
permissions:
  contents: read
  issues: read
  pull-requests: read
timeout-minutes: 10
max-turns: 12
max-ai-credits: 200
safe-outputs:
  threat-detection: false   # engine:pi detection runs on Copilot CLI — not available (no Copilot); structural guardrails + human merge carry the boundary
  add-comment:
    max: 2
  close-pull-request:
    max: 1
---

# Retry

You are executing a human's explicit sanction. The command author passed
the write-role gate (fail-closed); that is the whole authorization.

1. Identify the target issue/PR from the command context: the issue or PR
   this comment is on, or the referenced number in the command args.
2. If the target references an open PR that belongs to this issue's
   devloop loop, close it with a comment "stale PR closed by /retry
   (human sanction)" — execution of the command author's judgment, not
   yours.
3. Post the budget reset stamp (see budget protocol — `gh-aw budget:
   reset`), which clears the attempt count for this issue.
4. Tell the human what re-fires: the issue needs its human-applied label
   re-applied or `/plan` re-invoked. **Never** apply or re-apply trigger
   labels yourself; agents never carry that authority.
