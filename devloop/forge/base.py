"""Forge interface. Every forge adapter implements this — and inherits the guardrails."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..guardrails import HUMAN_ONLY, GuardrailViolation


@dataclass
class Issue:
    number: int
    title: str
    body: str
    labels: list[str] = field(default_factory=list)


@dataclass
class Comment:
    author: str
    body: str


class Forge:
    """Adapter for one git forge. Subclasses implement the primitives;
    guardrails are enforced here in the base so no adapter can forget."""

    # --- read side -------------------------------------------------------
    def issues_with_labels(self, labels: list[str]) -> list[Issue]:
        raise NotImplementedError

    def issue(self, number: int) -> Issue:
        raise NotImplementedError

    def create_issue(self, title: str, body: str) -> int:
        """Create an issue. Returns its number. NEVER carries a trigger label —
        the human decides which stories to build."""
        raise NotImplementedError

    def edit_issue_body(self, number: int, body: str) -> None:
        raise NotImplementedError

    def comments(self, number: int) -> list[Comment]:
        return []

    # --- write side ------------------------------------------------------
    def start_work(self, number: int, branch: str, workdir: str = ".") -> None:
        """Create `branch` from the default branch, in its own git worktree
        at `workdir` (parallel builds each get a private checkout — agents
        must never share a working tree)."""
        raise NotImplementedError

    def commit_all(self, message: str, workdir: str = ".") -> bool:
        """Commit + push all changes. Returns False when nothing changed —
        an agent run that produces no diff is a failed delivery, not a
        silent success (callers report the agent's output to the issue)."""
        raise NotImplementedError

    def open_pr(self, branch: str, title: str, body: str) -> None:
        raise NotImplementedError

    def pr_files(self, pr_number: int) -> list[str]:
        """Files touched by an open PR (for the delivery conflict gate)."""
        raise NotImplementedError

    def branch_files(self, branch: str) -> list[str]:
        """Files a pushed branch changes vs the default branch — the
        conflict gate's view of a build's scope before it has a PR."""
        raise NotImplementedError

    def comment(self, number: int, body: str) -> None:
        raise NotImplementedError

    def pr_comment(self, pr_number: int, body: str) -> None:
        raise NotImplementedError

    def pr_for_branch(self, branch: str) -> int | None:
        """Number of the open PR with this head branch, if any. An agent may
        self-deliver (its own commit + push + gh pr create) — the pipeline
        must recognize that and honor it, not report it as a failure."""
        return None

    def pr_diff(self, branch: str) -> str:
        """Unified diff of branch vs the default branch (for AI review)."""
        return ""

    def pr_diff_by_number(self, pr_number: int) -> str:
        """Unified diff of a PR by number (review-by-number mode)."""
        return ""

    def pr_body(self, pr_number: int) -> str:
        return ""

    # --- human-only operations: blocked in the base -----------------------
    def merge(self, pr_number: int) -> None:
        self._human_only("merge")

    def approve(self, pr_number: int) -> None:
        self._human_only("approve")

    def close_issue(self, number: int) -> None:
        self._human_only("close_issue")

    def apply_trigger(self, number: int, label: str) -> None:
        self._human_only("apply_trigger")

    def _human_only(self, op: str) -> None:
        assert op in HUMAN_ONLY
        raise GuardrailViolation(
            f"{op!r} is human-only — agents may never {op} (guardrail: {op})"
        )

    # --- trigger authority: who may fire AI flows -------------------------
    # AI tokens cost money — default is the narrowest useful set (maintainers),
    # configurable per repo: owners | maintainers | collaborators | everyone,
    # with allow/deny username lists on top (deny wins).
    def is_owner(self, author: str) -> bool:
        raise NotImplementedError

    def is_maintainer(self, author: str) -> bool:
        raise NotImplementedError

    def is_collaborator(self, author: str) -> bool:
        raise NotImplementedError

    def is_authorized(self, author: str, access) -> bool:
        # usernames are case-insensitive on GitHub-family forges
        a = author.lower()
        if a in {d.lower() for d in access.deny}:
            return False
        if a in {u.lower() for u in access.allow}:
            return True
        if access.mode == "everyone":
            return True
        if access.mode == "owners":
            return self.is_owner(author)
        if access.mode == "collaborators":
            return self.is_collaborator(author)
        return self.is_maintainer(author)  # default: maintainers
