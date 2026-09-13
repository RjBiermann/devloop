# Changelog

All notable changes to devloop. Semver-ish: minor bumps add features,
patch bumps fix behavior bugs. Tag = release.

## Unreleased

(nothing yet — releases are automatic (ADR-0002); notes land here when a
merge ships)

## v0.3.8 — template + docs hardening

- **Template passes actionlint**: comments moved out of the folded `if:`
  expression — the shipped template failed GitHub's workflow parser for
  every adopter copying it verbatim.
- **PAT delivery pattern**: GITHUB_TOKEN cannot push commits that modify
  `.github/workflows/`, regardless of permissions — the run's work is
  silently discarded at delivery. docs/environments.md → Auth documents
  the extraheader PAT pattern (fine-grained PAT, Contents + Workflows
  read/write).
- **Pinning**: the template install line recommends pinning to a tag;
  a Pinning section explains why (an unpinned devloop means a broken
  devloop commit breaks every adopting pipeline at once).
- **Glossary**: Workflow template and Adopter defined in CONTEXT.md.
- **Test fix**: `test_version_bump` rewrote the repo's real
  pyproject.toml — a no-op when written at 0.3.0, a silent version
  downgrade on every test run afterwards. Isolated to a temp file.

## v0.3.7 — forge owns its identity

- **Git identity**: on fresh CI checkouts, devloop sets the commit
  identity itself (start_work / rebase_branch) — only when unset; a
  human's config always wins.
- **Trigger-label contract**: the reserved `ai-` prefix is the workflow
  filter contract (ADR-0003) — a config rename within the namespace
  never orphans the trigger, and the workflow never hardcodes label
  names.

## v0.3.6 — M1 hardening

- **Layered settings**: `~/.config/devloop/config.toml` (or
  `$XDG_CONFIG_HOME`) holds org-standard defaults; the repo `config.toml`
  overrides key-by-key (sections merge, repo wins) — pi's global/project
  settings model. No global file = unchanged behavior.
- **Budget caps**: `[pipeline].max_per_day` bounds failed attempts per
  issue per day (runaway detection). Like `max_attempts`, it counts the
  issue's comment ledger — failure comments now carry a dated
  `devloop budget:` header; marker matching moved from line-start to
  contains, so old comments still count.
- **GitHub Enterprise Server**: `[forge].base_url = "ghe.example.com"`
  reaches every `gh` call as `GH_HOST`; auth via `gh auth login
  --hostname`. Git remote ops untouched.
- **Refactor + docs sync**: ponytail-review fixes across the core;
  stale `ai-task` workflow gate removed.

## v0.3.5 — forge fixes

- Fixed rebase of open devloop PRs rebasing the local head instead of the
  remote PR head; infrastructure errors during rebase skip the head for
  this sweep instead of closing the PR (never destroy delivered work on a
  transient git/network hiccup)

## v0.3.4 — sweep on push to default branch

- Push trigger on the default branch in the workflow template: main
  moving runs the sweep immediately (rebase stale PRs, rebuild on
  conflict) instead of waiting up to 30 min for the schedule. No new
  code — `run_once` already owned the upkeep; redundant runs from a
  release-bot's follow-up push are accepted (an idle sweep is a few
  `gh` list calls, serialized by the concurrency group)

## v0.3.2 / v0.3.3 — merge closeout

- Merge closeout: a human-merged devloop PR (`devloop/issue-N`) posts a
  `devloop PR merged` ledger entry and closes its issue — no more
  ghost issues reopened by sweeps after their PR merged. New
  `forge.complete_issue` (carve-out documented in the base class, same
  precedent as `/retry`'s close_pr), `devloop merged` CLI, and a
  `pull_request: closed` trigger in the workflow template (YAML-gated to
  merged devloop branches, so other merges cost nothing)

## v0.3.1 — Forge owns its checkouts

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
- Dropped the speculative `ai-task` trigger (v0.2.x leftover); trigger
  vocabulary is `ai-fix` / `ai-build` / `ai-remove`

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
