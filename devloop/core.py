"""Build orchestration: trigger → agent job → delivery → upkeep.

The spec loop is devloop/spec.py; the review loop is devloop/review.py;
the ledger protocol is devloop/ledger.py; build selection policy is
devloop/queue.py. This module owns only the build flow and the sweep that
drives it."""

import logging
import time
from concurrent.futures import ThreadPoolExecutor

from . import ledger
from .config import Config
from .delivery import Outcome, deliver
from .forge import Forge, Issue
from .queue import next_builds
from .repair import repair_pr
from .review import review_pr
from .runtime import AgentRuntime

log = logging.getLogger(__name__)

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
}


# --- spec loop: moved to devloop/spec.py -------------------------------------


def process_issue(cfg: Config, forge: Forge, runtime: AgentRuntime, issue: Issue,
                  workdir: str | None = None) -> Outcome:
    """One build: prompt the agent, then hand the finished work to the
    delivery module. Agent-run failures report here; everything after a
    successful run (gate, commit, conflict gate, PR) is deliver()'s job.
    Owns the build's create/cleanup bracket: start_work → finish_work,
    even when the run explodes. workdir=None means the Forge allocates
    its own checkout; callers never name paths."""
    kind = cfg.kind_for(issue.labels)  # raises if triggers are not exclusive
    branch = forge.branch_for(issue.number)
    # per-kind runtime override: [runtime.<kind>] full argv wins for this
    # build; no section configured → the caller's global runtime
    agent = cfg.runtime.for_kind(kind) or runtime
    # progress heartbeat: the issue timeline shows when a build starts and
    # which attempt this is — comments are free, silence is not (a 30-min
    # agent run with no visible start looks identical to a broken pipeline)
    forge.comment(issue.number,
                  f"build started — attempt {ledger.count(forge, issue) + 1}/"
                  f"{cfg.pipeline.max_attempts}, kind `{kind}`, agent `{agent.name}`, "
                  f"branch `{branch}`")
    # Forge allocates the private checkout (one per build — parallel agents
    # must never share a working tree); process_issue owns the cleanup bracket.
    workdir = forge.start_work(issue.number, branch)
    t0 = time.monotonic()
    try:
        res = None
        try:
            log.info("#%d: agent run started (%s, kind %s, branch %s)",
                     issue.number, agent.name, kind, branch)
            res = agent.run(
                PROMPTS[kind]
                .replace("{n}", str(issue.number))
                .replace("{title}", issue.title)
                .replace("{body}", issue.body),
                cwd=workdir, timeout=cfg.pipeline.build_timeout)
        except Exception as e:
            # Timeout/explosion mid-run: no delivery, but the human must know.
            log.error("#%d: agent run failed after %.0fs: %s", issue.number,
                      time.monotonic() - t0, type(e).__name__)
            ledger.failure(forge, issue, "agent", note=f"no PR opened ({type(e).__name__})", tail=str(e))
            return Outcome(issue.number, branch, False, False)
        if not res.ok:
            # A failed agent run must not ship: no commit, no gate, no PR — the
            # error tail goes to the issue for the human, the branch stays local.
            log.error("#%d: agent run FAILED after %.0fs (exit nonzero)", issue.number,
                      time.monotonic() - t0)
            ledger.failure(forge, issue, "agent", note="no PR opened", tail=res.output)
            return Outcome(issue.number, branch, False)
        log.info("#%d: agent run finished in %.0fs — delivering", issue.number,
                 time.monotonic() - t0)
        out = deliver(cfg, forge, runtime.name, issue, branch, workdir, res.output)
        if out.pr:
            findings = review_pr(cfg, forge, runtime, out.pr, issue)
            if findings and cfg.pipeline.repair_rounds > 0:
                repair_pr(cfg, forge, runtime, out.pr, branch, workdir,
                          issue.title, issue.body, findings)
        return out
    finally:
        forge.finish_work(issue.number)


def rebase_stale(cfg: Config, forge: Forge) -> None:
    """Pipeline upkeep, not human work: rebase open devloop PRs onto the
    current default branch (silently when clean). On conflict, close the PR
    and mark the issue for rebuild — main moved under the work, and redoing
    agent labor is cheaper than spending human conflict resolution."""
    for pr in forge.open_devloop_prs():
        head = pr.head
        n = forge.issue_of_branch(head)
        if n is None:
            continue
        try:
            clean = forge.rebase_branch(head)
        except Exception as e:
            # infrastructure failure (transient network, git hiccup) — not a
            # conflict: never a reason to close a PR and destroy delivered
            # work. Skip the head loudly; the next sweep retries it.
            log.warning("rebase of %s failed (%s: %s) — skipping this sweep",
                        head, type(e).__name__, str(e)[:300])
            continue
        if clean:
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
            existing = forge.pr_for_branch(forge.branch_for(n))
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


def handle_merge(cfg: Config, forge: Forge, pr_number: int, head_branch: str) -> str | None:
    """A devloop PR was merged by a human: ledger the completion, close the
    issue. Same carve-out as close_pr — the merge IS the human's sanction;
    this fires only from a real forge merge event, never agent output.
    None = not a devloop PR (caller's YAML gate should already know)."""
    n = forge.issue_of_branch(head_branch)
    if n is None:
        return None
    ledger.merged(forge, n, pr_number)
    forge.complete_issue(n)
    return f"completed issue #{n}"


def run_once(cfg: Config, forge: Forge, runtime: AgentRuntime) -> list[Outcome]:
    sweep_t0 = time.monotonic()
    # Upkeep before slot math: rebase stale PRs; a conflict-closed PR frees a slot.
    rebase_stale(cfg, forge)
    candidates = next_builds(cfg, forge)
    if not candidates:
        log.info("sweep: nothing to build")
        return []

    def worker(issue: Issue) -> Outcome:
        try:
            return process_issue(cfg, forge, runtime, issue)
        except Exception as e:
            # One broken issue must not block the queue (head-of-line blocking
            # would retry it forever in watch mode and starve everything else).
            log.error("#%d: build crashed: %s", issue.number, e)
            return Outcome(issue.number, forge.branch_for(issue.number), False, False)

    out: list[Outcome] = []
    with ThreadPoolExecutor(max_workers=len(candidates)) as pool:
        for r in pool.map(worker, candidates):
            out.append(r)
    log.info("sweep done in %.0fs: %d started, %d shipped a PR, %d failed",
             time.monotonic() - sweep_t0, len(out),
             sum(1 for o in out if getattr(o, "pr", None)),
             sum(1 for o in out if not getattr(o, "agent_ok", True)))
    return out
