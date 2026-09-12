# devloop

**A forge-agnostic framework for AI-native development: human writes the spec, AI builds, humans merge.**

```
Human owns intent and acceptance. AI owns everything between.
```

**No build starts on an ambiguous spec.** Specs go through a state machine:
`draft → clarify (agent interrogates ambiguity, human answers in batches)
→ propose (agent breaks down epics/stories/sub-issues) → human `approved`
→ finalize (sub-issues created unlabeled, parent issue = final spec).
Trigger labels stay human-only — deciding what to build is the human's call.
`devloop spec <n>` advances one round per invocation; every round is a comment
on the issue, so the whole negotiation is on the record.

## The loop

```
┌─ SPEC (human) ─────────────────────────────────────────────┐
│  issues + trigger labels · spec templates · /spec command   │
│  rule: no build starts without human-authored intent        │
├─ ORCHESTRATE (framework) ──────────────────────────────────┤
│  forge adapters (github · gitlab · gitea) · event routing   │
│  label vocabulary · command routing · budgets/rate caps     │
├─ EXECUTE (pluggable) ──────────────────────────────────────┤
│  agent runtimes: opencode · claude · goose · custom argv    │
│  any model backend · skills = Agent Skills spec (SKILL.md)  │
├─ VERIFY (AI) ──────────────────────────────────────────────┤
│  user-defined gate command · evidence files required        │
│  gate fails → PR marked needs-work, never merged            │
├─ REVIEW (AI + human) ──────────────────────────────────────┤
│  AI pre-review rounds (capped) → fixes pushed → HUMAN merge │
├─ MONITOR (AI → human) ─────────────────────────────────────┤
│  scheduled drift probes · tracking issues · verdict tables  │
│  chronic flags → candidates for human to call               │
└────────────────────────────────────────────────────────────┘
```

## Guardrails (non-negotiable, enforced in code)

An agent running under devloop can **never**:

- merge or approve a PR
- apply a trigger label (`ai-fix`, `ai-build`, `ai-remove`)
- close an issue it was spawned from

Comment commands (`/retry <issue>`, `/review <pr>`) are the one exception,
and they are safe: devloop executes them **for** an authorized human (the
author is access-gated before anything happens), and closing a stale PR on
`/retry` is executing that human's explicit sanction — not the agent judging
its own work. Labels create work; commands re-fire it. Trigger labels and
`ready-for-agent` are mutually exclusive. Humans merge.

## Comment commands

Post in an issue or PR thread (authorized users only — same `[access]`
policy as everything else):

- `/retry <issue>` — reset the attempt budget, close the issue's stale
  devloop PR if any, and re-fire the build
- `/review <pr>` — run the AI pre-review rounds on an open PR on demand
  (`/review` inside a PR thread targets that PR)

The workflow triggers on `issue_comment` with a YAML-level gate so plain
comments never spin up a runner job; non-command comments cost nothing.

## Quickstart

**Prereqs** (all free, ~5 min once):
- Python 3.11+
- `gh` (GitHub CLI), authenticated: `gh auth login`
- an agent CLI, authenticated — e.g. `opencode` or `claude` (any model
  backend they support; `runtime.argv` takes anything)
- git push access to the target repo

```bash
pip install -e .          # no runtime deps, stdlib only
devloop init              # writes config.toml + skills/ into your repo
# ... edit config.toml: [forge].repo at minimum; check [runtime] and [access]
gh label create ai-fix -R you/your-repo --color 0E8A16      # repeat for
gh label create ai-build -R you/your-repo --color 2A6E3F    # ai-remove too
gh label create ai-remove -R you/your-repo --color B60205   # (names must match config)

# The spec loop — one `devloop spec` round per exchange:
devloop spec 42           # ① agent posts clarify questions → you answer in the thread
devloop spec 42           # ② agent posts epic/story/sub-issue breakdown
# you reply `approved`
devloop spec 42           # ③ sub-issues created (unlabeled) + issue body = final spec
# you apply a trigger label on a story issue → `devloop once` builds it

devloop once              # process everything pending
devloop watch             # poll loop for local / CI-less setups
```

On GitHub, the bundled workflow file runs `devloop once` on label events,
comments, and a schedule for the drift monitor. Per-forge auth, scheduling,
label setup, and access-control mapping: see **[docs/environments.md](docs/environments.md)**
(GitLab/Gitea are M2 — no adapter yet).

## Configuration

```toml
[forge]
kind = "github"          # github | gitlab (future) | gitea (future)
repo = "owner/name"

[labels]
fix = "ai-fix"
new = "ai-build"
remove = "ai-remove"

[runtime]
engine = "opencode"      # argv is fully overridable — any agent CLI works
argv = ["opencode", "run"]
skills_path = "skills/"  # your skills override the bundled pack

[pipeline]
verify = ""              # your gate, e.g. "make verify"
review_rounds = 2
max_parallel = 1           # raise to build concurrently; each build gets its
                           # own worktree and file-overlap deliveries defer
poll_seconds = 300
```

Everything is overridable; zero-config works with defaults.

## Known MVP limits

- **Guardrails bind devloop's forge calls, not the agent's shell.** The agent
  runtime can still invoke `gh`/`git` directly — real enforcement (tool
  denylists at the runtime layer) lands in M1. Until then, run agents with
  your runtime's own permission controls.
- `devloop init` reads bundled templates from the source tree — install
  editable (`pip install -e .`) until M1 ships proper package data.
- Config keys are validated with a warning on unknown keys; unknown values
  are not type-checked.

## Layout

```
devloop/            orchestrator: events → agent job → PR
  forge/            Forge interface + adapters (github today)
  runtime/          AgentRuntime interface + engines
skills/             bundled generic skill pack (SKILL.md spec)
tests/              guardrail + routing checks
```
