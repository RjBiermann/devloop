---
features:
  dangerously-disable-sandbox-agent: true
sandbox:
  agent: false
strict: false
description: "/review — on-demand review round, findings only"
on:
  slash_command:
    name: review
    events: [issue_comment, pull_request_review_comment]
  roles: [admin, maintainer, write]
imports:
  - ../shared/engine-lane.md
  - ../shared/gate.md
  - ../shared/budget.md
permissions:
  contents: read
  issues: read
  pull-requests: read
timeout-minutes: 25
max-turns: 25
max-ai-credits: 800
safe-outputs:
  threat-detection: false
  create-pull-request-review-comment:
    max: 10
    target: "*"
  add-comment:
    max: 1
---

# Review (command — findings only; ADR-0001 semantics)

The `/review` command re-fires a review round on the PR the command was
posted on (PR comments are issue_comments in GitHub's model) or the PR
referenced by the command args. Same contract as the auto-review (06):
review that PR's current diff against its spec issue and prior findings;
**findings only** — you never push, edit, close, merge, or fix.

- Blockers as `create-pull-request-review-comment`s on the exact lines.
- Empty/unverifiable diff = loud abort, never a pass (Ghost diff rule;
  re-fire the command after the head settles).
- Close with one work-attempt stamp via `add-comment`.
- No diff to review (command posted on a non-PR issue): say so in one
  comment and stop.
