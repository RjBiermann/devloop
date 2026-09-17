"""GitHub adapter — implemented on top of the `gh` CLI and plain git.

MVP choice: no SDK dependency. `gh` is ubiquitous, already authenticated
on dev machines and GitHub-hosted runners, and maps 1:1 to forge operations.
"""

import json
import os
import shutil
import subprocess
import tempfile

from .base import Comment, Forge, Issue, OpenPR


def _ensure_identity(cwd: str) -> None:
    """Fresh CI checkouts have no git identity — agents must not guess one.
    Set the devloop identity only when unset: a human's explicit config
    (local or global) always wins. Needed at every fresh worktree: build
    worktrees for agent/pipeline commits, detached worktrees for rebase
    (rebase re-commits, so it needs committer identity too)."""
    r = subprocess.run(["git", "config", "--get", "user.email"], cwd=cwd,
                       capture_output=True)
    if r.returncode != 0:
        _run(["git", "config", "user.name", "devloop agent"], cwd=cwd)
        _run(["git", "config", "user.email",
              "devloop@users.noreply.github.com"], cwd=cwd)


def _run(args: list[str], cwd: str = ".", gh_host: str = "") -> str:
    # GHES: gh picks the host from GH_HOST (auth via `gh auth login
    # --hostname`); git calls pass gh_host="" — env untouched.
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                       env={"GH_HOST": gh_host} if gh_host else None)
    if r.returncode != 0:
        raise RuntimeError(f"{args[0]} failed: {r.stderr.strip()[:500]}")
    return r.stdout


class GitHub(Forge):
    def __init__(self, repo: str, base_url: str = "") -> None:
        self.repo = repo
        # GHES: [forge].base_url = "ghe.example.com" — carried to every gh
        # call via GH_HOST (the gh-native mechanism; auth via `gh auth login
        # --hostname`). git remote operations are untouched: the checkout's
        # remote already points at the right host.
        self._gh_host = base_url.removeprefix("https://").removeprefix("http://").rstrip("/")
        # checkout registry: issue number → worktree path. start_work and
        # finish_work are the only code that creates or deletes these, so
        # the adapter can never rmtree a path it did not create itself
        # (the old caller-supplied-workdir interface allowed rmtree('.')).
        self._checkouts: dict[int, str] = {}

    def issues_with_labels(self, labels: list[str]) -> list[Issue]:
        issues: list[Issue] = []
        for label in labels:
            out = _run([
                "gh", "issue", "list", "-R", self.repo,
                "--label", label, "--state", "open",
                "--json", "number,title,body,labels",
            ], gh_host=self._gh_host)
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
                    "--json", "number,title,body,labels"], gh_host=self._gh_host)
        it = json.loads(out or "{}")
        names = [l["name"] for l in it.get("labels", [])]
        return Issue(it["number"], it["title"], it.get("body") or "", names)

    def create_issue(self, title: str, body: str) -> int:
        out = _run(["gh", "issue", "create", "-R", self.repo,
                    "--title", title, "--body", body], gh_host=self._gh_host)
        return int(out.strip().rstrip("/").rsplit("/", 1)[-1])

    def edit_issue_body(self, number: int, body: str) -> None:
        _run(["gh", "issue", "edit", str(number), "-R", self.repo, "--body", body], gh_host=self._gh_host)

    def comment(self, number: int, body: str) -> None:
        _run(["gh", "issue", "comment", str(number), "-R", self.repo, "--body", body], gh_host=self._gh_host)

    def pr_comment(self, pr_number: int, body: str) -> None:
        _run(["gh", "pr", "comment", str(pr_number), "-R", self.repo, "--body", body], gh_host=self._gh_host)

    def pr_for_branch(self, branch: str) -> int | None:
        out = _run(["gh", "pr", "list", "-R", self.repo, "--head", branch,
                    "--state", "open", "--json", "number", "--jq", "[.[].number]"], gh_host=self._gh_host)
        nums = json.loads(out or "[]")
        return int(nums[0]) if nums else None

    def pr_diff_by_number(self, pr_number: int) -> str:
        return _run(["gh", "pr", "diff", str(pr_number), "-R", self.repo], gh_host=self._gh_host)

    def pr_body(self, pr_number: int) -> str:
        return _run(["gh", "pr", "view", str(pr_number), "-R", self.repo, "--json", "body",
                     "--jq", ".body"], gh_host=self._gh_host) or ""

    def comments(self, number: int) -> list[Comment]:
        # --paginate: long spec conversations exceed gh's default 30-per-page
        out = _run(["gh", "api", f"repos/{self.repo}/issues/{number}/comments",
                    "--paginate", "--jq", "[.[] | {author: .user.login, body: .body}]"], gh_host=self._gh_host)
        return [Comment(it["author"], it["body"]) for it in json.loads(out or "[]")]

    def pr_comments(self, pr_number: int) -> list[Comment]:
        # PR comments live on the issue endpoint with the same number
        return self.comments(pr_number)

    def rebase_branch(self, branch: str) -> bool:
        """Rebase a pushed branch onto the default branch and force-push.
        False on conflicts — the caller closes the PR and rebuilds (agent
        work is cheaper to redo than human conflict resolution)."""
        _run(["git", "fetch", "origin"])
        default = _run(["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"]).strip()
        wt = tempfile.mkdtemp(prefix="devloop-rebase-") + "/tree"
        # rebase the remote ref, not the bare name: a CI checkout has no local
        # branch for a PR opened by a previous run (fetch created origin/<branch>,
        # not <branch>) — 'invalid reference' otherwise
        _run(["git", "worktree", "add", "--detach", wt, f"origin/{branch}"])
        _ensure_identity(wt)
        try:
            r = subprocess.run(["git", "rebase", default], cwd=wt,
                               capture_output=True, text=True)
            if r.returncode != 0:
                subprocess.run(["git", "rebase", "--abort"], cwd=wt)
                return False
            # detached worktree: rebase moved HEAD, not the branch ref —
            # repoint it before pushing, or the push re-pushes the stale tip
            # (update-ref, not branch -f: branch -f refuses when any worktree
            # entry — even a stale one — still names the branch)
            sha = _run(["git", "rev-parse", "HEAD"], cwd=wt).strip()
            _run(["git", "update-ref", f"refs/heads/{branch}", sha], cwd=wt)
            _run(["git", "push", "--force-with-lease", "origin", branch], cwd=wt)
            return True
        finally:
            shutil.rmtree(os.path.dirname(wt), ignore_errors=True)
            subprocess.run(["git", "worktree", "prune"], capture_output=True)

    def open_devloop_prs(self) -> list[OpenPR]:
        """One gh call for the whole open-devloop-PR picture (number, head,
files) — the sweep and the delivery conflict gate read this snapshot;
they never fan out per-PR."""
        out = _run(["gh", "pr", "list", "-R", self.repo, "--state", "open",
                    "--json", "number,headRefName,files"], gh_host=self._gh_host)
        return [OpenPR(it["number"], it["headRefName"],
                       [f["path"] for f in it.get("files", [])])
                for it in json.loads(out or "[]")
                if it["headRefName"].startswith("devloop/")]

    # --- trigger authority (GitHub roles via collaborator permission API) ---
    def _permission(self, author: str) -> str:
        return _run(["gh", "api", f"repos/{self.repo}/collaborators/{author}/permission",
                     "--jq", ".permission"], gh_host=self._gh_host).strip()

    def is_owner(self, author: str) -> bool:
        return self._permission(author) == "admin"

    def is_maintainer(self, author: str) -> bool:
        return self._permission(author) in {"admin", "maintain"}

    def is_collaborator(self, author: str) -> bool:
        return self._permission(author) in {"admin", "maintain", "write"}

    # --- git side (assumes the working tree IS the target repo) ----------
    def start_work(self, number: int, branch: str) -> str:
        """Create the build checkout: one git worktree per issue, path owned
        by the adapter and registered for finish_work."""
        _run(["git", "fetch", "origin"])
        # heal crash leftovers: an uncleanly-removed worktree leaves admin
        # entries that block worktree add on the same branch/path forever
        _run(["git", "worktree", "prune"])
        parent = tempfile.mkdtemp(prefix=f"devloop-{number}-")
        workdir = parent + "/tree"
        default = _run(["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"]).strip()
        _run(["git", "worktree", "add", "-B", branch, workdir, default])
        _ensure_identity(workdir)
        self._checkouts[number] = workdir
        # force when the remote branch already exists (a deferred or abandoned
        # build): this branch is devloop-owned, the worktree is fresh from main
        exists = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"origin/{branch}"],
            capture_output=True).returncode == 0
        push = ["git", "push", "--force", "-u", "origin", branch] if exists \
            else ["git", "push", "-u", "origin", branch]
        _run(push, cwd=workdir)
        return workdir

    def finish_work(self, number: int) -> None:
        """Remove this issue's checkout — only ever a path this adapter
        created. Deleting caller-supplied paths (the old interface allowed
        rmtree('.')) is structurally impossible."""
        path = self._checkouts.pop(number, None)
        if path is None:
            return  # never started (normal) or already finished
        shutil.rmtree(os.path.dirname(path), ignore_errors=True)
        _run(["git", "worktree", "prune"])

    def commit_all(self, message: str, workdir: str = ".") -> bool:
        """Commit + push all changes. Returns True when the branch carries
        deliverable work: staged changes, unpushed commits, or commits the
        agent already pushed without opening a PR (half-delivery).
        False = genuinely empty run."""
        _run(["git", "add", "-A"], cwd=workdir)
        r = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=workdir)
        if r.returncode == 0:
            # nothing staged — but the agent may have committed itself
            # (prompts say "leave the work committed"). Push unpushed commits.
            ahead = subprocess.run(["git", "rev-list", "--count", "@{u}..HEAD"],
                                   capture_output=True, text=True, cwd=workdir)
            if ahead.returncode == 0 and ahead.stdout.strip() not in {"", "0"}:
                _run(["git", "push"], cwd=workdir)
                return True
            # already pushed, no PR yet: still deliverable work (half-delivery)
            pushed = subprocess.run(
                ["git", "rev-list", "--count", "origin/HEAD..HEAD"],
                capture_output=True, text=True, cwd=workdir)
            return pushed.returncode == 0 and pushed.stdout.strip() not in {"", "0"}
        _run(["git", "commit", "-m", message], cwd=workdir)
        _run(["git", "push"], cwd=workdir)
        return True

    def open_pr(self, branch: str, title: str, body: str) -> None:
        _run(["gh", "pr", "create", "--head", branch, "--title", title, "--body", body], gh_host=self._gh_host)

    def close_pr(self, pr_number: int, reason: str) -> None:
        _run(["gh", "pr", "close", str(pr_number), "-R", self.repo,
              "--comment", reason, "--delete-branch"], gh_host=self._gh_host)

    def complete_issue(self, number: int) -> None:
        _run(["gh", "issue", "close", str(number), "-R", self.repo], gh_host=self._gh_host)

    def branch_files(self, branch: str) -> list[str]:
        default = _run(["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"]).strip()
        out = _run(["git", "diff", "--name-only", f"{default}...{branch}"])
        return [f for f in out.splitlines() if f.strip()]
