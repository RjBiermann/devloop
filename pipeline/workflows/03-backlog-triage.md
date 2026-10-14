---
features:
  dangerously-disable-sandbox-agent: true
sandbox:
  agent: false
strict: false
description: Daily sweep of open issues — re-check vocab, flag chronic flappers
on:
  schedule: daily
  workflow_dispatch:
imports:
  - ../shared/engine-lane.md
  - ../shared/gate.md
permissions:
  contents: read
  issues: read
timeout-minutes: 30
max-turns: 50
max-ai-credits: 800
safe-outputs:
  threat-detection: false   # engine:pi detection runs on Copilot CLI — not available (no Copilot); structural guardrails + human merge carry the boundary
  add-labels:
    allowed: [status/queued, status/in-review, status/fixing, status/fixing-stuck, status/ready-to-merge, triage/from-agent]
    max: 20
  remove-labels:
    allowed: [status/queued, status/in-review, status/fixing, status/fixing-stuck, status/ready-to-merge]
    max: 20
  add-comment:
    max: 10
  link-sub-issue:
    max: 10
  create-issue:
    max: 1
    title-prefix: "[backlog-report] "
---

# Backlog triage

Daily corpus sweep (replaces the cron-Sweep's queue-review duties beyond
what the sweeper can do deterministically):

- Scan open issues; normalize state labels to the one-state-at-a-time
  invariant (this is the **healer** for non-atomic safe-output batches —
  add the correct label, remove stale ones, same pass).
- Add `triage/from-agent` when you discover or classify work; link
  discovered sub-work to parents via `link-sub-issue`.
- Flag chronic flappers (issues cycling fix/work states repeatedly, per
  budget-stamp history in comments) with a short comment naming the
  stamp evidence.
- Post nothing on issues that need no change; your caps are shared with
  every other workflow in this repo.
- If nothing needed attention, say nothing anywhere.
