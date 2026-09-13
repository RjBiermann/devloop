# Environment guides

What changes per forge / runner. The tool, config schema, skills, and
behavior are identical everywhere — only authentication and scheduling
differ. Adapters that don't exist yet (GitLab, Gitea/Forgejo) are marked;
their sections say what's pending, not fiction.

---

## Updating devloop

Adopters upgrade deliberately: the install is pinned to a tag, and you
move the pin when you choose.

1. Read the CHANGELOG for the tags between yours and the target.
2. Bump the pinned tag in the workflow (`pip install <source>@vX.Y.Z`).
3. Push — the next sweep runs on the new version.

Two contracts hold at the boundary:

- **Config schema version is the upgrade gate.** A devloop that doesn't
  speak your `config.toml`'s schema version errors loudly at startup and
  names the fix — nothing migrates silently. (Schema 1 is current.)
- **Version counts merges, not significance** (CONTEXT.md → Version):
  patch by default, `minor:` in the merge subject declares a minor.
  Don't infer risk from the number — read the CHANGELOG.

---

## GitHub (SaaS + Enterprise Server)

Fully supported (`forge.kind = "github"`, adapter: `gh` CLI + git).

### Auth

```bash
gh auth login          # once per machine/runner
```

- The adapter shells out to `gh` and plain `git` — whatever `gh` is
  authenticated as is the agent's identity.
- Enterprise Server: set `[forge].base_url = "ghe.example.com"` in the
  repo config — the adapter injects it as `GH_HOST` on every `gh` call
  (a pre-existing `GH_HOST` env still wins for local overrides). Auth via
  `gh auth login --hostname ghe.example.com`. Git remote operations are
  untouched — the checkout's remote already points at the right host.
- **`GITHUB_TOKEN` (the Actions-provided App token) cannot push commits
  that modify files under `.github/workflows/`** — the push is rejected
  regardless of `permissions: contents: write`, and the run's work is
  silently discarded at delivery. Fine-grained PATs with **Contents +
  Workflows: read/write** are unaffected. If agent work can touch CI
  plumbing, install a PAT in place of the checkout token:

  ```yaml
  - name: PAT credentials (GITHUB_TOKEN cannot push workflow files)
    env:
      AGENT_PAT: ${{ secrets.AGENT_PAT }}
    run: |
      B64=$(printf 'x-access-token:%s' "$AGENT_PAT" | base64 -w0)
      git config http.https://github.com/.extraheader "AUTHORIZATION: basic $B64"
  ```

  The PAT must live in the `extraheader` itself — it overrides remote-URL
  credentials, so fetch and push both use it.

### Running modes

| Mode | Setup |
|---|---|
| **GitHub Actions** (recommended) | copy `deploy/github-actions.yml` to `.github/workflows/devloop.yml` in the target repo. Runs on trigger-label events + `workflow_dispatch`. Needs `permissions: issues: write, pull-requests: write, contents: write` (already in the template). `GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}` makes `gh` work in-run. |
| **Local / dedicated box** | `devloop watch` (polls every `pipeline.poll_seconds`) under tmux/systemd/cron. |

### Pinning

Pin the devloop install to a tag (`pip install <source>@vX.Y.Z`). An
unpinned install means a broken devloop commit breaks every adopting
pipeline at once — the template ships unpinned only because the install
source is per-org (your devloop checkout, not PyPI).

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
