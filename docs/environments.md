# Environment guides

What changes per forge / runner. The tool, config schema, skills, and
behavior are identical everywhere — only authentication and scheduling
differ. Adapters that don't exist yet (GitLab, Gitea/Forgejo) are marked;
their sections say what's pending, not fiction.

---

## GitHub (SaaS + Enterprise Server)

Fully supported (`forge.kind = "github"`, adapter: `gh` CLI + git).

### Auth

```bash
gh auth login          # once per machine/runner
```

- The adapter shells out to `gh` and plain `git` — whatever `gh` is
  authenticated as is the agent's identity.
- Enterprise Server: the same adapter works; `gh` picks the host from your
  `GH_HOST` env or `gh auth login --hostname`.

### Running modes

| Mode | Setup |
|---|---|
| **GitHub Actions** (recommended) | copy `deploy/github-actions.yml` to `.github/workflows/devloop.yml` in the target repo. Runs on trigger-label events + `workflow_dispatch`. Needs `permissions: issues: write, pull-requests: write, contents: write` (already in the template). `GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}` makes `gh` work in-run. |
| **Local / dedicated box** | `devloop watch` (polls every `pipeline.poll_seconds`) under tmux/systemd/cron. |

### Labels

Create once per repo (names must match `config.toml [labels]`):

```bash
for spec in "ai-fix 0E8A16" "ai-build 2A6E3F" "ai-remove B60205"; do
  gh label create ${spec% *} -R OWNER/REPO --color ${spec#* } || true
done
```

### Access control

`[access] mode` maps to GitHub collaborator permissions:
`owners` → `admin` · `maintainers` → `admin|maintain` ·
`collaborators` → `admin|maintain|write`. `everyone` skips the check.
`allow`/`deny` username lists apply on top (deny wins).

### Trigger labels + branching

- Apply a trigger label to an issue → the workflow fires a build.
- Agent branches are `devloop/issue-N`; one build in flight by default
  (`pipeline.max_parallel = 1`).
- Human applies labels, human merges PRs — the workflow only builds.

---

## GitLab (SaaS + Self-Managed) — **M2, adapter pending**

Not yet usable: there is no GitLab adapter. The section will cover, once it
ships: `glab`-based adapter or token REST, project access tokens, MR
approvals (different semantics from GitHub reviews), CI job on
issue-webhook vs scheduled `devloop watch`.

Until then: no workaround — do not hand-edit label names to "make it work".

---

## Gitea / Forgejo — **M2, adapter pending**

Not yet usable. Planned: token-based REST (no `gh` equivalent), API is
GitHub-compatible so the adapter may largely reuse the GitHub one.

---

## Anywhere else (runner-agnostic)

Anything that can run a shell can run devloop — but only against forges
that have an adapter. The runner needs:

1. the checkout
2. `pip install` of devloop + a `config.toml`
3. `gh` (or the adapter's CLI) authenticated
4. `devloop once` (one pass) or `devloop watch` (poll loop)

Jenkins, Buildkite, cron, a Raspberry Pi — all identical. See MILESTONES
M2 "runner cookbook" for per-CI job examples as those land.
