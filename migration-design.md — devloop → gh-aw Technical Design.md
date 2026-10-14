# Migration Design: devloop → GitHub Agentic Workflows (gh-aw)

## 1. Concept map (devloop term → gh-aw implementation)

| devloop | gh-aw design element | Where |
|---|---|---|
| `forge/` adapter (github) | gh-aw's native GitHub integration | platform |
| `runtime/` engines | `engine:` frontmatter — **an adopter decision, not a framework pin**: one of gh-aw's built-ins (pi, claude, codex, copilot, gemini/agy). **Decision recorded**: pi + OpenCode Go, model `opencode-go/glm-5.3-flash`, secret `OPENCODE_API_KEY` (single lane; see PIPELINE.md Engine decision). All engines take per-workflow `model:`/`fallback-models:` pinning; budgets (`max-turns`, `max-ai-credits`) are engine-agnostic. Bespoke argv runtimes have no port (gh-aw ships no custom-argv engine) | all agent workflows |
| `skills/` SKILL.md pack | **Shared fragments in `ai-pipeline/`, versioned with the workflows they steer** (pre-review+repair → 06/07; spec-author+clarify → 04; progress → dropped — narration is prose, never state; verify/gate → 99-ci.yml itself). Per-repo AGENTS.md carries only repo-specific guidance, never pipeline-owned prompts — forking prompts per-repo recreates the two-sync-points bug ADR-0003 exists because of | pipeline repo + repo root |
| `[labels]` vocabulary | §7.3 taxonomy (superset of devloop's) | pilot repo setup |
| `/spec` rounds | `/plan` command, one-round-per-invoke | 04-plan.md |
| `ai-fix` / `ai-build` / `ai-remove` | trigger labels survive (§7.3 family table); the build flows they start: `05-implement.md` (+ `06`/`07` on the PR side) | 05-implement.md |
| `ready-for-agent` exclusivity | "exactly one state label at a time" removal rule in every transition | all label-touching workflows |
| `verify` gate + evidence | CI job uploading `evidence/` artifact; check named `verify` | 99-ci.yml |
| `review_rounds`, `repair_rounds` | review workflow + `/repair` variant of fix-loop | 06, 07 |
| `max_parallel` | not needed — each issue = its own run; concurrency group per issue number | `concurrency:` blocks |
| `max_attempts`, `max_per_day` | **Ledger protocol survives** (see 4.4): workflows post `gh-aw budget:`-stamped comments; the sweeper parses the comment history per issue with the same scan as `devloop/ledger.py`. Cooldown (`on.cooldown`) stays as an in-flight spacing guard only — it does not accumulate and **fails open** if run history is unqueryable, so it is never the budget | 06/07/report |
| `[access]` policy | `shared/gate.md` author_association gate | every workflow |
| comment-command YAML-gate (free for plain comments) | gh-aw `on: command` triggers | per command workflow |
| "merge = human verdict → closeout" | post-merge watcher closes sub-issues of merged PRs | 12-post-merge.md |

## 2. Trust model (ported and strengthened)

devloop enforced `[access]` in Python and denylisted agent CLI commands.
gh-aw gives structural enforcement instead:

```
Agent job: read-only, sandboxed, no write tokens, no PR/issue mutations possible
      │  (only requests, as structured output)
      ▼
Safe-outputs jobs: validate + cap + execute (labels, comments, PRs)
      │  (no merge path exists for agents — 11-merge-gate CUT from v1:
      │   merge-pull-request is experimental + refuses default-branch merges)
      ▼
Human clicks the merge button — the ONLY path to main
(branch protection + required `verify` are the floor)
```

Guardrails hold by construction:
- never merge/approve → no such safe-output enabled for agents
- never apply trigger labels → `safe-outputs.add-labels.allowed` excludes `status/planned` and `ai/go`
- never close spawned issue → `close-issue` not enabled (except post-merge watcher whose trigger is the human merge itself)

### Gate checks (per trigger)

| Trigger | Checks | Distrusted result |
|---|---|---|
| `issues: opened/reopened` | issue author assoc ∈ {OWNER, MEMBER, COLLABORATOR} | `status/queued`, agent skipped |
| `issues: labeled` | labeler sender trusted (or Actions token from our own workflows) | — (outsiders can't label) |
| `status/queued` label / `/triage` cmd | write-role + gate (gh-aw reactions are status feedback, **not triggers** — authoring-time correction) | no-op, agent skipped |
| `/command` | `on.roles` fail-closed default (defense-in-depth: restated in `shared/gate.md`, ADR-0005) | no-op |
| `pull_request` | PR author trusted | `status/queued` flag, review skipped |
| `pull_request_target` | **never used** | fork isolation |
| `push: main` | trusted by branch protection | runs post-merge only |

Bot exception: issues authored by Actions bot pre-labeled `triage/from-agent`
may pass triage (Option B intake); they may never pass implement triggers.

## 3. Spec loop design (the `/plan` port)

```
/plan #N  (owner comment, write-gated)
   agent round 1: reads issue + repo, posts clarify questions as ONE
                  comment (numbered, batchable answers)
   human replies (any format — no answer-format parser: the next
                  round's prompt includes the thread verbatim under
                  Comment-context untrusted framing)
/plan #N  (again)
   agent round 2: confirms spec, proposes epic/story breakdown
   human replies `approved`
/plan #N  (again)
   agent round 3: finalize — creates sub-issues UNLABELED, links via
   link-sub-issue, rewrites parent issue body as the final spec
   parent gets `status/planned` ONLY by human hand
```

Invariants (from devloop, kept verbatim in intent):
- No build starts without human-authored intent (`status/planned` is
  human-only — excluded from agent `add-labels.allowed`).
- Every round is a comment → whole negotiation on the record.
- One round per invocation — the human controls pacing.

## 4. Execute + verify loop

### 4.1 implement (per sub-issue labeled `status/planned`)

- Agent: read-only, `max-turns: 30`, `timeout-minutes: 30`, concurrency group
  on the issue number (one run per issue = `max_parallel` semantics).
- Effect chain: implement → `create-pull-request` → PR references sub-issue →
  `add-labels status/in-review` on parent → sub-issue loses
  `status/planned` (remove-labels) — the "one state at a time" rule.
- Provenance: the PR body links the agent run (workflow run URL, credits
  spent, budget stamp) — CI's `verify` proves the code passed; the link
  proves who/what produced it (ADR-0006-adjacent evidence trail).
- Scope discipline block: unrelated findings → search → link or create-issue
  (`triage/from-agent`, max 2), never fix inline.

### 4.2 verify (evidence-gated CI)

- `99-ci.yml`: build + tests; on success uploads `evidence/` artifact
  (tool versions, command outputs, test logs).
- Gate name: `verify` — required status check on target branches.
- Verify fail → PR is needs-work by definition; nothing in the AI loop
  can override a missing check (required checks don't disappear).

### 4.3 review + repair + retry (devloop commands ported)

| devloop | workflow | Trigger | Behavior |
|---|---|---|---|
| `/review <pr>` | 06-review.md | command, or auto on `pull_request` | AI review round(s): blockers as review comments; findings only |
| `/repair <pr>` | 07-fix-loop.md | command, or auto on `requested_changes` | review findings → fix attempt → push to PR branch → re-review, capped 3 cycles |
| `/retry <issue>` | 00-retry.md | command | reset attempt budget, close stale PR, human's sanction re-fires labeling |
| auto-flap guard | (inherits) | cooldown 10m | chronic flappers surfaced by daily sweep as "needs human" |

### 4.4 The sweeper (self-healing survives the Sweep)

devloop's cron Sweep existed "so missed events self-heal" (CONTEXT.md). gh-aw
has no native missed-event catch-up and Actions silently skips cron runs
under load, so the healing role is preserved explicitly:

- A **plain, non-AI Actions workflow** — deterministic state-machine work,
  no agent, no AI turns.
- Finds state labels stuck past a per-state timeout, re-fires by
  remove+re-add of the trigger label (works with gh-aw's `label_command`
  one-shot semantics).
- Parses `gh-aw budget:`-stamped comments per issue (Ledger protocol,
  see §6 `max_attempts` row) and applies the attempt-cap outcome:
  escalation comment + stuck label.
- Posts the weekly status report (the `devloop status` successor): what
  ran, what's stuck, attempt counts, skip reasons — same data it already
  computes for its re-fire decisions, zero AI.
- A probability reducer, not a guarantee — cron runs can still be skipped;
  the design accepts this residual risk.

Escalation: after 3 review→fix cycles → comment "needs human" + label
`status/fixing-stuck`; nothing else fires on that PR until a human intervenes.

## 5. Workflow inventory

| # | File | Trigger | Safe-outputs | Caps |
|---|---|---|---|---|
| 00 | retry.md | `/retry` | close-pull-request(1), add-comment | gate-run only |
| 01 | queue-watcher.md | `labeled: status/queued`, `/triage` (gh-aw reactions are feedback, not triggers) | add-labels | max 1 |
| 02 | triage.md | `issues: opened/reopened` | add-labels(4), add-comment(1) | 10m |
| 03 | backlog-triage.md | daily + dispatch | labels(20), comments(10), link-sub-issue(10), report issue(1) | 30m, 50k turns cap |
| 04 | plan.md | `/plan` | create-issue(6), link-sub-issue(6), add-comment(1) | 20m |
| 05 | implement.md | `status/planned` labeled | create-pull-request(1), add-labels, remove-labels, create-issue(2) | 30m, 30 turns |
| 06 | review.md | `pull_request`, `/review` | review-comment(10), add-comment(1), add-labels | 25 turns |
| 07 | fix-loop.md | `requested_changes`, `/repair` | push-to-pull-request-branch(3), review-comment(10), create-issue(2) | cooldown 10m |
| 08 | security-scan.md (secret-leak check merged in) | `pull_request` | add-labels(security/*), add-comment | cheap |
| 09 | ~~secret-leak-check.md~~ — merged into 08 | — | — | — |
| 11 | ~~merge-gate.md~~ | ~~`/merge`~~ | **cut from v1** — `merge-pull-request` safe-output is experimental *and always refuses merges to the default branch*, the only merge `/merge` would perform. v1: `status/ready-to-merge` labels the PR, the human clicks the merge button, 12-post-merge records the verdict. Revisit only if gh-aw ships a non-refusing path *and* the manual click demonstrably hurts | — |
| 12 | post-merge.md | `push: main` | close-issue linked subs | low caps — no `create-pull-request`: no migrated-repo need has been named; add back only when a concrete adopter asks |
| 13 | cost-tracker.md | weekly | create-issue(1) | — |

All agent workflows pin `model:` + `fallback-models:` in pipeline sources and
set **`max-ai-credits`** — the only gh-aw-native budget that is never skipped
for our trigger mix (`max-daily-ai-credits` is disabled by default *and*
skipped for command/label-triggered runs; `on.cooldown` fails open). The
Ledger counts attempts; `max-ai-credits` bounds tokens per run. 00-retry
stays a separate file on purpose: its `close-pull-request` is a destructive
permission the other command workflows don't have, and least-privilege-per-
file keeps every lock review a one-glance check (does the safe-output list
match the job?).

## 6. devloop config → gh-aw knobs (translation table)

| devloop key | gh-aw equivalent |
|---|---|
| `[forge].repo` | the repo the workflow compiles into |
| `[labels].fix/new/remove` | taxonomy labels (workflow `add-labels.allowed` + gh label create script) |
| `[runtime].engine/argv` | `engine:` + `model:` frontmatter — engine is the adopter's choice (see §1); `argv` plugins (arbitrary CLIs) have no port |
| `[pipeline].verify` | required check named `verify` |
| `review_rounds` | review workflow invocation cap (labels/comments per run) |
| `repair_rounds` | fix-loop cycle cap (3) |
| `max_parallel` | `concurrency: group: impl-${{ github.event.issue.number }}` |
| `max_attempts` | cycle cap + `status/fixing-stuck` |
| `max_per_day` | Ledger protocol (see §6 `max_attempts` row) — budget stamps in comment history, sweeper parses; cooldown is spacing only |
| `poll_seconds` | n/a for triggering — event-driven; the cron Sweep's *self-healing* role survives as the non-AI sweeper (§4.4), not as a poller |
| `timeout` | `timeout-minutes: 30` |
| `[access]` | `shared/gate.md` |

## 7.3. Label taxonomy (devloop `[labels]` successor)

Three families; membership decides who may apply a label. Trigger authority
and state transitions both read from this table — every workflow's
`add-labels.allowed` is derived from it.

| Family | Examples | Who applies | Notes |
|---|---|---|---|
| `ai-*` (trigger) | `ai-fix`, `ai-build`, `ai-remove` | **Human only** | Reserved prefix (ADR-0003 unchanged); agent allow-lists structurally exclude the family |
| `status/*` (state machine) | `status/queued`, `status/planned`, `status/in-review`, `status/fixing`, `status/fixing-stuck`, `status/ready-to-merge` | Agents, **except `status/planned`** — human-only | One state label at a time; add+remove in the same safe-output batch; the sweeper re-checks and normalizes |
| `triage/*` (intake) | `triage/from-agent` | Agents | Provenance marker for agent-discovered work; never starts a build |

Changes from the original draft taxonomy: `ai/queued` → `status/queued`
(no agent-applicable label shares the reserved `ai-` namespace, ADR-0003);
**`ai/go` is removed** — work re-fires by the `status/queued` label event or
a `/triage` command, never by a label an agent could apply (gh-aw reactions
are status feedback, not triggers). `status/planned` (human-only) replaces the draft's
`ai-go`-mediated entry into implement.

## 7.4. Multi-repo distribution

- Sources + fragments only in `ai-pipeline/`; per-repo `.github/workflows`
  contains compiled `.lock.yml` (via `gh aw install`), never hand-edited.
- **Pinned like devloop tags (Adopter/Upgrade semantics carry over):** locks
  upgrade deliberately per repo — a recompile + PR into that repo's
  `.github/workflows`, never auto-following the pipeline repo. gh-aw pinned
  exactly (v0.89.21 at authoring), upgraded deliberately.
- **Lock-drift CI:** `gh aw list --stale` / `--json` compiled-check in the
  pipeline repo fails on any out-of-sync lock (replaces guardrail unit tests
  — see ADR-0005).
- Org-level provider secret inherited everywhere (the one matching the chosen lane — decision: `OPENCODE_API_KEY` for the pi + OpenCode Go lane; Copilot would need none/its own auth).
- Repo-specific deltas: labels names, backlog-triage schedule, cost caps →
  per-repo `vars` (e.g. `PIPELINE_LABEL_PREFIX`).
- PIPELINE.md in shared repo = the operator runbook (replaces devloop's config.toml docs).

## 8. State machine (final)

```
status/queued ──(owner label / /triage cmd)──▶ triage
triage ──(human /plan rounds x3)──▶ status/planned (human-only label)
status/planned ──(label event)──▶ status/implementing ──▶ PR + status/in-review
status/in-review ──(blockers)──↔ status/fixing  (≤3 cycles, cooldown 10m)
   └─(3 cycles hit)─▶ status/fixing-stuck ──(human /retry or takeover)
status/in-review ──(review clean + verify passed + security cleared)
   ──▶ status/ready-to-merge ──(/merge by owner)──▶ merged
merged ──(push: main watcher)──▶ close spawned sub-issues + record
```

One state label at a time; every transition adds then removes in the same
safe-output batch; state labels mutually exclusive by construction.

## 9. Decommission devloop (per migrated repo)

- Remove devloop bundle workflow + GitHub App tokens if any.
- Archive the devloop tool itself (`config.toml` under `docs/devloop-archive`
  for provenance) — the pipeline is **single-track**: no GitLab/Gitea
  carve-out; other-forge repos must migrate to GitHub to adopt it.
- PIPELINE.md states: gh-aw is the only pipeline; devloop is archived.
