# Per-kind runtime with an issue-scoped build budget

Adopters run one agent (one `[runtime].argv`) for every build kind. Field
evidence says that can't fit: on an adopting repo, `fix` builds on existing
providers finished in 6–12 min while greenfield `new`-site builds timed out
twice at 1800s and failed on both flash-tier models (issues #421, #73) —
the task shape differs by orders of magnitude, but the config couldn't
express it, so each retry burned a full attempt re-paying a doomed run.

Decision: runtime selection keys on the canonical build kind.
`[runtime.<kind>]` sections (`fix | new | remove`) hold a full `argv` that
replaces the global runtime for that kind's issue-scoped runs (build, spec
— the flows that know the issue); unlisted kinds keep the global `[runtime]`.
Kind names are canonical (`kind_for` maps trigger labels onto them), so a
label rename within the reserved `ai-` prefix (ADR-0003) can never orphan a
kind section. Unknown kind names in config fail loudly. Alongside it,
`[pipeline].build_timeout` (default 3600) is the budget for issue-scoped
runs while `[pipeline].timeout` stays for PR-scoped runs (review, repair) —
one rule: issue-scoped runs are long, PR-scoped runs are short.

Considered and rejected: per-kind timeout sections (a second dimension on
the same knob with no adopter demand), and not counting timeouts against
`max_attempts` (a timeout is not proven deterministic — a slow queue or
cold cache gets better on retry; the attempt cap stays the runaway
protection). Per-kind runtime is entirely adopter-supplied argv: the
framework stays generic, no model or repo names anywhere in it.
