"""The Sweep: one pass of `devloop once` — upkeep, then queued builds.

Selection policy lives in devloop/queue.py; the build flow it drives is
devloop/build.py (run_build + process_issue). This module owns only the
sweep: rebase upkeep of stale PRs, then start queued builds within the
parallelism budget."""

import logging
import time
from concurrent.futures import ThreadPoolExecutor

from . import ledger
from .build import run_build
from .config import Config
from .delivery import Outcome
from .forge import Forge, Issue
from .queue import next_builds

log = logging.getLogger(__name__)


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


def run_once(cfg: Config, forge: Forge, runtime, build=run_build) -> list[Outcome]:
    """One sweep: rebase-upkeep, then queued builds within the parallelism
    budget. `build` is the build step started per queued issue (default
    run_build) — tests inject a stub through this one argument."""
    sweep_t0 = time.monotonic()
    # Upkeep before slot math: rebase stale PRs; a conflict-closed PR frees a slot.
    rebase_stale(cfg, forge)
    candidates = next_builds(cfg, forge)
    if not candidates:
        log.info("sweep: nothing to build")
        return []

    def worker(issue: Issue):
        return build(cfg, forge, runtime, issue)

    out: list[Outcome] = []
    with ThreadPoolExecutor(max_workers=len(candidates)) as pool:
        for r in pool.map(worker, candidates):
            out.append(r)
    log.info("sweep done in %.0fs: %d started, %d shipped a PR, %d failed",
             time.monotonic() - sweep_t0, len(out),
             sum(1 for o in out if getattr(o, "pr", None)),
             sum(1 for o in out if not getattr(o, "agent_ok", True)))
    return out
