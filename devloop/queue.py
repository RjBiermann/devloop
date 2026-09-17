"""Build queue: which issues may start a build this sweep.

Selection policy lives here, not in the sweep driver: slot math, the
delivered-set, both attempt budgets (max_attempts, max_per_day), and the
loud queue-full report. Budgets read the Ledger protocol (devloop/ledger.py);
the driver (devloop/core.py) only rebase-upkeeps, then drives what this
returns. The interface is the test surface — caps are probed through
next_builds(), no agent, no thread pool.
"""

import sys

from . import ledger
from .config import Config
from .forge import Forge, Issue


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
        print(f"queue full: {len(prs)} build(s) in flight "
              f"({', '.join(p.head for p in prs)}); nothing started — "
              "merge/close the open devloop PR(s) or raise pipeline.max_parallel",
              file=sys.stderr)
        return []
    delivered = {p.head for p in prs}
    candidates = []
    for issue in forge.issues_with_labels(cfg.labels.triggers):
        if forge.branch_for(issue.number) in delivered:
            continue
        attempts, today = ledger.budget(forge, issue)
        if attempts >= cfg.pipeline.max_attempts:
            print(f"#{issue.number}: {attempts} failed attempts — "
                  "skipped; re-label to retry", file=sys.stderr)
            continue
        if cfg.pipeline.max_per_day and today >= cfg.pipeline.max_per_day:
            print(f"#{issue.number}: daily cap reached ({cfg.pipeline.max_per_day}) — "
                  "skipped until tomorrow", file=sys.stderr)
            continue
        candidates.append(issue)
        if len(candidates) >= slots:
            break
    return candidates
