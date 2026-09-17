"""The one check: guardrails hold and trigger routing is correct."""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from devloop.config import Access, Config, Labels, Pipeline
from devloop.forge.base import Comment, Forge, Issue
from devloop.guardrails import GuardrailViolation


def test_human_only_ops_are_blocked():
    forge = Forge()  # base class: guardrails enforced, adapters inherit

    for call in [
        lambda: forge.merge(1),
        lambda: forge.approve(1),
        lambda: forge.close_issue(1),
        lambda: forge.apply_trigger(1, "ai-fix"),
    ]:
        try:
            call()
        except GuardrailViolation:
            pass
        else:
            raise AssertionError("human-only operation did not raise")


def test_spec_state_machine():
    from devloop.spec import MARKER, parse_status, spec_phase

    class EveryoneForge(Forge):
        """every commenter authorized — isolates the state-machine logic"""
        def is_maintainer(self, a): return True
        def is_owner(self, a): return True
        def is_collaborator(self, a): return True

    forge, access = EveryoneForge(), Access(mode="everyone")

    assert parse_status("blah\ndevloop: status=clarify") == "clarify"
    assert parse_status("devloop: status=propose.") == "propose"
    assert parse_status("no marker here") is None
    assert parse_status("a\ndevloop: status=clarify\nb\ndevloop: status=finalized") == "finalized"

    assert spec_phase([], forge, access) == "clarify"
    assert spec_phase([Comment("h", f"x\n{MARKER}propose")], forge, access) == "propose"
    # authorized 'approved' after a proposal → finalized, ready to build
    assert spec_phase([Comment("h", f"q\n{MARKER}propose"),
                       Comment("human", "Approved"),
                       Comment("h", f"{MARKER}propose")], forge, access) == "finalized"
    # proposal + approval WITHOUT the agent's proposal marker stays clarify
    assert spec_phase([Comment("human", "approved")], forge, access) == "clarify"
    assert spec_phase([Comment("h", f"{MARKER}finalized")], forge, access) == "finalized"


def test_spec_never_reprocesses_finalized():
    """Terminal state: a finalized spec gets no second agent round."""
    from devloop.spec import process_spec

    calls = []

    class DoneForge(Forge):
        def comments(self, _n):
            return [Comment("agent", f"summary\ndevloop: status=finalized")]

        def is_maintainer(self, a): return True
        def is_owner(self, a): return True
        def is_collaborator(self, a): return True

        def issue(self, _n):
            raise AssertionError("finalized issue must not be re-fetched")

        def comment(self, _n, body):
            calls.append(body)

    class NoRuntime:
        def run(self, *_a, **_k):
            raise AssertionError("agent must not run on a finalized spec")

    from devloop.config import Config

    assert process_spec(Config(repo="o/r"), DoneForge(), NoRuntime(), 1) == "finalized"
    assert not calls


def test_run_once_skips_issues_with_open_pr():
    from devloop.config import Config
    from devloop.core import run_once

    class FakeForge(Forge):
        def issues_with_labels(self, _labels):
            return [
                self._issue(1, ["ai-fix"]),
                self._issue(2, ["ai-fix"]),
            ]

        def _issue(self, n, labels):
            return type("I", (), {"number": n, "title": f"t{n}", "body": "", "labels": labels})()

        def open_devloop_prs(self):
            from devloop.forge.base import OpenPR
            return [OpenPR(1, "devloop/issue-1", [])]

        def rebase_branch(self, branch):
            return True

        def start_work(self, *a):
            raise AssertionError("issue with open PR must be skipped")

        def comments(self, _n):
            return []  # ledger reads the issue; no failures recorded here

    class FakeRuntime:
        name = "fake"

        def run(self, prompt, cwd, timeout):
            return type("R", (), {"ok": True, "output": ""})()

    processed = []
    cfg = Config(repo="o/r", pipeline=Pipeline(max_parallel=2))  # queue headroom so #2 runs
    forge = FakeForge()

    # process_issue calls the git-side methods; only stub what skip-logic needs
    import devloop.core as core

    orig = core.process_issue

    def spy(cfg, forge, runtime, issue, workdir=None):
        processed.append((issue.number, workdir))
        return type("O", (), {"issue": issue.number, "branch": "", "delivered": True, "gate": True})()

    core.process_issue = spy
    try:
        run_once(cfg, FakeForge(), FakeRuntime())
    finally:
        core.process_issue = orig
    assert [n for n, _ in processed] == [2]  # #1 skipped: PR already open


def test_trigger_authority_defaults_and_overrides():
    """AI tokens cost money: default = maintainers only, configurable up or
    down; allow/deny lists override mode, deny wins."""
    from devloop.config import Access

    class FakeForge(Forge):
        def __init__(self, perms):
            self._p = perms

        def is_owner(self, a): return self._p.get(a) == "admin"
        def is_maintainer(self, a): return self._p.get(a) in {"admin", "maintain"}
        def is_collaborator(self, a): return self._p.get(a) in {"admin", "maintain", "write"}

    f = FakeForge({"boss": "admin", "dev": "maintain", "triager": "write", "stranger": "read"})

    # default: maintainers only
    acc = Access()
    assert f.is_authorized("boss", acc) and f.is_authorized("dev", acc)
    assert not f.is_authorized("triager", acc)
    assert not f.is_authorized("stranger", acc)

    # widened to collaborators / everyone
    assert f.is_authorized("triager", Access(mode="collaborators"))
    assert f.is_authorized("stranger", Access(mode="everyone"))

    # narrowed to owners
    assert f.is_authorized("boss", Access(mode="owners"))
    assert not f.is_authorized("dev", Access(mode="owners"))

    # allow list grants (case-insensitive — GitHub usernames are); deny wins
    acc = Access(mode="maintainers", allow=["TriageR"])
    assert f.is_authorized("triager", acc)
    acc = Access(mode="everyone", deny=["STRANGER"])
    assert not f.is_authorized("stranger", acc)


def test_trigger_labels_are_mutually_exclusive():
    cfg = Config(repo="o/r")
    assert cfg.kind_for(["ai-fix"]) == "fix"
    assert cfg.kind_for(["ai-build"]) == "new"
    assert cfg.kind_for(["ai-remove"]) == "remove"
    assert cfg.kind_for(["bug", "needs-info"]) is None
    try:
        cfg.kind_for(["ai-fix", "ai-build"])
    except Exception:
        pass
    else:
        raise AssertionError("double trigger did not raise")


def test_queue_full_starts_nothing():
    """Serial builds: with max_parallel=1 and one devloop PR open, no new
    builds start — conflicts are prevented by construction, not merged."""
    import devloop.core as core
    from devloop.config import Config
    from devloop.core import run_once

    class QueueForge(Forge):
        def open_devloop_prs(self):
            from devloop.forge.base import OpenPR
            return [OpenPR(9, "devloop/issue-9", [])]

        def rebase_branch(self, branch):
            return True  # upkeep runs even when full — it frees the queue

        def issues_with_labels(self, _l):
            raise AssertionError("must not even list issues when queue is full")

    assert run_once(Config(repo="o/r"), QueueForge(), None) == []

    class ParallelForge(QueueForge):
        def issues_with_labels(self, _l):
            return []  # listed when parallelism allows

    assert run_once(Config(repo="o/r", pipeline=Pipeline(max_parallel=2)), ParallelForge(), None) == []


def test_skillcheck_warns_and_never_blocks():
    import tempfile
    from devloop.skillcheck import validate_skills

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        good = root / "good"
        good.mkdir()
        (good / "SKILL.md").write_text(
            "---\nname: good-skill\ndescription: Does a thing.\n---\nbody")
        bad_desc = root / "bad-desc"
        bad_desc.mkdir()
        (bad_desc / "SKILL.md").write_text("---\nname: bad-desc\n---\nbody")
        bad_name = root / "bad_name"
        bad_name.mkdir()
        (bad_name / "SKILL.md").write_text(
            "---\nname: Bad_Name!\ndescription: x\n---\nbody")
        no_fm = root / "no-frontmatter"
        no_fm.mkdir()
        (no_fm / "SKILL.md").write_text("just text")

        warnings = validate_skills([root])
        text = "\n".join(warnings)
        # good skill: silent. bad ones: warned. nothing raises.
        assert not any("good-skill" in w for w in warnings)
        assert "bad-desc" in text and "description" in text
        assert "Bad_Name!" in text
        assert "no frontmatter" in text
        assert validate_skills([root / "nonexistent"]) == []  # missing path is normal, no warning


def test_access_mode_typo_fails_loudly():
    """An access-control typo must error, not silently narrow or widen."""
    import tempfile
    from devloop.config import ConfigError, load

    for bad in ["everyon", "Maintainers", "all"]:
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as fh:
            fh.write(f'[forge]\nrepo = "o/n"\n[access]\nmode = "{bad}"\n')
            path = fh.name
        try:
            load(path)
        except ConfigError as e:
            assert bad in str(e)
        else:
            raise AssertionError(f"unknown mode {bad!r} did not raise")


def test_config_version_guard():
    import tempfile
    from devloop.config import ConfigError, load

    with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
        f.write("version = 99\n[forge]\nrepo = 'o/n'\n")
        path = f.name
    try:
        load(path)
    except ConfigError as e:
        assert "99" in str(e)
    else:
        raise AssertionError("future config version did not raise")


def test_renamed_labels_route():
    cfg = Config(repo="o/r", labels=Labels(fix="needs-robot", new="needs-robot-new"))
    assert cfg.kind_for(["needs-robot"]) == "fix"
    assert cfg.kind_for(["ai-fix"]) is None  # renamed away: old label inert



class FlowForge(Forge):
    """FakeForge wired for the full process_issue flow: agent 'commits and
    pushes' (commit_all True), open_pr recorded, branch_files and the
    open_devloop_prs snapshot overridable to stage conflict-gate scenarios."""

    def __init__(self, open_prs=()):
        self.prs = []
        self.notes = []
        self.cwds = []
        self.finished = []
        self._open_prs = list(open_prs)

    def issues_with_labels(self, _l):
        return [Issue(n, f"t{n}", "", ["ai-fix"]) for n in (1, 2)]

    def open_devloop_prs(self):
        return list(self._open_prs)

    def pr_for_branch(self, _b):
        return None

    def start_work(self, number, branch):
        self.cwds.append(f"/fake/wt-{number}")
        return self.cwds[-1]

    def finish_work(self, number):
        self.finished.append(number)

    def commit_all(self, message, workdir="."):
        return True

    def branch_files(self, _b):
        return ["lint.yml"]  # both builds touch the same file

    def open_pr(self, branch, title, body):
        self.prs.append(branch)

    def comment(self, number, body):
        self.notes.append((number, body))

    def comments(self, number):
        # the ledger protocol reads failure comments back off the issue;
        # ledger.failure now stamps a "devloop budget: <date>" header line,
        # count() matches on the marker inside the body
        return [Comment("x", b) for n, b in self.notes if n == number]


def test_parallel_builds_get_distinct_worktrees():
    """max_parallel=2 with an empty queue: two builds run concurrently, each
    in its own worktree — agents must never share a working tree."""
    import devloop.core as core
    from devloop.config import Config

    forge = FlowForge()

    class R:
        name = "fake"
        def run(self, prompt, cwd, timeout):
            return type("Res", (), {"ok": True, "output": "done"})()

    out = core.run_once(Config(repo="o/r", pipeline=Pipeline(max_parallel=2)), forge, R())
    assert sorted(o.issue for o in out) == [1, 2]
    assert len(forge.prs) == 2
    # two distinct private worktrees, neither the shared checkout —
    # allocated by the Forge, cleaned up after each build
    assert len(set(forge.cwds)) == 2 and "." not in forge.cwds
    assert sorted(forge.finished) == [1, 2]


def test_conflict_gate_defers_overlapping_builds():
    """A build touching files an open devloop PR also touches: the delivery
    is deferred (no PR), not shipped as a guaranteed merge conflict. The
    branch keeps the work; a later sweep delivers after the other PR merges.
    Tests hit the delivery module's interface directly — no full build run."""
    import devloop.delivery as delivery
    from devloop import ledger
    from devloop.config import Config
    from devloop.forge.base import Issue, OpenPR

    forge = FlowForge(open_prs=[OpenPR(77, "devloop/issue-2", ["lint.yml"])])
    issue = Issue(1, "t1", "", ["ai-fix"])

    class R:
        name = "fake"

    out = delivery.deliver(Config(repo="o/r"), forge, R(), issue,
                           "devloop/issue-1", ".", "done")
    assert out.pr is None
    assert not forge.prs  # nothing opened — no guaranteed conflict shipped
    assert any("build deferred" in n for _, n in forge.notes)
    # deferral is an attempt: the cap bounds re-run spend
    assert ledger.count(forge, issue) == 1


def test_conflict_gate_passes_disjoint_builds():
    """Same scenario, disjoint files: the PR opens — parallel where parallel
    is actually safe. Delivery interface, no full build run."""
    import devloop.delivery as delivery
    from devloop.config import Config
    from devloop.forge.base import Issue, OpenPR

    forge = FlowForge(open_prs=[OpenPR(77, "devloop/issue-2", ["other.py"])])
    forge.branch_files = lambda b: ["lint.yml"]
    issue = Issue(1, "t1", "", ["ai-fix"])

    class R:
        name = "fake"

    out = delivery.deliver(Config(repo="o/r"), forge, R().name, issue,
                           "devloop/issue-1", ".", "done")
    assert forge.prs == ["devloop/issue-1"]


def _cmd_forge(auth_ok=True):
    from devloop.forge.base import Comment

    class CmdForge(Forge):
        def __init__(self):
            self.closed, self.notes, self.reviewed, self.built = [], [], [], []

        def is_owner(self, a): return auth_ok and a == "boss"
        def is_maintainer(self, a): return auth_ok and a in {"boss", "dev"}
        def is_collaborator(self, a): return auth_ok and a in {"boss", "dev", "c"}

        def issue(self, n):
            return type("I", (), {"number": n, "title": f"t{n}", "body": "", "labels": ["ai-fix"]})()

        def pr_for_branch(self, b):
            return 55 if b == "devloop/issue-9" else None

        def close_pr(self, n, reason): self.closed.append((n, reason))
        def comment(self, n, body): self.notes.append((n, body))
        def pr_diff_by_number(self, n): return "diff"
        def pr_body(self, n): return "Closes #9"
        def pr_comments(self, n):
            from devloop.forge.base import Comment
            return [Comment("human", "out of scope — tracked in #12")] if n == 55 else []
        def pr_comment(self, n, body): self.notes.append((n, body))

        def comments(self, n):
            # ledger: one failure, then a reset, then one more failure
            return [Comment("boss", "agent run FAILED — no PR opened."),
                    Comment("dev", "build reset by `/retry` — attempt budget cleared"),
                    Comment("boss", "delivery FAILED (x)")]

    return CmdForge()


def test_failure_budget_resets_on_retry():
    import devloop.core as core
    from devloop import ledger

    forge = _cmd_forge()
    issue = type("I", (), {"number": 9})()
    assert ledger.count(forge, issue) == 1  # only failures after the reset


def test_ledger_producer_and_parser_agree():
    """The interface is the test surface: every ledger failure kind feeds
    count() and lands on one side of the attempt budget."""
    from devloop import ledger

    notes = []

    class Forge_:
        def comment(self, n, body): notes.append(body)
        def comments(self, n): return [Comment("x", b) for b in notes]

    forge, issue = Forge_(), type("I", (), {"number": 1})()
    for kind in ledger.MARKERS:
        ledger.failure(forge, issue, kind, note="n", tail="t")
    assert ledger.count(forge, issue) == len(ledger.MARKERS)
    ledger.reset(forge, issue, "reason")
    assert ledger.count(forge, issue) == 0  # reset clears the budget
    assert notes[-1].startswith(ledger.RESET) and "reason" in notes[-1]


def test_review_rounds_carry_prior_findings():
    import devloop.core as core
    from devloop.config import Config

    forge = _cmd_forge()
    seen = []

    class R:
        name = "fake"
        def run(self, prompt, cwd, timeout):
            seen.append(prompt)
            return type("Res", (), {"ok": True, "output": f"finding round {len(seen)}"})()

    from devloop.review import review_pr
    review_pr(Config(repo="o/r", pipeline=Pipeline(review_rounds=2)), forge, R(), 55)
    assert "finding round 1" in seen[1]     # round 2 saw round 1's findings
    assert "diff" in seen[0] and seen[0].count("```diff") == 1  # the diff IS injected
    assert "Your earlier findings" in seen[1]


def test_repair_pushes_gates_and_verifies():
    """The repair loop: fixer → gate → push → one verification round.
    LGTM ends it; fresh findings feed the next attempt; the verify gate
    failing blocks the push; the budget exhausts loudly, never silently."""
    from devloop.repair import repair_pr
    from devloop.forge.base import Comment

    class RepairForge:
        def __init__(self, gate_ok=True):
            self.gate_ok, self.pushed, self.notes = gate_ok, 0, []

        def pr_diff_by_number(self, n): return f"diff-v{len(self.notes)}"

        def pr_comments(self, n): return [Comment("human", "out of scope — tracked in #12")]

        def pr_comment(self, n, body): self.notes.append(body)

        def commit_all(self, msg, workdir):
            self.pushed += 1
            return True

    class R:
        name = "fake"

        def __init__(self, outputs):
            self.outputs, self.calls = list(outputs), []

        def run(self, prompt, cwd, timeout):
            self.calls.append((prompt, cwd))
            return type("Res", (), {"ok": True, "output": self.outputs.pop(0)})()

    # fixer saw findings + thread + repo guidance; verifier judged a FRESH diff
    f = RepairForge()
    r = R(["fixed the thing", "LGTM"])
    assert repair_pr(Config(repo="o/r", pipeline=Pipeline(repair_rounds=1)),
                     f, r, 55, "devloop/issue-9", "wt", "t", "b", "P0: broken") == ""
    assert "P0: broken" in r.calls[0][0] and "out of scope" in r.calls[0][0]
    assert "Repo-specific repair guidance" in r.calls[0][0]  # skills/repair carried in
    assert f.pushed == 1
    assert "diff-v1" in r.calls[1][0]      # verifier saw the post-fix diff
    assert "AI verify, round 1/1" in f.notes[-1]

    # unresolved findings: budget exhausts, findings returned for the human
    f = RepairForge()
    r = R(["fixed half", "P1: still broken", "fixed more", "P1: still broken"])
    out = repair_pr(Config(repo="o/r", pipeline=Pipeline(repair_rounds=2)),
                    f, r, 55, "devloop/issue-9", "wt", "t", "b", "P1: bad")
    assert out == "P1: still broken" and f.pushed == 2 and len(r.calls) == 4
    assert "repair budget exhausted" in f.notes[-1]

    # gate fail: no push, findings stay open (workdir="." so the gate has a cwd)
    f = RepairForge(gate_ok=False)
    r = R(["fixed the thing"])
    cfg = Config(repo="o/r", pipeline=Pipeline(repair_rounds=1, verify="false"))
    assert repair_pr(cfg, f, r, 55, "devloop/issue-9", ".", "t", "b", "P0: broken") == "P0: broken"
    assert f.pushed == 0 and "gate FAILED" in f.notes[-1]


def test_build_flow_hands_review_findings_to_repair():
    """LGTM review → no repair; findings + repair_rounds → repair runs."""
    import devloop.core as core

    calls = []

    def fake_review(cfg, forge, runtime, pr, issue=None):
        calls.append(("review", issue.title))
        return "" if issue.title == "lgtm" else "P1: wrong"

    def fake_repair(cfg, forge, runtime, pr, branch, workdir, t, b, findings):
        calls.append(("repair", findings))
    review_pr, repair_pr = core.review_pr, core.repair_pr
    core.review_pr, core.repair_pr = fake_review, fake_repair
    try:
        runtime = type("R", (), {"name": "fake",
            "run": lambda self, *a, **k: type("Res", (), {"ok": True, "output": "work"})()})()
        for title in ("finds", "lgtm"):  # findings → repair; LGTM → review only
            forge = _cmd_forge()
            forge.start_work = lambda *a, **k: "/fake/wt"
            forge.finish_work = lambda *a, **k: None
            forge.commit_all = lambda msg, workdir: True
            issue = forge.issue(9)
            issue.title = title
            core.process_issue(Config(repo="o/r"), forge, runtime, issue, workdir="wt")
    finally:
        core.review_pr, core.repair_pr = review_pr, repair_pr
    assert calls == [("review", "finds"), ("repair", "P1: wrong"), ("review", "lgtm")]


def test_braced_issue_body_and_cleanup_on_failure():
    """Braces in an issue body are data, not format fields (the .format()
    crash is a regression); and finish_work runs even when the agent run
    explodes mid-build."""
    import devloop.core as core
    from devloop.config import Config
    from devloop.forge.base import Issue

    class F(Forge):
        def __init__(self):
            self.finished, self.notes, self.prs = [], [], []

        def start_work(self, n, branch): return f"/fake/wt-{n}"
        def finish_work(self, n): self.finished.append(n)
        def comment(self, n, body): self.notes.append(body)
        def comments(self, n): return [Comment("x", b) for b in self.notes]
        def commit_all(self, msg, workdir): return True
        def pr_for_branch(self, b): return None
        def open_devloop_prs(self): return []
        def branch_files(self, b): return []
        def open_pr(self, branch, title, body): self.prs.append(branch)
        def is_owner(self, a): return True
        def is_maintainer(self, a): return True
        def is_collaborator(self, a): return True

    issue = Issue(5, "t5", "def f(): return {'a': 1} — braces are data", ["ai-fix"])
    cfg = Config(repo="o/r", pipeline=Pipeline(review_rounds=0))

    class R:
        name = "fake"
        def __init__(self, boom=False): self.boom = boom
        def run(self, prompt, cwd, timeout):
            if self.boom:
                raise TimeoutError()
            self.prompt, self.cwd = prompt, cwd
            return type("Res", (), {"ok": True, "output": "work"})()

    # braces survive substitution; the Forge-allocated cwd reaches the agent
    f, r = F(), R()
    core.process_issue(cfg, f, r, issue)
    assert "{'a': 1}" in r.prompt  # body braces intact — .format() would crash
    assert r.cwd == "/fake/wt-5"
    assert f.prs == ["devloop/issue-5"]
    assert f.finished == [5]

    # agent run explodes → failure posted to the issue AND checkout cleaned up
    f2, b = F(), R(boom=True)
    out = core.process_issue(cfg, f2, b, issue)
    assert not out.agent_ok
    assert any("agent run FAILED" in n for n in f2.notes)
    assert f2.finished == [5]


def test_comment_commands():
    import devloop.core as core
    from devloop.config import Config

    cfg = Config(repo="o/r")
    forge = _cmd_forge()

    class R:
        name = "fake"
        def run(self, prompt, cwd, timeout):
            return type("Res", (), {"ok": True, "output": "LGTM"})()

    # not a command → untouched
    assert core.handle_command(cfg, forge, R(), "boss", "looks good", 9) is None
    # unauthorized → ignored, loudly
    assert core.handle_command(cfg, forge, R(), "stranger", "/review", 9) == "ignored:not-authorized"
    assert any("not authorized" in b for _, b in forge.notes)
    # /review executes review rounds
    assert core.handle_command(cfg, forge, R(), "dev", "/review", 9) == "reviewed PR #9"
    # /retry closes the stale PR and re-fires the build
    orig = core.process_issue
    core.process_issue = lambda cfg, f, r, issue, workdir=".": (forge.built.append(issue.number), None)[1]
    try:
        assert core.handle_command(cfg, forge, R(), "boss", "/retry 9", 1) == "retried issue #9"
    finally:
        core.process_issue = orig
    assert forge.closed and forge.closed[0][0] == 55
    # unknown command
    assert core.handle_command(cfg, forge, R(), "boss", "/merge everything", 9) == "ignored:unknown"
    # guardrail unchanged: direct close_issue from agent code still blocked
    from devloop.guardrails import GuardrailViolation
    try:
        forge.close_issue(9)
    except GuardrailViolation:
        pass
    else:
        raise AssertionError("close_issue must stay human-only")


def test_commit_all_counts_pushed_ahead_as_delivered():
    """The half-delivery rule lives behind the Forge seam: commit_all returns
    True for work the agent already pushed (no PR), False for a clean branch.
    Real git, no gh — the seam contract, not the adapter's gh plumbing."""
    import subprocess as sp
    import tempfile
    from devloop.forge.github import GitHub

    tmp = tempfile.mkdtemp()
    bare = f"{tmp}/origin.git"
    sp.run(["git", "init", "--bare", "-q", bare], check=True)
    w = f"{tmp}/clone"
    sp.run(["git", "clone", "-q", bare, w], check=True)
    sp.run(["git", "config", "user.email", "t@t"], cwd=w, check=True)
    sp.run(["git", "config", "user.name", "t"], cwd=w, check=True)

    def g(*a, **kw):
        return sp.run(["git", *a], cwd=kw.pop("cwd", w),
                      capture_output=True, text=True)

    default = g("symbolic-ref", "--short", "HEAD").stdout.strip()
    g("commit", "--allow-empty", "-m", "init")
    g("push", "-q", "-u", "origin", default)
    g("remote", "set-head", "origin", "-a")  # create origin/HEAD

    forge = GitHub("o/r")
    # half-delivery: agent pushed devloop/issue-7 itself, no PR — deliverable
    g("checkout", "-q", "-b", "devloop/issue-7")
    g("commit", "--allow-empty", "-m", "agent work")
    g("push", "-q", "-u", "origin", "devloop/issue-7")
    assert forge.commit_all("devloop: fixes #7", w) is True
    # genuinely empty branch: False
    g("checkout", "-q", "-b", "devloop/issue-8", "origin/HEAD")
    assert forge.commit_all("devloop: fixes #8", w) is False


def test_rebase_stage_rebases_clean_and_rebuilds_conflicts():
    """Pipeline upkeep: open devloop PRs get rebased onto main silently;
    a conflicting PR is closed with a rebuild note (counts as an attempt)."""
    import devloop.core as core

    class RebaseForge(FlowForge):
        def __init__(self, conflict):
            super().__init__()
            self.conflict = conflict
            self.rebased = []
            self.closed = []

        def open_devloop_prs(self):
            from devloop.forge.base import OpenPR
            return [OpenPR(77, "devloop/issue-9", [])]

        def rebase_branch(self, branch):
            self.rebased.append(branch)
            return not self.conflict

        def pr_for_branch(self, b):
            return 77 if b == "devloop/issue-9" else None

        def close_pr(self, n, reason):
            self.closed.append(n)

    # clean rebase: silent, PR stays open
    f1 = RebaseForge(conflict=False)
    core.rebase_stale(Config(repo="o/r"), f1)
    assert f1.rebased == ["devloop/issue-9"] and not f1.closed and not f1.notes

    # conflict: PR closed, issue told loudly, counts as an attempt
    f2 = RebaseForge(conflict=True)
    core.rebase_stale(Config(repo="o/r"), f2)
    assert f2.closed == [77]
    assert any("rebase conflict" in n for _, n in f2.notes)
    from devloop import ledger
    assert ledger.count(f2, type("I", (), {"number": 9})()) == 1


def test_rebase_branch_infra_error_skips_head():
    """rebase_stale: a git *failure* in rebase_branch (transient network,
    missing ref — anything that raises) must NOT close the PR or burn an
    attempt; that path is for real conflicts only. The head is skipped
    loudly and the sweep moves on."""
    import devloop.core as core

    class BoomForge(FlowForge):
        def __init__(self):
            super().__init__()
            self.closed = []

        def open_devloop_prs(self):
            from devloop.forge.base import OpenPR
            return [OpenPR(77, "devloop/issue-9", [])]

        def rebase_branch(self, branch):
            raise RuntimeError("git failed: fatal: invalid reference: " + branch)

        def pr_for_branch(self, b):
            return 77

        def close_pr(self, n, reason):
            self.closed.append(n)

    f = BoomForge()
    core.rebase_stale(Config(repo="o/r"), f)
    assert f.closed == [] and f.notes == []  # nothing destroyed, nothing counted


def test_rebase_branch_real_git_resolves_remote_pr_head():
    """The shipped bug: rebase_branch ran in a fresh CI checkout where the
    PR branch exists only as origin/<branch> (fetch created no local ref).
    Real git, real remote — asserts the origin/<branch> resolution and the
    force-push land."""
    import os
    import subprocess
    import tempfile
    from devloop.forge.github import GitHub

    def g(*args, cwd):
        subprocess.run(["git", *args], cwd=cwd, check=True,
                       capture_output=True)

    with tempfile.TemporaryDirectory() as tmp:
        # bare remote with main + a devloop branch one commit ahead
        remote = tmp + "/remote.git"
        subprocess.run(["git", "init", "--bare", "-b", "main", remote], check=True,
                       capture_output=True)
        seed = tmp + "/seed"
        g("clone", remote, "seed", cwd=tmp)
        g("config", "user.email", "t@t", cwd=seed)
        g("config", "user.name", "t", cwd=seed)
        with open(seed + "/f.txt", "w") as fh:
            fh.write("one\n")
        g("add", "-A", cwd=seed)
        g("commit", "-m", "one", cwd=seed)
        g("push", "origin", "main", cwd=seed)
        g("checkout", "-b", "devloop/issue-9", cwd=seed)
        with open(seed + "/pr.txt", "w") as fh:
            fh.write("pr work\n")
        g("add", "-A", cwd=seed)
        g("commit", "-m", "two", cwd=seed)
        g("push", "origin", "devloop/issue-9", cwd=seed)

        # fresh CI-style checkout of main only — no local devloop ref, but
        # the remote-tracking ref exists (what fetch of all branches leaves)
        co = tmp + "/co"
        g("clone", "--single-branch", "--branch", "main", remote, "co", cwd=tmp)
        g("fetch", "origin", "devloop/issue-9:refs/remotes/origin/devloop/issue-9",
          cwd=co)
        g("config", "user.email", "t@t", cwd=co)
        g("config", "user.name", "t", cwd=co)
        g("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main", cwd=co)

        # main moved forward after the PR branched
        g("checkout", "main", cwd=co)
        with open(co + "/base.txt", "w") as fh:
            fh.write("base\n")
        g("add", "-A", cwd=co)
        g("commit", "-m", "base", cwd=co)
        g("push", "origin", "main", cwd=co)

        forge = GitHub("o/r")  # repo arg unused by rebase_branch; git ops run in cwd
        old = os.getcwd()
        os.chdir(co)  # _run defaults to "." — the checkout IS the cwd
        try:
            assert forge.rebase_branch("devloop/issue-9") is True
        finally:
            os.chdir(old)

        # remote branch was force-pushed and now sits on current main
        g("fetch", "origin", cwd=seed)
        tip = subprocess.run(
            ["git", "log", "--format=%s", "origin/main..origin/devloop/issue-9"],
            cwd=seed, capture_output=True, text=True).stdout
        assert "two" in tip  # the PR's unique commit survived the rebase
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", "origin/main", "origin/devloop/issue-9"],
            cwd=seed, capture_output=True)
        assert ancestor.returncode == 0  # rebased onto current main


def test_issue_scoped_runs_use_build_budget():
    """Issue-scoped runs (build) get build_timeout; PR-scoped runs (review)
    keep timeout — greenfield builds are a different magnitude than reviews.
    Spec runs (also issue-scoped) share the build budget."""
    import devloop.core as core
    from devloop.review import review_pr

    cfg = Config(repo="o/r", pipeline=Pipeline(review_rounds=1))
    assert cfg.pipeline.build_timeout == 3600 and cfg.pipeline.timeout == 1800

    class F(Forge):
        def __init__(self):
            self.notes, self.finished, self.prs = [], [], []

        def start_work(self, n, branch): return f"/fake/wt-{n}"
        def finish_work(self, n): self.finished.append(n)
        def comment(self, n, body): self.notes.append(body)
        def comments(self, n): return [Comment("x", b) for b in self.notes]
        def commit_all(self, msg, workdir): return True
        def pr_for_branch(self, b): return None
        def open_devloop_prs(self): return []
        def is_owner(self, a): return True
        def is_maintainer(self, a): return True
        def is_collaborator(self, a): return True

    class R:
        name = "fake"
        def run(self, prompt, cwd, timeout):
            self.timeout = timeout
            return type("Res", (), {"ok": True, "output": "work"})()

    r = R()
    core.process_issue(cfg, F(), r, Issue(9, "t9", "b", ["ai-fix"]))
    assert r.timeout == cfg.pipeline.build_timeout  # build run: build budget

    rr = R()
    review_pr(cfg, _cmd_forge(), rr, 55)
    assert rr.timeout == cfg.pipeline.timeout       # review run: PR budget


def test_kind_runtime_config_parsing():
    """[runtime.<kind>] full-argv sections parse per canonical kind; an
    unknown kind name fails loudly; unlisted kinds fall back to global."""
    import tempfile
    from devloop.config import ConfigError, load

    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "config.toml"
        p.write_text(
            "[forge]\nrepo = 'o/r'\n"
            "[runtime]\nengine = 'pi'\n"
            "[runtime.new]\nargv = ['pi', '--mode', 'text']\n"
        )
        cfg = load(p)
        assert cfg.runtime.kind_argv["new"] == ["pi", "--mode", "text"]
        assert cfg.runtime.for_kind("new").argv == ["pi", "--mode", "text"]
        assert cfg.runtime.for_kind("fix") is None   # unlisted kind → global argv
        assert cfg.runtime.for_kind(None) is None

        p.write_text("[forge]\nrepo = 'o/r'\n[runtime.newsite]\nargv = ['x']\n")
        try:
            load(p)
        except ConfigError as e:
            assert "newsite" in str(e)
        else:
            raise AssertionError("unknown kind section did not raise")


def test_build_flow_uses_kind_runtime():
    """A [runtime.<kind>] override replaces the global runtime for that
    kind's build run; the heartbeat reports the agent actually run."""
    import devloop.core as core
    from devloop.config import Runtime

    class F(Forge):
        def __init__(self):
            self.notes, self.finished, self.prs = [], [], []

        def start_work(self, n, branch): return f"/fake/wt-{n}"
        def finish_work(self, n): self.finished.append(n)
        def comment(self, n, body): self.notes.append(body)
        def comments(self, n): return [Comment("x", b) for b in self.notes]
        def commit_all(self, msg, workdir): return True
        def pr_for_branch(self, b): return 55 if b in self.prs else None
        def open_devloop_prs(self): return []
        def branch_files(self, b): return set()
        def open_pr(self, branch, title, body): self.prs.append(branch)
        def is_owner(self, a): return True
        def is_maintainer(self, a): return True
        def is_collaborator(self, a): return True

    class R:
        name = "global"
        def run(self, prompt, cwd, timeout):
            raise AssertionError("global runtime must not run a kind override")

    # the override is a real argv → a real stub binary named kindagent on
    # PATH, so the run succeeds without any agent CLI installed
    import os
    import stat
    import tempfile
    with tempfile.TemporaryDirectory() as bin_d, \
            tempfile.TemporaryDirectory() as wt_d:
        stub = bin_d + "/kindagent"
        with open(stub, "w") as fh:
            fh.write("#!/bin/sh\nexit 0\n")
        os.chmod(stub, os.stat(stub).st_mode | stat.S_IEXEC)
        old_path = os.environ["PATH"]
        os.environ["PATH"] = bin_d + os.pathsep + old_path
        f = F()
        f.start_work = lambda n, branch: wt_d
        try:
            cfg = Config(repo="o/r",
                         runtime=Runtime(kind_argv={"fix": ["kindagent", "run"]}),
                         pipeline=Pipeline(review_rounds=0))
            out = core.process_issue(cfg, f, R(), Issue(7, "t7", "b", ["ai-fix"]))
        finally:
            os.environ["PATH"] = old_path
    assert f.prs == ["devloop/issue-7"]              # override ran, not R
    assert "agent `kindagent`" in f.notes[0]          # heartbeat names it
    assert out.pr == 55                              # PR bookkeeping via pr_for_branch


def test_layered_settings_global_repo_merge():
    """M1 layered settings: ~/.config/devloop/config.toml = org defaults,
    repo config.toml overrides key-by-key; sections merge, repo wins.
    Tests point XDG_CONFIG_HOME at a temp dir instead of $HOME."""
    import os
    import tempfile
    from devloop.config import load

    with tempfile.TemporaryDirectory() as tmp:
        xdg = Path(tmp) / "xdg"
        (xdg / "devloop").mkdir(parents=True)
        g = xdg / "devloop" / "config.toml"
        r = Path(tmp) / "repo.toml"
        g.write_text(
            "[forge]\nrepo = 'org/standard'\n"
            "[pipeline]\nreview_rounds = 1\nrepair_rounds = 0\n"
            "[access]\nmode = 'owners'\n"
        )
        r.write_text(
            "[forge]\nrepo = 'me/myrepo'\n"
            "[pipeline]\nreview_rounds = 4\n"
        )
        old = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = str(xdg)
        try:
            cfg = load(r)
            # repo wins on the key it sets
            assert cfg.repo == "me/myrepo" and cfg.pipeline.review_rounds == 4
            # untouched global keys survive
            assert cfg.pipeline.repair_rounds == 0 and cfg.access.mode == "owners"

            # no global file = repo config alone (the normal path, unchanged)
            g.unlink()
            assert load(r).repo == "me/myrepo"
        finally:
            if old is None:
                os.environ.pop("XDG_CONFIG_HOME", None)
            else:
                os.environ["XDG_CONFIG_HOME"] = old


def test_daily_budget_cap_blocks_runaway_issue():
    """max_per_day: an issue that failed N times today gets skipped (loudly)
    until tomorrow; other issues still build. Reads the ledger, no state."""
    import datetime
    import devloop.core as core
    from devloop import ledger

    today = f"{ledger.DAY} {datetime.date.today().isoformat()}"
    yesterday = f"{ledger.DAY} 2000-01-01"

    class BudgetForge(FlowForge):
        def __init__(self):
            super().__init__()
            self.today_failures = 2

        def comments(self, number):
            # issue 1: two failures today (at max_per_day); issue 2: clean
            if number != 1:
                return []
            fresh = [Comment("x", f"{today}\n\nagent run FAILED — fresh")] * self.today_failures
            return fresh

        def issues_with_labels(self, _l):
            return [Issue(1, "t1", "", ["ai-fix"]), Issue(2, "t2", "", ["ai-fix"])]

    started = []
    orig = core.process_issue
    core.process_issue = lambda cfg, f, r, issue, workdir=None: started.append(issue.number)
    try:
        cfg = Config(repo="o/r", pipeline=Pipeline(max_parallel=2, max_per_day=2))
        forge = BudgetForge()  # today_failures=2: at cap
        core.run_once(cfg, forge, type("R", (), {"name": "fake"})())
        # issue 1 hit its daily cap; issue 2 built
        assert started == [2]
    finally:
        core.process_issue = orig

    # budget() counts only today's entries for the daily cap, ignores yesterday's
    class CountForge:
        def comments(self, _n):
            return [Comment("x", f"{yesterday}\n\nagent run FAILED"),
                    Comment("x", f"{today}\n\nagent run FAILED")]

    assert ledger.budget(CountForge(), type("I", (), {"number": 1})())[1] == 1


def test_github_adapter_carries_base_url_to_gh():
    """GHES: [forge].base_url reaches every gh call as GH_HOST; URLs are
    normalized (scheme stripped, trailing slash dropped); empty = github.com
    and git calls run with the ambient env."""
    import subprocess as sp
    from devloop.forge.github import GitHub, _run

    assert GitHub("o/r", base_url="https://ghe.example.com/")._gh_host == "ghe.example.com"
    assert GitHub("o/r")._gh_host == ""

    # the adapter's host reaches the subprocess env on gh calls…
    out = _run(["python3", "-c",
                "import os; print(os.environ.get('GH_HOST', 'unset'))"],
               gh_host="ghe.example.com")
    assert out.strip() == "ghe.example.com"
    # …and git calls (gh_host="") inherit the ambient env untouched
    out = _run(["python3", "-c",
                "import os; print(os.environ.get('GH_HOST', 'unset'))"])
    assert out.strip() == "unset"
    # gh itself parses a host argument (the real consumer of the plumbing)
    r = sp.run(["gh", "--help"], capture_output=True, text=True)
    assert r.returncode == 0


def test_version_bump():
    from devloop.version import next_version
    assert next_version("v0.3.0") == "v0.3.1"
    assert next_version("v0.3.0", minor=True) == "v0.4.0"
    assert next_version("v0.2.17", minor=True) == "v0.3.0"
    try:
        next_version("0.3.0")
        raise AssertionError("missing v prefix should fail loudly")
    except SystemExit:
        pass
    import tempfile
    import devloop.version as vmod
    vmod._PYPROJECT = Path(tempfile.mkdtemp()) / "pyproject.toml"  # never touch the real file
    vmod._PYPROJECT.write_text('name = "devloop"\nversion = "0.3.0"\n')
    vmod.set_version("0.3.0")  # no-change rewrite must not fail
    assert 'version = "0.3.0"' in vmod._PYPROJECT.read_text()


def test_runtime_denylists_bind_agent_shell():
    """The forge-level wall is advisory for the agent's own shell; the runtime
    must bind the same human-only ops via engine tool policies: claude gets
    --disallowedTools, opencode gets OPENCODE_CONFIG_CONTENT deny rules."""
    import devloop.runtime as rt
    captured = {}

    def fake_run(argv, **kw):
        captured["argv"] = argv
        captured["env"] = kw.get("env")
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    real_run = rt.subprocess.run
    rt.subprocess.run = fake_run
    try:
        for engine, argv in [("claude", ["claude", "-p"]),
                             ("opencode", ["opencode", "run"])]:
            captured.clear()
            rt.AgentRuntime(argv).run("do work", cwd=".", timeout=60)
            assert captured["argv"][:2] == argv and captured["argv"][-1] == "do work"
            if engine == "claude":
                flags = captured["argv"][2:-1]
                assert flags[0] == "--disallowedTools"
                for c in rt.DENY_COMMANDS:
                    assert f"Bash({c}:*)" in flags[1]
            else:
                content = json.loads(captured["env"]["OPENCODE_CONFIG_CONTENT"])
                bash = content["permission"]["bash"]
                for c in rt.DENY_COMMANDS:
                    assert bash[c] == "deny" and bash[f"{c} *"] == "deny"
    finally:
        rt.subprocess.run = real_run
    # unknown custom engines are the user's control — no binding, no crash
    rt.AgentRuntime(["pi", "--mode", "text"])  # constructor only; run() passes through


def test_runtime_output_keeps_stderr_off_success():
    """Agent stderr (install/progress noise) must not leak into the output
    that becomes PR bodies and ledger tails. It joins only on failure."""
    import devloop.runtime as rt

    def fake_run(argv, **kw):
        return type("R", (), {"returncode": code, "stdout": "report\n",
                              "stderr": "Cloning into '/tmp/x'...\n"})()

    real_run = rt.subprocess.run
    rt.subprocess.run = fake_run
    try:
        code = 0
        out = rt.AgentRuntime(["pi"]).run("do work", cwd=".", timeout=60)
        assert out.ok and out.output == "report\n"
        code = 1
        out = rt.AgentRuntime(["pi"]).run("do work", cwd=".", timeout=60)
        assert not out.ok and "report\n" in out.output and "Cloning into" in out.output
    finally:
        rt.subprocess.run = real_run


def test_skip_reasons_are_logged():
    """The decision trace: every queue skip names its reason in the log —
    a silent green no-op is the worst failure mode a pipeline has."""
    import datetime
    import logging
    from devloop import ledger
    from devloop.queue import next_builds
    from devloop.forge.base import OpenPR

    class CapForge(FlowForge):
        def __init__(self, attempts=(), open_prs=()):
            super().__init__(open_prs=open_prs)
            self._attempts = dict(attempts)

        def issues_with_labels(self, _l):
            return [Issue(n, f"t{n}", "", ["ai-fix"]) for n in (1, 2, 3)]

        def comments(self, number):
            return [Comment("x", "agent run FAILED — x")] * self._attempts.get(number, 0)

    records = []

    class Capture(logging.Handler):
        def emit(self, r):
            records.append(r.getMessage())

    qlog = logging.getLogger("devloop.queue")
    h, old_level, old_prop = Capture(), qlog.level, qlog.propagate
    qlog.addHandler(h)
    qlog.setLevel(logging.INFO)
    qlog.propagate = False
    try:
        # queue full: the loud no-op, visible at default verbosity
        next_builds(Config(repo="o/r"), CapForge(
            open_prs=[OpenPR(77, "devloop/issue-2", []), OpenPR(78, "devloop/issue-8", [])]))
        assert any("queue full" in m for m in records)
        records.clear()

        # delivered skip + attempt-cap skip, each naming issue and reason
        cfg = Config(repo="o/r", pipeline=Pipeline(max_parallel=2, max_attempts=3))
        next_builds(cfg, CapForge(open_prs=[OpenPR(77, "devloop/issue-2", [])],
                                  attempts={1: 3}))
        text = "\n".join(records)
        assert "#2" in text and "already delivered" in text
        assert "#1" in text and "failed attempts" in text
        records.clear()

        # daily-cap skip
        today = f"{ledger.DAY} {datetime.date.today().isoformat()}"

        class DailyForge(CapForge):
            def comments(self, number):
                return [Comment("x", f"{today}\n\nagent run FAILED")] * self._attempts.get(number, 0)

        next_builds(Config(repo="o/r", pipeline=Pipeline(max_parallel=3, max_per_day=2)),
                    DailyForge(attempts={2: 2}))
        assert any("#2" in m and "daily cap" in m for m in records)
    finally:
        qlog.removeHandler(h)
        qlog.setLevel(old_level)
        qlog.propagate = old_prop


def test_status_previews_queue_without_side_effects():
    """devloop status: the same decisions next_builds makes, reported not
    executed — no worktree allocated, no comments written, and the WOULD-START
    set agrees with the policy it previews."""
    import re
    from devloop.queue import next_builds, status_lines
    from devloop.forge.base import OpenPR

    class CapForge(FlowForge):
        def __init__(self, attempts=(), open_prs=()):
            super().__init__(open_prs=open_prs)
            self._attempts = dict(attempts)

        def issues_with_labels(self, _l):
            return [Issue(n, f"t{n}", "", ["ai-fix"]) for n in (1, 2, 3)]

        def comments(self, number):
            return [Comment("x", "agent run FAILED — x")] * self._attempts.get(number, 0)

    cfg = Config(repo="o/r", pipeline=Pipeline(max_parallel=2, max_attempts=3))
    forge = CapForge(open_prs=[OpenPR(77, "devloop/issue-2", [])], attempts={1: 3})
    lines = status_lines(cfg, forge)
    text = "\n".join(lines)
    assert "#3" in text and "WOULD START" in text
    assert "#2" in text and "already delivered" in text
    assert "#1" in text and "budget exhausted" in text
    would = {int(m.group(1)) for l in lines
             if (m := re.match(r"  #(\d+) .*WOULD START", l))}
    assert would == {i.number for i in next_builds(cfg, forge)}
    # read-only: no worktree allocated, nothing posted
    assert not forge.cwds and not forge.notes

    # queue full: the preview names the bottleneck, starts nothing
    full = CapForge(open_prs=[OpenPR(77, "devloop/issue-2", [])])
    assert "queue full" in "\n".join(status_lines(Config(repo="o/r"), full))
    assert not full.cwds


def test_queue_next_builds_selection_policy():
    """Selection policy probed through the queue module's interface — no
    agent, no driver: delivered-set skip, attempt cap, daily cap, and
    slot-limited selection all read one Forge snapshot + one ledger scan."""
    from devloop.queue import next_builds
    from devloop.forge.base import OpenPR

    class CapForge(FlowForge):
        def __init__(self, attempts=(), open_prs=()):
            super().__init__(open_prs=open_prs)
            self._attempts = dict(attempts)  # issue number → failure count

        def issues_with_labels(self, _l):
            return [Issue(n, f"t{n}", "", ["ai-fix"]) for n in (1, 2, 3)]

        def comments(self, number):
            return [Comment("x", "agent run FAILED — x")] * self._attempts.get(number, 0)

    cfg = Config(repo="o/r", pipeline=Pipeline(max_parallel=2, max_attempts=3))

    # clean queue → issues in order, up to the slot budget
    assert [i.number for i in next_builds(cfg, CapForge())] == [1, 2]

    # delivered work never rebuilds: #2's PR is open → only #1 and #3, slot-bound
    forge = CapForge(open_prs=[OpenPR(77, "devloop/issue-2", [])])
    assert [i.number for i in next_builds(cfg, forge)] == [1]
    assert [i.number for i in next_builds(
        Config(repo="o/r", pipeline=Pipeline(max_parallel=3, max_attempts=3)), forge)] == [1, 3]

    # attempt cap: #1 exhausted → skipped loudly, #2 still builds
    forge = CapForge(attempts={1: 3})
    assert [i.number for i in next_builds(cfg, forge)] == [2, 3]

    # daily cap: #2 spent today's budget → #1 and #3 build
    import datetime
    from devloop import ledger
    today = f"{ledger.DAY} {datetime.date.today().isoformat()}"

    class DailyForge(CapForge):
        def comments(self, number):
            return [Comment("x", f"{today}\n\nagent run FAILED")] * self._attempts.get(number, 0)

    forge = DailyForge(attempts={2: 2}, )
    dcfg = Config(repo="o/r", pipeline=Pipeline(max_parallel=3, max_per_day=2))
    assert [i.number for i in next_builds(dcfg, forge)] == [1, 3]


def test_forge_conformance():
    """M2: one conformance suite, every adapter must pass. New adapters
    register a Harness in tests/conformance.ADAPTERS and get this for free."""
    import conformance
    failures: list[str] = []
    for harness_cls in conformance.ADAPTERS:
        failures += conformance.run_offline(harness_cls)
    assert not failures, "conformance failures:\n" + "\n".join(failures)


def test_merged_pr_completes_issue():
    """A human-merged devloop PR closes its issue — executing the human's
    merge sanction (same carve-out as close_pr), on the ledger record."""
    import devloop.core as core
    from devloop.config import Config
    from devloop.forge.base import Comment

    class F(Forge):
        def __init__(self):
            self.notes, self.completed = [], []

        def comment(self, n, body): self.notes.append((n, body))
        def complete_issue(self, n): self.completed.append(n)

    forge = F()
    cfg = Config(repo="o/r")

    # devloop PR merged → ledger entry + issue closed
    out = core.handle_merge(cfg, forge, 55, "devloop/issue-9")
    assert out == "completed issue #9"
    assert forge.notes and forge.notes[0][1].startswith("devloop PR merged #55")
    assert forge.completed == [9]

    # non-devloop branch → no-op (never touches a stranger's issue)
    f2 = F()
    assert core.handle_merge(cfg, f2, 56, "feature/x") is None
    assert not f2.notes and not f2.completed

    # malformed devloop branch → no-op, not a crash
    f3 = F()
    assert core.handle_merge(cfg, f3, 57, "devloop/issue-") is None
    assert not f3.completed

    # guardrail unchanged: close_issue stays human-only for all other callers
    try:
        forge.close_issue(9)
    except GuardrailViolation:
        pass
    else:
        raise AssertionError("close_issue must stay human-only")

    # ledger protocol: the completion marker is not counted as an attempt
    class LF(Forge):
        def comments(self, n):
            return [Comment("x", "devloop PR merged #55 — closing the issue"),
                    Comment("x", "agent run FAILED — boom")]

    from devloop import ledger
    from devloop.forge.base import Issue
    assert ledger.count(LF(), Issue(9, "t", "b")) == 1  # merge ≠ an attempt; the failure is


def test_merged_cli_glue():
    """cmd_merged must survive its own wiring: the unpack target once shadowed
    the _runtime function (UnboundLocalError) and _event was called with a
    nonexistent name (NameError) — both crash closeout before the forge call."""
    import argparse
    import json
    import tempfile
    import unittest.mock as mock

    import devloop.cli as cli
    from devloop.forge.base import Forge

    class F(Forge):
        def comment(self, *a):
            pass

        def complete_issue(self, n):
            self.completed = n

    forge = F()
    with mock.patch.object(cli, "load",
                           return_value=type("C", (), {"repo": "o/r"})()), \
            mock.patch.object(cli, "_runtime", return_value=(forge, None)):
        with tempfile.TemporaryDirectory() as tmp:
            ev = tmp + "/ev.json"
            env = mock.patch.dict(cli.os.environ, {"GITHUB_EVENT_PATH": ev})
            args = argparse.Namespace(event=ev)
            # not merged → silent; no forge call either way
            Path(ev).write_text(json.dumps(
                {"pull_request": {"merged": False, "number": 55,
                                  "head": {"ref": "devloop/issue-9"}}}))
            with env:
                cli.cmd_merged(args)
            assert not hasattr(forge, "completed")

            # merged: closeout fires — the bugs above died before this line
            Path(ev).write_text(json.dumps(
                {"pull_request": {"merged": True, "number": 55,
                                  "head": {"ref": "devloop/issue-9"}}}))
            with env:
                cli.cmd_merged(args)
        assert forge.completed == 9


def test_git_identity_guard():
    """Fresh CI checkouts have no git identity — start_work sets one so
    agent self-commits and pipeline commits never fail or guess. A human's
    explicit config (local or global) always wins."""
    import os
    import subprocess
    import tempfile
    from devloop.forge.github import GitHub

    def g(*args, cwd):
        subprocess.run(["git", *args], cwd=cwd, check=True,
                       capture_output=True)

    # dev machines carry a global git identity — CI checkouts don't. Isolate
    # the test from both so the CI-like "no identity" precondition holds.
    os.environ["GIT_CONFIG_GLOBAL"] = "/dev/null"
    os.environ["GIT_CONFIG_SYSTEM"] = "/dev/null"
    with tempfile.TemporaryDirectory() as tmp:
        remote = tmp + "/remote.git"
        subprocess.run(["git", "init", "--bare", "-b", "main", remote],
                       check=True, capture_output=True)
        seed = tmp + "/seed"
        g("clone", remote, "seed", cwd=tmp)
        g("config", "user.email", "t@t", cwd=seed)
        g("config", "user.name", "t", cwd=seed)
        with open(seed + "/f.txt", "w") as fh:
            fh.write("one\n")
        g("add", "-A", cwd=seed)
        g("commit", "-m", "one", cwd=seed)
        g("push", "origin", "main", cwd=seed)

        # fresh CI-style checkout: no identity anywhere
        co = tmp + "/co"
        g("clone", remote, "co", cwd=tmp)
        g("symbolic-ref", "refs/remotes/origin/HEAD",
          "refs/remotes/origin/main", cwd=co)

        forge = GitHub("o/r")
        old = os.getcwd()
        os.chdir(co)
        try:
            workdir = forge.start_work(9, "devloop/issue-9")
            name = subprocess.run(["git", "config", "user.name"], cwd=workdir,
                                  capture_output=True, text=True).stdout.strip()
            email = subprocess.run(["git", "config", "user.email"], cwd=co,
                                   capture_output=True, text=True).stdout.strip()
        finally:
            os.chdir(old)
        assert name == "devloop agent" and \
            email == "devloop@users.noreply.github.com"

        # human-set identity is never overridden
        g("config", "user.email", "human@repo", cwd=co)
        g("config", "user.name", "human", cwd=co)
        old = os.getcwd()
        os.chdir(co)
        try:
            from devloop.forge.github import _ensure_identity
            _ensure_identity(co)
        finally:
            os.chdir(old)
        assert subprocess.run(["git", "config", "user.email"], cwd=co,
                              capture_output=True, text=True).stdout.strip() \
            == "human@repo"


def test_verify_gate_one_policy():
    """The gate module owns the verify policy: PASS/FAIL semantics and the
    timeout — a hung gate is a FAIL, not a wedge. Both callers (delivery,
    repair) gate through this one interface."""
    from devloop.gate import run_gate

    assert run_gate("true", ".", 10) is True
    assert run_gate("exit 1", ".", 10) is False
    # the latent hang: a gate that never returns is a FAIL, not a blocked
    # build thread — this is why the policy lives in one place
    assert run_gate("sleep 2", ".", timeout=1) is False


def test_branch_naming_one_owner():
    """The devloop branch convention is owned by the Forge interface:
    build and parse in one place, inherited by every adapter and fake —
    callers never touch the string."""
    from devloop.forge.base import Forge

    f = Forge()
    assert f.branch_for(7) == "devloop/issue-7"
    assert f.issue_of_branch("devloop/issue-7") == 7
    assert f.issue_of_branch("feature/x") is None          # stranger's branch
    assert f.issue_of_branch("devloop/issue-") is None     # malformed
    assert f.issue_of_branch("devloop/issue-x") is None    # unparseable


def test_rounds_dialect_shared():
    """The round engine: LGTM verdict parsing, thread formatting, and
    repo-guidance loading exist once in rounds.py — and run_round owns the
    full round bracket: diff+thread injection, announcement, run-failure
    comment. Plus the PR-body contract, owned by delivery."""
    from devloop.forge.base import Comment
    from devloop.rounds import is_lgtm, run_round, thread_lines, with_repo_guidance

    assert is_lgtm("all good\nLGTM") is True
    # verdict lives at the tail: LGTM older than the 200-char tail window is not a verdict
    assert is_lgtm("LGTM was mentioned earlier\n" + "x" * 220 + "\nP1: still broken") is False
    assert thread_lines([Comment("ann", "already fixed"),
                         Comment("bob", "  out of scope  ")]) == \
        ["- ann: already fixed", "- bob: out of scope"]
    base = with_repo_guidance("BASE", "/nonexistent/skill.md", "X")
    assert base == "BASE"  # missing guidance file leaves the prompt alone

    from devloop.delivery import issue_of_body
    assert issue_of_body("context\nCloses #12\nmore") == 12
    assert issue_of_body("closes #7") == 7
    assert issue_of_body("no marker here") is None

    notes = []

    class RoundForge:
        def pr_diff_by_number(self, n):
            return f"the diff"

        def pr_comments(self, n):
            return [Comment("human", "already fixed")]

        def pr_comment(self, n, body):
            notes.append(body)

    class R:
        name = "fake"

        def run(self, prompt, cwd, timeout):
            self.prompt, self.cwd = prompt, cwd
            return type("Res", (), {"ok": True, "output": "P1: something"})()

    # one round: {diff} filled from the forge, thread appended, extra last,
    # announcement posted
    f, r = RoundForge(), R()
    res = run_round(f, r, 55, "pre-review", "judge {diff}", 1, 2, ".", 60,
                    extra="\nPRIOR FINDINGS")
    assert res is not None
    assert "the diff" in r.prompt and "```diff" not in r.prompt.split("judge")[0]
    assert "already fixed" in r.prompt and "PRIOR FINDINGS" in r.prompt
    assert r.cwd == "."
    assert notes[-1].startswith("**AI pre-review, round 1/2**")

    # failed run: failure commented on the PR, None returned
    class Boom(R):
        def run(self, prompt, cwd, timeout):
            return type("Res", (), {"ok": False, "output": "boom"})()

    notes.clear()
    assert run_round(RoundForge(), Boom(), 55, "repair", "x", 1, 1, ".", 60) is None
    assert "AI repair round 1: run failed" in notes[-1]


if __name__ == "__main__":
    # discover every test_* in this file — a test defined below the old
    # explicit call list never ran, which is how cmd_merged shipped broken
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
    print(f"all checks passed ({_name} last of many)")
