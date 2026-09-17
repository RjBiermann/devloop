"""Forge interface. Every forge adapter implements this — and inherits the guardrails."""

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


@dataclass
class OpenPR:
    """An open PR scoped to what the pipeline reads about it: number, head
    branch, files touched (the delivery conflict gate's view)."""
    number: int
    head: str
    files: list[str] = field(default_factory=list)


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
        raise NotImplementedError

    # --- write side ------------------------------------------------------
    def start_work(self, number: int, branch: str) -> str:
        """Create `branch` from the default branch in a private checkout
       (parallel builds must never share a working tree — agents race on
        git state). Returns the checkout path. The Forge owns its checkouts:
        callers never name paths, and the adapter only ever deletes a
        checkout it created itself (finish_work)."""
        raise NotImplementedError

    def finish_work(self, number: int) -> None:
        """Remove the checkout start_work made for this issue. No-op when
        the issue never started (normal: kind_for can raise first)."""
        raise NotImplementedError

    def commit_all(self, message: str, workdir: str = ".") -> bool:
        """Commit + push all changes. Returns True when the branch carries
        deliverable work: staged changes, unpushed commits, or commits the
        agent already pushed without opening a PR (half-delivery). False =
        genuinely empty run — a failed delivery, not a silent success
        (callers report the agent's output to the issue)."""
        raise NotImplementedError

    def open_pr(self, branch: str, title: str, body: str) -> None:
        raise NotImplementedError

    def close_pr(self, pr_number: int, reason: str) -> None:
        """Close a PR. NOT in HUMAN_ONLY — deliberately: /retry from an
        authorized human is the sanction, and devloop closing the stale
        delivery is executing that human's explicit command. Still guarded
        one layer down: handle_command is the only caller, and it
        access-gates the author first."""
        raise NotImplementedError

    def complete_issue(self, number: int) -> None:
        """Close an issue whose devloop PR a human merged. NOT in
        HUMAN_ONLY — deliberately, same precedent as close_pr: the human
        merging the PR IS the judgment that the work is done; devloop is
        executing that act, not judging its own work. Guarded one layer
        down: handle_merge is the only caller, and it fires only from a
        real forge merge event — never from agent output."""
        raise NotImplementedError

    def pr_comments(self, pr_number: int) -> list[Comment]:
        """PR review-thread comments — the reviewer reads the thread so
        human replies ("already fixed", "out of scope") aren't ignored."""
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
        raise NotImplementedError

    def pr_diff_by_number(self, pr_number: int) -> str:
        """Unified diff of a PR by number (review-by-number mode)."""
        raise NotImplementedError

    def rebase_branch(self, branch: str) -> bool:
        """Rebase a pushed branch onto the default branch and force-push.
        False on conflicts — the caller closes the PR and rebuilds (agent
        work is cheaper to redo than human conflict resolution)."""
        raise NotImplementedError

    def open_devloop_prs(self) -> list[OpenPR]:
        """All open PRs whose head branch is devloop-owned, with the files
each touches. One snapshot read instead of a per-PR fan-out: the sweep's
slot math, the delivered-set, and the delivery conflict gate all read
this single call."""
        raise NotImplementedError

    def pr_body(self, pr_number: int) -> str:
        raise NotImplementedError

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
