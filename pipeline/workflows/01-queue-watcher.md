---
description: Outsiders only enqueue — human labels status/queued or posts /triage
on:
  issues:
    types: [labeled]
    names: [status/queued]
  slash_command:
    name: triage
    events: [issues, issue_comment]
  roles: [admin, maintainer, write, triage]
imports:
  - ../shared/engine-lane.md
  - ../shared/gate.md
permissions:
  contents: read
  issues: read
timeout-minutes: 5
max-turns: 8
max-ai-credits: 100
safe-outputs:
  threat-detection: false   # engine:pi detection runs on Copilot CLI — not available (no Copilot); structural guardrails + human merge carry the boundary
  add-labels:
    allowed: [status/in-review, status/fixing, status/fixing-stuck, status/ready-to-merge]
    max: 1
---

# Queue watcher

Light-weight router. gh-aw reactions are status feedback only — human
intent to enqueue arrives as a `status/queued` label event (persistent) or
a `/triage` command. If the triggering actor or item fails the triage-role
gate, workflow skips before you run.

Confirm the issue carries exactly one state label. If state is ambiguous
(two `status/*` labels), do nothing — the sweeper normalizes it. Upstream
triage (02) runs on issue-opened; you only exist so label-events and
commands land on the record cheaply.
