"""The one check: guardrails hold and trigger routing is correct."""

import sys
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

        def open_pr_head_branches(self):
            return ["devloop/issue-1"]

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
        def open_pr_head_branches(self):
            return ["devloop/issue-9"]

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
    pushes' (commit_all True), open_pr recorded, branch_files/pr_files
    overridable to stage conflict-gate scenarios."""

    def __init__(self, open_heads=(), pr_files=None):
        self.prs = []
        self.notes = []
        self.cwds = []
        self.finished = []
        self._open_heads = list(open_heads)
        self._pr_files = pr_files or {}

    def issues_with_labels(self, _l):
        return [Issue(n, f"t{n}", "", ["ai-fix"]) for n in (1, 2)]

    def open_pr_head_branches(self):
        return list(self._open_heads)

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

    def pr_files(self, n):
        return self._pr_files.get(n, [])

    def open_pr(self, branch, title, body):
        self.prs.append(branch)

    def comment(self, number, body):
        self.notes.append((number, body))

    def comments(self, number):
        # the ledger protocol reads failure comments back off the issue
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
    from devloop.forge.base import Issue

    forge = FlowForge(open_heads=["devloop/issue-2"], pr_files={77: ["lint.yml"]})
    forge.pr_for_branch = lambda b: 77 if b == "devloop/issue-2" else None
    issue = Issue(1, "t1", "", ["ai-fix"])

    class R:
        name = "fake"

    out = delivery.deliver(Config(repo="o/r"), forge, R(), issue,
                           "devloop/issue-1", ".", "done")
    assert out.pr is None
    assert not forge.prs  # nothing opened — no guaranteed conflict shipped
    assert any(n.startswith("build deferred") for _, n in forge.notes)
    # deferral is an attempt: the cap bounds re-run spend
    assert ledger.count(forge, issue) == 1


def test_conflict_gate_passes_disjoint_builds():
    """Same scenario, disjoint files: the PR opens — parallel where parallel
    is actually safe. Delivery interface, no full build run."""
    import devloop.delivery as delivery
    from devloop.config import Config
    from devloop.forge.base import Issue

    forge = FlowForge(open_heads=["devloop/issue-2"], pr_files={77: ["other.py"]})
    forge.pr_for_branch = lambda b: 77 if b == "devloop/issue-2" else None
    forge.branch_files = lambda b: ["lint.yml"]
    issue = Issue(1, "t1", "", ["ai-fix"])

    class R:
        name = "fake"

    out = delivery.deliver(Config(repo="o/r"), forge, R(), issue,
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
    assert "AI verify after repair 1" in f.notes[-1]

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

    def fake_review(cfg, forge, runtime, pr, branch, issue_title="", issue_body=""):
        calls.append(("review", issue_title))
        return "" if issue_title == "lgtm" else "P1: wrong"

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
        def open_pr_head_branches(self): return []
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
    assert any(n.startswith("agent run FAILED") for n in f2.notes)
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

        def rebase_branch(self, branch):
            self.rebased.append(branch)
            return not self.conflict

        def pr_for_branch(self, b):
            return 77 if b == "devloop/issue-9" else None

        def close_pr(self, n, reason):
            self.closed.append(n)

    # clean rebase: silent, PR stays open
    f1 = RebaseForge(conflict=False)
    core.rebase_stale(Config(repo="o/r"), f1, ["devloop/issue-9"])
    assert f1.rebased == ["devloop/issue-9"] and not f1.closed and not f1.notes

    # conflict: PR closed, issue told loudly, counts as an attempt
    f2 = RebaseForge(conflict=True)
    core.rebase_stale(Config(repo="o/r"), f2, ["devloop/issue-9"])
    assert f2.closed == [77]
    assert any(n.startswith("rebase conflict") for _, n in f2.notes)
    from devloop import ledger
    assert ledger.count(f2, type("I", (), {"number": 9})()) == 1


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
    from devloop.version import set_version
    set_version("0.3.0")  # no-change rewrite must not fail


if __name__ == "__main__":
    test_human_only_ops_are_blocked()
    test_spec_state_machine()
    test_spec_never_reprocesses_finalized()
    test_run_once_skips_issues_with_open_pr()
    test_queue_full_starts_nothing()
    test_skillcheck_warns_and_never_blocks()
    test_trigger_authority_defaults_and_overrides()
    test_access_mode_typo_fails_loudly()
    test_trigger_labels_are_mutually_exclusive()
    test_renamed_labels_route()
    test_config_version_guard()
    test_parallel_builds_get_distinct_worktrees()
    test_conflict_gate_defers_overlapping_builds()
    test_conflict_gate_passes_disjoint_builds()
    test_failure_budget_resets_on_retry()
    test_ledger_producer_and_parser_agree()
    test_review_rounds_carry_prior_findings()
    test_repair_pushes_gates_and_verifies()
    test_build_flow_hands_review_findings_to_repair()
    test_braced_issue_body_and_cleanup_on_failure()
    test_comment_commands()
    test_rebase_stage_rebases_clean_and_rebuilds_conflicts()
    test_version_bump()
    print("all checks passed")



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
    assert ledger.count(LF(), 9) == 1  # merge ≠ an attempt; the failure is
