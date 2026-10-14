---
description: Security scan + secret-leak check merged (one PR-triggered pass)
on:
  pull_request:
    types: [opened, synchronize]
  roles: [admin, maintainer, write]
imports:
  - ../shared/engine-lane.md
  - ../shared/gate.md
permissions:
  contents: read
  issues: read
  pull-requests: read
timeout-minutes: 10
max-turns: 8
max-ai-credits: 200
safe-outputs:
  add-labels:
    allowed: [security/blocked, security/flagged]
    max: 4
  add-comment:
    max: 1
---

# Security scan (08+09 merged)

Cheap, focused pass over the PR diff only:

- Look for: injected secrets/tokens/keys, credential-shaped strings,
  unsafe subprocess/eval/SQL interpolation, dependency red flags visible
  in the diff.
- `security/blocked` for definite findings with the line reference in a
  single comment; `security/flagged` for suspicion worth human review.
- No findings → say nothing, label nothing. This workflow exists to be
  boring; every run is cheap by cap design.
