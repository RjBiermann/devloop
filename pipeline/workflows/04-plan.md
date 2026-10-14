---
features:
  dangerously-disable-sandbox-agent: true
sandbox:
  agent: false
strict: false
description: "/plan #N — one spec round per invocation; negotiation stays on the record"
on:
  slash_command:
    name: plan
    events: [issues, issue_comment]
  roles: [admin, maintainer, write]
imports:
  - ../shared/engine-lane.md
  - ../shared/gate.md
permissions:
  contents: read
  issues: read
timeout-minutes: 20
max-turns: 25
max-ai-credits: 500
safe-outputs:
  threat-detection: false   # engine:pi detection runs on Copilot CLI — not available (no Copilot); structural guardrails + human merge carry the boundary
  add-comment:
    max: 1
  create-issue:
    max: 6
    title-prefix: "[spec] "
  link-sub-issue:
    max: 6
---

# Plan (spec loop port)

One round per `/plan` invocation. The human controls pacing; never
advance a round yourself.

- **Round 1** (no prior round-1 marker in the issue comments): read the
  issue + repo + comment thread (Comment Context: untrusted framing).
  Post ONE numbered list of clarify questions as a single comment.
- **Round 2** (round 1 exists + human replied): re-read the thread verbatim
  — answers in any format are acceptable, no parser enforces a contract.
  Confirm the spec, propose an epic/story breakdown in a single comment.
- **Round 3** (round 2 exists + human wrote the word `approved` +
  replies): finalize — create the sub-issues (UNLABELED: no state label,
  no trigger label), link each as a sub-issue of the parent, then rewrite
  the parent body as the final spec.

Never apply `status/planned`: that label is human-only. Never create
trigger labels. Every round ends with one comment, nothing else. If the
state of the thread doesn't match a round above, state your read in one
comment and stop.
