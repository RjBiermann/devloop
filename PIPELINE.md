# PIPELINE.md — operator runbook

The gh-aw successor to `config.toml`. **Single-track**: gh-aw is the only
pipeline; other forges are out of scope. Sources live in `pipeline/` until
they move to `your-org/ai-pipeline` (shared fragments imported from there);
per-repo `.github/workflows` receives **only compiled `.lock.yml`** — never
hand-edited, upgraded deliberately per repo (pinned like devloop tags).

## Engine lane (ADR-0007) — mechanism

**Every agent workflow imports `shared/engine-lane.md`, and that file is
the adopting repo's own** — the one place an adopter writes their engine,
model, secret lane, and network. The pipeline's shared sources never
hardcode an engine. Mechanism:

1. Adopting repo copies `pipeline/` sources into `.github/workflows/`
   (or compiles from ai-pipeline once that exists).
2. Adopting repo writes its own `shared/engine-lane.md` (one small
   fragment: `engine:` block + optional key env + optional models.json
   pre-step + `network:`). Trial it: `gh aw trial --engine <id>` per
   candidate before committing.
3. Adopting repo creates the lane's secret (name defined by their lane
   fragment — the pilot's is `OPENCODE_API_KEY`).

**Pilot lane (this repo's choice, recorded as the worked example):**

- Engine: **pi**, pinned `version: 1.1.0` (session-header-complete pi on
  Go's validated-clients list)
- Provider/model: **`opencode-go/glm-5.3-flash`** — OpenAI Chat
  Completions surface (`https://opencode.ai/zen/go/v1/chat/completions`),
  configured via the pre-agent step's `models.json` write
- Secret lane: **`OPENCODE_API_KEY`** (Go's metered lane;
  glm-5.3-flash caps at $60/Go-tier per model; gh-aw-side ceiling is
  per-workflow `max-ai-credits`)
- Composer caveat: if the fragment-import engine ever fails to register
  at compile time, fall back to repeating the engine block per workflow;
  decide on `gh aw compile` evidence at C0

## Vocabulary (successor terms; CONTEXT.md remains devloop-the-tool)

- **Sweeper** — the plain non-AI Actions workflow (`90-sweeper.yml`) that
  preserves the Sweep's self-healing role: re-fires stuck state labels,
  parses budget stamps, posts the weekly status report. Probability
  reducer, not a guarantee (ADR-0006).
- **Ledger stamp** — a comment body beginning `gh-aw budget:`, the only
  budget-affecting comment form. Producers only; parsers count; never
  edited, only appended (same contract as devloop's ledger markers).
- **Kind** — the budget shape a workflow encodes in frontmatter; the
  trigger label → workflow chain *is* the mapping (ADR-0004 superseded by
  ADR-0007 on engines; kinds survive as budget shapes).
- **Fragment** — a shared markdown import in `pipeline/shared/`
  (gate.md, budget.md), versioned with the workflows that consume it.
  Per-repo AGENTS.md never duplicates pipeline-owned prompts.
- **Engine lane** — the adopting repo's own `shared/engine-lane.md`
  fragment: their engine, model, secret name, network. The pipeline's
  only engine requirement is that this file exists and imports cleanly;
  its content is adopter jurisdiction (ADR-0007).

## Install (per repo)

```sh
gh extension install github/gh-aw@v0.89.21          # pinned (or @<tag>)
gh aw init --engine pi
bash pipeline/labels.sh                              # taxonomy bootstrap (A5)
# copy pipeline/workflows/*.md -> .github/workflows/ (or aw add from ai-pipeline)
gh aw compile --validate --strict
gh aw list --stale                                   # drift check; CI uses:
gh aw list --json | jq -e 'all(.[]; .compiled == "Yes")'
```

## Assets

| Path | Role |
|---|---|
| `pipeline/workflows/00–13-*.md` | The 11 agent workflows (11-merge-gate cut; 08+09 merged) |
| `pipeline/shared/*.md` | Fragments imported by every agent workflow |
| `pipeline/fixed/90-sweeper.yml` | Non-AI sweeper + weekly status report |
| `pipeline/fixed/99-ci.yml` | `verify` required check + `evidence/` upload |
| `pipeline/labels.sh` | Taxonomy bootstrap (A5) |

## Known deltas during authoring (gh-aw v0.89.21 facts)

1. 👀 **reactions are status feedback, not triggers** in gh-aw. The design's
   "owner 👀 fires triage" is corrected to: owner applies `status/queued`
   (persistent label event) or posts `/triage` — human intent fires by
   label or command, never by reaction.
1b. **Model lane is his per-repo:** the pilot's OpenCode Go lane
   (`OPENCODE_API_KEY`, glm-5.3-flash) is the `engine-lane.md` example —
   not a pipeline default. Adopters write their own; the drift check's
   only engine assertion is that every agent workflow imports
   `engine-lane.md` and that the fragment declares *some* engine.
2. `merge-pull-request` is experimental and **always refuses merges to the
   default branch** — `/merge` stays cut; humans click the merge button.
3. `on:cooldown` **fails open** when run history is unqueryable — it is a
   spacing guard only; the Ledger is the budget.
4. `max-daily-ai-credits` is disabled by default and skipped for
   command/label-triggered runs — `max-ai-credits` (always-on, per run)
   is set on every agent workflow.
5. Safe-output batches are **not atomic** across operations; partial
   failure is healed by the sweeper re-checking the "one state label"
   invariant.
6. **Threat detection**: gh-aw's AI detection runs on the Copilot engine;
   without Copilot access it can't run. Every workflow sets
   `safe-outputs.threat-detection: false` (documented-off; default was
   non-blocking anyway). Compensating controls stay: read-only agents,
   safe-output allow-lists, human-only labels/merge, gate framing. If
   Copilot access ever exists, flip the flag to re-enable CTR analysis.
7. **`slash_command` + `pull_request` are mutually exclusive in one
   workflow** — `/review` lives in its own file now
   (`06b-command-review.md`); 06-review is PR-triggered only.
8. **Import paths are repo-root-relative at install time**
   (`.github/workflows/shared/*.md`) — the pipeline source tree uses
   `../shared/...` and the deploy step rewrites them (one sed).
9. **Go GLM reasoning quirk** (from the adopter's own #479/#493 history):
   the GLM upstream 400s on `reasoning_effort`, so the lane's
   `models.json` sets `"reasoning": false` explicitly — never omit, pi
   falls back to its default reasoning for reasoning-capable models.
   Pi branch pin: `engine.lane` pins pi `version: "1.1.0"`.

10. **glm-5.3-flash on Go = native lane (post-burn-in, 2026-10-14):** v0.89.21's
   sandboxed pi gateway hard-pins the wire protocol per model prefix
   (copilot|anthropic|openai|codex → Responses/Anthropic/etc.) —
   chat-completions-only models CANNOT run there, and `engine.config.model`
   overrides don't reach the aw-gateway extension. Live-proven emissive
   fix: `sandbox.agent: false` + `features.dangerously-disable-sandbox-agent:`
   `true` + per-workflow `strict: false` (strict compile rejects the
   opt-out) — pi runs natively on the runner via a pre-agent `models.json`
   (provider `openai` retargeted to `zen/go/v1`), same one-lane model,
   same secret alias (`engine.env` override lifts `OPENCODE_API_KEY` into
   the validate step). Everything outside the firewall holds: read-only
   agent, safe-output allow-lists, roles gate, human merge. REMAINING
   cosmetic: pi exits 1 on an interim provider error even after internal
   retry — the run shows status=failure though safe-outputs landed
   (`add_comment`/-`add_labels`-style written) and the model got a full
   successful turn (`stopReason: stop`).


## Rollback (through Phase D)

Devloop's bundle workflow stays **installed but disabled** until Phase D
completes; unfreeze template in `docs/devloop-archive/` (created at D5).

## Cutover runbook (absorbed from migration-plan.md, deleted 2026-10)

**Assets already built**: A5 labels — `pipeline/labels.sh`; A8 sweeper,
B1 fragments, B2–B10 workflows, 99-ci, per ADR-0005–0007. Still to ship:

| Step | Task | Owner |
|---|---|---|
| C0 | `gh aw trial` the workflow set (compile + live runner network proofs: lane fragment registration; pi-under-AWF vs `opencode.ai`) | me, post-merge |
| C1 | Pilot repo = this repo (dogfood) | decided |
| C3 | Install compiled set (`gh aw init --engine pi`, `gh aw add` / copy sources+fixed/ into `.github/workflows/`, `gh aw compile --validate --strict`, review `.lock.yml` diffs in the pilot PR/window) | me |
| C4 | Pilot has no devloop sweeps running — rollback window stays installed-but-disabled | decided |
| C5–C6 | Acceptance run on a real issue (timestamped); 2 clean weeks → next adopter, whose own engine-lane file they write | human |

**Branch protection floor (A4, pilot)**: required check `verify` (+CodeQL)
+ no force-push; review rule deferred until a multi-maintainer repo.
**`/merge` automation stays cut** (gh-aw refuses default-branch merges).
D-phase: D1 outsider/label-forge/forged-command smoke tests; D2 force a
failure ×3 cycles → `status/fixing-stuck`; D3 failing verify block even on
attempted `/merge`; D4 cost report vs devloop; D5 archive devloop for
`docs/devloop-archive` and archive the tool (single-track).

**Success criteria**: zero agent merges/approves/trigger-labels/spawned-
closes · spec→merge with labels+commands only · `verify` is required and
merge-button-bound · fix loop converges or escalates ≤3 cycles · single
pipeline per repo. **Top risks carried**: experimental glad-handshake
`merge-pull-request` (cut), partial safe-output batches (sweeper heals),
compile-day engine-lane arbitration (C0), runner network for the Go lane
(C0).

## Delta 11 — implement budget-stamp scoping (C5 finding, 2026-10-14)

The implement directive told the agent to post its work-attempt stamp as an
issue comment on the SPEC issue — but the compiled safe-output allow-list
scopes `add_comment.target` to the *triggering item* (the PR), so the write
was rejected by the allow-list (upstream diagnostic filed impl-side). Fix
shipped in the next lock compile: `add-comment.target: "*"` in implement's
safe-outputs (pilot PR #591), so stamps can reach the spec issue. Everything
else in the C5 chain ran clean on the native glm lane.

## Delta 12 — safe-output *intent* vs *sink* is not enforced in the native lane (triage on audit #593)

glm-5.3-flash streamed "Now apply labels…" and finished exit 0 *without
ever emitting a safe-output call* — `agent_output.jsonl` was empty and gh-aw
had no hook to complain (the MISSING-TOOL gate only fires on infrastructure
failures, not on model-forgotten calls). Fix: the compiled fragment body now
ends with a **Terminal action block** that instructs the agent to run the
`safeoutputs` CLI directly as its last bash step
(`safeoutputs add_labels '{…}'` / `add_comment '{…}'`) — concrete invocation
beats named-tool intent for weak-tool-use models under pi `--print` mode.
Ground truth observed 2026-10-14: a zero-findings fix-loop still needs this
(noop clause) — `/[aw] no safe outputs` fired on a *correct* silent exit
(f-o-f #610); 07-fix-loop.md now binds stamp+noop explicitly (delta 13 noop
sub-item, both repos). Fade the aliasing away if gh-aw adds a hard gate on
empty outputs.jsonl.

## Delta 13 — audit-class run budget + steering-crash partial-durability

- **13a**: `05-implement` timeout 30 → 75 minutes. The S2 deep pass was
  wall-killed at the old 30-minute ceiling mid-fleet-verification
  (f-o-f run 38593712488, credits wasted, zero safe-outputs since the
  steering crash ate the warnings). 75 mirrors the old audit-class budget
  (build_timeout=5400 + margin). Ported f-o-f PR #605.
- **13b (upstream wishlist)**: gh-aw's steering extension crashes under pi
  v1.1.0 (`Cannot read properties of undefined (reading 'steer')`) so the
  "time remaining" warnings never reach the agent — one of two compounding
  causes above. Filed for the gh-aw side; no devloop-side action.
- **13c (f-o-f decision, 2026-10-14)**: daily AIC guardrail 5K → 20K via the
  `GH_AW_DEFAULT_MAX_DAILY_AI_CREDITS` repo variable after the S1+S2 chain
  legitimately spent ~6K AIC in one 24h window and blocked S3 — the adopter
  chose "raise the envelope" over "wait for UTC-midnight reset"; the
  default stays 5K in the pipeline sources.

## Delta 14 — `07-fix-loop` zero-findings gate (2026-10-14)

An approve-triggered fix-loop run on merged PR #609 legitimately decided
"zero actionable findings" (bot status content = data, not tasks) and then
exited silently — delta 12's noop clause wasn't binding on this prompt's
own contract. `07-fix-loop.md` body now states the zero-findings outcome
explicitly: close with a work-attempt stamp **and** emit
`safeoutputs noop …` as the final bash step; an empty exit is a defect in
every workflow. devloop `e2ab258` / f-o-f `b6822e0`.

## Delta 15 — safe-output payload channels (2026-10-15, f-o-f #613)

A `/plan` agent built its clarify-question payload in a heredoc, then
invoked `safeoutputs add_comment` **with both** the heredoc on stdin and an
inline `body: "sentinel"` placeholder arg — the CLI takes the inline arg,
the heredoc was discarded, and the run's entire `add_comment.max: 1`
budget was spent emitting a one-word placeholder comment (run 38685870541;
the run itself concluded `failure` only via that mismatch, and the issue
surface carried the noise). Fixed contract in the engine lane's
terminal-action block: **payload through one channel, never both**, plus
"check for placeholder residue before invoking; re-exec on malformed call"
(a malformed call is free — a processed output is not).

## Delta 16 — the mechanical conveyor (ADR-0008, 2026-10-15)

Session-side orchestration (approve stuck companion runs, queue merges,
stamp next-story triggers, close transient `[aw]` diagnostics) is now
GitHub-native: plain-Actions `95-orchestrator.yml`, scheduled every 10
minutes, no engine block — a sibling of `90-sweeper`. Human decision stays
once per chain (the plan loop's `approved`), execution is mechanical.
Revertible by three switches: repo variable `GH_AW_AUTO_MERGE=false`,
deleting secret `GH_AW_PROXY_PAT` (approvals stay manual), or removing the
workflow file. Documented in `docs/adr/0008-mechanical-conveyor.md`.

### Delta 16 amendment — same-day changes (ADR-0008 amended)

- **Merges return to the maintainer** (user decision): default is the
  human-merge contract — the orchestrator labels `status/ready-to-merge`
  and @mentions the owner when all checks are green. Auto-merge queueing
  is opt-in per repo (`GH_AW_AUTO_MERGE=true`; unset/false = the
  maintainer clicks merge).
- **Plan-loop surrogate**: the orchestrator fires `/plan` mechanically —
  round 1 on a fresh `ai-*` trigger, round 2 when the human answered a
  round-1 clarifier, round 3 when the owner replies `approved`. Every
  firing carries a per-round `[orchestrator]` marker so it can never
  loop. Content decisions remain human.
- **Decision tags**: when a round is waiting on the maintainer, one
  `@owner decision needed` comment is posted (deduped per round).
- Implementation is a committed python script (`.github/orchestrator.py`,
  single entry, per-step try/except so one failure never blocks the rest)
  driven by `95-orchestrator.yml` (10-minute cadence, single-flight).

### Delta 16 follow-up (first orchestrator live-run findings, f-o-f run 38816082027)

- **Crash**: the nit-fold commit's preflight helper still referenced the
  removed `gh_json` shim → NameError on first scheduled pass. Fixed to
  use the `api()` surface (f-o-f PR #624).
- **Review blockers folded**: story-state comparisons lowercase-tolerant;
  auto-merge path now requires the chain's owner approval comment before
  queueing merges (falls back to readiness ping otherwise).
- **Round-anchor convention codified**: 04-plan.md round posts begin with
  `Plan round N — ` exactly; the conveyor detects loop state by that
  anchor, so the fragility the in-flow review flagged becomes a compile-
  day contract instead of a guess.
