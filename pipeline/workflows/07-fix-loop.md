---
description: Repair acts on review findings — separate session, capped, cooldown
on:
  pull_request_review:
    types: [submitted]
  slash_command:
    name: repair
    events: [issue_comment, pull_request_review_comment]
  roles: [admin, maintainer, write]
  cooldown: 10m
imports:
  - ../shared/engine-lane.md
  - ../shared/gate.md
  - ../shared/budget.md
permissions:
  contents: read
  issues: read
  pull-requests: read
timeout-minutes: 30
max-turns: 30
max-ai-credits: 1200
safe-outputs:
  threat-detection: false   # engine:pi detection runs on Copilot CLI — not available (no Copilot); structural guardrails + human merge carry the boundary
  push-to-pull-request-branch:
    max: 3
  add-labels:
    allowed: [status/fixing, status/fixing-stuck]
    max: 2
  remove-labels:
    allowed: [status/fixing]
    max: 1
  add-comment:
    max: 2
  create-issue:
    max: 2
    title-prefix: "[from-repair] "
    labels: [triage/from-agent]
---

# Fix loop (repair; consumes findings from 06)

The fixer session — separate prompt, separate budget, separate judgment
from the reviewer (ADR-0001: review finds, repair acts).

1. Re-derive findings from the current review comments + diff; a PR with
   a stale/empty diff aborts loudly (never pass on unverifiable state).
2. If this would be cycle 4 or later (count work-attempt stamps on the
   issue), stop: add `status/fixing-stuck`, comment "needs human" with
   the stamp evidence, and do nothing else.
3. Otherwise: add `status/fixing`, fix **only** the findings (scope
   discipline: new discoveries go to `create-issue`, max 2, linked —
   never fixed inline), verify before requesting delivery, and request
   the push via `push-to-pull-request-branch` (max 3 per run) — the
   safe-output job performs the push; you yourself stay read-only, so
   even the fixer never holds a write token.
4. Remove `status/fixing` after the push; let re-review re-fire.
5. Close with a work-attempt stamp.
