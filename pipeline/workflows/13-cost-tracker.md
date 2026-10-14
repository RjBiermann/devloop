---
description: Weekly spend + ledger report from run history (weekly, cheap)
on:
  schedule: weekly on monday
imports:
  - ../shared/engine-lane.md
  - ../shared/gate.md
permissions:
  contents: read
  issues: read
  pull-requests: read
timeout-minutes: 15
max-turns: 15
max-ai-credits: 250
safe-outputs:
  threat-detection: false   # engine:pi detection runs on Copilot CLI — not available (no Copilot); structural guardrails + human merge carry the boundary
  create-issue:
    max: 1
    title-prefix: "[cost-report] "
    close-older-issues: true
---

# Cost tracker

Weekly accounting against the Actions API, for the org's single spend
lane: tokens/credits consumed per workflow (this repo + rolled-up per-repo
totals when run from the pipeline repo), run counts, crashes/timeouts,
budget-stamp-based attempt histograms, and chronic flappers the sweeper
report flagged but a human hasn't visited. One issue; the next week's run
closes it (`close-older-issues`). No advice, no fixes — numbers only.
