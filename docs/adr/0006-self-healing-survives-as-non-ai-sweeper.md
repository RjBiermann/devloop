# Self-healing survives as a non-AI sweeper

The gh-aw migration removes the Python Sweep, whose 30-min cron existed "so
missed events self-heal" (CONTEXT.md) — gh-aw is purely event-driven and has
no native missed-event catch-up, while GitHub Actions itself silently skips
cron runs under load. We accept event-driven triggering but keep the
self-healing invariant as one plain, non-AI Actions workflow: it re-fires
stuck state labels (remove + re-add, matching gh-aw's one-shot
`label_command` semantics), parses `budget:`-stamped comments per issue with
the same scan as `devloop/ledger.py`, and posts the weekly status report
(the `devloop status` successor) from state it already computes for its
re-fire decisions.

It is a probability reducer, not a guarantee — cron runs can still be
skipped — and that residual risk is accepted: the alternative (pure
event-driven) made a dropped event permanent until a human happened to
notice, which contradicted the vocabulary terms the pipeline ports.

Considered and rejected: implementing the sweeper as an agent workflow
(burns AI turns on deterministic state-machine work and adds a new way for
judgment to leak into state transitions); leaving healing to humans
(the invariant exists precisely so no one has to remember to).
