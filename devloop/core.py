"""Build orchestration: trigger → agent job → delivery → upkeep.

The spec loop is devloop/spec.py; the review loop is devloop/review.py;
the ledger protocol is devloop/ledger.py. This module owns only the
build flow and the sweep that drives it."""

import shutil
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

from . import ledger
from .config import Config
from .delivery import Outcome, deliver
from .forge import Forge, Issue
from .repair import repair_pr
from .review import review_pr
from .runtime import AgentRuntime

# Per trigger kind: what the agent is asked to do. Skills carry the how.
PROMPTS = {
    "fix": "A reported problem exists in this repo (issue below). Probe reality first, "
           "record evidence in FINDINGS-{n}.md (per-issue evidence file — a shared "
           "FINDINGS.md collides with every concurrent merge), then make the minimal "
           "fix, and follow the "
           "verify skill. Do not merge; leave the work committed for human review.\n\n"
           "## Issue #{n}: {title}\n{body}",
    "new": "Build the unit of work described in this issue. Read any spec carefully, "
           "probe what's needed first (probe skill), implement test-first where the "
           "spec implies it, and follow the verify skill. Do not merge.\n\n"
           "## Issue #{n}: {title}\n{body}",
    "remove": "Remove the component named in this issue. First gather evidence it is "
              "dead/broken (probe skill), put the evidence in FINDINGS-{n}.md, then remove "
              "the component and anything only it referenced. Do not merge.\n\n"
              "## Issue #{n}: {title}\n{body}",
    "task": "Execute the task specified in this issue body — it is the full spec. "
            "Do exactly what it says, no more: do not expand scope, do not fix "
            "unrelated things you notice (list them as notes in the PR body "
            "instead). Follow repo conventions (AGENTS.md). Do not merge.\n\n"
            "## Issue #{n}: {title}\n{body}",
}


# --- spec loop: moved to devloop/spec.py -------------------------------------


def process_issue(cfg: Config, forge: Forge, runtime: AgentRuntime, issue: Issue,
                  workdir: str = ".") -> Outcome:
    """One build: prompt the agent, then hand the finished work to the
    delivery module. Agent-run failures report here; everything after a
    successful run (gate, commit, conflict gate, PR) is deliver()'s job."""
    kind = cfg.kind_for(issue.labels)  # raises if triggers are not exclusive
    branch = f"devloop/issue-{issue.number}"
    # progress heartbeat: the issue timeline shows when a build starts and
    # which attempt this is — comments are free, silence is not (a 30-min
    # agent run with no visible start looks identical to a broken pipeline)
    forge.comment(issue.number,
                  f"build started — attempt {ledger.count(forge, issue) + 1}/"
                  f"{cfg.pipeline.max_attempts}, kind `{kind}`, agent `{runtime.name}`, "
                  f"branch `{branch}`")
    forge.start_work(issue.number, branch, workdir)
    res = None
    try:
        res = runtime.run(PROMPTS[kind].format(n=issue.number, title=issue.title, body=issue.body),
                          cwd=workdir, timeout=cfg.pipeline.timeout)
    except Exception as e:
        # Timeout/explosion mid-run: no delivery, but the human must know.
        ledger.failure(forge, issue, "agent", note=f"no PR opened ({type(e).__name__})", tail=str(e))
        return Outcome(issue.number, branch, False, False)
    if not res.ok:
        # A failed agent run must not ship: no commit, no gate, no PR — the
        # error tail goes to the issue for the human, the branch stays local.
        ledger.failure(forge, issue, "agent", note="no PR opened", tail=res.output)
        return Outcome(issue.number, branch, False)
    out = deliver(cfg, forge, runtime, issue, branch, workdir, res.output)
    if out.pr:
        findings = review_pr(cfg, forge, runtime, out.pr, branch,
                             issue_title=issue.title, issue_body=issue.body)
        if findings and cfg.pipeline.repair_rounds > 0:
            repair_pr(cfg, forge, runtime, out.pr, branch, workdir,
                      issue.title, issue.body, findings)
    return out


def rebase_stale(cfg: Config, forge: Forge, devloop_heads: list[str]) -> None:
    """Pipeline upkeep, not human work: rebase open devloop PRs onto the
    current default branch (silently when clean). On conflict, close the PR
    and mark the issue for rebuild — main moved under the work, and redoing
    agent labor is cheaper than spending human conflict resolution."""
    for head in devloop_heads:
        try:
            n = int(head.rsplit("-", 1)[-1])
        except ValueError:
            continue
        if forge.rebase_branch(head):
            continue  # clean — no-op or silently updated, nothing to announce
        pr = forge.pr_for_branch(head)
        if pr:
            forge.close_pr(pr, f"rebase onto main conflicts with merged work — rebuilding ({head})")
        ledger.failure(forge, n, "rebase", note=f"PR closed, building again on fresh main ({head})")


def handle_command(cfg: Config, forge: Forge, runtime: AgentRuntime,
                   author: str, text: str, context_number: int) -> str | None:
    """Execute one comment command (`/review <pr>`, `/retry <issue>`).
    The wall stays up: commands are executed BY devloop FOR an authorized
    human — the author is access-gated before anything happens, and the
    agent's own comments never contain commands (this is invoked from a
    CI event, not from reading comment contents)."""
    text = text.strip()
    if not text.startswith("/"):
        return None
    cmd, _, arg = text.partition(" ")
    arg = arg.strip()
    if not forge.is_authorized(author, cfg.access):
        forge.comment(context_number,
                      f"command `{cmd}` ignored — `{author}` is not authorized "
                      "to fire devloop (access policy)")
        return "ignored:not-authorized"
    try:
        if cmd == "/review":
            pr = int(arg) if arg else context_number
            review_pr(cfg, forge, runtime, pr)
            return f"reviewed PR #{pr}"
        if cmd == "/retry":
            n = int(arg) if arg else context_number
            existing = forge.pr_for_branch(f"devloop/issue-{n}")
            if existing:
                # the human sanctioned discarding the delivery — devloop is
                # executing that command, not judging the work itself
                forge.close_pr(existing, f"closed by `/retry` from {author} — rebuild incoming")
            ledger.reset(forge, n, f"`/retry` from {author} — attempt budget cleared, rebuilding")
            process_issue(cfg, forge, runtime, forge.issue(n))
            return f"retried issue #{n}"
        forge.comment(context_number,
                      f"unknown command `{cmd}` — supported: `/review <pr>`, `/retry <issue>`")
        return "ignored:unknown"
    except Exception as e:
        forge.comment(context_number,
                      f"command `{cmd}` FAILED ({type(e).__name__}): {str(e)[:500]}")
        return "failed"


def run_once(cfg: Config, forge: Forge, runtime: AgentRuntime) -> list[Outcome]:
    open_heads = forge.open_pr_head_branches()
    devloop_heads = [h for h in open_heads if h.startswith("devloop/")]
    # Upkeep before slot math: rebase stale PRs; a conflict-closed PR frees a slot.
    if devloop_heads:
        rebase_stale(cfg, forge, devloop_heads)
        open_heads = forge.open_pr_head_branches()
        devloop_heads = [h for h in open_heads if h.startswith("devloop/")]
    slots = cfg.pipeline.max_parallel - len(devloop_heads)
    # Two layers of conflict prevention:
    #   1. skip issues that already have a devloop PR — never rebuild delivered work
    #   2. never exceed max_parallel in-flight builds; builds themselves get a
    #      per-PR conflict gate at delivery (files overlapping an open devloop
    #      PR defer instead of opening a conflicting PR)
    if slots <= 0:
        # Queue full — say so, loudly. Silent green no-ops are the worst
        # failure mode a pipeline can have (the human believes it ran).
        print(f"queue full: {len(devloop_heads)} build(s) in flight "
              f"({', '.join(devloop_heads)}); nothing started — "
              "merge/close the open devloop PR(s) or raise pipeline.max_parallel",
              file=sys.stderr)
        return []
    delivered = set(open_heads)
    candidates = []
    for issue in forge.issues_with_labels(cfg.labels.triggers):
        if f"devloop/issue-{issue.number}" in delivered:
            continue
        if ledger.count(forge, issue) >= cfg.pipeline.max_attempts:
            print(f"#{issue.number}: {ledger.count(forge, issue)} failed attempts — "
                  "skipped; re-label to retry", file=sys.stderr)
            continue
        candidates.append(issue)
        if len(candidates) >= slots:
            break
    if not candidates:
        return []

    # One private git worktree per build: parallel agents must not share a
    # working tree (they race on git state). Removed when the build ends.
    dirs: dict[int, str] = {}
    parents: dict[int, str] = {}
    for issue in candidates:
        parents[issue.number] = tempfile.mkdtemp(prefix=f"devloop-{issue.number}-")
        dirs[issue.number] = parents[issue.number] + "/tree"

    def worker(issue: Issue) -> Outcome:
        try:
            return process_issue(cfg, forge, runtime, issue, dirs[issue.number])
        except Exception as e:
            # One broken issue must not block the queue (head-of-line blocking
            # would retry it forever in watch mode and starve everything else).
            print(f"#{issue.number}: failed: {e}", file=sys.stderr)
            return Outcome(issue.number, f"devloop/issue-{issue.number}", False, False)
        finally:
            shutil.rmtree(parents[issue.number], ignore_errors=True)

    out: list[Outcome] = []
    with ThreadPoolExecutor(max_workers=slots) as pool:
        for r in pool.map(worker, candidates):
            out.append(r)
    return out
