"""Orchestrator: trigger → agent job → verify gate → PR. Pure logic + one loop."""

from __future__ import annotations

import subprocess
import re
import shutil
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

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


def run_verify(verify_cmd: str, workdir: str = ".") -> bool:
    """Runs in the build's worktree — the gate judges what will be delivered,
    not the (possibly older) default checkout."""
    r = subprocess.run(verify_cmd, shell=True, capture_output=True, text=True, cwd=workdir)
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


def process_issue(cfg: Config, forge: Forge, runtime: AgentRuntime, issue: Issue,
                  workdir: str = ".") -> Outcome:
    kind = cfg.kind_for(issue.labels)  # raises if triggers are not exclusive
    branch = f"devloop/issue-{issue.number}"
    forge.start_work(issue.number, branch, workdir)
    res = None
    try:
        res = runtime.run(PROMPTS[kind].format(n=issue.number, title=issue.title, body=issue.body),
                          cwd=workdir, timeout=cfg.pipeline.timeout)
    except Exception as e:
        # Timeout/explosion mid-run: no delivery, but the human must know.
        forge.comment(issue.number,
                      f"agent run FAILED ({type(e).__name__}) — no PR opened. tail:\n"
                      f"```\n{str(e)[-800:]}\n```")
        return Outcome(issue.number, branch, False, False)
    if not res.ok:
        # A failed agent run must not ship: no commit, no gate, no PR — the
        # error tail goes to the issue for the human, the branch stays local.
        forge.comment(issue.number,
                      f"agent run FAILED — no PR opened. tail:\n```\n{res.output[-800:]}\n```")
        return Outcome(issue.number, branch, False, False)
    gate_ok = True
    try:
        if cfg.pipeline.verify:
            gate_ok = run_verify(cfg.pipeline.verify, workdir)
        existing = forge.pr_for_branch(branch)
        delivered = forge.commit_all(
            f"devloop({kind}): fixes #{issue.number} [agent: {runtime.name}]", workdir)
        if not delivered and not existing:
            # nothing staged and nothing unpushed — but the agent may have
            # pushed the branch itself without opening a PR (half-delivery):
            # if the branch is ahead of main, deliver it by opening the PR.
            ahead = subprocess.run(["git", "rev-list", "--count", "origin/HEAD..HEAD"],
                                   capture_output=True, text=True, cwd=workdir)
            delivered = ahead.returncode == 0 and ahead.stdout.strip() not in {"", "0"}
        if not existing and not delivered:
            # No diff AND no PR — nothing delivered. The agent said something —
            # that's the finding (question, verdict, or stall); surface it.
            forge.comment(issue.number,
                          f"agent made NO changes — no PR opened. agent output tail:\n"
                          f"```\n{res.output[-1200:]}\n```")
            return Outcome(issue.number, branch, False, False)
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
                forge.comment(issue.number,
                              f"build deferred — branch `{branch}` touches files also "
                              f"touched by open devloop PR(s) {', '.join(conflicts)}; "
                              "will retry on a later sweep after they merge")
                return Outcome(issue.number, branch, False, False)
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
                    + "\n\n## Agent report\n\n" + res.output[-4000:].strip()
                ),
            )
            forge.comment(issue.number, f"Work delivered on `{branch}` — gate {'PASS' if gate_ok else 'FAIL'}.")
        pr_num = existing or forge.pr_for_branch(branch)
        review_pr(cfg, forge, runtime, pr_num, branch,
                  issue_title=issue.title, issue_body=issue.body)
    except Exception as e:
        # Delivery-stage failure (gate, commit, PR creation): the agent did
        # its work but the pipeline could not ship it — tell the human here,
        # not just on the runner's stderr.
        forge.comment(issue.number,
                      f"delivery FAILED ({type(e).__name__}) — no PR opened. tail:\n"
                      f"```\n{str(e)[-800:]}\n```")
        return Outcome(issue.number, branch, False, False)
    return Outcome(issue.number, branch, res.ok, gate_ok)


REVIEW_PROMPT = (
    "You are reviewing a pull request authored by another AI agent. Review "
    "the diff below against the spec issue below it: correctness, scope creep "
    "(changes the issue never asked for), repo-convention violations "
    "(AGENTS.md), and missing tests. Do NOT make changes.\n\n"
    "Output format: the single word `LGTM` if the PR is ready for human "
    "review, otherwise a numbered findings list — each finding as "
    "`file:line — severity (P0/P1/P2) — one-paragraph rationale`.\n\n"
    "## The spec issue\n## {issue_title}\n{issue_body}\n\n"
    "## The diff\n```diff\n{diff}\n```"
)


def review_prompt(cfg: Config, issue_title: str = "", issue_body: str = "") -> str:
    """Fully substituted review prompt: base template + repo-specific
    guidance from skills/pre-review/SKILL.md (the customization point) +
    the spec issue. Substitution is replace-based, not .format — injected
    content (issue bodies, diffs) may contain braces."""
    p = Path("skills/pre-review/SKILL.md")
    prompt = REVIEW_PROMPT + "\n\n## Repo-specific review guidance\n" + p.read_text() if p.exists() else REVIEW_PROMPT
    return (prompt
            .replace("{issue_title}", issue_title)
            .replace("{issue_body}", issue_body)
            .replace("{diff}", ""))


def review_pr(cfg: Config, forge: Forge, runtime: AgentRuntime, pr_number: int,
              branch: str = "", issue_title: str = "", issue_body: str = "") -> None:
    """AI pre-review rounds (pipeline.review_rounds) on one PR. Findings only
    — no auto-fix: a human reads them on the PR. Stops early on LGTM.
    branch = head branch when known (build flow); empty = review-by-number
    (`devloop review <pr>`), diff fetched from the forge.
    issue_title/issue_body: the spec the diff is judged against (the builder
    flow has it; review-by-number parses `Closes #N` from the PR body)."""
    if not issue_title:
        body = forge.pr_body(pr_number)
        m = re.search(r"[Cc]loses #(\d+)", body)
        if m:
            it = forge.issue(int(m.group(1)))
            issue_title, issue_body = it.title, it.body
    prompt = review_prompt(cfg, issue_title, issue_body)
    for rnd in range(1, cfg.pipeline.review_rounds + 1):
        # diff straight from the forge — GitHub computes it authoritatively;
        # local origin/HEAD-based diffs proved unreliable mid-build
        diff = forge.pr_diff_by_number(pr_number)
        res = runtime.run(prompt.replace("{diff}", diff[:40000]),
                          cwd=".", timeout=cfg.pipeline.timeout)
        if not res.ok:
            forge.pr_comment(pr_number, f"AI pre-review round {rnd}: reviewer run failed.")
            return
        forge.pr_comment(pr_number, f"**AI pre-review, round {rnd}/{cfg.pipeline.review_rounds}**\n\n"
                                 + res.output.strip()[-4000:])
        if "LGTM" in res.output[-200:].upper():
            return


FAILURE_MARKERS = (
    "agent run FAILED", "agent made NO changes", "delivery FAILED",
    "build deferred",
)


def failure_count(forge: Forge, issue: Issue) -> int:
    """Past failed attempts, counted from the issue's own comment ledger —
    no extra state. Guards the scheduled sweeps against burning tokens on
    a poison task forever: after pipeline.max_attempts, a human re-labels.
    Deferrals count too — a build that keeps losing the conflict gate is
    re-running its agent each sweep; the cap bounds that spend."""
    return sum(1 for c in forge.comments(issue.number)
               if any(c.body.startswith(m) for m in FAILURE_MARKERS))


def run_once(cfg: Config, forge: Forge, runtime: AgentRuntime) -> list[Outcome]:
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
        if failure_count(forge, issue) >= cfg.pipeline.max_attempts:
            print(f"#{issue.number}: {failure_count(forge, issue)} failed attempts — "
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
    subprocess.run(["git", "worktree", "prune"], capture_output=True)
    return out
