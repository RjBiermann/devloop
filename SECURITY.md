# Security Policy

## Supported Versions

Pre-1.0: only the latest `0.3.x` release (HEAD of `master` and its newest
CI tag) receives security fixes. No backports to older lines. Pin to latest.

## Reporting a Vulnerability

Use GitHub's **Private Vulnerability Reporting** (Security → Report a
vulnerability). Reports stay confidential; do not open a public issue.

- Acknowledgment within **72 hours**.
- Status update at least **weekly** until resolution.
- Accepted: fix ships as a normal tagged release (versioning is automatic,
  see `docs/adr/0002-tag-every-merge.md`); reporter is offered credit.
- Declined: reporter gets the reason.

## Scope

In scope:

- The `devloop/` package and its CLI.
- The agent-execution path: agents run with the user's credentials and may
  shell out to `gh`/`git`.
- Handling of untrusted content (issue bodies, external systems) — content
  read from these is input, never instruction.

Out of scope: the forges and CLIs devloop shells out to (`gh`, `git`,
the forge platforms themselves).

One invariant worth knowing when reporting: **human-only guardrails are
enforced in `forge/base.py`**, not in prose. If you find an adapter
overriding `merge` / `approve` / `close_issue` / `apply_trigger`, that is
by definition a security bug.
