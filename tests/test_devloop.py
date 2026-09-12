"""The one check: guardrails hold and trigger routing is correct."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from devloop.config import Access, Config, Labels, Pipeline
from devloop.forge.base import Comment, Forge
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
    from devloop.core import MARKER, parse_status, spec_phase

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
    from devloop.core import process_spec

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

        def start_work(self, *a):
            raise AssertionError("issue with open PR must be skipped")

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

    def spy(cfg, forge, runtime, issue, workdir="."):
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
    print("all checks passed")


def _full_flow_forge(open_heads=(), pr_files=None, calls=None):
    """FakeForge wired for the full process_issue flow: agent 'commits and
    pushes' (commit_all True), open_pr recorded, branch_files/pr_files
    overridable to stage conflict-gate scenarios."""
    from devloop.forge.base import Forge

    class FlowForge(Forge):
        def __init__(self):
            self.prs = []
            self.notes = []
            self.cwds = []

        def issues_with_labels(self, _l):
            return [type("I", (), {"number": n, "title": f"t{n}", "body": "", "labels": ["ai-fix"]})
                    for n in (1, 2)]

        def open_pr_head_branches(self):
            return list(open_heads)

        def pr_for_branch(self, _b):
            return None

        def start_work(self, number, branch, workdir="."):
            self.cwds.append(workdir)

        def commit_all(self, message, workdir="."):
            return True

        def branch_files(self, _b):
            return ["lint.yml"]  # both builds touch the same file

        def pr_files(self, n):
            return (pr_files or {}).get(n, [])

        def open_pr(self, branch, title, body):
            self.prs.append(branch)

        def comment(self, number, body):
            self.notes.append((number, body))

    return FlowForge()


def test_parallel_builds_get_distinct_worktrees():
    """max_parallel=2 with an empty queue: two builds run concurrently, each
    in its own worktree — agents must never share a working tree."""
    import devloop.core as core
    from devloop.config import Config

    forge = _full_flow_forge()

    class R:
        name = "fake"
        def run(self, prompt, cwd, timeout):
            return type("Res", (), {"ok": True, "output": "done"})()

    out = core.run_once(Config(repo="o/r", pipeline=Pipeline(max_parallel=2)), forge, R())
    assert sorted(o.issue for o in out) == [1, 2]
    assert len(forge.prs) == 2
    # two distinct private worktrees, neither the shared checkout
    assert len(set(forge.cwds)) == 2 and "." not in forge.cwds


def test_conflict_gate_defers_overlapping_builds():
    """Two concurrent builds touching the same files: the later delivery is
    deferred (no PR), not shipped as a guaranteed merge conflict. The branch
    keeps the work; a later sweep delivers after the conflicting PR merges."""
    import devloop.core as core
    from devloop.config import Config

    forge = _full_flow_forge(open_heads=["devloop/issue-2"], pr_files={77: ["lint.yml"]})
    forge.pr_for_branch = lambda b: 77 if b == "devloop/issue-2" else None

    class R:
        name = "fake"
        def run(self, prompt, cwd, timeout):
            return type("Res", (), {"ok": True, "output": "done"})()

    out = core.run_once(Config(repo="o/r", pipeline=Pipeline(max_parallel=2)), forge, R())
    assert len(out) == 1 and out[0].issue == 1 and not out[0].delivered
    assert not forge.prs  # nothing opened — no guaranteed conflict shipped
    assert any(n.startswith("build deferred") for _, n in forge.notes)
    # deferral is an attempt: the cap bounds re-run spend
    assert core.failure_count(forge, type("I", (), {"number": 1})()) == 1


def test_conflict_gate_passes_disjoint_builds():
    """Same scenario, disjoint files: both PRs open — parallel where parallel
    is actually safe."""
    import devloop.core as core
    from devloop.config import Config

    forge = _full_flow_forge(open_heads=["devloop/issue-2"], pr_files={77: ["other.py"]})
    forge.pr_for_branch = lambda b: 77 if b == "devloop/issue-2" else None
    forge.branch_files = lambda b: ["lint.yml"]

    class R:
        name = "fake"
        def run(self, prompt, cwd, timeout):
            return type("Res", (), {"ok": True, "output": "done"})()

    out = core.run_once(Config(repo="o/r", pipeline=Pipeline(max_parallel=2)), forge, R())
    assert len(out) == 2 and len(forge.prs) == 2


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

    forge = _cmd_forge()
    issue = type("I", (), {"number": 9})()
    assert core.failure_count(forge, issue) == 1  # only failures after the reset


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

    core.review_pr(Config(repo="o/r", pipeline=Pipeline(review_rounds=2)), forge, R(), 55)
    assert "finding round 1" in seen[1]     # round 2 saw round 1's findings
    assert "diff" in seen[0] and seen[0].count("```diff") == 1  # the diff IS injected
    assert "Your earlier findings" in seen[1]


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
