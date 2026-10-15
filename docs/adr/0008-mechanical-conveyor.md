# ADR-0008: The mechanical conveyor — approvals, merge, chain

Status: **accepted** (2026-10-15)
Supersedes the operator-session orchestration pattern established in C5/C6;
amends ADR-0001's "humans merge" surface in a defined, revertible way.

## Context

Operating the pipeline proved that a maintainer session performs a
predictable set of mechanical steps per PR: approve companion runs stuck in
`action_required` (bot authored PRs put everything there), give the merge
go-ahead once all required contexts are green, stamp `status/planned` on the
next story, and close transient `[aw]` diagnostics whose triggering item has
already recovered. None of these need judgement after the human decision
that authorizes the chain exists; manual repetition only adds latency and
session-side fragility (the whole point of gh-aw was to move maintenance
orchestration onto GitHub itself, not into an operator's chat).

## Decision

A new plain-Actions workflow, `95-orchestrator.yml` (non-AI — no engine, no
agent; sibling of `90-sweeper`), runs on a 10-minute cadence and performs
four mechanical jobs:

1. **Approve companion runs** on `devloop/*` PR branches that are stuck in
   `action_required` — non-AI companions only (99-ci, Lint, CodeQL,
   Security scan, dependency submissions, Review agents). Agent workflows
   from gh-aw itself are excluded from the approve-allowlist: those rows
   stay visible pending human attention by design, not accidentally.
   Needs an admin PAT (`GH_AW_PROXY_PAT`); when the secret is unset the
   step warns and leaves approvals to the maintainer (safe-fail).
2. **Auto-merge spec-chain PRs**: every open, non-draft `devloop/issue-*`
   PR gets `gh pr merge --squash --auto` queued, so branch protection
   (the required `verify` check, CodeQL etc.) remains the actual gating
   mechanism. Governing variable: repo-level `GH_AW_AUTO_MERGE` (default
   `true`); set `false` to return per-PR merges to the maintainer.
3. **Drive the story chain**: once a `[spec] Story N-1` sub-issue closes
   (its PR merged), stamp `status/planned` on the next `[spec] Story N`
   sibling (open, unlabeled). Never touches `ai-*` trigger labels.
4. **Watchdog**: close an issue authored by `github-actions[bot]` whose
   title matches `[aw]…no safe outputs` / `[aw]…reported incomplete` when
   a LATER successful run of the same workflow exists; the comment points
   at the later run and invites reopening on new evidence.

## Why this keeps the guardrails

- **Human decision, once per chain**: the plan loop's `approved` reply
  (round-3 finalize) authorizes a story chain as a unit. What the
  orchestrator automates is the *mechanics* of executing that approval,
  not new approval authority. The maintainer can always set
  `GH_AW_AUTO_MERGE=false` to return the per-PR merge to their hand.
- **No agent merges**: the conveyor is not an agent workflow (no `engine:`
  block), so ADR-0001's "agents never merge" is untouched at the
  structural level — an agent still has no merge capability in the
  compiled frontmatter set.
- **`ai-*` trigger labels remain human-only** (ADR-0003): the conveyor's
  label writes are limited to `status/planned` on spec-authored sub-issues
  that came from an already-approved chain.
- **Every action is revertible by config**: `GH_AW_AUTO_MERGE` false, a
  branch-protection rule requiring a human review on the PR, or deleting
  the workflow file each undo effectively the previous behavior.

## Consequences

- Adopters need an admin PAT (`GH_AW_PROXY_PAT`, fine-grained scoped
  `contents:read` + `actions:write` + `pull_requests:write` + read on the
  repo twin if they want cross-repo orchestration) for the approve step.
  Fresh adopters can start without it (approvals remain manual; nothing
  degrades) and add the secret when they are ready to remove latency.
- Branch protection must have `Allow auto-merge` enabled (a repo setting,
  not a workflow-level one).
- The workflow adds a periodic walk of `devloop/*` branches and open
  `[aw]` issues; it is scheduled at 10 minutes and uses
  `concurrency.group: orchestrator` to avoid self-contention.
- A transient re-run closing is only valid if a later success exists for
  the *same* workflow family; a genuinely new failure mode still lands on
  a maintainer.

## Rollback

- `GH_AW_AUTO_MERGE=false` variable → merge automation off.
- Remove `GH_AW_PROXY_PAT` secret → approve automation off (manual flow).
- Disable or delete `95-orchestrator.yml` → all conveyor steps off; the
  maintainer session steps from C5/C6 are the manual fallback.
