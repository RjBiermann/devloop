---
name: progress
description: How the agent narrates its own build on the issue timeline — short prose progress comments, never state markers. Bundled default; repos may override.
---

# Progress

During a long build, post short progress comments on the issue so the human
can follow the AI's work without reading the runner log.

## Rules

- At most ~3 progress comments per build, and only when something meaningful
  finished. A short run needs none — the orchestrator already posts the
  build-started heartbeat, and the ledger records the outcome.
- Two lines each: what you just finished, what's next.
- Plain prose only. Never write anything resembling a devloop marker
  (`devloop budget:`, `agent run FAILED`, `devloop: status=…`) — the ledger
  counts state by marker, and your prose must stay inert.
- No secrets, tokens, or file dumps — the issue timeline is public.
