# Context

Domain vocabulary for devloop. Terms here are the words this project uses — don't drift to synonyms.

## Glossary

### Sweep

One pass of `devloop once`: rebase stale devloop PRs onto the default
branch (rebuilding on conflict), then start queued builds within the
parallelism budget. The self-healing unit of orchestration — trigger
labels, comment commands, merged-PR closeouts, and pushes to the default
branch all just feed the next sweep; the schedule (30-min cron) exists
only so missed events self-heal, not as the primary trigger.

### Version

Semver-ish number identifying a release: `Tag = release`, every merge to master
bumps **patch** by default; the human declares a **minor** when they merge;
majors stay manual. Version counts merges, not significance — significance is
the human's call, encoded in the merge, never inferred.
_Avoid_: bump-as-judgment, release-note generation.

### Ledger

The issue comment history as state. Failure and reset comments on an issue are
a protocol, not prose: the attempt cap (`max_attempts`) counts them back out of
the comment history — no extra state anywhere. The **ledger module** (`devloop/ledger.py`) owns this interface: producer
functions (`failure`, `reset`) and the parsers (`count` for the attempt
cap, `budget` for both caps in one scan — max_attempts and max_per_day
read the same comment history). Marker strings are load-bearing for
comments already on live issues and never change — only append. Related
terms from AGENTS.md: trigger labels, `ready-for-human`, the `devloop: status=`
marker (the spec-loop counterpart of the ledger protocol; the spec loop lives
in `devloop/spec.py`).

### Delivery

Turning a finished agent run into a PR — or telling the issue why not. The
**delivery module** (`devloop/delivery.py`) owns this interface: one function,
`deliver()`, behind which live the verify gate (owned by its own module,
`devloop/gate.py` — one gate policy for every caller), commit,
half-delivery heal,
the delivery conflict gate, self-delivery bookkeeping, and the PR body. It
never raises: every failure path posts its own ledger comment and returns an
`Outcome` (`pr=None` means nothing shipped). A silent delivery failure is a
bug in one place, not a forgotten except clause in a caller. Review is NOT
delivery — see Review.

### Closeout

Closing the loop on a build: a human merged the devloop PR, so its issue's
lifecycle is complete. The **merge handler** (`core.handle_merge`, fired only
from a real forge merge event — never agent output) posts the
`devloop PR merged #N` ledger entry and closes the issue via
`forge.complete_issue`. Not a guardrail breach — same carve-out as `/retry`'s
close_pr: the human's merge IS the judgment that the work is done; devloop is
executing that act, not judging its own work. The completion marker is a
ledger record, never an attempt (see Ledger).

### Rebuild

A pipeline-initiated redo of a build whose branch can no longer land: a
rebase conflict with the default branch closes the PR and the issue
re-enters the queue on fresh main. Counts as an attempt against
`max_attempts` (see Ledger) — unlike **Retry** (the human's `/retry`, which
resets the budget), and unlike `ready-for-human` (the agent gave up; here
the pipeline decided the work is cheaper to redo than to resolve by hand).
Never triggered by agent output — only the sweep's rebase stage (see Sweep).

### Trigger label

A human-applied issue label that starts a build: `ai-fix`, `ai-build`,
`ai-remove` — or any repo rename **within the reserved `ai-` prefix**
(ADR-0003). Mutually exclusive — two on one issue is a config error — and
agents never apply them (see AGENTS.md). Renames live in config
(`[labels]`); the prefix is the contract the workflow template filters on,
so a config rename can never orphan the trigger. Not to be confused with
`ready-for-agent` (a triage label: specified and queued, but no build
until a trigger label lands).

### Kind

The canonical build class an issue dispatches as: `fix`, `new`, or
`remove` — mapped from the trigger label by config (`kind_for`), never
inferred from prose. Kinds key the per-kind config surface
(`[runtime.<kind>]`, prompt selection), so renaming a label within the
`ai-` prefix changes the label, never the kind. Not the same as the
trigger label itself: the label is the human-applied marker; the kind is
what the pipeline dispatches on (ADR-0004).

### Workflow template

The copy-ready GitHub Actions file an adopter starts from: `deploy/github-actions.yml`,
kept generic on purpose — it never hardcodes a label name (filters on the
reserved `ai-` prefix), the install source, the agent CLI, or the model
list; those are per-repo (see docs/environments.md). Naming the file
`devloop.yml` and editing the marked placeholders is the adopter's whole
setup. Not a devloop artifact at runtime — the pipeline never reads it;
broken template syntax breaks the adopter's workflow parser before
devloop runs (see ADR-0003 for why the filter stays prefix-based).

### Adopter

A repo running devloop against its own forge: copies the workflow template
into `.github/workflows/`, sets `[forge].repo` and the label vocabulary in
`config.toml`, and provides the agent runtime. Everything else — tool,
config schema, skills, behavior — is identical to the devloop checkout;
only authentication and scheduling differ (see docs/environments.md). The
adopter's humans keep the guardrails: labels, merges, closes. devloop
versions are not adopter versions — the adopter pins a devloop tag
(Pinning) and upgrades deliberately.

### Upgrade

An adopter's deliberate move to a newer devloop tag — a pin bump, never
auto-following master (see the Adopter entry). The boundary is the config
schema version: a devloop that doesn't speak the adopter's `config.toml`
schema errors loudly and names the fix; nothing migrates silently. Not
the same as Rebuild or Retry (pipeline-initiated redos of one build) — an
Upgrade is human-initiated and changes the pipeline itself, not one run.
Version counts merges, not significance (see Version); the CHANGELOG,
not the number, is what you read before upgrading.

### Review

Finding what's wrong before a human merges. The **review module**
(`devloop/review.py`) owns this interface: one function, `review_pr()`, behind
which live the review prompt (base template + repo guidance from
`skills/pre-review/SKILL.md` + the spec issue), per-round diff injection, the
PR-thread read, prior-findings carry between rounds, and the LGTM early-exit.
Review runs after a PR exists and is reachable on its own (`devloop review`,
`/review`). Findings only: a human reads them; the reviewer never changes
code. Review returns its final findings — the build flow hands them to Repair.

### Repair

Acting on review findings before a human reads them. The **repair module**
(`devloop/repair.py`) owns this interface: one function, `repair_pr()`, behind
which live the fixer prompt (findings + diff + spec issue + PR thread, with
repo guidance from `skills/repair/SKILL.md`), the verify gate before any push
(`devloop/gate.py`, same policy as delivery),
the commit-and-push (the fixer commits, the pipeline pushes), and the
one-round verification re-review that decides fixed vs still open. Repair is
not Review — review finds, repair acts; review stays findings-only. Repair is
not Delivery — it never opens, closes, or merges a PR; it only pushes commits
to the PR branch that already exists. Not the same as the `ai-fix` label:
`ai-fix` is an issue-level trigger a human applies to start a build; Repair is
PR-level upkeep that runs inside one.
