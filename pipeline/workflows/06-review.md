---
description: Findings-only review rounds on the PR — the reviewer never edits code
on:
  pull_request:
    types: [opened, synchronize]
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
  create-pull-request-review-comment:
    max: 10
  add-comment:
    max: 1
  add-labels:
    allowed: [status/ready-to-merge]
    max: 1
---

# Review (findings only; ADR-0001 semantics preserved)

Full-peer review, like a human senior reviewer would:

- **Verdict per PR comment thread**: blockers (wrong, unsafe, dead on
  arrival) go as `create-pull-request-review-comment`s on the exact
  lines. Style suggestions are comments too — findings stay yours.
- **You never push, edit, or fix anything**; any review feedback lands
  for a separate repair session to act on (07). Never push to the PR
  branch, never close, never merge.
- Carry prior findings between rounds (re-derived against the current
  diff; empty diffs are always a hard abort, never a pass).
- If the diff passes your review AND CI (`verify`) is green AND no
  `security/blocked` label is present, add `status/ready-to-merge` —
  the human decides the merge itself.
- Close with one work-attempt stamp.
