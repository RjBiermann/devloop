# Changelog

All notable changes to devloop. Semver-ish: minor bumps add features,
patch bumps fix behavior bugs. Tag = release.

## v0.2.10 — comment commands + review context

- `/retry <issue>` and `/review <pr>` comment commands (access-gated;
  `/retry` resets the attempt budget and closes the stale devloop PR)
- `devloop command` CLI: executes comment commands from the GitHub
  `issue_comment` CI event; silent exit on non-commands (zero token spend)
- Review context: each round carries the PR thread (human replies) and
  the reviewer's own prior findings — stateless sessions see full state
- Workflow template: `issue_comment` trigger with YAML-level `/`-gate

## v0.2.9 — parallel builds

- Per-build git worktrees: parallel agents never share a working tree;
  stale worktree admin entries self-heal
- Delivery conflict gate: builds whose files overlap an open devloop PR
  defer to a later sweep instead of opening a guaranteed conflict
- `max_parallel` is now a throughput choice, not a correctness one
- Fix: duplicated reviewer invocation per review round (token leak)
- Fix: review diffs always via `gh pr diff` (local origin/HEAD diffs
  proved unreliable mid-build)

## v0.2.5–v0.2.8 — review + delivery hardening

- `pipeline.review_rounds`: AI pre-review with repo customization via
  `skills/pre-review/SKILL.md`; `devloop review <pr>` on demand
- Review prompt carries the spec issue (the yardstick)
- Attempt cap (`pipeline.max_attempts`): poison tasks skipped until a
  human re-labels; failure ledger read from issue comments
- Half-delivery recovery: agent pushed a branch without a PR — devloop
  opens the PR itself
- Braces in injected issue bodies no longer break prompt assembly
  (replace-based substitution)

## v0.1.x — MVP

- Core loop: trigger labels → agent build → gate → PR → human merge
- Spec loop (`devloop spec <n>`): clarify ↔ approve ↔ finalize
- Guardrails: merge/approve/close/label are human-only, enforced in the
  forge base so no adapter can forget
- Trigger authority: `[access]` modes + allow/deny lists, deny wins
- Serial builds; loud failure reporting on the issue ledger; no-diff =
  failed delivery
