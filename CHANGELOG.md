# Changelog

All notable changes to devloop. Semver-ish: minor bumps add features,
patch bumps fix behavior bugs. Tag = release.

## Unreleased — Forge owns its checkouts

- **Forge adapter interface changed** (custom adapters need a two-line
  update): `start_work(number, branch) -> str` now allocates the build
  checkout itself and returns its path; callers never name paths. New
  `finish_work(number)` removes the checkout (no-op when the issue never
  started). Fixes a live bug: `/retry` ran with the default
  `workdir="."`, and the old adapter deleted that path — wiping the
  repo checkout. Deleting caller-supplied paths is now structurally
  impossible: the adapter only ever removes checkouts it created.
- Fixed repair's verification round running in the default checkout
  (`cwd="."`) instead of the PR branch's worktree
- Fixed build prompts using `.format()`: braces in an issue body
  (`def f(): return {'a': 1}`) crashed the build before the agent ran;
  substitution is now replace-based, like review and repair
- Merge closeout: a human-merged devloop PR (`devloop/issue-N`) posts a
  `devloop PR merged` ledger entry and closes its issue — no more
  ghost issues reopened by sweeps after their PR merged. New
  `forge.complete_issue` (carve-out documented in the base class, same
  precedent as `/retry`'s close_pr), `devloop merged` CLI, and a
  `pull_request: closed` trigger in the workflow template (YAML-gated to
  merged devloop branches, so other merges cost nothing)
- Push trigger on the default branch in the workflow template: main
  moving runs the sweep immediately (rebase stale PRs, rebuild on
  conflict) instead of waiting up to 30 min for the schedule. No new
  code — `run_once` already owned the upkeep; redundant runs from a
  release-bot's follow-up push are accepted (an idle sweep is a few
  `gh` list calls, serialized by the concurrency group)

## v0.3.0 — repair phase

- `pipeline.repair_rounds` (default 1, 0 = off): after pre-review finds
  issues, an independent repair session acts on the findings — minimal
  fixes, verify gate before push, one verification review round per
  repair, attempt cap before the human takes over
- Review stays findings-only; `review_pr()` now returns its final
  findings ("" on LGTM) for repair to consume
- New `skills/repair/SKILL.md` customization point; `skills/pre-review`
  clarified back to findings-only (its old "fixes as commits" step
  contradicted the reviewer prompt — this resolves it)
- ADR 0001: why repair is a separate phase, not a self-fixing reviewer

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
