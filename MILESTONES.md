# Milestones

## M0 — MVP (this tree)

- [x] Forge interface + GitHub adapter (gh CLI-based, no SDK deps)
- [x] AgentRuntime interface + opencode/claude/custom-argv engines
- [x] Orchestrator: trigger label → branch → agent run → verify gate → PR → issue comment
- [x] Guardrails enforced in adapter code (never merge/approve/trigger-label/close)
- [x] Bundled generic skills: spec-author, clarify, decompose, probe, verify, pre-review, drift-monitor
- [x] Spec loop: `devloop spec <n>` — clarify ↔ human back-and-forth → breakdown proposal → human `approved` → sub-issues created unlabeled + parent issue finalized
- [x] `devloop init | once | watch`
- [x] One runnable check (guardrails + trigger routing)

## M1 — GitHub hardening (first users)

- [x] Skill validation: lenient, pi-style — warn on missing/oversized
  description, invalid name chars, duplicate names; never block the run
  (`devloop.skillcheck.validate`, runs at `once`/`spec` startup)
- [x] Trigger authority: who may fire AI flows is configurable per repo
  (`[access] mode = owners|maintainers|collaborators|everyone` + allow/deny
  username lists, deny wins). Default: maintainers — AI tokens cost money,
  strangers don't get to spend them. Enforced on spec approvals today;
  every future comment command routes through `forge.is_authorized`
- [x] Layered settings: global user defaults (`~/.config/devloop/config.toml`)
  + repo `config.toml` override — org-standard knobs once, per-repo deltas
  (pi's global/project settings model). Sections deep-merge, repo wins;
  missing global file = unchanged behavior.
- [x] Budget caps: `pipeline.max_per_day` — per-issue daily attempt cap,
  counted from the dated failure comments in the ledger (runaway detection)

- [x] **First end-to-end dogfood run** on a real repo
  (RjBiermann/fictional-octo-fiesta): trigger → build → verify gate → PR →
  merge proven over ~40 PRs; review rounds spawned a full findings ladder
  (review #347 → ai-fix/ai-task issues); budget/retry machinery exercised.
  Its failures already reshaped the runtime (per-kind runtime, build budget
  split). Still unexercised: the **spec loop** (`devloop spec <n>` → clarify
  → decompose → approved → sub-issues) — every issue there was hand-authored
  or review-generated; track it as part of M2 dogfooding.
  Runtime permission denylists (below) and M2's GitLab adapter pick up from
  this repo as the live test bed.
- [x] `/retry`, `/review` comment commands — access-gated via
  `forge.is_authorized`; `/retry` resets the attempt budget, closes the
  stale devloop PR (executing an authorized human's sanction), re-fires;
  `/review` runs review rounds on demand from the thread. YAML-level gate
  in the workflow so non-command comments never spin up a runner.
  `/triage` waits for the triage agent (M2+)
- [x] Review rounds: AI pre-review N rounds, findings-only, each round
  carries the thread + its prior findings (stateless sessions that see
  the complete review state); `LGTM` stops the budget early; customizable
  via repo `skills/pre-review/SKILL.md`; on-demand via `devloop review <pr>`
- [x] Runtime permission denylists: guardrails also bind the agent's
  shell (`gh`/`git` calls the agent makes itself) — claude gets
  `--disallowedTools`, opencode gets `OPENCODE_CONFIG_CONTENT` deny rules,
  mirroring `guardrails.HUMAN_ONLY` (`devloop.runtime.DENY_COMMANDS`); the
  adapter-level wall is no longer advisory for built-in engines. Custom-argv
  engines bind their own policies.
- [x] Conflict management: parallel builds with per-build git worktrees +
  a delivery conflict gate (builds overlapping an open devloop PR's files
  defer to a later sweep; disjoint builds ship in parallel) —
  `max_parallel` is a throughput choice, never a correctness one
- [x] GitHub Enterprise Server: base-URL config on the GitHub adapter
  (`[forge].base_url` → `GH_HOST` on every gh call; SaaS + self-hosted,
  same adapter)
- [ ] Skills freshness: `.devloop/lock` (pack version + per-skill content
  hash at copy time) + `devloop skills status|update|diff` — unmodified
  copies fast-forward via a PR branch; overridden copies are never touched,
  only reported; user-added skills ignored; deletions tombstoned
- [ ] Tracking issues with verdict tables; chronic-item flags
- [ ] PR body: evidence summary + gate output template
- [x] Release discipline: CHANGELOG.md, semver policy (minor bump = opt-in
  via `minor:` in the merge subject, majors manual), auto-tag on every
  merge to master (`.github/workflows/release.yml`, ADR-0002) — shipped
  v0.1.0…v0.3.5
- [x] PR body: evidence summary + gate output template (`delivery.py` —
  agent/gate lines + agent report tail; "Human merge required" always)

## M2 — Forge breadth

- [ ] GitLab adapter (approval semantics, deploy tokens) — first demand;
  the Forge interface is unproven until a second adapter passes conformance
- [ ] Gitea/Forgejo adapter (GitHub-API-compatible; may nearly reuse the
  GitHub adapter minus `gh` — token REST instead)
- [x] Forge conformance test suite: one suite, every adapter must pass
  (`tests/conformance.py` — scenario functions + per-adapter Harness; offline
  tier: guardrails, authority ladder, git lifecycle via real git, no forge
  API; gh/glab plumbing stays adapter-specific). GitHub registered; new
  adapters join by adding a Harness.
- [ ] Config-driven label vocabulary renaming (all names overridable)
- [ ] Runner cookbook: one doc page covering GitLab CI, Jenkins, Buildkite,
  cron — all reduce to "checkout + install devloop + `devloop once`"
- [ ] Issue-tracker sync convention (docs): Jira/Linear ticket ↔ devloop
  issue link in both bodies — no adapter until a user refuses forge issues

## M3 — Hosted mode (GitHub App + service)

- [ ] GitHub App install flow (no workflow file needed per repo)
- [ ] Webhook → queue → sandboxed runners (containers or Firecracker/E2B)
- [ ] Skills update globally from the service, per-repo overrides win
- [ ] Scoped permissions via app token instead of user PAT

## M4 — Context layer

- [ ] Per-repo learning store: what worked, what reviewers flagged
- [ ] Run history + cost per workflow dashboard
- [ ] Drift history trends (monitored-unit health over time, not just today)
- [ ] Spec templates library per repo type
- [ ] Record-system sync adapters (only on paying demand): Jira,
  ServiceNow (incident → unlabeled issue; CR approval = human-only gate;
  run summaries → CR work notes as audit trail)
- [ ] Human-surface integrations (same rule): Slack/Teams trigger + status

## M5 — Ecosystem

- [ ] Skills marketplace, mirroring pi's package model (the proven design):
  - sources: `npm:` / `git:host/user/repo@pinned-ref` / local path
  - `devloop install|remove|list|update --skills` — pinned refs skipped by
    updates, `update` reconciles clones
  - per-repo filtering: enable/disable individual skills over the pack
  - scope + dedupe: global vs repo entry for the same pack, project wins
  - discovery: `devloop-package` keyword for a gallery index
- [ ] `devloop update` self-updating: staged install, run the bundled checks
  against the new version, activate only on green (pi's staged-release model);
  current install stays intact on failure
- [ ] Runtime plugins: third-party agent engines behind the same interface
- [ ] Progressive disclosure at scale: orchestration prompts carry skill
  descriptions only; full SKILL.md content loaded on demand by the agent
- [ ] Org policies: allowed models, spend caps, audit log

## Deliberately deferred

- Multi-agent orchestration (one agent per job is enough; composition is a skill concern)
- Auto-merge (contradicts the core contract; never)
- A web UI before M4 (config file + CLI covers M0–M3 users)
- **TypeScript rewrite** (considered, rejected): core is subprocess
  orchestration where stdlib Python is at its laziest; pi's patterns are
  ported as designs, not code; skills are language-neutral files. Revisit
  only if embedding as a pi extension (which can shell out to the CLI
  instead) or building an M4 UI layer (which would be TS beside a Python
  core anyway). Language promise: Python >=3.11, stdlib-only core.
