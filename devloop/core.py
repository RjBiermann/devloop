"""Orchestrator: trigger → agent job → verify gate → PR. Pure logic + one loop."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass

from .config import Config
from .forge import Forge, Issue
from .runtime import AgentRuntime

# Per trigger kind: what the agent is asked to do. Skills carry the how.
PROMPTS = {
    "fix": "A reported problem exists in this repo (issue below). Probe reality first, "
           "record evidence in FINDINGS.md, then make the minimal fix, and follow the "
           "verify skill. Do not merge; leave the work committed for human review.\n\n"
           "## Issue #{n}: {title}\n{body}",
    "new": "Build the unit of work described in this issue. Read any spec carefully, "
           "probe what's needed first (probe skill), implement test-first where the "
           "spec implies it, and follow the verify skill. Do not merge.\n\n"
           "## Issue #{n}: {title}\n{body}",
    "remove": "Remove the component named in this issue. First gather evidence it is "
              "dead/broken (probe skill), put the evidence in FINDINGS.md, then remove "
              "the component and anything only it referenced. Do not merge.\n\n"
              "## Issue #{n}: {title}\n{body}",
    "task": "Execute the task specified in this issue body — it is the full spec. "
            "Do exactly what it says, no more: do not expand scope, do not fix "
            "unrelated things you notice (list them as notes in the PR body "
            "instead). Follow repo conventions (AGENTS.md). Do not merge.\n\n"
            "## Issue #{n}: {title}\n{body}",
}


@dataclass
class Outcome:
    issue: int
    branch: str
    agent_ok: bool
    gate_ok: bool


def run_verify(verify_cmd: str) -> bool:
    r = subprocess.run(verify_cmd, shell=True, capture_output=True, text=True)
    return r.returncode == 0


# --- spec loop: draft → clarify ↔ human → propose → approved → finalized ----

MARKER = "devloop: status="


def parse_status(text: str) -> str | None:
    """Extract the last devloop status marker from a comment body."""
    found = None
    for line in text.splitlines():
        if line.strip().startswith(MARKER):
            found = line.strip()[len(MARKER):].split()[0].rstrip(".`")
    return found


SPEC_PHASES = ("clarify", "propose", "finalized")


# Instructions appended to the agent prompt per spec phase. The agent decides
# whether to advance; the human decides whether a proposal becomes final.
SPEC_INSTRUCTIONS = {
    "clarify":
        "Follow the clarify skill: interrogate this spec draft for ambiguity, "
        "ask at most 3 questions per round with your proposed defaults, and post "
        "them as ONE issue comment ending with `devloop: status=clarify`. If no "
        "ambiguity remains that would change what gets built, instead write the "
        "decision record and post it ending with `devloop: status=propose`.",
    "propose":
        "The human has answered the clarify round. Apply their answers to the "
        "decision record, then follow the decompose skill: propose the epic/"
        "story/sub-issue breakdown as ONE issue comment ending with "
        "`devloop: status=propose`. The human will reply `approved` if they "
        "accept it.",
    "finalized":
        "The human approved the breakdown. Follow the decompose skill's "
        "finalize step: create one issue per story/sub-issue (acceptance "
        "condition in each body, NO labels — the human labels what to build), "
        "rewrite this issue's body into the finalized spec (intent + decision "
        "record + task tree with issue links), and post a summary ending with "
        "`devloop: status=finalized`.",
}


def spec_phase(comments, forge: Forge, access) -> str:
    """Current spec state = last marker posted by us, unless an AUTHORIZED
    human has replied `approved` after a proposal (→ finalized). Pure: takes
    comments; only authorized authors' approvals count (AI tokens cost money
    — strangers don't get to fire the pipeline)."""
    status = "clarify"
    for c in comments:
        s = parse_status(c.body)
        if s in SPEC_PHASES:
            status = s
    if status == "propose" and any(
        c.body.strip().lower() in {"approved", "approved."}
        and forge.is_authorized(c.author, access)
        for c in comments
    ):
        return "finalized"
    return status


def process_spec(cfg: Config, forge: Forge, runtime: AgentRuntime, number: int) -> str:
    """One round of the spec loop. Returns the phase after this round."""
    comments = forge.comments(number)
    phase = spec_phase(comments, forge, cfg.access)
    if phase == "finalized":
        return phase  # terminal: sub-issues exist, spec rewritten — nothing to redo
    issue = forge.issue(number)
    prompt = (
        f"You are refining a spec for issue #{number}. Do NOT write code.\n\n"
        f"## Issue #{number}: {issue.title}\n{issue.body}\n\n"
        f"## Conversation so far\n" + "\n---\n".join(c.body for c in comments) + "\n\n"
        + SPEC_INSTRUCTIONS[phase]
    )
    res = runtime.run(prompt, cwd=".", timeout=cfg.pipeline.timeout)
    forge.comment(number, res.output.strip())
    return parse_status(res.output) or phase


def process_issue(cfg: Config, forge: Forge, runtime: AgentRuntime, issue: Issue) -> Outcome:
    kind = cfg.kind_for(issue.labels)  # raises if triggers are not exclusive
    branch = f"devloop/issue-{issue.number}"
    forge.start_work(issue.number, branch)
    res = runtime.run(PROMPTS[kind].format(n=issue.number, title=issue.title, body=issue.body),
                      cwd=".", timeout=cfg.pipeline.timeout)
    if not res.ok:
        # A failed agent run must not ship: no commit, no gate, no PR — the
        # error tail goes to the issue for the human, the branch stays local.
        forge.comment(issue.number,
                      f"agent run FAILED — no PR opened. tail:\n```\n{res.output[-800:]}\n```")
        return Outcome(issue.number, branch, False, False)
    gate_ok = True
    if cfg.pipeline.verify:
        gate_ok = run_verify(cfg.pipeline.verify)
    forge.commit_all(f"devloop({kind}): fixes #{issue.number} [agent: {runtime.name}]")
    forge.open_pr(
        branch,
        title=f"devloop({kind}): {issue.title} (#{issue.number})",
        body=(
            f"Closes #{issue.number}\n\n"
            f"- agent: `{runtime.name}`\n"
            f"- gate: {'PASS' if gate_ok else 'FAIL'}"
            + (f" (`{cfg.pipeline.verify}`)" if cfg.pipeline.verify else " (none configured)")
            + "\n\nHuman merge required — agents never merge."
        ),
    )
    forge.comment(issue.number, f"Work delivered on `{branch}` — gate {'PASS' if gate_ok else 'FAIL'}.")
    return Outcome(issue.number, branch, res.ok, gate_ok)


def run_once(cfg: Config, forge: Forge, runtime: AgentRuntime) -> list[Outcome]:
    open_heads = forge.open_pr_head_branches()
    devloop_heads = [h for h in open_heads if h.startswith("devloop/")]
    # Two layers of conflict prevention:
    #   1. skip issues that already have a devloop PR — never rebuild delivered work
    #   2. never exceed max_parallel in-flight builds — overlapping touch-sets
    #      can only conflict, so by default builds run serially (partition skill
    #      designs touch-sets disjoint; raising max_parallel is a deliberate
    #      throughput choice backed by that discipline)
    if len(devloop_heads) >= cfg.pipeline.max_parallel:
        # Queue full — say so, loudly. Silent green no-ops are the worst
        # failure mode a pipeline can have (the human believes it ran).
        print(f"queue full: {len(devloop_heads)} build(s) in flight "
              f"({', '.join(devloop_heads)}); nothing started — "
              "merge/close the open devloop PR(s) or raise pipeline.max_parallel",
              file=sys.stderr)
        return []
    delivered = set(open_heads)
    out = []
    for issue in forge.issues_with_labels(cfg.labels.triggers):
        if f"devloop/issue-{issue.number}" in delivered:
            continue
        try:
            out.append(process_issue(cfg, forge, runtime, issue))
        except Exception as e:
            # One broken issue must not block the queue (head-of-line blocking
            # would retry it forever in watch mode and starve everything else).
            out.append(Outcome(issue.number, f"devloop/issue-{issue.number}", False, False))
            print(f"#{issue.number}: failed: {e}", file=sys.stderr)
        if len(out) >= cfg.pipeline.max_parallel - len(devloop_heads):
            break
    return out
