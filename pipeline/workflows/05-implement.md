---
features:
  dangerously-disable-sandbox-agent: true
sandbox:
  agent: false
strict: false
description: Implement one status/planned spec issue into a scoped PR
on:
  issues:
    types: [labeled]
    names: [status/planned]
  roles: [admin, maintainer, write]
imports:
  - ../shared/engine-lane.md
  - ../shared/gate.md
  - ../shared/budget.md
permissions:
  contents: read
  issues: read
  pull-requests: read
concurrency:
  group: impl-${{ github.event.issue.number }}
timeout-minutes: 75
max-turns: 30
max-ai-credits: 1500
safe-outputs:
  threat-detection: false
  add-comment:
    target: "*"
    max: 1
   # engine:pi detection runs on Copilot CLI — not available (no Copilot); structural guardrails + human merge carry the boundary
  create-pull-request:
    max: 1
    title-prefix: "[impl] "
  add-labels:
    allowed: [status/in-review]
    max: 1
  remove-labels:
    allowed: [status/planned]
    max: 1
  create-issue:
    max: 2
    title-prefix: "[from-impl] "
    labels: [triage/from-agent]
---

# Implement

Build this issue's spec exactly, nothing else. Scope discipline: unrelated
findings belong in the backlog, not in your diff — record them via
`create-issue` (`triage/from-agent`, max 2) or link the existing issue,
never fix inline.

1. Read the parent spec body and its linked sub-issues fully.
2. Implement; run the repo's own test command (from AGENTS.md/README).
3. `create-pull-request` — the PR body MUST include a "## Provenance"
   section: this workflow run URL, the trigger issue number, and your
   stamp (`gh-aw budget:` line per the budget protocol).
4. Transition state in one pass: `add-labels status/in-review`, then
   `remove-labels status/planned` (one state label at a time; partial
   failure is healed by the daily sweep).
5. Post one work-attempt stamp (`add-comment`) closing out what you did.

Never: apply trigger labels, label `status/planned`, merge, approve, or
close anything.
