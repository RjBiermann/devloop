# Migration Plan: devloop → GitHub Agentic Workflows (gh-aw)

## Scope

Replace devloop's orchestrator (Python sweep engine, forge adapter, runtime
pluggability) with gh-aw for GitHub-hosted repos, preserving devloop's core
contract: **human writes the spec, AI builds, humans merge**, plus the
non-negotiable guardrails (agents never merge, approve, apply trigger
labels, or close the issue that spawned them).

GitHub-only, single-track: no devloop carve-out for other forges — repos on
GitLab/Gitea either migrate to GitHub or don't adopt this pipeline. No local
development: everything runs in Actions.

## What we keep vs. discard

| devloop piece | Decision | gh-aw replacement |
|---|---|---|
| Spec state machine (`diaft->clarify->propose->approved->finalize`) | **Port** | `/plan` command workflow, one round per invocation, rounds as comments |
| Trigger labels (ai-fix, ai-build, ai-remove) human-set | **Port** | `status/*` + `ai/*` label taxonomy; enforced by Triage-role requirement |
| `/retry`, `/review`, `/repair` commands | **Port** | Command-triggered workflows (write-role-gated by gh-aw) |
| `verify` gate + evidence files | **Port** | Evidence-gated `99-ci.yml` check as required status check |
| AI pre-review rounds (capped) → human merge | **Port** | review + fix-loop workflows with cycle caps |
| Scheduled drift probes / monitors | **Port** | Daily backlog-triage sweep + weekly cost tracker |
| Forge adapters (gitlab, gitea) | **Discard** — no dual-track: other forges are out of scope | Migrated repos: GitHub only |
| Pluggable agent runtimes (opencode, claude, argv) | **The adopter decides** | `engine:` frontmatter — one of gh-aw's built-ins (pi, claude, codex, copilot, gemini/agy), chosen per adoption; `model:`/`fallback-models:` pinned per workflow; per-workflow budgets unchanged. Bespoke argv runtimes still have no port (gh-aw ships no custom-argv engine) |
| Guardrail denylists (per-engine CLI deny rules) | **Discard** | Structural: agents are read-only; writes only via safe-outputs; unit tests replaced by compile-drift CI (`gh aw list --stale` + allow-list assertions) — ADR-0005 |
| Guardrail unit tests | **Discard** | Platform-enforced; keep a smoke test workflow |
| Local `devloop watch` mode | **Discard** | `gh aw trial` + workflow_dispatch cover manual/on-demand runs |
| Layered config (org defaults / repo overrides) | **Port conceptually** | Org-level secret + shared pipeline repo; per-repo vars for deltas |
| Runaway caps (`max_attempts`, `max_per_day`) | **Port** | Ledger protocol survives: `gh-aw budget:` stamps, sweeper parses the comment history (same scan as `ledger.py`); cycle cap 3; `on.cooldown` = spacing only (fails open); `max-ai-credits` per workflow = always-on token ceiling |
| "merge = human's verdict → close linked issues" | **Port** | `status/ready-to-merge` + human clicks the merge button; post-merge watcher on `push: main` closes linked sub-issues. `/merge` automation **cut from v1** — gh-aw `merge-pull-request` is experimental *and always refuses merges to the default branch* |

## Phase A — Prepare (Repo infra, no AI)

| Step | Task | Output |
|---|---|---|
| A1 | Install gh-aw ^(0.85.4+^): `gh extensions install github/gh-aw` | CLI ready |
| A2 | In-repo pilot (Q24): sources compile from this repo; the shared `ai-pipeline` repo is deferred until a second repo adopts the pipeline (then sources move there — sources never duplicated per-repo) | DRY home, deferred |
| A3 | Org secret for the adopting repo's **own engine lane** (name set by their `engine-lane.md` fragment; pilot's lane: pi + OpenCode Go → `OPENCODE_API_KEY` rotated in from the existing opencode credential) | Single spend lane, per-adopter |
| A4 | Branch protection/rulesets on each repo's `main`: required checks (CI + security scan), 1 human review, no force-push, signed commits | Merge floor |
| A5 | Label taxonomy synced to target repos (see design 7.3); create via `gh label create` script | State machine exists |
| A6 | CODEOWNERS for `.github/workflows/**`, `shared/*.md`, AGENTS.md | Workflow edits gated |
| A7 | Secret scanning + push protection ON; Actions-PR self-approval rule ON | Supply-chain floor |
| A8 | Sweeper: plain **non-AI** Actions workflow — re-fires stuck state labels (remove+re-add), parses `budget:` stamps per issue, applies attempt-cap outcomes, posts the weekly status report (`devloop status` successor). Probability reducer, not a guarantee (Actions can skip cron under load) | Self-healing survives the Sweep (ADR-0006) |

## Phase B — Author the workflow set

| Step | Task | Output |
|---|---|---|
| B1 | `shared/gate.md` + `shared/budget.md` fragments + the adopter's **own `shared/engine-lane.md`** (mechanism per PIPELINE.md §Engine lane), imported into all workflows | Trust boundary + lane |
| B2 | `01-queue-watcher.md` | Outsiders only enqueue |
| B3 | `02-triage.md` + `03-backlog-triage.md` (vendor agentics issue-triage as base) | Intake + corpus sweep |
| B4 | `04-plan.md` — port `devloop spec` clarify loop (one round per `/plan` invoke; agent asks batch, human answers in thread, `/plan` again); `/approved` reply finalizes sub-issues + parent body as spec | Spec negotiation ported |
| B5 | `05-implement.md` — trigger on `status/planned`, engine per A3, scoped PR + evidence-gated branch | Execute layer |
| B6 | `06-review.md` + `07-fix-loop.md` — port `/review` and `/repair` semantics; 3-cycle cap, cooldown, stuck escalation | Review loop |
| B7 | `08-security-scan.md` (secret-leak check merged in; vendor agentics) + `99-ci.yml` (verify required check + `evidence/` upload) | Security + gate floor |
| B8 | ~~`11-merge-gate.md`~~ **cut** — merge button is the verdict (A4 branch protection + required `verify` are the floor); human's verdict preserved structurally | Human verdict preserved |
| B9 | `12-post-merge.md` — port "merge closes issue's devloop PR → close linked sub-issues" as `push: main` watcher | Closeout recorded |
| B10 | `00-retry.md` — port `/retry` semantics: reset attempt budget, close stale PR, re-fire (human-sanctioned only) | Re-work primitive |

## Phase C — Cut over per repo

| Step | Task | Output |
|---|---|---|
| C0 | Trial per engine candidate over the 12-workflow set (`gh aw trial --engine <e>`, sandbox); pilot default **pi** unless a trial shows a better fit; record choice in PIPELINE.md | Engine on evidence (ADR-0007) |
| C1 | Pick pilot repo (lowest risk, small backlog) | — |
| C2 | Map existing devloop trigger labels → new taxonomy (script, defensible rename) | Labels migrated |
| C3 | `gh aw install` pipeline into pilot repo; compile + review `.lock.yml` diffs | Workflows live |
| C4 | Freeze devloop sweeps in that repo (`max_parallel=0` or disable scheduled workflow); devloop has no role after cutover (rollback window: disabled-not-deleted through Phase D, then D5) | Single owner of GH loop |
| C5 | Run the spec→build→merge happy path with a real issue; timestamp every step | Acceptance run |
| C6 | Turn on remaining repos after 2 clean weeks on pilot | Rollout |

## Phase D — Post-migration verification

| Step | Task | Output |
|---|---|---|
| D1 | Guardrail smoke test: attempt outsider issue + label-like spam + forged command; confirm no AI run fires | Gate holds |
| D2 | Convergence test: force a review failure x3 cycles; confirm `status/fixing-stuck` + escalate comment | Loop bounds hold |
| D3 | Evidence test: inject a failing `verify` step; confirm merge blocked even on `/merge` attempt | Gate floor holds |
| D4 | Cost report vs. devloop run cost | Bounded spend |
| D5 | Decommission: archive devloop config and the devloop tool itself — the pipeline is single-track | Clean archivest |

## Open risks

| Risk | Mitigation |
|---|---|
| `/merge` automation someday | Only if gh-aw ships a non-refusing `merge-pull-request` path *and* the manual click demonstrably hurts |
| Clarify-loop ergonomics vs devloop's batch answers | No answer-format parser: the next `/plan` round's prompt re-reads the thread verbatim under Comment-context framing |
| CI evidence artifacts differ from devloop's `verify` evidence files | CI workflow uploads `evidence/` artifact; implement links its own run provenance into the PR body (run URL, credits, budget stamp) — both evidences carry |
| Token burn from heavy spec conversations | `max-turns` per round + command-driven rounds (no auto-advance) |
| Repos on other forges | Out of scope by decision — migrate to GitHub to adopt the pipeline (see Scope) |

## Success criteria

1. devloop guardrails all hold in gh-aw form (zero agent merges/approves/trigger-labels/spawned-closes).
2. Full spec→merge achievable with only labels/commands from owner (gh-aw reactions are feedback, not triggers).
3. Verify gate (CI + evidence) is a required check the merge button cannot bypass; `/merge` automation cut from v1.
4. Fix loop converges or escalates within 3 cycles; total daily spend bounded.
5. Every repo runs exactly one pipeline (gh-aw) — no dual-track; devloop archived after the Phase-D rollback window.
