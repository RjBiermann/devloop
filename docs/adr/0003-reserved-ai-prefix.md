# Reserved `ai-` prefix as the trigger-label contract

Trigger labels were named in two places: `config.toml [labels]` (declared
"rename freely") and the `deploy/github-actions.yml` event filter
(hardcoded `ai-fix` / `ai-build` / `ai-remove`). An adopting repo renamed
its labels in config and the workflow silently stopped firing — the filter
never learned about the rename. Renaming via re-running `devloop init`
would just add a second sync point, the same class of bug.

Decision: the `ai-` prefix is reserved vocabulary. Config renames stay
legal within the namespace (`ai-new-site`, not `agent-fix`); the template
filters on `startsWith(github.event.label.name, 'ai-')` and never hardcodes
names. False positives (a non-trigger `ai-*` label) are cheap: `run_once`
no-ops when no issue carries a configured trigger.

Considered and rejected: filter-less template (every irrelevant label burns
a full CI run — checkout, install, sweep — on busy repos) and generated
filters from config (the sync-point bug again). Renaming outside the
namespace is the one thing the glossary forbids; if a repo ever needs it,
that's a new decision, not a config edit.
