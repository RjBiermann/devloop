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
