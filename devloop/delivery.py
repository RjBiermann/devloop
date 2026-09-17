"""Delivery: gate the work, ship it as a PR, or tell the issue why not.

One interface function: deliver(). Every rule about how finished agent work
becomes a PR — the verify gate (owned by devloop/gate.py), commit,
half-delivery heal, the delivery conflict gate, self-delivery bookkeeping,
the PR body — lives behind it. Never raises: every failure path posts its
own ledger comment and returns an Outcome, so a silent delivery failure is
a bug in one place, not a forgotten except clause in a caller.
"""

from dataclasses import dataclass

from . import ledger
from .config import Config
from .forge import Forge, Issue
from .gate import run_gate
from .runtime import TAIL


@dataclass
class Outcome:
    issue: int
    branch: str
    agent_ok: bool
    gate_ok: bool = True
    pr: int | None = None  # None = nothing shipped (failed, empty, or deferred)


def deliver(cfg: Config, forge: Forge, agent_name: str, issue: Issue,
            branch: str, workdir: str, agent_output: str) -> Outcome:
    """Ship one finished agent run. The agent already succeeded (res.ok);
    everything from here to PR-or-ledger-comment is delivery."""
    kind = cfg.kind_for(issue.labels)
    gate_ok = True
    if cfg.pipeline.verify:
        # runs in the build's worktree — the gate judges what will be
        # delivered, not the (possibly older) default checkout; the gate
        # module owns the policy (timeout, PASS semantics)
        gate_ok = run_gate(cfg.pipeline.verify, workdir, cfg.pipeline.timeout)
    try:
        existing = forge.pr_for_branch(branch)
        # half-delivery rule lives behind the Forge seam: commit_all returns
        # True for staged, unpushed, or already-pushed-but-no-PR work.
        delivered = forge.commit_all(
            f"devloop({kind}): fixes #{issue.number} [agent: {agent_name}]", workdir)
        if not existing and not delivered:
            # No diff AND no PR — nothing delivered. The agent said something —
            # that's the finding (question, verdict, or stall); surface it.
            ledger.failure(forge, issue, "no-changes",
                           note="no PR opened — agent output tail", tail=agent_output)
            return Outcome(issue.number, branch, True, gate_ok)
        if not existing:
            # delivery conflict gate: the build's scope is only knowable now —
            # if its files overlap an open devloop PR, park the branch (work is
            # pushed) and retry after the other PR merges; opening both would
            # create a merge conflict a human has to untangle.
            touched = set(forge.branch_files(branch))
            conflicts = [
                f"#{p.number} ({p.head})"
                for p in forge.open_devloop_prs()
                if p.head != branch and touched & set(p.files)
            ]
            if conflicts:
                ledger.failure(forge, issue, "deferred",
                               note=f"branch `{branch}` touches files also touched by "
                                    f"open devloop PR(s) {', '.join(conflicts)}; "
                                    "will retry on a later sweep after they merge")
                return Outcome(issue.number, branch, True, gate_ok)
        if existing:
            # Agent self-delivered (own commit, push, PR). Honor it: gate already
            # ran above; skip open_pr, correct the bookkeeping.
            forge.comment(issue.number,
                          f"Work delivered on `{branch}` — gate "
                          f"{'PASS' if gate_ok else 'FAIL'}. (agent self-delivered #{existing})")
        else:
            forge.open_pr(
                branch,
                title=f"devloop({kind}): {issue.title} (#{issue.number})",
                body=(
                    f"Closes #{issue.number}\n\n"
                    f"- agent: `{agent_name}`\n"
                    f"- gate: {'PASS' if gate_ok else 'FAIL'}"
                    + (f" (`{cfg.pipeline.verify}`)" if cfg.pipeline.verify else " (none configured)")
                    + "\n\nHuman merge required — agents never merge."
                    + "\n\n## Agent report\n\n" + agent_output[-TAIL:].strip()
                ),
            )
            forge.comment(issue.number, f"Work delivered on `{branch}` — gate {'PASS' if gate_ok else 'FAIL'}.")
        return Outcome(issue.number, branch, True, gate_ok,
                       existing or forge.pr_for_branch(branch))
    except Exception as e:
        # Delivery-stage failure (gate, commit, PR creation): the agent did
        # its work but the pipeline could not ship it — tell the human here,
        # not just on the runner's stderr.
        ledger.failure(forge, issue, "delivery", note=f"no PR opened ({type(e).__name__})", tail=str(e))
        return Outcome(issue.number, branch, True, gate_ok)
