"""Delivery: gate the work, ship it as a PR, or tell the issue why not.

One interface function: deliver(). Every rule about how finished agent work
becomes a PR — the verify gate, commit, half-delivery heal, the delivery
conflict gate, self-delivery bookkeeping, the PR body — lives behind it.
Never raises: every failure path posts its own ledger comment and returns
an Outcome, so a silent delivery failure is a bug in one place, not a
forgotten except clause in a caller.
"""

from __future__ import annotations

import subprocess  # only run_verify — all git goes through the Forge seam
from dataclasses import dataclass

from . import ledger
from .config import Config
from .forge import Forge, Issue
from .runtime import AgentRuntime


@dataclass
class Outcome:
    issue: int
    branch: str
    agent_ok: bool
    gate_ok: bool = True
    pr: int | None = None  # None = nothing shipped (failed, empty, or deferred)


def run_verify(verify_cmd: str, workdir: str = ".") -> bool:
    """Runs in the build's worktree — the gate judges what will be delivered,
    not the (possibly older) default checkout."""
    r = subprocess.run(verify_cmd, shell=True, capture_output=True, text=True, cwd=workdir)
    return r.returncode == 0


def deliver(cfg: Config, forge: Forge, runtime: AgentRuntime, issue: Issue,
            branch: str, workdir: str, agent_output: str) -> Outcome:
    """Ship one finished agent run. The agent already succeeded (res.ok);
    everything from here to PR-or-ledger-comment is delivery."""
    kind = cfg.kind_for(issue.labels)
    gate_ok = True
    try:
        if cfg.pipeline.verify:
            gate_ok = run_verify(cfg.pipeline.verify, workdir)
        existing = forge.pr_for_branch(branch)
        # half-delivery rule lives behind the Forge seam: commit_all returns
        # True for staged, unpushed, or already-pushed-but-no-PR work.
        delivered = forge.commit_all(
            f"devloop({kind}): fixes #{issue.number} [agent: {runtime.name}]", workdir)
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
            conflicts = []
            for head in forge.open_pr_head_branches():
                if not head.startswith("devloop/") or head == branch:
                    continue
                other = forge.pr_for_branch(head)
                if other and touched & set(forge.pr_files(other)):
                    conflicts.append(f"#{other} ({head})")
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
                    f"- agent: `{runtime.name}`\n"
                    f"- gate: {'PASS' if gate_ok else 'FAIL'}"
                    + (f" (`{cfg.pipeline.verify}`)" if cfg.pipeline.verify else " (none configured)")
                    + "\n\nHuman merge required — agents never merge."
                    + "\n\n## Agent report\n\n" + agent_output[-4000:].strip()
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
