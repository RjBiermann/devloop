"""Forge conformance suite: one set of scenarios, every adapter must pass.

Scope (the interface contract, not the transport):
- guardrails: human-only ops are blocked in the base and never overridden
- trigger authority: role predicates ladder correctly; is_authorized matrix
- git-side lifecycle: start_work/finish_work ownership, commit_all delivery
  semantics, branch_files, rebase_branch — real git, no forge API

The forge-API plumbing (gh/glab flags, JSON shapes) is adapter-specific and
stays in each adapter's own tests — it cannot be shared, so it is not part
of conformance.

An adapter joins by writing a Harness and registering it in ADAPTERS;
tests/test_devloop.py runs every registered harness automatically.
"""

import os
import shutil
import subprocess
import tempfile

from devloop.config import Access
from devloop.forge.base import Forge
from devloop.guardrails import GuardrailViolation, HUMAN_ONLY


class Harness:
    """Per-adapter fixture. setup() prepares a controlled environment and
    enters the repo working dir; teardown() restores everything."""

    name = "?"
    forge: Forge

    def setup(self) -> None:
        raise NotImplementedError

    def set_role(self, author: str, role: str) -> None:
        """Map author to one of owner | maintainer | collaborator | none —
        whatever the forge's native mechanism is."""
        raise NotImplementedError

    def teardown(self) -> None:
        raise NotImplementedError


# --- scenarios ----------------------------------------------------------
# Each takes (h) and raises AssertionError on contract violation.

def check_guardrails_blocked(h: Harness) -> None:
    """The four human-only ops raise, and no adapter can forget: none of
    them is overridden (the base's raise is the implementation, not a
    default an adapter replaces). The two carve-outs stay out of the set."""
    f = h.forge
    for op in ("merge", "approve", "close_issue", "apply_trigger"):
        assert getattr(type(f), op) is getattr(Forge, op), \
            f"{h.name} overrides human-only op {op!r} — that's a bug"
        try:
            arg = (1, "ai-build") if op == "apply_trigger" else (1,)
            getattr(f, op)(*arg)
        except GuardrailViolation:
            pass
        else:
            raise AssertionError(f"{h.name}: {op} must stay human-only")
    assert "complete_issue" not in HUMAN_ONLY and "close_pr" not in HUMAN_ONLY


def check_authority_ladder(h: Harness) -> None:
    """Role predicates are a strict ladder: owner ⊃ maintainer ⊃
    collaborator ⊃ nobody."""
    f = h.forge
    for author, role in [("own", "owner"), ("mnt", "maintainer"),
                         ("wri", "collaborator"), ("out", "none")]:
        h.set_role(author, role)
    assert f.is_owner("own") and not f.is_owner("mnt") and not f.is_owner("wri")
    assert f.is_maintainer("own") and f.is_maintainer("mnt") \
        and not f.is_maintainer("wri")
    assert f.is_collaborator("wri") and not f.is_collaborator("out")


def check_authorization_matrix(h: Harness) -> None:
    """is_authorized: deny wins over everything, allow bypasses mode,
    mode picks the rung, default is maintainers, usernames case-insensitive."""
    f = h.forge
    for author, role in [("own", "owner"), ("mnt", "maintainer"),
                         ("wri", "collaborator"), ("out", "none")]:
        h.set_role(author, role)
    assert not f.is_authorized("own", Access(mode="owners", deny=["own"]))
    assert f.is_authorized("out", Access(mode="maintainers", allow=["out"]))
    assert f.is_authorized("mnt", Access(mode="maintainers"))
    assert not f.is_authorized("wri", Access(mode="maintainers"))
    assert f.is_authorized("own", Access(mode="owners"))
    assert not f.is_authorized("mnt", Access(mode="owners"))
    assert f.is_authorized("wri", Access(mode="collaborators"))
    assert f.is_authorized("out", Access(mode="everyone"))
    assert f.is_authorized("OWN", Access(mode="owners"))


def check_checkout_lifecycle(h: Harness) -> None:
    """start_work gives a fresh checkout per issue (parallel builds never
    share a tree), finish_work removes only what it created and tolerates
    never-started issues."""
    f = h.forge
    w1 = f.start_work(1, "devloop/issue-1")
    w2 = f.start_work(2, "devloop/issue-2")
    assert w1 != w2 and os.path.isdir(w1) and os.path.isdir(w2)
    f.finish_work(1)
    assert not os.path.exists(w1) and os.path.isdir(w2)
    f.finish_work(3)  # never started: no-op, no raise
    f.finish_work(2)
    assert not os.path.exists(w2)


def check_commit_all_semantics(h: Harness) -> None:
    """True = deliverable work (staged, unpushed commits, half-delivery);
    False = genuinely empty run."""
    f = h.forge
    w = f.start_work(1, "devloop/issue-1")
    assert f.commit_all("devloop: fixes #1", w) is False          # empty run
    open(f"{w}/work.txt", "w").write("x")
    assert f.commit_all("devloop: fixes #1", w) is True           # staged
    subprocess.run(["git", "commit", "--allow-empty", "-qm", "agent work"],
                   cwd=w, capture_output=True)
    assert f.commit_all("devloop: fixes #1", w) is True           # unpushed
    f.finish_work(1)
    w = f.start_work(2, "devloop/issue-2")
    subprocess.run(["git", "commit", "--allow-empty", "-qm", "agent work"],
                   cwd=w, capture_output=True)
    subprocess.run(["git", "push", "-q"], cwd=w, capture_output=True)
    assert f.commit_all("devloop: fixes #2", w) is True           # half-delivery
    f.finish_work(2)


def check_branch_files(h: Harness) -> None:
    """branch_files = the conflict gate's scope view of a branch vs default."""
    f = h.forge
    w = f.start_work(1, "devloop/issue-1")
    open(f"{w}/scope.txt", "w").write("x")
    for cmd in (["add", "-A"], ["commit", "-qm", "scope"], ["push", "-q"]):
        subprocess.run(["git", *cmd], cwd=w, capture_output=True)
    assert f.branch_files("devloop/issue-1") == ["scope.txt"]
    f.finish_work(1)


def check_rebase_branch(h: Harness) -> None:
    """True on clean rebase (branch carries default), False on conflict."""
    f = h.forge
    # clean rebase: default moves without touching the branch's file
    w = f.start_work(1, "devloop/issue-1")
    open(f"{w}/a.txt", "w").write("branch\n")
    for cmd in (["add", "-A"], ["commit", "-qm", "branch work"], ["push", "-q"]):
        subprocess.run(["git", *cmd], cwd=w, capture_output=True)
    h.advance_default([])  # empty commit on main, pushed
    assert f.rebase_branch("devloop/issue-1") is True
    f.finish_work(1)
    # conflict: both sides touch b.txt
    w = f.start_work(2, "devloop/issue-2")
    open(f"{w}/b.txt", "w").write("branch\n")
    for cmd in (["add", "-A"], ["commit", "-qm", "b branch"], ["push", "-q"]):
        subprocess.run(["git", *cmd], cwd=w, capture_output=True)
    h.advance_default([("b.txt", "main\n")])
    assert f.rebase_branch("devloop/issue-2") is False
    f.finish_work(2)


OFFLINE_SCENARIOS = [
    check_guardrails_blocked,
    check_authority_ladder,
    check_authorization_matrix,
    check_checkout_lifecycle,
    check_commit_all_semantics,
    check_branch_files,
    check_rebase_branch,
]


def run_offline(harness_cls) -> list[str]:
    """Run every offline scenario over one harness; return failure messages
    (empty list = all pass)."""
    h = harness_cls()
    failures: list[str] = []
    h.setup()
    try:
        for check in OFFLINE_SCENARIOS:
            try:
                check(h)
            except Exception as e:  # noqa: BLE001 — collect, don't stop
                failures.append(f"{h.name}/{check.__name__}: {e}")
    finally:
        h.teardown()
    return failures


# --- adapters -----------------------------------------------------------

class GitHubHarness(Harness):
    """GitHub adapter, offline tier: real git against a local bare remote.
    The gh-side role API is stubbed — the ladder mapping is the contract."""

    name = "github"

    def setup(self) -> None:
        from devloop.forge.github import GitHub
        self._tmp = tempfile.mkdtemp(prefix="devloop-conf-")
        self._old = os.getcwd()
        bare = f"{self._tmp}/origin.git"
        subprocess.run(["git", "init", "--bare", "-q", "-b", "main", bare],
                       check=True)
        self.main_checkout = f"{self._tmp}/main"
        subprocess.run(["git", "clone", "-q", bare, self.main_checkout],
                       check=True)
        self._g("checkout", "-qb", "main")  # fix the branch name pre-seed
        self._g("config", "user.email", "conf@test")
        self._g("config", "user.name", "conf")
        open(f"{self.main_checkout}/seed.txt", "w").write("seed\n")
        self._g("add", "-A")
        self._g("commit", "-m", "seed")
        self._g("push", "-qu", "origin", "main")
        self._g("remote", "set-head", "origin", "-a")
        os.chdir(self.main_checkout)
        self.forge = GitHub("local/remote")
        self._roles: dict[str, str] = {}
        self.forge._permission = self._stub_permission  # conformance stub

    def _g(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self.main_checkout, check=True,
                       capture_output=True)

    def advance_default(self, files: list[tuple[str, str]]) -> None:
        for name, content in files:
            open(f"{self.main_checkout}/{name}", "w").write(content)
        self._g("add", "-A")
        self._g("commit", "-q", "--allow-empty", "-m", "main moves")
        self._g("push", "-q")

    def _stub_permission(self, author: str) -> str:
        return {"owner": "admin", "maintainer": "maintain",
                "collaborator": "write"}.get(
            self._roles.get(author.lower()), "none")

    def set_role(self, author: str, role: str) -> None:
        self._roles[author.lower()] = role

    def teardown(self) -> None:
        os.chdir(self._old)
        shutil.rmtree(self._tmp, ignore_errors=True)


ADAPTERS = [GitHubHarness]
