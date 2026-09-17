"""Build queue: which issues may start a build this sweep.

Selection policy lives here, not in the sweep driver: slot math, the
delivered-set, both attempt budgets (max_attempts, max_per_day), and the
loud queue-full report. Budgets read the Ledger protocol (devloop/ledger.py);
the driver (devloop/core.py) only rebase-upkeeps, then drives what this
returns. The interface is the test surface — caps are probed through
next_builds(), no agent, no thread pool.

Every skip decision is logged here, at the point the reason is known —
run_once's summary counts outcomes, this is the why-not trace.
"""

import logging

from . import ledger
from .config import Config
from .forge import Forge, Issue

log = logging.getLogger(__name__)


def status_lines(cfg: Config, forge: Forge) -> list[str]:
    """Read-only queue preview for `devloop status` — the same decisions
    next_builds() makes, reported instead of executed. No forge writes,
    no agent runs."""
    log.info("status: forge %s", cfg.repo)
    prs = forge.open_devloop_prs()
    lines = [f"open devloop PRs: {len(prs)}"]
    for p in prs:
        lines.append(f"  #{p.number} {p.head}")
    slots = cfg.pipeline.max_parallel - len(prs)
    if slots <= 0:
        lines.append("queue full — merge/close an open devloop PR or raise "
                     "pipeline.max_parallel")
        return lines
    lines.append(f"free build slots: {slots}/{cfg.pipeline.max_parallel}")
    lines.append("would start now:")
    started = False
    for issue in forge.issues_with_labels(cfg.labels.triggers):
        if forge.branch_for(issue.number) in {p.head for p in prs}:
            lines.append(f"  #{issue.number} {issue.title} — already delivered")
            continue
        attempts, today = ledger.budget(forge, issue)
        if attempts >= cfg.pipeline.max_attempts:
            lines.append(f"  #{issue.number} {issue.title} — budget exhausted "
                         f"({attempts}/{cfg.pipeline.max_attempts}), re-label or /retry")
            continue
        if cfg.pipeline.max_per_day and today >= cfg.pipeline.max_per_day:
            lines.append(f"  #{issue.number} {issue.title} — daily cap reached "
                         f"({today}/{cfg.pipeline.max_per_day})")
            continue
        lines.append(f"  #{issue.number} {issue.title} — WOULD START (attempt "
                     f"{attempts + 1}/{cfg.pipeline.max_attempts})")
        started = True
    if not started:
        lines[-1] = "would start now: nothing"
    return lines


def next_builds(cfg: Config, forge: Forge) -> list[Issue]:
    """Issues whose builds may start now, within the parallelism budget.
    Two layers of conflict prevention:
      1. skip issues that already have a devloop PR — never rebuild delivered work
      2. never exceed max_parallel in-flight builds; builds themselves get a
         per-PR conflict gate at delivery (files overlapping an open devloop
         PR defer instead of opening a conflicting PR)"""
    prs = forge.open_devloop_prs()
    slots = cfg.pipeline.max_parallel - len(prs)
    if slots <= 0:
        # Queue full — say so, loudly. Silent green no-ops are the worst
        # failure mode a pipeline can have (the human believes it ran).
        log.warning("queue full: %d build(s) in flight (%s); nothing started — "
                    "merge/close the open devloop PR(s) or raise pipeline.max_parallel",
                    len(prs), ', '.join(p.head for p in prs))
        return []
    delivered = {p.head for p in prs}
    candidates = []
    for issue in forge.issues_with_labels(cfg.labels.triggers):
        if forge.branch_for(issue.number) in delivered:
            log.info("#%d: skipped — already delivered (%s open)", issue.number,
                     forge.branch_for(issue.number))
            continue
        attempts, today = ledger.budget(forge, issue)
        if attempts >= cfg.pipeline.max_attempts:
            log.warning("#%d: %d failed attempts — skipped; re-label to retry",
                        issue.number, attempts)
            continue
        if cfg.pipeline.max_per_day and today >= cfg.pipeline.max_per_day:
            log.warning("#%d: daily cap reached (%d) — skipped until tomorrow",
                        issue.number, cfg.pipeline.max_per_day)
            continue
        log.info("#%d: starting build (attempt %d/%d)", issue.number,
                 attempts + 1, cfg.pipeline.max_attempts)
        candidates.append(issue)
        if len(candidates) >= slots:
            break
    return candidates
