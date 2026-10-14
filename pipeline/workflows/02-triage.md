---
description: Gate new issues to the triage vocabulary — outsiders get status/queued
on:
  issues:
    types: [opened, reopened]
  roles: [admin, maintainer, write, triage]
imports:
  - ../shared/engine-lane.md
  - ../shared/gate.md
permissions:
  contents: read
  issues: read
timeout-minutes: 10
max-turns: 12
max-ai-credits: 250
safe-outputs:
  add-labels:
    allowed: [status/queued, triage/from-agent]
    max: 4
  add-comment:
    max: 1
---

# Triage

Label the new issue into the intake vocabulary (§7.3 taxonomy):

- Issues authored by trusted roles: label `status/queued` unless a more
  specific disposition is obvious from body/labels.
- Issues authored by the Actions bot with local workflow markers: label
  `triage/from-agent` + `status/queued` (provenance only — never a build
  trigger).
- Unknown or uncategorizable authorship: still `status/queued`; the
  post-activation role check has already run for the *trigger*, and
 Comment Context rules apply to everything you read.

After labelling, post one comment describing your disposition in one or
two sentences. You never start a build, never create PRs, never post more
than one comment.
