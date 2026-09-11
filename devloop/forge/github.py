"""GitHub adapter — implemented on top of the `gh` CLI and plain git.

MVP choice: no SDK dependency. `gh` is ubiquitous, already authenticated
on dev machines and GitHub-hosted runners, and maps 1:1 to forge operations.
"""

from __future__ import annotations

import json
import subprocess

from .base import Comment, Forge, Issue


def _run(args: list[str], cwd: str = ".") -> str:
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{args[0]} failed: {r.stderr.strip()[:500]}")
    return r.stdout


class GitHub(Forge):
    def __init__(self, repo: str) -> None:
        self.repo = repo

    def issues_with_labels(self, labels: list[str]) -> list[Issue]:
        issues: list[Issue] = []
        for label in labels:
            out = _run([
                "gh", "issue", "list", "-R", self.repo,
                "--label", label, "--state", "open",
                "--json", "number,title,body,labels",
            ])
            for it in json.loads(out or "[]"):
                names = [l["name"] for l in it.get("labels", [])]
                issues.append(Issue(it["number"], it["title"], it.get("body") or "", names))
        # dedupe: an issue may match several labels (which is itself an error
        # the orchestrator will catch via kind_for's exclusivity check)
        seen: dict[int, Issue] = {}
        for i in issues:
            seen.setdefault(i.number, i)
        return list(seen.values())

    def issue(self, number: int) -> Issue:
        out = _run(["gh", "issue", "view", str(number), "-R", self.repo,
                    "--json", "number,title,body,labels"])
        it = json.loads(out or "{}")
        names = [l["name"] for l in it.get("labels", [])]
        return Issue(it["number"], it["title"], it.get("body") or "", names)

    def create_issue(self, title: str, body: str) -> int:
        out = _run(["gh", "issue", "create", "-R", self.repo,
                    "--title", title, "--body", body])
        return int(out.strip().rstrip("/").rsplit("/", 1)[-1])

    def edit_issue_body(self, number: int, body: str) -> None:
        _run(["gh", "issue", "edit", str(number), "-R", self.repo, "--body", body])

    def comment(self, number: int, body: str) -> None:
        _run(["gh", "issue", "comment", str(number), "-R", self.repo, "--body", body])

    def pr_comment(self, pr_number: int, body: str) -> None:
        _run(["gh", "pr", "comment", str(pr_number), "-R", self.repo, "--body", body])

    def pr_for_branch(self, branch: str) -> int | None:
        out = _run(["gh", "pr", "list", "-R", self.repo, "--head", branch,
                    "--state", "open", "--json", "number", "--jq", "[.[].number]"])
        nums = json.loads(out or "[]")
        return int(nums[0]) if nums else None

    def pr_diff(self, branch: str) -> str:
        default = _run(["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"]).strip()
        return _run(["git", "diff", f"{default}...{branch}"])

    def pr_diff_by_number(self, pr_number: int) -> str:
        return _run(["gh", "pr", "diff", str(pr_number), "-R", self.repo])

    def comments(self, number: int) -> list[Comment]:
        # --paginate: long spec conversations exceed gh's default 30-per-page
        out = _run(["gh", "api", f"repos/{self.repo}/issues/{number}/comments",
                    "--paginate", "--jq", "[.[] | {author: .user.login, body: .body}]"])
        return [Comment(it["author"], it["body"]) for it in json.loads(out or "[]")]

    def open_pr_head_branches(self) -> list[str]:
        out = _run(["gh", "pr", "list", "-R", self.repo, "--state", "open",
                    "--json", "headRefName", "--jq", "[.[].headRefName]"])
        return json.loads(out or "[]")

    # --- trigger authority (GitHub roles via collaborator permission API) ---
    def _permission(self, author: str) -> str:
        return _run(["gh", "api", f"repos/{self.repo}/collaborators/{author}/permission",
                     "--jq", ".permission"]).strip()

    def is_owner(self, author: str) -> bool:
        return self._permission(author) == "admin"

    def is_maintainer(self, author: str) -> bool:
        return self._permission(author) in {"admin", "maintain"}

    def is_collaborator(self, author: str) -> bool:
        return self._permission(author) in {"admin", "maintain", "write"}

    # --- git side (assumes the working tree IS the target repo) ----------
    def start_work(self, number: int, branch: str) -> None:
        _run(["git", "fetch", "origin"])
        default = _run(["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"]).strip()
        _run(["git", "checkout", "-B", branch, default])
        _run(["git", "push", "-u", "origin", branch])

    def commit_all(self, message: str) -> bool:
        """Commit + push all changes. Returns False when nothing changed —
        an agent run that produces no diff is a failed delivery, not a
        silent success (callers report the agent's output to the issue)."""
        _run(["git", "add", "-A"])
        r = subprocess.run(["git", "diff", "--cached", "--quiet"])
        if r.returncode == 0:
            # nothing staged — but the agent may have committed itself
            # (prompts say "leave the work committed"). Push unpushed commits.
            ahead = subprocess.run(["git", "rev-list", "--count", "@{u}..HEAD"],
                                   capture_output=True, text=True)
            if ahead.returncode == 0 and ahead.stdout.strip() not in {"", "0"}:
                _run(["git", "push"])
                return True
            return False  # genuinely empty run
        _run(["git", "commit", "-m", message])
        _run(["git", "push"])
        return True

    def open_pr(self, branch: str, title: str, body: str) -> None:
        _run(["gh", "pr", "create", "--head", branch, "--title", title, "--body", body])
